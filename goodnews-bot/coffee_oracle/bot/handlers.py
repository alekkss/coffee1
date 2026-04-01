"""Bot message handlers."""

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
from coffee_oracle.config import config
from coffee_oracle.database.connection import db_manager
from coffee_oracle.database.repositories import PredictionRepository, SettingsRepository, SubscriptionRepository, UserRepository
from coffee_oracle.services.photo_processor import PhotoProcessor
from coffee_oracle.utils.errors import PhotoProcessingError, OpenAIError, format_error_message
from coffee_oracle.utils.telegram import split_message, markdown_to_telegram_html, strip_html_tags

logger = logging.getLogger(__name__)

router = Router()

EMAIL_RE = re.compile(r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$")


class PaymentStates(StatesGroup):
    waiting_for_email = State()


async def get_bot_text(key: str, default: str) -> str:
    """Get text from settings or return default."""
    try:
        async for session in db_manager.get_session():
            settings_repo = SettingsRepository(session)
            value = await settings_repo.get_setting(key)
            return value if value else default
    except Exception:
        return default


@router.message(CommandStart())
async def start_handler(message: Message) -> Any:
    """Handle /start command."""
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
            full_name=user.full_name or f"{user.first_name} {user.last_name or ''}".strip()
        )
        
        # Get welcome message from settings
        welcome_template = await settings_repo.get_setting("welcome_message")
        if not welcome_template:
            welcome_template = """🔮 Добро пожаловать в мир Кофейного Оракула, {name}!

Я — добрый мистический дух, живущий в узорах кофейной гущи. Присылай фото дна чашки после утреннего кофе, и я поделюсь с тобой своей мудростью ✨

☕ Первые гадания — мои подарок тебе!
Потом, если захочешь продолжить наше магическое путешествие, можно оформить подписку.

🌟 Мои предсказания всегда несут свет и вдохновение!

Выбери действие в меню:"""
        
        welcome_text = welcome_template.replace("{name}", db_user.full_name)
        
        await message.answer(
            welcome_text,
            reply_markup=KeyboardManager.get_main_menu_with_subscription()
        )


@router.message(Command("help"))
async def help_handler(message: Message) -> Any:
    """Handle /help command."""
    await message.answer(
        "📚 Искусство гадания на кофейной гуще",
        reply_markup=KeyboardManager.get_help_menu()
    )


@router.message(F.text == "🔮 Получить предсказание")
async def prediction_request_handler(message: Message) -> Any:
    """Handle prediction request."""
    instruction_text = await get_bot_text("photo_instruction", """📸 Отправьте мне фотографию дна вашей кофейной чашки!

Убедитесь, что:
• Узоры кофейной гущи хорошо видны
• Освещение достаточное
• Фото сделано сверху

Я внимательно изучу узоры и расскажу, что они предвещают! ✨""")
    
    await message.answer(instruction_text)


@router.message(F.text == "📜 Моя история")
async def history_handler(message: Message) -> Any:
    """Handle history request."""
    user = message.from_user
    if not user:
        return
    
    async for session in db_manager.get_session():
        user_repo = UserRepository(session)
        prediction_repo = PredictionRepository(session)
        
        # Get user
        db_user = await user_repo.get_user_by_telegram_id(user.id)
        if not db_user:
            await message.answer(
                "Сначала получите ваше первое предсказание! 🔮\n\n"
                "Отправьте фото кофейной чашки, и я расскажу, "
                "что говорят узоры гущи о вашем будущем!"
            )
            return
        
        # Get user's predictions (limit to 5 as per requirements)
        predictions = await prediction_repo.get_user_predictions(db_user.id, limit=5)
        
        if not predictions:
            await message.answer(
                "📜 У вас пока нет предсказаний в истории.\n\n"
                "Отправьте фото кофейной чашки с гущей, "
                "чтобы получить первое магическое предсказание! ☕✨"
            )
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


@router.message(F.text == "ℹ️ О боте")
async def about_handler(message: Message) -> Any:
    """Handle about request."""
    about_text = await get_bot_text("about_text", """🔮 Кофейный Оракул

Я — добрый магический дух, живущий в узорах кофейной гущи. С древних времён люди находили в кофе ответы на сокровенные вопросы, и я продолжаю эту прекрасную традицию.

✨ Как я работаю:
Присылай фото дна кофейной чашки — я внимательно изучу узоры и поделюсь тем, что вижу. Мои слова всегда несут свет, тепло и вдохновение!

☕ Начни знакомство:
Первые гадания — мой дар тебе. Если мои предсказания тронут твоё сердце, ты сможешь оформить подписку для безлимитных сеансов магии.

🌟 Помни: будущее создаёшь ты сам, а я лишь помогаю увидеть возможности!

С любовью, твой Кофейный Оракул ☕✨""")
    
    await message.answer(about_text)


@router.message(F.photo)
async def photo_handler(
    message: Message, 
    bot: Bot,
    media_group_photos: list = None,
    is_media_group: bool = False,
    media_group_caption: str = None,
) -> Any:
    """Handle photo messages for prediction."""
    user = message.from_user
    if not user or not message.photo:
        return
    
    # Check subscription status before processing
    async for session in db_manager.get_session():
        user_repo = UserRepository(session)
        subscription_repo = SubscriptionRepository(session)
        
        # Get or create user first
        db_user = await user_repo.get_user_by_telegram_id(user.id)
        if not db_user:
            db_user = await user_repo.create_user(
                telegram_id=user.id,
                username=user.username,
                full_name=user.full_name or f"{user.first_name} {user.last_name or ''}".strip()
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

                paywall_text = (
                    f"{reason}\n\n"
                    "✨ Хочешь продолжить наше магическое путешествие?\n\n"
                    "Оформи подписку и получи:\n"
                    "• Безлимитные сеансы магии\n"
                    "• Безграничную мудрость Оракула\n"
                    "• Поддержку проекта ❤️\n\n"
                    f"💰 Стоимость: {price}₽/мес"
                )
                keyboard = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="⭐ Оформить подписку", callback_data="start_payment")],
                    [InlineKeyboardButton(text="◀️ Назад в меню", callback_data="back_to_menu")],
                ])
                await message.answer(paywall_text, reply_markup=keyboard)

            except Exception as e:
                logger.error("Error showing paywall: %s", e)
                await message.answer(
                    f"{reason}\n\n"
                    "⚠️ Временно недоступна оплата. "
                    "Попробуйте /subscribe позже."
                )
            return
    
    # Get photos to process (from middleware or single photo)
    photos_to_process = media_group_photos or [message]
    
    # Show typing indicator
    await bot.send_chat_action(chat_id=message.chat.id, action=ChatAction.TYPING)
    
    # Get processing message from settings
    processing_text = await get_bot_text("processing_message", "🔮 Смотрю в чашку... Звезды открывают свои тайны... ✨")
    
    # Adjust message for multiple photos
    if is_media_group and len(photos_to_process) > 1:
        processing_text = f"🔮 Получено {len(photos_to_process)} фото. Изучаю узоры... ✨"
    
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
                await processing_msg.edit_text(
                    "📸 Все фото слишком большие или повреждены. Попробуйте отправить другие фото."
                )
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
                await processing_msg.edit_text(
                    "📸 Фото слишком большое или повреждено. Попробуйте отправить другое фото."
                )
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
            await processing_msg.edit_text(
                "🔮 Не удалось получить предсказание. Попробуйте еще раз."
            )
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
                db_user = await user_repo.get_user_by_telegram_id(user.id)
                if not db_user:
                    db_user = await user_repo.create_user(
                        telegram_id=user.id,
                        username=user.username,
                        full_name=user.full_name or f"{user.first_name} {user.last_name or ''}".strip()
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
            logger.error("Database error saving prediction: %s", e)
            # Still send prediction to user even if saving fails
            await processing_msg.edit_text(
                f"{prediction_text}\n\n⚠️ Предсказание не сохранено в истории из-за технической ошибки."
            )
            return
        
        # Send prediction to user with action buttons
        # Convert markdown to Telegram HTML format
        formatted_prediction = markdown_to_telegram_html(prediction_text)
        
        # Split if too long (Telegram limit: 4096 chars)
        chunks = split_message(formatted_prediction)
        
        async def send_with_fallback(msg_func, text, **kwargs):
            """Try to send with HTML, fallback to plain text on error."""
            try:
                return await msg_func(text, **kwargs)
            except Exception as e:
                if "parse entities" in str(e).lower() or "can't parse" in str(e).lower():
                    # HTML parsing failed, send as plain text
                    logger.warning("HTML parsing failed, sending as plain text: %s", e)
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
            logger.error("Failed to send formatted prediction: %s", e)
            plain_text = strip_html_tags(formatted_prediction)
            chunks = split_message(plain_text)
            await processing_msg.edit_text(chunks[0])
            for chunk in chunks[1:]:
                await message.answer(chunk)
            await message.answer(
                "👆 Ваше предсказание выше!",
                reply_markup=KeyboardManager.get_prediction_actions()
            )
        
    except Exception as e:
        logger.error(
            "Error in photo_handler: user_id=%s, username=%s, chat_id=%s, "
            "is_media_group=%s, error_type=%s, error=%s",
            user.id if user else "unknown",
            user.username if user else "unknown",
            message.chat.id,
            is_media_group,
            type(e).__name__,
            e,
            exc_info=True,
        )
        await processing_msg.edit_text(
            "🔮 Произошла магическая помеха. Попробуйте еще раз через несколько минут."
        )


@router.message(F.content_type.in_({"document", "video", "audio", "voice", "sticker"}))
async def non_photo_handler(message: Message) -> Any:
    """Handle non-photo content when user should send photo."""
    await message.answer(
        "📸 Пожалуйста, отправьте именно фотографию кофейной чашки с гущей.\n\n"
        "Я не могу анализировать другие типы файлов. Сделайте фото дна чашки и отправьте его как изображение! ☕"
    )


@router.message(F.text == "🎯 Случайное предсказание")
async def random_prediction_handler(message: Message) -> Any:
    """Handle random prediction request."""
    random_predictions = [
        "🌟 Сегодня звезды благоволят вашим начинаниям! Смело идите к своим целям, удача на вашей стороне.",
        "💫 Впереди вас ждет приятная встреча, которая может изменить ваш взгляд на многие вещи к лучшему.",
        "🍀 Ваша интуиция сегодня особенно сильна. Доверьтесь внутреннему голосу - он не подведет.",
        "✨ Скоро в вашу жизнь войдет что-то новое и прекрасное. Будьте открыты для перемен!",
        "🌈 После небольших трудностей вас ждет период гармонии и процветания. Не сдавайтесь!",
        "🎭 Ваши творческие способности сейчас на пике. Время воплощать смелые идеи в жизнь!",
        "🌸 Любовь и дружба окружат вас теплом. Цените близких людей - они ваша главная сила.",
        "🚀 Впереди открываются новые возможности для роста. Не бойтесь выходить из зоны комфорта!"
    ]
    
    prediction = random.choice(random_predictions)
    await message.answer(
        f"🔮 Случайное предсказание от Кофейного Оракула:\n\n{prediction}",
        reply_markup=KeyboardManager.get_prediction_actions()
    )


@router.message(F.text == "📚 Как гадать")
async def how_to_divinate_handler(message: Message) -> Any:
    """Handle how to divinate request."""
    await message.answer(
        "📚 Искусство гадания на кофейной гуще",
        reply_markup=KeyboardManager.get_help_menu()
    )


@router.message(F.text == "🗑️ Очистить историю")
async def clear_history_handler(message: Message) -> Any:
    """Handle clear history request."""
    await message.answer(
        "🗑️ Очистить историю предсказаний\n\n"
        "⚠️ Это действие нельзя отменить!\n"
        "Все ваши предсказания будут удалены навсегда.\n\n"
        "Вы уверены?",
        reply_markup=KeyboardManager.get_confirmation_keyboard("clear_history")
    )


@router.message(F.text == "📞 Поддержка")
async def support_handler(message: Message) -> Any:
    """Handle support request."""
    support_text = """📞 Поддержка Кофейного Оракула

🔮 Если у вас возникли вопросы или проблемы:

• Убедитесь, что отправляете именно фото (не файл)
• Проверьте качество освещения на фото
• Убедитесь, что гуща хорошо видна

❓ Частые вопросы:
• Бот не отвечает → Попробуйте команду /start
• Плохое предсказание → Все предсказания позитивные!
• Нет истории → Сначала получите предсказание

🛠️ Технические проблемы:
Если бот не работает, попробуйте перезапустить диалог командой /start

✨ Помните: магия требует терпения!"""
    
    await message.answer(support_text)


@router.message(Command("menu"))
async def menu_handler(message: Message) -> Any:
    """Handle /menu command."""
    await message.answer(
        "📋 Главное меню Кофейного Оракула:",
        reply_markup=KeyboardManager.get_main_menu()
    )


@router.message(Command("random"))
async def random_command_handler(message: Message) -> Any:
    """Handle /random command."""
    await random_prediction_handler(message)


@router.message(Command("stats"))
async def stats_command_handler(message: Message) -> Any:
    """Handle /stats command (hidden)."""
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
    """Handle /clear command."""
    await clear_history_handler(message)


@router.message(Command("predict"))
async def predict_command_handler(message: Message) -> Any:
    """Handle /predict command."""
    await prediction_request_handler(message)


@router.message(Command("history"))
async def history_command_handler(message: Message) -> Any:
    """Handle /history command."""
    await history_handler(message)


@router.message(Command("about"))
async def about_command_handler(message: Message) -> Any:
    """Handle /about command."""
    await about_handler(message)


@router.message(Command("support"))
async def support_command_handler(message: Message) -> Any:
    """Handle /support command."""
    await support_handler(message)


@router.message(Command("subscribe"))
async def subscribe_command_handler(message: Message) -> Any:
    """Handle /subscribe command."""
    await subscription_handler(message)


@router.message(Command("update_menu"))
async def update_menu_command_handler(message: Message, bot: Bot) -> Any:
    """Handle /update_menu command - force update bot commands."""
    try:
        commands = [
            BotCommand(command="start", description="🔮 Начать работу с ботом"),
            BotCommand(command="help", description="📚 Как гадать"),
            BotCommand(command="predict", description="🔮 Получить предсказание"),
            BotCommand(command="history", description="📜 Моя история"),
            BotCommand(command="random", description="🎯 Случайное предсказание"),
            BotCommand(command="about", description="ℹ️ О боте"),
            BotCommand(command="clear", description="🗑️ Очистить историю"),
            BotCommand(command="support", description="📞 Поддержка"),
        ]
        
        await bot.set_my_commands(commands)
        await message.answer("✅ Меню команд обновлено! Перезапустите чат или нажмите на кнопку меню рядом с полем ввода.")
        
    except Exception as e:
        logger.error(f"Failed to update commands: {e}")
        await message.answer("❌ Ошибка при обновлении меню команд.")


# Callback handlers
@router.callback_query(F.data == "back_to_menu")
async def back_to_menu_callback(callback: CallbackQuery, state: FSMContext) -> Any:
    """Handle back to menu callback."""
    await state.clear()
    await callback.message.edit_text(
        "📋 Главное меню Кофейного Оракула\n\nВыберите действие из меню ниже:"
    )
    await callback.answer()


@router.callback_query(F.data == "new_prediction")
async def new_prediction_callback(callback: CallbackQuery) -> Any:
    """Handle new prediction callback."""
    # Send as a new message to keep the prediction visible
    await callback.message.answer(
        "📸 Отправьте мне фотографию дна вашей кофейной чашки!\n\n"
        "Убедитесь, что узоры кофейной гущи хорошо видны и освещение достаточное. ✨"
    )
    await callback.answer()


@router.callback_query(F.data == "show_history")
async def show_history_callback(callback: CallbackQuery) -> Any:
    """Handle show history callback."""
    user = callback.from_user
    if not user:
        await callback.answer()
        return
    
    async for session in db_manager.get_session():
        user_repo = UserRepository(session)
        prediction_repo = PredictionRepository(session)
        
        # Get user
        db_user = await user_repo.get_user_by_telegram_id(user.id)
        if not db_user:
            await callback.message.answer(
                "Сначала получите ваше первое предсказание! 🔮\n\n"
                "Отправьте фото кофейной чашки, и я расскажу, "
                "что говорят узоры гущи о вашем будущем!"
            )
            await callback.answer()
            return
        
        # Get user's predictions (limit to 5 as per requirements)
        predictions = await prediction_repo.get_user_predictions(db_user.id, limit=5)
        
        if not predictions:
            await callback.message.answer(
                "📜 У вас пока нет предсказаний в истории.\n\n"
                "Отправьте фото кофейной чашки с гущей, "
                "чтобы получить первое магическое предсказание! ☕✨"
            )
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
    """Handle share prediction callback."""
    # Send instructions as a separate message, keeping the prediction visible
    await callback.message.answer(
        "📤 Поделиться предсказанием\n\n"
        "Скопируйте текст предсказания и поделитесь им с друзьями!\n\n"
        "🔮 Пусть магия кофейной гущи принесет радость и вашим близким!"
    )
    await callback.answer()


@router.callback_query(F.data.startswith("help_"))
async def help_callback(callback: CallbackQuery) -> Any:
    """Handle help callbacks."""
    help_type = callback.data.split("_")[1]
    
    help_texts = {
        "photo": """📸 Как правильно сфотографировать чашку:

1. ☕ Выпейте кофе, оставив немного гущи на дне
2. 🔄 Слегка покрутите чашку, чтобы гуща распределилась
3. 📱 Сделайте фото сверху при хорошем освещении
4. 🔍 Убедитесь, что узоры четко видны
5. 📤 Отправьте фото как изображение (не файл)

💡 Совет: лучше всего фотографировать при дневном свете!""",
        
        "coffee": """☕ Приготовление кофе для гадания:

1. ☕ Используйте молотый кофе среднего помола
2. 🔥 Заварите крепкий кофе (турка или френч-пресс)
3. 🥄 Не добавляйте сахар и молоко
4. 🍵 Выпейте, оставив 1-2 глотка с гущей
5. 🔄 Покрутите чашку 3 раза по часовой стрелке
6. ⏰ Подождите 2-3 минуты, пока гуща осядет

✨ Чем крепче кофе, тем четче узоры!""",
        
        "divination": """🔮 О гадании на кофейной гуще:

📜 Древнее искусство, пришедшее с Востока
🎨 Узоры гущи - это язык подсознания
✨ Каждый символ имеет свое значение
🌟 Гадание помогает увидеть возможности

🔍 Основные символы:
• Круги - гармония, завершение дел
• Линии - путешествия, перемены
• Звезды - исполнение желаний
• Цветы - любовь и радость
• Птицы - хорошие новости

💫 Помните: будущее в ваших руках!""",
        
        "faq": """❓ Частые вопросы:

Q: Почему бот не отвечает на фото?
A: Проверьте качество фото и освещение

Q: Можно ли гадать на растворимом кофе?
A: Лучше использовать молотый кофе

Q: Сколько раз в день можно гадать?
A: Рекомендуется не чаще 2-3 раз

Q: Почему все предсказания позитивные?
A: Мы верим в силу позитивного мышления!

Q: Как очистить историю предсказаний?
A: Используйте настройки → Очистить историю

Q: Бот не работает, что делать?
A: Попробуйте команду /start"""
    }
    
    text = help_texts.get(help_type, "Информация не найдена")
    await callback.message.edit_text(text, reply_markup=KeyboardManager.get_help_menu())
    await callback.answer()





@router.callback_query(F.data == "cancel_subscription")
async def cancel_subscription_callback(callback: CallbackQuery) -> Any:
    """Show confirmation before cancelling subscription."""
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Да, отменить подписку", callback_data="confirm_cancel_sub")],
        [InlineKeyboardButton(text="◀️ Нет, вернуться", callback_data="subscription_status")]
    ])
    await callback.message.edit_text(
        "⚠️ Вы уверены, что хотите отменить подписку?\n\n"
        "Автопродление будет отключено, а доступ сохранится до конца оплаченного периода.",
        reply_markup=keyboard
    )
    await callback.answer()


@router.callback_query(F.data == "confirm_cancel_sub")
async def confirm_cancel_subscription_callback(callback: CallbackQuery) -> Any:
    """Handle confirmed subscription cancellation."""
    user = callback.from_user
    if not user:
        await callback.answer()
        return

    try:
        async for session in db_manager.get_session():
            user_repo = UserRepository(session)
            subscription_repo = SubscriptionRepository(session)

            db_user = await user_repo.get_user_by_telegram_id(user.id)
            if not db_user:
                await callback.message.edit_text("Пользователь не найден. Используйте /start")
                await callback.answer()
                return

            await subscription_repo.disable_recurring_payment(db_user.id)

            status = await subscription_repo.get_subscription_status(db_user.id)
            until = status.get("until", "")[:10] if status.get("until") else ""

        until_text = f"\n📅 Доступ сохранится до: {until}" if until else ""
        await callback.message.edit_text(
            "✅ Автопродление отключено\n\n"
            f"Премиум-функции останутся доступны до конца оплаченного периода.{until_text}\n\n"
            "Вы всегда можете оформить подписку снова. ☕",
            reply_markup=KeyboardManager.get_subscription_status_keyboard(
                has_active_subscription=bool(until),
                is_vip=False,
                recurring_enabled=False,
            )
        )
        await callback.answer("Автопродление отключено", show_alert=False)
        return
    except Exception as e:
        logger.error(f"Error cancelling subscription: {e}")
        await callback.message.edit_text(
            "❌ Произошла ошибка при отмене подписки.\n\n"
            "Попробуйте позже или обратитесь в поддержку.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔄 Попробовать снова", callback_data="cancel_subscription")],
                [InlineKeyboardButton(text="◀️ В меню", callback_data="back_to_menu")]
            ])
        )

    await callback.answer()


@router.callback_query(F.data.startswith("confirm_"))
async def confirm_callback(callback: CallbackQuery) -> Any:
    """Handle confirmation callbacks."""
    action = callback.data.split("_")[1]
    
    if action == "clear_history":
        user = callback.from_user
        if user:
            try:
                async for session in db_manager.get_session():
                    user_repo = UserRepository(session)
                    prediction_repo = PredictionRepository(session)
                    
                    # Get user
                    db_user = await user_repo.get_user_by_telegram_id(user.id)
                    if db_user:
                        # Delete all user predictions using raw SQL for simplicity
                        from sqlalchemy import text
                        await session.execute(
                            text("DELETE FROM predictions WHERE user_id = :user_id"),
                            {"user_id": db_user.id}
                        )
                        await session.commit()
                
                await callback.message.edit_text(
                    "✅ История предсказаний очищена!\n\n"
                    "Теперь вы можете начать с чистого листа. "
                    "Отправьте фото кофейной чашки для нового предсказания! 🔮"
                )
            except Exception as e:
                logger.error(f"Error clearing history: {e}")
                await callback.message.edit_text(
                    "❌ Произошла ошибка при очистке истории.\n\n"
                    "Попробуйте позже или обратитесь в поддержку."
                )
    
    await callback.answer()


@router.callback_query(F.data == "cancel_action")
async def cancel_callback(callback: CallbackQuery) -> Any:
    """Handle cancel callback."""
    await callback.message.edit_text(
        "❌ Действие отменено\n\n"
        "Используйте меню ниже для выбора других действий."
    )
    await callback.answer()


# ===== Subscription Handlers =====

@router.message(F.text == "💎 Подписка")
async def subscription_handler(message: Message) -> Any:
    """Handle subscription menu request."""
    user = message.from_user
    if not user:
        return
    
    async for session in db_manager.get_session():
        user_repo = UserRepository(session)
        subscription_repo = SubscriptionRepository(session)
        settings_repo = SettingsRepository(session)
        
        db_user = await user_repo.get_user_by_telegram_id(user.id)
        if not db_user:
            db_user = await user_repo.create_user(
                telegram_id=user.id,
                username=user.username,
                full_name=user.full_name or f"{user.first_name} {user.last_name or ''}".strip()
            )
        
        status = await subscription_repo.get_subscription_status(db_user.id)
        price_str = await settings_repo.get_setting("subscription_price")
        price = int(float(price_str)) if price_str else 300
        
        if status["type"] == "vip":
            status_text = (
                "✨ Твой статус: VIP ⭐\n\n"
                f"Причина: {status.get('vip_reason', 'Особый гость Оракула')}\n\n"
                "Тебе открыты все тайны кофейных узоров!"
            )
        elif status["type"] == "premium" and status["active"]:
            status_text = (
                "✨ Твой статус: Премиум 💫\n\n"
                f"Магия действует до: {status['until'][:10]}\n\n"
                "Тебе открыты безграничные сеансы гадания!"
            )
        else:
            remaining = status.get("predictions_remaining", 0)
            used = status.get("predictions_used", 0)
            limit = status.get("predictions_limit", 10)
            if remaining > 0:
                status_text = (
                    f"☕ Твой статус: Гость Оракула\n\n"
                    f"🎁 Использовано бесплатных гаданий: {used} из {limit}\n\n"
                    f"💰 Подписка для безлимита: {price}₽/мес"
                )
            else:
                status_text = (
                    f"☕ Твой статус: Гость Оракула\n\n"
                    f"🎁 Использовано бесплатных гаданий: {used} из {limit}\n\n"
                    f"💰 Подписка для безлимита: {price}₽/мес"
                )
        
        has_active = (status["type"] == "vip") or (status["type"] == "premium" and status["active"])
        is_vip = status["type"] == "vip"
        recurring_enabled, _ = await subscription_repo.is_recurring_enabled(db_user.id)

        if has_active and not is_vip and not recurring_enabled:
            status_text += "\n\n⚠️ Автопродление выключено — подписка не продлится автоматически."

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
    """Handle subscription status callback."""
    user = callback.from_user
    if not user:
        await callback.answer()
        return
    
    async for session in db_manager.get_session():
        user_repo = UserRepository(session)
        subscription_repo = SubscriptionRepository(session)
        settings_repo = SettingsRepository(session)
        
        db_user = await user_repo.get_user_by_telegram_id(user.id)
        if not db_user:
            await callback.message.edit_text("Пользователь не найден. Используйте /start")
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
            status_text += "\n\n⚠️ Подписка не продлится автоматически."

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
    """Background task: poll YooKassa until payment succeeds or is terminal, then notify user."""
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
            logger.warning("Background poll error for %s: %s", payment_id, exc)
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

                    db_user = await user_repo.get_user_by_telegram_id(telegram_user_id)
                    if not db_user:
                        return

                    await sub_repo.activate_premium(db_user.id)

                    payment_method_saved = status_result.get("payment_method_saved", False)
                    payment_method_id = status_result.get("payment_method_id")
                    if payment_method_saved and payment_method_id:
                        await sub_repo.enable_recurring_payment(db_user.id, payment_method_id)

                    await sub_repo.update_payment_status(payment_id, "succeeded")

                payment_service.clear_pending_payment(telegram_user_id)

                try:
                    await bot.edit_message_text(
                        chat_id=chat_id,
                        message_id=message_id,
                        text=(
                            "✅ Оплата прошла успешно!\n\n"
                            "Премиум-подписка активирована на 1 месяц.\n"
                            "Спасибо за поддержку! ☕"
                        ),
                        reply_markup=KeyboardManager.get_subscription_status_keyboard(
                            has_active_subscription=True,
                            recurring_enabled=bool(payment_method_saved and payment_method_id),
                        ),
                    )
                except Exception:
                    # Message may have been already edited by manual check
                    await bot.send_message(
                        chat_id=chat_id,
                        text=(
                            "✅ Оплата прошла успешно!\n\n"
                            "Премиум-подписка активирована на 1 месяц.\n"
                            "Спасибо за поддержку! ☕"
                        ),
                        reply_markup=KeyboardManager.get_subscription_status_keyboard(
                            has_active_subscription=True,
                            recurring_enabled=bool(payment_method_saved and payment_method_id),
                        ),
                    )
            except Exception as exc:
                logger.error("Background poll activation error: %s", exc)
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
                        text=(
                            "❌ Платёж отменён.\n"
                            "Попробуйте оформить подписку снова."
                        ),
                        reply_markup=KeyboardManager.get_subscription_status_keyboard(
                            has_active_subscription=False,
                        ),
                    )
                except Exception:
                    await bot.send_message(
                        chat_id=chat_id,
                        text=(
                            "❌ Платёж отменён.\n"
                            "Попробуйте оформить подписку снова."
                        ),
                        reply_markup=KeyboardManager.get_subscription_status_keyboard(
                            has_active_subscription=False,
                        ),
                    )
            except Exception as exc:
                logger.error("Background poll cancel handling error: %s", exc)
            return

    # Exhausted all attempts — payment still pending, user can use the button
    logger.info("Background poll exhausted for payment %s, user %s", payment_id, telegram_user_id)


@router.callback_query(F.data == "start_payment")
async def start_payment_callback(callback: CallbackQuery, bot: Bot, state: FSMContext) -> Any:
    """Handle start payment callback - ask for email before creating payment."""
    user = callback.from_user
    if not user:
        await callback.answer()
        return

    from coffee_oracle.services.payment_service import get_payment_service

    payment_service = get_payment_service()
    if payment_service is None:
        await callback.message.edit_text(
            "⚠️ Платежи временно недоступны.\n"
            "Обратитесь в поддержку для оформления подписки."
        )
        await callback.answer()
        return

    await state.set_state(PaymentStates.waiting_for_email)

    back_keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Назад в меню", callback_data="back_to_menu")],
    ])

    await callback.message.edit_text(
        "По закону мы обязаны отправить вам чек об оплате 🧾\n\n"
        "Пожалуйста, напишите ваш email, куда мы сможем его прислать:",
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
    """Shared logic: create YooKassa payment and send the payment link."""
    from coffee_oracle.services.payment_service import get_payment_service

    await state.clear()

    payment_service = get_payment_service()
    if payment_service is None:
        await bot.send_message(
            chat_id,
            "⚠️ Платежи временно недоступны.\n"
            "Обратитесь в поддержку для оформления подписки.",
        )
        return

    async for session in db_manager.get_session():
        user_repo = UserRepository(session)
        settings_repo = SettingsRepository(session)
        sub_repo = SubscriptionRepository(session)

        db_user = await user_repo.get_user_by_telegram_id(telegram_user_id)
        if not db_user:
            await bot.send_message(chat_id, "Пользователь не найден. Используйте /start")
            return

        # Save email for future recurring payments (54-ФЗ receipts)
        if user_email and db_user.email != user_email:
            db_user.email = user_email
            await session.commit()

        try:
            price_str = await settings_repo.get_setting("subscription_price")
            price = float(price_str) if price_str else 300.0
            price_kopecks = int(price * 100)

            description = "Подписка Coffee Oracle (1 месяц)"

            result = await payment_service.create_first_payment(
                amount=price_kopecks,
                description=description,
                user_id=telegram_user_id,
                user_email=user_email,
            )

            if not result.get("success"):
                error_msg = result.get("error", "Неизвестная ошибка")
                logger.error("Failed to create payment via YooKassa: %s", error_msg)
                await bot.send_message(
                    chat_id,
                    "❌ Ошибка создания платежа.\n"
                    "Попробуйте позже или обратитесь в поддержку.",
                )
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

            recurring_note = ""
            if not is_recurring:
                recurring_note = (
                    "\n⚠️ Автопродление временно недоступно. "
                    "По истечении подписки потребуется оплатить заново."
                )

            sent = await bot.send_message(
                chat_id,
                "💳 Для оплаты подписки перейдите по ссылке ниже.\n\n"
                f"Сумма: {price:.0f} ₽\n"
                "Период: 1 месяц\n\n"
                f"Продолжая оплату, вы соглашаетесь с <a href=\"https://{config.domain}/terms\">условиями использования</a> "
                f"и <a href=\"https://{config.domain}/privacy\">политикой конфиденциальности</a>.\n\n"
                f"Статус оплаты обновится автоматически.{recurring_note}",
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
            logger.error("Unexpected error in payment flow: %s", e)
            try:
                await bot.send_message(
                    chat_id,
                    "❌ Произошла непредвиденная ошибка.\n"
                    "Попробуйте позже или обратитесь в поддержку.",
                )
            except Exception:
                pass


@router.message(PaymentStates.waiting_for_email)
async def email_input_handler(message: Message, bot: Bot, state: FSMContext) -> Any:
    """Validate email and proceed to payment creation."""
    email = message.text.strip() if message.text else ""

    if not EMAIL_RE.match(email):
        back_keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ Назад в меню", callback_data="back_to_menu")],
        ])
        await message.answer(
            "❌ Некорректный email. Попробуйте ещё раз.\n\n"
            "Пример: user@example.com",
            reply_markup=back_keyboard,
        )
        return

    await message.answer(f"✉️ Чек будет отправлен на {email}\n⏳ Создаём платёж...")
    await _create_payment_and_respond(
        bot=bot,
        chat_id=message.chat.id,
        telegram_user_id=message.from_user.id,
        user_email=email,
        state=state,
    )


@router.callback_query(F.data == "check_payment")
async def check_payment_callback(callback: CallbackQuery) -> Any:
    """Handle check payment callback - verify payment status via YooKassa API."""
    user = callback.from_user
    if not user:
        await callback.answer()
        return

    from coffee_oracle.services.payment_service import get_payment_service

    payment_service = get_payment_service()
    if payment_service is None:
        await callback.message.edit_text(
            "⚠️ Платежи временно недоступны.\n"
            "Обратитесь в поддержку для оформления подписки."
        )
        await callback.answer()
        return

    # Get pending payment for this user
    payment_id = payment_service.get_pending_payment(user.id)
    if not payment_id:
        await callback.message.edit_text("ℹ️ Нет ожидающих платежей.")
        await callback.answer()
        return

    async for session in db_manager.get_session():
        user_repo = UserRepository(session)
        sub_repo = SubscriptionRepository(session)

        db_user = await user_repo.get_user_by_telegram_id(user.id)
        if not db_user:
            await callback.message.edit_text("Пользователь не найден. Используйте /start")
            await callback.answer()
            return

        try:
            status_result = await payment_service.get_payment_status(payment_id)

            if not status_result.get("success"):
                logger.error("Failed to get payment status: %s", status_result.get("error"))
                await callback.message.edit_text(
                    "❌ Не удалось проверить статус платежа.\n"
                    "Попробуйте позже."
                )
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

                await callback.message.edit_text(
                    "✅ Оплата прошла успешно!\n\n"
                    "Премиум-подписка активирована на 1 месяц.\n"
                    "Спасибо за поддержку! ☕",
                    reply_markup=KeyboardManager.get_subscription_status_keyboard(
                        has_active_subscription=True,
                        recurring_enabled=bool(payment_method_saved and payment_method_id),
                    ),
                )

            elif status == "pending":
                await callback.message.edit_text(
                    "⏳ Платёж ещё обрабатывается, проверьте позже.",
                    reply_markup=KeyboardManager.get_subscription_keyboard(),
                )

            elif status == "canceled":
                # Update payment status in DB
                await sub_repo.update_payment_status(payment_id, "canceled")

                # Clear pending payment
                payment_service.clear_pending_payment(user.id)

                await callback.message.edit_text(
                    "❌ Платёж отменён.\n"
                    "Попробуйте оформить подписку снова.",
                    reply_markup=KeyboardManager.get_subscription_status_keyboard(
                        has_active_subscription=False,
                    ),
                )

            else:
                await callback.message.edit_text(
                    f"ℹ️ Статус платежа: {status}.\n"
                    "Попробуйте проверить позже.",
                    reply_markup=KeyboardManager.get_subscription_keyboard(),
                )

        except Exception as e:
            logger.error("Unexpected error checking payment status: %s", e)
            try:
                await callback.message.edit_text(
                    "❌ Произошла ошибка при проверке платежа.\n"
                    "Попробуйте позже."
                )
            except Exception:
                pass

    await callback.answer()



@router.message(F.text & ~F.text.in_([
    "🔮 Получить предсказание", "📜 Моя история", "ℹ️ О боте",
    "🎯 Случайное предсказание", "📚 Как гадать", "🗑️ Очистить историю", 
    "📞 Поддержка", "💎 Подписка"
]))
async def text_handler(message: Message) -> Any:
    """Handle other text messages."""
    await message.answer(
        "🔮 Я понимаю только язык кофейной гущи! \n\n"
        "Отправьте фото вашей кофейной чашки или воспользуйтесь меню ниже.",
        reply_markup=KeyboardManager.get_main_menu_with_subscription()
    )