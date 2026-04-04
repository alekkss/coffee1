"""FastAPI-приложение админ-панели Coffee Oracle.

Содержит все роуты, API-эндпоинты, вебхук YooKassa,
управление партнёрами и кабинет партнёра.
"""

import logging
from datetime import datetime, timedelta
from typing import Annotated, Any, Dict, List

from fastapi import Depends, FastAPI, Query, Request, status, HTTPException, Response
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from coffee_oracle.admin.auth import (
    authenticate_admin,
    create_access_token,
    require_admin_role,
    require_superadmin_role,
)
from coffee_oracle.config import config
from coffee_oracle.database.connection import db_manager
from pydantic import BaseModel, Field
import bcrypt
from sqlalchemy import select, delete
from coffee_oracle.database.models import Prediction, User, AdminUser
from coffee_oracle.database.repositories import (
    PartnerRepository,
    PredictionRepository,
    SettingsRepository,
    SubscriptionRepository,
    UserRepository,
)

# Создание FastAPI-приложения
app = FastAPI(title="Coffee Oracle Admin v2.0", version="2.0.0")

logger = logging.getLogger(__name__)

# Раздача медиафайлов
app.mount("/media", StaticFiles(directory="/opt/oracle-bot/media"), name="media")

# Настройка шаблонов
templates = Jinja2Templates(directory="coffee_oracle/admin/templates")


@app.exception_handler(status.HTTP_401_UNAUTHORIZED)
async def unauthorized_exception_handler(request: Request, exc: HTTPException):
    """Перенаправление на страницу логина при отсутствии авторизации."""
    if "text/html" in request.headers.get("accept", ""):
        return RedirectResponse(url="/login")
    return JSONResponse(status_code=401, content={"detail": exc.detail})


@app.exception_handler(status.HTTP_403_FORBIDDEN)
async def forbidden_exception_handler(request: Request, exc: HTTPException):
    """Перенаправление партнёров в кабинет при попытке доступа к админ-страницам."""
    if "text/html" in request.headers.get("accept", ""):
        # Проверяем, авторизован ли пользователь как партнёр
        try:
            user = await authenticate_admin(request.cookies.get("access_token"))
            if user.role == "partner":
                return RedirectResponse(url="/partner")
        except HTTPException:
            pass
        return RedirectResponse(url="/login")
    return JSONResponse(status_code=403, content={"detail": exc.detail})


class LoginRequest(BaseModel):
    username: str
    password: str


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    """Страница входа."""
    return templates.TemplateResponse("login.html", {"request": request})


@app.post("/login")
async def login(data: LoginRequest, response: Response):
    """Обработка входа и установка JWT cookie.

    Для партнёров в ответе добавляется redirect_url=/partner,
    чтобы фронтенд перенаправил на кабинет партнёра.
    """
    async for session in db_manager.get_session():
        stmt = select(AdminUser).where(AdminUser.username == data.username)
        result = await session.execute(stmt)
        user = result.scalar_one_or_none()

        valid = False
        if user:
            try:
                if bcrypt.checkpw(
                    data.password.encode("utf-8"),
                    user.password_hash.encode("utf-8"),
                ):
                    valid = True
            except ValueError:
                pass

        if not valid:
            raise HTTPException(
                status_code=400, detail="Неверный логин или пароль"
            )

        # Создаём JWT-токен
        token = create_access_token(user.id, user.username)

        # Устанавливаем cookie
        response.set_cookie(
            key="access_token",
            value=token,
            httponly=True,
            max_age=86400,  # 24 часа
            secure=config.secure_cookies,
            samesite="lax",
        )

        # Для партнёров указываем URL кабинета
        redirect_url = "/partner" if user.role == "partner" else "/"

        return {"success": True, "redirect_url": redirect_url}


# ===== Страницы админ-панели (защищены от партнёров) =====


@app.get("/", response_class=HTMLResponse)
async def dashboard_page(
    request: Request,
    user: Annotated[AdminUser, Depends(require_admin_role)],
) -> HTMLResponse:
    """Главная страница дашборда."""
    return templates.TemplateResponse(
        "dashboard.html", {"request": request, "user": user}
    )


@app.get("/users", response_class=HTMLResponse)
async def users_page(
    request: Request,
    user: Annotated[AdminUser, Depends(require_admin_role)],
) -> HTMLResponse:
    """Страница списка пользователей."""
    return templates.TemplateResponse(
        "users.html", {"request": request, "user": user}
    )


@app.get("/predictions", response_class=HTMLResponse)
async def predictions_page(
    request: Request,
    user: Annotated[AdminUser, Depends(require_admin_role)],
) -> HTMLResponse:
    """Страница предсказаний."""
    return templates.TemplateResponse(
        "predictions.html", {"request": request, "user": user}
    )


@app.get("/settings", response_class=HTMLResponse)
async def settings_page(
    request: Request,
    user: Annotated[AdminUser, Depends(require_superadmin_role)],
) -> HTMLResponse:
    """Страница настроек (только superadmin)."""
    return templates.TemplateResponse(
        "settings.html", {"request": request, "user": user}
    )


@app.get("/subscriptions", response_class=HTMLResponse)
async def subscriptions_page(
    request: Request,
    user: Annotated[AdminUser, Depends(require_admin_role)],
) -> HTMLResponse:
    """Страница управления подписками."""
    return templates.TemplateResponse(
        "subscriptions.html", {"request": request, "user": user}
    )


# ===== Кабинет партнёра =====


@app.get("/partner", response_class=HTMLResponse)
async def partner_cabinet_page(
    request: Request,
    user: Annotated[AdminUser, Depends(authenticate_admin)],
) -> HTMLResponse:
    """Страница кабинета партнёра.

    Доступна только пользователям с ролью 'partner'.
    Администраторы перенаправляются на главную.
    """
    if user.role != "partner":
        return RedirectResponse(url="/", status_code=302)

    return templates.TemplateResponse(
        "partner_cabinet.html", {"request": request, "user": user}
    )


@app.get("/api/partner/stats")
async def get_partner_stats(
    user: Annotated[AdminUser, Depends(authenticate_admin)],
) -> Dict[str, Any]:
    """Получение статистики для кабинета партнёра.

    Возвращает реферальную ссылку, общее число переходов,
    переходы за сегодня, количество привлечённых пользователей
    и разбивку по дням за 30 дней.
    """
    if user.role != "partner":
        raise HTTPException(status_code=403, detail="Доступ запрещён")

    async for session in db_manager.get_session():
        partner_repo = PartnerRepository(session)
        partner = await partner_repo.get_partner_by_admin_user_id(user.id)

        if not partner:
            raise HTTPException(
                status_code=404, detail="Партнёрский профиль не найден"
            )

        # Получаем статистику кликов
        stats = await partner_repo.get_click_stats(partner.id)

        # Формируем реферальную ссылку
        bot_username = config.bot_username if hasattr(config, "bot_username") and config.bot_username else ""
        referral_link = (
            f"https://t.me/{bot_username}?start={partner.referral_code}"
            if bot_username
            else ""
        )

        return {
            "success": True,
            "referral_code": partner.referral_code,
            "referral_link": referral_link,
            "description": partner.description,
            "total_clicks": stats["total_clicks"],
            "today_clicks": stats["today_clicks"],
            "referred_users": stats["referred_users"],
            "clicks_by_day": stats["clicks_by_day"],
        }


# ===== API управления партнёрами (superadmin) =====


class PartnerCreateRequest(BaseModel):
    """Модель запроса на создание партнёра."""

    username: str = Field(..., min_length=3, max_length=50)
    password: str = Field(..., min_length=6)
    description: str = Field("", max_length=500)


@app.get("/api/partners")
async def get_partners(
    user: Annotated[AdminUser, Depends(require_superadmin_role)],
) -> Dict[str, Any]:
    """Получение списка всех партнёров (superadmin)."""
    async for session in db_manager.get_session():
        partner_repo = PartnerRepository(session)
        partners = await partner_repo.get_all_partners()

        # Добавляем реферальные ссылки
        bot_username = config.bot_username if hasattr(config, "bot_username") and config.bot_username else ""
        for p in partners:
            p["referral_link"] = (
                f"https://t.me/{bot_username}?start={p['referral_code']}"
                if bot_username
                else ""
            )

        return {"success": True, "partners": partners}


@app.post("/api/partners")
async def create_partner(
    data: PartnerCreateRequest,
    user: Annotated[AdminUser, Depends(require_superadmin_role)],
) -> Dict[str, Any]:
    """Создание нового партнёра (superadmin).

    Создаёт AdminUser с ролью 'partner' и связанную запись Partner
    с уникальным реферальным кодом.
    """
    async for session in db_manager.get_session():
        # Проверяем уникальность логина
        stmt = select(AdminUser).where(AdminUser.username == data.username)
        result = await session.execute(stmt)
        if result.scalar_one_or_none():
            raise HTTPException(
                status_code=400, detail="Логин уже занят"
            )

        # Хешируем пароль
        password_hash = bcrypt.hashpw(
            data.password.encode("utf-8"), bcrypt.gensalt()
        ).decode("utf-8")

        partner_repo = PartnerRepository(session)

        try:
            partner_data = await partner_repo.create_partner(
                username=data.username,
                password_hash=password_hash,
                description=data.description or None,
            )
        except Exception as e:
            logger.error("Ошибка создания партнёра: %s", e)
            raise HTTPException(
                status_code=500, detail="Ошибка создания партнёра"
            )

        # Формируем реферальную ссылку
        bot_username = config.bot_username if hasattr(config, "bot_username") and config.bot_username else ""
        referral_link = (
            f"https://t.me/{bot_username}?start={partner_data['referral_code']}"
            if bot_username
            else ""
        )

        logger.info(
            "Создан партнёр: username=%s, code=%s (создал: %s)",
            data.username,
            partner_data["referral_code"],
            user.username,
        )

        return {
            "success": True,
            "partner": {
                **partner_data,
                "referral_link": referral_link,
            },
        }


@app.delete("/api/partners/{partner_id}")
async def delete_partner(
    partner_id: int,
    user: Annotated[AdminUser, Depends(require_superadmin_role)],
) -> Dict[str, Any]:
    """Удаление партнёра (superadmin).

    Каскадно удаляет AdminUser, Partner и все ReferralClick.
    Поле referred_by_partner_id в users обнуляется (SET NULL).
    """
    async for session in db_manager.get_session():
        partner_repo = PartnerRepository(session)
        success = await partner_repo.delete_partner(partner_id)

        if not success:
            raise HTTPException(
                status_code=404, detail="Партнёр не найден"
            )

        logger.info(
            "Удалён партнёр: partner_id=%d (удалил: %s)",
            partner_id,
            user.username,
        )

        return {"success": True, "message": "Партнёр удалён"}


# ===== Общие служебные эндпоинты =====


@app.get("/logout")
async def logout(response: Response):
    """Выход: очистка cookie и редирект на логин."""
    response.delete_cookie(key="access_token")
    return RedirectResponse(url="/login")


@app.get("/terms", response_class=HTMLResponse)
async def terms_page(request: Request):
    """Публичная страница условий использования."""
    async for session in db_manager.get_session():
        settings_repo = SettingsRepository(session)
        text = await settings_repo.get_setting("terms_text")
    return templates.TemplateResponse(
        "legal_page.html",
        {"request": request, "title": "Условия использования", "content": text or ""},
    )


@app.get("/privacy", response_class=HTMLResponse)
async def privacy_page(request: Request):
    """Публичная страница политики конфиденциальности."""
    async for session in db_manager.get_session():
        settings_repo = SettingsRepository(session)
        text = await settings_repo.get_setting("privacy_text")
    return templates.TemplateResponse(
        "legal_page.html",
        {
            "request": request,
            "title": "Политика конфиденциальности",
            "content": text or "",
        },
    )


@app.get("/health")
async def health_check() -> Dict[str, str]:
    """Health-check эндпоинт."""
    return {"status": "healthy", "timestamp": datetime.utcnow().isoformat()}


# ===== API дашборда и аналитики =====


@app.get("/api/dashboard")
async def dashboard_stats(
    _: Annotated[AdminUser, Depends(require_admin_role)],
) -> Dict[str, Any]:
    """Получение KPI-метрик для дашборда."""
    async for session in db_manager.get_session():
        user_repo = UserRepository(session)
        prediction_repo = PredictionRepository(session)

        total_users = await user_repo.get_users_count()
        new_users_today = await user_repo.get_new_users_count(hours=24)
        total_predictions = await prediction_repo.get_predictions_count()
        predictions_today = await prediction_repo.get_predictions_count_since(hours=24)

        return {
            "kpi": {
                "total_users": total_users,
                "new_users_today": new_users_today,
                "total_predictions": total_predictions,
                "predictions_today": predictions_today,
            },
            "timestamp": datetime.utcnow().isoformat(),
        }


@app.get("/api/analytics")
async def analytics_data(
    period: str = Query("24h", regex="^(24h|7d|4w|12m)$"),
    _: Annotated[str, Depends(require_admin_role)] = None,
) -> Dict[str, Any]:
    """Получение данных аналитики для графиков."""
    async for session in db_manager.get_session():
        user_repo = UserRepository(session)
        prediction_repo = PredictionRepository(session)

        if period == "24h":
            hours_back = 24
            group_by = "hour"
        elif period == "7d":
            hours_back = 7 * 24
            group_by = "day"
        elif period == "4w":
            hours_back = 4 * 7 * 24
            group_by = "week"
        else:  # 12m
            hours_back = 12 * 30 * 24
            group_by = "month"

        users_data = await user_repo.get_users_time_series(hours_back, group_by)
        predictions_data = await prediction_repo.get_predictions_time_series(
            hours_back, group_by
        )

        return {
            "period": period,
            "users": users_data,
            "predictions": predictions_data,
            "timestamp": datetime.utcnow().isoformat(),
        }


@app.get("/api/retention")
async def retention_stats(
    _: Annotated[str, Depends(require_admin_role)],
) -> Dict[str, Any]:
    """Получение статистики ретенции."""
    async for session in db_manager.get_session():
        user_repo = UserRepository(session)
        prediction_repo = PredictionRepository(session)

        periods = [
            ("today", 1),
            ("this_week", 7),
            ("this_month", 30),
            ("all_time", None),
        ]

        retention_data = []
        for period_name, days in periods:
            if days:
                new_users = await user_repo.get_new_users_count(hours=days * 24)
                predictions = await prediction_repo.get_predictions_count_since(
                    hours=days * 24
                )
            else:
                new_users = await user_repo.get_users_count()
                predictions = await prediction_repo.get_predictions_count()

            retention_data.append(
                {
                    "period": period_name.replace("_", " ").title(),
                    "new_users": new_users,
                    "predictions": predictions,
                }
            )

        return {"retention": retention_data}


# ===== API пользователей и предсказаний =====


@app.get("/api/users")
async def get_users(
    _: Annotated[str, Depends(require_admin_role)],
) -> List[Dict[str, Any]]:
    """Получение списка пользователей с количеством предсказаний."""
    try:
        async for session in db_manager.get_session():
            user_repo = UserRepository(session)
            prediction_repo = PredictionRepository(session)
            users = await user_repo.get_all_users()

            result = []
            for user in users:
                pred_count = await prediction_repo.get_user_predictions_count(user.id)
                result.append(
                    {
                        "id": user.id,
                        "telegram_id": user.telegram_id,
                        "source": user.source,
                        "username": user.username,
                        "full_name": user.full_name,
                        "subscription_type": user.subscription_type or "free",
                        "subscription_until": user.subscription_until.isoformat()
                        if user.subscription_until
                        else None,
                        "created_at": user.created_at.isoformat(),
                        "predictions_count": pred_count,
                    }
                )

            return result
    except Exception as e:
        logger.error("Ошибка в эндпоинте пользователей: %s", e)
        return []


@app.get("/api/predictions")
async def get_predictions(
    _: Annotated[str, Depends(require_admin_role)],
) -> List[Dict[str, Any]]:
    """Получение списка предсказаний."""
    try:
        async for session in db_manager.get_session():
            prediction_repo = PredictionRepository(session)
            predictions = await prediction_repo.get_all_predictions_with_users()

            return [
                {
                    "id": prediction.id,
                    "user_id": prediction.user_id,
                    "telegram_id": prediction.user.telegram_id
                    if prediction.user
                    else None,
                    "source": prediction.user.source if prediction.user else "tg",
                    "user_name": prediction.user.full_name
                    if prediction.user
                    else "Unknown",
                    "prediction_text": prediction.prediction_text,
                    "user_request": prediction.user_request,
                    "photo_path": prediction.photo_path,
                    "photos": [
                        {"id": p.id, "file_path": p.file_path}
                        for p in prediction.photos
                    ]
                    if prediction.photos
                    else [],
                    "created_at": prediction.created_at.isoformat(),
                    "subscription_type": prediction.subscription_type or "free",
                }
                for prediction in predictions
            ]
    except Exception as e:
        logger.error("Ошибка в эндпоинте предсказаний: %s", e)
        return []


# ===== Настройки бота =====


@app.get("/api/settings")
async def get_settings(
    _: Annotated[str, Depends(require_admin_role)],
) -> Dict[str, Any]:
    """Получение всех настроек бота."""
    async for session in db_manager.get_session():
        settings_repo = SettingsRepository(session)
        settings = await settings_repo.get_all_settings()
        return {"settings": settings}


@app.post("/api/settings")
async def update_settings(
    request: Request,
    user: Annotated[AdminUser, Depends(require_superadmin_role)],
) -> Dict[str, Any]:
    """Обновление настроек бота (superadmin)."""
    try:
        data = await request.json()
        async for session in db_manager.get_session():
            settings_repo = SettingsRepository(session)

            updated = []
            for key, value in data.items():
                await settings_repo.set_setting(
                    key, str(value), updated_by=user.username
                )
                updated.append(key)

            return {"success": True, "updated": updated}
    except Exception as e:
        logger.error("Ошибка обновления настроек: %s", e)
        return {"success": False, "error": str(e)}


@app.post("/api/settings/reset")
async def reset_settings(
    _: Annotated[str, Depends(require_superadmin_role)],
) -> Dict[str, Any]:
    """Сброс всех настроек к значениям по умолчанию (superadmin)."""
    try:
        async for session in db_manager.get_session():
            settings_repo = SettingsRepository(session)
            await settings_repo.reset_to_defaults()

            from coffee_oracle.services.openai_client import clear_settings_cache

            clear_settings_cache()

            return {"success": True, "message": "Настройки сброшены"}
    except Exception as e:
        logger.error("Ошибка сброса настроек: %s", e)
        return {"success": False, "error": str(e)}


@app.post("/api/settings/clear-cache")
async def clear_cache(
    _: Annotated[str, Depends(require_admin_role)],
) -> Dict[str, Any]:
    """Очистка кэша настроек LLM."""
    try:
        from coffee_oracle.services.openai_client import clear_settings_cache

        clear_settings_cache()
        return {"success": True, "message": "Кэш очищен"}
    except Exception as e:
        logger.error("Ошибка очистки кэша: %s", e)
        return {"success": False, "error": str(e)}


# ===== Управление администраторами =====


class AdminUserCreate(BaseModel):
    username: str = Field(..., min_length=3, max_length=50)
    password: str = Field(..., min_length=6)
    role: str = Field("restricted", pattern="^(superadmin|restricted)$")


@app.get("/admins", response_class=HTMLResponse)
async def admins_page(
    request: Request,
    user: Annotated[AdminUser, Depends(require_admin_role)],
) -> HTMLResponse:
    """Страница управления администраторами (временно отключена)."""
    return RedirectResponse(url="/", status_code=302)


@app.get("/api/admin-users")
async def get_admin_users(
    user: Annotated[AdminUser, Depends(require_superadmin_role)],
) -> List[Dict[str, Any]]:
    """Получение списка администраторов (superadmin)."""
    async for session in db_manager.get_session():
        stmt = select(AdminUser).order_by(AdminUser.created_at.desc())
        result = await session.execute(stmt)
        admins = result.scalars().all()

        return [
            {
                "id": a.id,
                "username": a.username,
                "role": a.role,
                "created_at": a.created_at.isoformat(),
            }
            for a in admins
        ]


@app.post("/api/admin-users")
async def create_admin_user(
    data: AdminUserCreate,
    user: Annotated[AdminUser, Depends(require_superadmin_role)],
) -> Dict[str, Any]:
    """Создание нового администратора (superadmin)."""
    async for session in db_manager.get_session():
        stmt = select(AdminUser).where(AdminUser.username == data.username)
        result = await session.execute(stmt)
        if result.scalar_one_or_none():
            raise HTTPException(status_code=400, detail="Логин уже занят")

        hashed_bytes = bcrypt.hashpw(
            data.password.encode("utf-8"), bcrypt.gensalt()
        )

        new_admin = AdminUser(
            username=data.username,
            password_hash=hashed_bytes.decode("utf-8"),
            role=data.role,
        )
        session.add(new_admin)
        try:
            await session.commit()
            return {"success": True, "message": f"Администратор {data.username} создан"}
        except Exception as e:
            await session.rollback()
            raise HTTPException(status_code=500, detail=str(e))


@app.delete("/api/admin-users/{user_id}")
async def delete_admin_user(
    user_id: int,
    user: Annotated[AdminUser, Depends(require_superadmin_role)],
) -> Dict[str, Any]:
    """Удаление администратора (superadmin)."""
    if user.id == user_id:
        raise HTTPException(
            status_code=400, detail="Нельзя удалить собственный аккаунт"
        )

    async for session in db_manager.get_session():
        stmt = select(AdminUser).where(AdminUser.id == user_id)
        result = await session.execute(stmt)
        admin_to_delete = result.scalar_one_or_none()

        if not admin_to_delete:
            raise HTTPException(status_code=404, detail="Администратор не найден")

        await session.delete(admin_to_delete)
        await session.commit()
        return {"success": True, "message": "Администратор удалён"}


# ===== Управление подписками =====


class VipStatusRequest(BaseModel):
    """Модель запроса на установку VIP-статуса."""

    user_id: int
    reason: str = Field(..., min_length=1, max_length=255)
    source: str = Field("tg", pattern="^(tg|max)$")


class PaymentCompleteRequest(BaseModel):
    """Модель запроса на ручное завершение платежа."""

    label: str


@app.get("/api/subscriptions/stats")
async def get_subscription_stats(
    user: Annotated[AdminUser, Depends(require_admin_role)],
) -> Dict[str, Any]:
    """Получение статистики подписок."""
    async for session in db_manager.get_session():
        sub_repo = SubscriptionRepository(session)
        stats = await sub_repo.get_subscription_stats()
        return {"success": True, "stats": stats}


@app.get("/api/subscriptions/vip")
async def get_vip_users(
    user: Annotated[AdminUser, Depends(require_admin_role)],
) -> Dict[str, Any]:
    """Получение списка VIP-пользователей."""
    async for session in db_manager.get_session():
        sub_repo = SubscriptionRepository(session)
        vip_users = await sub_repo.get_all_vip_users()
        return {
            "success": True,
            "users": [
                {
                    "id": u.id,
                    "telegram_id": u.telegram_id,
                    "source": u.source,
                    "username": u.username,
                    "full_name": u.full_name,
                    "vip_reason": u.vip_reason,
                }
                for u in vip_users
            ],
        }


@app.post("/api/subscriptions/vip")
async def set_vip_status(
    request: VipStatusRequest,
    user: Annotated[AdminUser, Depends(require_superadmin_role)],
) -> Dict[str, Any]:
    """Установка VIP-статуса (superadmin)."""
    async for session in db_manager.get_session():
        sub_repo = SubscriptionRepository(session)
        success = await sub_repo.set_vip_status(
            request.user_id, request.reason, source=request.source
        )
        if not success:
            raise HTTPException(status_code=404, detail="Пользователь не найден")
        return {
            "success": True,
            "message": f"VIP-статус установлен для пользователя {request.user_id} ({request.source})",
        }


@app.delete("/api/subscriptions/vip/{user_id}")
async def remove_vip_status(
    user_id: int,
    user: Annotated[AdminUser, Depends(require_superadmin_role)],
) -> Dict[str, Any]:
    """Снятие VIP-статуса (superadmin)."""
    async for session in db_manager.get_session():
        sub_repo = SubscriptionRepository(session)
        success = await sub_repo.remove_vip_status(user_id)
        if not success:
            raise HTTPException(status_code=404, detail="Пользователь не найден")
        return {
            "success": True,
            "message": f"VIP-статус снят с пользователя {user_id}",
        }


@app.post("/api/subscriptions/complete-payment")
async def complete_payment(
    request: PaymentCompleteRequest,
    user: Annotated[AdminUser, Depends(require_superadmin_role)],
) -> Dict[str, Any]:
    """Ручное завершение платежа (superadmin)."""
    async for session in db_manager.get_session():
        sub_repo = SubscriptionRepository(session)
        success = await sub_repo.complete_payment(request.label)
        if not success:
            raise HTTPException(
                status_code=404,
                detail="Платёж не найден или уже завершён",
            )
        return {"success": True, "message": f"Платёж {request.label} завершён"}


@app.get("/api/subscriptions/premium")
async def get_premium_users(
    user: Annotated[AdminUser, Depends(require_admin_role)],
) -> Dict[str, Any]:
    """Получение списка premium-пользователей."""
    async for session in db_manager.get_session():
        sub_repo = SubscriptionRepository(session)
        premium_users = await sub_repo.get_all_premium_users()
        return {
            "success": True,
            "users": [
                {
                    "id": u.id,
                    "telegram_id": u.telegram_id,
                    "source": u.source,
                    "username": u.username,
                    "full_name": u.full_name,
                    "subscription_until": u.subscription_until.isoformat()
                    if u.subscription_until
                    else None,
                }
                for u in premium_users
            ],
        }


@app.delete("/api/subscriptions/premium/{user_id}")
async def remove_premium_subscription(
    user_id: int,
    user: Annotated[AdminUser, Depends(require_superadmin_role)],
) -> Dict[str, Any]:
    """Снятие premium-подписки (superadmin)."""
    async for session in db_manager.get_session():
        sub_repo = SubscriptionRepository(session)
        success = await sub_repo.remove_premium_subscription(user_id)
        if not success:
            raise HTTPException(status_code=404, detail="Пользователь не найден")
        return {
            "success": True,
            "message": f"Premium-подписка снята с пользователя {user_id}",
        }


@app.get("/api/users/{user_id}/subscription")
async def get_user_subscription(
    user_id: int,
    user: Annotated[AdminUser, Depends(require_admin_role)],
) -> Dict[str, Any]:
    """Получение статуса подписки конкретного пользователя."""
    async for session in db_manager.get_session():
        sub_repo = SubscriptionRepository(session)
        sub_status = await sub_repo.get_subscription_status(user_id)
        payments = await sub_repo.get_user_payments(user_id)
        return {
            "success": True,
            "subscription": sub_status,
            "payments": [
                {
                    "id": p.id,
                    "amount": p.amount / 100,
                    "label": p.label,
                    "status": p.status,
                    "created_at": p.created_at.isoformat(),
                    "completed_at": p.completed_at.isoformat()
                    if p.completed_at
                    else None,
                }
                for p in payments
            ],
        }


# ===== YooKassa Webhook =====

_webhook_handler = None


def init_webhook_handler(bot) -> None:
    """Инициализация обработчика вебхуков YooKassa. Вызывается из main.py."""
    global _webhook_handler
    from coffee_oracle.services.webhook_handler import WebhookHandler

    _webhook_handler = WebhookHandler(bot)
    logger.info("Обработчик вебхуков YooKassa инициализирован")


@app.post("/api/yookassa/webhook")
async def yookassa_webhook(request: Request) -> JSONResponse:
    """Приём уведомлений от YooKassa."""
    from coffee_oracle.services.webhook_handler import is_yookassa_ip

    client_ip = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
    if not client_ip:
        client_ip = request.client.host if request.client else ""

    if not is_yookassa_ip(client_ip):
        logger.warning("Запрос вебхука с недоверенного IP: %s", client_ip)
        return JSONResponse(status_code=403, content={"error": "Forbidden"})

    try:
        body = await request.json()
    except Exception:
        return JSONResponse(status_code=400, content={"error": "Invalid JSON"})

    event_type = body.get("event")
    payment_object = body.get("object")

    if not event_type or not payment_object:
        return JSONResponse(
            status_code=400, content={"error": "Missing event or object"}
        )

    logger.info(
        "Получен вебхук YooKassa: event=%s, payment_id=%s",
        event_type,
        payment_object.get("id"),
    )

    if _webhook_handler is None:
        logger.error("Обработчик вебхуков не инициализирован")
        return JSONResponse(
            status_code=503, content={"error": "Service unavailable"}
        )

    result = await _webhook_handler.handle_notification(event_type, payment_object)

    return JSONResponse(status_code=200, content=result)
