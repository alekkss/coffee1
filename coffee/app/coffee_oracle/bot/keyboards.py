"""Менеджер клавиатур Telegram-бота.

Содержит Reply- и Inline-клавиатуры для всех экранов:
главное меню, действия после предсказания, подписка,
подтверждение действий, оплата, подменю помощи.

Названия кнопок импортируются из bot/texts.py —
единого источника для TG и MAX ботов.
"""

from aiogram.types import (
    KeyboardButton,
    ReplyKeyboardMarkup,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)

from coffee_oracle.bot import texts
from coffee_oracle.config import config

# Порог предсказаний, после которого показывается кнопка подписки
_SUBSCRIPTION_BUTTON_THRESHOLD = 5

# Порог предсказаний, после которого показывается кнопка «Открыть безлимит»
_UNLOCK_BUTTON_THRESHOLD = 9


class KeyboardManager:
    """Менеджер клавиатур Telegram-бота."""

    @staticmethod
    def get_main_menu() -> ReplyKeyboardMarkup:
        """Главное меню без кнопки подписки."""
        keyboard = [
            [KeyboardButton(text=texts.BTN_PREDICT)],
            [KeyboardButton(text=texts.BTN_VIDEO_INSTRUCTION)],
            [KeyboardButton(text=texts.BTN_HISTORY)],
            [KeyboardButton(text=texts.BTN_HELP)],
        ]

        return ReplyKeyboardMarkup(
            keyboard=keyboard,
            resize_keyboard=True,
            one_time_keyboard=False,
            is_persistent=True,
        )

    @staticmethod
    def get_main_menu_with_subscription() -> ReplyKeyboardMarkup:
        """Главное меню с кнопкой подписки."""
        keyboard = [
            [KeyboardButton(text=texts.BTN_PREDICT)],
            [KeyboardButton(text=texts.BTN_VIDEO_INSTRUCTION)],
            [KeyboardButton(text=texts.BTN_HISTORY)],
            [KeyboardButton(text=texts.BTN_SUBSCRIPTION), KeyboardButton(text=texts.BTN_HELP)],
        ]

        return ReplyKeyboardMarkup(
            keyboard=keyboard,
            resize_keyboard=True,
            one_time_keyboard=False,
            is_persistent=True,
        )

    @staticmethod
    def get_menu_for_user(is_vip: bool, predictions_count: int) -> ReplyKeyboardMarkup:
        """Выбор клавиатуры главного меню в зависимости от статуса пользователя.

        Кнопка «Подписка» показывается только если:
        - пользователь НЕ VIP
        - количество предсказаний строго больше порога (5)

        Args:
            is_vip: Является ли пользователь VIP.
            predictions_count: Количество сделанных предсказаний.

        Returns:
            ReplyKeyboardMarkup с подпиской или без.
        """
        if not is_vip and predictions_count > _SUBSCRIPTION_BUTTON_THRESHOLD:
            return KeyboardManager.get_main_menu_with_subscription()
        return KeyboardManager.get_main_menu()

    @staticmethod
    def get_help_menu_keyboard() -> InlineKeyboardMarkup:
        """Inline-клавиатура подменю «Помощь»."""
        keyboard = [
            [InlineKeyboardButton(text=texts.BTN_HELP_FAQ, callback_data="help_faq")],
            [InlineKeyboardButton(text=texts.BTN_HELP_ABOUT, callback_data="help_about")],
            [InlineKeyboardButton(text=texts.BTN_HELP_SUPPORT, callback_data="help_support")],
            [InlineKeyboardButton(text=texts.BTN_HELP_SUBSCRIPTION_INFO, callback_data="help_subscription_info")],
            [InlineKeyboardButton(text=texts.BTN_HELP_DISABLE_REMINDERS, callback_data="help_disable_reminders")],
            [InlineKeyboardButton(text=texts.BTN_HELP_BOT_NOT_RESPONDING, callback_data="help_bot_not_responding")],
            [InlineKeyboardButton(text=texts.BTN_HELP_PHOTO_NOT_RECOGNIZED, callback_data="help_photo_not_recognized")],
            [InlineKeyboardButton(text=texts.BTN_HELP_CONTACT, callback_data="help_contact")],
            [InlineKeyboardButton(text=texts.BTN_BACK_TO_MENU, callback_data="back_to_menu")],
        ]
        return InlineKeyboardMarkup(inline_keyboard=keyboard)

    @staticmethod
    def get_back_to_help_keyboard() -> InlineKeyboardMarkup:
        """Кнопка возврата в подменю помощи."""
        keyboard = [
            [InlineKeyboardButton(text=texts.BTN_BACK_TO_MENU, callback_data="back_to_help")],
            [InlineKeyboardButton(text=texts.BTN_BACK_SHORT, callback_data="back_to_menu")],
        ]
        return InlineKeyboardMarkup(inline_keyboard=keyboard)

    @staticmethod
    def get_predict_instruction_keyboard() -> InlineKeyboardMarkup:
        """Клавиатура экрана инструкции перед отправкой фото."""
        keyboard = [
            [InlineKeyboardButton(text=texts.BTN_VIDEO_INSTRUCTION, callback_data="action_video_instruction")],
            [InlineKeyboardButton(text=texts.BTN_HISTORY, callback_data="show_history")],
            [InlineKeyboardButton(text=texts.BTN_BACK_TO_MENU, callback_data="back_to_menu")],
        ]
        return InlineKeyboardMarkup(inline_keyboard=keyboard)

    @staticmethod
    def get_confirmation_keyboard(action: str) -> InlineKeyboardMarkup:
        """Клавиатура подтверждения опасного действия."""
        keyboard = [
            [InlineKeyboardButton(text=texts.BTN_CONFIRM, callback_data=f"confirm_{action}")],
            [InlineKeyboardButton(text=texts.BTN_CANCEL, callback_data="cancel_action")]
        ]

        return InlineKeyboardMarkup(inline_keyboard=keyboard)

    @staticmethod
    def get_prediction_actions(show_unlock: bool = False) -> InlineKeyboardMarkup:
        """Кнопки действий после предсказания.

        Args:
            show_unlock: Показывать кнопку «Открыть безлимит».
                         True если пользователь использовал >= 9 предсказаний
                         или исчерпал лимит.

        Returns:
            InlineKeyboardMarkup с кнопками действий.
        """
        keyboard = [
            [InlineKeyboardButton(text=texts.BTN_NEW_PREDICTION, callback_data="new_prediction")],
        ]

        if show_unlock:
            keyboard.append([
                InlineKeyboardButton(text=texts.BTN_UNLOCK_UNLIMITED, callback_data="start_payment"),
            ])

        keyboard.append([
            InlineKeyboardButton(text=texts.BTN_BACK_TO_MENU, callback_data="back_to_menu"),
        ])

        return InlineKeyboardMarkup(inline_keyboard=keyboard)

    @staticmethod
    def should_show_unlock(is_vip: bool, is_premium: bool, predictions_count: int, limit_exhausted: bool) -> bool:
        """Определяет, нужно ли показывать кнопку «Открыть безлимит».

        Кнопка показывается если пользователь:
        - НЕ VIP и НЕ Premium
        - Использовал >= 9 предсказаний ИЛИ исчерпал лимит

        Args:
            is_vip: Является ли пользователь VIP.
            is_premium: Является ли пользователь Premium.
            predictions_count: Количество сделанных предсказаний.
            limit_exhausted: Исчерпан ли лимит бесплатных предсказаний.

        Returns:
            True если кнопку нужно показать.
        """
        if is_vip or is_premium:
            return False
        return predictions_count >= _UNLOCK_BUTTON_THRESHOLD or limit_exhausted

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
            [InlineKeyboardButton(
                text=texts.BTN_BACK_TO_MENU,
                callback_data="back_to_menu",
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
    def get_back_to_menu_keyboard() -> InlineKeyboardMarkup:
        """Одиночная inline-кнопка возврата в главное меню."""
        keyboard = [
            [InlineKeyboardButton(text=texts.BTN_BACK_TO_MENU, callback_data="back_to_menu")],
        ]
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
