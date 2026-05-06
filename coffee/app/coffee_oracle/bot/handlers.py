"""Обработчики сообщений Telegram-бота.

Содержит логику реакции на все типы входящих событий:
команды, текстовые сообщения, фотографии, callback от кнопок,
FSM для оплаты подписки.
"""

import asyncio
import logging
import re
from typing import Any, Optional

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery, BotCommand, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.enums import ChatAction
import random

from coffee_oracle.bot.keyboards import KeyboardManager
from coffee_oracle.bot import texts
from coffee_oracle.config import config
from coffee_oracle.database.connection import db_manager
from coffee_oracle.database.repositories import (
    PartnerRepository,
    PredictionRepository,
    SettingsRepository,
    SubscriptionRepository,
    UserRepository,
)
from coffee_oracle.services.photo_processor import PhotoProcessor
from coffee_oracle.utils.errors import PhotoProcessingError, OpenAIError, format_error_message
from coffee_oracle.utils.telegram import split_message, markdown_to_telegram_html, strip_html_tags

logger = logging.getLogger(__name__)

router = Router()

EMAIL_RE = re.compile(r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$")

# Идентификатор платформы для всех операций с БД в Telegram-боте
_SOURCE = "tg"


class PaymentStates(StatesGroup):
    waiting_for_email = State()


async def get_bot_text(key: str, default: str) -> str:
    """Получение текста из настроек БД или значения по умолчанию.

    Args:
        key: Ключ настройки в таблице bot_settings.
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


@router.message(CommandStart(deep_link=True))
async def start_with_referral_handler(message: Message) -> Any:
    """Обработка /start с deep link параметром (реферальный код).

    Ссылка вида https://t.me/bot?start=КОД вызывает /start КОД.
    Если КОД соответствует реферальному коду партнёра:
    1. Записывает переход (ReferralClick).
    2. Создаёт/получает пользователя с привязкой к партнёру.
    3. Отправляет стандартное приветствие.

    Если КОД не найден среди партнёров — обрабатывает как обычный /start.
    """
    user = message.from_user
    if not user:
        return

    # Извлекаем deep link параметр
    args = message.text.split(maxsplit=1)
    referral_code = args[1].strip() if len(args) > 1 else ""

    # Пытаемся найти партнёра по коду
    partner_id = None
    if referral_code:
        try:
            async for session in db_manager.get_session():
                partner_repo = PartnerRepository(session)
                partner = await partner_repo.get_partner_by_referral_code(referral_code)

                if partner:
                    partner_id = partner.id

                    # Записываем переход по реферальной ссылке
                    await partner_repo.record_click(
                        partner_id=partner.id,
                        telegram_id=user.id,
                        source=_SOURCE,
                    )
                    logger.info(
                        "Реферальный переход: code=%s, partner_id=%d, telegram_id=%d",
                        referral_code, partner.id, user.id,
                    )
                else:
                    logger.debug(
                        "Реферальный код не найден: code=%s, telegram_id=%d",
                        referral_code, user.id,
                    )
        except Exception as e:
            logger.error("Ошибка обработки реферального кода: %s", e)

    # Создаём/получаем пользователя (с привязкой к партнёру, если найден)
    async for session in db_manager.get_session():
        user_repo = UserRepository(session)
        settings_repo = SettingsRepository(session)

        db_user = await user_repo.create_user(
            telegram_id=user.id,
            username=user.username,
            full_name=user.full_name or f"{user.first_name} {user.last_name or ''}".strip(),
            source=_SOURCE,
            referred_by_partner_id=partner_id,
        )

        # Стандартное приветствие
        welcome_template = await settings_repo.get_setting("welcome_message")
        if not welcome_template:
            welcome_template = texts.WELCOME_MESSAGE_FALLBACK

        welcome_text = welcome_template.replace("{name}", db_user.full_name)

        await message.answer(
            welcome_text,
            reply_markup=KeyboardManager.get_main_menu_with_subscription()
        )


@router.message(CommandStart())
async def start_handler(message: Message) -> Any:
    """Обработка /start без параметров."""
    user = message.from_user
    if not user:
        return

    async for session in db_manager.get_session():
        user_repo = UserRepository(session)
        settings_repo = SettingsRepository(session)

        # Create or get existing user
        db_user = await user_repo.create_user(
            telegram_id=user.id,
            username=user.username,
            full_name=user.full_name or f"{user.first_name} {user.last_name or ''}".strip(),
            source=_SOURCE,
        )

        # Get welcome message from settings
        welcome_template = await settings_repo.get_setting("welcome_message")
        if not welcome_template:
            welcome_template = texts.WELCOME_MESSAGE_FALLBACK

        welcome_text = welcome_template.replace("{name}", db_user.full_name)

        await message.answer(
            welcome_text,
            reply_markup=KeyboardManager.get_main_menu_with_subscription()
        )


@router.message(Command("help"))
async def help_handler(message: Message) -> Any:
    """Обработка команды /help — показ FAQ."""
    faq_text = texts.HELP_SECTIONS.get("faq", "Информация не найдена")
    await message.answer(faq_text)


@router.message(F.text == "🔮 Получить предсказание")
async def prediction_request_handler(message: Message) -> Any:
    """Обработка запроса на предсказание."""
    instruction_text = await get_bot_text(
        "photo_instruction", texts.PHOTO_INSTRUCTION_FALLBACK,
    )
    await message.answer(instruction_text)


@router.message(F.text == "📜 Моя история")
async def history_handler(message: Message) -> Any:
    """Обработка запроса истории предсказаний."""
    user = message.from_user
    if not user:
        return

    async for session in db_manager.get_session():
        user_repo = UserRepository(session)
        prediction_repo = PredictionRepository(session)

        # Get user
        db_user = await user_repo.get_user_by_telegram_id(user.id, source=_SOURCE)
        if not db_user:
            await message.answer(texts.NO_USER_FOR_HISTORY)
            return

        # Get user's predictions (limit to 5 as per requirements)
        predictions = await prediction_repo.get_user_predictions(db_user.id, limit=5)

        if not predictions:
            await message.answer(texts.EMPTY_HISTORY)
            return

        # Format history with proper numbering and dates
        history_text = f"📜 Ваши последние предсказания ({len(predictions)} из 5):\n\n"

        for i, prediction in enumerate(predictions, 1):
            # Format date in Russian locale style
            date_str = prediction.created_at.strftime("%d.%m.%Y в %H:%M")
            history_text += f"🔮 {i}. {date_str}\n"
            # Convert stored prediction from markdown to HTML
            formatted_pred = markdown_to_telegram_html(prediction.prediction_text)
            history_text += f"{formatted_pred}\n"
            history_text += "─" * 30 + "\n\n"

        # Remove last separator
        history_text = history_text.rstrip("─" * 30 + "\n\n")

        # Split message if too long (Telegram limit: 4096 chars)
        chunks = split_message(history_text)
        for chunk in chunks:
            await message.answer(chunk, parse_mode="HTML")


@router.message(F.text == "ℹ️ Об Оракуле")
async def about_handler(message: Message) -> Any:
    """Обработка запроса информации о боте."""
    about_text = await get_bot_text("about_text", texts.ABOUT_TEXT_FALLBACK)
    await message.answer(about_text)


@router.message(F.photo)
async def photo_handler(
    message: Message,
    bot: Bot,
    media_group_photos: list = None,
    is_media_group: bool = False,
    media_group_caption: str = None,
) -> Any:
    """Обработка фотографий для предсказания."""
    user = message.from_user
    if not user or not message.photo:
        return

    # Check subscription status before processing
    async for session in db_manager.get_session():
        user_repo = UserRepository(session)
        subscription_repo = SubscriptionRepository(session)

        # Get or create user first
        db_user = await user_repo.get_user_by_telegram_id(user.id, source=_SOURCE)
        if not db_user:
            db_user = await user_repo.create_user(
                telegram_id=user.id,
                username=user.username,
                full_name=user.full_name or f"{user.first_name} {user.last_name or ''}".strip(),
                source=_SOURCE,
            )

        # Check if user can make a prediction
        can_predict, reason = await subscription_repo.can_make_prediction(db_user.id)

        if not can_predict:
            # User has exhausted free predictions - show paywall
            try:
                # Get subscription price
                settings_repo = SettingsRepository(session)
                price_str = await settings_repo.get_setting("subscription_price")
                price = int(float(price_str)) if price_str else 300

                keyboard = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="⭐ Оформить подписку", callback_data="start_payment")],
                    [InlineKeyboardButton(text="◀️ Назад в меню", callback_data="back_to_menu")],
                ])
                await message.answer(
                    texts.paywall_text(reason, price),
                    reply_markup=keyboard,
                )

            except Exception as e:
                logger.error("Ошибка отображения paywall: %s", e)
                await message.answer(
                    f"{reason}\n\n{texts.PAYWALL_PAYMENT_UNAVAILABLE}"
                )
            return

    # Get photos to process (from middleware or single photo)
    photos_to_process = media_group_photos or [message]

    # Show typing indicator
    await bot.send_chat_action(chat_id=message.chat.id, action=ChatAction.TYPING)

    # Get processing message from settings
    processing_text = await get_bot_text(
        "processing_message", texts.PROCESSING_MESSAGE_FALLBACK,
    )

    # Adjust message for multiple photos
    if is_media_group and len(photos_to_process) > 1:
        processing_text = texts.processing_message_multiple(len(photos_to_process))

    processing_msg = await message.answer(processing_text)

    # Get user's caption/question if provided
    user_message = media_group_caption or (message.caption.strip() if message.caption else None)

    try:
        # Initialize photo processor
        photo_processor = PhotoProcessor(bot)

        # Check setting for multiple photos
        analyze_all = await get_bot_text("analyze_all_photos", "true")
        analyze_all = analyze_all.lower() == "true"

        # Collect photos to analyze
        if is_media_group and len(photos_to_process) > 1 and analyze_all:
            # Process multiple photos
            valid_photos = []
            for photo_msg in photos_to_process:
                if photo_processor.is_valid_photo(photo_msg.photo):
                    valid_photos.append(photo_processor.get_best_photo_size(photo_msg.photo))

            if not valid_photos:
                await processing_msg.edit_text(texts.ALL_PHOTOS_INVALID)
                return

            # Process multiple photos
            try:
                prediction_text, photos_data = await photo_processor.process_multiple_photos(
                    valid_photos,
                    user_message=user_message,
                    username=user.first_name
                )
            except (PhotoProcessingError, OpenAIError) as e:
                await processing_msg.edit_text(format_error_message(e, user_friendly=True))
                return
        else:
            # Process single photo (first one)
            first_photo_msg = photos_to_process[0]

            if not photo_processor.is_valid_photo(first_photo_msg.photo):
                await processing_msg.edit_text(texts.PHOTO_TOO_LARGE)
                return

            best_photo = photo_processor.get_best_photo_size(first_photo_msg.photo)

            try:
                prediction_text, photo_path = await photo_processor.process_photo(
                    best_photo,
                    user_message=user_message,
                    username=user.first_name
                )
                # Create photos_data list for consistency
                photos_data = []
                if photo_path:
                    photos_data.append({
                        "file_path": photo_path,
                        "file_id": best_photo.file_id
                    })
            except (PhotoProcessingError, OpenAIError) as e:
                await processing_msg.edit_text(format_error_message(e, user_friendly=True))
                return

        if not prediction_text:
            await processing_msg.edit_text(texts.PREDICTION_FAILED)
            return

        # Get photo file_id for saving (use first valid photo)
        photo_file_id = photos_data[0]["file_id"] if photos_data else "unknown"
        photo_path = photos_data[0]["file_path"] if photos_data else None

        # Save to database
        try:
            async for session in db_manager.get_session():
                user_repo = UserRepository(session)
                prediction_repo = PredictionRepository(session)

                # Get or create user
                db_user = await user_repo.get_user_by_telegram_id(user.id, source=_SOURCE)
                if not db_user:
                    db_user = await user_repo.create_user(
                        telegram_id=user.id,
                        username=user.username,
                        full_name=user.full_name or f"{user.first_name} {user.last_name or ''}".strip(),
                        source=_SOURCE,
                    )

                # Save prediction
                await prediction_repo.create_prediction(
                    user_id=db_user.id,
                    photo_file_id=photo_file_id,
                    prediction_text=prediction_text,
                    photo_path=photo_path,
                    user_request=user_message,
                    photos=photos_data,
                    subscription_type=db_user.subscription_type
                )
        except Exception as e:
            logger.error("Ошибка сохранения предсказания в БД: %s", e)
            # Still send prediction to user even if saving fails
            await processing_msg.edit_text(
                f"{prediction_text}{texts.PREDICTION_NOT_SAVED}"
            )
            return

        # Send prediction to user with action buttons
        # Convert markdown to Telegram HTML format
        formatted_prediction = markdown_to_telegram_html(prediction_text)

        # Split if too long (Telegram limit: 4096 chars)
        chunks = split_message(formatted_prediction)

        async def send_with_fallback(msg_func, text, **kwargs):
            """Отправка с HTML, fallback на plain text при ошибке парсинга."""
            try:
                return await msg_func(text, **kwargs)
            except Exception as e:
                if "parse entities" in str(e).lower() or "can't parse" in str(e).lower():
                    # HTML parsing failed, send as plain text
                    logger.warning("Ошибка парсинга HTML, отправка plain text: %s", e)
                    plain_text = strip_html_tags(text)
                    kwargs.pop('parse_mode', None)
                    return await msg_func(plain_text, **kwargs)
                raise

        try:
            if len(chunks) == 1:
                await send_with_fallback(
                    processing_msg.edit_text,
                    formatted_prediction,
                    reply_markup=KeyboardManager.get_prediction_actions(),
                    parse_mode="HTML"
                )
            else:
                # Edit first message, send rest as new, last one with buttons
                await send_with_fallback(processing_msg.edit_text, chunks[0], parse_mode="HTML")
                for chunk in chunks[1:-1]:
                    await send_with_fallback(message.answer, chunk, parse_mode="HTML")
                await send_with_fallback(
                    message.answer,
                    chunks[-1],
                    reply_markup=KeyboardManager.get_prediction_actions(),
                    parse_mode="HTML"
                )
        except Exception as e:
            # Final fallback - send completely plain text
            logger.error("Не удалось отправить форматированное предсказание: %s", e)
            plain_text = strip_html_tags(formatted_prediction)
            chunks = split_message(plain_text)
            await processing_msg.edit_text(chunks[0])
            for chunk in chunks[1:]:
                await message.answer(chunk)
            await message.answer(
                texts.PREDICTION_ABOVE,
                reply_markup=KeyboardManager.get_prediction_actions()
            )

    except Exception as e:
        logger.error(
            "Ошибка в photo_handler: user_id=%s, username=%s, chat_id=%s, "
            "is_media_group=%s, error_type=%s, error=%s",
            user.id if user else "unknown",
            user.username if user else "unknown",
            message.chat.id,
            is_media_group,
            type(e).__name__,
            e,
            exc_info=True,
        )
        await processing_msg.edit_text(texts.PHOTO_PROCESSING_ERROR)


@router.message(F.content_type.in_({"document", "video", "audio", "voice", "sticker"}))
async def non_photo_handler(message: Message) -> Any:
    """Обработка нефото контента."""
    await message.answer(texts.NON_PHOTO_CONTENT)


@router.message(F.text == "🎯 Случайное предсказание")
async def random_prediction_handler(message: Message) -> Any:
    """Обработка запроса случайного предсказания."""
    prediction = random.choice(texts.RANDOM_PREDICTIONS)
    await message.answer(
        f"{texts.RANDOM_PREDICTION_HEADER}{prediction}",
        reply_markup=KeyboardManager.get_prediction_actions()
    )


@router.message(F.text == "❓ Частые вопросы")
async def faq_handler(message: Message) -> Any:
    """Обработка кнопки «Частые вопросы» — показ FAQ напрямую."""
    faq_text = texts.HELP_SECTIONS.get("faq", "Информация не найдена")
    await message.answer(faq_text)


@router.message(F.text == "🗑️ Очистить историю")
async def clear_history_handler(message: Message) -> Any:
    """Обработка запроса очистки истории."""
    await message.answer(
        texts.CLEAR_HISTORY_CONFIRM,
        reply_markup=KeyboardManager.get_confirmation_keyboard("clear_history")
    )


@router.message(F.text == "📞 Поддержка")
async def support_handler(message: Message) -> Any:
    """Обработка запроса поддержки."""
    await message.answer(texts.SUPPORT_TEXT)


@router.message(Command("menu"))
async def menu_handler(message: Message) -> Any:
    """Обработка команды /menu."""
    await message.answer(
        texts.MAIN_MENU_TEXT,
        reply_markup=KeyboardManager.get_main_menu()
    )


@router.message(Command("random"))
async def random_command_handler(message: Message) -> Any:
    """Обработка команды /random."""
    await random_prediction_handler(message)


@router.message(Command("stats"))
async def stats_command_handler(message: Message) -> Any:
    """Обработка команды /stats (скрытая)."""
    async for session in db_manager.get_session():
        prediction_repo = PredictionRepository(session)

        predictions_count = await prediction_repo.get_predictions_count()
        photos_count = await prediction_repo.get_photos_count()

        await message.answer(
            f"📊 Статистика:\n\n"
            f"🔮 Всего предсказаний: {predictions_count}\n"
            f"📸 Всего фото в базе: {photos_count}"
        )


@router.message(Command("clear"))
async def clear_command_handler(message: Message) -> Any:
    """Обработка команды /clear."""
    await clear_history_handler(message)


@router.message(Command("predict"))
async def predict_command_handler(message: Message) -> Any:
    """Обработка команды /predict."""
    await prediction_request_handler(message)


@router.message(Command("history"))
async def history_command_handler(message: Message) -> Any:
    """Обработка команды /history."""
    await history_handler(message)


@router.message(Command("about"))
async def about_command_handler(message: Message) -> Any:
    """Обработка команды /about."""
    await about_handler(message)


@router.message(Command("support"))
async def support_command_handler(message: Message) -> Any:
    """Обработка команды /support."""
    await support_handler(message)


@router.message(Command("subscribe"))
async def subscribe_command_handler(message: Message) -> Any:
    """Обработка команды /subscribe."""
    await subscription_handler(message)


@router.message(Command("update_menu"))
async def update_menu_command_handler(message: Message, bot: Bot) -> Any:
    """Обработка команды /update_menu — принудительное обновление меню."""
    try:
        commands = [
            BotCommand(command="start", description="🔮 Начать работу с ботом"),
            BotCommand(command="help", description="❓ Частые вопросы"),
            BotCommand(command="predict", description="🔮 Получить предсказание"),
            BotCommand(command="history", description="📜 Моя история"),
            BotCommand(command="random", description="🎯 Случайное предсказание"),
            BotCommand(command="about", description="ℹ️ Об Оракуле"),
            BotCommand(command="clear", description="🗑️ Очистить историю"),
            BotCommand(command="support", description="📞 Поддержка"),
        ]

        await bot.set_my_commands(commands)
        await message.answer(texts.BOT_COMMANDS_UPDATED)

    except Exception as e:
        logger.error("Ошибка обновления команд меню: %s", e)
        await message.answer(texts.BOT_COMMANDS_UPDATE_ERROR)


# Callback handlers
@router.callback_query(F.data == "back_to_menu")
async def back_to_menu_callback(callback: CallbackQuery, state: FSMContext) -> Any:
    """Обработка callback возврата в меню."""
    await state.clear()
    await callback.message.edit_text(texts.MAIN_MENU_EDIT_TEXT)
    await callback.answer()


@router.callback_query(F.data == "new_prediction")
async def new_prediction_callback(callback: CallbackQuery) -> Any:
    """Обработка callback нового предсказания."""
    # Send as a new message to keep the prediction visible
    await callback.message.answer(texts.NEW_PREDICTION_INSTRUCTION)
    await callback.answer()


@router.callback_query(F.data == "show_history")
async def show_history_callback(callback: CallbackQuery) -> Any:
    """Обработка callback показа истории."""
    user = callback.from_user
    if not user:
        await callback.answer()
        return

    async for session in db_manager.get_session():
        user_repo = UserRepository(session)
        prediction_repo = PredictionRepository(session)

        # Get user
        db_user = await user_repo.get_user_by_telegram_id(user.id, source=_SOURCE)
        if not db_user:
            await callback.message.answer(texts.NO_USER_FOR_HISTORY)
            await callback.answer()
            return

        # Get user's predictions (limit to 5 as per requirements)
        predictions = await prediction_repo.get_user_predictions(db_user.id, limit=5)

        if not predictions:
            await callback.message.answer(texts.EMPTY_HISTORY)
            await callback.answer()
            return

        # Format history with proper numbering and dates
        history_text = f"📜 Ваши последние предсказания ({len(predictions)} из 5):\n\n"

        for i, prediction in enumerate(predictions, 1):
            # Format date in Russian locale style
            date_str = prediction.created_at.strftime("%d.%m.%Y в %H:%M")
            history_text += f"🔮 {i}. {date_str}\n"
            # Convert stored prediction from markdown to HTML
            formatted_pred = markdown_to_telegram_html(prediction.prediction_text)
            history_text += f"{formatted_pred}\n"
            history_text += "─" * 30 + "\n\n"

        # Remove last separator
        history_text = history_text.rstrip("─" * 30 + "\n\n")

        # Split message if too long (Telegram limit: 4096 chars)
        chunks = split_message(history_text)

        # Send all chunks as new messages to keep the prediction visible
        for chunk in chunks:
            await callback.message.answer(chunk, parse_mode="HTML")

    await callback.answer()


@router.callback_query(F.data == "share_prediction")
async def share_prediction_callback(callback: CallbackQuery) -> Any:
    """Обработка callback «Поделиться предсказанием»."""
    # Send instructions as a separate message, keeping the prediction visible
    await callback.message.answer(texts.SHARE_PREDICTION)
    await callback.answer()


@router.callback_query(F.data.startswith("help_"))
async def help_callback(callback: CallbackQuery) -> Any:
    """Обработка callback разделов помощи (обратная совместимость).

    Если пользователь нажмёт старую кнопку из кэша — покажем текст раздела.
    """
    help_type = callback.data.split("_")[1]
    text = texts.HELP_SECTIONS.get(help_type, "Информация не найдена")
    await callback.message.edit_text(text)
    await callback.answer()


@router.callback_query(F.data == "cancel_subscription")
async def cancel_subscription_callback(callback: CallbackQuery) -> Any:
    """Запрос подтверждения отмены подписки."""
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Да, отменить подписку", callback_data="confirm_cancel_sub")],
        [InlineKeyboardButton(text="◀️ Нет, вернуться", callback_data="subscription_status")]
    ])
    await callback.message.edit_text(
        texts.CANCEL_SUBSCRIPTION_CONFIRM,
        reply_markup=keyboard,
    )
    await callback.answer()


@router.callback_query(F.data == "confirm_cancel_sub")
async def confirm_cancel_subscription_callback(callback: CallbackQuery) -> Any:
    """Обработка подтверждённой отмены подписки."""
    user = callback.from_user
    if not user:
        await callback.answer()
        return

    try:
        async for session in db_manager.get_session():
            user_repo = UserRepository(session)
            subscription_repo = SubscriptionRepository(session)

            db_user = await user_repo.get_user_by_telegram_id(user.id, source=_SOURCE)
            if not db_user:
                await callback.message.edit_text(texts.USER_NOT_FOUND)
                await callback.answer()
                return

            await subscription_repo.disable_recurring_payment(db_user.id)

            status = await subscription_repo.get_subscription_status(db_user.id)
            until = status.get("until", "")[:10] if status.get("until") else ""

        await callback.message.edit_text(
            texts.cancel_subscription_success(until),
            reply_markup=KeyboardManager.get_subscription_status_keyboard(
                has_active_subscription=bool(until),
                is_vip=False,
                recurring_enabled=False,
            )
        )
        await callback.answer("Автопродление отключено", show_alert=False)
        return
    except Exception as e:
        logger.error("Ошибка отмены подписки: %s", e)
        await callback.message.edit_text(
            texts.CANCEL_SUBSCRIPTION_ERROR,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔄 Попробовать снова", callback_data="cancel_subscription")],
                [InlineKeyboardButton(text="◀️ В меню", callback_data="back_to_menu")]
            ])
        )

    await callback.answer()


@router.callback_query(F.data.startswith("confirm_"))
async def confirm_callback(callback: CallbackQuery) -> Any:
    """Обработка callback подтверждения действий."""
    action = callback.data.split("_")[1]

    if action == "clear_history":
        user = callback.from_user
        if user:
            try:
                async for session in db_manager.get_session():
                    user_repo = UserRepository(session)

                    # Get user
                    db_user = await user_repo.get_user_by_telegram_id(user.id, source=_SOURCE)
                    if db_user:
                        # Delete all user predictions using raw SQL for simplicity
                        from sqlalchemy import text
                        await session.execute(
                            text("DELETE FROM predictions WHERE user_id = :user_id"),
                            {"user_id": db_user.id}
                        )
                        await session.commit()

                await callback.message.edit_text(texts.CLEAR_HISTORY_SUCCESS)
            except Exception as e:
                logger.error("Ошибка очистки истории: %s", e)
                await callback.message.edit_text(texts.CLEAR_HISTORY_ERROR)

    await callback.answer()


@router.callback_query(F.data == "cancel_action")
async def cancel_callback(callback: CallbackQuery) -> Any:
    """Обработка callback отмены действия."""
    await callback.message.edit_text(texts.ACTION_CANCELLED)
    await callback.answer()


# ===== Subscription Handlers =====

@router.message(F.text == "💎 Подписка")
async def subscription_handler(message: Message) -> Any:
    """Обработка запроса статуса подписки."""
    user = message.from_user
    if not user:
        return

    async for session in db_manager.get_session():
        user_repo = UserRepository(session)
        subscription_repo = SubscriptionRepository(session)
        settings_repo = SettingsRepository(session)

        db_user = await user_repo.get_user_by_telegram_id(user.id, source=_SOURCE)
        if not db_user:
            db_user = await user_repo.create_user(
                telegram_id=user.id,
                username=user.username,
                full_name=user.full_name or f"{user.first_name} {user.last_name or ''}".strip(),
                source=_SOURCE,
            )

        status = await subscription_repo.get_subscription_status(db_user.id)
        price_str = await settings_repo.get_setting("subscription_price")
        price = int(float(price_str)) if price_str else 300

        if status["type"] == "vip":
            status_text = texts.subscription_status_vip(status.get("vip_reason"))
        elif status["type"] == "premium" and status["active"]:
            status_text = texts.subscription_status_premium(status["until"][:10])
        else:
            remaining = status.get("predictions_remaining", 0)
            used = status.get("predictions_used", 0)
            limit = status.get("predictions_limit", 10)
            status_text = texts.subscription_status_free(used, limit, price)

        has_active = (status["type"] == "vip") or (status["type"] == "premium" and status["active"])
        is_vip = status["type"] == "vip"
        recurring_enabled, _ = await subscription_repo.is_recurring_enabled(db_user.id)

        if has_active and not is_vip and not recurring_enabled:
            status_text += texts.SUBSCRIPTION_RECURRING_OFF_WARNING

        await message.answer(
            status_text,
            reply_markup=KeyboardManager.get_subscription_status_keyboard(
                has_active_subscription=has_active,
                is_vip=is_vip,
                recurring_enabled=recurring_enabled,
            )
        )


@router.callback_query(F.data == "subscription_status")
async def subscription_status_callback(callback: CallbackQuery) -> Any:
    """Обработка callback статуса подписки."""
    user = callback.from_user
    if not user:
        await callback.answer()
        return

    async for session in db_manager.get_session():
        user_repo = UserRepository(session)
        subscription_repo = SubscriptionRepository(session)
        settings_repo = SettingsRepository(session)

        db_user = await user_repo.get_user_by_telegram_id(user.id, source=_SOURCE)
        if not db_user:
            await callback.message.edit_text(texts.USER_NOT_FOUND)
            await callback.answer()
            return

        status = await subscription_repo.get_subscription_status(db_user.id)
        price_str = await settings_repo.get_setting("subscription_price")
        price = int(float(price_str)) if price_str else 300

        # Check if recurring payment is enabled
        recurring_enabled, recurring_charge_id = await subscription_repo.is_recurring_enabled(db_user.id)

        if status["type"] == "vip":
            status_text = f"✨ Статус: VIP ⭐\nТебе открыты все тайны!"
        elif status["type"] == "premium" and status["active"]:
            renewal_info = "\n🔄 Автопродление: включено" if recurring_enabled else "\n⚠️ Автопродление: выключено"
            status_text = f"✨ Статус: Премиум 💫\nМагия до: {status['until'][:10]}{renewal_info}"
        else:
            remaining = status.get("predictions_remaining", 0)
            used = status.get("predictions_used", 0)
            limit = status.get("predictions_limit", 10)
            status_text = f"☕ Гость Оракула\n🎁 Использовано: {used}/{limit}\n💰 Подписка: {price}₽/мес"

        has_active = (status["type"] == "vip") or (status["type"] == "premium" and status["active"])
        is_vip = status["type"] == "vip"

        if has_active and not is_vip and not recurring_enabled:
            status_text += texts.SUBSCRIPTION_RECURRING_OFF_SHORT

        await callback.message.edit_text(
            status_text,
            reply_markup=KeyboardManager.get_subscription_status_keyboard(
                has_active_subscription=has_active,
                is_vip=is_vip,
                recurring_enabled=recurring_enabled,
            )
        )

    await callback.answer()


async def _poll_payment_and_activate(
    bot: Bot,
    chat_id: int,
    telegram_user_id: int,
    payment_id: str,
    message_id: int,
) -> None:
    """Фоновая задача: polling YooKassa до завершения платежа."""
    from coffee_oracle.services.payment_service import get_payment_service

    payment_service = get_payment_service()
    if payment_service is None:
        return

    # Polling schedule: wait 15s, 30s, 60s, 120s (total ~225s ≈ 3.5 min)
    delays = [15, 30, 60, 120]

    for delay in delays:
        await asyncio.sleep(delay)

        # If user already confirmed manually, pending will be cleared
        if payment_service.get_pending_payment(telegram_user_id) != payment_id:
            return

        try:
            status_result = await payment_service.get_payment_status(payment_id)
        except Exception as exc:
            logger.warning("Ошибка фонового polling для %s: %s", payment_id, exc)
            continue

        if not status_result.get("success"):
            continue

        status = status_result.get("status")
        paid = status_result.get("paid", False)

        if status == "succeeded" and paid:
            # Activate subscription
            try:
                async for session in db_manager.get_session():
                    user_repo = UserRepository(session)
                    sub_repo = SubscriptionRepository(session)

                    db_user = await user_repo.get_user_by_telegram_id(
                        telegram_user_id, source=_SOURCE,
                    )
                    if not db_user:
                        return

                    await sub_repo.activate_premium(db_user.id)

                    payment_method_saved = status_result.get("payment_method_saved", False)
                    payment_method_id = status_result.get("payment_method_id")
                    if payment_method_saved and payment_method_id:
                        await sub_repo.enable_recurring_payment(db_user.id, payment_method_id)

                    await sub_repo.update_payment_status(payment_id, "succeeded")

                payment_service.clear_pending_payment(telegram_user_id)

                recurring_enabled = bool(
                    status_result.get("payment_method_saved")
                    and status_result.get("payment_method_id")
                )
                success_text = (
                    texts.PAYMENT_SUCCESS_RECURRING if recurring_enabled
                    else texts.PAYMENT_SUCCESS
                )

                try:
                    await bot.edit_message_text(
                        chat_id=chat_id,
                        message_id=message_id,
                        text=success_text,
                        reply_markup=KeyboardManager.get_subscription_status_keyboard(
                            has_active_subscription=True,
                            recurring_enabled=recurring_enabled,
                        ),
                    )
                except Exception:
                    # Message may have been already edited by manual check
                    await bot.send_message(
                        chat_id=chat_id,
                        text=success_text,
                        reply_markup=KeyboardManager.get_subscription_status_keyboard(
                            has_active_subscription=True,
                            recurring_enabled=recurring_enabled,
                        ),
                    )
            except Exception as exc:
                logger.error("Ошибка активации подписки при polling: %s", exc)
            return

        if status == "canceled":
            try:
                async for session in db_manager.get_session():
                    sub_repo = SubscriptionRepository(session)
                    await sub_repo.update_payment_status(payment_id, "canceled")

                payment_service.clear_pending_payment(telegram_user_id)

                try:
                    await bot.edit_message_text(
                        chat_id=chat_id,
                        message_id=message_id,
                        text=texts.PAYMENT_CANCELLED,
                        reply_markup=KeyboardManager.get_subscription_status_keyboard(
                            has_active_subscription=False,
                        ),
                    )
                except Exception:
                    await bot.send_message(
                        chat_id=chat_id,
                        text=texts.PAYMENT_CANCELLED,
                        reply_markup=KeyboardManager.get_subscription_status_keyboard(
                            has_active_subscription=False,
                        ),
                    )
            except Exception as exc:
                logger.error("Ошибка обработки отмены при polling: %s", exc)
            return

    # Exhausted all attempts — payment still pending, user can use the button
    logger.info("Фоновый polling исчерпан для платежа %s, пользователь %s", payment_id, telegram_user_id)


@router.callback_query(F.data == "start_payment")
async def start_payment_callback(callback: CallbackQuery, bot: Bot, state: FSMContext) -> Any:
    """Обработка callback начала оплаты — запрос email."""
    user = callback.from_user
    if not user:
        await callback.answer()
        return

    from coffee_oracle.services.payment_service import get_payment_service

    payment_service = get_payment_service()
    if payment_service is None:
        await callback.message.edit_text(texts.PAYMENT_UNAVAILABLE)
        await callback.answer()
        return

    await state.set_state(PaymentStates.waiting_for_email)

    back_keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Назад в меню", callback_data="back_to_menu")],
    ])

    await callback.message.edit_text(
        texts.EMAIL_REQUEST,
        reply_markup=back_keyboard,
    )
    await callback.answer()


async def _create_payment_and_respond(
    bot: Bot,
    chat_id: int,
    telegram_user_id: int,
    user_email: Optional[str],
    state: FSMContext,
) -> None:
    """Общая логика: создание платежа YooKassa и отправка ссылки."""
    from coffee_oracle.services.payment_service import get_payment_service

    await state.clear()

    payment_service = get_payment_service()
    if payment_service is None:
        await bot.send_message(chat_id, texts.PAYMENT_UNAVAILABLE)
        return

    async for session in db_manager.get_session():
        user_repo = UserRepository(session)
        settings_repo = SettingsRepository(session)
        sub_repo = SubscriptionRepository(session)

        db_user = await user_repo.get_user_by_telegram_id(
            telegram_user_id, source=_SOURCE,
        )
        if not db_user:
            await bot.send_message(chat_id, texts.USER_NOT_FOUND)
            return

        # Save email for future recurring payments (54-ФЗ receipts)
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
                user_id=telegram_user_id,
                user_email=user_email,
            )

            if not result.get("success"):
                error_msg = result.get("error", "Неизвестная ошибка")
                logger.error("Ошибка создания платежа YooKassa: %s", error_msg)
                await bot.send_message(chat_id, texts.PAYMENT_CREATE_ERROR)
                return

            payment_id = result["payment_id"]
            confirmation_url = result["confirmation_url"]
            label = result["label"]
            is_recurring = result.get("recurring", False)

            await sub_repo.create_payment(
                user_id=db_user.id,
                amount=price_kopecks,
                label=label,
                payment_id=payment_id,
            )

            payment_service.set_pending_payment(telegram_user_id, payment_id)

            recurring_note = "" if is_recurring else texts.RECURRING_UNAVAILABLE_NOTE

            sent = await bot.send_message(
                chat_id,
                texts.payment_link_text_html(price, config.domain, recurring_note),
                reply_markup=KeyboardManager.get_subscription_keyboard(payment_url=confirmation_url),
                parse_mode="HTML",
            )

            asyncio.create_task(
                _poll_payment_and_activate(
                    bot=bot,
                    chat_id=chat_id,
                    telegram_user_id=telegram_user_id,
                    payment_id=payment_id,
                    message_id=sent.message_id,
                )
            )

        except Exception as e:
            logger.error("Непредвиденная ошибка в потоке оплаты: %s", e)
            try:
                await bot.send_message(chat_id, texts.PAYMENT_UNEXPECTED_ERROR)
            except Exception:
                pass


@router.message(PaymentStates.waiting_for_email)
async def email_input_handler(message: Message, bot: Bot, state: FSMContext) -> Any:
    """Валидация email и переход к созданию платежа."""
    email = message.text.strip() if message.text else ""

    if not EMAIL_RE.match(email):
        back_keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ Назад в меню", callback_data="back_to_menu")],
        ])
        await message.answer(
            texts.EMAIL_INVALID,
            reply_markup=back_keyboard,
        )
        return

    await message.answer(texts.email_confirmed(email))
    await _create_payment_and_respond(
        bot=bot,
        chat_id=message.chat.id,
        telegram_user_id=message.from_user.id,
        user_email=email,
        state=state,
    )


@router.callback_query(F.data == "check_payment")
async def check_payment_callback(callback: CallbackQuery) -> Any:
    """Обработка callback проверки статуса платежа."""
    user = callback.from_user
    if not user:
        await callback.answer()
        return

    from coffee_oracle.services.payment_service import get_payment_service

    payment_service = get_payment_service()
    if payment_service is None:
        await callback.message.edit_text(texts.PAYMENT_UNAVAILABLE)
        await callback.answer()
        return

    # Get pending payment for this user
    payment_id = payment_service.get_pending_payment(user.id)
    if not payment_id:
        await callback.message.edit_text(texts.NO_PENDING_PAYMENTS)
        await callback.answer()
        return

    async for session in db_manager.get_session():
        user_repo = UserRepository(session)
        sub_repo = SubscriptionRepository(session)

        db_user = await user_repo.get_user_by_telegram_id(user.id, source=_SOURCE)
        if not db_user:
            await callback.message.edit_text(texts.USER_NOT_FOUND)
            await callback.answer()
            return

        try:
            status_result = await payment_service.get_payment_status(payment_id)

            if not status_result.get("success"):
                logger.error("Ошибка получения статуса платежа: %s", status_result.get("error"))
                await callback.message.edit_text(texts.PAYMENT_STATUS_CHECK_FAILED)
                await callback.answer()
                return

            status = status_result.get("status")
            paid = status_result.get("paid", False)

            if status == "succeeded" and paid:
                # Activate premium subscription for 1 month
                await sub_repo.activate_premium(db_user.id)

                # Save payment method and enable recurring if method was saved
                payment_method_saved = status_result.get("payment_method_saved", False)
                payment_method_id = status_result.get("payment_method_id")
                if payment_method_saved and payment_method_id:
                    await sub_repo.enable_recurring_payment(db_user.id, payment_method_id)

                # Update payment status in DB
                await sub_repo.update_payment_status(payment_id, "succeeded")

                # Clear pending payment
                payment_service.clear_pending_payment(user.id)

                recurring_enabled = bool(payment_method_saved and payment_method_id)
                success_text = (
                    texts.PAYMENT_SUCCESS_RECURRING if recurring_enabled
                    else texts.PAYMENT_SUCCESS
                )

                await callback.message.edit_text(
                    success_text,
                    reply_markup=KeyboardManager.get_subscription_status_keyboard(
                        has_active_subscription=True,
                        recurring_enabled=recurring_enabled,
                    ),
                )

            elif status == "pending":
                await callback.message.edit_text(
                    texts.PAYMENT_PENDING,
                    reply_markup=KeyboardManager.get_subscription_keyboard(),
                )

            elif status == "canceled":
                # Update payment status in DB
                await sub_repo.update_payment_status(payment_id, "canceled")

                # Clear pending payment
                payment_service.clear_pending_payment(user.id)

                await callback.message.edit_text(
                    texts.PAYMENT_CANCELLED,
                    reply_markup=KeyboardManager.get_subscription_status_keyboard(
                        has_active_subscription=False,
                    ),
                )

            else:
                await callback.message.edit_text(
                    texts.payment_status_unknown(status),
                    reply_markup=KeyboardManager.get_subscription_keyboard(),
                )

        except Exception as e:
            logger.error("Непредвиденная ошибка проверки платежа: %s", e)
            try:
                await callback.message.edit_text(texts.PAYMENT_CHECK_ERROR)
            except Exception:
                pass

    await callback.answer()


@router.message(F.text & ~F.text.in_([
    "🔮 Получить предсказание", "📜 Моя история", "ℹ️ Об Оракуле",
    "🎯 Случайное предсказание", "❓ Частые вопросы", "🗑️ Очистить историю",
    "📞 Поддержка", "💎 Подписка"
]))
async def text_handler(message: Message) -> Any:
    """Обработка прочих текстовых сообщений."""
    await message.answer(
        texts.UNKNOWN_TEXT_MESSAGE,
        reply_markup=KeyboardManager.get_main_menu_with_subscription()
    )
