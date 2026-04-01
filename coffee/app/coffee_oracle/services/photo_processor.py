import io
import logging
import os
import uuid
from typing import Optional, Tuple, List, Dict

from aiogram import Bot
from aiogram.types import PhotoSize
from PIL import Image

from coffee_oracle.services.openai_client import get_llm_client
from coffee_oracle.utils.errors import PhotoProcessingError, OpenAIError

logger = logging.getLogger(__name__)

# Image size limits
MAX_IMAGE_DIMENSION = 800  # Max width or height in pixels for API
MAX_IMAGE_SIZE_BYTES = 4 * 1024 * 1024  # 4MB for API
JPEG_QUALITY = 85
MEDIA_DIR = "/opt/oracle-bot/media"


class PhotoProcessor:
    """Service for processing photos from Telegram."""
    
    def __init__(self, bot: Bot):
        self.bot = bot
        self.llm_client = get_llm_client()
    
    def _resize_image(self, image_data: bytes) -> bytes:
        """
        Resize image if it's too large.
        
        Args:
            image_data: Original image bytes
            
        Returns:
            Resized image bytes (JPEG format)
        """
        try:
            img = Image.open(io.BytesIO(image_data))
            
            # Convert to RGB if necessary (for PNG with transparency, etc.)
            if img.mode in ('RGBA', 'LA', 'P'):
                # Create white background
                background = Image.new('RGB', img.size, (255, 255, 255))
                if img.mode == 'P':
                    img = img.convert('RGBA')
                background.paste(img, mask=img.split()[-1] if img.mode == 'RGBA' else None)
                img = background
            elif img.mode != 'RGB':
                img = img.convert('RGB')
            
            original_size = len(image_data)
            width, height = img.size
            
            # Check if resize is needed
            needs_resize = (
                width > MAX_IMAGE_DIMENSION or 
                height > MAX_IMAGE_DIMENSION or 
                original_size > MAX_IMAGE_SIZE_BYTES
            )
            
            if not needs_resize:
                # Still convert to JPEG for consistency
                output = io.BytesIO()
                img.save(output, format='JPEG', quality=JPEG_QUALITY, optimize=True)
                result = output.getvalue()
                logger.debug("Image converted to JPEG: %d -> %d bytes", original_size, len(result))
                return result
            
            # Calculate new dimensions maintaining aspect ratio
            if width > height:
                if width > MAX_IMAGE_DIMENSION:
                    new_width = MAX_IMAGE_DIMENSION
                    new_height = int(height * (MAX_IMAGE_DIMENSION / width))
                else:
                    new_width, new_height = width, height
            else:
                if height > MAX_IMAGE_DIMENSION:
                    new_height = MAX_IMAGE_DIMENSION
                    new_width = int(width * (MAX_IMAGE_DIMENSION / height))
                else:
                    new_width, new_height = width, height
            
            # Resize image
            img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
            
            # Save to bytes with compression
            output = io.BytesIO()
            quality = JPEG_QUALITY
            
            # Iteratively reduce quality if still too large
            while quality >= 50:
                output.seek(0)
                output.truncate()
                img.save(output, format='JPEG', quality=quality, optimize=True)
                
                if output.tell() <= MAX_IMAGE_SIZE_BYTES:
                    break
                quality -= 10
            
            result = output.getvalue()
            logger.info(
                "Image resized: %dx%d -> %dx%d, %d -> %d bytes (quality=%d)",
                width, height, new_width, new_height, original_size, len(result), quality
            )
            
            return result
            
        except Exception as e:
            logger.warning("Failed to resize image, using original: %s", e)
            return image_data

    def _save_image_to_disk(self, image_data: bytes) -> Optional[str]:
        """Save image to disk and return filename."""
        try:
            os.makedirs(MEDIA_DIR, exist_ok=True)
            filename = f"{uuid.uuid4()}.jpg"
            filepath = os.path.join(MEDIA_DIR, filename)
            
            with open(filepath, "wb") as f:
                f.write(image_data)
                
            logger.info("Saved image to %s", filepath)
            return filename
        except Exception as e:
            logger.error("Failed to save image to disk: %s", e)
            return None
    
    async def process_photo(
        self, 
        photo: PhotoSize, 
        user_message: Optional[str] = None,
        username: Optional[str] = None
    ) -> Tuple[Optional[str], Optional[str]]:
        """Process photo and generate prediction.
        
        Args:
            photo: Telegram photo object
            user_message: Optional user's question or context
            username: Optional user's name
            
        Returns:
            Tuple of (prediction_text, photo_filename)
        """
        try:
            # Download photo from Telegram
            file_info = await self.bot.get_file(photo.file_id)
            if not file_info.file_path:
                logger.error("Could not get file path from Telegram for file_id: %s", photo.file_id)
                raise PhotoProcessingError(
                    "🔮 Не удалось получить фото. Попробуйте отправить другое изображение.",
                    "Could not get file path from Telegram"
                )
            
            # Download file content
            file_content = await self.bot.download_file(file_info.file_path)
            if not file_content:
                logger.error("Could not download file content for path: %s", file_info.file_path)
                raise PhotoProcessingError(
                    "🔮 Не удалось загрузить фото. Попробуйте отправить другое изображение.",
                    "Could not download file content"
                )
            
            # Convert to bytes if needed
            if hasattr(file_content, 'read'):
                image_data = file_content.read()
            else:
                image_data = file_content
            
            if not image_data:
                raise PhotoProcessingError(
                    "🔮 Фото повреждено или пустое. Попробуйте отправить другое изображение.",
                    "Empty image data"
                )
            
            # Resize image if too large
            image_data = self._resize_image(image_data)
            
            # Save to disk
            photo_filename = self._save_image_to_disk(image_data)
            
            # Analyze with LLM
            try:
                prediction = await self.llm_client.analyze_coffee_image(
                    image_data, 
                    user_message=user_message,
                    username=username
                )
                return prediction, photo_filename
            except OpenAIError:
                # Re-raise OpenAI errors as they already have user-friendly messages
                raise
            
        except PhotoProcessingError:
            # Re-raise our custom errors
            raise
        except OpenAIError:
            # Re-raise OpenAI errors
            raise
        except Exception as e:
            logger.error(
                "Unexpected error processing photo: file_id=%s, file_path=%s, "
                "user_message=%r, username=%r, error_type=%s, error=%s",
                photo.file_id,
                getattr(file_info, 'file_path', 'N/A') if 'file_info' in dir() else 'not_downloaded',
                user_message,
                username,
                type(e).__name__,
                e,
                exc_info=True,
            )
            raise PhotoProcessingError(
                "🔮 Произошла ошибка при обработке фото. Попробуйте еще раз.",
                f"Unexpected error ({type(e).__name__}): {e}"
            ) from e
    
    def is_valid_photo(self, photo_sizes: list[PhotoSize]) -> bool:
        """Check if photo is valid for processing."""
        if not photo_sizes:
            return False
        
        # Get the largest photo size
        largest_photo = max(photo_sizes, key=lambda p: p.file_size or 0)
        
        # Check file size (max 20MB for LLM API)
        if largest_photo.file_size and largest_photo.file_size > 20 * 1024 * 1024:
            return False
        
        return True
    
    def get_best_photo_size(self, photo_sizes: list[PhotoSize]) -> PhotoSize:
        """Get the best photo size for processing."""
        # Return the largest available photo
        return max(photo_sizes, key=lambda p: p.file_size or 0)

    async def process_multiple_photos(
        self, 
        photos: list[PhotoSize], 
        user_message: Optional[str] = None,
        username: Optional[str] = None
    ) -> Tuple[Optional[str], List[Dict[str, str]]]:
        """Process multiple photos and generate prediction.
        
        Args:
            photos: List of Telegram photo objects
            user_message: Optional user's question or context
            username: Optional user's name
            
        Returns:
            Tuple of (prediction_text, list_of_photo_data)
        """
        if not photos:
            raise PhotoProcessingError(
                "🔮 Не получено ни одного фото.",
                "No photos provided"
            )
        
        # Download and process all photos
        images_data = []
        processed_photos = [] # List of dicts with file_path and file_id
        
        for i, photo in enumerate(photos):
            try:
                file_info = await self.bot.get_file(photo.file_id)
                if not file_info.file_path:
                    logger.warning("Could not get file path for photo %s", photo.file_id)
                    continue
                
                file_content = await self.bot.download_file(file_info.file_path)
                if not file_content:
                    logger.warning("Could not download photo %s", photo.file_id)
                    continue
                
                if hasattr(file_content, 'read'):
                    image_data = file_content.read()
                else:
                    image_data = file_content
                
                if image_data:
                    # Resize if needed
                    image_data = self._resize_image(image_data)
                    images_data.append(image_data)
                    
                    # Save image to disk
                    saved_filename = self._save_image_to_disk(image_data)
                    if saved_filename:
                        processed_photos.append({
                            "file_path": saved_filename,
                            "file_id": photo.file_id
                        })
                    
            except Exception as e:
                logger.warning(
                    "Error processing photo %d/%d: file_id=%s, error_type=%s, error=%s",
                    i + 1, len(photos), photo.file_id, type(e).__name__, e,
                    exc_info=True,
                )
                continue
        
        if not images_data:
            raise PhotoProcessingError(
                "🔮 Не удалось загрузить фотографии. Попробуйте отправить другие.",
                "Failed to download any photos"
            )
        
        logger.info("Processing %d photos for prediction", len(images_data))
        
        # Analyze with LLM
        try:
            prediction = await self.llm_client.analyze_multiple_images(
                images_data, 
                user_message=user_message,
                username=username
            )
            return prediction, processed_photos
        except OpenAIError:
            raise
        except Exception as e:
            logger.error(
                "Unexpected error analyzing multiple photos: "
                "photo_count=%d, downloaded=%d, user_message=%r, username=%r, "
                "error_type=%s, error=%s",
                len(photos), len(images_data), user_message, username,
                type(e).__name__, e,
                exc_info=True,
            )
            raise PhotoProcessingError(
                "🔮 Произошла ошибка при анализе фотографий. Попробуйте еще раз.",
                f"Unexpected error ({type(e).__name__}): {e}"
            ) from e
