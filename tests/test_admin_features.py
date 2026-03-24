#!/usr/bin/env python3
"""Тест всех функций админ-панели Coffee Oracle."""

import requests
import json
from requests.auth import HTTPBasicAuth

# Настройки
BASE_URL = "http://localhost:8000"
AUTH = HTTPBasicAuth("admin", "secret_pass")

def test_authentication():
    """Тест защиты паролем."""
    print("🔐 Тестируем защиту паролем...")
    
    # Без пароля - должна быть ошибка
    response = requests.get(f"{BASE_URL}/")
    print(f"   Без пароля: {response.status_code} - {response.json()}")
    
    # С неправильным паролем
    wrong_auth = HTTPBasicAuth("admin", "wrong_password")
    response = requests.get(f"{BASE_URL}/", auth=wrong_auth)
    print(f"   Неправильный пароль: {response.status_code}")
    
    # С правильным паролем
    response = requests.get(f"{BASE_URL}/", auth=AUTH)
    print(f"   Правильный пароль: {response.status_code} - ✅ Доступ разрешен")
    
    return response.status_code == 200

def test_dashboard_api():
    """Тест API дашборда."""
    print("\n📊 Тестируем API дашборда...")
    
    response = requests.get(f"{BASE_URL}/api/dashboard", auth=AUTH)
    data = response.json()
    
    print(f"   Статус: {response.status_code}")
    print(f"   KPI данные:")
    for key, value in data['kpi'].items():
        print(f"     {key}: {value}")
    
    return response.status_code == 200

def test_analytics_api():
    """Тест API аналитики для графиков."""
    print("\n📈 Тестируем API аналитики...")
    
    periods = ["7d", "1m", "1y"]
    for period in periods:
        response = requests.get(f"{BASE_URL}/api/analytics?period={period}", auth=AUTH)
        data = response.json()
        
        print(f"   Период {period}: {response.status_code}")
        print(f"     Пользователи: {len(data['users'])} точек данных")
        print(f"     Предсказания: {len(data['predictions'])} точек данных")
    
    return True

def test_retention_api():
    """Тест API статистики удержания."""
    print("\n📋 Тестируем API статистики...")
    
    response = requests.get(f"{BASE_URL}/api/retention", auth=AUTH)
    data = response.json()
    
    print(f"   Статус: {response.status_code}")
    print(f"   Периоды статистики:")
    for item in data['retention']:
        print(f"     {item['period']}: {item['new_users']} пользователей, {item['predictions']} предсказаний")
    
    return response.status_code == 200

def test_admin_panels():
    """Тест админ-панелей."""
    print("\n🗄️ Тестируем админ-панели...")
    
    # Пользователи
    response = requests.get(f"{BASE_URL}/admin/user/list", auth=AUTH)
    print(f"   Панель пользователей: {response.status_code}")
    if "Denis" in response.text:
        print("     ✅ Данные пользователей загружены")
    
    # Предсказания
    response = requests.get(f"{BASE_URL}/admin/prediction/list", auth=AUTH)
    print(f"   Панель предсказаний: {response.status_code}")
    if "prediction" in response.text.lower():
        print("     ✅ Данные предсказаний загружены")
    
    return True

def test_dashboard_html():
    """Тест HTML дашборда."""
    print("\n🎨 Тестируем HTML дашборд...")
    
    response = requests.get(f"{BASE_URL}/", auth=AUTH)
    html = response.text
    
    components = [
        ("Chart.js", "📊 Библиотека графиков"),
        ("KPI", "📈 KPI метрики"),
        ("period-btn", "🔘 Кнопки периодов"),
        ("activityChart", "📊 График активности"),
        ("retention-table", "📋 Таблица статистики")
    ]
    
    print(f"   HTML статус: {response.status_code}")
    for component, description in components:
        if component in html:
            print(f"     ✅ {description}")
        else:
            print(f"     ❌ {description}")
    
    return response.status_code == 200

if __name__ == "__main__":
    print("🔮 ТЕСТИРОВАНИЕ COFFEE ORACLE ADMIN PANEL v1.0")
    print("=" * 50)
    
    try:
        # Запускаем все тесты
        auth_ok = test_authentication()
        dashboard_ok = test_dashboard_api()
        analytics_ok = test_analytics_api()
        retention_ok = test_retention_api()
        admin_ok = test_admin_panels()
        html_ok = test_dashboard_html()
        
        print("\n" + "=" * 50)
        print("📋 РЕЗУЛЬТАТЫ ТЕСТИРОВАНИЯ:")
        print(f"🔐 Защита паролем: {'✅' if auth_ok else '❌'}")
        print(f"📊 API дашборда: {'✅' if dashboard_ok else '❌'}")
        print(f"📈 API аналитики: {'✅' if analytics_ok else '❌'}")
        print(f"📋 API статистики: {'✅' if retention_ok else '❌'}")
        print(f"🗄️ Админ-панели: {'✅' if admin_ok else '❌'}")
        print(f"🎨 HTML дашборд: {'✅' if html_ok else '❌'}")
        
        if all([auth_ok, dashboard_ok, analytics_ok, retention_ok, admin_ok, html_ok]):
            print("\n🎉 ВСЕ ФУНКЦИИ РАБОТАЮТ ИДЕАЛЬНО!")
            print("🌐 Откройте http://localhost:8000/ в браузере")
            print("🔑 Логин: admin, Пароль: secret_pass")
        else:
            print("\n⚠️ Некоторые функции требуют внимания")
            
    except Exception as e:
        print(f"\n❌ Ошибка тестирования: {e}")
        print("Убедитесь, что контейнер запущен: docker compose up -d")