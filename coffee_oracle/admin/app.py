"""FastAPI admin panel application."""

import logging
from datetime import datetime, timedelta
from typing import Annotated, Any, Dict, List

from fastapi import Depends, FastAPI, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from coffee_oracle.admin.auth import authenticate_admin
from coffee_oracle.config import config
from coffee_oracle.database.connection import db_manager
from coffee_oracle.database.models import Prediction, User
from coffee_oracle.database.repositories import PredictionRepository, SettingsRepository, UserRepository

# Create FastAPI app
app = FastAPI(title="Coffee Oracle Admin v1.0", version="1.0.0")

logger = logging.getLogger(__name__)

# Mount media files
app.mount("/media", StaticFiles(directory="/app/media"), name="media")

# Setup templates
templates = Jinja2Templates(directory="coffee_oracle/admin/templates")

# SQLAdmin отключен для безопасности - все данные теперь в защищенном дашборде


@app.get("/", response_class=HTMLResponse)
async def dashboard_page(
    request: Request,
    _: Annotated[str, Depends(authenticate_admin)]
) -> HTMLResponse:
    """Main dashboard page."""
    return templates.TemplateResponse("dashboard.html", {"request": request})


@app.get("/users", response_class=HTMLResponse)
async def users_page(
    request: Request,
    _: Annotated[str, Depends(authenticate_admin)]
) -> HTMLResponse:
    """Users list page."""
    return templates.TemplateResponse("users.html", {"request": request})


@app.get("/predictions", response_class=HTMLResponse)
async def predictions_page(
    request: Request,
    _: Annotated[str, Depends(authenticate_admin)]
) -> HTMLResponse:
    """Predictions list page."""
    return templates.TemplateResponse("predictions.html", {"request": request})


@app.get("/settings", response_class=HTMLResponse)
async def settings_page(
    request: Request,
    _: Annotated[str, Depends(authenticate_admin)]
) -> HTMLResponse:
    """Settings page."""
    return templates.TemplateResponse("settings.html", {"request": request})


@app.get("/api/dashboard")
async def dashboard_stats(
    _: Annotated[str, Depends(authenticate_admin)]
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
                    "created_at": prediction.created_at.isoformat()
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
    _: Annotated[str, Depends(authenticate_admin)]
) -> Dict[str, Any]:
    """Update bot settings."""
    try:
        data = await request.json()
        async for session in db_manager.get_session():
            settings_repo = SettingsRepository(session)
            
            updated = []
            for key, value in data.items():
                await settings_repo.set_setting(key, str(value))
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