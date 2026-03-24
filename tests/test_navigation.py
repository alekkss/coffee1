#!/usr/bin/env python3
"""Тест навигационных ссылок Coffee Oracle Admin Panel."""

import requests
from requests.auth import HTTPBasicAuth

# Настройки
BASE_URL = "http://localhost:8000"
AUTH = HTTPBasicAuth("admin", "secret_pass")

def test_navigation_links():
    """Тест всех навигационных ссылок."""
    print("🔗 ТЕСТИРОВАНИЕ НАВИГАЦИОННЫХ ССЫЛОК")
    print("=" * 50)
    
    links = [
        ("Главная страница", "/", "Coffee Oracle Admin Dashboard"),
        ("Пользователи", "/admin/user/list", "Users"),
        ("Предсказания", "/admin/prediction/list", "Predictions"),
        ("Статус системы", "/health", "healthy")
    ]
    
    all_ok = True
    
    for name, url, expected_text in links:
        print(f"\n🔍 Тестируем: {name}")
        print(f"   URL: {url}")
        
        try:
            response = requests.get(f"{BASE_URL}{url}", auth=AUTH)
            
            if response.status_code == 200:
                print(f"   ✅ Статус: {response.status_code}")
                
                if expected_text in response.text:
                    print(f"   ✅ Содержимое корректно (найдено: '{expected_text}')")
                else:
                    print(f"   ⚠️ Ожидаемый текст '{expected_text}' не найден")
                    all_ok = False
            else:
                print(f"   ❌ Статус: {response.status_code}")
                all_ok = False
                
        except Exception as e:
            print(f"   ❌ Ошибка: {e}")
            all_ok = False
    
    return all_ok

def test_dashboard_links():
    """Тест ссылок в HTML дашборда."""
    print(f"\n🎨 ТЕСТИРОВАНИЕ ССЫЛОК В ДАШБОРДЕ")
    print("=" * 35)
    
    try:
        response = requests.get(f"{BASE_URL}/", auth=AUTH)
        html = response.text
        
        expected_links = [
            ("/admin/user/list", "👥 Пользователи"),
            ("/admin/prediction/list", "🔮 Предсказания"),
            ("/health", "🏥 Статус системы")
        ]
        
        all_found = True
        
        for href, text in expected_links:
            if f'href="{href}"' in html and text in html:
                print(f"   ✅ Ссылка '{text}' найдена: {href}")
            else:
                print(f"   ❌ Ссылка '{text}' не найдена или неправильная")
                all_found = False
        
        return all_found
        
    except Exception as e:
        print(f"   ❌ Ошибка: {e}")
        return False

def test_click_through():
    """Тест переходов по ссылкам."""
    print(f"\n🖱️ ТЕСТИРОВАНИЕ ПЕРЕХОДОВ")
    print("=" * 25)
    
    # Начинаем с главной страницы
    print("   1. Открываем главную страницу...")
    response = requests.get(f"{BASE_URL}/", auth=AUTH)
    if response.status_code == 200:
        print("      ✅ Главная страница загружена")
    else:
        print("      ❌ Ошибка загрузки главной страницы")
        return False
    
    # Переходим к пользователям
    print("   2. Переходим к списку пользователей...")
    response = requests.get(f"{BASE_URL}/admin/user/list", auth=AUTH)
    if response.status_code == 200 and "Users" in response.text:
        print("      ✅ Страница пользователей загружена")
    else:
        print("      ❌ Ошибка загрузки страницы пользователей")
        return False
    
    # Переходим к предсказаниям
    print("   3. Переходим к списку предсказаний...")
    response = requests.get(f"{BASE_URL}/admin/prediction/list", auth=AUTH)
    if response.status_code == 200 and "Predictions" in response.text:
        print("      ✅ Страница предсказаний загружена")
    else:
        print("      ❌ Ошибка загрузки страницы предсказаний")
        return False
    
    # Проверяем статус системы
    print("   4. Проверяем статус системы...")
    response = requests.get(f"{BASE_URL}/health", auth=AUTH)
    if response.status_code == 200 and "healthy" in response.text:
        print("      ✅ Статус системы: healthy")
    else:
        print("      ❌ Ошибка проверки статуса")
        return False
    
    return True

if __name__ == "__main__":
    try:
        print("🔮 ТЕСТИРОВАНИЕ НАВИГАЦИИ COFFEE ORACLE ADMIN PANEL")
        print("=" * 55)
        
        links_ok = test_navigation_links()
        dashboard_ok = test_dashboard_links()
        clickthrough_ok = test_click_through()
        
        print("\n" + "=" * 55)
        print("📋 РЕЗУЛЬТАТЫ ТЕСТИРОВАНИЯ:")
        print(f"🔗 Навигационные ссылки: {'✅' if links_ok else '❌'}")
        print(f"🎨 Ссылки в дашборде: {'✅' if dashboard_ok else '❌'}")
        print(f"🖱️ Переходы по ссылкам: {'✅' if clickthrough_ok else '❌'}")
        
        if all([links_ok, dashboard_ok, clickthrough_ok]):
            print("\n🎉 ВСЕ НАВИГАЦИОННЫЕ ССЫЛКИ РАБОТАЮТ!")
            print("🌐 Теперь вы можете:")
            print("   • Открыть http://localhost:8000/")
            print("   • Кликнуть '👥 Пользователи' - откроется список пользователей")
            print("   • Кликнуть '🔮 Предсказания' - откроется список предсказаний")
            print("   • Кликнуть '🏥 Статус системы' - откроется статус")
        else:
            print("\n⚠️ Некоторые ссылки требуют внимания")
            
    except Exception as e:
        print(f"\n❌ Ошибка тестирования: {e}")
        print("Убедитесь, что контейнер запущен: docker compose up -d")