"""Обработчик фотографий для MAX-бота.

Скачивает фото через MAX API, ресайзит, сохраняет на диск,
отправляет на анализ в LLM. Переиспользует общую логику
ресайза и сохранения из базового PhotoProcessor.
"""

import io
import logging
import os
import uuid
from typing import Any, Dict, List, Optional, Tuple

from PIL import Image

from coffee_oracle.max_bot.api_client import MaxApiClient, MaxApiError, MaxMessage
from coffee_oracle.services.openai_client import get_llm_client, LLMClient
from coffee_oracle.utils.errors import OpenAIError, PhotoProcessingError

logger = logging.getLogger(__name__)

# Константы обработки изображений (идентичны оригинальному PhotoProcessor)
MAX_IMAGE_DIMENSION = 800
MAX_IMAGE_SIZE_BYTES = 4 * 1024 * 1024
JPEG_QUALITY = 85
MEDIA_DIR = "/app/media"


class MaxPhotoProcessor:
    """Обработчик фотографий из MAX-мессенджера.

    Скачивает изображения через MAX API, приводит к нужному размеру
    и формату, сохраняет на диск, отправляет в LLM для анализа.

    Args:
        api_client: HTTP-клиент MAX API для скачивания файлов.
        llm_client: Клиент LLM для анализа изображений (опционально,
                    по умолчанию используется глобальный экземпляр).
    """

    def __init__(
        self,
        api_client: MaxApiClient,
        llm_client: Optional[LLMClient] = None,
    ):
        self._api_client = api_client
        self._llm_client = llm_client or get_llm_client()

    # ────────────────────────────────────────────
    #  Ресайз и сохранение (общая логика)
    # ────────────────────────────────────────────

    @staticmethod
    def _resize_image(image_data: bytes) -> bytes:
        """Ресайз и конвертация изображения в JPEG.

        Приводит изображение к максимальному размеру MAX_IMAGE_DIMENSION
        с сохранением пропорций. Прозрачные PNG получают белый фон.
        Если файл всё ещё слишком большой — итеративно снижает качество.

        Args:
            image_data: Исходные байты изображения.

        Returns:
            Байты обработанного JPEG-изображения.
        """
        try:
            img = Image.open(io.BytesIO(image_data))

            # Конвертация в RGB при необходимости
            if img.mode in ("RGBA", "LA", "P"):
                background = Image.new("RGB", img.size, (255, 255, 255))
                if img.mode == "P":
                    img = img.convert("RGBA")
                if img.mode in ("RGBA", "LA"):
                    background.paste(img, mask=img.split()[-1])
                else:
                    background.paste(img)
                img = background
            elif img.mode != "RGB":
                img = img.convert("RGB")

            original_size = len(image_data)
            width, height = img.size

            # Проверка необходимости ресайза
            needs_resize = (
                width > MAX_IMAGE_DIMENSION
                or height > MAX_IMAGE_DIMENSION
                or original_size > MAX_IMAGE_SIZE_BYTES
            )

            if not needs_resize:
                output = io.BytesIO()
                img.save(output, format="JPEG", quality=JPEG_QUALITY, optimize=True)
                result = output.getvalue()
                logger.debug(
                    "Изображение конвертировано в JPEG: %d -> %d байт",
                    original_size, len(result),
                )
                return result

            # Вычисление новых размеров с сохранением пропорций
            if width >= height:
                new_width = min(width, MAX_IMAGE_DIMENSION)
                new_height = int(height * (new_width / width))
            else:
                new_height = min(height, MAX_IMAGE_DIMENSION)
                new_width = int(width * (new_height / height))

            img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)

            # Итеративное сжатие до допустимого размера
            output = io.BytesIO()
            quality = JPEG_QUALITY

            while quality >= 50:
                output.seek(0)
                output.truncate()
                img.save(output, format="JPEG", quality=quality, optimize=True)

                if output.tell() <= MAX_IMAGE_SIZE_BYTES:
                    break
                quality -= 10

            result = output.getvalue()
            logger.info(
                "Изображение уменьшено: %dx%d -> %dx%d, %d -> %d байт (quality=%d)",
                width, height, new_width, new_height,
                original_size, len(result), quality,
            )
            return result

        except Exception as e:
            logger.warning("Не удалось обработать изображение, используется оригинал: %s", e)
            return image_data

    @staticmethod
    def _save_image_to_disk(image_data: bytes) -> Optional[str]:
        """Сохранение изображения на диск.

        Args:
            image_data: Байты изображения.

        Returns:
            Имя файла (без пути) или None при ошибке.
        """
        try:
            os.makedirs(MEDIA_DIR, exist_ok=True)
            filename = f"{uuid.uuid4()}.jpg"
            filepath = os.path.join(MEDIA_DIR, filename)

            with open(filepath, "wb") as f:
                f.write(image_data)

            logger.info("Изображение сохранено: %s", filepath)
            return filename
        except OSError as e:
            logger.error("Ошибка сохранения изображения на диск: %s", e)
            return None

    # ────────────────────────────────────────────
    #  Извлечение фото из сообщения MAX
    # ────────────────────────────────────────────

    @staticmethod
    def extract_photo_urls(message: MaxMessage) -> List[str]:
        """Извлечение URL фото-вложений из сообщения MAX.

        Args:
            message: Объект сообщения MAX.

        Returns:
            Список URL изображений.
        """
        urls: List[str] = []
        if not message.body or not message.body.attachments:
            return urls

        for attachment in message.body.attachments:
            att_type = attachment.get("type", "")
            if att_type == "image":
                payload = attachment.get("payload", {})
                url = payload.get("url", "")
                if url:
                    urls.append(url)

        return urls

    @staticmethod
    def has_photos(message: MaxMessage) -> bool:
        """Проверка наличия фото-вложений в сообщении.

        Args:
            message: Объект сообщения MAX.

        Returns:
            True если сообщение содержит хотя бы одно изображение.
        """
        if not message.body or not message.body.attachments:
            return False

        for attachment in message.body.attachments:
            if attachment.get("type") == "image":
                return True

        return False

    # ────────────────────────────────────────────
    #  Скачивание фото через MAX API
    # ────────────────────────────────────────────

    async def _download_photo(self, photo_url: str) -> bytes:
        """Скачивание одного фото по URL через MAX API.

        Args:
            photo_url: URL изображения из вложения.

        Returns:
            Байты изображения.

        Raises:
            PhotoProcessingError: При ошибке скачивания.
        """
        try:
            image_data = await self._api_client.download_file(photo_url)

            if not image_data:
                raise PhotoProcessingError(
                    "📸 Не удалось скачать фото. Попробуйте отправить другое.",
                    "Пустые данные при скачивании фото из MAX",
                )

            return image_data

        except MaxApiError as e:
            logger.error("Ошибка скачивания фото из MAX: %s", e)
            raise PhotoProcessingError(
                "📸 Не удалось скачать фото. Попробуйте отправить другое.",
                f"MAX API ошибка скачивания: {e.details}",
            ) from e

    # ────────────────────────────────────────────
    #  Обработка одного фото
    # ────────────────────────────────────────────

    async def process_single_photo(
        self,
        photo_url: str,
        user_message: Optional[str] = None,
        username: Optional[str] = None,
    ) -> Tuple[Optional[str], List[Dict[str, str]]]:
        """Обработка одного фото: скачивание, ресайз, анализ LLM.

        Args:
            photo_url: URL изображения из вложения MAX.
            user_message: Текст запроса пользователя (caption).
            username: Имя пользователя для персонализации.

        Returns:
            Кортеж (текст_предсказания, список_данных_фото).
            Список данных фото содержит словари с ключами
            'file_path' и 'file_id'.

        Raises:
            PhotoProcessingError: При ошибке обработки фото.
            OpenAIError: При ошибке анализа через LLM.
        """
        # Скачивание
        image_data = await self._download_photo(photo_url)

        # Ресайз
        image_data = self._resize_image(image_data)

        # Сохранение на диск
        saved_filename = self._save_image_to_disk(image_data)

        # Анализ через LLM
        try:
            prediction = await self._llm_client.analyze_coffee_image(
                image_data,
                user_message=user_message,
                username=username,
            )
        except OpenAIError:
            raise

        # Формирование данных о фото
        photos_data: List[Dict[str, str]] = []
        if saved_filename:
            photos_data.append({
                "file_path": saved_filename,
                "file_id": photo_url,  # В MAX используем URL как идентификатор
            })

        return prediction, photos_data

    # ────────────────────────────────────────────
    #  Обработка нескольких фото
    # ────────────────────────────────────────────

    async def process_multiple_photos(
        self,
        photo_urls: List[str],
        user_message: Optional[str] = None,
        username: Optional[str] = None,
    ) -> Tuple[Optional[str], List[Dict[str, str]]]:
        """Обработка нескольких фото: скачивание, ресайз, общий анализ LLM.

        Args:
            photo_urls: Список URL изображений из вложений MAX.
            user_message: Текст запроса пользователя.
            username: Имя пользователя для персонализации.

        Returns:
            Кортеж (текст_предсказания, список_данных_фото).

        Raises:
            PhotoProcessingError: Если ни одно фото не удалось обработать.
            OpenAIError: При ошибке анализа через LLM.
        """
        if not photo_urls:
            raise PhotoProcessingError(
                "📸 Не найдено фотографий для анализа.",
                "Пустой список URL фото",
            )

        images_data: List[bytes] = []
        photos_data: List[Dict[str, str]] = []

        for photo_url in photo_urls:
            try:
                # Скачивание
                raw_data = await self._download_photo(photo_url)

                # Ресайз
                processed_data = self._resize_image(raw_data)
                images_data.append(processed_data)

                # Сохранение на диск
                saved_filename = self._save_image_to_disk(processed_data)
                if saved_filename:
                    photos_data.append({
                        "file_path": saved_filename,
                        "file_id": photo_url,
                    })

            except PhotoProcessingError as e:
                logger.warning(
                    "Пропуск фото %s при групповой обработке: %s",
                    photo_url, e.details,
                )
                continue

        if not images_data:
            raise PhotoProcessingError(
                "📸 Не удалось обработать ни одно фото. Попробуйте другие изображения.",
                "Все фото из группы не удалось скачать/обработать",
            )

        logger.info("Обработка %d фото для предсказания в MAX", len(images_data))

        # Анализ через LLM
        try:
            if len(images_data) == 1:
                prediction = await self._llm_client.analyze_coffee_image(
                    images_data[0],
                    user_message=user_message,
                    username=username,
                )
            else:
                prediction = await self._llm_client.analyze_multiple_images(
                    images_data,
                    user_message=user_message,
                    username=username,
                )
        except OpenAIError:
            raise

        return prediction, photos_data
