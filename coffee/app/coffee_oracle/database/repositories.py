"""Репозитории для работы с базой данных.

Содержит репозитории для всех сущностей: пользователи,
предсказания, настройки, подписки, платежи, партнёры и ремайндеры.
"""

import os
import logging
import secrets
import string
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy import desc, func, select, text, delete, or_, exists
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError

from coffee_oracle.database.models import (
    AdminUser,
    BotSettings,
    Partner,
    Payment,
    Prediction,
    PredictionPhoto,
    ReferralClick,
    User,
    UserReminder,
)

MEDIA_DIR = "/opt/oracle-bot/media"
logger = logging.getLogger(__name__)


class UserRepository:
    """Репозиторий для операций с пользователями.

    Все методы поиска по telegram_id требуют указания source,
    чтобы корректно различать пользователей из разных платформ
    (Telegram и MAX).
    """

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create_user(
        self,
        telegram_id: int,
        username: Optional[str],
        full_name: str,
        source: str = "tg",
        referred_by_partner_id: Optional[int] = None,
    ) -> User:
        """Создание нового пользователя. Если пользователь был soft-deleted, восстанавливает его.

        Args:
            telegram_id: ID пользователя на платформе.
            username: Имя пользователя (@username).
            full_name: Отображаемое имя.
            source: Платформа-источник ('tg' для Telegram, 'max' для MAX).
            referred_by_partner_id: ID партнёра, по чьей ссылке пришёл пользователь.

        Returns:
            Созданный или восстановленный объект User.
        """
        # Проверяем, есть ли soft-deleted пользователь с этой платформы
        result = await self.session.execute(
            select(User).where(
                User.telegram_id == telegram_id,
                User.source == source,
                User.deleted_at.isnot(None),
            )
        )
        existing_deleted = result.scalar_one_or_none()
        if existing_deleted:
            existing_deleted.deleted_at = None
            existing_deleted.username = username
            existing_deleted.full_name = full_name
            if referred_by_partner_id and not existing_deleted.referred_by_partner_id:
                existing_deleted.referred_by_partner_id = referred_by_partner_id
            await self.session.commit()
            await self.session.refresh(existing_deleted)
            return existing_deleted

        user = User(
            telegram_id=telegram_id,
            username=username,
            full_name=full_name,
            source=source,
            referred_by_partner_id=referred_by_partner_id,
        )

        self.session.add(user)
        try:
            await self.session.commit()
            await self.session.refresh(user)
            return user
        except IntegrityError:
            await self.session.rollback()
            return await self.get_user_by_telegram_id(telegram_id, source=source)

    async def get_user_by_telegram_id(
        self,
        telegram_id: int,
        source: str = "tg",
    ) -> Optional[User]:
        """Получение активного пользователя по ID платформы и источнику.

        Args:
            telegram_id: ID пользователя на платформе.
            source: Платформа-источник ('tg' или 'max').

        Returns:
            Объект User или None, если не найден.
        """
        result = await self.session.execute(
            select(User).where(
                User.telegram_id == telegram_id,
                User.source == source,
                User.deleted_at.is_(None),
            )
        )
        return result.scalar_one_or_none()

    async def get_user_by_id(self, user_id: int) -> Optional[User]:
        """Получение активного пользователя по внутреннему ID."""
        result = await self.session.execute(
            select(User).where(
                User.id == user_id,
                User.deleted_at.is_(None),
            )
        )
        return result.scalar_one_or_none()

    async def get_all_users(self, include_deleted: bool = False) -> List[User]:
        """Получение всех пользователей. По умолчанию исключает удалённых."""
        stmt = select(User)
        if not include_deleted:
            stmt = stmt.where(User.deleted_at.is_(None))
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def search_users_by_username(self, username: str) -> List[User]:
        """Поиск активных пользователей по username."""
        result = await self.session.execute(
            select(User).where(
                User.username.ilike(f"%{username}%"),
                User.deleted_at.is_(None),
            )
        )
        return list(result.scalars().all())

    async def search_users_by_full_name(self, full_name: str) -> List[User]:
        """Поиск активных пользователей по полному имени."""
        result = await self.session.execute(
            select(User).where(
                User.full_name.ilike(f"%{full_name}%"),
                User.deleted_at.is_(None),
            )
        )
        return list(result.scalars().all())

    async def get_users_count(self) -> int:
        """Получение общего количества активных пользователей."""
        result = await self.session.execute(
            select(func.count(User.id)).where(User.deleted_at.is_(None))
        )
        return result.scalar() or 0

    async def get_new_users_count(self, hours: int = 24) -> int:
        """Получение количества новых активных пользователей за последние N часов."""
        cutoff_time = datetime.utcnow() - timedelta(hours=hours)
        result = await self.session.execute(
            select(func.count(User.id)).where(
                User.created_at >= cutoff_time,
                User.deleted_at.is_(None),
            )
        )
        return result.scalar() or 0

    async def get_users_time_series(
        self, hours_back: int, group_by: str = "day"
    ) -> List[Dict[str, Any]]:
        """Получение временных рядов пользователей для аналитики."""
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
        """Мягкое удаление пользователя по внутреннему ID."""
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
        """Восстановление мягко удалённого пользователя."""
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
    """Репозиторий для операций с предсказаниями."""

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
        subscription_type: Optional[str] = None,
    ) -> Prediction:
        # Если subscription_type не передан — берём актуальный из БД
        if subscription_type is None:
            user_result = await self.session.execute(
                select(User).where(User.id == user_id)
            )
            user = user_result.scalar_one_or_none()
            if user:
                subscription_type = user.subscription_type or "free"
            else:
                subscription_type = "free"

        prediction = Prediction(
            user_id=user_id,
            photo_file_id=photo_file_id,
            prediction_text=prediction_text,
            photo_path=photo_path,
            user_request=user_request,
            subscription_type=subscription_type,
        )

        if photos:
            for photo_data in photos:
                photo = PredictionPhoto(
                    file_path=photo_data["file_path"],
                    file_id=photo_data["file_id"],
                )
                prediction.photos.append(photo)

        self.session.add(prediction)
        await self.session.commit()
        await self.session.refresh(prediction)

        try:
            await self.prune_old_photos()
        except Exception as e:
            logger.error("Не удалось очистить старые фото: %s", e)

        return prediction

    async def prune_old_photos(self, limit: int = 20000) -> List[str]:
        """Удаление старых фотографий при превышении лимита."""
        # Проверяем текущее количество
        count_result = await self.session.execute(select(func.count(PredictionPhoto.id)))
        count = count_result.scalar() or 0

        if count <= limit:
            return []

        excess = count - limit
        logger.info(
            "Лимит фото превышен (%d > %d). Удаляем %d старейших фото...",
            count, limit, excess,
        )

        # Выбираем лишние старейшие фото
        result = await self.session.execute(
            select(PredictionPhoto)
            .order_by(PredictionPhoto.created_at.asc())
            .limit(excess)
        )
        photos_to_delete = result.scalars().all()

        deleted_paths = []
        for photo in photos_to_delete:
            # Удаление файла с диска
            if photo.file_path:
                try:
                    file_path = os.path.join(MEDIA_DIR, photo.file_path)
                    if os.path.exists(file_path):
                        os.remove(file_path)
                        deleted_paths.append(file_path)
                except Exception as e:
                    logger.warning("Не удалось удалить файл %s: %s", photo.file_path, e)

            # Удаление из БД
            await self.session.delete(photo)

        await self.session.commit()
        logger.info("Удалено %d фото.", len(photos_to_delete))
        return deleted_paths

    async def get_user_predictions(
        self,
        user_id: int,
        limit: int = 5,
    ) -> List[Prediction]:
        """Получение предсказаний пользователя (новейшие первыми)."""
        result = await self.session.execute(
            select(Prediction)
            .where(Prediction.user_id == user_id)
            .order_by(desc(Prediction.created_at))
            .limit(limit)
        )
        return list(result.scalars().all())

    async def get_user_predictions_count(self, user_id: int) -> int:
        """Получение количества предсказаний конкретного пользователя."""
        result = await self.session.execute(
            select(func.count(Prediction.id)).where(Prediction.user_id == user_id)
        )
        return result.scalar() or 0

    async def get_all_predictions(self) -> List[Prediction]:
        """Получение всех предсказаний."""
        result = await self.session.execute(
            select(Prediction).order_by(desc(Prediction.created_at))
        )
        return list(result.scalars().all())

    async def get_all_predictions_with_users(self) -> List[Prediction]:
        """Получение всех предсказаний с данными пользователей."""
        from sqlalchemy.orm import selectinload

        result = await self.session.execute(
            select(Prediction)
            .options(
                selectinload(Prediction.user),
                selectinload(Prediction.photos),
            )
            .order_by(desc(Prediction.created_at))
        )
        return list(result.scalars().all())

    async def get_predictions_count(self) -> int:
        """Получение общего количества предсказаний."""
        result = await self.session.execute(select(func.count(Prediction.id)))
        return result.scalar() or 0

    async def get_photos_count(self) -> int:
        """Получение общего количества фотографий."""
        result = await self.session.execute(select(func.count(PredictionPhoto.id)))
        return result.scalar() or 0

    async def get_predictions_count_since(self, hours: int = 24) -> int:
        """Получение количества предсказаний за последние N часов."""
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
        """Получение временных рядов предсказаний для аналитики."""
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
        FROM predictions
        WHERE created_at >= :cutoff_time
        GROUP BY strftime('{sql_format}', created_at)
        ORDER BY period
        """)

        result = await self.session.execute(query, {"cutoff_time": cutoff_time})
        rows = result.fetchall()

        return [{"period": row[0], "count": row[1]} for row in rows]


class SettingsRepository:
    """Репозиторий для операций с настройками бота."""

    # Настройки по умолчанию с описаниями
    DEFAULT_SETTINGS = {
        "system_prompt": {
            "value": """  ,     .          .     ,       .

 :
1.  ""    .       ( , , ,   ).       ,     .
2.     .
3.  ,       .

 :
1.  ():   .  2-3 ,   ""   (: "      ...").
2.   (): 4-5  ().    ,   .   ,  ,  .
3.  ():     .

  :
- : .
- :   ,  ,    (, , , , , ).
- : , , .

  (Safety Guidelines):
-    , , , ,   .
-            ,     .
-   ,   .  , , ,   .

   :
-       .
-       .
-       .
-    .

       .""",
            "description": "   LLM "
        },
        "temperature": {
            "value": "0.8",
            "description": "  (0.0-2.0).  = "
        },
        "max_tokens": {
            "value": "1500",
            "description": "    "
        },
        "welcome_message": {
            "value": """      , {name}!

    ,     .       ,        

      !
,      ,   .

       !

   :""",
            "description": "  ({name}    )"
        },
        "photo_instruction": {
            "value": """       !

    :
  
 ,    
     

     ,   !""",
            "description": "   "
        },
        "processing_message": {
            "value": "    ...  ... ",
            "description": "    "
        },
        "about_text": {
            "value": """  

    ,     .           ,      .

   :
            ,  .     ,   !

  :
     .      ,        .

 :    ,      !

 ,    """,
            "description": "  ' '"
        },
        "analyze_all_photos": {
            "value": "true",
            "description": "     (true)    (false)"
        },
        "filter_bad_words": {
            "value": "true",
            "description": "   ( false,   )"
        },
        "subscription_price": {
            "value": "300",
            "description": "     "
        },
        "free_predictions_limit": {
            "value": "10",
            "description": "     "
        },
        "terms_text": {
            "value": """   Coffee Oracle

1.  
       Coffee Oracle (  ),   Telegram-.

2.  
              .           .

3.   
3.1.      .
3.2.        .
3.3.      Kassa.
3.4.    1     .
3.5.          .

4.  
        .      .

5.  
   .      ,     .

6.  
    .        .""",
            "description": "    (/terms)"
        },
        "privacy_text": {
            "value": """    Coffee Oracle

1.  
         Coffee Oracle.

2.    
 Telegram ID,        Telegram;
 ,     ;
 Email-,    (  );
      .

3.   
    ( );
     ;
       54-;
   .

4.  
    .          .

5.    
       .    Kassa      .

6.  
     ,     .

7. 
         .""",
            "description": "    (/privacy)"
        },
    }

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_setting(self, key: str) -> Optional[str]:
        """Получение значения настройки по ключу."""
        result = await self.session.execute(
            select(BotSettings).where(BotSettings.key == key)
        )
        setting = result.scalar_one_or_none()
        if setting:
            return setting.value
        # Возвращаем значение по умолчанию, если существует
        if key in self.DEFAULT_SETTINGS:
            return self.DEFAULT_SETTINGS[key]["value"]
        return None

    async def set_setting(
        self,
        key: str,
        value: str,
        description: Optional[str] = None,
        updated_by: str = "admin",
    ) -> BotSettings:
        """Установка или обновление настройки."""
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
            setting = BotSettings(
                key=key, value=value, description=desc, updated_by=updated_by
            )
            self.session.add(setting)

        await self.session.commit()
        await self.session.refresh(setting)
        return setting

    async def get_all_settings(self) -> Dict[str, Dict[str, Any]]:
        """Получение всех настроек с значениями по умолчанию."""
        result = await self.session.execute(select(BotSettings))
        db_settings = {
            s.key: {
                "value": s.value,
                "description": s.description,
                "updated_at": s.updated_at.isoformat() if s.updated_at else None,
                "updated_by": s.updated_by or "admin",
            }
            for s in result.scalars().all()
        }

        # Объединяем с настройками по умолчанию
        all_settings = {}
        for key, default in self.DEFAULT_SETTINGS.items():
            if key in db_settings:
                all_settings[key] = db_settings[key]
            else:
                all_settings[key] = {
                    "value": default["value"],
                    "description": default["description"],
                    "updated_at": None,
                    "updated_by": None,
                }

        return all_settings

    async def reset_to_defaults(self) -> None:
        """Сброс всех настроек к значениям по умолчанию."""
        for key, default in self.DEFAULT_SETTINGS.items():
            await self.set_setting(key, default["value"], default["description"])


class SubscriptionRepository:
    """Репозиторий для операций с подписками и платежами."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_subscription_status(self, user_id: int) -> Dict[str, Any]:
        """Получение детального статуса подписки пользователя."""
        result = await self.session.execute(
            select(User).where(User.id == user_id)
        )
        user = result.scalar_one_or_none()

        if not user:
            return {"type": "unknown", "active": False}

        # VIP-пользователи всегда имеют доступ
        if user.subscription_type == "vip":
            return {
                "type": "vip",
                "active": True,
                "vip_reason": user.vip_reason,
                "unlimited": True,
            }

        # Проверяем premium-подписку
        if user.subscription_type == "premium":
            if user.subscription_until and user.subscription_until > datetime.utcnow():
                return {
                    "type": "premium",
                    "active": True,
                    "until": user.subscription_until.isoformat(),
                    "unlimited": True,
                }
            else:
                # Premium истёк, возвращаем на бесплатный
                user.subscription_type = "free"
                user.subscription_until = None
                await self.session.commit()

        # Бесплатный тариф — считаем предсказания
        pred_count = await self.session.execute(
            select(func.count(Prediction.id)).where(Prediction.user_id == user_id)
        )
        predictions_used = pred_count.scalar() or 0

        # Получаем лимит из настроек
        settings_repo = SettingsRepository(self.session)
        limit_str = await settings_repo.get_setting("free_predictions_limit")
        free_limit = int(limit_str) if limit_str else 10

        return {
            "type": "free",
            "active": predictions_used < free_limit,
            "predictions_used": predictions_used,
            "predictions_limit": free_limit,
            "predictions_remaining": max(0, free_limit - predictions_used),
        }

    async def get_expiring_premium_users(self, days: int = 1) -> List[User]:
        """Получение premium-пользователей с истекающей подпиской."""
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
        """Получение статистики подписок (только активные пользователи)."""
        free_count = await self.session.execute(
            select(func.count(User.id)).where(
                User.subscription_type == "free",
                User.deleted_at.is_(None),
            )
        )
        premium_count = await self.session.execute(
            select(func.count(User.id)).where(
                User.subscription_type == "premium",
                User.subscription_until > datetime.utcnow(),
                User.deleted_at.is_(None),
            )
        )
        vip_count = await self.session.execute(
            select(func.count(User.id)).where(
                User.subscription_type == "vip",
                User.deleted_at.is_(None),
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
            "total_revenue": (total_revenue.scalar() or 0) / 100,  # Копейки в рубли
        }

    async def can_make_prediction(self, user_id: int) -> tuple[bool, str]:
        """Проверка, может ли пользователь сделать предсказание."""
        status = await self.get_subscription_status(user_id)

        if status["type"] == "vip":
            return True, "VIP-доступ"

        if status["type"] == "premium" and status["active"]:
            return True, "Premium подписка"

        if status["type"] == "free":
            if status["active"]:
                remaining = status["predictions_remaining"]
                return True, f"Осталось предсказаний: {remaining}"
            else:
                return False, (
                    f"Вы использовали все бесплатные предсказания!\n\n"
                    f"Использовано {status['predictions_limit']} из {status['predictions_limit']} предсказаний.\n\n"
                    f"Оформите подписку, чтобы продолжить!"
                )

        return False, "Неизвестный статус подписки"

    async def activate_premium(self, user_id: int, months: int = 1) -> bool:
        """Активация premium-подписки для пользователя."""
        result = await self.session.execute(
            select(User).where(User.id == user_id)
        )
        user = result.scalar_one_or_none()

        if not user:
            return False

        # Вычисляем новую дату окончания подписки
        from dateutil.relativedelta import relativedelta

        current_until = user.subscription_until
        if current_until and current_until > datetime.utcnow():
            # Продлеваем существующую подписку
            new_until = current_until + relativedelta(months=months)
        else:
            # Новая подписка
            new_until = datetime.utcnow() + relativedelta(months=months)

        user.subscription_type = "premium"
        user.subscription_until = new_until
        await self.session.commit()

        logger.info("Активирована premium-подписка для пользователя %d до %s", user_id, new_until)
        return True

    async def set_vip_status(
        self, user_id: int, reason: str, source: Optional[str] = None
    ) -> bool:
        """Установка VIP-статуса для пользователя (тестеры, партнёры и т.д.).

        Args:
            user_id: Telegram/MAX ID пользователя на платформе.
            reason: Причина назначения VIP.
            source: Платформа ('tg' или 'max'). Если указана — ищет по
                    telegram_id + source. Если не указана — ищет по telegram_id
                    среди всех платформ, затем fallback на внутренний id.

        Returns:
            True если пользователь найден и статус установлен, False иначе.
        """
        user = None

        if source:
            # Точный поиск по платформе
            result = await self.session.execute(
                select(User).where(
                    User.telegram_id == user_id,
                    User.source == source,
                    User.deleted_at.is_(None),
                )
            )
            user = result.scalar_one_or_none()
        else:
            # Поиск по telegram_id без фильтра платформы (обратная совместимость)
            result = await self.session.execute(
                select(User).where(
                    User.telegram_id == user_id,
                    User.deleted_at.is_(None),
                )
            )
            user = result.scalar_one_or_none()

        if not user:
            # Fallback на внутренний id
            result = await self.session.execute(
                select(User).where(
                    User.id == user_id,
                    User.deleted_at.is_(None),
                )
            )
            user = result.scalar_one_or_none()

        if not user:
            return False

        user.subscription_type = "vip"
        user.vip_reason = reason
        user.subscription_until = None  # VIP без срока действия
        await self.session.commit()

        logger.info(
            "Установлен VIP-статус для пользователя %d (telegram_id=%d, source=%s): %s",
            user.id, user.telegram_id, user.source, reason,
        )
        return True

    async def remove_vip_status(self, user_id: int) -> bool:
        """Снятие VIP-статуса, возврат на бесплатный тариф."""
        result = await self.session.execute(
            select(User).where(User.id == user_id)
        )
        user = result.scalar_one_or_none()

        if not user:
            return False

        user.subscription_type = "free"
        user.vip_reason = None
        await self.session.commit()

        logger.info("Снят VIP-статус для пользователя %d", user_id)
        return True

    async def remove_premium_subscription(self, user_id: int) -> bool:
        """Снятие premium-подписки, возврат на бесплатный тариф."""
        result = await self.session.execute(
            select(User).where(User.id == user_id)
        )
        user = result.scalar_one_or_none()

        if not user:
            return False

        user.subscription_type = "free"
        user.subscription_until = None
        await self.session.commit()

        logger.info("Снята premium-подписка для пользователя %d", user_id)
        return True

    async def enable_recurring_payment(self, user_id: int, recurring_charge_id: str) -> bool:
        """Включение рекуррентного платежа для пользователя."""
        result = await self.session.execute(
            select(User).where(User.id == user_id)
        )
        user = result.scalar_one_or_none()

        if not user:
            return False

        user.recurring_payment_enabled = 1
        user.telegram_recurring_payment_charge_id = recurring_charge_id
        await self.session.commit()

        logger.info(
            "Включено автопродление для пользователя %d с charge_id %s",
            user_id, recurring_charge_id,
        )
        return True

    async def disable_recurring_payment(self, user_id: int) -> bool:
        """Отключение рекуррентного платежа для пользователя."""
        result = await self.session.execute(
            select(User).where(User.id == user_id)
        )
        user = result.scalar_one_or_none()

        if not user:
            return False

        user.recurring_payment_enabled = 0
        user.telegram_recurring_payment_charge_id = None
        await self.session.commit()

        logger.info("Отключено автопродление для пользователя %d", user_id)
        return True

    async def is_recurring_enabled(self, user_id: int) -> tuple[bool, Optional[str]]:
        """Проверка, включено ли автопродление для пользователя."""
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
        recurring_charge_id: str = None,
    ) -> Payment:
        """Создание записи о платеже."""
        payment = Payment(
            user_id=user_id,
            amount=amount,
            label=label,
            payment_id=payment_id,
            status="pending",
            is_recurring=1 if is_recurring else 0,
            telegram_recurring_payment_charge_id=recurring_charge_id,
        )
        self.session.add(payment)
        await self.session.commit()
        await self.session.refresh(payment)
        return payment

    async def get_payment_by_label(self, label: str) -> Optional[Payment]:
        """Получение платежа по уникальной метке."""
        result = await self.session.execute(
            select(Payment).where(Payment.label == label)
        )
        return result.scalar_one_or_none()

    async def get_payment_by_payment_id(self, payment_id: str) -> Optional[Payment]:
        """Получение платежа по YooKassa payment ID."""
        result = await self.session.execute(
            select(Payment).where(Payment.payment_id == payment_id)
        )
        return result.scalar_one_or_none()

    async def complete_payment(self, label: str) -> bool:
        """Завершение платежа и активация подписки."""
        payment = await self.get_payment_by_label(label)

        if not payment or payment.status == "completed":
            return False

        payment.status = "completed"
        payment.completed_at = datetime.utcnow()

        # Активируем premium для пользователя
        await self.activate_premium(payment.user_id, months=1)

        await self.session.commit()
        logger.info("Завершён платёж %s для пользователя %d", label, payment.user_id)
        return True

    async def update_payment_status(self, payment_id: str, status: str) -> bool:
        """Обновление статуса платежа по YooKassa payment_id.

        Args:
            payment_id: YooKassa payment ID.
            status: Новый статус (pending, succeeded, canceled).

        Returns:
            True если платёж найден и обновлён, False иначе.
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

        logger.info("Обновлён статус платежа %s на %s", payment_id, status)
        return True

    async def get_user_payments(self, user_id: int) -> List[Payment]:
        """Получение всех платежей пользователя."""
        result = await self.session.execute(
            select(Payment)
            .where(Payment.user_id == user_id)
            .order_by(desc(Payment.created_at))
        )
        return list(result.scalars().all())

    async def get_all_vip_users(self) -> List[User]:
        """Получение всех активных VIP-пользователей."""
        result = await self.session.execute(
            select(User).where(
                User.subscription_type == "vip",
                User.deleted_at.is_(None),
            )
        )
        return list(result.scalars().all())

    async def get_all_premium_users(self) -> List[User]:
        """Получение всех активных пользователей с premium-подпиской."""
        result = await self.session.execute(
            select(User).where(
                User.subscription_type == "premium",
                User.subscription_until > datetime.utcnow(),
                User.deleted_at.is_(None),
            )
        )
        return list(result.scalars().all())


class ReminderRepository:
    """Репозиторий для управления ремайндерами неактивных пользователей.

    Отвечает за поиск пользователей, которым нужно отправить
    напоминание через 1, 3 или 7 дней после последнего предсказания,
    фиксацию факта отправки и сброс цепочки при новой активности.
    """

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_users_for_reminder(self, day: int) -> List[User]:
        """Получение пользователей для отправки ремайндера.

        Находит активных пользователей, у которых последнее предсказание
        (или дата регистрации, если предсказаний не было) попадает
        в суточный диапазон [day, day+1) дней назад, и у которых
        ещё нет записи об отправке ремайндера этого дня.

        Args:
            day: День неактивности (1, 3 или 7).

        Returns:
            Список объектов User, которым нужно отправить ремайндер.
        """
        now = datetime.utcnow()
        lower_bound = now - timedelta(days=day + 1)
        upper_bound = now - timedelta(days=day)

        # Подзапрос: дата последнего предсказания пользователя
        last_pred_subq = (
            select(
                Prediction.user_id,
                func.max(Prediction.created_at).label("last_pred_at"),
            )
            .group_by(Prediction.user_id)
            .subquery()
        )

        # Подзапрос: проверка, что ремайндер уже отправлялся
        reminder_exists = exists().where(
            UserReminder.user_id == User.id,
            UserReminder.reminder_day == day,
        )

        stmt = (
            select(User)
            .outerjoin(last_pred_subq, User.id == last_pred_subq.c.user_id)
            .where(
                User.deleted_at.is_(None),
                ~reminder_exists,
                or_(
                    # Есть предсказания — смотрим на последнее
                    and_(
                        last_pred_subq.c.last_pred_at.isnot(None),
                        last_pred_subq.c.last_pred_at >= lower_bound,
                        last_pred_subq.c.last_pred_at < upper_bound,
                    ),
                    # Нет предсказаний — смотрим на дату регистрации
                    and_(
                        last_pred_subq.c.last_pred_at.is_(None),
                        User.created_at >= lower_bound,
                        User.created_at < upper_bound,
                    ),
                ),
            )
        )

        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def mark_reminder_sent(self, user_id: int, day: int) -> None:
        """Фиксация отправки ремайндера.

        Создаёт запись в user_reminders, чтобы в следующих циклах
        планировщика этот ремайндер не дублировался.

        Args:
            user_id: Внутренний ID пользователя.
            day: День неактивности (1, 3 или 7).
        """
        reminder = UserReminder(user_id=user_id, reminder_day=day)
        self.session.add(reminder)
        await self.session.commit()
        logger.info(
            "Ремайндер дня %d зафиксирован для пользователя %d", day, user_id
        )

    async def reset_reminders(self, user_id: int) -> None:
        """Сброс цепочки ремайндеров пользователя.

        Вызывается при новом предсказании — удаляет все записи
        ремайндеров, чтобы цепочка 1→3→7 началась заново.

        Args:
            user_id: Внутренний ID пользователя.
        """
        result = await self.session.execute(
            delete(UserReminder).where(UserReminder.user_id == user_id)
        )
        await self.session.commit()

        deleted = result.rowcount or 0
        if deleted > 0:
            logger.info(
                "Сброшена цепочка ремайндеров для пользователя %d (удалено %d)",
                user_id, deleted,
            )


class PartnerRepository:
    """Репозиторий для операций с партнёрами и реферальными переходами.

    Отвечает за полный жизненный цикл партнёра: создание (вместе
    с AdminUser), удаление, запись реферальных кликов и получение
    статистики переходов с группировкой по дням.
    """

    # Длина генерируемого реферального кода
    _REFERRAL_CODE_LENGTH = 8

    def __init__(self, session: AsyncSession):
        self.session = session

    def _generate_referral_code(self) -> str:
        """Генерация уникального реферального кода.

        Код состоит из букв латинского алфавита (строчных) и цифр.
        Длина определяется _REFERRAL_CODE_LENGTH (по умолчанию 8 символов).

        Returns:
            Строка вида 'a7k2m9x1'.
        """
        alphabet = string.ascii_lowercase + string.digits
        return "".join(secrets.choice(alphabet) for _ in range(self._REFERRAL_CODE_LENGTH))

    async def _ensure_unique_referral_code(self) -> str:
        """Генерация гарантированно уникального реферального кода.

        Проверяет отсутствие коллизий в таблице partners.
        При коллизии генерирует новый код (до 10 попыток).

        Returns:
            Уникальный реферальный код.

        Raises:
            RuntimeError: Если не удалось сгенерировать уникальный код за 10 попыток.
        """
        for _ in range(10):
            code = self._generate_referral_code()
            result = await self.session.execute(
                select(Partner).where(Partner.referral_code == code)
            )
            if result.scalar_one_or_none() is None:
                return code

        raise RuntimeError("Не удалось сгенерировать уникальный реферальный код за 10 попыток")

    async def create_partner(
        self,
        username: str,
        password_hash: str,
        description: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Создание нового партнёра.

        Создаёт запись AdminUser с ролью 'partner' и связанную
        запись Partner с уникальным реферальным кодом.

        Args:
            username: Логин партнёра для входа в админку.
            password_hash: Хеш пароля (bcrypt).
            description: Описание партнёра (компания, канал и т.д.).

        Returns:
            Словарь с данными созданного партнёра:
            {partner_id, admin_user_id, username, referral_code, description}.

        Raises:
            IntegrityError: Если username уже занят.
        """
        # Создаём AdminUser с ролью partner
        admin_user = AdminUser(
            username=username,
            password_hash=password_hash,
            role="partner",
        )
        self.session.add(admin_user)
        await self.session.flush()  # Получаем admin_user.id без коммита

        # Генерируем уникальный реферальный код
        referral_code = await self._ensure_unique_referral_code()

        # Создаём запись Partner
        partner = Partner(
            admin_user_id=admin_user.id,
            referral_code=referral_code,
            description=description,
        )
        self.session.add(partner)

        await self.session.commit()
        await self.session.refresh(partner)
        await self.session.refresh(admin_user)

        logger.info(
            "Создан партнёр: username=%s, referral_code=%s, partner_id=%d",
            username, referral_code, partner.id,
        )

        return {
            "partner_id": partner.id,
            "admin_user_id": admin_user.id,
            "username": admin_user.username,
            "referral_code": partner.referral_code,
            "description": partner.description,
        }

    async def delete_partner(self, partner_id: int) -> bool:
        """Удаление партнёра и связанного AdminUser.

        Каскадно удаляет: Partner → ReferralClick (через CASCADE),
        AdminUser удаляется отдельно. Поле referred_by_partner_id
        в users обнуляется (ON DELETE SET NULL).

        Args:
            partner_id: ID партнёра.

        Returns:
            True если партнёр найден и удалён, False иначе.
        """
        result = await self.session.execute(
            select(Partner).where(Partner.id == partner_id)
        )
        partner = result.scalar_one_or_none()

        if not partner:
            return False

        admin_user_id = partner.admin_user_id

        # Удаляем партнёра (каскадно удалит referral_clicks)
        await self.session.delete(partner)

        # Удаляем связанного AdminUser
        admin_result = await self.session.execute(
            select(AdminUser).where(AdminUser.id == admin_user_id)
        )
        admin_user = admin_result.scalar_one_or_none()
        if admin_user:
            await self.session.delete(admin_user)

        await self.session.commit()

        logger.info("Удалён партнёр: partner_id=%d, admin_user_id=%d", partner_id, admin_user_id)
        return True

    async def get_partner_by_referral_code(self, referral_code: str) -> Optional[Partner]:
        """Получение партнёра по реферальному коду.

        Используется при обработке /start с реферальным параметром.

        Args:
            referral_code: Реферальный код из deep link.

        Returns:
            Объект Partner или None.
        """
        result = await self.session.execute(
            select(Partner).where(Partner.referral_code == referral_code)
        )
        return result.scalar_one_or_none()

    async def get_partner_by_admin_user_id(self, admin_user_id: int) -> Optional[Partner]:
        """Получение партнёра по ID администратора.

        Используется для отображения кабинета партнёра после авторизации.

        Args:
            admin_user_id: ID записи AdminUser.

        Returns:
            Объект Partner или None.
        """
        result = await self.session.execute(
            select(Partner).where(Partner.admin_user_id == admin_user_id)
        )
        return result.scalar_one_or_none()

    async def get_all_partners(self) -> List[Dict[str, Any]]:
        """Получение всех партнёров с количеством кликов.

        Returns:
            Список словарей с данными партнёров, включая total_clicks.
        """
        result = await self.session.execute(
            select(Partner).order_by(desc(Partner.created_at))
        )
        partners = list(result.scalars().all())

        partners_data = []
        for partner in partners:
            # Подсчёт кликов
            clicks_result = await self.session.execute(
                select(func.count(ReferralClick.id)).where(
                    ReferralClick.partner_id == partner.id
                )
            )
            total_clicks = clicks_result.scalar() or 0

            # Подсчёт уникальных пользователей, пришедших по ссылке
            users_result = await self.session.execute(
                select(func.count(User.id)).where(
                    User.referred_by_partner_id == partner.id,
                    User.deleted_at.is_(None),
                )
            )
            referred_users = users_result.scalar() or 0

            # Получаем username админа
            admin_result = await self.session.execute(
                select(AdminUser.username).where(AdminUser.id == partner.admin_user_id)
            )
            admin_row = admin_result.fetchone()
            admin_username = admin_row[0] if admin_row else "unknown"

            partners_data.append({
                "id": partner.id,
                "admin_user_id": partner.admin_user_id,
                "username": admin_username,
                "referral_code": partner.referral_code,
                "description": partner.description,
                "total_clicks": total_clicks,
                "referred_users": referred_users,
                "created_at": partner.created_at.isoformat() if partner.created_at else None,
            })

        return partners_data

    async def record_click(
        self,
        partner_id: int,
        telegram_id: int,
        source: str = "tg",
    ) -> ReferralClick:
        """Запись перехода по реферальной ссылке.

        Каждый переход записывается отдельно (не дедуплицируется),
        чтобы партнёр видел полную картину трафика.

        Args:
            partner_id: ID партнёра.
            telegram_id: ID пользователя, который перешёл.
            source: Платформа перехода ('tg' или 'max').

        Returns:
            Созданный объект ReferralClick.
        """
        click = ReferralClick(
            partner_id=partner_id,
            telegram_id=telegram_id,
            source=source,
        )
        self.session.add(click)
        await self.session.commit()
        await self.session.refresh(click)

        logger.info(
            "Записан реферальный переход: partner_id=%d, telegram_id=%d, source=%s",
            partner_id, telegram_id, source,
        )
        return click

    async def get_click_stats(self, partner_id: int) -> Dict[str, Any]:
        """Получение полной статистики кликов для партнёра.

        Args:
            partner_id: ID партнёра.

        Returns:
            Словарь со статистикой: total_clicks, today_clicks,
            referred_users, clicks_by_day (последние 30 дней).
        """
        # Общее количество кликов
        total_result = await self.session.execute(
            select(func.count(ReferralClick.id)).where(
                ReferralClick.partner_id == partner_id
            )
        )
        total_clicks = total_result.scalar() or 0

        # Клики за сегодня
        today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        today_result = await self.session.execute(
            select(func.count(ReferralClick.id)).where(
                ReferralClick.partner_id == partner_id,
                ReferralClick.created_at >= today_start,
            )
        )
        today_clicks = today_result.scalar() or 0

        # Количество привлечённых пользователей
        users_result = await self.session.execute(
            select(func.count(User.id)).where(
                User.referred_by_partner_id == partner_id,
                User.deleted_at.is_(None),
            )
        )
        referred_users = users_result.scalar() or 0

        # Клики по дням за последние 30 дней
        thirty_days_ago = datetime.utcnow() - timedelta(days=30)
        daily_result = await self.session.execute(
            text("""
                SELECT
                    strftime('%Y-%m-%d', created_at) as day,
                    COUNT(*) as count
                FROM referral_clicks
                WHERE partner_id = :partner_id
                    AND created_at >= :since
                GROUP BY strftime('%Y-%m-%d', created_at)
                ORDER BY day
            """),
            {"partner_id": partner_id, "since": thirty_days_ago},
        )
        clicks_by_day = [
            {"date": row[0], "count": row[1]}
            for row in daily_result.fetchall()
        ]

        return {
            "total_clicks": total_clicks,
            "today_clicks": today_clicks,
            "referred_users": referred_users,
            "clicks_by_day": clicks_by_day,
        }

    async def get_partner_earnings_stats(self, partner_id: int) -> Dict[str, Any]:
        """Получение статистики выручки и заработка партнёра.

        Рассчитывает выручку от успешных платежей пользователей,
        привлечённых партнёром, и заработок по фиксированной
        комиссии 25%. Возвращает общие показатели, показатели
        за текущий месяц и помесячную разбивку за последние 6 месяцев.

        Args:
            partner_id: ID партнёра.

        Returns:
            Словарь с выручкой, заработком, количеством покупок
            и помесячной разбивкой.
        """
        commission_rate = 0.25

        # Общая выручка (сумма в копейках)
        total_revenue_result = await self.session.execute(
            text("""
                SELECT COALESCE(SUM(pay.amount), 0)
                FROM payments pay
                JOIN users u ON u.id = pay.user_id
                WHERE u.referred_by_partner_id = :partner_id
                  AND pay.status IN ('succeeded', 'completed')
                  AND u.deleted_at IS NULL
            """),
            {"partner_id": partner_id},
        )
        total_revenue_kopecks = total_revenue_result.scalar() or 0

        # Выручка за текущий месяц
        month_revenue_result = await self.session.execute(
            text("""
                SELECT COALESCE(SUM(pay.amount), 0)
                FROM payments pay
                JOIN users u ON u.id = pay.user_id
                WHERE u.referred_by_partner_id = :partner_id
                  AND pay.status IN ('succeeded', 'completed')
                  AND u.deleted_at IS NULL
                  AND pay.created_at >= date('now', 'start of month')
            """),
            {"partner_id": partner_id},
        )
        month_revenue_kopecks = month_revenue_result.scalar() or 0

        # Общее количество покупок
        total_purchases_result = await self.session.execute(
            text("""
                SELECT COUNT(*)
                FROM payments pay
                JOIN users u ON u.id = pay.user_id
                WHERE u.referred_by_partner_id = :partner_id
                  AND pay.status IN ('succeeded', 'completed')
                  AND u.deleted_at IS NULL
            """),
            {"partner_id": partner_id},
        )
        total_purchases = total_purchases_result.scalar() or 0

        # Покупки за текущий месяц
        month_purchases_result = await self.session.execute(
            text("""
                SELECT COUNT(*)
                FROM payments pay
                JOIN users u ON u.id = pay.user_id
                WHERE u.referred_by_partner_id = :partner_id
                  AND pay.status IN ('succeeded', 'completed')
                  AND u.deleted_at IS NULL
                  AND pay.created_at >= date('now', 'start of month')
            """),
            {"partner_id": partner_id},
        )
        month_purchases = month_purchases_result.scalar() or 0

        # Помесячная разбивка за последние 6 месяцев
        monthly_result = await self.session.execute(
            text("""
                SELECT 
                    strftime('%Y-%m', pay.created_at) as month,
                    COALESCE(SUM(pay.amount), 0) as revenue
                FROM payments pay
                JOIN users u ON u.id = pay.user_id
                WHERE u.referred_by_partner_id = :partner_id
                  AND pay.status IN ('succeeded', 'completed')
                  AND u.deleted_at IS NULL
                  AND pay.created_at >= date('now', '-6 months')
                GROUP BY strftime('%Y-%m', pay.created_at)
                ORDER BY month DESC
            """),
            {"partner_id": partner_id},
        )
        monthly_rows = monthly_result.fetchall()
        monthly_breakdown = [
            {
                "month": row[0],
                "revenue": round((row[1] or 0) / 100, 2),
                "earnings": round((row[1] or 0) / 100 * commission_rate, 2),
            }
            for row in monthly_rows
        ]

        return {
            "revenue_total": round(total_revenue_kopecks / 100, 2),
            "revenue_this_month": round(month_revenue_kopecks / 100, 2),
            "earnings_total": round(total_revenue_kopecks / 100 * commission_rate, 2),
            "earnings_this_month": round(month_revenue_kopecks / 100 * commission_rate, 2),
            "purchases_total": total_purchases,
            "purchases_this_month": month_purchases,
            "commission_percent": 25,
            "monthly_breakdown": monthly_breakdown,
        }

    async def get_marketing_stats(self) -> List[Dict[str, Any]]:
        """Агрегированная маркетинговая статистика по всем партнёрам.

        Один SQL-запрос возвращает все метрики для сводной таблицы
        раздела «Маркетинг»: клики, новые пользователи, предсказания
        когорты, покупки (succeeded/completed-платежи) и выручку.

        Returns:
            Список словарей, по одному на каждого партнёра.
        """
        result = await self.session.execute(text("""
            SELECT
                p.id               AS partner_id,
                p.referral_code,
                p.campaign_name,
                p.ad_cost,
                p.description,
                p.created_at,
                au.username        AS partner_username,

                -- Переходы (все активации /start с реф. кодом)
                (
                    SELECT COUNT(*)
                    FROM referral_clicks rc
                    WHERE rc.partner_id = p.id
                ) AS clicks,

                -- Новые пользователи, привлечённые ссылкой
                (
                    SELECT COUNT(*)
                    FROM users u
                    WHERE u.referred_by_partner_id = p.id
                      AND u.deleted_at IS NULL
                ) AS new_users,

                -- Предсказания когорты (качество канала)
                (
                    SELECT COUNT(*)
                    FROM predictions pr
                    JOIN users u ON u.id = pr.user_id
                    WHERE u.referred_by_partner_id = p.id
                      AND u.deleted_at IS NULL
                ) AS predictions_count,

                -- Покупки: и ручные (completed) и через webhook (succeeded)
                (
                    SELECT COUNT(*)
                    FROM payments pay
                    JOIN users u ON u.id = pay.user_id
                    WHERE u.referred_by_partner_id = p.id
                      AND pay.status IN ('succeeded', 'completed')
                      AND u.deleted_at IS NULL
                ) AS purchases,

                -- Выручка в копейках (делим на 100 при сериализации)
                (
                    SELECT COALESCE(SUM(pay.amount), 0)
                    FROM payments pay
                    JOIN users u ON u.id = pay.user_id
                    WHERE u.referred_by_partner_id = p.id
                      AND pay.status IN ('succeeded', 'completed')
                      AND u.deleted_at IS NULL
                ) AS revenue_kopecks

            FROM partners p
            JOIN admin_users au ON au.id = p.admin_user_id
            ORDER BY p.created_at DESC
        """))

        rows = result.fetchall()
        stats = []
        for row in rows:
            # _mapping гарантирует доступ по имени колонки в любой версии SQLAlchemy/aiosqlite
            m = row._mapping

            # created_at может прийти строкой из SQLite — обрабатываем оба варианта
            created_at_val = m["created_at"]
            if created_at_val is None:
                created_at_str = None
            elif hasattr(created_at_val, "isoformat"):
                created_at_str = created_at_val.isoformat()
            else:
                created_at_str = str(created_at_val)

            stats.append({
                "partner_id":        m["partner_id"],
                "referral_code":     m["referral_code"],
                "campaign_name":     m["campaign_name"] or "",
                "ad_cost":           m["ad_cost"] or 0,
                "description":       m["description"] or "",
                "partner_username":  m["partner_username"],
                "created_at":        created_at_str,
                "clicks":            m["clicks"],
                "new_users":         m["new_users"],
                "predictions_count": m["predictions_count"],
                "purchases":         m["purchases"],
                "revenue":           round((m["revenue_kopecks"] or 0) / 100, 2),
            })
        return stats

    async def update_partner_marketing(
        self,
        partner_id: int,
        campaign_name: Optional[str] = None,
        ad_cost: Optional[int] = None,
    ) -> bool:
        """Обновление маркетинговых полей партнёра.

        Используется для inline-редактирования в разделе «Маркетинг».
        Обновляет только переданные поля (None = не трогать).

        Args:
            partner_id:    ID партнёра.
            campaign_name: Новое название кампании (None — без изменений).
            ad_cost:       Новые затраты в рублях (None — без изменений).

        Returns:
            True если партнёр найден и обновлён, False если не найден.
        """
        result = await self.session.execute(
            select(Partner).where(Partner.id == partner_id)
        )
        partner = result.scalar_one_or_none()

        if not partner:
            return False

        if campaign_name is not None:
            partner.campaign_name = campaign_name.strip() or None
        if ad_cost is not None:
            partner.ad_cost = max(0, int(ad_cost))

        await self.session.commit()

        logger.info(
            "Обновлены маркетинговые поля партнёра %d: campaign_name=%r, ad_cost=%r",
            partner_id, campaign_name, ad_cost,
        )
        return True