"""Главный класс MAX-бота.

Управляет жизненным циклом бота: инициализация компонентов,
цикл long polling для получения обновлений, graceful shutdown.
"""

import asyncio
import logging
from typing import Optional

from coffee_oracle.max_bot.api_client import MaxApiClient, MaxApiError
from coffee_oracle.max_bot.handlers import MaxBotHandlers
from coffee_oracle.max_bot.photo_processor import MaxPhotoProcessor

logger = logging.getLogger(__name__)

# Параметры long polling
POLL_TIMEOUT = 30
POLL_LIMIT = 100
POLL_UPDATE_TYPES = [
    "bot_started",
    "message_created",
    "message_callback",
]

# Параметры переподключения при ошибках
INITIAL_RETRY_DELAY = 1.0
MAX_RETRY_DELAY = 60.0
RETRY_MULTIPLIER = 2.0


class MaxOracleBot:
    """MAX-бот Coffee Oracle.

    Инициализирует все необходимые компоненты (API-клиент,
    обработчик фото, обработчики событий) и запускает
    цикл long polling для получения обновлений.

    Args:
        token: Токен доступа бота MAX.
    """

    def __init__(self, token: str):
        self._token = token
        self._running = False
        self._marker: Optional[int] = None
        self._retry_delay = INITIAL_RETRY_DELAY

        # Инициализация компонентов
        self._api_client = MaxApiClient(token=token)
        self._photo_processor = MaxPhotoProcessor(api_client=self._api_client)
        self._handlers = MaxBotHandlers(
            api_client=self._api_client,
            photo_processor=self._photo_processor,
        )

        logger.info("MAX-бот: компоненты инициализированы")

    async def start_polling(self) -> None:
        """Запуск цикла long polling.

        Получает обновления от MAX API в бесконечном цикле.
        При сетевых ошибках переподключается с экспоненциальной задержкой.
        Завершается при вызове stop() или при критической ошибке.
        """
        self._running = True

        # Проверка подключения — получаем информацию о боте
        try:
            bot_info = await self._api_client.get_me()
            logger.info(
                "MAX-бот запущен: id=%d, имя='%s', username='%s'",
                bot_info.user_id,
                bot_info.first_name,
                bot_info.username or "нет",
            )
        except MaxApiError as e:
            logger.error("MAX-бот: не удалось получить информацию о боте: %s", e)
            raise RuntimeError(
                f"MAX-бот не может подключиться к API: {e.message}"
            ) from e

        logger.info("MAX-бот: начинаю long polling (timeout=%d)", POLL_TIMEOUT)

        while self._running:
            try:
                await self._poll_once()
                # Успешный опрос — сбрасываем задержку
                self._retry_delay = INITIAL_RETRY_DELAY

            except MaxApiError as e:
                if not self._running:
                    break

                logger.warning(
                    "MAX-бот: ошибка API при опросе (повтор через %.1f сек): %s",
                    self._retry_delay, e.message,
                )
                await self._wait_before_retry()

            except asyncio.CancelledError:
                logger.info("MAX-бот: polling отменён")
                break

            except Exception as e:
                if not self._running:
                    break

                logger.error(
                    "MAX-бот: непредвиденная ошибка polling (повтор через %.1f сек): %s",
                    self._retry_delay, e,
                    exc_info=True,
                )
                await self._wait_before_retry()

        logger.info("MAX-бот: цикл polling завершён")

    async def _poll_once(self) -> None:
        """Один цикл опроса обновлений.

        Запрашивает обновления от MAX API, обрабатывает каждое
        через маршрутизатор, обновляет маркер.
        """
        updates, new_marker = await self._api_client.get_updates(
            marker=self._marker,
            limit=POLL_LIMIT,
            timeout=POLL_TIMEOUT,
            types=POLL_UPDATE_TYPES,
        )

        # Обновляем маркер для следующего запроса
        if new_marker is not None:
            self._marker = new_marker

        if not updates:
            return

        logger.debug("MAX-бот: получено %d обновлений", len(updates))

        # Обрабатываем каждое обновление
        for update in updates:
            try:
                await self._handlers.handle_update(update)
            except Exception as e:
                logger.error(
                    "MAX-бот: ошибка обработки обновления (тип=%s): %s",
                    update.update_type, e,
                    exc_info=True,
                )

    async def _wait_before_retry(self) -> None:
        """Ожидание перед повторной попыткой с экспоненциальной задержкой."""
        if not self._running:
            return

        await asyncio.sleep(self._retry_delay)

        # Увеличиваем задержку для следующей ошибки
        self._retry_delay = min(
            self._retry_delay * RETRY_MULTIPLIER,
            MAX_RETRY_DELAY,
        )

    async def stop(self) -> None:
        """Корректное завершение работы бота.

        Останавливает цикл polling и закрывает HTTP-сессию.
        """
        logger.info("MAX-бот: остановка...")
        self._running = False

        # Закрытие HTTP-сессии
        await self._api_client.close()

        logger.info("MAX-бот: остановлен")
