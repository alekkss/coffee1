#!/usr/bin/env python3
"""Тест безопасности Coffee Oracle Admin Panel после исправлений."""

import requests
from requests.auth import HTTPBasicAuth

# Настройки
BASE_URL = "http://localhost:8000"
AUTH = HTTPBasicAuth("admin", "secret_pass")

def test_admin_panels_disabled():
    """Тест что небезопасные админ-панели отключены."""
    print("🔒 ТЕСТИРОВАНИЕ БЕЗОПАСНОСТИ")
    print("=" * 30)
    
    unsafe_urls = [
        "/admin/user/list",
        "/admin/prediction/list",
        "/admin/user",
        "/admin/prediction",
        "/admin"
    ]
    
    all_secure = True
    
    for url in unsafe_urls:
        print(f"\n🔍 Проверяем: {url}")
        
        # Тест без авторизации
        response = requests.get(f"{BASE_URL}{url}")
        if response.status_code == 404:
            print(f"   ✅ Без авторизации: 404 (отключено)")
        elif response.status_code == 401:
            print(f"   ✅ Без авторизации: 401 (требует пароль)")
        else:
            print(f"   ❌ Без авторизации: {response.status_code} (небезопасно!)")
            all_secure = False
        
        # Тест с авторизацией
        response = requests.get(f"{BASE_URL}{url}", auth=AUTH)
        if response.status_code == 404:
            print(f"   ✅ С авторизацией: 404 (отключено)")
        else:
            print(f"   ⚠️ С авторизацией: {response.status_code}")
    
    return all_secure

def test_dashboard_access():
    """Тест доступа к дашборду."""
    print(f"\n🎨 ТЕСТИРОВАНИЕ ДАШБОРДА")
    print("=" * 25)
    
    # Без пароля - должен требовать авторизацию
    response = requests.get(f"{BASE_URL}/")
    if response.status_code == 401:
        print("   ✅ Без пароля: 401 (требует авторизацию)")
    else:
        print(f"   ❌ Без пароля: {response.status_code} (небезопасно!)")
        return False
    
    # С паролем - должен работать
    response = requests.get(f"{BASE_URL}/", auth=AUTH)
    if response.status_code == 200:
        print("   ✅ С паролем: 200 (доступ разрешен)")
        
        # Проверяем наличие новых секций
        html = response.text
        if "users-section" in html and "predictions-section" in html:
            print("   ✅ Новые секции найдены в дашборде")
        else:
            print("   ❌ Новые секции не найдены")
            return False
            
        return True
    else:
        print(f"   ❌ С паролем: {response.status_code}")
        return False

def test_api_endpoints():
    """Тест API endpoints."""
    print(f"\n📡 ТЕСТИРОВАНИЕ API")
    print("=" * 20)
    
    endpoints = [
        ("/api/dashboard", "KPI данные"),
        ("/api/analytics?period=24h", "Аналитика"),
        ("/api/retention", "Статистика"),
        ("/api/users", "Пользователи"),
        ("/health", "Статус системы")
    ]
    
    all_ok = True
    
    for endpoint, description in endpoints:
        print(f"\n🔍 {description}: {endpoint}")
        
        # Без пароля (кроме /health)
        if endpoint != "/health":
            response = requests.get(f"{BASE_URL}{endpoint}")
            if response.status_code == 401:
                print(f"   ✅ Без пароля: 401 (защищено)")
            else:
                print(f"   ❌ Без пароля: {response.status_code} (небезопасно!)")
                all_ok = False
        
        # С паролем
        auth_needed = AUTH if endpoint != "/health" else None
        response = requests.get(f"{BASE_URL}{endpoint}", auth=auth_needed)
        if response.status_code == 200:
            print(f"   ✅ С паролем: 200 (работает)")
        else:
            print(f"   ❌ С паролем: {response.status_code}")
            all_ok = False
    
    return all_ok

def test_navigation_links():
    """Тест навигационных ссылок."""
    print(f"\n🔗 ТЕСТИРОВАНИЕ НАВИГАЦИИ")
    print("=" * 25)
    
    response = requests.get(f"{BASE_URL}/", auth=AUTH)
    html = response.text
    
    # Проверяем что ссылки теперь ведут на якоря, а не на админ-панели
    expected_links = [
        'href="#users-section"',
        'href="#predictions-section"',
        'href="/health"'
    ]
    
    all_found = True
    for link in expected_links:
        if link in html:
            print(f"   ✅ Найдена безопасная ссылка: {link}")
        else:
            print(f"   ❌ Не найдена ссылка: {link}")
            all_found = False
    
    # Проверяем что старых небезопасных ссылок нет
    unsafe_links = [
        'href="/admin/user/list"',
        'href="/admin/prediction/list"'
    ]
    
    for link in unsafe_links:
        if link not in html:
            print(f"   ✅ Небезопасная ссылка удалена: {link}")
        else:
            print(f"   ❌ Найдена небезопасная ссылка: {link}")
            all_found = False
    
    return all_found

if __name__ == "__main__":
    try:
        print("🔮 ТЕСТИРОВАНИЕ БЕЗОПАСНОСТИ COFFEE ORACLE ADMIN PANEL")
        print("=" * 60)
        
        admin_secure = test_admin_panels_disabled()
        dashboard_ok = test_dashboard_access()
        api_ok = test_api_endpoints()
        nav_ok = test_navigation_links()
        
        print("\n" + "=" * 60)
        print("📋 РЕЗУЛЬТАТЫ ТЕСТИРОВАНИЯ БЕЗОПАСНОСТИ:")
        print(f"🔒 Админ-панели отключены: {'✅' if admin_secure else '❌'}")
        print(f"🎨 Дашборд защищен: {'✅' if dashboard_ok else '❌'}")
        print(f"📡 API защищено: {'✅' if api_ok else '❌'}")
        print(f"🔗 Навигация безопасна: {'✅' if nav_ok else '❌'}")
        
        if all([admin_secure, dashboard_ok, api_ok, nav_ok]):
            print("\n🎉 ВСЕ ПРОБЛЕМЫ БЕЗОПАСНОСТИ ИСПРАВЛЕНЫ!")
            print("🔐 Теперь:")
            print("   • Небезопасные админ-панели отключены")
            print("   • Все данные доступны только через защищенный дашборд")
            print("   • Все API требуют авторизацию")
            print("   • Навигация ведет на безопасные секции")
            print("\n🌐 Откройте http://localhost:8000/ и войдите с паролем!")
        else:
            print("\n⚠️ Обнаружены проблемы безопасности!")
            
    except Exception as e:
        print(f"\n❌ Ошибка тестирования: {e}")
        print("Убедитесь, что контейнер запущен: docker compose up -d")