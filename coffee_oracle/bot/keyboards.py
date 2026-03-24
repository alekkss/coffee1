"""Keyboard manager for bot."""

from aiogram.types import KeyboardButton, ReplyKeyboardMarkup, InlineKeyboardButton, InlineKeyboardMarkup


class KeyboardManager:
    """Manager for bot keyboards."""
    
    @staticmethod
    def get_main_menu() -> ReplyKeyboardMarkup:
        """Get main menu keyboard."""
        keyboard = [
            [KeyboardButton(text="🔮 Получить предсказание")],
            [KeyboardButton(text="📜 Моя история"), KeyboardButton(text="🎯 Случайное предсказание")],
            [KeyboardButton(text="📚 Как гадать"), KeyboardButton(text="ℹ️ О боте")],
            [KeyboardButton(text="🗑️ Очистить историю"), KeyboardButton(text="📞 Поддержка")]
        ]
        
        return ReplyKeyboardMarkup(
            keyboard=keyboard,
            resize_keyboard=True,
            one_time_keyboard=False
        )
    

    
    @staticmethod
    def get_help_menu() -> InlineKeyboardMarkup:
        """Get help inline keyboard."""
        keyboard = [
            [InlineKeyboardButton(text="📸 Как фотографировать", callback_data="help_photo")],
            [InlineKeyboardButton(text="☕ Приготовление кофе", callback_data="help_coffee")],
            [InlineKeyboardButton(text="🔮 О гадании", callback_data="help_divination")],
            [InlineKeyboardButton(text="❓ Частые вопросы", callback_data="help_faq")],
            [InlineKeyboardButton(text="◀️ Назад в меню", callback_data="back_to_menu")]
        ]
        
        return InlineKeyboardMarkup(inline_keyboard=keyboard)
    
    @staticmethod
    def get_confirmation_keyboard(action: str) -> InlineKeyboardMarkup:
        """Get confirmation keyboard for dangerous actions."""
        keyboard = [
            [InlineKeyboardButton(text="✅ Да, подтверждаю", callback_data=f"confirm_{action}")],
            [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_action")]
        ]
        
        return InlineKeyboardMarkup(inline_keyboard=keyboard)
    
    @staticmethod
    def get_prediction_actions() -> InlineKeyboardMarkup:
        """Get actions for after prediction."""
        keyboard = [
            [InlineKeyboardButton(text="🔮 Еще предсказание", callback_data="new_prediction")],
            [InlineKeyboardButton(text="📜 Моя история", callback_data="show_history")],
            [InlineKeyboardButton(text="📤 Поделиться", callback_data="share_prediction")]
        ]
        
        return InlineKeyboardMarkup(inline_keyboard=keyboard)