"""Database repositories."""

import os
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy import desc, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError

from coffee_oracle.database.models import BotSettings, Prediction, PredictionPhoto, User

MEDIA_DIR = "/app/media"
logger = logging.getLogger(__name__)


class UserRepository:
    """Repository for User operations."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create_user(
        self,
        telegram_id: int,
        username: Optional[str],
        full_name: str
    ) -> User:
        """Create a new user."""
        user = User(
            telegram_id=telegram_id,
            username=username,
            full_name=full_name
        )
        
        self.session.add(user)
        try:
            await self.session.commit()
            await self.session.refresh(user)
            return user
        except IntegrityError:
            await self.session.rollback()
            # User already exists, return existing user
            return await self.get_user_by_telegram_id(telegram_id)

    async def get_user_by_telegram_id(self, telegram_id: int) -> Optional[User]:
        """Get user by telegram ID."""
        result = await self.session.execute(
            select(User).where(User.telegram_id == telegram_id)
        )
        return result.scalar_one_or_none()

    async def get_user_by_id(self, user_id: int) -> Optional[User]:
        """Get user by ID."""
        result = await self.session.execute(
            select(User).where(User.id == user_id)
        )
        return result.scalar_one_or_none()

    async def get_all_users(self) -> List[User]:
        """Get all users."""
        result = await self.session.execute(select(User))
        return list(result.scalars().all())

    async def search_users_by_username(self, username: str) -> List[User]:
        """Search users by username."""
        result = await self.session.execute(
            select(User).where(User.username.ilike(f"%{username}%"))
        )
        return list(result.scalars().all())

    async def search_users_by_full_name(self, full_name: str) -> List[User]:
        """Search users by full name."""
        result = await self.session.execute(
            select(User).where(User.full_name.ilike(f"%{full_name}%"))
        )
        return list(result.scalars().all())

    async def get_users_count(self) -> int:
        """Get total users count."""
        result = await self.session.execute(select(func.count(User.id)))
        return result.scalar() or 0

    async def get_new_users_count(self, hours: int = 24) -> int:
        """Get count of new users in the last N hours."""
        cutoff_time = datetime.utcnow() - timedelta(hours=hours)
        result = await self.session.execute(
            select(func.count(User.id)).where(User.created_at >= cutoff_time)
        )
        return result.scalar() or 0

    async def get_users_time_series(
        self, hours_back: int, group_by: str = "day"
    ) -> List[Dict[str, Any]]:
        """Get users time series data for analytics."""
        cutoff_time = datetime.utcnow() - timedelta(hours=hours_back)

        # Determine SQL format based on grouping
        if group_by == "hour":
            sql_format = "%Y-%m-%d %H:00"
        elif group_by == "day":
            sql_format = "%Y-%m-%d"
        elif group_by == "week":
            sql_format = "%Y-W%W"  # Year-Week format
        else:  # month
            sql_format = "%Y-%m"

        # Use SQLAlchemy text for raw SQL
        query = text(f"""
        SELECT
            strftime('{sql_format}', created_at) as period,
            COUNT(*) as count
        FROM users
        WHERE created_at >= :cutoff_time
        GROUP BY strftime('{sql_format}', created_at)
        ORDER BY period
        """)

        result = await self.session.execute(query, {"cutoff_time": cutoff_time})
        rows = result.fetchall()

        return [{"period": row[0], "count": row[1]} for row in rows]


class PredictionRepository:
    """Repository for Prediction operations."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create_prediction(
        self,
        user_id: int,
        photo_file_id: str,
        prediction_text: str,
        photo_path: Optional[str] = None,
        user_request: Optional[str] = None,
        photos: Optional[List[Dict[str, str]]] = None
    ) -> Prediction:
        """Create a new prediction."""
        prediction = Prediction(
            user_id=user_id,
            photo_file_id=photo_file_id,
            prediction_text=prediction_text,
            photo_path=photo_path,
            user_request=user_request
        )

        if photos:
            for photo_data in photos:
                photo = PredictionPhoto(
                    file_path=photo_data["file_path"],
                    file_id=photo_data["file_id"]
                )
                prediction.photos.append(photo)

        self.session.add(prediction)
        await self.session.commit()
        await self.session.refresh(prediction)
        
        # Enforce photo limit
        try:
            await self.prune_old_photos()
        except Exception as e:
            logger.error("Failed to prune old photos: %s", e)
            
        return prediction

    async def prune_old_photos(self, limit: int = 20000) -> List[str]:
        """Prune old photos if count exceeds limit."""
        # Check current count
        count_result = await self.session.execute(select(func.count(PredictionPhoto.id)))
        count = count_result.scalar() or 0
        
        if count <= limit:
            return []
            
        excess = count - limit
        logger.info("Photo limit exceeded (%d > %d). Pruning %d oldest photos...", count, limit, excess)
        
        # Select excess oldest photos
        result = await self.session.execute(
            select(PredictionPhoto)
            .order_by(PredictionPhoto.created_at.asc())
            .limit(excess)
        )
        photos_to_delete = result.scalars().all()
        
        deleted_paths = []
        for photo in photos_to_delete:
            # Delete file from disk
            if photo.file_path:
                try:
                    file_path = os.path.join(MEDIA_DIR, photo.file_path)
                    if os.path.exists(file_path):
                        os.remove(file_path)
                        deleted_paths.append(file_path)
                except Exception as e:
                    logger.warning("Failed to delete file %s: %s", photo.file_path, e)
            
            # Delete from DB
            await self.session.delete(photo)
            
        await self.session.commit()
        logger.info("Pruned %d photos.", len(photos_to_delete))
        return deleted_paths

    async def get_user_predictions(
        self,
        user_id: int,
        limit: int = 5
    ) -> List[Prediction]:
        """Get user's predictions ordered by creation date (newest first)."""
        result = await self.session.execute(
            select(Prediction)
            .where(Prediction.user_id == user_id)
            .order_by(desc(Prediction.created_at))
            .limit(limit)
        )
        return list(result.scalars().all())

    async def get_user_predictions_count(self, user_id: int) -> int:
        """Get count of predictions for a specific user."""
        result = await self.session.execute(
            select(func.count(Prediction.id)).where(Prediction.user_id == user_id)
        )
        return result.scalar() or 0

    async def get_all_predictions(self) -> List[Prediction]:
        """Get all predictions."""
        result = await self.session.execute(
            select(Prediction).order_by(desc(Prediction.created_at))
        )
        return list(result.scalars().all())

    async def get_all_predictions_with_users(self) -> List[Prediction]:
        """Get all predictions with user data."""
        from sqlalchemy.orm import selectinload

        result = await self.session.execute(
            select(Prediction)
            .options(
                selectinload(Prediction.user),
                selectinload(Prediction.photos)
            )
            .order_by(desc(Prediction.created_at))
        )
        return list(result.scalars().all())

    async def get_predictions_count(self) -> int:
        """Get total predictions count."""
        result = await self.session.execute(select(func.count(Prediction.id)))
        return result.scalar() or 0

    async def get_photos_count(self) -> int:
        """Get total photos count."""
        result = await self.session.execute(select(func.count(PredictionPhoto.id)))
        return result.scalar() or 0

    async def get_predictions_count_since(self, hours: int = 24) -> int:
        """Get count of predictions in the last N hours."""
        cutoff_time = datetime.utcnow() - timedelta(hours=hours)
        result = await self.session.execute(
            select(func.count(Prediction.id)).where(
                Prediction.created_at >= cutoff_time
            )
        )
        return result.scalar() or 0

    async def get_predictions_time_series(
        self, hours_back: int, group_by: str = "day"
    ) -> List[Dict[str, Any]]:
        """Get predictions time series data for analytics."""
        cutoff_time = datetime.utcnow() - timedelta(hours=hours_back)

        # Determine SQL format based on grouping
        if group_by == "hour":
            sql_format = "%Y-%m-%d %H:00"
        elif group_by == "day":
            sql_format = "%Y-%m-%d"
        elif group_by == "week":
            sql_format = "%Y-W%W"  # Year-Week format
        else:  # month
            sql_format = "%Y-%m"

        # Use SQLAlchemy text for raw SQL
        query = text(f"""
        SELECT
            strftime('{sql_format}', created_at) as period,
            COUNT(*) as count
        FROM predictions
        WHERE created_at >= :cutoff_time
        GROUP BY strftime('{sql_format}', created_at)
        ORDER BY period
        """)

        result = await self.session.execute(query, {"cutoff_time": cutoff_time})
        rows = result.fetchall()

        return [{"period": row[0], "count": row[1]} for row in rows]



class SettingsRepository:
    """Repository for BotSettings operations."""

    # Default settings with descriptions
    DEFAULT_SETTINGS = {
        "system_prompt": {
            "value": """Ты — мудрый, добрый и таинственный Кофейный Оракул. Твоя суть — видеть светлое будущее в узорах кофейной гущи. Твоя цель — вдохновить пользователя, поднять ему настроение и дать заряд мотивации.

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

Твой ответ должен вызывать улыбку и ощущение чуда.""",
            "description": "Системный промпт для LLM модели"
        },
        "temperature": {
            "value": "0.8",
            "description": "Температура генерации (0.0-2.0). Выше = креативнее"
        },
        "max_tokens": {
            "value": "1500",
            "description": "Максимальное количество токенов в ответе"
        },
        "welcome_message": {
            "value": """🔮 Добро пожаловать в мир Кофейного Оракула, {name}!

Я помогу вам узнать, что говорят узоры кофейной гущи о вашем будущем. Просто сфотографируйте дно выпитой чашки кофе, и я открою вам тайны, которые скрывают эти магические узоры.

✨ Все предсказания несут только позитивную энергию и вдохновение!

Выберите действие в меню ниже:""",
            "description": "Приветственное сообщение ({name} заменяется на имя пользователя)"
        },
        "photo_instruction": {
            "value": """📸 Отправьте мне фотографию дна вашей кофейной чашки!

Убедитесь, что:
• Узоры кофейной гущи хорошо видны
• Освещение достаточное
• Фото сделано сверху

Я внимательно изучу узоры и расскажу, что они предвещают! ✨""",
            "description": "Инструкция для отправки фото"
        },
        "processing_message": {
            "value": "🔮 Смотрю в чашку... Звезды открывают свои тайны... ✨",
            "description": "Сообщение во время обработки фото"
        },
        "about_text": {
            "value": """🔮 Кофейный Оракул

Я — мистический бот, который умеет читать будущее по узорам кофейной гущи. Используя древние знания и современные технологии, я анализирую фотографии вашей кофейной чашки и открываю тайны, которые скрывают магические узоры.

✨ Особенности:
• Только позитивные предсказания
• Анализ реальных узоров гущи
• Мистический, но добрый подход
• История ваших предсказаний

🔮 Помните: будущее в ваших руках, а я лишь помогаю увидеть возможности!

Создано с ❤️ для любителей кофе и магии.""",
            "description": "Текст раздела 'О боте'"
        },
        "analyze_all_photos": {
            "value": "true",
            "description": "Анализировать все фото из группы (true) или только первое (false)"
        },
        "filter_bad_words": {
            "value": "true",
            "description": "Фильтр плохих слов (если false, пропускает любые предсказания)"
        },
    }

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_setting(self, key: str) -> Optional[str]:
        """Get setting value by key."""
        result = await self.session.execute(
            select(BotSettings).where(BotSettings.key == key)
        )
        setting = result.scalar_one_or_none()
        if setting:
            return setting.value
        # Return default if exists
        if key in self.DEFAULT_SETTINGS:
            return self.DEFAULT_SETTINGS[key]["value"]
        return None

    async def set_setting(self, key: str, value: str, description: Optional[str] = None) -> BotSettings:
        """Set or update a setting."""
        result = await self.session.execute(
            select(BotSettings).where(BotSettings.key == key)
        )
        setting = result.scalar_one_or_none()
        
        if setting:
            setting.value = value
            if description:
                setting.description = description
        else:
            desc = description or self.DEFAULT_SETTINGS.get(key, {}).get("description")
            setting = BotSettings(key=key, value=value, description=desc)
            self.session.add(setting)
        
        await self.session.commit()
        await self.session.refresh(setting)
        return setting

    async def get_all_settings(self) -> Dict[str, Dict[str, Any]]:
        """Get all settings with defaults."""
        result = await self.session.execute(select(BotSettings))
        db_settings = {s.key: {"value": s.value, "description": s.description, "updated_at": s.updated_at.isoformat() if s.updated_at else None} 
                       for s in result.scalars().all()}
        
        # Merge with defaults
        all_settings = {}
        for key, default in self.DEFAULT_SETTINGS.items():
            if key in db_settings:
                all_settings[key] = db_settings[key]
            else:
                all_settings[key] = {
                    "value": default["value"],
                    "description": default["description"],
                    "updated_at": None
                }
        
        return all_settings

    async def reset_to_defaults(self) -> None:
        """Reset all settings to defaults."""
        for key, default in self.DEFAULT_SETTINGS.items():
            await self.set_setting(key, default["value"], default["description"])
