"""HTTP-клиент для MAX Bot API.

Инкапсулирует все HTTP-запросы к platform-api.max.ru.
Предоставляет асинхронные методы для работы с ботом в мессенджере MAX.
"""

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import aiohttp

logger = logging.getLogger(__name__)

# Базовый URL MAX Bot API
MAX_API_BASE_URL = "https://platform-api.max.ru"


@dataclass
class MaxUser:
    """Модель пользователя MAX."""

    user_id: int
    first_name: str
    last_name: Optional[str] = None
    username: Optional[str] = None
    is_bot: bool = False
    last_activity_time: Optional[int] = None
    name: Optional[str] = None
    description: Optional[str] = None
    avatar_url: Optional[str] = None
    full_avatar_url: Optional[str] = None

    @property
    def full_name(self) -> str:
        """Полное имя пользователя."""
        if self.last_name:
            return f"{self.first_name} {self.last_name}"
        return self.first_name


@dataclass
class MaxRecipient:
    """Модель получателя сообщения в MAX."""

    chat_id: Optional[int] = None
    chat_type: Optional[str] = None
    user_id: Optional[int] = None


@dataclass
class MaxMessageBody:
    """Тело сообщения MAX."""

    mid: Optional[str] = None
    seq: Optional[int] = None
    text: Optional[str] = None
    attachments: Optional[List[Dict[str, Any]]] = None
    markup: Optional[str] = None


@dataclass
class MaxMessage:
    """Модель сообщения MAX."""

    sender: Optional[MaxUser] = None
    recipient: Optional[MaxRecipient] = None
    timestamp: int = 0
    body: Optional[MaxMessageBody] = None
    link: Optional[Dict[str, Any]] = None
    stat: Optional[Dict[str, Any]] = None
    url: Optional[str] = None

    @property
    def chat_id(self) -> Optional[int]:
        """ID чата из получателя."""
        if self.recipient:
            return self.recipient.chat_id
        return None

    @property
    def text(self) -> Optional[str]:
        """Текст сообщения."""
        if self.body:
            return self.body.text
        return None

    @property
    def message_id(self) -> Optional[str]:
        """ID сообщения."""
        if self.body:
            return self.body.mid
        return None


@dataclass
class MaxCallback:
    """Модель callback от нажатия кнопки в MAX."""

    timestamp: int = 0
    callback_id: Optional[str] = None
    payload: Optional[str] = None
    user: Optional[MaxUser] = None
    message: Optional[MaxMessage] = None


@dataclass
class MaxUpdate:
    """Модель обновления из MAX Bot API."""

    update_type: str = ""
    timestamp: int = 0
    message: Optional[MaxMessage] = None
    callback: Optional[MaxCallback] = None
    user: Optional[MaxUser] = None
    chat_id: Optional[int] = None
    user_locale: Optional[str] = None
    payload: Optional[str] = None


@dataclass
class MaxPhotoAttachment:
    """Данные фото-вложения из MAX."""

    token: Optional[str] = None
    url: Optional[str] = None
    photo_id: Optional[int] = None
    width: int = 0
    height: int = 0
    file_size: int = 0


class MaxApiError(Exception):
    """Ошибка при работе с MAX Bot API."""

    def __init__(self, message: str, status_code: Optional[int] = None, details: Optional[str] = None):
        self.message = message
        self.status_code = status_code
        self.details = details
        super().__init__(self.message)


class MaxApiClient:
    """HTTP-клиент для взаимодействия с MAX Bot API.

    Предоставляет асинхронные методы для всех операций:
    получение информации о боте, отправка сообщений,
    скачивание/загрузка файлов, long polling обновлений.
    """

    def __init__(self, token: str, base_url: str = MAX_API_BASE_URL):
        """Инициализация клиента.

        Args:
            token: Токен доступа бота MAX.
            base_url: Базовый URL API (по умолчанию production).
        """
        self._token = token
        self._base_url = base_url.rstrip("/")
        self._session: Optional[aiohttp.ClientSession] = None

    async def _get_session(self) -> aiohttp.ClientSession:
        """Получение или создание HTTP-сессии."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                headers={"Authorization": self._token},
                timeout=aiohttp.ClientTimeout(total=120),
            )
        return self._session

    async def close(self) -> None:
        """Закрытие HTTP-сессии."""
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None
            logger.info("MAX API клиент: HTTP-сессия закрыта")

    async def _request(
        self,
        method: str,
        endpoint: str,
        params: Optional[Dict[str, Any]] = None,
        json_data: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Выполнение HTTP-запроса к MAX API.

        Args:
            method: HTTP-метод (GET, POST, PUT, DELETE, PATCH).
            endpoint: Путь эндпоинта (например, /me).
            params: Query-параметры запроса.
            json_data: Тело запроса в формате JSON.

        Returns:
            Распарсенный JSON-ответ.

        Raises:
            MaxApiError: При ошибке HTTP-запроса или API.
        """
        url = f"{self._base_url}{endpoint}"
        session = await self._get_session()

        # Очистка None-значений из параметров
        if params:
            params = {k: v for k, v in params.items() if v is not None}

        try:
            async with session.request(
                method=method,
                url=url,
                params=params,
                json=json_data,
            ) as response:
                response_text = await response.text()

                if response.status == 200:
                    if response_text:
                        return await response.json()
                    return {}

                logger.error(
                    "MAX API ошибка: %s %s -> %d: %s",
                    method, endpoint, response.status, response_text,
                )
                raise MaxApiError(
                    message=f"Ошибка MAX API: HTTP {response.status}",
                    status_code=response.status,
                    details=response_text,
                )

        except aiohttp.ClientError as e:
            logger.error("MAX API сетевая ошибка: %s %s -> %s", method, endpoint, e)
            raise MaxApiError(
                message="Сетевая ошибка при обращении к MAX API",
                details=str(e),
            ) from e

    # ────────────────────────────────────────────
    #  Информация о боте
    # ────────────────────────────────────────────

    async def get_me(self) -> MaxUser:
        """Получение информации о текущем боте.

        Returns:
            Объект MaxUser с данными бота.
        """
        data = await self._request("GET", "/me")
        return self._parse_user(data)

    # ────────────────────────────────────────────
    #  Отправка сообщений
    # ────────────────────────────────────────────

    async def send_message(
        self,
        chat_id: Optional[int] = None,
        user_id: Optional[int] = None,
        text: Optional[str] = None,
        attachments: Optional[List[Dict[str, Any]]] = None,
        link: Optional[Dict[str, Any]] = None,
        notify: bool = True,
        format_type: Optional[str] = None,
        disable_link_preview: Optional[bool] = None,
    ) -> MaxMessage:
        """Отправка сообщения в чат или пользователю.

        Args:
            chat_id: ID чата (для групповых чатов).
            user_id: ID пользователя (для диалогов).
            text: Текст сообщения (до 4000 символов).
            attachments: Список вложений.
            link: Ссылка на сообщение (ответ/пересылка).
            notify: Уведомлять ли участников.
            format_type: Формат текста ('markdown' или 'html').
            disable_link_preview: Отключить превью ссылок.

        Returns:
            Объект MaxMessage отправленного сообщения.
        """
        params: Dict[str, Any] = {}
        if chat_id is not None:
            params["chat_id"] = chat_id
        if user_id is not None:
            params["user_id"] = user_id
        if disable_link_preview is not None:
            params["disable_link_preview"] = disable_link_preview

        body: Dict[str, Any] = {}
        if text is not None:
            body["text"] = text
        if attachments is not None:
            body["attachments"] = attachments
        if link is not None:
            body["link"] = link
        if not notify:
            body["notify"] = False
        if format_type is not None:
            body["format"] = format_type

        data = await self._request("POST", "/messages", params=params, json_data=body)
        return self._parse_message(data.get("message", data))

    async def edit_message(
        self,
        message_id: str,
        text: Optional[str] = None,
        attachments: Optional[List[Dict[str, Any]]] = None,
        format_type: Optional[str] = None,
    ) -> bool:
        """Редактирование сообщения.

        Args:
            message_id: ID редактируемого сообщения.
            text: Новый текст сообщения.
            attachments: Новые вложения.
            format_type: Формат текста.

        Returns:
            True при успешном редактировании.
        """
        params = {"message_id": message_id}

        body: Dict[str, Any] = {}
        if text is not None:
            body["text"] = text
        if attachments is not None:
            body["attachments"] = attachments
        if format_type is not None:
            body["format"] = format_type

        data = await self._request("PUT", "/messages", params=params, json_data=body)
        return data.get("success", False)

    async def delete_message(self, message_id: str) -> bool:
        """Удаление сообщения.

        Args:
            message_id: ID удаляемого сообщения.

        Returns:
            True при успешном удалении.
        """
        params = {"message_id": message_id}
        data = await self._request("DELETE", "/messages", params=params)
        return data.get("success", False)

    # ────────────────────────────────────────────
    #  Callback-ответы
    # ────────────────────────────────────────────

    async def answer_callback(
        self,
        callback_id: str,
        message: Optional[Dict[str, Any]] = None,
        notification: Optional[str] = None,
    ) -> bool:
        """Ответ на callback от нажатия кнопки.

        Args:
            callback_id: ID callback-а из обновления.
            message: Новое тело сообщения (для обновления).
            notification: Текст уведомления пользователю.

        Returns:
            True при успешном ответе.
        """
        params = {"callback_id": callback_id}

        body: Dict[str, Any] = {}
        if message is not None:
            body["message"] = message
        if notification is not None:
            body["notification"] = notification

        data = await self._request("POST", "/answers", params=params, json_data=body)
        return data.get("success", False)

    # ────────────────────────────────────────────
    #  Действия бота в чате
    # ────────────────────────────────────────────

    async def send_action(self, chat_id: int, action: str = "typing_on") -> bool:
        """Отправка действия бота в чат.

        Args:
            chat_id: ID чата.
            action: Тип действия (typing_on, sending_photo и др.).

        Returns:
            True при успехе.
        """
        body = {"action": action}
        data = await self._request("POST", f"/chats/{chat_id}/actions", json_data=body)
        return data.get("success", False)

    # ────────────────────────────────────────────
    #  Загрузка файлов
    # ────────────────────────────────────────────

    async def get_upload_url(self, file_type: str = "image") -> Dict[str, Any]:
        """Получение URL для загрузки файла.

        Args:
            file_type: Тип файла ('image', 'video', 'audio', 'file').

        Returns:
            Словарь с полями 'url' и опционально 'token'.
        """
        params = {"type": file_type}
        return await self._request("POST", "/uploads", params=params)

    async def upload_file(self, upload_url: str, file_data: bytes, filename: str = "photo.jpg") -> Dict[str, Any]:
        """Загрузка файла по полученному URL.

        Args:
            upload_url: URL для загрузки (из get_upload_url).
            file_data: Байты файла.
            filename: Имя файла.

        Returns:
            Ответ сервера с токеном загруженного файла.
        """
        session = await self._get_session()

        form_data = aiohttp.FormData()
        form_data.add_field(
            "data",
            file_data,
            filename=filename,
            content_type="image/jpeg",
        )

        try:
            async with session.post(upload_url, data=form_data) as response:
                response_text = await response.text()

                if response.status == 200:
                    return await response.json() if response_text else {}

                logger.error(
                    "MAX API ошибка загрузки файла: %d -> %s",
                    response.status, response_text,
                )
                raise MaxApiError(
                    message=f"Ошибка загрузки файла: HTTP {response.status}",
                    status_code=response.status,
                    details=response_text,
                )

        except aiohttp.ClientError as e:
            logger.error("MAX API сетевая ошибка при загрузке: %s", e)
            raise MaxApiError(
                message="Сетевая ошибка при загрузке файла",
                details=str(e),
            ) from e
    
    async def send_video_from_file(
        self,
        file_path: str,
        chat_id: Optional[int] = None,
        user_id: Optional[int] = None,
        text: Optional[str] = None,
        max_retries: int = 5,
        initial_delay: float = 2.0,
    ) -> MaxMessage:
        """Загрузка видео из локального файла и отправка в чат.

        Выполняет трёхшаговый процесс MAX API:
        1. POST /uploads?type=video → получение upload_url и token.
        2. POST upload_url с multipart файлом → загрузка байтов.
        3. POST /messages с attachment type=video и token → отправка.

        Включает retry при ошибке 'attachment.not.ready' с экспоненциальной задержкой.

        Args:
            file_path: Путь к видеофайлу на диске.
            chat_id: ID чата для отправки (для групповых чатов).
            user_id: ID пользователя для отправки (для диалогов).
            text: Подпись к видео (до 4000 символов).
            max_retries: Максимальное количество попыток отправки при 'not ready'.
            initial_delay: Начальная задержка между попытками (секунды).

        Returns:
            Объект MaxMessage отправленного сообщения.

        Raises:
            MaxApiError: При ошибке на любом этапе загрузки/отправки.
            FileNotFoundError: Если файл не найден по указанному пути.
        """
        import asyncio as _asyncio
        import os as _os

        if not _os.path.isfile(file_path):
            raise FileNotFoundError(f"Видеофайл не найден: {file_path}")

        # Шаг 1: получение URL для загрузки и токена видео
        upload_data = await self.get_upload_url(file_type="video")
        upload_url = upload_data.get("url")
        video_token = upload_data.get("token")

        if not upload_url:
            raise MaxApiError(
                message="MAX API не вернул URL для загрузки видео",
                details=str(upload_data),
            )

        # Шаг 2: загрузка файла по полученному URL
        filename = _os.path.basename(file_path)
        with open(file_path, "rb") as f:
            file_data = f.read()

        session = await self._get_session()

        form_data = aiohttp.FormData()
        form_data.add_field(
            "data",
            file_data,
            filename=filename,
            content_type="video/mp4",
        )

        try:
            async with session.post(upload_url, data=form_data) as response:
                response_text = await response.text()

                if response.status != 200:
                    raise MaxApiError(
                        message=f"Ошибка загрузки видео: HTTP {response.status}",
                        status_code=response.status,
                        details=response_text,
                    )

                # Для video токен приходит в шаге 1, а upload подтверждает загрузку
                logger.info(
                    "MAX API: видео загружено, token=%s, файл=%s",
                    video_token, filename,
                )

        except aiohttp.ClientError as e:
            raise MaxApiError(
                message="Сетевая ошибка при загрузке видео",
                details=str(e),
            ) from e

        # Если токен не пришёл в шаге 1, пробуем извлечь из ответа загрузки
        if not video_token:
            try:
                import json
                upload_response = json.loads(response_text)
                video_token = upload_response.get("token")
            except (json.JSONDecodeError, AttributeError):
                pass

        if not video_token:
            raise MaxApiError(
                message="Не удалось получить токен видео после загрузки",
                details=f"upload_data={upload_data}, upload_response={response_text}",
            )

        # Шаг 3: отправка сообщения с видео-вложением (с retry при 'not ready')
        video_attachment = {
            "type": "video",
            "payload": {
                "token": video_token,
            },
        }

        delay = initial_delay
        last_error: Optional[Exception] = None

        for attempt in range(max_retries):
            try:
                return await self.send_message(
                    chat_id=chat_id,
                    user_id=user_id,
                    text=text,
                    attachments=[video_attachment],
                )
            except MaxApiError as e:
                if e.details and "attachment.not.ready" in str(e.details):
                    last_error = e
                    logger.debug(
                        "MAX API: видео ещё не обработано, попытка %d/%d, ожидание %.1fс",
                        attempt + 1, max_retries, delay,
                    )
                    await _asyncio.sleep(delay)
                    delay *= 1.5  # Экспоненциальная задержка
                else:
                    raise

        # Все попытки исчерпаны
        raise MaxApiError(
            message="Видео не обработано сервером MAX после всех попыток",
            details=str(last_error),
        )

    # ────────────────────────────────────────────
    #  Скачивание файлов (по URL из вложения)
    # ────────────────────────────────────────────

    async def download_file(self, file_url: str) -> bytes:
        """Скачивание файла по URL.

        Args:
            file_url: Прямой URL файла из вложения сообщения.

        Returns:
            Байты файла.

        Raises:
            MaxApiError: При ошибке скачивания.
        """
        session = await self._get_session()

        try:
            async with session.get(file_url) as response:
                if response.status == 200:
                    return await response.read()

                raise MaxApiError(
                    message=f"Ошибка скачивания файла: HTTP {response.status}",
                    status_code=response.status,
                )

        except aiohttp.ClientError as e:
            logger.error("MAX API сетевая ошибка при скачивании: %s", e)
            raise MaxApiError(
                message="Сетевая ошибка при скачивании файла",
                details=str(e),
            ) from e

    # ────────────────────────────────────────────
    #  Long Polling (получение обновлений)
    # ────────────────────────────────────────────

    async def get_updates(
        self,
        marker: Optional[int] = None,
        limit: int = 100,
        timeout: int = 30,
        types: Optional[List[str]] = None,
    ) -> tuple[List[MaxUpdate], Optional[int]]:
        """Получение обновлений через long polling.

        Args:
            marker: Маркер для получения новых обновлений.
            limit: Максимальное количество обновлений (1-1000).
            timeout: Таймаут в секундах (0-90).
            types: Фильтр типов обновлений.

        Returns:
            Кортеж (список обновлений, новый маркер).
        """
        params: Dict[str, Any] = {
            "limit": limit,
            "timeout": timeout,
        }
        if marker is not None:
            params["marker"] = marker
        if types:
            params["types"] = ",".join(types)

        data = await self._request("GET", "/updates", params=params)

        updates = []
        for update_data in data.get("updates", []):
            updates.append(self._parse_update(update_data))

        new_marker = data.get("marker")
        return updates, new_marker

    async def get_updates_raw(
        self,
        marker: Optional[int] = None,
        limit: int = 100,
        timeout: int = 30,
        types: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Получение сырого JSON обновлений без парсинга.

        Используется для диагностики структуры данных от API.

        Args:
            marker: Маркер для получения новых обновлений.
            limit: Максимальное количество обновлений (1-1000).
            timeout: Таймаут в секундах (0-90).
            types: Фильтр типов обновлений.

        Returns:
            Сырой словарь из JSON-ответа API.
        """
        params: Dict[str, Any] = {
            "limit": limit,
            "timeout": timeout,
        }
        if marker is not None:
            params["marker"] = marker
        if types:
            params["types"] = ",".join(types)

        return await self._request("GET", "/updates", params=params)

    # ────────────────────────────────────────────
    #  Парсинг данных из ответов API
    # ────────────────────────────────────────────

    @staticmethod
    def _parse_user(data: Dict[str, Any]) -> MaxUser:
        """Парсинг данных пользователя из JSON."""
        return MaxUser(
            user_id=data.get("user_id", 0),
            first_name=data.get("first_name", ""),
            last_name=data.get("last_name"),
            username=data.get("username"),
            is_bot=data.get("is_bot", False),
            last_activity_time=data.get("last_activity_time"),
            name=data.get("name"),
            description=data.get("description"),
            avatar_url=data.get("avatar_url"),
            full_avatar_url=data.get("full_avatar_url"),
        )

    @staticmethod
    def _parse_recipient(data: Dict[str, Any]) -> MaxRecipient:
        """Парсинг данных получателя из JSON."""
        return MaxRecipient(
            chat_id=data.get("chat_id"),
            chat_type=data.get("chat_type"),
            user_id=data.get("user_id"),
        )

    @staticmethod
    def _parse_message_body(data: Dict[str, Any]) -> MaxMessageBody:
        """Парсинг тела сообщения из JSON."""
        return MaxMessageBody(
            mid=data.get("mid"),
            seq=data.get("seq"),
            text=data.get("text"),
            attachments=data.get("attachments"),
            markup=data.get("markup"),
        )

    @classmethod
    def _parse_message(cls, data: Dict[str, Any]) -> MaxMessage:
        """Парсинг сообщения из JSON."""
        sender = None
        if "sender" in data and data["sender"]:
            sender = cls._parse_user(data["sender"])

        recipient = None
        if "recipient" in data and data["recipient"]:
            recipient = cls._parse_recipient(data["recipient"])

        body = None
        if "body" in data and data["body"]:
            body = cls._parse_message_body(data["body"])

        return MaxMessage(
            sender=sender,
            recipient=recipient,
            timestamp=data.get("timestamp", 0),
            body=body,
            link=data.get("link"),
            stat=data.get("stat"),
            url=data.get("url"),
        )

    @classmethod
    def _parse_callback(cls, data: Dict[str, Any]) -> MaxCallback:
        """Парсинг callback из JSON."""
        user = None
        if "user" in data and data["user"]:
            user = cls._parse_user(data["user"])

        message = None
        if "message" in data and data["message"]:
            message = cls._parse_message(data["message"])

        return MaxCallback(
            timestamp=data.get("timestamp", 0),
            callback_id=data.get("callback_id"),
            payload=data.get("payload"),
            user=user,
            message=message,
        )

    @classmethod
    def _parse_update(cls, data: Dict[str, Any]) -> MaxUpdate:
        """Парсинг обновления из JSON."""
        update_type = data.get("update_type", "")

        message = None
        if "message" in data and data["message"]:
            message = cls._parse_message(data["message"])

        callback = None
        if "callback" in data and data["callback"]:
            callback = cls._parse_callback(data["callback"])

        user = None
        if "user" in data and data["user"]:
            user = cls._parse_user(data["user"])

        return MaxUpdate(
            update_type=update_type,
            timestamp=data.get("timestamp", 0),
            message=message,
            callback=callback,
            user=user,
            chat_id=data.get("chat_id"),
            user_locale=data.get("user_locale"),
            payload=data.get("payload"),
        )

    # ────────────────────────────────────────────
    #  Вспомогательные методы для вложений
    # ────────────────────────────────────────────

    @staticmethod
    def extract_photo_attachments(message: MaxMessage) -> List[Dict[str, Any]]:
        """Извлечение фото-вложений из сообщения.

        Args:
            message: Объект сообщения MAX.

        Returns:
            Список словарей с данными фото (url, token, photo_id и др.).
        """
        photos = []
        if not message.body or not message.body.attachments:
            return photos

        for attachment in message.body.attachments:
            att_type = attachment.get("type", "")
            if att_type == "image":
                payload = attachment.get("payload", {})
                photos.append({
                    "url": payload.get("url", ""),
                    "token": payload.get("token"),
                    "photo_id": payload.get("photo_id"),
                    "width": payload.get("width", 0),
                    "height": payload.get("height", 0),
                })

        return photos

    @staticmethod
    def build_inline_keyboard(buttons: List[List[Dict[str, Any]]]) -> Dict[str, Any]:
        """Построение вложения inline-клавиатуры для MAX.

        Args:
            buttons: Двумерный массив кнопок. Каждая кнопка — словарь
                     с полями type, text, payload/url.

        Returns:
            Вложение типа inline_keyboard для передачи в attachments.
        """
        return {
            "type": "inline_keyboard",
            "payload": {
                "buttons": buttons,
            },
        }
