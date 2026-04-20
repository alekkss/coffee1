"""Клавиатуры для MAX-бота.

Формирует структуры inline-клавиатур в формате MAX Bot API.
Каждая кнопка — словарь с полями type, text, payload/url.
Клавиатура передаётся как вложение типа inline_keyboard.
"""

from typing import Any, Dict, List, Optional


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

        Содержит основные действия: предсказание, история,
        случайное предсказание, помощь, о боте, очистка, поддержка.

        Returns:
            Вложение inline_keyboard с кнопками главного меню.
        """
        buttons = [
            [
                {
                    "type": "callback",
                    "text": "🔮 Получить предсказание",
                    "payload": "action_predict",
                },
            ],
            [
                {
                    "type": "callback",
                    "text": "📜 Моя история",
                    "payload": "action_history",
                },
                {
                    "type": "callback",
                    "text": "🎯 Случайное",
                    "payload": "action_random",
                },
            ],
            [
                {
                    "type": "callback",
                    "text": "📚 Как гадать",
                    "payload": "action_help",
                },
                {
                    "type": "callback",
                    "text": "ℹ️ О боте",
                    "payload": "action_about",
                },
            ],
            [
                {
                    "type": "callback",
                    "text": "🗑️ Очистить историю",
                    "payload": "action_clear",
                },
                {
                    "type": "callback",
                    "text": "📞 Поддержка",
                    "payload": "action_support",
                },
            ],
        ]
        return cls._build_attachment(buttons)

    @classmethod
    def get_main_menu_with_subscription(cls) -> Dict[str, Any]:
        """Главное меню бота с кнопкой подписки.

        Аналог get_main_menu(), но с добавленной кнопкой
        «💎 Подписка» для управления подпиской и оплатой.

        Returns:
            Вложение inline_keyboard с кнопками главного меню и подпиской.
        """
        buttons = [
            [
                {
                    "type": "callback",
                    "text": "🔮 Получить предсказание",
                    "payload": "action_predict",
                },
            ],
            [
                {
                    "type": "callback",
                    "text": "📜 Моя история",
                    "payload": "action_history",
                },
                {
                    "type": "callback",
                    "text": "🎯 Случайное",
                    "payload": "action_random",
                },
            ],
            [
                {
                    "type": "callback",
                    "text": "💎 Подписка",
                    "payload": "action_subscription",
                },
                {
                    "type": "callback",
                    "text": "📚 Как гадать",
                    "payload": "action_help",
                },
            ],
            [
                {
                    "type": "callback",
                    "text": "ℹ️ О боте",
                    "payload": "action_about",
                },
                {
                    "type": "callback",
                    "text": "📞 Поддержка",
                    "payload": "action_support",
                },
            ],
            [
                {
                    "type": "callback",
                    "text": "🗑️ Очистить историю",
                    "payload": "action_clear",
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

        Набор кнопок зависит от текущего состояния подписки пользователя.

        Args:
            has_active_subscription: Есть ли активная подписка (premium или vip).
            is_vip: Является ли пользователь VIP.
            recurring_enabled: Включено ли автопродление.

        Returns:
            Вложение inline_keyboard с кнопками управления подпиской.
        """
        buttons: List[List[Dict[str, Any]]] = []

        if is_vip:
            # VIP — только возврат в меню
            buttons.append([
                {
                    "type": "callback",
                    "text": "◀️ Назад в меню",
                    "payload": "action_back_to_menu",
                },
            ])
        elif has_active_subscription:
            # Premium — управление подпиской
            if recurring_enabled:
                buttons.append([
                    {
                        "type": "callback",
                        "text": "🔄 Отменить автопродление",
                        "payload": "action_cancel_subscription",
                    },
                ])
            buttons.append([
                {
                    "type": "callback",
                    "text": "🔄 Обновить статус",
                    "payload": "action_subscription_status",
                },
            ])
            buttons.append([
                {
                    "type": "callback",
                    "text": "◀️ Назад в меню",
                    "payload": "action_back_to_menu",
                },
            ])
        else:
            # Free — предложение оформить подписку
            buttons.append([
                {
                    "type": "callback",
                    "text": "⭐ Оформить подписку",
                    "payload": "action_start_payment",
                },
            ])
            buttons.append([
                {
                    "type": "callback",
                    "text": "◀️ Назад в меню",
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

        Содержит ссылку на страницу оплаты YooKassa (если передана)
        и кнопку ручной проверки статуса платежа.

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
                    "text": "💳 Перейти к оплате",
                    "url": payment_url,
                },
            ])

        buttons.append([
            {
                "type": "callback",
                "text": "✅ Я оплатил — проверить",
                "payload": "action_check_payment",
            },
        ])
        buttons.append([
            {
                "type": "callback",
                "text": "◀️ Назад в меню",
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
                    "text": "◀️ Назад в меню",
                    "payload": "action_back_to_menu",
                },
            ],
        ]
        return cls._build_attachment(buttons)

    @classmethod
    def get_paywall_keyboard(cls) -> Dict[str, Any]:
        """Клавиатура пэйволла (лимит бесплатных предсказаний исчерпан).

        Показывается вместо предсказания, когда у пользователя
        закончились бесплатные гадания.

        Returns:
            Вложение inline_keyboard с кнопками оформления подписки.
        """
        buttons = [
            [
                {
                    "type": "callback",
                    "text": "⭐ Оформить подписку",
                    "payload": "action_start_payment",
                },
            ],
            [
                {
                    "type": "callback",
                    "text": "◀️ Назад в меню",
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
                    "text": "✅ Да, отменить автопродление",
                    "payload": "action_confirm_cancel_sub",
                },
            ],
            [
                {
                    "type": "callback",
                    "text": "◀️ Нет, вернуться",
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
                    "text": "🔮 Ещё предсказание",
                    "payload": "action_new_prediction",
                },
            ],
            [
                {
                    "type": "callback",
                    "text": "📜 Моя история",
                    "payload": "action_show_history",
                },
            ],
        ]
        return cls._build_attachment(buttons)

    @classmethod
    def get_help_menu(cls) -> Dict[str, Any]:
        """Меню помощи с разделами.

        Returns:
            Вложение inline_keyboard с кнопками разделов помощи.
        """
        buttons = [
            [
                {
                    "type": "callback",
                    "text": "📸 Как фотографировать",
                    "payload": "help_photo",
                },
            ],
            [
                {
                    "type": "callback",
                    "text": "☕ Приготовление кофе",
                    "payload": "help_coffee",
                },
            ],
            [
                {
                    "type": "callback",
                    "text": "🔮 О гадании",
                    "payload": "help_divination",
                },
            ],
            [
                {
                    "type": "callback",
                    "text": "❓ Частые вопросы",
                    "payload": "help_faq",
                },
            ],
            [
                {
                    "type": "callback",
                    "text": "◀️ Назад в меню",
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
                    "text": "✅ Да, подтверждаю",
                    "payload": f"confirm_{action}",
                },
            ],
            [
                {
                    "type": "callback",
                    "text": "❌ Отмена",
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
                    "text": "◀️ Назад в меню",
                    "payload": "action_back_to_menu",
                },
            ],
        ]
        return cls._build_attachment(buttons)
