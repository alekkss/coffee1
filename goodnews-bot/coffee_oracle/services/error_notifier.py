"""Telegram error notification service.

Sends error logs to specified Telegram users via a custom logging handler.
Configured via ERROR_NOTIFY_TELEGRAM_IDS environment variable (comma-separated).
"""

import asyncio
import logging
import time
import os
from typing import List, Optional

from aiogram import Bot

logger = logging.getLogger(__name__)

# Deduplicate identical errors within this window (seconds)
DEDUP_WINDOW = 60
MAX_MESSAGE_LENGTH = 4000


class TelegramErrorHandler(logging.Handler):
    """Logging handler that sends ERROR+ logs to Telegram users."""

    def __init__(self, bot: Bot, chat_ids: List[int]):
        super().__init__(level=logging.ERROR)
        self.bot = bot
        self.chat_ids = chat_ids
        self._recent: dict[str, float] = {}
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
            # Deduplicate
            now = time.monotonic()
            key = f"{record.name}:{record.lineno}:{record.getMessage()}"
            last = self._recent.get(key)
            if last and now - last < DEDUP_WINDOW:
                return
            self._recent[key] = now
            # Cleanup old entries
            self._recent = {
                k: v for k, v in self._recent.items() if now - v < DEDUP_WINDOW
            }

            text = f"🚨 <b>Error</b>\n<pre>{_escape_html(msg[:MAX_MESSAGE_LENGTH])}</pre>"
            self._send(text)
        except Exception:
            self.handleError(record)

    def _send(self, text: str) -> None:
        loop = self._get_loop()
        if loop is None or loop.is_closed():
            return
        for chat_id in self.chat_ids:
            asyncio.run_coroutine_threadsafe(
                self._safe_send(chat_id, text), loop
            )

    async def _safe_send(self, chat_id: int, text: str) -> None:
        try:
            await self.bot.send_message(chat_id, text, parse_mode="HTML")
        except Exception as e:
            # Avoid recursion — don't use logger here
            print(f"[ErrorNotifier] Failed to send to {chat_id}: {e}")

    def _get_loop(self) -> Optional[asyncio.AbstractEventLoop]:
        if self._loop is None or self._loop.is_closed():
            try:
                self._loop = asyncio.get_running_loop()
            except RuntimeError:
                return None
        return self._loop


def _escape_html(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def setup_error_notifier(bot: Bot) -> Optional[TelegramErrorHandler]:
    """Register the Telegram error handler if chat IDs are configured.

    Call this after the bot is created and the event loop is running.
    Returns the handler instance or None if not configured.
    """
    raw = os.getenv("ERROR_NOTIFY_TELEGRAM_IDS", "").strip()
    if not raw:
        return None

    try:
        chat_ids = [int(x.strip()) for x in raw.split(",") if x.strip()]
    except ValueError:
        logger.warning("Invalid ERROR_NOTIFY_TELEGRAM_IDS value: %s", raw)
        return None

    if not chat_ids:
        return None

    handler = TelegramErrorHandler(bot, chat_ids)
    handler.setFormatter(
        logging.Formatter("%(asctime)s [%(name)s] %(levelname)s: %(message)s")
    )
    logging.getLogger().addHandler(handler)
    logger.info(
        "Error notifier enabled for %d recipient(s)", len(chat_ids)
    )
    return handler
