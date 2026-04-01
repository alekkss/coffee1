"""Database repositories."""

import os
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy import desc, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError

from coffee_oracle.database.models import BotSettings, Payment, Prediction, PredictionPhoto, User

MEDIA_DIR = "/opt/oracle-bot/media"
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
        """Create a new user. If user was soft-deleted, restore them."""
        # Check if soft-deleted user exists
        result = await self.session.execute(
            select(User).where(
                User.telegram_id == telegram_id,
                User.deleted_at.isnot(None)
            )
        )
        existing_deleted = result.scalar_one_or_none()
        if existing_deleted:
            existing_deleted.deleted_at = None
            existing_deleted.username = username
            existing_deleted.full_name = full_name
            await self.session.commit()
            await self.session.refresh(existing_deleted)
            return existing_deleted

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
            return await self.get_user_by_telegram_id(telegram_id)

    async def get_user_by_telegram_id(self, telegram_id: int) -> Optional[User]:
        """Get active user by telegram ID."""
        result = await self.session.execute(
            select(User).where(
                User.telegram_id == telegram_id,
                User.deleted_at.is_(None)
            )
        )
        return result.scalar_one_or_none()

    async def get_user_by_id(self, user_id: int) -> Optional[User]:
        """Get active user by ID."""
        result = await self.session.execute(
            select(User).where(
                User.id == user_id,
                User.deleted_at.is_(None)
            )
        )
        return result.scalar_one_or_none()

    async def get_all_users(self, include_deleted: bool = False) -> List[User]:
        """Get all users. By default excludes soft-deleted."""
        stmt = select(User)
        if not include_deleted:
            stmt = stmt.where(User.deleted_at.is_(None))
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def search_users_by_username(self, username: str) -> List[User]:
        """Search active users by username."""
        result = await self.session.execute(
            select(User).where(
                User.username.ilike(f"%{username}%"),
                User.deleted_at.is_(None)
            )
        )
        return list(result.scalars().all())

    async def search_users_by_full_name(self, full_name: str) -> List[User]:
        """Search active users by full name."""
        result = await self.session.execute(
            select(User).where(
                User.full_name.ilike(f"%{full_name}%"),
                User.deleted_at.is_(None)
            )
        )
        return list(result.scalars().all())

    async def get_users_count(self) -> int:
        """Get total active users count."""
        result = await self.session.execute(
            select(func.count(User.id)).where(User.deleted_at.is_(None))
        )
        return result.scalar() or 0

    async def get_new_users_count(self, hours: int = 24) -> int:
        """Get count of new active users in the last N hours."""
        cutoff_time = datetime.utcnow() - timedelta(hours=hours)
        result = await self.session.execute(
            select(func.count(User.id)).where(
                User.created_at >= cutoff_time,
                User.deleted_at.is_(None)
            )
        )
        return result.scalar() or 0

    async def get_users_time_series(
        self, hours_back: int, group_by: str = "day"
    ) -> List[Dict[str, Any]]:
        """Get users time series data for analytics."""
        cutoff_time = datetime.utcnow() - timedelta(hours=hours_back)

        if group_by == "hour":
            sql_format = "%Y-%m-%d %H:00"
        elif group_by == "day":
            sql_format = "%Y-%m-%d"
        elif group_by == "week":
            sql_format = "%Y-W%W"
        else:
            sql_format = "%Y-%m"

        query = text(f"""
        SELECT
            strftime('{sql_format}', created_at) as period,
            COUNT(*) as count
        FROM users
        WHERE created_at >= :cutoff_time AND deleted_at IS NULL
        GROUP BY strftime('{sql_format}', created_at)
        ORDER BY period
        """)

        result = await self.session.execute(query, {"cutoff_time": cutoff_time})
        rows = result.fetchall()

        return [{"period": row[0], "count": row[1]} for row in rows]

    async def soft_delete_user(self, user_id: int) -> bool:
        """Soft delete a user by setting deleted_at."""
        result = await self.session.execute(
            select(User).where(User.id == user_id, User.deleted_at.is_(None))
        )
        user = result.scalar_one_or_none()
        if not user:
            return False

        user.deleted_at = datetime.utcnow()
        await self.session.commit()
        return True

    async def restore_user(self, user_id: int) -> bool:
        """Restore a soft-deleted user."""
        result = await self.session.execute(
            select(User).where(User.id == user_id, User.deleted_at.isnot(None))
        )
        user = result.scalar_one_or_none()
        if not user:
            return False

        user.deleted_at = None
        await self.session.commit()
        return True


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
        photos: Optional[List[Dict[str, str]]] = None,
        subscription_type: Optional[str] = None
    ) -> Prediction:
        """Create a new prediction."""
        prediction = Prediction(
            user_id=user_id,
            photo_file_id=photo_file_id,
            prediction_text=prediction_text,
            photo_path=photo_path,
            user_request=user_request,
            subscription_type=subscription_type
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

Я — добрый мистический дух, живущий в узорах кофейной гущи. Присылай фото дна чашки после утреннего кофе, и я поделюсь с тобой своей мудростью ✨

☕ Первые гадания — мои подарок тебе!
Потом, если захочешь продолжить наше магическое путешествие, можно оформить подписку.

🌟 Мои предсказания всегда несут свет и вдохновение!

Выбери действие в меню:""",
            "description": "Приветственное сообщение ({name} заменяется на имя пользователя)"
        },
        "photo_instruction": {
            "value": """📸 Пришли мне фото дна твоей кофейной чашки!

Чтобы я лучше увидел узоры:
• Сфотографируй сверху
• Убедись, что гуща хорошо видна
• Хорошее освещение поможет магии ✨

Я внимательно изучу узоры и расскажу, что они предвещают!""",
            "description": "Инструкция для отправки фото"
        },
        "processing_message": {
            "value": "🔮 Вглядываюсь в узоры гущи... Вижу образы... ✨",
            "description": "Сообщение во время обработки фото"
        },
        "about_text": {
            "value": """🔮 Кофейный Оракул

Я — добрый магический дух, живущий в узорах кофейной гущи. С древних времён люди находили в кофе ответы на сокровенные вопросы, и я продолжаю эту прекрасную традицию.

✨ Как я работаю:
Присылай фото дна кофейной чашки — я внимательно изучу узоры и поделюсь тем, что вижу. Мои слова всегда несут свет, тепло и вдохновение!

☕ Начни знакомство:
Первые гадания — мой дар тебе. Если мои предсказания тронут твоё сердце, ты сможешь оформить подписку для безлимитных сеансов магии.

🌟 Помни: будущее создаёшь ты сам, а я лишь помогаю увидеть возможности!

С любовью, твой Кофейный Оракул ☕✨""",
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
        "subscription_price": {
            "value": "300",
            "description": "Цена подписки в рублях за месяц"
        },
        "free_predictions_limit": {
            "value": "10",
            "description": "Количество бесплатных предсказаний для новых пользователей"
        },
        "terms_text": {
            "value": """Условия использования сервиса Coffee Oracle

1. Общие положения
Настоящие Условия использования регулируют порядок использования сервиса Coffee Oracle (далее — «Сервис»), предоставляемого через Telegram-бот.

2. Описание сервиса
Сервис предоставляет развлекательные предсказания на основе анализа изображений кофейной гущи с использованием технологий искусственного интеллекта. Все предсказания носят исключительно развлекательный характер и не являются профессиональными советами.

3. Подписка и оплата
3.1. Сервис предоставляет ограниченное количество бесплатных предсказаний.
3.2. Для получения безлимитного доступа необходимо оформить платную подписку.
3.3. Оплата производится через платёжную систему ЮKassa.
3.4. Подписка оформляется на 1 месяц с возможностью автоматического продления.
3.5. Пользователь вправе отменить автопродление в любое время через меню бота.

4. Возврат средств
Возврат средств осуществляется в соответствии с действующим законодательством РФ. По вопросам возврата обращайтесь в поддержку.

5. Ограничение ответственности
Сервис предоставляется «как есть». Администрация не несёт ответственности за решения, принятые пользователем на основании предсказаний.

6. Изменение условий
Администрация вправе изменять настоящие Условия. Продолжение использования Сервиса означает согласие с новыми условиями.""",
            "description": "Текст страницы «Условия использования» (/terms)"
        },
        "privacy_text": {
            "value": """Политика обработки персональных данных Coffee Oracle

1. Оператор данных
Настоящая Политика описывает порядок обработки персональных данных пользователей сервиса Coffee Oracle.

2. Какие данные мы собираем
— Telegram ID, имя пользователя и отображаемое имя из профиля Telegram;
— Изображения, отправленные пользователем для получения предсказания;
— Email-адрес, предоставленный при оплате (для отправки чека);
— История предсказаний и данные о платежах.

3. Цели обработки данных
— Предоставление функций сервиса (генерация предсказаний);
— Управление подпиской и обработка платежей;
— Отправка фискальных чеков в соответствии с 54-ФЗ;
— Улучшение качества сервиса.

4. Хранение данных
Данные хранятся на защищённых серверах. Изображения хранятся ограниченное время и автоматически удаляются при превышении лимита.

5. Передача данных третьим лицам
Данные платёжных карт не хранятся на наших серверах. Платёжные данные обрабатываются ЮKassa в соответствии с их политикой конфиденциальности.

6. Права пользователя
Вы вправе запросить удаление своих данных, обратившись в поддержку через бот.

7. Контакты
По вопросам обработки персональных данных обращайтесь через поддержку в боте.""",
            "description": "Текст страницы «Политика конфиденциальности» (/privacy)"
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

    async def set_setting(self, key: str, value: str, description: Optional[str] = None, updated_by: str = "admin") -> BotSettings:
        """Set or update a setting."""
        result = await self.session.execute(
            select(BotSettings).where(BotSettings.key == key)
        )
        setting = result.scalar_one_or_none()
        
        if setting:
            setting.value = value
            setting.updated_by = updated_by
            if description:
                setting.description = description
        else:
            desc = description or self.DEFAULT_SETTINGS.get(key, {}).get("description")
            setting = BotSettings(key=key, value=value, description=desc, updated_by=updated_by)
            self.session.add(setting)
        
        await self.session.commit()
        await self.session.refresh(setting)
        return setting

    async def get_all_settings(self) -> Dict[str, Dict[str, Any]]:
        """Get all settings with defaults."""
        result = await self.session.execute(select(BotSettings))
        db_settings = {
            s.key: {
                "value": s.value, 
                "description": s.description, 
                "updated_at": s.updated_at.isoformat() if s.updated_at else None,
                "updated_by": s.updated_by or "admin"
            } 
            for s in result.scalars().all()
        }
        
        # Merge with defaults
        all_settings = {}
        for key, default in self.DEFAULT_SETTINGS.items():
            if key in db_settings:
                all_settings[key] = db_settings[key]
            else:
                all_settings[key] = {
                    "value": default["value"],
                    "description": default["description"],
                    "updated_at": None,
                    "updated_by": None
                }
        
        return all_settings

    async def reset_to_defaults(self) -> None:
        """Reset all settings to defaults."""
        for key, default in self.DEFAULT_SETTINGS.items():
            await self.set_setting(key, default["value"], default["description"])


class SubscriptionRepository:
    """Repository for subscription and payment operations."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_subscription_status(self, user_id: int) -> Dict[str, Any]:
        """Get detailed subscription status for a user."""
        result = await self.session.execute(
            select(User).where(User.id == user_id)
        )
        user = result.scalar_one_or_none()
        
        if not user:
            return {"type": "unknown", "active": False}
        
        # VIP users always have access
        if user.subscription_type == "vip":
            return {
                "type": "vip",
                "active": True,
                "vip_reason": user.vip_reason,
                "unlimited": True
            }
        
        # Check premium subscription
        if user.subscription_type == "premium":
            if user.subscription_until and user.subscription_until > datetime.utcnow():
                return {
                    "type": "premium",
                    "active": True,
                    "until": user.subscription_until.isoformat(),
                    "unlimited": True
                }
            else:
                # Premium expired, revert to free
                user.subscription_type = "free"
                user.subscription_until = None
                await self.session.commit()
        
        # Free tier - count predictions
        pred_count = await self.session.execute(
            select(func.count(Prediction.id)).where(Prediction.user_id == user_id)
        )
        predictions_used = pred_count.scalar() or 0
        
        # Get limit from settings
        settings_repo = SettingsRepository(self.session)
        limit_str = await settings_repo.get_setting("free_predictions_limit")
        free_limit = int(limit_str) if limit_str else 10
        
        return {
            "type": "free",
            "active": predictions_used < free_limit,
            "predictions_used": predictions_used,
            "predictions_limit": free_limit,
            "predictions_remaining": max(0, free_limit - predictions_used)
        }
    async def get_expiring_premium_users(self, days: int = 1) -> List[User]:
        """Get premium users whose subscription expires within the given number of days."""
        now = datetime.utcnow()
        cutoff = now + timedelta(days=days)
        result = await self.session.execute(
            select(User).where(
                User.subscription_type == "premium",
                User.subscription_until.isnot(None),
                User.subscription_until > now,
                User.subscription_until <= cutoff,
                User.deleted_at.is_(None),
            )
        )
        return list(result.scalars().all())

    async def get_subscription_stats(self) -> Dict[str, int]:
        """Get subscription statistics (only active users)."""
        free_count = await self.session.execute(
            select(func.count(User.id)).where(
                User.subscription_type == "free",
                User.deleted_at.is_(None)
            )
        )
        premium_count = await self.session.execute(
            select(func.count(User.id)).where(
                User.subscription_type == "premium",
                User.subscription_until > datetime.utcnow(),
                User.deleted_at.is_(None)
            )
        )
        vip_count = await self.session.execute(
            select(func.count(User.id)).where(
                User.subscription_type == "vip",
                User.deleted_at.is_(None)
            )
        )

        total_payments = await self.session.execute(
            select(func.count(Payment.id)).where(Payment.status == "completed")
        )
        total_revenue = await self.session.execute(
            select(func.sum(Payment.amount)).where(Payment.status == "completed")
        )

        return {
            "free_users": free_count.scalar() or 0,
            "premium_users": premium_count.scalar() or 0,
            "vip_users": vip_count.scalar() or 0,
            "total_payments": total_payments.scalar() or 0,
            "total_revenue": (total_revenue.scalar() or 0) / 100  # Convert kopecks to rubles
        }

    async def can_make_prediction(self, user_id: int) -> tuple[bool, str]:
        """Check if user can make a prediction. Returns (can_proceed, message)."""
        status = await self.get_subscription_status(user_id)
        
        if status["type"] == "vip":
            return True, "VIP-доступ"
        
        if status["type"] == "premium" and status["active"]:
            return True, "Премиум подписка"
        
        if status["type"] == "free":
            if status["active"]:
                remaining = status["predictions_remaining"]
                return True, f"Осталось бесплатных: {remaining}"
            else:
                return False, (
                    f"🔮 Ваши бесплатные предсказания закончились!\n\n"
                    f"Вы использовали {status['predictions_limit']} из {status['predictions_limit']} бесплатных предсказаний.\n\n"
                    f"💳 Оформите подписку, чтобы получать безлимитные предсказания!"
                )
        
        return False, "Неизвестный статус подписки"

    async def activate_premium(self, user_id: int, months: int = 1) -> bool:
        """Activate premium subscription for user."""
        result = await self.session.execute(
            select(User).where(User.id == user_id)
        )
        user = result.scalar_one_or_none()
        
        if not user:
            return False
        
        # Calculate new subscription end date
        from dateutil.relativedelta import relativedelta
        current_until = user.subscription_until
        if current_until and current_until > datetime.utcnow():
            # Extend existing subscription
            new_until = current_until + relativedelta(months=months)
        else:
            # New subscription
            new_until = datetime.utcnow() + relativedelta(months=months)
        
        user.subscription_type = "premium"
        user.subscription_until = new_until
        await self.session.commit()
        
        logger.info("Activated premium for user %d until %s", user_id, new_until)
        return True

    async def set_vip_status(self, user_id: int, reason: str) -> bool:
        """Set VIP status for a user (testers, partners, etc.)."""
        # Search by telegram_id first, then by internal id
        result = await self.session.execute(
            select(User).where(User.telegram_id == user_id)
        )
        user = result.scalar_one_or_none()
        
        if not user:
            # Fallback to internal id
            result = await self.session.execute(
                select(User).where(User.id == user_id)
            )
            user = result.scalar_one_or_none()
        
        if not user:
            return False
        
        user.subscription_type = "vip"
        user.vip_reason = reason
        user.subscription_until = None  # VIP has no expiration
        await self.session.commit()
        
        logger.info("Set VIP status for user %d (telegram_id=%d): %s", user.id, user.telegram_id, reason)
        return True

    async def remove_vip_status(self, user_id: int) -> bool:
        """Remove VIP status, reverting user to free tier."""
        result = await self.session.execute(
            select(User).where(User.id == user_id)
        )
        user = result.scalar_one_or_none()
        
        if not user:
            return False
        
        user.subscription_type = "free"
        user.vip_reason = None
        await self.session.commit()
        
        logger.info("Removed VIP status for user %d", user_id)
        return True

    async def remove_premium_subscription(self, user_id: int) -> bool:
        """Remove premium subscription, reverting user to free tier."""
        result = await self.session.execute(
            select(User).where(User.id == user_id)
        )
        user = result.scalar_one_or_none()

        if not user:
            return False

        user.subscription_type = "free"
        user.subscription_until = None
        await self.session.commit()

        logger.info("Removed premium subscription for user %d", user_id)
        return True

    async def enable_recurring_payment(self, user_id: int, recurring_charge_id: str) -> bool:
        """Enable recurring payment for a user."""
        result = await self.session.execute(
            select(User).where(User.id == user_id)
        )
        user = result.scalar_one_or_none()

        if not user:
            return False

        user.recurring_payment_enabled = 1
        user.telegram_recurring_payment_charge_id = recurring_charge_id
        await self.session.commit()

        logger.info("Enabled recurring payment for user %d with charge_id %s", user_id, recurring_charge_id)
        return True

    async def disable_recurring_payment(self, user_id: int) -> bool:
        """Disable recurring payment for a user."""
        result = await self.session.execute(
            select(User).where(User.id == user_id)
        )
        user = result.scalar_one_or_none()

        if not user:
            return False

        user.recurring_payment_enabled = 0
        user.telegram_recurring_payment_charge_id = None
        await self.session.commit()

        logger.info("Disabled recurring payment for user %d", user_id)
        return True

    async def is_recurring_enabled(self, user_id: int) -> tuple[bool, Optional[str]]:
        """Check if recurring payment is enabled for a user. Returns (enabled, charge_id)."""
        result = await self.session.execute(
            select(User).where(User.id == user_id)
        )
        user = result.scalar_one_or_none()

        if not user:
            return False, None

        return bool(user.recurring_payment_enabled), user.telegram_recurring_payment_charge_id



    async def create_payment(
        self, 
        user_id: int, 
        amount: int, 
        label: str, 
        payment_id: str = None,
        is_recurring: bool = False,
        recurring_charge_id: str = None
    ) -> Payment:
        """Create a pending payment record."""
        payment = Payment(
            user_id=user_id,
            amount=amount,
            label=label,
            payment_id=payment_id,
            status="pending",
            is_recurring=1 if is_recurring else 0,
            telegram_recurring_payment_charge_id=recurring_charge_id
        )
        self.session.add(payment)
        await self.session.commit()
        await self.session.refresh(payment)
        return payment

    async def get_payment_by_label(self, label: str) -> Optional[Payment]:
        """Get payment by its unique label."""
        result = await self.session.execute(
            select(Payment).where(Payment.label == label)
        )
        return result.scalar_one_or_none()

    async def get_payment_by_payment_id(self, payment_id: str) -> Optional[Payment]:
        """Get payment by YooKassa payment ID."""
        result = await self.session.execute(
            select(Payment).where(Payment.payment_id == payment_id)
        )
        return result.scalar_one_or_none()

    async def complete_payment(self, label: str) -> bool:
        """Mark payment as completed and activate subscription."""
        payment = await self.get_payment_by_label(label)
        
        if not payment or payment.status == "completed":
            return False
        
        payment.status = "completed"
        payment.completed_at = datetime.utcnow()
        
        # Activate premium for the user
        await self.activate_premium(payment.user_id, months=1)
        
        await self.session.commit()
        logger.info("Completed payment %s for user %d", label, payment.user_id)
        return True

    async def update_payment_status(self, payment_id: str, status: str) -> bool:
        """Update payment status by YooKassa payment_id.

        Args:
            payment_id: YooKassa payment ID.
            status: New status value (pending, succeeded, canceled).

        Returns:
            True if payment was found and updated, False otherwise.
        """
        result = await self.session.execute(
            select(Payment).where(Payment.payment_id == payment_id)
        )
        payment = result.scalar_one_or_none()

        if not payment:
            return False

        payment.status = status
        if status == "succeeded":
            payment.completed_at = datetime.utcnow()
        await self.session.commit()

        logger.info("Updated payment %s status to %s", payment_id, status)
        return True


    async def get_user_payments(self, user_id: int) -> List[Payment]:
        """Get all payments for a user."""
        result = await self.session.execute(
            select(Payment)
            .where(Payment.user_id == user_id)
            .order_by(desc(Payment.created_at))
        )
        return list(result.scalars().all())

    async def get_all_vip_users(self) -> List[User]:
        """Get all active VIP users."""
        result = await self.session.execute(
            select(User).where(
                User.subscription_type == "vip",
                User.deleted_at.is_(None)
            )
        )
        return list(result.scalars().all())

    async def get_all_premium_users(self) -> List[User]:
        """Get all active users with active premium subscription."""
        result = await self.session.execute(
            select(User).where(
                User.subscription_type == "premium",
                User.subscription_until > datetime.utcnow(),
                User.deleted_at.is_(None)
            )
        )
        return list(result.scalars().all())

