# Coffee Oracle Bot 🔮☕

Развлекательный Telegram-бот, который анализирует фотографии кофейной гущи с помощью ИИ и предоставляет позитивные, вдохновляющие предсказания.

## Возможности

- 🔮 Анализ фотографий кофейной гущи с помощью OpenAI Vision API
- ✨ Только позитивные и вдохновляющие предсказания
- 📜 История предсказаний пользователя (последние 5)
- 🎛️ Веб-админ панель для управления и мониторинга
- 🐳 Простое развертывание через Docker Compose

## Технологический стек

- **Python 3.11+**
- **aiogram 3.x** - современный фреймворк для Telegram ботов
- **LiteLLM** - унифицированный интерфейс для различных LLM провайдеров (OpenAI, Azure, Anthropic, Google и др.)
- **SQLAlchemy + SQLite** - база данных
- **FastAPI + SQLAdmin** - веб-админ панель
- **Docker + Docker Compose** - контейнеризация

## Быстрый старт

### 1. Клонирование репозитория

```bash
git clone <repository-url>
cd coffee-oracle-bot
```

### 2. Настройка окружения

Скопируйте файл с примером переменных окружения:

```bash
cp .env.example .env
```

Отредактируйте `.env` файл, указав ваши данные:

```bash
BOT_TOKEN=your_telegram_bot_token_here
LITELLM_MODEL=gpt-4o-mini
LITELLM_API_KEY=your_openai_api_key_here
ADMIN_USERNAME=admin
ADMIN_PASSWORD=your_secure_password_here
DB_NAME=coffee_oracle.db
```

### 3. Получение токенов

**Telegram Bot Token:**
1. Напишите [@BotFather](https://t.me/botfather) в Telegram
2. Создайте нового бота командой `/newbot`
3. Следуйте инструкциям и получите токен

**LiteLLM API Key:**
1. Зарегистрируйтесь у любого поддерживаемого провайдера:
   - [OpenAI Platform](https://platform.openai.com/) (рекомендуется)
   - [Azure OpenAI Service](https://azure.microsoft.com/en-us/products/ai-services/openai-service)
   - [Anthropic](https://www.anthropic.com/)
   - [Google AI Studio](https://makersuite.google.com/)
2. Создайте API ключ
3. Настройте модель в `.env` файле (см. [документацию LiteLLM](docs/LITELLM_CONFIGURATION.md))

### 4. Запуск через Docker Compose

```bash
docker compose up -d
```

Бот автоматически запустится и будет доступен в Telegram, а админ-панель будет доступна по адресу `http://localhost:8000/admin`.

## Использование

### Telegram Bot

1. Найдите вашего бота в Telegram и нажмите `/start`
2. Выпейте кофе, оставив немного гущи на дне чашки
3. Сфотографируйте дно чашки сверху
4. Отправьте фото боту
5. Получите позитивное предсказание! ✨

### Админ-панель

Откройте `http://localhost:8000/admin` в браузере и войдите, используя логин и пароль из `.env` файла.

**Доступные разделы:**
- 📊 Дашборд со статистикой
- 👥 Управление пользователями
- 🔮 История предсказаний
- 🔍 Поиск по пользователям

## Конфигурация LiteLLM

Система поддерживает множество LLM провайдеров через LiteLLM. Подробная документация: [LITELLM_CONFIGURATION.md](docs/LITELLM_CONFIGURATION.md)

### Быстрая настройка для разных провайдеров:

**OpenAI (по умолчанию):**
```bash
LITELLM_MODEL=gpt-4o-mini
LITELLM_API_KEY=sk-proj-your-openai-key
```

**Azure OpenAI:**
```bash
LITELLM_MODEL=azure/gpt-4o-mini
LITELLM_API_KEY=your-azure-key
LITELLM_API_BASE=https://your-resource.openai.azure.com/
LITELLM_API_VERSION=2023-12-01-preview
```

**Anthropic Claude:**
```bash
LITELLM_MODEL=claude-3-sonnet-20240229
LITELLM_API_KEY=sk-ant-your-anthropic-key
```

**Тестирование конфигурации:**
```bash
python scripts/test_litellm_integration.py
```

## Разработка

### Локальная разработка

```bash
# Создание виртуального окружения
python -m venv venv
source venv/bin/activate  # Linux/Mac
# или
venv\Scripts\activate  # Windows

# Установка зависимостей
pip install -r requirements.txt

# Запуск приложения
python main.py
```

### Структура проекта

```
coffee-oracle-bot/
├── coffee_oracle/          # Основной пакет приложения
│   ├── bot/                # Telegram бот
│   ├── admin/              # Админ-панель
│   ├── database/           # Модели и репозитории БД
│   ├── services/           # Сервисы (OpenAI, обработка фото)
│   └── config.py           # Конфигурация
├── docs/                   # Документация проекта
├── scripts/                # Утилиты и скрипты
├── tests/                  # Тесты приложения
├── db_data/                # База данных SQLite
├── logs/                   # Логи приложения
├── main.py                 # Точка входа приложения
├── requirements.txt        # Python зависимости
├── Dockerfile             # Docker образ
├── docker-compose.yml     # Docker Compose конфигурация
└── .env.example           # Пример переменных окружения
```

## API Endpoints

### Админ-панель API

- `GET /admin/dashboard` - Статистика дашборда
- `GET /admin/users` - Список пользователей с поиском
- `GET /admin/predictions` - История предсказаний
- `GET /health` - Проверка здоровья сервиса

Все endpoints требуют Basic Auth аутентификации.

## Мониторинг

### Логи

Логи приложения сохраняются в:
- Контейнер: `/app/logs/`
- Хост: `./logs/`

### Health Check

Проверка состояния сервиса:
```bash
curl http://localhost:8000/health
```

### Docker статус

```bash
docker compose ps
docker compose logs coffee-oracle-bot
```

### Тестирование

Запуск всех тестов:
```bash
pytest tests/
```

Системный тест (требует запущенный сервис):
```bash
./scripts/test_system.sh
```

## Безопасность

- ✅ Basic Auth для админ-панели
- ✅ Валидация входных данных
- ✅ Фильтрация негативного контента
- ✅ Ограничения размера файлов
- ✅ Обработка ошибок API

## Лицензия

MIT License

## Поддержка

При возникновении проблем:

1. Проверьте логи: `docker compose logs coffee-oracle-bot`
2. Убедитесь, что все переменные окружения заданы корректно
3. Проверьте доступность OpenAI API
4. Убедитесь, что токен Telegram бота действителен

---

Создано с ❤️ для любителей кофе и магии! 🔮☕