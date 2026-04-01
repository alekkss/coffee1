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
    
    @staticmethod
    def get_subscription_keyboard(payment_url: str = None) -> InlineKeyboardMarkup:
        """Клавиатура с URL-кнопкой оплаты и кнопкой проверки."""
        keyboard = []
        if payment_url:
            keyboard.append([
                InlineKeyboardButton(text="💳 Оплатить", url=payment_url)
            ])
        keyboard.append([
            InlineKeyboardButton(text="🔍 Проверить оплату", callback_data="check_payment")
        ])
        keyboard.append([
            InlineKeyboardButton(text="◀️ Назад в меню", callback_data="back_to_menu")
        ])
        return InlineKeyboardMarkup(inline_keyboard=keyboard)
    
    @staticmethod
    def get_subscription_status_keyboard(
        has_active_subscription: bool = False,
        is_vip: bool = False,
        recurring_enabled: bool = False,
    ) -> InlineKeyboardMarkup:
        """Get keyboard for subscription status page."""
        keyboard = []

        if has_active_subscription and not is_vip:
            if recurring_enabled:
                keyboard.append([InlineKeyboardButton(text="❌ Отменить автопродление", callback_data="cancel_subscription")])
            else:
                keyboard.append([InlineKeyboardButton(text="🔄 Возобновить подписку", callback_data="start_payment")])
        elif not has_active_subscription:
            keyboard.append([InlineKeyboardButton(text="💳 Оформить подписку", callback_data="start_payment")])

        keyboard.append([InlineKeyboardButton(text="◀️ Назад в меню", callback_data="back_to_menu")])

        return InlineKeyboardMarkup(inline_keyboard=keyboard)
    
    @staticmethod
    def get_main_menu_with_subscription() -> ReplyKeyboardMarkup:
        """Get main menu keyboard with subscription button."""
        keyboard = [
            [KeyboardButton(text="🔮 Получить предсказание")],
            [KeyboardButton(text="📜 Моя история"), KeyboardButton(text="🎯 Случайное предсказание")],
            [KeyboardButton(text="💎 Подписка"), KeyboardButton(text="📚 Как гадать")],
            [KeyboardButton(text="ℹ️ О боте"), KeyboardButton(text="📞 Поддержка")]
        ]
        
        return ReplyKeyboardMarkup(
            keyboard=keyboard,
            resize_keyboard=True,
            one_time_keyboard=False
        )