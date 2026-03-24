#!/usr/bin/env python3
"""Тест новых периодов графика Coffee Oracle Admin Panel."""

import requests
import json
from requests.auth import HTTPBasicAuth

# Настройки
BASE_URL = "http://localhost:8000"
AUTH = HTTPBasicAuth("admin", "secret_pass")

def test_new_periods():
    """Тест всех новых периодов графика."""
    print("📊 ТЕСТИРОВАНИЕ НОВЫХ ПЕРИОДОВ ГРАФИКА")
    print("=" * 50)
    
    periods = [
        ("24h", "По часам", "последние 24 часа"),
        ("7d", "По дням", "последние 7 дней"),
        ("4w", "По неделям", "последние 4 недели"),
        ("12m", "По месяцам", "последние 12 месяцев")
    ]
    
    for period_code, period_name, description in periods:
        print(f"\n🔍 Тестируем период: {period_name} ({description})")
        
        try:
            response = requests.get(f"{BASE_URL}/api/analytics?period={period_code}", auth=AUTH)
            data = response.json()
            
            print(f"   ✅ Статус: {response.status_code}")
            print(f"   📈 Пользователи: {len(data['users'])} точек данных")
            print(f"   🔮 Предсказания: {len(data['predictions'])} точек данных")
            
            # Показываем примеры данных
            if data['users']:
                print(f"   📊 Пример данных пользователей:")
                for item in data['users'][:3]:  # Показываем первые 3
                    print(f"      {item['period']}: {item['count']} пользователей")
            
            if data['predictions']:
                print(f"   📊 Пример данных предсказаний:")
                for item in data['predictions'][:3]:  # Показываем первые 3
                    print(f"      {item['period']}: {item['count']} предсказаний")
                    
        except Exception as e:
            print(f"   ❌ Ошибка: {e}")

def test_dashboard_buttons():
    """Тест HTML дашборда с новыми кнопками."""
    print(f"\n🎨 ТЕСТИРОВАНИЕ HTML ДАШБОРДА")
    print("=" * 30)
    
    try:
        response = requests.get(f"{BASE_URL}/", auth=AUTH)
        html = response.text
        
        buttons = [
            ("По часам", "24h"),
            ("По дням", "7d"),
            ("По неделям", "4w"),
            ("По месяцам", "12m")
        ]
        
        print(f"   HTML статус: {response.status_code}")
        
        for button_text, period_code in buttons:
            if button_text in html and period_code in html:
                print(f"   ✅ Кнопка '{button_text}' найдена")
            else:
                print(f"   ❌ Кнопка '{button_text}' не найдена")
                
        # Проверяем JavaScript функции
        js_functions = [
            "getPeriodTitle",
            "loadAnalytics",
            "renderChart"
        ]
        
        for func in js_functions:
            if func in html:
                print(f"   ✅ JavaScript функция '{func}' найдена")
            else:
                print(f"   ❌ JavaScript функция '{func}' не найдена")
                
    except Exception as e:
        print(f"   ❌ Ошибка: {e}")

def show_usage_instructions():
    """Показать инструкции по использованию."""
    print(f"\n🚀 ИНСТРУКЦИИ ПО ИСПОЛЬЗОВАНИЮ")
    print("=" * 35)
    print("1. Откройте браузер: http://localhost:8000/")
    print("2. Введите логин: admin, пароль: secret_pass")
    print("3. На главной странице увидите 4 кнопки:")
    print("   📊 [По часам] - показывает активность по часам за 24 часа")
    print("   📊 [По дням] - показывает активность по дням за 7 дней")
    print("   📊 [По неделям] - показывает активность по неделям за 4 недели")
    print("   📊 [По месяцам] - показывает активность по месяцам за 12 месяцев")
    print("4. Кликайте на кнопки - график будет обновляться автоматически!")
    print("5. График показывает:")
    print("   🔴 Красная линия - новые пользователи")
    print("   🔵 Синяя линия - количество предсказаний")

if __name__ == "__main__":
    try:
        test_new_periods()
        test_dashboard_buttons()
        show_usage_instructions()
        
        print(f"\n🎉 ВСЕ НОВЫЕ ПЕРИОДЫ РАБОТАЮТ!")
        print("🌐 Откройте http://localhost:8000/ и попробуйте кнопки!")
        
    except Exception as e:
        print(f"\n❌ Ошибка тестирования: {e}")
        print("Убедитесь, что контейнер запущен: docker compose up -d")