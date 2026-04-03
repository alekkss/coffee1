"""Клавиатуры для MAX-бота.

Формирует структуры inline-клавиатур в формате MAX Bot API.
Каждая кнопка — словарь с полями type, text, payload/url.
Клавиатура передаётся как вложение типа inline_keyboard.
"""

from typing import Any, Dict, List


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
        """Главное меню бота.

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
