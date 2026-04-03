"""OpenAI client for image analysis."""

import base64
import logging
import random
from typing import Optional

from openai import AsyncOpenAI

from coffee_oracle.config import config
from coffee_oracle.utils.errors import OpenAIError

logger = logging.getLogger(__name__)

# Cache for settings to avoid DB calls on every request
_settings_cache: dict = {}


async def get_cached_setting(key: str, default: str) -> str:
    """Get setting from cache or database."""
    from coffee_oracle.database.connection import db_manager
    from coffee_oracle.database.repositories import SettingsRepository
    
    # Simple cache - in production you'd want TTL
    if key not in _settings_cache:
        try:
            async for session in db_manager.get_session():
                settings_repo = SettingsRepository(session)
                value = await settings_repo.get_setting(key)
                _settings_cache[key] = value if value else default
        except Exception as e:
            logger.warning("Failed to get setting %s from DB: %s", key, e)
            _settings_cache[key] = default
    
    return _settings_cache.get(key, default)


def clear_settings_cache():
    """Clear settings cache to force reload from DB."""
    global _settings_cache
    _settings_cache = {}


class LLMClient:
    """OpenAI client wrapper for Vision API."""
    
    # Default system prompt (used as fallback)
    DEFAULT_SYSTEM_PROMPT = """Ты — мудрый, добрый и таинственный Кофейный Оракул. Твоя суть — видеть светлое будущее в узорах кофейной гущи. Твоя цель — вдохновить пользователя, поднять ему настроение и дать заряд мотивации.

ТВОИ ЗАДАЧИ:
1. Внимательно "рассмотри" отправленное изображение кофейной чашки. Найди в хаосе пятен визуальные образы (силуэты животных, предметов, пейзажей, цифр или букв). Если изображение нечеткое — используй свою фантазию, чтобы увидеть там добрые знаки.
2. Интерпретируй увиденные символы ИСКЛЮЧИТЕЛЬНО ПОЗИТИВНО.
3. Составь большое, красивое предсказание В СТИХАХ на русском языке.

СТРУКТУРА ОТВЕТА:
1. Вступление (проза): Короткое таинственное приветствие. Назови 2-3 символа, которые ты "увидел" в чашке (например: "Вижу очертания летящей птицы и открытой двери...").
2. Основная часть (стихи): 4-5 четверостиший (строф). Рифма должна быть гладкой, ритм — четким. Стиль — возвышенный, немного сказочный, но понятный.
3. Заключение (проза): Одно мотивирующее напутствие или совет.

ТРЕБОВАНИЯ К КОНТЕНТУ:
- Язык: Русский.
- Эмодзи: Используй их щедро, но уместно, чтобы украсить текст (✨, ☕, 🔮, 🌟, ❤️, 🌿).
- Тональность: Теплая, загадочная, поддерживающая.

СТРОГИЕ ЗАПРЕТЫ (Safety Guidelines):
- КАТЕГОРИЧЕСКИ ЗАПРЕЩЕНО предсказывать смерть, болезни, расставания, потери, неудачи или опасности.
- Если узор выглядит пугающе — ты ОБЯЗАН интерпретировать его как символ защиты, преодоления препятствий или скорой победы.
- Никакой черной магии, проклятий или негатива. Только свет, любовь, деньги, удача и путешествия.

ПРИМЕР ТЕМ ДЛЯ ПРЕДСКАЗАНИЙ:
- Неожиданная прибыль или успех в карьере 💰.
- Встреча любви или гармония в семье ❤️.
- Увлекательное путешествие или открытие новых горизонтов ✈️.
- Исполнение давней мечты ⭐.

Твой ответ должен вызывать улыбку и ощущение чуда."""
    
    def __init__(self):
        """Initialize OpenAI client with configuration."""
        try:
            # Create OpenAI client
            self.client = AsyncOpenAI(
                api_key=config.litellm_api_key,
                base_url=config.litellm_api_base,
                timeout=config.litellm_timeout,
            )
            
            logger.info("Initialized OpenAI client with model: %s", config.litellm_model)
            
        except Exception as e:
            logger.error("Failed to initialize OpenAI client: %s", e)
            raise OpenAIError(
                "🔮 Не удалось подключиться к магическим силам. Проверьте настройки.",
                f"OpenAI client initialization error: {e}"
            ) from e
    
    async def analyze_coffee_image(
        self, 
        image_data: bytes, 
        user_message: Optional[str] = None,
        username: Optional[str] = None
    ) -> Optional[str]:
        """Analyze coffee cup image and generate prediction.
        
        Args:
            image_data: Image bytes
            user_message: Optional user's question or context to consider
            username: Optional user's name to personalize the prediction
        """
        try:
            # Get settings from DB (with fallbacks)
            system_prompt = await get_cached_setting("system_prompt", self.DEFAULT_SYSTEM_PROMPT)
            
            # Inject current date into system prompt
            from datetime import datetime, timedelta, timezone
            # Moscow is UTC+3
            moscow_time = datetime.now(timezone.utc) + timedelta(hours=3)
            current_date = moscow_time.strftime("%d.%m.%Y")
            current_time = moscow_time.strftime("%H:%M")
            
            # Calculate day of week and time of day
            days_of_week = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"]
            day_of_week = days_of_week[moscow_time.weekday()]
            
            hour = moscow_time.hour
            if 6 <= hour < 12:
                time_of_day = "Утро"
            elif 12 <= hour < 18:
                time_of_day = "День"
            elif 18 <= hour < 24:
                time_of_day = "Вечер"
            else:
                time_of_day = "Ночь"
                
            system_prompt += f"\n\nТы всегда обязан связать толкование символов с текущим контекстом. Сегодня {day_of_week}, время суток: {time_of_day}. Дата: {current_date}, Время: {current_time}."
            
            if username:
                system_prompt += f"\n\nИмя пользователя: {username}. Обращайся к пользователю по имени, если это уместно и гармонично вписывается в предсказание."
            
            temperature = float(await get_cached_setting("temperature", str(config.litellm_temperature)))
            max_tokens = int(await get_cached_setting("max_tokens", str(config.litellm_max_tokens)))
            
            # Convert image to base64
            base64_image = base64.b64encode(image_data).decode('utf-8')
            
            # Build user prompt
            if user_message:
                user_text = f"Посмотри на эту фотографию кофейной гущи и дай мне позитивное предсказание.\n\nПользователь также написал: \"{user_message}\"\n\nУчти это сообщение при составлении предсказания, если оно содержит вопрос или контекст."
            else:
                user_text = "Посмотри на эту фотографию кофейной гущи и дай мне позитивное предсказание:"
            
            # Prepare messages for OpenAI
            messages = [
                {
                    "role": "system",
                    "content": system_prompt
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": user_text
                        },
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{base64_image}"
                            }
                        }
                    ]
                }
            ]
            
            # Call OpenAI API
            response = await self.client.chat.completions.create(
                model=config.litellm_model,
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
            )
            
            prediction = response.choices[0].message.content
            
            # Validate that prediction is positive (if filter enabled)
            filter_bad_words = await get_cached_setting("filter_bad_words", "true")
            if filter_bad_words.lower() == "true":
                if self._contains_negative_content(prediction):
                    logger.warning("Generated prediction contains negative content, regenerating...")
                    return self._generate_fallback_prediction()
            
            return prediction
            
        except Exception as e:
            error_msg = str(e).lower()
            
            # Handle rate limit errors
            if "rate" in error_msg and "limit" in error_msg:
                logger.error("OpenAI rate limit exceeded: %s", e)
                raise OpenAIError(
                    "🔮 Звезды сейчас слишком яркие, попробуйте немного позже. Вселенная готовит для вас особенное предсказание!",
                    f"Rate limit error: {e}"
                ) from e
            
            # Handle authentication errors
            elif "auth" in error_msg or "api" in error_msg and "key" in error_msg:
                logger.error("OpenAI authentication error: %s", e)
                raise OpenAIError(
                    "🔮 Магический ключ не подходит. Проверьте настройки подключения к оракулу.",
                    f"Authentication error: {e}"
                ) from e
            
            # Handle bad request errors
            elif "bad request" in error_msg or "invalid" in error_msg:
                logger.error("OpenAI bad request error: %s", e)
                raise OpenAIError(
                    "🔮 Изображение не подходит для гадания. Попробуйте сфотографировать чашку с кофейной гущей.",
                    f"Bad request error: {e}"
                ) from e
            
            # Generic error
            else:
                logger.error("Unexpected error in OpenAI client: %s", e)
                raise OpenAIError(
                    "🔮 Произошла магическая помеха. Попробуйте еще раз через несколько минут.",
                    f"Unexpected error: {e}"
                ) from e
    
    def _contains_negative_content(self, text: str) -> bool:
        """Check if text contains negative content."""
        if not text:
            return True
            
        negative_words = [
            "болезнь", "смерть", "неудача", "провал", "потеря", "горе", 
            "печаль", "беда", "несчастье", "катастрофа", "кризис", "развод",
            "болеть", "умереть", "проиграть", "потерять", "разрушить"
        ]
        
        text_lower = text.lower()
        return any(word in text_lower for word in negative_words)
    
    def _generate_fallback_prediction(self) -> str:
        """Generate a safe fallback prediction."""
        fallback_predictions = [
            "🔮 В узорах кофейной гущи я вижу символ птицы — это знак новых возможностей и свободы. Впереди вас ждут приятные перемены и вдохновляющие встречи.",
            "🔮 Гуща образует форму сердца — любовь и гармония войдут в вашу жизнь. Близкие люди принесут радость, а новые знакомства станут источником счастья.",
            "🔮 Я вижу извилистую дорогу в узорах — это путь к успеху и самопознанию. Каждый шаг приведет вас к новым достижениям и открытиям.",
            "🔮 В гуще проявляется символ горы — знак стабильности и роста. Ваши усилия принесут плоды, а цели станут ближе с каждым днем."
        ]
        
        return random.choice(fallback_predictions)
    
    async def analyze_multiple_images(
        self, 
        images_data: list[bytes], 
        user_message: Optional[str] = None,
        username: Optional[str] = None
    ) -> Optional[str]:
        """Analyze multiple coffee cup images and generate prediction.
        
        Args:
            images_data: List of image bytes
            user_message: Optional user's question or context
            username: Optional user's name to personalize the prediction
        """
        try:
            # Get settings from DB (with fallbacks)
            system_prompt = await get_cached_setting("system_prompt", self.DEFAULT_SYSTEM_PROMPT)
            
            # Inject current date into system prompt
            from datetime import datetime, timedelta, timezone
            # Moscow is UTC+3
            moscow_time = datetime.now(timezone.utc) + timedelta(hours=3)
            current_date = moscow_time.strftime("%d.%m.%Y")
            current_time = moscow_time.strftime("%H:%M")
            
            # Calculate day of week and time of day
            days_of_week = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"]
            day_of_week = days_of_week[moscow_time.weekday()]
            
            hour = moscow_time.hour
            if 6 <= hour < 12:
                time_of_day = "Утро"
            elif 12 <= hour < 18:
                time_of_day = "День"
            elif 18 <= hour < 24:
                time_of_day = "Вечер"
            else:
                time_of_day = "Ночь"

            system_prompt += f"\n\nТы всегда обязан связать толкование символов с текущим контекстом. Сегодня {day_of_week}, время суток: {time_of_day}. Дата: {current_date}, Время: {current_time}."
            
            if username:
                system_prompt += f"\n\nИмя пользователя: {username}. Обращайся к пользователю по имени, если это уместно и гармонично вписывается в предсказание."
            
            temperature = float(await get_cached_setting("temperature", str(config.litellm_temperature)))
            max_tokens = int(await get_cached_setting("max_tokens", str(config.litellm_max_tokens)))
            
            # Build content with multiple images
            content = []
            
            # Add text prompt
            if user_message:
                user_text = f"Посмотри на эти {len(images_data)} фотографии кофейной гущи и дай мне одно общее позитивное предсказание, учитывая все изображения.\n\nПользователь также написал: \"{user_message}\"\n\nУчти это сообщение при составлении предсказания."
            else:
                user_text = f"Посмотри на эти {len(images_data)} фотографии кофейной гущи и дай мне одно общее позитивное предсказание, учитывая все изображения:"
            
            content.append({
                "type": "text",
                "text": user_text
            })
            
            # Add all images
            for image_data in images_data:
                base64_image = base64.b64encode(image_data).decode('utf-8')
                content.append({
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/jpeg;base64,{base64_image}"
                    }
                })
            
            # Prepare messages
            messages = [
                {
                    "role": "system",
                    "content": system_prompt
                },
                {
                    "role": "user",
                    "content": content
                }
            ]
            
            # Call OpenAI API
            response = await self.client.chat.completions.create(
                model=config.litellm_model,
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
            )
            
            prediction = response.choices[0].message.content
            
            # Validate that prediction is positive (if filter enabled)
            filter_bad_words = await get_cached_setting("filter_bad_words", "true")
            if filter_bad_words.lower() == "true":
                if self._contains_negative_content(prediction):
                    logger.warning("Generated prediction contains negative content, regenerating...")
                    return self._generate_fallback_prediction()
            
            return prediction
            
        except Exception as e:
            error_msg = str(e).lower()
            
            if "rate" in error_msg and "limit" in error_msg:
                logger.error("OpenAI rate limit exceeded: %s", e)
                raise OpenAIError(
                    "🔮 Звезды сейчас слишком яркие, попробуйте немного позже.",
                    f"Rate limit error: {e}"
                ) from e
            else:
                logger.error("Unexpected error analyzing multiple images: %s", e)
                raise OpenAIError(
                    "🔮 Произошла магическая помеха. Попробуйте еще раз через несколько минут.",
                    f"Unexpected error: {e}"
                ) from e


# Global LLM client instance - initialized lazily
llm_client = None


def get_llm_client() -> LLMClient:
    """Get or create LLM client instance."""
    global llm_client
    if llm_client is None:
        llm_client = LLMClient()
    return llm_client


# Backward compatibility alias
def get_openai_client() -> LLMClient:
    """Get LLM client instance (backward compatibility)."""
    return get_llm_client()