#!/usr/bin/env python3
"""Тест исправления секции предсказаний."""

import requests
from requests.auth import HTTPBasicAuth

# Настройки
BASE_URL = "http://localhost:8000"
AUTH = HTTPBasicAuth("admin", "secret_pass")

def test_predictions_api():
    """Тест API предсказаний."""
    print("🔮 ТЕСТИРОВАНИЕ API ПРЕДСКАЗАНИЙ")
    print("=" * 35)
    
    try:
        response = requests.get(f"{BASE_URL}/api/predictions", auth=AUTH)
        
        if response.status_code == 200:
            print(f"   ✅ Статус: {response.status_code}")
            
            data = response.json()
            print(f"   ✅ Получено предсказаний: {len(data)}")
            
            if data:
                print("   📊 Примеры данных:")
                for i, prediction in enumerate(data[:2]):  # Показываем первые 2
                    print(f"      {i+1}. ID: {prediction['id']}")
                    print(f"         Пользователь: {prediction['user_name']}")
                    print(f"         Текст: {prediction['prediction_text'][:50]}...")
                    print(f"         Дата: {prediction['created_at']}")
                    print()
            
            return True
        else:
            print(f"   ❌ Статус: {response.status_code}")
            print(f"   ❌ Ответ: {response.text}")
            return False
            
    except Exception as e:
        print(f"   ❌ Ошибка: {e}")
        return False

def test_dashboard_sections():
    """Тест секций в дашборде."""
    print(f"\n🎨 ТЕСТИРОВАНИЕ СЕКЦИЙ ДАШБОРДА")
    print("=" * 35)
    
    try:
        response = requests.get(f"{BASE_URL}/", auth=AUTH)
        html = response.text
        
        sections = [
            ("users-section", "👥 Пользователи"),
            ("predictions-section", "🔮 Предсказания"),
            ("users-search", "Поиск пользователей"),
            ("predictions-search", "Поиск предсказаний"),
            ("users-table", "Таблица пользователей"),
            ("predictions-table", "Таблица предсказаний")
        ]
        
        all_found = True
        for section_id, description in sections:
            if section_id in html:
                print(f"   ✅ {description}: найдено")
            else:
                print(f"   ❌ {description}: не найдено")
                all_found = False
        
        return all_found
        
    except Exception as e:
        print(f"   ❌ Ошибка: {e}")
        return False

def test_javascript_functions():
    """Тест JavaScript функций."""
    print(f"\n⚡ ТЕСТИРОВАНИЕ JAVASCRIPT")
    print("=" * 25)
    
    try:
        response = requests.get(f"{BASE_URL}/", auth=AUTH)
        html = response.text
        
        js_functions = [
            ("loadUsers", "Загрузка пользователей"),
            ("loadPredictions", "Загрузка предсказаний"),
            ("renderUsersTable", "Отображение таблицы пользователей"),
            ("renderPredictionsTable", "Отображение таблицы предсказаний"),
            ("setupSearch", "Настройка поиска"),
            ("filterTable", "Фильтрация таблиц")
        ]
        
        all_found = True
        for func_name, description in js_functions:
            if func_name in html:
                print(f"   ✅ {description}: найдено")
            else:
                print(f"   ❌ {description}: не найдено")
                all_found = False
        
        return all_found
        
    except Exception as e:
        print(f"   ❌ Ошибка: {e}")
        return False

def test_navigation():
    """Тест навигации."""
    print(f"\n🔗 ТЕСТИРОВАНИЕ НАВИГАЦИИ")
    print("=" * 25)
    
    try:
        response = requests.get(f"{BASE_URL}/", auth=AUTH)
        html = response.text
        
        # Проверяем якорные ссылки
        anchor_links = [
            'href="#users-section"',
            'href="#predictions-section"'
        ]
        
        all_found = True
        for link in anchor_links:
            if link in html:
                print(f"   ✅ Якорная ссылка найдена: {link}")
            else:
                print(f"   ❌ Якорная ссылка не найдена: {link}")
                all_found = False
        
        return all_found
        
    except Exception as e:
        print(f"   ❌ Ошибка: {e}")
        return False

if __name__ == "__main__":
    try:
        print("🔮 ТЕСТИРОВАНИЕ ИСПРАВЛЕНИЯ СЕКЦИИ ПРЕДСКАЗАНИЙ")
        print("=" * 55)
        
        api_ok = test_predictions_api()
        sections_ok = test_dashboard_sections()
        js_ok = test_javascript_functions()
        nav_ok = test_navigation()
        
        print("\n" + "=" * 55)
        print("📋 РЕЗУЛЬТАТЫ ТЕСТИРОВАНИЯ:")
        print(f"🔮 API предсказаний: {'✅' if api_ok else '❌'}")
        print(f"🎨 Секции дашборда: {'✅' if sections_ok else '❌'}")
        print(f"⚡ JavaScript функции: {'✅' if js_ok else '❌'}")
        print(f"🔗 Навигация: {'✅' if nav_ok else '❌'}")
        
        if all([api_ok, sections_ok, js_ok, nav_ok]):
            print("\n🎉 СЕКЦИЯ ПРЕДСКАЗАНИЙ ИСПРАВЛЕНА!")
            print("🌐 Теперь:")
            print("   • Откройте http://localhost:8000/")
            print("   • Войдите с паролем admin/secret_pass")
            print("   • Прокрутите вниз до секции '🔮 Предсказания'")
            print("   • Или кликните ссылку '🔮 Предсказания' для прокрутки")
            print("   • Используйте поиск для фильтрации предсказаний")
            print("   • Кликайте кнопки 'Просмотр' и 'Удалить'")
        else:
            print("\n⚠️ Некоторые компоненты требуют внимания")
            
    except Exception as e:
        print(f"\n❌ Ошибка тестирования: {e}")
        print("Убедитесь, что контейнер запущен: docker compose up -d")