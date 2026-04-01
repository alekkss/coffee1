"""Обработчики событий MAX-бота.

Содержит логику реакции на все типы входящих событий:
текстовые сообщения, фотографии, callback от кнопок.
Аналог bot/handlers.py для мессенджера MAX.
"""

import logging
import random
from typing import Any, Dict, List, Optional

from coffee_oracle.database.connection import db_manager
from coffee_oracle.database.repositories import (
    PredictionRepository,
    SettingsRepository,
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
) -> Any:
    """Получение или создание пользователя MAX в БД.

    Использует source='max' для разделения пространства ID
    с Telegram-пользователями.

    Args:
        max_user: Объект пользователя MAX.

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
        )


class MaxBotHandlers:
    """Обработчики событий MAX-бота.

    Маршрутизирует входящие обновления к соответствующим
    методам-обработчикам. Управляет взаимодействием между
    MAX API клиентом, обработчиком фото и базой данных.

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

        Args:
            update: Обновление с типом bot_started.
        """
        user = update.user
        if not user:
            return

        logger.info("MAX: пользователь %d запустил бота", user.user_id)

        db_user = await _get_or_create_user(user)

        welcome_template = await _get_bot_text(
            "welcome_message",
            "🔮 Добро пожаловать в мир Кофейного Оракула, {name}!\n\n"
            "Я помогу вам узнать, что говорят узоры кофейной гущи "
            "о вашем будущем. Просто сфотографируйте дно выпитой "
            "чашки кофе, и я открою вам тайны, которые скрывают "
            "эти магические узоры.\n\n"
            "✨ Все предсказания несут только позитивную энергию "
            "и вдохновение!\n\n"
            "Выберите действие:",
        )

        welcome_text = welcome_template.replace("{name}", db_user.full_name)

        await self._api.send_message(
            user_id=user.user_id,
            text=welcome_text,
            attachments=[MaxKeyboardManager.get_main_menu()],
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
            text="📸 Пожалуйста, отправьте фотографию кофейной чашки "
                 "с гущей или воспользуйтесь кнопками меню.",
            attachments=[MaxKeyboardManager.get_main_menu()],
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

        Args:
            text: Текст сообщения.
            message: Полное сообщение MAX.
            chat_id: ID чата для ответа.
        """
        # Обработка команд (начинаются с /)
        text_lower = text.lower()

        if text_lower == "/start":
            await self._handle_start_command(message, chat_id)
        elif text_lower == "/help":
            await self._handle_help_command(chat_id)
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
        else:
            # Произвольный текст — предложить меню
            await self._api.send_message(
                chat_id=chat_id,
                text="🔮 Я понимаю только язык кофейной гущи!\n\n"
                     "Отправьте фото вашей кофейной чашки "
                     "или воспользуйтесь кнопками меню.",
                attachments=[MaxKeyboardManager.get_main_menu()],
            )

    # ────────────────────────────────────────────
    #  Команды
    # ────────────────────────────────────────────

    async def _handle_start_command(self, message: MaxMessage, chat_id: int) -> None:
        """Обработка команды /start."""
        user = message.sender
        if not user:
            return

        db_user = await _get_or_create_user(user)

        welcome_template = await _get_bot_text(
            "welcome_message",
            "🔮 Добро пожаловать в мир Кофейного Оракула, {name}!\n\n"
            "Просто сфотографируйте дно выпитой чашки кофе, "
            "и я открою вам тайны узоров.\n\n"
            "Выберите действие:",
        )

        welcome_text = welcome_template.replace("{name}", db_user.full_name)

        await self._api.send_message(
            chat_id=chat_id,
            text=welcome_text,
            attachments=[MaxKeyboardManager.get_main_menu()],
        )

    async def _handle_help_command(self, chat_id: int) -> None:
        """Обработка команды /help."""
        await self._api.send_message(
            chat_id=chat_id,
            text="📚 Искусство гадания на кофейной гуще",
            attachments=[MaxKeyboardManager.get_help_menu()],
        )

    async def _handle_predict_command(self, chat_id: int) -> None:
        """Обработка команды /predict."""
        instruction = await _get_bot_text(
            "photo_instruction",
            "📸 Отправьте мне фотографию дна вашей кофейной чашки!\n\n"
            "Убедитесь, что:\n"
            "• Узоры кофейной гущи хорошо видны\n"
            "• Освещение достаточное\n"
            "• Фото сделано сверху\n\n"
            "Я внимательно изучу узоры и расскажу, что они предвещают! ✨",
        )

        await self._api.send_message(chat_id=chat_id, text=instruction)

    async def _handle_history_command(self, message: MaxMessage, chat_id: int) -> None:
        """Обработка команды /history."""
        user = message.sender
        if not user:
            return

        async for session in db_manager.get_session():
            user_repo = UserRepository(session)
            prediction_repo = PredictionRepository(session)

            db_user = await user_repo.get_user_by_telegram_id(
                user.user_id, source=_SOURCE,
            )
            if not db_user:
                await self._api.send_message(
                    chat_id=chat_id,
                    text="Сначала получите ваше первое предсказание! 🔮\n\n"
                         "Отправьте фото кофейной чашки.",
                )
                return

            predictions = await prediction_repo.get_user_predictions(db_user.id, limit=5)

            if not predictions:
                await self._api.send_message(
                    chat_id=chat_id,
                    text="📜 У вас пока нет предсказаний в истории.\n\n"
                         "Отправьте фото кофейной чашки с гущей! ☕✨",
                )
                return

            history_text = f"📜 Ваши последние предсказания ({len(predictions)} из 5):\n\n"

            for i, prediction in enumerate(predictions, 1):
                date_str = prediction.created_at.strftime("%d.%m.%Y в %H:%M")
                history_text += f"🔮 {i}. {date_str}\n"
                history_text += f"{prediction.prediction_text}\n"
                history_text += "─" * 30 + "\n\n"

            # MAX лимит сообщения — 4000 символов
            if len(history_text) > 3900:
                history_text = history_text[:3900] + "\n\n...продолжение скрыто"

            await self._api.send_message(chat_id=chat_id, text=history_text)

    async def _handle_random_command(self, chat_id: int) -> None:
        """Обработка команды /random."""
        random_predictions = [
            "🌟 Сегодня звезды благоволят вашим начинаниям! "
            "Смело идите к своим целям, удача на вашей стороне.",
            "💫 Впереди вас ждет приятная встреча, которая может "
            "изменить ваш взгляд на многие вещи к лучшему.",
            "🍀 Ваша интуиция сегодня особенно сильна. "
            "Доверьтесь внутреннему голосу — он не подведет.",
            "✨ Скоро в вашу жизнь войдет что-то новое и прекрасное. "
            "Будьте открыты для перемен!",
            "🌈 После небольших трудностей вас ждет период гармонии "
            "и процветания. Не сдавайтесь!",
            "🎭 Ваши творческие способности сейчас на пике. "
            "Время воплощать смелые идеи в жизнь!",
            "🌸 Любовь и дружба окружат вас теплом. Цените близких "
            "людей — они ваша главная сила.",
            "🚀 Впереди открываются новые возможности для роста. "
            "Не бойтесь выходить из зоны комфорта!",
        ]

        prediction = random.choice(random_predictions)
        await self._api.send_message(
            chat_id=chat_id,
            text=f"🔮 Случайное предсказание от Кофейного Оракула:\n\n{prediction}",
            attachments=[MaxKeyboardManager.get_prediction_actions()],
        )

    async def _handle_about_command(self, chat_id: int) -> None:
        """Обработка команды /about."""
        about_text = await _get_bot_text(
            "about_text",
            "🔮 Кофейный Оракул\n\n"
            "Я — мистический бот, который умеет читать будущее "
            "по узорам кофейной гущи.\n\n"
            "✨ Особенности:\n"
            "• Только позитивные предсказания\n"
            "• Анализ реальных узоров гущи\n"
            "• Мистический, но добрый подход\n"
            "• История ваших предсказаний\n\n"
            "Создано с ❤️ для любителей кофе и магии.",
        )
        await self._api.send_message(chat_id=chat_id, text=about_text)

    async def _handle_clear_command(self, chat_id: int) -> None:
        """Обработка команды /clear — запрос подтверждения."""
        await self._api.send_message(
            chat_id=chat_id,
            text="🗑️ Очистить историю предсказаний\n\n"
                 "⚠️ Это действие нельзя отменить!\n"
                 "Все ваши предсказания будут удалены навсегда.\n\n"
                 "Вы уверены?",
            attachments=[MaxKeyboardManager.get_confirmation_keyboard("clear_history")],
        )

    async def _handle_support_command(self, chat_id: int) -> None:
        """Обработка команды /support."""
        support_text = (
            "📞 Поддержка Кофейного Оракула\n\n"
            "🔮 Если у вас возникли вопросы или проблемы:\n\n"
            "• Убедитесь, что отправляете именно фото (не файл)\n"
            "• Проверьте качество освещения на фото\n"
            "• Убедитесь, что гуща хорошо видна\n\n"
            "❓ Частые вопросы:\n"
            "• Бот не отвечает → Попробуйте /start\n"
            "• Нет истории → Сначала получите предсказание\n\n"
            "✨ Помните: магия требует терпения!"
        )
        await self._api.send_message(chat_id=chat_id, text=support_text)

    # ────────────────────────────────────────────
    #  Фотографии
    # ────────────────────────────────────────────

    async def _handle_photo_message(self, message: MaxMessage, chat_id: int) -> None:
        """Обработка сообщения с фотографией.

        Args:
            message: Сообщение MAX с фото-вложениями.
            chat_id: ID чата для ответа.
        """
        user = message.sender
        if not user:
            return

        # Показываем индикатор набора
        try:
            await self._api.send_action(chat_id, "typing_on")
        except Exception:
            pass

        # Сообщение обработки
        photo_urls = self._photo.extract_photo_urls(message)
        if len(photo_urls) > 1:
            processing_text = f"🔮 Получено {len(photo_urls)} фото. Изучаю узоры... ✨"
        else:
            processing_text = await _get_bot_text(
                "processing_message",
                "🔮 Смотрю в чашку... Звезды открывают свои тайны... ✨",
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
            error_text = "🔮 Произошла магическая помеха. Попробуйте ещё раз через несколько минут."
            if processing_msg_id:
                await self._safe_edit_message(processing_msg_id, error_text)
            else:
                await self._api.send_message(chat_id=chat_id, text=error_text)
            return

        if not prediction_text:
            await self._safe_edit_message(
                processing_msg_id,
                "🔮 Не удалось получить предсказание. Попробуйте ещё раз.",
            )
            return

        # Сохранение в БД
        photo_file_id = photos_data[0]["file_id"] if photos_data else "unknown"
        photo_path = photos_data[0]["file_path"] if photos_data else None

        try:
            async for session in db_manager.get_session():
                user_repo = UserRepository(session)
                prediction_repo = PredictionRepository(session)

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
                )
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
        """Отправка предсказания пользователю.

        Редактирует сообщение-индикатор или отправляет новое.
        При длинном тексте разбивает на части.

        Args:
            chat_id: ID чата для ответа.
            processing_msg_id: ID сообщения обработки для редактирования.
            prediction_text: Текст предсказания.
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
                    )
                    return
                except Exception as e:
                    logger.warning("MAX: не удалось отредактировать сообщение: %s", e)

            # Fallback — новое сообщение
            await self._api.send_message(
                chat_id=chat_id,
                text=prediction_text,
                attachments=[MaxKeyboardManager.get_prediction_actions()],
            )
        else:
            # Длинное предсказание — разбиваем
            chunks = self._split_text(prediction_text, max_length)

            # Первый чанк — редактируем индикатор
            if processing_msg_id:
                await self._safe_edit_message(processing_msg_id, chunks[0])
            else:
                await self._api.send_message(chat_id=chat_id, text=chunks[0])

            # Средние чанки — новые сообщения
            for chunk in chunks[1:-1]:
                await self._api.send_message(chat_id=chat_id, text=chunk)

            # Последний чанк — с кнопками
            last_chunk = chunks[-1] if len(chunks) > 1 else chunks[0]
            await self._api.send_message(
                chat_id=chat_id,
                text=last_chunk,
                attachments=[MaxKeyboardManager.get_prediction_actions()],
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

        logger.info("MAX callback: payload=%s, user=%d, chat_id=%d", payload, user.user_id, chat_id)

        # Маршрутизация по payload
        try:
            if payload == "action_predict":
                await self._handle_predict_command(chat_id)

            elif payload in ("action_history", "action_show_history"):
                await self._callback_show_history(callback, chat_id)

            elif payload == "action_random":
                await self._handle_random_command(chat_id)

            elif payload == "action_help":
                await self._handle_help_command(chat_id)

            elif payload == "action_about":
                await self._handle_about_command(chat_id)

            elif payload == "action_clear":
                await self._handle_clear_command(chat_id)

            elif payload == "action_support":
                await self._handle_support_command(chat_id)

            elif payload == "action_new_prediction":
                await self._handle_predict_command(chat_id)

            elif payload == "action_back_to_menu":
                await self._callback_back_to_menu(callback, chat_id)

            elif payload == "action_cancel":
                await self._callback_cancel(callback, chat_id)

            elif payload.startswith("confirm_"):
                await self._callback_confirm(callback, payload, chat_id)

            elif payload.startswith("help_"):
                await self._callback_help_section(callback, payload, chat_id)

            else:
                logger.warning("MAX: неизвестный callback payload: %s", payload)

        except Exception as e:
            logger.error(
                "MAX: ошибка обработки callback payload=%s: %s",
                payload, e,
                exc_info=True,
            )

    async def _callback_show_history(self, callback: MaxCallback, chat_id: int) -> None:
        """Callback: показать историю предсказаний."""
        user = callback.user
        if not user:
            return

        async for session in db_manager.get_session():
            user_repo = UserRepository(session)
            prediction_repo = PredictionRepository(session)

            db_user = await user_repo.get_user_by_telegram_id(
                user.user_id, source=_SOURCE,
            )
            if not db_user:
                await self._api.send_message(
                    chat_id=chat_id,
                    text="Сначала получите ваше первое предсказание! 🔮",
                )
                return

            predictions = await prediction_repo.get_user_predictions(db_user.id, limit=5)

            if not predictions:
                await self._api.send_message(
                    chat_id=chat_id,
                    text="📜 У вас пока нет предсказаний. "
                         "Отправьте фото кофейной чашки! ☕✨",
                )
                return

            history_text = f"📜 Ваши последние предсказания ({len(predictions)} из 5):\n\n"
            for i, prediction in enumerate(predictions, 1):
                date_str = prediction.created_at.strftime("%d.%m.%Y в %H:%M")
                history_text += f"🔮 {i}. {date_str}\n"
                history_text += f"{prediction.prediction_text}\n"
                history_text += "─" * 30 + "\n\n"

            if len(history_text) > 3900:
                history_text = history_text[:3900] + "\n\n...продолжение скрыто"

            await self._api.send_message(chat_id=chat_id, text=history_text)

    async def _callback_back_to_menu(self, callback: MaxCallback, chat_id: int) -> None:
        """Callback: возврат в главное меню."""
        await self._api.send_message(
            chat_id=chat_id,
            text="📋 Главное меню Кофейного Оракула\n\nВыберите действие:",
            attachments=[MaxKeyboardManager.get_main_menu()],
        )

    async def _callback_cancel(self, callback: MaxCallback, chat_id: int) -> None:
        """Callback: отмена действия."""
        await self._api.send_message(
            chat_id=chat_id,
            text="❌ Действие отменено\n\n"
                 "Используйте кнопки меню для выбора других действий.",
            attachments=[MaxKeyboardManager.get_main_menu()],
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
                    text="✅ История предсказаний очищена!\n\n"
                         "Теперь вы можете начать с чистого листа. "
                         "Отправьте фото кофейной чашки для нового предсказания! 🔮",
                    attachments=[MaxKeyboardManager.get_main_menu()],
                )

            except Exception as e:
                logger.error("MAX: ошибка очистки истории: %s", e)
                await self._api.send_message(
                    chat_id=chat_id,
                    text="❌ Произошла ошибка при очистке истории.\n"
                         "Попробуйте позже.",
                )

    async def _callback_help_section(
        self,
        callback: MaxCallback,
        payload: str,
        chat_id: int,
    ) -> None:
        """Callback: отображение раздела помощи.

        Args:
            callback: Объект callback.
            payload: Payload вида 'help_photo', 'help_coffee' и т.д.
            chat_id: ID чата для ответа.
        """
        help_type = payload.replace("help_", "", 1)

        help_texts = {
            "photo": (
                "📸 Как правильно сфотографировать чашку:\n\n"
                "1. ☕ Выпейте кофе, оставив немного гущи на дне\n"
                "2. 🔄 Слегка покрутите чашку\n"
                "3. 📱 Сделайте фото сверху при хорошем освещении\n"
                "4. 🔍 Убедитесь, что узоры четко видны\n"
                "5. 📤 Отправьте фото\n\n"
                "💡 Совет: лучше всего фотографировать при дневном свете!"
            ),
            "coffee": (
                "☕ Приготовление кофе для гадания:\n\n"
                "1. ☕ Используйте молотый кофе среднего помола\n"
                "2. 🔥 Заварите крепкий кофе (турка или френч-пресс)\n"
                "3. 🥄 Не добавляйте сахар и молоко\n"
                "4. 🍵 Выпейте, оставив 1-2 глотка с гущей\n"
                "5. 🔄 Покрутите чашку 3 раза по часовой стрелке\n"
                "6. ⏰ Подождите 2-3 минуты\n\n"
                "✨ Чем крепче кофе, тем четче узоры!"
            ),
            "divination": (
                "🔮 О гадании на кофейной гуще:\n\n"
                "📜 Древнее искусство, пришедшее с Востока\n"
                "🎨 Узоры гущи — это язык подсознания\n\n"
                "🔍 Основные символы:\n"
                "• Круги — гармония, завершение дел\n"
                "• Линии — путешествия, перемены\n"
                "• Звезды — исполнение желаний\n"
                "• Цветы — любовь и радость\n"
                "• Птицы — хорошие новости\n\n"
                "💫 Помните: будущее в ваших руках!"
            ),
            "faq": (
                "❓ Частые вопросы:\n\n"
                "Q: Почему бот не отвечает на фото?\n"
                "A: Проверьте качество фото и освещение\n\n"
                "Q: Можно ли гадать на растворимом кофе?\n"
                "A: Лучше использовать молотый кофе\n\n"
                "Q: Сколько раз в день можно гадать?\n"
                "A: Рекомендуется не чаще 2-3 раз\n\n"
                "Q: Бот не работает, что делать?\n"
                "A: Попробуйте команду /start"
            ),
        }

        text = help_texts.get(help_type, "Информация не найдена")
        await self._api.send_message(
            chat_id=chat_id,
            text=text,
            attachments=[MaxKeyboardManager.get_help_menu()],
        )

    # ────────────────────────────────────────────
    #  Вспомогательные методы
    # ────────────────────────────────────────────

    async def _safe_edit_message(self, message_id: Optional[str], text: str) -> None:
        """Безопасное редактирование сообщения (игнорирует ошибки).

        Args:
            message_id: ID сообщения для редактирования.
            text: Новый текст.
        """
        if not message_id:
            return
        try:
            await self._api.edit_message(message_id=message_id, text=text)
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
