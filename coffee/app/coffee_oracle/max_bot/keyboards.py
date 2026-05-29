"""Клавиатуры для MAX-бота.

Формирует структуры inline-клавиатур в формате MAX Bot API.
Каждая кнопка — словарь с полями type, text, payload/url.
Клавиатура передаётся как вложение типа inline_keyboard.

Названия кнопок импортируются из bot/texts.py —
единого источника для TG и MAX ботов.
"""

from typing import Any, Dict, List, Optional

from coffee_oracle.bot import texts
from coffee_oracle.config import config


class MaxKeyboardManager:
    """Менеджер клавиатур для MAX-бота.

    Все методы статические — формируют и возвращают
    структуру вложения inline_keyboard для MAX API.
    """

    @staticmethod
    def _build_attachment(buttons: List[List[Dict[str, Any]]]) -> Dict[str, Any]:
        """Построение вложения inline-клавиатуры.

        Args:
            buttons: Двумерный массив кнопок (строки × кнопки в строке).

        Returns:
            Вложение для поля attachments в запросе POST /messages.
        """
        return {
            "type": "inline_keyboard",
            "payload": {
                "buttons": buttons,
            },
        }

    @classmethod
    def get_main_menu(cls) -> Dict[str, Any]:
        """Главное меню бота (без кнопки подписки).

        Returns:
            Вложение inline_keyboard с кнопками главного меню.
        """
        buttons = [
            [
                {
                    "type": "callback",
                    "text": texts.BTN_PREDICT,
                    "payload": "action_predict",
                },
            ],
            [
                {
                    "type": "callback",
                    "text": texts.BTN_VIDEO_INSTRUCTION,
                    "payload": "action_video_instruction",
                },
            ],
            [
                {
                    "type": "callback",
                    "text": texts.BTN_HISTORY,
                    "payload": "action_history",
                },
                {
                    "type": "callback",
                    "text": texts.BTN_RANDOM_SHORT,
                    "payload": "action_random",
                },
            ],
            [
                {
                    "type": "callback",
                    "text": texts.BTN_HELP,
                    "payload": "action_help_menu",
                },
            ],
        ]
        return cls._build_attachment(buttons)

    @classmethod
    def get_main_menu_with_subscription(cls) -> Dict[str, Any]:
        """Главное меню бота с кнопкой подписки.

        Returns:
            Вложение inline_keyboard с кнопками главного меню и подпиской.
        """
        buttons = [
            [
                {
                    "type": "callback",
                    "text": texts.BTN_PREDICT,
                    "payload": "action_predict",
                },
            ],
            [
                {
                    "type": "callback",
                    "text": texts.BTN_VIDEO_INSTRUCTION,
                    "payload": "action_video_instruction",
                },
            ],
            [
                {
                    "type": "callback",
                    "text": texts.BTN_HISTORY,
                    "payload": "action_history",
                },
                {
                    "type": "callback",
                    "text": texts.BTN_RANDOM_SHORT,
                    "payload": "action_random",
                },
            ],
            [
                {
                    "type": "callback",
                    "text": texts.BTN_SUBSCRIPTION,
                    "payload": "action_subscription",
                },
                {
                    "type": "callback",
                    "text": texts.BTN_HELP,
                    "payload": "action_help_menu",
                },
            ],
        ]
        return cls._build_attachment(buttons)

    @classmethod
    def get_help_menu_keyboard(cls) -> Dict[str, Any]:
        """Inline-клавиатура подменю «Помощь».

        Returns:
            Вложение inline_keyboard с кнопками разделов помощи.
        """
        buttons = [
            [
                {
                    "type": "callback",
                    "text": texts.BTN_HELP_FAQ,
                    "payload": "action_help_faq",
                },
            ],
            [
                {
                    "type": "callback",
                    "text": texts.BTN_HELP_ABOUT,
                    "payload": "action_help_about",
                },
            ],
            [
                {
                    "type": "callback",
                    "text": texts.BTN_HELP_SUPPORT,
                    "payload": "action_help_support",
                },
            ],
            [
                {
                    "type": "callback",
                    "text": texts.BTN_HELP_SUBSCRIPTION_INFO,
                    "payload": "action_help_subscription_info",
                },
            ],
            [
                {
                    "type": "callback",
                    "text": texts.BTN_HELP_DISABLE_REMINDERS,
                    "payload": "action_help_disable_reminders",
                },
            ],
            [
                {
                    "type": "callback",
                    "text": texts.BTN_HELP_BOT_NOT_RESPONDING,
                    "payload": "action_help_bot_not_responding",
                },
            ],
            [
                {
                    "type": "callback",
                    "text": texts.BTN_HELP_PHOTO_NOT_RECOGNIZED,
                    "payload": "action_help_photo_not_recognized",
                },
            ],
            [
                {
                    "type": "callback",
                    "text": texts.BTN_HELP_CONTACT,
                    "payload": "action_help_contact",
                },
            ],
            [
                {
                    "type": "callback",
                    "text": texts.BTN_BACK_TO_MENU,
                    "payload": "action_back_to_menu",
                },
            ],
        ]
        return cls._build_attachment(buttons)

    @classmethod
    def get_back_to_help_keyboard(cls) -> Dict[str, Any]:
        """Кнопки возврата: в подменю помощи и в главное меню.

        Returns:
            Вложение inline_keyboard с двумя кнопками навигации.
        """
        buttons = [
            [
                {
                    "type": "callback",
                    "text": texts.BTN_BACK_TO_MENU,
                    "payload": "action_back_to_help",
                },
            ],
            [
                {
                    "type": "callback",
                    "text": texts.BTN_BACK_SHORT,
                    "payload": "action_back_to_menu",
                },
            ],
        ]
        return cls._build_attachment(buttons)
    @classmethod
    def get_predict_instruction_keyboard(cls) -> Dict[str, Any]:
        """Клавиатура экрана инструкции перед отправкой фото.

        Returns:
            Вложение inline_keyboard с подсказками и кнопкой «Назад».
        """
        buttons = [
            [
                {
                    "type": "callback",
                    "text": texts.BTN_VIDEO_INSTRUCTION,
                    "payload": "action_video_instruction",
                },
            ],
            [
                {
                    "type": "callback",
                    "text": texts.BTN_HISTORY,
                    "payload": "action_history",
                },
            ],
            [
                {
                    "type": "callback",
                    "text": texts.BTN_BACK_TO_MENU,
                    "payload": "action_back_to_menu",
                },
            ],
        ]
        return cls._build_attachment(buttons)

    @classmethod
    def get_about_keyboard(cls) -> Dict[str, Any]:
        """Клавиатура «Об Оракуле» со ссылками на правовые документы.

        Returns:
            Вложение inline_keyboard с кнопками-ссылками и кнопкой «Назад».
        """
        domain = config.domain
        buttons = [
            [
                {
                    "type": "link",
                    "text": "📄 Условия использования",
                    "url": f"https://{domain}/terms",
                },
            ],
            [
                {
                    "type": "link",
                    "text": "🔒 Политика конфиденциальности",
                    "url": f"https://{domain}/privacy",
                },
            ],
            [
                {
                    "type": "callback",
                    "text": texts.BTN_BACK_TO_MENU,
                    "payload": "action_back_to_help",
                },
            ],
            [
                {
                    "type": "callback",
                    "text": texts.BTN_BACK_SHORT,
                    "payload": "action_back_to_menu",
                },
            ],
        ]
        return cls._build_attachment(buttons)

    @classmethod
    def get_subscription_status_keyboard(
        cls,
        has_active_subscription: bool = False,
        is_vip: bool = False,
        recurring_enabled: bool = False,
    ) -> Dict[str, Any]:
        """Клавиатура статуса подписки.

        Args:
            has_active_subscription: Есть ли активная подписка (premium или vip).
            is_vip: Является ли пользователь VIP.
            recurring_enabled: Включено ли автопродление.

        Returns:
            Вложение inline_keyboard с кнопками управления подпиской.
        """
        buttons: List[List[Dict[str, Any]]] = []

        if is_vip:
            buttons.append([
                {
                    "type": "callback",
                    "text": texts.BTN_BACK_TO_MENU,
                    "payload": "action_back_to_menu",
                },
            ])
        elif has_active_subscription:
            if recurring_enabled:
                buttons.append([
                    {
                        "type": "callback",
                        "text": texts.BTN_CANCEL_RECURRING,
                        "payload": "action_cancel_subscription",
                    },
                ])
            buttons.append([
                {
                    "type": "callback",
                    "text": texts.BTN_UPDATE_STATUS,
                    "payload": "action_subscription_status",
                },
            ])
            buttons.append([
                {
                    "type": "callback",
                    "text": texts.BTN_BACK_TO_MENU,
                    "payload": "action_back_to_menu",
                },
            ])
        else:
            buttons.append([
                {
                    "type": "callback",
                    "text": texts.BTN_SUBSCRIBE,
                    "payload": "action_start_payment",
                },
            ])
            buttons.append([
                {
                    "type": "callback",
                    "text": texts.BTN_BACK_TO_MENU,
                    "payload": "action_back_to_menu",
                },
            ])

        return cls._build_attachment(buttons)

    @classmethod
    def get_subscription_keyboard(
        cls,
        payment_url: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Клавиатура оплаты подписки.

        Args:
            payment_url: URL для перехода на страницу оплаты YooKassa.

        Returns:
            Вложение inline_keyboard с кнопками оплаты.
        """
        buttons: List[List[Dict[str, Any]]] = []

        if payment_url:
            buttons.append([
                {
                    "type": "link",
                    "text": texts.BTN_PAY_LINK,
                    "url": payment_url,
                },
            ])

        buttons.append([
            {
                "type": "callback",
                "text": texts.BTN_CHECK_PAYMENT_MAX,
                "payload": "action_check_payment",
            },
        ])
        buttons.append([
            {
                "type": "callback",
                "text": texts.BTN_BACK_TO_MENU,
                "payload": "action_back_to_menu",
            },
        ])

        return cls._build_attachment(buttons)

    @classmethod
    def get_email_cancel_keyboard(cls) -> Dict[str, Any]:
        """Клавиатура отмены при ожидании ввода email.

        Returns:
            Вложение inline_keyboard с кнопкой отмены.
        """
        buttons = [
            [
                {
                    "type": "callback",
                    "text": texts.BTN_BACK_TO_MENU,
                    "payload": "action_back_to_menu",
                },
            ],
        ]
        return cls._build_attachment(buttons)

    @classmethod
    def get_paywall_keyboard(cls) -> Dict[str, Any]:
        """Клавиатура пэйволла.

        Returns:
            Вложение inline_keyboard с кнопками оформления подписки.
        """
        buttons = [
            [
                {
                    "type": "callback",
                    "text": texts.BTN_SUBSCRIBE,
                    "payload": "action_start_payment",
                },
            ],
            [
                {
                    "type": "callback",
                    "text": texts.BTN_BACK_TO_MENU,
                    "payload": "action_back_to_menu",
                },
            ],
        ]
        return cls._build_attachment(buttons)

    @classmethod
    def get_cancel_subscription_confirmation(cls) -> Dict[str, Any]:
        """Клавиатура подтверждения отмены автопродления.

        Returns:
            Вложение inline_keyboard с кнопками подтверждения/отмены.
        """
        buttons = [
            [
                {
                    "type": "callback",
                    "text": texts.BTN_CONFIRM_CANCEL_SUB_MAX,
                    "payload": "action_confirm_cancel_sub",
                },
            ],
            [
                {
                    "type": "callback",
                    "text": texts.BTN_BACK_NO,
                    "payload": "action_subscription_status",
                },
            ],
        ]
        return cls._build_attachment(buttons)

    @classmethod
    def get_prediction_actions(cls) -> Dict[str, Any]:
        """Кнопки после получения предсказания.

        Returns:
            Вложение inline_keyboard с действиями после предсказания.
        """
        buttons = [
            [
                {
                    "type": "callback",
                    "text": texts.BTN_NEW_PREDICTION,
                    "payload": "action_new_prediction",
                },
            ],
            [
                {
                    "type": "callback",
                    "text": texts.BTN_SHOW_HISTORY,
                    "payload": "action_show_history",
                },
            ],
            [
                {
                    "type": "callback",
                    "text": texts.BTN_BACK_TO_MENU,
                    "payload": "action_back_to_menu",
                },
            ],
        ]
        return cls._build_attachment(buttons)

    @classmethod
    def get_confirmation_keyboard(cls, action: str) -> Dict[str, Any]:
        """Клавиатура подтверждения опасного действия.

        Args:
            action: Идентификатор действия (например, 'clear_history').

        Returns:
            Вложение inline_keyboard с кнопками подтверждения/отмены.
        """
        buttons = [
            [
                {
                    "type": "callback",
                    "text": texts.BTN_CONFIRM,
                    "payload": f"confirm_{action}",
                },
            ],
            [
                {
                    "type": "callback",
                    "text": texts.BTN_CANCEL,
                    "payload": "action_cancel",
                },
            ],
        ]
        return cls._build_attachment(buttons)

    @classmethod
    def get_back_to_menu_button(cls) -> Dict[str, Any]:
        """Одиночная кнопка возврата в меню.

        Returns:
            Вложение inline_keyboard с одной кнопкой.
        """
        buttons = [
            [
                {
                    "type": "callback",
                    "text": texts.BTN_BACK_TO_MENU,
                    "payload": "action_back_to_menu",
                },
            ],
        ]
        return cls._build_attachment(buttons)
