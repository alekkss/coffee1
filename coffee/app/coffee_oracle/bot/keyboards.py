"""Менеджер клавиатур Telegram-бота.

Содержит Reply- и Inline-клавиатуры для всех экранов:
главное меню, действия после предсказания, подписка,
подтверждение действий, оплата.

Названия кнопок импортируются из bot/texts.py —
единого источника для TG и MAX ботов.
"""

from aiogram.types import KeyboardButton, ReplyKeyboardMarkup, InlineKeyboardButton, InlineKeyboardMarkup

from coffee_oracle.bot import texts
from coffee_oracle.config import config


class KeyboardManager:
    """Менеджер клавиатур Telegram-бота."""

    @staticmethod
    def get_main_menu() -> ReplyKeyboardMarkup:
        """Главное меню без кнопки подписки."""
        keyboard = [
            [KeyboardButton(text=texts.BTN_PREDICT)],
            [KeyboardButton(text=texts.BTN_VIDEO_INSTRUCTION)],
            [KeyboardButton(text=texts.BTN_HISTORY), KeyboardButton(text=texts.BTN_RANDOM)],
            [KeyboardButton(text=texts.BTN_FAQ), KeyboardButton(text=texts.BTN_ABOUT)],
            [KeyboardButton(text=texts.BTN_CLEAR), KeyboardButton(text=texts.BTN_SUPPORT)]
        ]

        return ReplyKeyboardMarkup(
            keyboard=keyboard,
            resize_keyboard=True,
            one_time_keyboard=False
        )

    @staticmethod
    def get_main_menu_with_subscription() -> ReplyKeyboardMarkup:
        """Главное меню с кнопкой подписки."""
        keyboard = [
            [KeyboardButton(text=texts.BTN_PREDICT)],
            [KeyboardButton(text=texts.BTN_VIDEO_INSTRUCTION)],
            [KeyboardButton(text=texts.BTN_SUBSCRIPTION), KeyboardButton(text=texts.BTN_RANDOM)],
            [KeyboardButton(text=texts.BTN_HISTORY), KeyboardButton(text=texts.BTN_FAQ)],
            [KeyboardButton(text=texts.BTN_ABOUT), KeyboardButton(text=texts.BTN_SUPPORT)]
        ]

        return ReplyKeyboardMarkup(
            keyboard=keyboard,
            resize_keyboard=True,
            one_time_keyboard=False
        )

    @staticmethod
    def get_confirmation_keyboard(action: str) -> InlineKeyboardMarkup:
        """Клавиатура подтверждения опасного действия."""
        keyboard = [
            [InlineKeyboardButton(text=texts.BTN_CONFIRM, callback_data=f"confirm_{action}")],
            [InlineKeyboardButton(text=texts.BTN_CANCEL, callback_data="cancel_action")]
        ]

        return InlineKeyboardMarkup(inline_keyboard=keyboard)

    @staticmethod
    def get_prediction_actions() -> InlineKeyboardMarkup:
        """Кнопки действий после предсказания."""
        keyboard = [
            [InlineKeyboardButton(text=texts.BTN_NEW_PREDICTION, callback_data="new_prediction")],
            [InlineKeyboardButton(text=texts.BTN_SHOW_HISTORY, callback_data="show_history")],
            [InlineKeyboardButton(text=texts.BTN_SHARE, callback_data="share_prediction")]
        ]

        return InlineKeyboardMarkup(inline_keyboard=keyboard)

    @staticmethod
    def get_about_keyboard() -> InlineKeyboardMarkup:
        """Клавиатура «Об Оракуле» со ссылками на правовые документы."""
        domain = config.domain
        keyboard = [
            [InlineKeyboardButton(
                text="📄 Условия использования",
                url=f"https://{domain}/terms",
            )],
            [InlineKeyboardButton(
                text="🔒 Политика конфиденциальности",
                url=f"https://{domain}/privacy",
            )],
        ]
        return InlineKeyboardMarkup(inline_keyboard=keyboard)

    @staticmethod
    def get_subscription_keyboard(payment_url: str = None) -> InlineKeyboardMarkup:
        """Клавиатура с URL-кнопкой оплаты и кнопкой проверки."""
        keyboard = []
        if payment_url:
            keyboard.append([
                InlineKeyboardButton(text=texts.BTN_PAY, url=payment_url)
            ])
        keyboard.append([
            InlineKeyboardButton(text=texts.BTN_CHECK_PAYMENT, callback_data="check_payment")
        ])
        keyboard.append([
            InlineKeyboardButton(text=texts.BTN_BACK_TO_MENU, callback_data="back_to_menu")
        ])
        return InlineKeyboardMarkup(inline_keyboard=keyboard)

    @staticmethod
    def get_subscription_status_keyboard(
        has_active_subscription: bool = False,
        is_vip: bool = False,
        recurring_enabled: bool = False,
    ) -> InlineKeyboardMarkup:
        """Клавиатура статуса подписки."""
        keyboard = []

        if has_active_subscription and not is_vip:
            if recurring_enabled:
                keyboard.append([InlineKeyboardButton(text=texts.BTN_CANCEL_RECURRING, callback_data="cancel_subscription")])
            else:
                keyboard.append([InlineKeyboardButton(text=texts.BTN_RENEW, callback_data="start_payment")])
        elif not has_active_subscription:
            keyboard.append([InlineKeyboardButton(text=texts.BTN_PAY + " подписку", callback_data="start_payment")])

        keyboard.append([InlineKeyboardButton(text=texts.BTN_BACK_TO_MENU, callback_data="back_to_menu")])

        return InlineKeyboardMarkup(inline_keyboard=keyboard)
