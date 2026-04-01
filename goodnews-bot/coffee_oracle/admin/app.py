"""FastAPI admin panel application."""

import logging
from datetime import datetime, timedelta
from typing import Annotated, Any, Dict, List

from fastapi import Depends, FastAPI, Query, Request, status, HTTPException, Response
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from coffee_oracle.admin.auth import authenticate_admin, create_access_token
from coffee_oracle.config import config
from coffee_oracle.database.connection import db_manager
from pydantic import BaseModel, Field
import bcrypt
from sqlalchemy import select, delete
from coffee_oracle.database.models import Prediction, User, AdminUser
from coffee_oracle.database.repositories import PredictionRepository, SettingsRepository, SubscriptionRepository, UserRepository

# Create FastAPI app
app = FastAPI(title="Coffee Oracle Admin v2.0", version="2.0.0")

logger = logging.getLogger(__name__)

# Mount media files
app.mount("/media", StaticFiles(directory="/opt/goodnews-bot/media"), name="media")

# Setup templates
templates = Jinja2Templates(directory="coffee_oracle/admin/templates")

# SQLAdmin отключен для безопасности - все данные теперь в защищенном дашборде


@app.exception_handler(status.HTTP_401_UNAUTHORIZED)
async def unauthorized_exception_handler(request: Request, exc: HTTPException):
    """Redirect to login page if unauthorized and requesting HTML."""
    if "text/html" in request.headers.get("accept", ""):
        return RedirectResponse(url="/login")
    return JSONResponse(status_code=401, content={"detail": exc.detail})


class LoginRequest(BaseModel):
    username: str
    password: str


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    """Login page."""
    return templates.TemplateResponse("login.html", {"request": request})


@app.post("/login")
async def login(data: LoginRequest, response: Response):
    """Handle login and set JWT cookie."""
    async for session in db_manager.get_session():
        stmt = select(AdminUser).where(AdminUser.username == data.username)
        result = await session.execute(stmt)
        user = result.scalar_one_or_none()
        
        valid = False
        if user:
            try:
                if bcrypt.checkpw(data.password.encode('utf-8'), user.password_hash.encode('utf-8')):
                    valid = True
            except ValueError:
                pass
        
        if not valid:
            raise HTTPException(status_code=400, detail="Incorrect username or password")
            
        # Create token
        token = create_access_token(user.id, user.username)
        
        # Set cookie
        response.set_cookie(
            key="access_token",
            value=token,
            httponly=True,
            max_age=86400, # 24 hours
            secure=config.secure_cookies,
            samesite="lax"
        )
        
        return {"success": True}


@app.get("/", response_class=HTMLResponse)
async def dashboard_page(
    request: Request,
    user: Annotated[AdminUser, Depends(authenticate_admin)]
) -> HTMLResponse:
    """Main dashboard page."""
    return templates.TemplateResponse("dashboard.html", {"request": request, "user": user})


@app.get("/users", response_class=HTMLResponse)
async def users_page(
    request: Request,
    user: Annotated[AdminUser, Depends(authenticate_admin)]
) -> HTMLResponse:
    """Users list page."""
    return templates.TemplateResponse("users.html", {"request": request, "user": user})


@app.get("/predictions", response_class=HTMLResponse)
async def predictions_page(
    request: Request,
    user: Annotated[AdminUser, Depends(authenticate_admin)]
) -> HTMLResponse:
    """Predictions list page."""
    return templates.TemplateResponse("predictions.html", {"request": request, "user": user})


@app.get("/settings", response_class=HTMLResponse)
async def settings_page(
    request: Request,
    user: Annotated[AdminUser, Depends(authenticate_admin)]
) -> HTMLResponse:
    """Settings page."""
    if user.role != "superadmin":
        raise HTTPException(status_code=403, detail="Access denied")
    return templates.TemplateResponse("settings.html", {"request": request, "user": user})


@app.get("/subscriptions", response_class=HTMLResponse)
async def subscriptions_page(
    request: Request,
    user: Annotated[AdminUser, Depends(authenticate_admin)]
) -> HTMLResponse:
    """Subscriptions management page."""
    return templates.TemplateResponse("subscriptions.html", {"request": request, "user": user})


@app.get("/logout")
async def logout(response: Response):
    """Logout endpoint to clear cookie."""
    response.delete_cookie(key="access_token")
    # Return a page that redirects, or use 302
    return RedirectResponse(url="/login")


@app.get("/terms", response_class=HTMLResponse)
async def terms_page(request: Request):
    """Public terms of service page."""
    async for session in db_manager.get_session():
        settings_repo = SettingsRepository(session)
        text = await settings_repo.get_setting("terms_text")
    return templates.TemplateResponse("legal_page.html", {
        "request": request,
        "title": "Условия использования",
        "content": text or ""
    })


@app.get("/privacy", response_class=HTMLResponse)
async def privacy_page(request: Request):
    """Public privacy policy page."""
    async for session in db_manager.get_session():
        settings_repo = SettingsRepository(session)
        text = await settings_repo.get_setting("privacy_text")
    return templates.TemplateResponse("legal_page.html", {
        "request": request,
        "title": "Политика конфиденциальности",
        "content": text or ""
    })


@app.get("/api/dashboard")
async def dashboard_stats(
    _: Annotated[AdminUser, Depends(authenticate_admin)]
) -> Dict[str, Any]:
    """Get dashboard statistics."""
    async for session in db_manager.get_session():
        user_repo = UserRepository(session)
        prediction_repo = PredictionRepository(session)
        
        # Get basic statistics
        total_users = await user_repo.get_users_count()
        new_users_today = await user_repo.get_new_users_count(hours=24)
        total_predictions = await prediction_repo.get_predictions_count()
        predictions_today = await prediction_repo.get_predictions_count_since(hours=24)
        
        return {
            "kpi": {
                "total_users": total_users,
                "new_users_today": new_users_today,
                "total_predictions": total_predictions,
                "predictions_today": predictions_today
            },
            "timestamp": datetime.utcnow().isoformat()
        }


@app.get("/api/analytics")
async def analytics_data(
    period: str = Query("24h", regex="^(24h|7d|4w|12m)$"),
    _: Annotated[str, Depends(authenticate_admin)] = None
) -> Dict[str, Any]:
    """Get analytics data for charts."""
    async for session in db_manager.get_session():
        user_repo = UserRepository(session)
        prediction_repo = PredictionRepository(session)
        
        # Determine date range and grouping
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
        
        # Get time series data
        users_data = await user_repo.get_users_time_series(hours_back, group_by)
        predictions_data = await prediction_repo.get_predictions_time_series(hours_back, group_by)
        
        return {
            "period": period,
            "users": users_data,
            "predictions": predictions_data,
            "timestamp": datetime.utcnow().isoformat()
        }


@app.get("/api/retention")
async def retention_stats(
    _: Annotated[str, Depends(authenticate_admin)]
) -> Dict[str, Any]:
    """Get retention statistics table."""
    async for session in db_manager.get_session():
        user_repo = UserRepository(session)
        prediction_repo = PredictionRepository(session)
        
        # Calculate stats for different periods
        periods = [
            ("today", 1),
            ("this_week", 7),
            ("this_month", 30),
            ("all_time", None)
        ]
        
        retention_data = []
        for period_name, days in periods:
            if days:
                new_users = await user_repo.get_new_users_count(hours=days * 24)
                predictions = await prediction_repo.get_predictions_count_since(hours=days * 24)
            else:
                new_users = await user_repo.get_users_count()
                predictions = await prediction_repo.get_predictions_count()
            
            retention_data.append({
                "period": period_name.replace("_", " ").title(),
                "new_users": new_users,
                "predictions": predictions
            })
        
        return {"retention": retention_data}


@app.get("/api/users")
async def get_users(
    _: Annotated[str, Depends(authenticate_admin)]
) -> List[Dict[str, Any]]:
    """Get users list with prediction counts."""
    try:
        async for session in db_manager.get_session():
            user_repo = UserRepository(session)
            prediction_repo = PredictionRepository(session)
            users = await user_repo.get_all_users()
            
            result = []
            for user in users:
                pred_count = await prediction_repo.get_user_predictions_count(user.id)
                result.append({
                    "id": user.id,
                    "telegram_id": user.telegram_id,
                    "username": user.username,
                    "full_name": user.full_name,
                    "subscription_type": user.subscription_type or "free",
                    "subscription_until": user.subscription_until.isoformat() if user.subscription_until else None,
                    "created_at": user.created_at.isoformat(),
                    "predictions_count": pred_count
                })
            
            return result
    except Exception as e:
        logger.error("Error in users endpoint: %s", e)
        return []


@app.get("/api/predictions")
async def get_predictions(
    _: Annotated[str, Depends(authenticate_admin)]
) -> List[Dict[str, Any]]:
    """Get predictions list."""
    try:
        async for session in db_manager.get_session():
            prediction_repo = PredictionRepository(session)
            predictions = await prediction_repo.get_all_predictions_with_users()
            
            return [
                {
                    "id": prediction.id,
                    "user_id": prediction.user_id,
                    "user_name": prediction.user.full_name if prediction.user else "Unknown",
                    "prediction_text": prediction.prediction_text,
                    "user_request": prediction.user_request,
                    "photo_path": prediction.photo_path,
                    "photos": [{"id": p.id, "file_path": p.file_path} for p in prediction.photos] if prediction.photos else [],
                    "created_at": prediction.created_at.isoformat(),
                    "subscription_type": prediction.subscription_type or "free"
                }
                for prediction in predictions
            ]
    except Exception as e:
        logger.error("Error in predictions endpoint: %s", e)
        return []


@app.get("/health")
async def health_check() -> Dict[str, str]:
    """Health check endpoint."""
    return {"status": "healthy", "timestamp": datetime.utcnow().isoformat()}


# --- YooKassa Webhook ---

# Lazy-initialized webhook handler (needs bot instance)
_webhook_handler = None


def init_webhook_handler(bot) -> None:
    """Initialize webhook handler with bot instance. Called from main.py."""
    global _webhook_handler
    from coffee_oracle.services.webhook_handler import WebhookHandler
    _webhook_handler = WebhookHandler(bot)
    logger.info("YooKassa webhook handler initialized")


@app.post("/api/yookassa/webhook")
async def yookassa_webhook(request: Request) -> JSONResponse:
    """Handle YooKassa payment notifications.

    YooKassa sends POST with JSON body:
    {
        "type": "notification",
        "event": "payment.succeeded",
        "object": { ... payment data ... }
    }
    """
    from coffee_oracle.services.webhook_handler import is_yookassa_ip

    # 1. Verify source IP
    client_ip = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
    if not client_ip:
        client_ip = request.client.host if request.client else ""

    if not is_yookassa_ip(client_ip):
        logger.warning("Webhook request from untrusted IP: %s", client_ip)
        return JSONResponse(status_code=403, content={"error": "Forbidden"})

    # 2. Parse body
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(status_code=400, content={"error": "Invalid JSON"})

    event_type = body.get("event")
    payment_object = body.get("object")

    if not event_type or not payment_object:
        return JSONResponse(status_code=400, content={"error": "Missing event or object"})

    logger.info("Received YooKassa webhook: event=%s, payment_id=%s",
                event_type, payment_object.get("id"))

    # 3. Process
    if _webhook_handler is None:
        logger.error("Webhook handler not initialized")
        return JSONResponse(status_code=503, content={"error": "Service unavailable"})

    result = await _webhook_handler.handle_notification(event_type, payment_object)

    # YooKassa expects 200 to confirm receipt
    return JSONResponse(status_code=200, content=result)


@app.get("/api/settings")
async def get_settings(
    _: Annotated[str, Depends(authenticate_admin)]
) -> Dict[str, Any]:
    """Get all bot settings."""
    async for session in db_manager.get_session():
        settings_repo = SettingsRepository(session)
        settings = await settings_repo.get_all_settings()
        return {"settings": settings}


@app.post("/api/settings")
async def update_settings(
    request: Request,
    user: Annotated[AdminUser, Depends(authenticate_admin)]
) -> Dict[str, Any]:
    """Update bot settings."""
    try:
        data = await request.json()
        async for session in db_manager.get_session():
            settings_repo = SettingsRepository(session)
            
            updated = []
            for key, value in data.items():
                await settings_repo.set_setting(key, str(value), updated_by=user.username)
                updated.append(key)
            
            return {"success": True, "updated": updated}
    except Exception as e:
        logger.error("Error updating settings: %s", e)
        return {"success": False, "error": str(e)}


@app.post("/api/settings/reset")
async def reset_settings(
    _: Annotated[str, Depends(authenticate_admin)]
) -> Dict[str, Any]:
    """Reset all settings to defaults."""
    try:
        async for session in db_manager.get_session():
            settings_repo = SettingsRepository(session)
            await settings_repo.reset_to_defaults()
            
            # Clear LLM settings cache
            from coffee_oracle.services.openai_client import clear_settings_cache
            clear_settings_cache()
            
            return {"success": True, "message": "Settings reset to defaults"}
    except Exception as e:
        logger.error("Error resetting settings: %s", e)
        return {"success": False, "error": str(e)}


@app.post("/api/settings/clear-cache")
async def clear_cache(
    _: Annotated[str, Depends(authenticate_admin)]
) -> Dict[str, Any]:
    """Clear settings cache to apply changes immediately."""
    try:
        from coffee_oracle.services.openai_client import clear_settings_cache
        clear_settings_cache()
        return {"success": True, "message": "Cache cleared"}
    except Exception as e:
        logger.error("Error clearing cache: %s", e)
        return {"success": False, "error": str(e)}


# --- Admin User Management ---

class AdminUsercreate(BaseModel):
    username: str = Field(..., min_length=3, max_length=50)
    password: str = Field(..., min_length=6)
    role: str = Field("restricted", pattern="^(superadmin|restricted)$")


@app.get("/admins", response_class=HTMLResponse)
async def admins_page(
    request: Request,
    user: Annotated[AdminUser, Depends(authenticate_admin)]
) -> HTMLResponse:
    """Admins management page - temporarily redirected."""
    # TODO: Remove redirect when ready to enable admin management
    return RedirectResponse(url="/", status_code=302)
    # if user.role != "superadmin":
    #     raise HTTPException(status_code=403, detail="Access denied")
    # return templates.TemplateResponse("admins.html", {"request": request, "user": user})


@app.get("/api/admin-users")
async def get_admin_users(
    user: Annotated[AdminUser, Depends(authenticate_admin)]
) -> List[Dict[str, Any]]:
    """Get list of admin users."""
    if user.role != "superadmin":
        raise HTTPException(status_code=403, detail="Access denied")
        
    async for session in db_manager.get_session():
        stmt = select(AdminUser).order_by(AdminUser.created_at.desc())
        result = await session.execute(stmt)
        admins = result.scalars().all()
        
        return [
            {
                "id": a.id,
                "username": a.username,
                "role": a.role,
                "created_at": a.created_at.isoformat()
            }
            for a in admins
        ]


@app.post("/api/admin-users")
async def create_admin_user(
    data: AdminUsercreate,
    user: Annotated[AdminUser, Depends(authenticate_admin)]
) -> Dict[str, Any]:
    """Create a new admin user."""
    if user.role != "superadmin":
        raise HTTPException(status_code=403, detail="Access denied")
        
    async for session in db_manager.get_session():
        # Check specific user existence
        stmt = select(AdminUser).where(AdminUser.username == data.username)
        result = await session.execute(stmt)
        if result.scalar_one_or_none():
             raise HTTPException(status_code=400, detail="Username already exists")
        
        hashed_bytes = bcrypt.hashpw(
            data.password.encode('utf-8'), 
            bcrypt.gensalt()
        )
        
        new_admin = AdminUser(
            username=data.username,
            password_hash=hashed_bytes.decode('utf-8'),
            role=data.role
        )
        session.add(new_admin)
        try:
            await session.commit()
            return {"success": True, "message": f"User {data.username} created"}
        except Exception as e:
            await session.rollback()
            raise HTTPException(status_code=500, detail=str(e))


@app.delete("/api/admin-users/{user_id}")
async def delete_admin_user(
    user_id: int,
    user: Annotated[AdminUser, Depends(authenticate_admin)]
) -> Dict[str, Any]:
    """Delete an admin user."""
    if user.role != "superadmin":
        raise HTTPException(status_code=403, detail="Access denied")
        
    if user.id == user_id:
        raise HTTPException(status_code=400, detail="Cannot delete your own account")
        
    async for session in db_manager.get_session():
        stmt = select(AdminUser).where(AdminUser.id == user_id)
        result = await session.execute(stmt)
        admin_to_delete = result.scalar_one_or_none()
        
        if not admin_to_delete:
            raise HTTPException(status_code=404, detail="User not found")
            
        await session.delete(admin_to_delete)
        await session.commit()
        return {"success": True, "message": "User deleted"}


# ===== Subscription Management Endpoints =====

class VipStatusRequest(BaseModel):
    """Request model for setting VIP status."""
    user_id: int
    reason: str = Field(..., min_length=1, max_length=255)


class PaymentCompleteRequest(BaseModel):
    """Request model for completing a payment."""
    label: str


@app.get("/api/subscriptions/stats")
async def get_subscription_stats(
    user: Annotated[AdminUser, Depends(authenticate_admin)]
) -> Dict[str, Any]:
    """Get subscription statistics."""
    async for session in db_manager.get_session():
        sub_repo = SubscriptionRepository(session)
        stats = await sub_repo.get_subscription_stats()
        return {"success": True, "stats": stats}


@app.get("/api/subscriptions/vip")
async def get_vip_users(
    user: Annotated[AdminUser, Depends(authenticate_admin)]
) -> Dict[str, Any]:
    """Get all VIP users."""
    async for session in db_manager.get_session():
        sub_repo = SubscriptionRepository(session)
        vip_users = await sub_repo.get_all_vip_users()
        return {
            "success": True,
            "users": [
                {
                    "id": u.id,
                    "telegram_id": u.telegram_id,
                    "username": u.username,
                    "full_name": u.full_name,
                    "vip_reason": u.vip_reason
                }
                for u in vip_users
            ]
        }


@app.post("/api/subscriptions/vip")
async def set_vip_status(
    request: VipStatusRequest,
    user: Annotated[AdminUser, Depends(authenticate_admin)]
) -> Dict[str, Any]:
    """Set VIP status for a user."""
    if user.role != "superadmin":
        raise HTTPException(status_code=403, detail="Access denied")
    
    async for session in db_manager.get_session():
        sub_repo = SubscriptionRepository(session)
        success = await sub_repo.set_vip_status(request.user_id, request.reason)
        if not success:
            raise HTTPException(status_code=404, detail="User not found")
        return {"success": True, "message": f"VIP status set for user {request.user_id}"}


@app.delete("/api/subscriptions/vip/{user_id}")
async def remove_vip_status(
    user_id: int,
    user: Annotated[AdminUser, Depends(authenticate_admin)]
) -> Dict[str, Any]:
    """Remove VIP status from a user."""
    if user.role != "superadmin":
        raise HTTPException(status_code=403, detail="Access denied")
    
    async for session in db_manager.get_session():
        sub_repo = SubscriptionRepository(session)
        success = await sub_repo.remove_vip_status(user_id)
        if not success:
            raise HTTPException(status_code=404, detail="User not found")
        return {"success": True, "message": f"VIP status removed from user {user_id}"}


@app.post("/api/subscriptions/complete-payment")
async def complete_payment(
    request: PaymentCompleteRequest,
    user: Annotated[AdminUser, Depends(authenticate_admin)]
) -> Dict[str, Any]:
    """Manually complete a payment."""
    if user.role != "superadmin":
        raise HTTPException(status_code=403, detail="Access denied")
    
    async for session in db_manager.get_session():
        sub_repo = SubscriptionRepository(session)
        success = await sub_repo.complete_payment(request.label)
        if not success:
            raise HTTPException(status_code=404, detail="Payment not found or already completed")
        return {"success": True, "message": f"Payment {request.label} completed"}


@app.get("/api/subscriptions/premium")
async def get_premium_users(
    user: Annotated[AdminUser, Depends(authenticate_admin)]
) -> Dict[str, Any]:
    """Get all premium users."""
    async for session in db_manager.get_session():
        sub_repo = SubscriptionRepository(session)
        premium_users = await sub_repo.get_all_premium_users()
        return {
            "success": True,
            "users": [
                {
                    "id": u.id,
                    "telegram_id": u.telegram_id,
                    "username": u.username,
                    "full_name": u.full_name,
                    "subscription_until": u.subscription_until.isoformat() if u.subscription_until else None
                }
                for u in premium_users
            ]
        }

@app.delete("/api/subscriptions/premium/{user_id}")
async def remove_premium_subscription(
    user_id: int,
    user: Annotated[AdminUser, Depends(authenticate_admin)]
) -> Dict[str, Any]:
    """Remove premium subscription from a user."""
    if user.role != "superadmin":
        raise HTTPException(status_code=403, detail="Access denied")

    async for session in db_manager.get_session():
        sub_repo = SubscriptionRepository(session)
        success = await sub_repo.remove_premium_subscription(user_id)
        if not success:
            raise HTTPException(status_code=404, detail="User not found")
        return {"success": True, "message": f"Premium subscription removed from user {user_id}"}



@app.get("/api/users/{user_id}/subscription")
async def get_user_subscription(
    user_id: int,
    user: Annotated[AdminUser, Depends(authenticate_admin)]
) -> Dict[str, Any]:
    """Get subscription status for a specific user."""
    async for session in db_manager.get_session():
        sub_repo = SubscriptionRepository(session)
        status = await sub_repo.get_subscription_status(user_id)
        payments = await sub_repo.get_user_payments(user_id)
        return {
            "success": True,
            "subscription": status,
            "payments": [
                {
                    "id": p.id,
                    "amount": p.amount / 100,  # Convert kopecks to rubles for display
                    "label": p.label,
                    "status": p.status,
                    "created_at": p.created_at.isoformat(),
                    "completed_at": p.completed_at.isoformat() if p.completed_at else None
                }
                for p in payments
            ]
        }