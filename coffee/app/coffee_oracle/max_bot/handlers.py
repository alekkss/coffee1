"""Обработчики событий MAX-бота.

Содержит логику реакции на все типы входящих событий:
текстовые сообщения, фотографии, callback от кнопок.
Включает систему подписок и платежей через YooKassa.
Аналог bot/handlers.py для мессенджера MAX.
"""

import asyncio
import logging
import re
import random
import os
from typing import Any, Dict, List, Optional

from coffee_oracle.bot import texts
from coffee_oracle.config import config
from coffee_oracle.database.connection import db_manager
from coffee_oracle.database.repositories import (
    PartnerRepository,
    PredictionRepository,
    ReminderRepository,
    SettingsRepository,
    SubscriptionRepository,
    UserRepository,
)
from coffee_oracle.max_bot.api_client import (
    MaxApiClient,
    MaxCallback,
    MaxMessage,
    MaxUpdate,
    MaxUser,
)
from coffee_oracle.max_bot.keyboards import MaxKeyboardManager
from coffee_oracle.max_bot.photo_processor import MaxPhotoProcessor
from coffee_oracle.utils.errors import OpenAIError, PhotoProcessingError, format_error_message

logger = logging.getLogger(__name__)

# Идентификатор платформы для всех операций с БД в MAX-боте
_SOURCE = "max"

# Регулярное выражение для валидации email
_EMAIL_RE = re.compile(r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$")


# ────────────────────────────────────────────
#  In-memory FSM для MAX-бота
# ────────────────────────────────────────────

class _UserStateManager:
    """Менеджер состояний пользователей для MAX-бота.

    Простая замена aiogram FSM — хранит состояния в памяти.
    При перезапуске бота состояния сбрасываются, что допустимо:
    пользователь просто начнёт процесс оплаты заново.
    """

    def __init__(self) -> None:
        self._states: Dict[int, Dict[str, Any]] = {}

    def set_state(self, user_id: int, state: str, **data: Any) -> None:
        """Установка состояния пользователя.

        Args:
            user_id: ID пользователя на платформе MAX.
            state: Название состояния (например, 'waiting_for_email').
            **data: Дополнительные данные (chat_id и т.д.).
        """
        self._states[user_id] = {"state": state, **data}

    def get_state(self, user_id: int) -> Optional[Dict[str, Any]]:
        """Получение текущего состояния пользователя.

        Args:
            user_id: ID пользователя на платформе MAX.

        Returns:
            Словарь с состоянием и данными, или None.
        """
        return self._states.get(user_id)

    def clear_state(self, user_id: int) -> None:
        """Сброс состояния пользователя.

        Args:
            user_id: ID пользователя на платформе MAX.
        """
        self._states.pop(user_id, None)

    def is_waiting_for_email(self, user_id: int) -> bool:
        """Проверка: ожидается ли ввод email от пользователя.

        Args:
            user_id: ID пользователя на платформе MAX.

        Returns:
            True, если пользователь в состоянии ввода email.
        """
        state_data = self._states.get(user_id)
        if state_data and state_data.get("state") == "waiting_for_email":
            return True
        return False


# Глобальный менеджер состояний (аналог FSM)
_state_manager = _UserStateManager()


# ────────────────────────────────────────────
#  Вспомогательные функции
# ────────────────────────────────────────────

async def _get_bot_text(key: str, default: str) -> str:
    """Получение текста из настроек бота или значения по умолчанию.

    Args:
        key: Ключ настройки.
        default: Значение по умолчанию.

    Returns:
        Текст из настроек или default.
    """
    try:
        async for session in db_manager.get_session():
            settings_repo = SettingsRepository(session)
            value = await settings_repo.get_setting(key)
            return value if value else default
    except Exception:
        return default


async def _get_or_create_user(
    max_user: MaxUser,
    referred_by_partner_id: Optional[int] = None,
) -> Any:
    """Получение или создание пользователя MAX в БД.

    Использует source='max' для разделения пространства ID
    с Telegram-пользователями.

    Args:
        max_user: Объект пользователя MAX.
        referred_by_partner_id: ID партнёра, по чьей ссылке пришёл пользователь.

    Returns:
        Объект User из базы данных.
    """
    async for session in db_manager.get_session():
        user_repo = UserRepository(session)

        db_user = await user_repo.get_user_by_telegram_id(
            max_user.user_id, source=_SOURCE,
        )
        if db_user:
            return db_user

        return await user_repo.create_user(
            telegram_id=max_user.user_id,
            username=max_user.username,
            full_name=max_user.full_name,
            source=_SOURCE,
            referred_by_partner_id=referred_by_partner_id,
        )


async def _process_referral(
    referral_code: str,
    user_id: int,
) -> Optional[int]:
    """Обработка реферального кода: запись перехода и получение ID партнёра.

    Записывает ReferralClick для каждого перехода (без дедупликации).
    Возвращает partner_id для привязки нового пользователя.

    Args:
        referral_code: Реферальный код из deep link (payload).
        user_id: ID пользователя на платформе MAX.

    Returns:
        ID партнёра или None, если код невалидный.
    """
    try:
        async for session in db_manager.get_session():
            partner_repo = PartnerRepository(session)

            partner = await partner_repo.get_partner_by_referral_code(referral_code)
            if not partner:
                logger.warning(
                    "MAX: неизвестный реферальный код '%s' от пользователя %d",
                    referral_code, user_id,
                )
                return None

            # Записываем переход (каждый переход отдельно)
            await partner_repo.record_click(
                partner_id=partner.id,
                telegram_id=user_id,
                source=_SOURCE,
            )

            logger.info(
                "MAX: реферальный переход записан: код='%s', partner_id=%d, user_id=%d",
                referral_code, partner.id, user_id,
            )
            return partner.id

    except Exception as e:
        logger.error(
            "MAX: ошибка обработки реферального кода '%s': %s",
            referral_code, e,
            exc_info=True,
        )
        return None


# ────────────────────────────────────────────
#  Background polling оплаты
# ────────────────────────────────────────────

async def _poll_payment_and_activate(
    api_client: MaxApiClient,
    chat_id: int,
    max_user_id: int,
    payment_id: str,
    processing_msg_id: Optional[str],
) -> None:
    """Фоновая задача: опрос YooKassa до завершения платежа.

    Аналог _poll_payment_and_activate из bot/handlers.py,
    но отправляет уведомления через MAX API.

    Args:
        api_client: HTTP-клиент MAX API.
        chat_id: ID чата для отправки уведомлений.
        max_user_id: ID пользователя на платформе MAX.
        payment_id: ID платежа в YooKassa.
        processing_msg_id: ID сообщения для редактирования (опционально).
    """
    from coffee_oracle.services.payment_service import get_payment_service

    payment_service = get_payment_service()
    if payment_service is None:
        return

    # Расписание polling: 15с, 30с, 60с, 120с (≈3.5 мин суммарно)
    delays = [15, 30, 60, 120]

    for delay in delays:
        await asyncio.sleep(delay)

        # Если пользователь уже подтвердил вручную, pending будет очищен
        if payment_service.get_pending_payment(max_user_id) != payment_id:
            return

        try:
            status_result = await payment_service.get_payment_status(payment_id)
        except Exception as exc:
            logger.warning(
                "MAX: ошибка фонового polling для платежа %s: %s",
                payment_id, exc,
            )
            continue

        if not status_result.get("success"):
            continue

        status = status_result.get("status")
        paid = status_result.get("paid", False)

        if status == "succeeded" and paid:
            # Активация подписки
            try:
                async for session in db_manager.get_session():
                    user_repo = UserRepository(session)
                    sub_repo = SubscriptionRepository(session)

                    db_user = await user_repo.get_user_by_telegram_id(
                        max_user_id, source=_SOURCE,
                    )
                    if not db_user:
                        return

                    await sub_repo.activate_premium(db_user.id)

                    payment_method_saved = status_result.get(
                        "payment_method_saved", False,
                    )
                    payment_method_id = status_result.get("payment_method_id")
                    if payment_method_saved and payment_method_id:
                        await sub_repo.enable_recurring_payment(
                            db_user.id, payment_method_id,
                        )

                    await sub_repo.update_payment_status(payment_id, "succeeded")

                payment_service.clear_pending_payment(max_user_id)

                recurring_enabled = bool(
                    status_result.get("payment_method_saved")
                    and status_result.get("payment_method_id")
                )
                success_text = (
                    texts.PAYMENT_SUCCESS_RECURRING if recurring_enabled
                    else texts.PAYMENT_SUCCESS
                )

                keyboard = MaxKeyboardManager.get_subscription_status_keyboard(
                    has_active_subscription=True,
                    recurring_enabled=recurring_enabled,
                )

                # Пробуем отредактировать, иначе — новое сообщение
                if processing_msg_id:
                    try:
                        await api_client.edit_message(
                            message_id=processing_msg_id,
                            text=success_text,
                            attachments=[keyboard],
                        )
                        return
                    except Exception:
                        pass

                await api_client.send_message(
                    chat_id=chat_id,
                    text=success_text,
                    attachments=[keyboard],
                )

            except Exception as exc:
                logger.error(
                    "MAX: ошибка активации подписки при polling: %s",
                    exc, exc_info=True,
                )
            return

        if status == "canceled":
            try:
                async for session in db_manager.get_session():
                    sub_repo = SubscriptionRepository(session)
                    await sub_repo.update_payment_status(payment_id, "canceled")

                payment_service.clear_pending_payment(max_user_id)

                keyboard = MaxKeyboardManager.get_subscription_status_keyboard(
                    has_active_subscription=False,
                )

                if processing_msg_id:
                    try:
                        await api_client.edit_message(
                            message_id=processing_msg_id,
                            text=texts.PAYMENT_CANCELLED,
                            attachments=[keyboard],
                        )
                        return
                    except Exception:
                        pass

                await api_client.send_message(
                    chat_id=chat_id,
                    text=texts.PAYMENT_CANCELLED,
                    attachments=[keyboard],
                )

            except Exception as exc:
                logger.error(
                    "MAX: ошибка обработки отмены при polling: %s",
                    exc, exc_info=True,
                )
            return

    # Все попытки исчерпаны — платёж всё ещё pending
    logger.info(
        "MAX: фоновый polling исчерпан для платежа %s, пользователь %d",
        payment_id, max_user_id,
    )


# ────────────────────────────────────────────
#  Основной класс обработчиков
# ────────────────────────────────────────────

class MaxBotHandlers:
    """Обработчики событий MAX-бота.

    Маршрутизирует входящие обновления к соответствующим
    методам-обработчикам. Управляет взаимодействием между
    MAX API клиентом, обработчиком фото и базой данных.
    Включает систему подписок и платежей через YooKassa.

    Args:
        api_client: HTTP-клиент MAX API.
        photo_processor: Обработчик фотографий для MAX.
    """

    def __init__(
        self,
        api_client: MaxApiClient,
        photo_processor: MaxPhotoProcessor,
    ):
        self._api = api_client
        self._photo = photo_processor

    # ────────────────────────────────────────────
    #  Главный маршрутизатор
    # ────────────────────────────────────────────

    async def handle_update(self, update: MaxUpdate) -> None:
        """Главный маршрутизатор обновлений.

        Определяет тип события и вызывает соответствующий обработчик.

        Args:
            update: Объект обновления из MAX API.
        """
        try:
            if update.update_type == "bot_started":
                await self._handle_bot_started(update)

            elif update.update_type == "message_created":
                await self._handle_message_created(update)

            elif update.update_type == "message_callback":
                await self._handle_callback(update)

            else:
                logger.debug("Неизвестный тип обновления MAX: %s", update.update_type)

        except Exception as e:
            logger.error(
                "Ошибка обработки обновления MAX (тип=%s): %s",
                update.update_type, e,
                exc_info=True,
            )

    # ────────────────────────────────────────────
    #  bot_started — пользователь нажал «Начать»
    # ────────────────────────────────────────────

    async def _handle_bot_started(self, update: MaxUpdate) -> None:
        """Обработка события запуска бота пользователем.

        Если в payload присутствует реферальный код — записывает
        переход и привязывает нового пользователя к партнёру.

        Args:
            update: Обновление с типом bot_started.
        """
        user = update.user
        if not user:
            return

        logger.info("MAX: пользователь %d запустил бота", user.user_id)

        # Сбрасываем FSM-состояние при перезапуске бота
        _state_manager.clear_state(user.user_id)

        # Обработка реферального кода из payload
        referred_by_partner_id = None
        referral_code = update.payload

        if referral_code and referral_code.strip():
            referral_code = referral_code.strip()
            logger.info(
                "MAX: обнаружен реферальный код '%s' от пользователя %d",
                referral_code, user.user_id,
            )
            referred_by_partner_id = await _process_referral(
                referral_code=referral_code,
                user_id=user.user_id,
            )

        db_user = await _get_or_create_user(
            user,
            referred_by_partner_id=referred_by_partner_id,
        )

        welcome_template = await _get_bot_text(
            "welcome_message",
            texts.WELCOME_MESSAGE_FALLBACK,
        )

        welcome_text = welcome_template.replace("{name}", db_user.full_name)

        await self._api.send_message(
            user_id=user.user_id,
            text=welcome_text,
            attachments=[MaxKeyboardManager.get_main_menu_with_subscription()],
            format_type="html",
        )

    # ────────────────────────────────────────────
    #  message_created — новое сообщение
    # ────────────────────────────────────────────

    async def _handle_message_created(self, update: MaxUpdate) -> None:
        """Маршрутизация входящих сообщений.

        Определяет, содержит ли сообщение фото или текст,
        и передаёт в соответствующий обработчик.

        Args:
            update: Обновление с типом message_created.
        """
        message = update.message
        if not message or not message.sender:
            return

        # Игнорируем сообщения от ботов
        if message.sender.is_bot:
            return

        # Определяем chat_id для ответа
        chat_id = message.chat_id
        if not chat_id:
            return

        # Проверяем наличие фото
        if self._photo.has_photos(message):
            await self._handle_photo_message(message, chat_id)
            return

        # Обработка текстовых сообщений
        text = message.text
        if text:
            await self._handle_text_message(text.strip(), message, chat_id)
            return

        # Неизвестный тип контента
        await self._api.send_message(
            chat_id=chat_id,
            text=texts.UNKNOWN_CONTENT_TYPE,
            attachments=[MaxKeyboardManager.get_main_menu_with_subscription()],
            format_type="html",
        )

    # ────────────────────────────────────────────
    #  Текстовые сообщения
    # ────────────────────────────────────────────

    async def _handle_text_message(
        self,
        text: str,
        message: MaxMessage,
        chat_id: int,
    ) -> None:
        """Обработка текстового сообщения.

        Сначала проверяет, есть ли активное FSM-состояние
        (ожидание ввода email). Если да — обрабатывает ввод.
        Иначе — маршрутизация по командам и кнопкам.

        Args:
            text: Текст сообщения.
            message: Полное сообщение MAX.
            chat_id: ID чата для ответа.
        """
        user = message.sender
        if not user:
            return

        # Проверяем FSM: если ожидаем email — перехватываем ввод
        if _state_manager.is_waiting_for_email(user.user_id):
            await self._handle_email_input(text, user, chat_id)
            return

        # Обработка команд (начинаются с /)
        text_lower = text.lower()

        if text_lower == "/start":
            await self._handle_start_command(message, chat_id)
        elif text_lower == "/help":
            await self._handle_faq_command(chat_id)
        elif text_lower == "/predict":
            await self._handle_predict_command(chat_id)
        elif text_lower == "/history":
            await self._handle_history_command(message, chat_id)
        elif text_lower == "/random":
            await self._handle_random_command(chat_id)
        elif text_lower == "/about":
            await self._handle_about_command(chat_id)
        elif text_lower == "/clear":
            await self._handle_clear_command(chat_id)
        elif text_lower == "/support":
            await self._handle_support_command(chat_id)
        elif text_lower == "/subscribe":
            await self._handle_subscription_command(user, chat_id)
        else:
            # Произвольный текст — предложить меню
            await self._api.send_message(
                chat_id=chat_id,
                text=texts.UNKNOWN_TEXT_MESSAGE,
                attachments=[MaxKeyboardManager.get_main_menu_with_subscription()],
            )

    # ────────────────────────────────────────────
    #  Обработка ввода email (FSM)
    # ────────────────────────────────────────────

    async def _handle_email_input(
        self,
        text: str,
        user: MaxUser,
        chat_id: int,
    ) -> None:
        """Обработка ввода email для создания платежа.

        Вызывается, когда пользователь находится в состоянии
        waiting_for_email. Валидирует email и создаёт платёж.

        Args:
            text: Введённый текст (предполагаемый email).
            user: Объект пользователя MAX.
            chat_id: ID чата для ответа.
        """
        email = text.strip()

        if not _EMAIL_RE.match(email):
            await self._api.send_message(
                chat_id=chat_id,
                text=texts.EMAIL_INVALID,
                attachments=[MaxKeyboardManager.get_email_cancel_keyboard()],
            )
            return

        # Email валиден — сбрасываем состояние и создаём платёж
        _state_manager.clear_state(user.user_id)

        await self._api.send_message(
            chat_id=chat_id,
            text=texts.email_confirmed(email),
        )

        await self._create_payment_and_respond(
            chat_id=chat_id,
            max_user_id=user.user_id,
            user_email=email,
        )

    # ────────────────────────────────────────────
    #  Создание платежа и отправка ссылки
    # ────────────────────────────────────────────

    async def _create_payment_and_respond(
        self,
        chat_id: int,
        max_user_id: int,
        user_email: Optional[str],
    ) -> None:
        """Создание платежа в YooKassa и отправка ссылки на оплату.

        Args:
            chat_id: ID чата для ответа.
            max_user_id: ID пользователя на платформе MAX.
            user_email: Email для чека 54-ФЗ.
        """
        from coffee_oracle.services.payment_service import get_payment_service

        payment_service = get_payment_service()
        if payment_service is None:
            await self._api.send_message(
                chat_id=chat_id,
                text=texts.PAYMENT_UNAVAILABLE,
            )
            return

        async for session in db_manager.get_session():
            user_repo = UserRepository(session)
            settings_repo = SettingsRepository(session)
            sub_repo = SubscriptionRepository(session)

            db_user = await user_repo.get_user_by_telegram_id(
                max_user_id, source=_SOURCE,
            )
            if not db_user:
                await self._api.send_message(
                    chat_id=chat_id,
                    text=texts.USER_NOT_FOUND,
                )
                return

            # Сохраняем email для будущих рекуррентных платежей
            if user_email and db_user.email != user_email:
                db_user.email = user_email
                await session.commit()

            try:
                price_str = await settings_repo.get_setting("subscription_price")
                price = float(price_str) if price_str else 300.0
                price_kopecks = int(price * 100)

                result = await payment_service.create_first_payment(
                    amount=price_kopecks,
                    description=texts.SUBSCRIPTION_DESCRIPTION,
                    user_id=max_user_id,
                    user_email=user_email,
                    return_url=f"https://max.ru/{config.max_bot_id}" if config.max_bot_id else "https://max.ru",
                )

                if not result.get("success"):
                    error_msg = result.get("error", "Неизвестная ошибка")
                    logger.error(
                        "MAX: ошибка создания платежа YooKassa: %s",
                        error_msg,
                    )
                    await self._api.send_message(
                        chat_id=chat_id,
                        text=texts.PAYMENT_CREATE_ERROR,
                    )
                    return

                payment_id = result["payment_id"]
                confirmation_url = result["confirmation_url"]
                label = result["label"]
                is_recurring = result.get("recurring", False)

                # Сохраняем платёж в БД
                await sub_repo.create_payment(
                    user_id=db_user.id,
                    amount=price_kopecks,
                    label=label,
                    payment_id=payment_id,
                )

                # Запоминаем pending-платёж в памяти
                payment_service.set_pending_payment(max_user_id, payment_id)

                recurring_note = "" if is_recurring else texts.RECURRING_UNAVAILABLE_NOTE

                payment_text = texts.payment_link_text(
                    price, config.domain, recurring_note,
                )

                sent_msg = await self._api.send_message(
                    chat_id=chat_id,
                    text=payment_text,
                    attachments=[
                        MaxKeyboardManager.get_subscription_keyboard(
                            payment_url=confirmation_url,
                        ),
                    ],
                )

                # Запускаем фоновый polling статуса платежа
                asyncio.create_task(
                    _poll_payment_and_activate(
                        api_client=self._api,
                        chat_id=chat_id,
                        max_user_id=max_user_id,
                        payment_id=payment_id,
                        processing_msg_id=sent_msg.message_id,
                    )
                )

            except Exception as e:
                logger.error(
                    "MAX: непредвиденная ошибка в потоке оплаты: %s",
                    e, exc_info=True,
                )
                await self._api.send_message(
                    chat_id=chat_id,
                    text=texts.PAYMENT_UNEXPECTED_ERROR,
                )

    # ────────────────────────────────────────────
    #  Команды
    # ────────────────────────────────────────────

    async def _handle_start_command(self, message: MaxMessage, chat_id: int) -> None:
        """Обработка команды /start."""
        user = message.sender
        if not user:
            return

        # Сбрасываем FSM-состояние
        _state_manager.clear_state(user.user_id)

        db_user = await _get_or_create_user(user)

        welcome_template = await _get_bot_text(
            "welcome_message",
            texts.WELCOME_MESSAGE_FALLBACK,
        )

        welcome_text = welcome_template.replace("{name}", db_user.full_name)

        await self._api.send_message(
            chat_id=chat_id,
            text=welcome_text,
            attachments=[MaxKeyboardManager.get_main_menu_with_subscription()],
            format_type="html",
        )

    async def _handle_faq_command(self, chat_id: int) -> None:
        """Обработка команды /help и кнопки «FAQ» — показ FAQ напрямую."""
        faq_text = texts.HELP_SECTIONS.get("faq", "Информация не найдена")
        await self._api.send_message(
            chat_id=chat_id,
            text=faq_text,
            attachments=[MaxKeyboardManager.get_back_to_menu_button()],
        )

    async def _handle_predict_command(self, chat_id: int) -> None:
        """Обработка команды /predict."""
        instruction = await _get_bot_text(
            "photo_instruction",
            texts.PHOTO_INSTRUCTION_FALLBACK,
        )

        await self._api.send_message(
            chat_id=chat_id,
            text=instruction,
            attachments=[MaxKeyboardManager.get_back_to_menu_button()],
        )
    
    async def _handle_video_instruction(self, chat_id: int) -> None:
        """Обработка кнопки «Видеоинструкция» — отправка видео из локального файла.

        Если WELCOME_VIDEO_PATH задан в .env и файл существует — загружает видео
        через MAX API (трёхшаговый upload) и отправляет с подписью.
        Если видео не настроено или произошла ошибка — отправляет текстовый fallback.

        Args:
            chat_id: ID чата для ответа.
        """
        video_path = config.welcome_video_path

        if video_path and os.path.isfile(video_path):
            try:
                # Показываем индикатор отправки видео
                try:
                    await self._api.send_action(chat_id, "sending_video")
                except Exception:
                    pass

                await self._api.send_video_from_file(
                    file_path=video_path,
                    chat_id=chat_id,
                    text=texts.VIDEO_INSTRUCTION_CAPTION,
                )
                # После видео показываем кнопку возврата в меню
                await self._api.send_message(
                    chat_id=chat_id,
                    text=texts.BTN_BACK_SHORT,
                    attachments=[MaxKeyboardManager.get_back_to_menu_button()],
                )
                return

            except Exception as e:
                logger.error("MAX: ошибка отправки видеоинструкции: %s", e)

        # Fallback: видео не настроено, файл не найден или ошибка отправки
        if video_path:
            logger.warning(
                "MAX: видеоинструкция недоступна, путь: %s",
                video_path,
            )

        await self._api.send_message(
            chat_id=chat_id,
            text=texts.VIDEO_NOT_CONFIGURED,
            attachments=[MaxKeyboardManager.get_back_to_menu_button()],
        )

    async def _handle_history_command(self, message: MaxMessage, chat_id: int) -> None:
        """Обработка команды /history — показ частых запросов."""
        await self._api.send_message(
            chat_id=chat_id,
            text=texts.FREQUENT_QUERIES_TEXT,
            attachments=[MaxKeyboardManager.get_back_to_menu_button()],
        )

    async def _handle_random_command(self, chat_id: int) -> None:
        """Обработка команды /random."""
        prediction = random.choice(texts.RANDOM_PREDICTIONS)
        await self._api.send_message(
            chat_id=chat_id,
            text=f"{texts.RANDOM_PREDICTION_HEADER}{prediction}",
            attachments=[MaxKeyboardManager.get_prediction_actions()],
        )

    async def _handle_about_command(self, chat_id: int) -> None:
        """Обработка команды /about."""
        about_text = await _get_bot_text(
            "about_text",
            texts.ABOUT_TEXT_FALLBACK,
        )
        await self._api.send_message(
            chat_id=chat_id,
            text=about_text,
            attachments=[MaxKeyboardManager.get_about_keyboard()],
        )

    async def _handle_clear_command(self, chat_id: int) -> None:
        """Обработка команды /clear — запрос подтверждения."""
        await self._api.send_message(
            chat_id=chat_id,
            text=texts.CLEAR_HISTORY_CONFIRM,
            attachments=[MaxKeyboardManager.get_confirmation_keyboard("clear_history")],
        )

    async def _handle_support_command(self, chat_id: int) -> None:
        """Обработка команды /support."""
        await self._api.send_message(
            chat_id=chat_id,
            text=texts.SUPPORT_TEXT,
            attachments=[MaxKeyboardManager.get_back_to_menu_button()],
        )

    async def _handle_subscription_command(
        self,
        user: MaxUser,
        chat_id: int,
    ) -> None:
        """Обработка команды /subscribe — показ статуса подписки.

        Args:
            user: Объект пользователя MAX.
            chat_id: ID чата для ответа.
        """
        db_user = await _get_or_create_user(user)
        await self._show_subscription_status(db_user, chat_id)

    # ────────────────────────────────────────────
    #  Подписка — общие методы
    # ────────────────────────────────────────────

    async def _show_subscription_status(
        self,
        db_user: Any,
        chat_id: int,
    ) -> None:
        """Отображение текущего статуса подписки пользователя.

        Args:
            db_user: Объект User из базы данных.
            chat_id: ID чата для ответа.
        """
        async for session in db_manager.get_session():
            sub_repo = SubscriptionRepository(session)
            settings_repo = SettingsRepository(session)

            status = await sub_repo.get_subscription_status(db_user.id)
            price_str = await settings_repo.get_setting("subscription_price")
            price = int(float(price_str)) if price_str else 300

            recurring_enabled, _ = await sub_repo.is_recurring_enabled(db_user.id)

            if status["type"] == "vip":
                status_text = texts.subscription_status_vip(
                    status.get("vip_reason"),
                )
            elif status["type"] == "premium" and status["active"]:
                status_text = texts.subscription_status_premium(
                    status["until"][:10],
                )
                if not recurring_enabled:
                    status_text += texts.SUBSCRIPTION_RECURRING_OFF_WARNING
            else:
                used = status.get("predictions_used", 0)
                limit = status.get("predictions_limit", 10)
                status_text = texts.subscription_status_free(used, limit, price)

            has_active = (
                status["type"] == "vip"
                or (status["type"] == "premium" and status["active"])
            )
            is_vip = status["type"] == "vip"

            await self._api.send_message(
                chat_id=chat_id,
                text=status_text,
                attachments=[
                    MaxKeyboardManager.get_subscription_status_keyboard(
                        has_active_subscription=has_active,
                        is_vip=is_vip,
                        recurring_enabled=recurring_enabled,
                    ),
                ],
            )

    # ────────────────────────────────────────────
    #  Фотографии
    # ────────────────────────────────────────────

    async def _handle_photo_message(self, message: MaxMessage, chat_id: int) -> None:
        """Обработка сообщения с фотографией.

        Перед анализом проверяет лимиты подписки пользователя.

        Args:
            message: Сообщение MAX с фото-вложениями.
            chat_id: ID чата для ответа.
        """
        user = message.sender
        if not user:
            return

        # Сбрасываем FSM-состояние при отправке фото
        _state_manager.clear_state(user.user_id)

        # ── Проверка подписки ──
        db_user = await _get_or_create_user(user)

        async for session in db_manager.get_session():
            sub_repo = SubscriptionRepository(session)
            settings_repo = SettingsRepository(session)

            can_predict, reason = await sub_repo.can_make_prediction(db_user.id)

            if not can_predict:
                price_str = await settings_repo.get_setting("subscription_price")
                price = int(float(price_str)) if price_str else 300

                await self._api.send_message(
                    chat_id=chat_id,
                    text=texts.paywall_text(reason, price),
                    attachments=[MaxKeyboardManager.get_paywall_keyboard()],
                )
                return

        # ── Обработка фото ──

        # Показываем индикатор набора
        try:
            await self._api.send_action(chat_id, "typing_on")
        except Exception:
            pass

        # Сообщение обработки
        photo_urls = self._photo.extract_photo_urls(message)
        if len(photo_urls) > 1:
            processing_text = texts.processing_message_multiple(len(photo_urls))
        else:
            processing_text = await _get_bot_text(
                "processing_message",
                texts.PROCESSING_MESSAGE_FALLBACK,
            )

        processing_msg = await self._api.send_message(
            chat_id=chat_id,
            text=processing_text,
        )
        processing_msg_id = processing_msg.message_id

        # Получаем caption пользователя
        user_message = message.text  # В MAX текст приходит в body.text

        try:
            # Проверка настройки анализа всех фото
            analyze_all = await _get_bot_text("analyze_all_photos", "true")
            analyze_all = analyze_all.lower() == "true"

            if len(photo_urls) > 1 and analyze_all:
                prediction_text, photos_data = await self._photo.process_multiple_photos(
                    photo_urls,
                    user_message=user_message,
                    username=user.first_name,
                )
            else:
                prediction_text, photos_data = await self._photo.process_single_photo(
                    photo_urls[0],
                    user_message=user_message,
                    username=user.first_name,
                )

        except (PhotoProcessingError, OpenAIError) as e:
            error_text = format_error_message(e, user_friendly=True)
            if processing_msg_id:
                await self._safe_edit_message(processing_msg_id, error_text)
            else:
                await self._api.send_message(chat_id=chat_id, text=error_text)
            return

        except Exception as e:
            logger.error("MAX: непредвиденная ошибка обработки фото: %s", e, exc_info=True)
            if processing_msg_id:
                await self._safe_edit_message(processing_msg_id, texts.PHOTO_PROCESSING_ERROR)
            else:
                await self._api.send_message(chat_id=chat_id, text=texts.PHOTO_PROCESSING_ERROR)
            return

        if not prediction_text:
            await self._safe_edit_message(
                processing_msg_id,
                texts.PREDICTION_FAILED,
            )
            return

        # Сохранение в БД
        photo_file_id = photos_data[0]["file_id"] if photos_data else "unknown"
        photo_path = photos_data[0]["file_path"] if photos_data else None

        try:
            async for session in db_manager.get_session():
                user_repo = UserRepository(session)
                prediction_repo = PredictionRepository(session)
                reminder_repo = ReminderRepository(session)

                db_user = await user_repo.get_user_by_telegram_id(
                    user.user_id, source=_SOURCE,
                )
                if not db_user:
                    db_user = await _get_or_create_user(user)

                await prediction_repo.create_prediction(
                    user_id=db_user.id,
                    photo_file_id=photo_file_id,
                    prediction_text=prediction_text,
                    photo_path=photo_path,
                    user_request=user_message,
                    photos=photos_data,
                    subscription_type=db_user.subscription_type,
                )

                # Сбрасываем цепочку ремайндеров — пользователь активен
                await reminder_repo.reset_reminders(db_user.id)

        except Exception as e:
            logger.error("MAX: ошибка сохранения предсказания в БД: %s", e)
            # Всё равно отправляем предсказание пользователю

        # Отправка предсказания
        await self._send_prediction_to_user(
            chat_id=chat_id,
            processing_msg_id=processing_msg_id,
            prediction_text=prediction_text,
        )

    async def _send_prediction_to_user(
        self,
        chat_id: int,
        processing_msg_id: Optional[str],
        prediction_text: str,
    ) -> None:
        """Отправка предсказания пользователю с Markdown-форматированием.

        Редактирует сообщение-индикатор или отправляет новое.
        При длинном тексте разбивает на части.

        Args:
            chat_id: ID чата для ответа.
            processing_msg_id: ID сообщения обработки для редактирования.
            prediction_text: Текст предсказания (содержит Markdown-разметку).
        """
        max_length = 3900  # С запасом от лимита 4000

        if len(prediction_text) <= max_length:
            # Короткое предсказание — редактируем и добавляем кнопки
            if processing_msg_id:
                try:
                    await self._api.edit_message(
                        message_id=processing_msg_id,
                        text=prediction_text,
                        attachments=[MaxKeyboardManager.get_prediction_actions()],
                        format_type="markdown",
                    )
                    return
                except Exception as e:
                    logger.warning("MAX: не удалось отредактировать сообщение: %s", e)

            # Fallback — новое сообщение
            await self._api.send_message(
                chat_id=chat_id,
                text=prediction_text,
                attachments=[MaxKeyboardManager.get_prediction_actions()],
                format_type="markdown",
            )
        else:
            # Длинное предсказание — разбиваем
            chunks = self._split_text(prediction_text, max_length)

            # Первый чанк — редактируем индикатор
            if processing_msg_id:
                await self._safe_edit_message(
                    processing_msg_id,
                    chunks[0],
                    format_type="markdown",
                )
            else:
                await self._api.send_message(
                    chat_id=chat_id,
                    text=chunks[0],
                    format_type="markdown",
                )

            # Средние чанки — новые сообщения
            for chunk in chunks[1:-1]:
                await self._api.send_message(
                    chat_id=chat_id,
                    text=chunk,
                    format_type="markdown",
                )

            # Последний чанк — с кнопками
            if len(chunks) > 1:
                await self._api.send_message(
                    chat_id=chat_id,
                    text=chunks[-1],
                    attachments=[MaxKeyboardManager.get_prediction_actions()],
                    format_type="markdown",
                )

    # ────────────────────────────────────────────
    #  Callback от кнопок
    # ────────────────────────────────────────────

    async def _handle_callback(self, update: MaxUpdate) -> None:
        """Маршрутизация callback от нажатия кнопок.

        Args:
            update: Обновление с типом message_callback.
        """
        callback = update.callback
        if not callback or not callback.callback_id:
            return

        payload = callback.payload or ""
        user = callback.user
        message = update.message  # Сообщение на верхнем уровне update

        # Если message не в update, берём из callback
        if not message and callback.message:
            message = callback.message

        chat_id = message.chat_id if message else None

        # Подтверждаем callback СРАЗУ — MAX API требует message или notification
        try:
            await self._api.answer_callback(
                callback.callback_id,
                notification="✨",
            )
        except Exception as e:
            logger.debug("MAX: ошибка подтверждения callback: %s", e)

        if not chat_id or not user:
            logger.warning(
                "MAX callback без chat_id или user: payload=%s, chat_id=%s, user=%s",
                payload, chat_id, user,
            )
            return

        logger.info(
            "MAX callback: payload=%s, user=%d, chat_id=%d",
            payload, user.user_id, chat_id,
        )

        # Маршрутизация по payload
        try:
            if payload == "action_predict":
                await self._handle_predict_command(chat_id)

            elif payload == "action_video_instruction":
                await self._handle_video_instruction(chat_id)

            elif payload in ("action_history", "action_show_history"):
                await self._callback_show_history(callback, chat_id)

            elif payload == "action_random":
                await self._handle_random_command(chat_id)

            elif payload in ("action_faq", "action_help"):
                # action_faq — новая кнопка, action_help — обратная совместимость
                await self._handle_faq_command(chat_id)

            elif payload == "action_about":
                await self._handle_about_command(chat_id)

            elif payload == "action_clear":
                await self._handle_clear_command(chat_id)

            elif payload == "action_support":
                await self._handle_support_command(chat_id)

            elif payload == "action_new_prediction":
                await self._handle_predict_command(chat_id)

            elif payload == "action_back_to_menu":
                # Сбрасываем FSM-состояние при возврате в меню
                _state_manager.clear_state(user.user_id)
                await self._callback_back_to_menu(callback, chat_id)

            elif payload == "action_cancel":
                _state_manager.clear_state(user.user_id)
                await self._callback_cancel(callback, chat_id)

            # ── Подписка и платежи ──
            elif payload == "action_subscription":
                await self._callback_subscription(user, chat_id)

            elif payload == "action_subscription_status":
                await self._callback_subscription_status(user, chat_id)

            elif payload == "action_start_payment":
                await self._callback_start_payment(user, chat_id)

            elif payload == "action_check_payment":
                await self._callback_check_payment(user, chat_id)

            elif payload == "action_cancel_subscription":
                await self._callback_cancel_subscription(chat_id)

            elif payload == "action_confirm_cancel_sub":
                await self._callback_confirm_cancel_sub(user, chat_id)

            elif payload.startswith("confirm_"):
                await self._callback_confirm(callback, payload, chat_id)

            elif payload.startswith("help_"):
                # Обратная совместимость: старые кнопки help_photo и т.д.
                await self._callback_help_section(callback, payload, chat_id)

            else:
                logger.warning("MAX: неизвестный callback payload: %s", payload)

        except Exception as e:
            logger.error(
                "MAX: ошибка обработки callback payload=%s: %s",
                payload, e,
                exc_info=True,
            )

    # ────────────────────────────────────────────
    #  Callback: подписка и платежи
    # ────────────────────────────────────────────

    async def _callback_subscription(
        self,
        user: MaxUser,
        chat_id: int,
    ) -> None:
        """Callback: показ статуса подписки (кнопка 💎 Подписка)."""
        db_user = await _get_or_create_user(user)
        await self._show_subscription_status(db_user, chat_id)

    async def _callback_subscription_status(
        self,
        user: MaxUser,
        chat_id: int,
    ) -> None:
        """Callback: обновление статуса подписки."""
        db_user = await _get_or_create_user(user)
        await self._show_subscription_status(db_user, chat_id)

    async def _callback_start_payment(
        self,
        user: MaxUser,
        chat_id: int,
    ) -> None:
        """Callback: начало оплаты — запрос email.

        Переводит пользователя в состояние ожидания email.
        """
        from coffee_oracle.services.payment_service import get_payment_service

        payment_service = get_payment_service()
        if payment_service is None:
            await self._api.send_message(
                chat_id=chat_id,
                text=texts.PAYMENT_UNAVAILABLE,
            )
            return

        # Устанавливаем FSM-состояние
        _state_manager.set_state(
            user.user_id,
            state="waiting_for_email",
            chat_id=chat_id,
        )

        await self._api.send_message(
            chat_id=chat_id,
            text=texts.EMAIL_REQUEST,
            attachments=[MaxKeyboardManager.get_email_cancel_keyboard()],
        )

    async def _callback_check_payment(
        self,
        user: MaxUser,
        chat_id: int,
    ) -> None:
        """Callback: ручная проверка статуса платежа."""
        from coffee_oracle.services.payment_service import get_payment_service

        payment_service = get_payment_service()
        if payment_service is None:
            await self._api.send_message(
                chat_id=chat_id,
                text=texts.PAYMENT_UNAVAILABLE,
            )
            return

        # Получаем pending-платёж
        payment_id = payment_service.get_pending_payment(user.user_id)
        if not payment_id:
            await self._api.send_message(
                chat_id=chat_id,
                text=texts.NO_PENDING_PAYMENTS,
            )
            return

        async for session in db_manager.get_session():
            user_repo = UserRepository(session)
            sub_repo = SubscriptionRepository(session)

            db_user = await user_repo.get_user_by_telegram_id(
                user.user_id, source=_SOURCE,
            )
            if not db_user:
                await self._api.send_message(
                    chat_id=chat_id,
                    text=texts.USER_NOT_FOUND,
                )
                return

            try:
                status_result = await payment_service.get_payment_status(payment_id)

                if not status_result.get("success"):
                    logger.error(
                        "MAX: ошибка проверки статуса платежа: %s",
                        status_result.get("error"),
                    )
                    await self._api.send_message(
                        chat_id=chat_id,
                        text=texts.PAYMENT_STATUS_CHECK_FAILED,
                    )
                    return

                status = status_result.get("status")
                paid = status_result.get("paid", False)

                if status == "succeeded" and paid:
                    # Активация подписки
                    await sub_repo.activate_premium(db_user.id)

                    payment_method_saved = status_result.get(
                        "payment_method_saved", False,
                    )
                    payment_method_id = status_result.get("payment_method_id")
                    if payment_method_saved and payment_method_id:
                        await sub_repo.enable_recurring_payment(
                            db_user.id, payment_method_id,
                        )

                    await sub_repo.update_payment_status(payment_id, "succeeded")
                    payment_service.clear_pending_payment(user.user_id)

                    recurring_enabled = bool(
                        payment_method_saved and payment_method_id,
                    )
                    success_text = (
                        texts.PAYMENT_SUCCESS_RECURRING if recurring_enabled
                        else texts.PAYMENT_SUCCESS
                    )

                    await self._api.send_message(
                        chat_id=chat_id,
                        text=success_text,
                        attachments=[
                            MaxKeyboardManager.get_subscription_status_keyboard(
                                has_active_subscription=True,
                                recurring_enabled=recurring_enabled,
                            ),
                        ],
                    )

                elif status == "pending":
                    await self._api.send_message(
                        chat_id=chat_id,
                        text=texts.PAYMENT_PENDING,
                        attachments=[
                            MaxKeyboardManager.get_subscription_keyboard(),
                        ],
                    )

                elif status == "canceled":
                    await sub_repo.update_payment_status(payment_id, "canceled")
                    payment_service.clear_pending_payment(user.user_id)

                    await self._api.send_message(
                        chat_id=chat_id,
                        text=texts.PAYMENT_CANCELLED,
                        attachments=[
                            MaxKeyboardManager.get_subscription_status_keyboard(
                                has_active_subscription=False,
                            ),
                        ],
                    )

                else:
                    await self._api.send_message(
                        chat_id=chat_id,
                        text=texts.payment_status_unknown(status),
                        attachments=[
                            MaxKeyboardManager.get_subscription_keyboard(),
                        ],
                    )

            except Exception as e:
                logger.error(
                    "MAX: ошибка проверки платежа: %s",
                    e, exc_info=True,
                )
                await self._api.send_message(
                    chat_id=chat_id,
                    text=texts.PAYMENT_CHECK_ERROR,
                )

    async def _callback_cancel_subscription(self, chat_id: int) -> None:
        """Callback: запрос подтверждения отмены автопродления."""
        await self._api.send_message(
            chat_id=chat_id,
            text=texts.CANCEL_SUBSCRIPTION_CONFIRM,
            attachments=[
                MaxKeyboardManager.get_cancel_subscription_confirmation(),
            ],
        )

    async def _callback_confirm_cancel_sub(
        self,
        user: MaxUser,
        chat_id: int,
    ) -> None:
        """Callback: подтверждённая отмена автопродления."""
        try:
            async for session in db_manager.get_session():
                user_repo = UserRepository(session)
                sub_repo = SubscriptionRepository(session)

                db_user = await user_repo.get_user_by_telegram_id(
                    user.user_id, source=_SOURCE,
                )
                if not db_user:
                    await self._api.send_message(
                        chat_id=chat_id,
                        text=texts.USER_NOT_FOUND,
                    )
                    return

                await sub_repo.disable_recurring_payment(db_user.id)

                status = await sub_repo.get_subscription_status(db_user.id)
                until = (
                    status.get("until", "")[:10]
                    if status.get("until")
                    else ""
                )

            await self._api.send_message(
                chat_id=chat_id,
                text=texts.cancel_subscription_success(until),
                attachments=[
                    MaxKeyboardManager.get_subscription_status_keyboard(
                        has_active_subscription=bool(until),
                        is_vip=False,
                        recurring_enabled=False,
                    ),
                ],
            )

        except Exception as e:
            logger.error("MAX: ошибка отмены подписки: %s", e, exc_info=True)
            await self._api.send_message(
                chat_id=chat_id,
                text=texts.CANCEL_SUBSCRIPTION_ERROR,
            )

    # ────────────────────────────────────────────
    #  Callback: прочие
    # ────────────────────────────────────────────

    async def _callback_show_history(self, callback: MaxCallback, chat_id: int) -> None:
        """Callback: показать частые запросы."""
        await self._api.send_message(
            chat_id=chat_id,
            text=texts.FREQUENT_QUERIES_TEXT,
            attachments=[MaxKeyboardManager.get_back_to_menu_button()],
        )

    async def _callback_back_to_menu(self, callback: MaxCallback, chat_id: int) -> None:
        """Callback: возврат в главное меню."""
        await self._api.send_message(
            chat_id=chat_id,
            text=texts.MAIN_MENU_TEXT,
            attachments=[MaxKeyboardManager.get_main_menu_with_subscription()],
        )

    async def _callback_cancel(self, callback: MaxCallback, chat_id: int) -> None:
        """Callback: отмена действия."""
        await self._api.send_message(
            chat_id=chat_id,
            text=texts.ACTION_CANCELLED_MAX,
            attachments=[MaxKeyboardManager.get_main_menu_with_subscription()],
        )

    async def _callback_confirm(
        self,
        callback: MaxCallback,
        payload: str,
        chat_id: int,
    ) -> None:
        """Callback: подтверждение действия.

        Args:
            callback: Объект callback.
            payload: Полный payload (например, 'confirm_clear_history').
            chat_id: ID чата для ответа.
        """
        action = payload.replace("confirm_", "", 1)

        if action == "clear_history":
            user = callback.user
            if not user:
                return

            try:
                async for session in db_manager.get_session():
                    user_repo = UserRepository(session)
                    db_user = await user_repo.get_user_by_telegram_id(
                        user.user_id, source=_SOURCE,
                    )

                    if db_user:
                        from sqlalchemy import text as sql_text

                        await session.execute(
                            sql_text("DELETE FROM predictions WHERE user_id = :user_id"),
                            {"user_id": db_user.id},
                        )
                        await session.commit()

                await self._api.send_message(
                    chat_id=chat_id,
                    text=texts.CLEAR_HISTORY_SUCCESS,
                    attachments=[MaxKeyboardManager.get_main_menu_with_subscription()],
                )

            except Exception as e:
                logger.error("MAX: ошибка очистки истории: %s", e)
                await self._api.send_message(
                    chat_id=chat_id,
                    text=texts.CLEAR_HISTORY_ERROR,
                )

    async def _callback_help_section(
        self,
        callback: MaxCallback,
        payload: str,
        chat_id: int,
    ) -> None:
        """Callback: отображение раздела помощи (обратная совместимость).

        Если пользователь нажмёт старую кнопку из кэша — покажем текст раздела.

        Args:
            callback: Объект callback.
            payload: Payload вида 'help_photo', 'help_coffee' и т.д.
            chat_id: ID чата для ответа.
        """
        help_type = payload.replace("help_", "", 1)
        text = texts.HELP_SECTIONS.get(help_type, "Информация не найдена")
        await self._api.send_message(
            chat_id=chat_id,
            text=text,
        )

    # ────────────────────────────────────────────
    #  Вспомогательные методы
    # ────────────────────────────────────────────

    async def _safe_edit_message(
        self,
        message_id: Optional[str],
        text: str,
        format_type: Optional[str] = None,
    ) -> None:
        """Безопасное редактирование сообщения (игнорирует ошибки).

        Args:
            message_id: ID сообщения для редактирования.
            text: Новый текст.
            format_type: Формат текста ('markdown' или 'html').
        """
        if not message_id:
            return
        try:
            await self._api.edit_message(
                message_id=message_id,
                text=text,
                format_type=format_type,
            )
        except Exception as e:
            logger.warning("MAX: не удалось отредактировать сообщение %s: %s", message_id, e)

    @staticmethod
    def _split_text(text: str, max_length: int = 3900) -> List[str]:
        """Разбиение длинного текста на части.

        Пытается разбить по параграфам, затем по строкам.

        Args:
            text: Текст для разбиения.
            max_length: Максимальная длина одной части.

        Returns:
            Список частей текста.
        """
        if len(text) <= max_length:
            return [text]

        chunks: List[str] = []
        current_chunk = ""

        paragraphs = text.split("\n\n")

        for paragraph in paragraphs:
            if len(current_chunk) + len(paragraph) + 2 > max_length:
                if current_chunk:
                    chunks.append(current_chunk.strip())
                    current_chunk = ""

                # Длинный параграф — разбиваем по строкам
                if len(paragraph) > max_length:
                    lines = paragraph.split("\n")
                    for line in lines:
                        if len(current_chunk) + len(line) + 1 > max_length:
                            if current_chunk:
                                chunks.append(current_chunk.strip())
                            current_chunk = line + "\n"
                        else:
                            current_chunk += line + "\n"
                else:
                    current_chunk = paragraph + "\n\n"
            else:
                current_chunk += paragraph + "\n\n"

        if current_chunk.strip():
            chunks.append(current_chunk.strip())

        return chunks if chunks else [text[:max_length]]