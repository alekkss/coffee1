# ☕🔮 Coffee Oracle Bot

**Мультиплатформенный бот для гадания на кофейной гуще с использованием AI Vision**

Бот работает одновременно в Telegram и мессенджере MAX. Анализирует фотографии кофейной гущи через OpenAI-совместимый Vision API и генерирует мистические позитивные предсказания в стихах. Включает админ-панель с аналитикой, систему подписок с оплатой через YooKassa и автопродлением. Все данные из обоих мессенджеров хранятся в общей базе и отображаются в единой админ-панели.

---

## Содержание

- [Архитектура](#архитектура)
- [Стек технологий](#стек-технологий)
- [Структура проекта](#структура-проекта)
- [Установка и запуск](#установка-и-запуск)
- [Конфигурация](#конфигурация)
- [Функциональность бота](#функциональность-бота)
- [Система подписок и платежей](#система-подписок-и-платежей)
- [Админ-панель](#админ-панель)
- [База данных](#база-данных)
- [API админ-панели](#api-админ-панели)
- [Обработка фотографий](#обработка-фотографий)
- [Интеграция с LLM](#интеграция-с-llm)
- [Middleware](#middleware)
- [Обработка ошибок](#обработка-ошибок)
- [Утилиты](#утилиты)
- [Инфраструктура и деплой](#инфраструктура-и-деплой)
- [Диагностика проблем](#диагностика-проблем)
- [Партнёрская реферальная система](#партнёрская-реферальная-система)

---

## Архитектура

Приложение состоит из трёх основных компонентов, запускаемых параллельно через `ApplicationOrchestrator` в `main.py`:

```
┌───────────────────────────────────────────────────────────────────┐
│                    ApplicationOrchestrator                         │
│                                                                   │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐           │
│  │ Telegram Bot  │  │  MAX Bot     │  │ Admin Panel  │           │
│  │ (aiogram 3.x) │  │ (aiohttp +   │  │ (FastAPI +   │           │
│  │ Long Polling  │  │  Long Polling)│  │  Uvicorn)    │           │
│  │ source="tg"  │  │ source="max" │  └──────┬───────┘           │
│  └──────┬───────┘  └──────┬───────┘         │                   │
│         │                 │                  │                   │
│         └────────┬────────┘         ┌────────┘                   │
│                  │                  │    ┌────────────────────┐   │
│                  │                  │    │ Subscription       │   │
│                  │                  │    │ Scheduler          │   │
│                  │                  │    │ (6h interval)      │   │
│                  │                  │    └─────────┬──────────┘   │
│          ┌───────▼──────────┐       │              │              │
│          │  LLM API         │    ┌──▼──────────────▼──────────┐  │
│          │  (OpenAI-compat) │    │  YooKassa API              │  │
│          └──────────────────┘    │  (Платежи, рекурренты)     │  │
│                                  └────────────────────────────┘  │
│          ┌──────────────────────────────────────┐                │
│          │  SQLite + SQLAlchemy (async, WAL)     │                │
│          │  Общая БД: users.source = 'tg'|'max' │                │
│          └──────────────────────────────────────┘ 
│          ┌──────────────────────────────────────┐                │
│          │  Партнёрская реферальная система       │                │
│          │  Partners → ReferralClicks            │                │
│          │  /start?start=КОД → учёт переходов   │                │
│          └──────────────────────────────────────┘                │        
└───────────────────────────────────────────────────────────────────┘

Компоненты запускаются условно:
- Telegram Bot — если задан BOT_TOKEN
- MAX Bot — если задан MAX_BOT_TOKEN
- Admin Panel — запускается всегда
- Subscription Scheduler — привязан к Telegram-боту
```

### Поток обработки предсказания

```
Пользователь отправляет фото
        │
        ▼
Проверка подписки (can_make_prediction)
        │
        ▼
MediaGroupMiddleware (сбор группы фото, 1с таймаут)
        │
        ▼
PhotoProcessor (скачивание, ресайз ≤800×800, сохранение на диск)
        │
        ▼
LLMClient (base64 → OpenAI Vision API → предсказание)
   ├── Primary model (config.litellm_model)
   └── Fallback model (config.litellm_model_fallback) — при ошибке основной
        │
        ▼
Фильтр негативного контента (_NEGATIVE_WORDS)
        │
        ▼
Markdown → Telegram HTML конвертация
        │
        ▼
Отправка пользователю (с разбиением на чанки при необходимости)
```

### Поток оплаты подписки

```
Пользователь нажимает "Подписка"
        │
        ▼
Запрос email (FSM: PaymentStates.waiting_for_email)
        │
        ▼
PaymentService.create_first_payment() → YooKassa API
   ├── Попытка с save_payment_method=true (рекуррент)
   └── Fallback: обычный платёж (при 403)
        │
        ▼
Пользователю отправляется ссылка на оплату
        │
        ▼
┌── Webhook от YooKassa (payment.succeeded) ──┐
│   ИЛИ                                       │
│   Polling: _poll_payment_and_activate()      │
│   ИЛИ                                       │
│   Ручная проверка: callback "check_payment"  │
└──────────────┬───────────────────────────────┘
               │
               ▼
Активация premium на 1 месяц + включение автопродления
```

### Разделение пользователей по платформам

Пользователи из Telegram и MAX хранятся в общей таблице `users` с разделением по полю `source`:

| source | Платформа | Бот | Пространство ID |
|--------|-----------|-----|-----------------|
| `tg`   | Telegram  | CoffeeOracleBot (aiogram) | Telegram user_id |
| `max`  | MAX       | MaxOracleBot (aiohttp)    | MAX user_id      |

Составной unique constraint `(telegram_id, source)` исключает коллизии ID между платформами.
Все предсказания, фото и платежи привязаны к внутреннему `users.id`, не зависящему от платформы.

## MAX-бот

Параллельный бот для мессенджера MAX (platform-api.max.ru). Функционально повторяет Telegram-бота
(предсказания по фото, история, случайные предсказания), но без системы подписок и платежей.

### Компоненты

| Компонент | Файл | Описание |
|-----------|------|----------|
| MaxOracleBot | `max_bot/bot.py` | Главный класс: инициализация, цикл long polling, graceful shutdown |
| MaxApiClient | `max_bot/api_client.py` | HTTP-клиент для MAX Bot API (aiohttp). Отправка/редактирование сообщений, callback-ответы, скачивание файлов |
| MaxBotHandlers | `max_bot/handlers.py` | Маршрутизация обновлений: bot_started, message_created, message_callback |
| MaxPhotoProcessor | `max_bot/photo_processor.py` | Скачивание фото через MAX API, ресайз (≤800×800), сохранение, анализ через LLM |
| MaxKeyboardManager | `max_bot/keyboards.py` | Формирование inline-клавиатур в формате MAX API |

### Особенности MAX API

- Авторизация: заголовок `Authorization: <token>` (без Bearer)
- Long polling: `GET /updates` с параметрами `marker`, `timeout`, `types`
- Сообщения: `POST /messages`, `PUT /messages`, `DELETE /messages`
- Callback-ответы: `POST /answers` с `callback_id`
- Фото приходят как вложения типа `image` с прямым URL в поле `payload.url`
- Лимит сообщения: 4000 символов (против 4096 у Telegram)
- Клавиатуры: передаются через `attachments` как объект `inline_keyboard`

### Переподключение при ошибках

Экспоненциальная задержка: 1с → 2с → 4с → ... → 60с (максимум). Сбрасывается при успешном опросе.

### Ограничения MAX-бота

- Нет системы подписок и платежей (нет аналога YooKassa для MAX)
- Нет MediaGroupMiddleware — MAX отправляет все фото в одном сообщении
- Нет FSM-состояний
- Нет форматирования текста (Markdown/HTML) — отправляется plain text

---

## Стек технологий

| Компонент | Технология | Описание |
|-----------|-----------|----------|
| Бот-фреймворк | aiogram 3.x | Асинхронный Telegram Bot API, FSM |
| Веб-фреймворк | FastAPI | Админ-панель + REST API + вебхуки |
| Валидация API | Pydantic | Request-модели для API эндпоинтов (LoginRequest, VipStatusRequest и др.) |
| ASGI-сервер | Uvicorn | Запуск FastAPI внутри asyncio loop |
| ORM | SQLAlchemy 2.x | Async, mapped_column, relationships |
| База данных | SQLite | WAL-режим, aiosqlite |
| AI/ML | OpenAI-совместимый API | Vision API через LiteLLM-прокси |
| Платежи | YooKassa API | Прямые HTTP-вызовы через httpx |
| HTTP-клиент | httpx | Async-запросы к YooKassa |
| Аутентификация | bcrypt + PyJWT | Хеширование паролей, JWT-токены в cookies |
| Обработка изображений | Pillow | Ресайз, конвертация в JPEG |
| Шаблонизатор | Jinja2 | HTML-шаблоны админ-панели |
| Конфигурация | python-dotenv | Переменные окружения из .env |
| Графики | Chart.js (CDN) | Аналитика в админ-панели |
| Markdown | marked.js (CDN) | Рендеринг предсказаний в админке |
| MAX Bot API       | aiohttp            | Long polling, отправка сообщений в MAX   |
| MAX Bot Platform  | platform-api.max.ru | REST API мессенджера MAX                |

---

## Структура проекта

```
coffee_oracle/
├── main.py                              # Точка входа, ApplicationOrchestrator
├── config.py                            # Конфигурация из env-переменных (dataclass)
│
├── bot/
│   ├── bot.py                           # CoffeeOracleBot — инициализация, polling
│   ├── handlers.py                      # Хендлеры команд, фото, подписок, платежей
│   ├── keyboards.py                     # KeyboardManager — Reply и Inline клавиатуры
│   └── middleware.py                    # MediaGroupMiddleware — сбор групп фото
├── max_bot/
│   ├── __init__.py                      # Инициализация пакета, реэкспорт классов
│   ├── bot.py                           # MaxOracleBot — инициализация, long polling
│   ├── api_client.py                    # MaxApiClient — HTTP-клиент MAX Bot API (aiohttp)
│   ├── handlers.py                      # MaxBotHandlers — обработчики событий MAX
│   ├── keyboards.py                     # MaxKeyboardManager — inline-клавиатуры MAX
│   └── photo_processor.py              # MaxPhotoProcessor — скачивание, ресайз, LLM-анализ
│
├── admin/
│   ├── app.py                           # FastAPI-приложение, роуты, API, вебхуки YooKassa
│   ├── auth.py                          # JWT-аутентификация (bcrypt + PyJWT cookies)
│   └── templates/
│       ├── login.html                   # Страница входа (JWT cookie flow)
│       ├── dashboard.html               # Главная: KPI-карточки, графики (Chart.js)
│       ├── users.html                   # Таблица пользователей с поиском и пагинацией
│       ├── predictions.html             # Таблица предсказаний с модалкой и marked.js
│       ├── subscriptions.html           # Управление подписками, VIP, платежи
│       ├── settings.html                # Редактор настроек + управление партнёрами
│       ├── partner_cabinet.html         # Кабинет партнёра (реф. ссылка, статистика)
│       ├── admins.html                  # CRUD администраторов (временно отключено)
│       └── legal_page.html              # Шаблон для /terms и /privacy (публичный)
│
├── database/
│   ├── connection.py                    # DatabaseManager — подключение, WAL, миграции
│   ├── models.py                        # SQLAlchemy-модели (User, Prediction, Payment и др.)
│   ├── migrations.py                    # Система миграций — проверка и применение
│   └── repositories.py                  # Репозитории: User, Prediction, Subscription, Settings
│
├── services/
│   ├── openai_client.py                 # LLMClient — обёртка Vision API с fallback
│   ├── photo_processor.py               # PhotoProcessor — скачивание, ресайз, сохранение
│   ├── payment_service.py               # PaymentService — YooKassa API (httpx)
│   ├── subscription_scheduler.py        # Фоновый планировщик автопродления подписок
│   ├── error_notifier.py                # Отправка ERROR-логов в Telegram админам
│   └── webhook_handler.py              # Обработка вебхуков YooKassa
│
└── utils/
    ├── errors.py                        # Иерархия кастомных исключений
    ├── logging.py                       # Настройка логирования с ротацией
    └── telegram.py                      # Markdown→HTML, split_message, sanitize

data/                                    # SQLite база данных (создаётся автоматически)
media/                                   # Сохранённые фото (создаётся автоматически)
logs/                                    # Файлы логов (создаётся автоматически)
```

---

## Установка и запуск

### Предварительные требования

- Python 3.11+
- Telegram Bot Token (от @BotFather)
- API-ключ OpenAI-совместимого провайдера (LiteLLM, OpenAI и др.)
- YooKassa Shop ID и Secret Key (для платежей, опционально)

### Локальный запуск

```bash
# 1. Клонирование
git clone <repository-url>
cd coffee-oracle

# 2. Создание виртуального окружения
python3 -m venv venv
source venv/bin/activate

# 3. Установка зависимостей
pip install -r requirements.txt

# 4. Конфигурация
cp .env.example .env
# Заполните обязательные переменные в .env

# 5. Запуск
python main.py
```

### Запуск в tmux (продакшн на VPS)

```bash
tmux new -s oracle-bot
cd /opt/oracle-bot/app
source venv/bin/activate
python main.py
# Ctrl+B, D — отсоединиться от сессии
```

Вернуться к логам:

```bash
tmux attach -t oracle-bot
```

### Docker

```bash
docker build -t coffee-oracle .

docker run -d \
  --name coffee-oracle \
  --env-file .env \
  -p 8000:8000 \
  -v ./data:/app/data \
  -v ./media:/app/media \
  -v ./logs:/app/logs \
  coffee-oracle
```

---

## Конфигурация

Все настройки задаются через переменные окружения (файл `.env`). Конфигурация загружается в dataclass `Config` через метод `Config.from_env()`.

### Обязательные переменные

| Переменная | Описание | Валидация |
|-----------|----------|-----------|
| `BOT_TOKEN` или `MAX_BOT_TOKEN` | Токен Telegram-бота и/или MAX-бота | Хотя бы один задан |
| `ADMIN_USERNAME` | Логин для входа в админ-панель | Не пустой |
| `ADMIN_PASSWORD` | Пароль для входа в админ-панель | Не пустой |
| `SECRET_KEY` | Секретный ключ приложения | Минимум 32 символа |
| `LITELLM_API_KEY` или `OPENAI_API_KEY` | API-ключ для LLM | Хотя бы один задан |

### Опциональные переменные

| Переменная | По умолчанию | Описание |
|-----------|-------------|----------|
| `DB_NAME` | `coffee_oracle.db` | Имя файла базы данных |
| `DOMAIN` | `localhost` | Домен для ссылок (terms, privacy) |
| `ADMIN_PORT` | `8000` | Порт админ-панели |
| `LITELLM_MODEL` | `platto/gpt-5.1` | Основная модель для анализа |
| `LITELLM_MODEL_FALLBACK` | — | Fallback-модель при ошибке основной |
| `LITELLM_API_BASE` | `https://api.1bitai.ru/v1` | URL API (прокси) |
| `LITELLM_TIMEOUT` | `30` | Таймаут запросов к API (секунды) |
| `LITELLM_MAX_TOKENS` | `1500` | Максимум токенов в ответе |
| `LITELLM_TEMPERATURE` | `0.8` | Температура генерации (0.0–2.0) |
| `YOOKASSA_SHOP_ID` | — | ID магазина YooKassa |
| `YOOKASSA_SECRET_KEY` | — | Секретный ключ YooKassa |
| `ERROR_NOTIFY_TELEGRAM_IDS` | — | Telegram ID для уведомлений об ошибках (через запятую) |
| `SECURE_COOKIES` | `true` | HTTPS-only cookies |
| `MAX_BOT_TOKEN` | — | Токен MAX-бота (если не задан, MAX-бот не запускается) |
| `BOT_USERNAME`| — |	Имя Telegram-бота без @ (для реферальных ссылок партнёров) |


### Пример .env

```env
BOT_TOKEN=8426845735:AAE2s7gIPoUiXiuwFLGnXXC0ucuYOnsu3Hk
ADMIN_USERNAME=admin
ADMIN_PASSWORD=strongpassword123
SECRET_KEY=RhTlIJkX3MA8Iub1C83MBxWmPrgHoC_CZphppFlKSIk
DOMAIN=oracle.kachestvozhizni.ru
LITELLM_API_KEY=sk-your-key-here
LITELLM_API_BASE=https://litellm.1bitai.ru
LITELLM_MODEL=techno/gpt-5.1
LITELLM_MODEL_FALLBACK=openai/gpt-5.1
LITELLM_TEMPERATURE=0.8
LITELLM_MAX_TOKENS=1500
ADMIN_PORT=8000
YOOKASSA_SHOP_ID=1270434
YOOKASSA_SECRET_KEY=live_xxxxxxxxxxxxx
ERROR_NOTIFY_TELEGRAM_IDS=91675683
BOT_USERNAME=oracul_coffee_bot
MAX_BOT_TOKEN=your-max-bot-token-here
```

---

## Функциональность бота

### Команды

| Команда | Описание |
|---------|----------|
| `/start` | Приветствие, создание пользователя в БД, показ главного меню. При наличии deep link параметра (реферального кода партнёра) записывает переход и привязывает пользователя к партнёру |
| `/help` | Inline-меню с разделами помощи (фото, кофе, гадание, FAQ) |
| `/predict` | Инструкция по отправке фото для предсказания |
| `/history` | Последние 5 предсказаний пользователя |
| `/random` | Случайное предсказание из списка (без фото) |
| `/subscribe` | Управление подпиской (статус, оплата, отмена автопродления) |
| `/about` | Информация о боте |
| `/clear` | Очистка истории предсказаний (с подтверждением) |
| `/support` | Справочная информация |

### Кнопки главного меню (ReplyKeyboard)

- 🔮 Получить предсказание
- 📜 Моя история
- 🎯 Случайное предсказание
- 💎 Подписка
- 📚 Как гадать
- ℹ️ О боте
- 📞 Поддержка

### FSM-состояния

| Состояние | Назначение |
|-----------|-----------|
| `PaymentStates.waiting_for_email` | Ожидание ввода email для чека 54-ФЗ |

### Настраиваемые тексты

Тексты приветствия, инструкций и описаний загружаются из таблицы `bot_settings` через `SettingsRepository`. Если настройка не задана — используется hardcoded-default. Ключи: `welcome_message`, `photo_instruction`, `about_text`.

---

## Система подписок и платежей

### Типы подписок

| Тип | Описание |
|-----|----------|
| `free` | Бесплатный тариф, ограниченное количество предсказаний |
| `premium` | Платная подписка (1 месяц), безлимитные предсказания |
| `vip` | Бессрочный доступ, назначается вручную (тестеры, партнёры) |

### PaymentService (payment_service.py)

Сервис работает напрямую с YooKassa REST API через `httpx`. Не использует SDK — только HTTP-вызовы с Basic Auth.

Основные методы:

- `create_first_payment()` — первый платёж с попыткой сохранения метода для рекуррентов. При ошибке 403 (рекурренты недоступны) автоматически fallback на обычный платёж.
- `create_recurring_payment()` — автосписание через сохранённый `payment_method_id`.
- `get_payment_status()` — проверка статуса платежа по ID.
- `wait_for_payment_completion()` — polling с экспоненциальным backoff (3с → 7.5с → 18.75с → 46.9с).
- `check_payment_completed()` — быстрая проверка (succeeded + paid).

In-memory хранение pending-платежей: `_pending_payments: dict[int, str]` (telegram_user_id → payment_id).

### WebhookHandler (webhook_handler.py)

Обрабатывает POST-запросы от YooKassa на `/api/yookassa/webhook`. Проверяет IP-адрес отправителя по белому списку YooKassa.

Обрабатываемые события:

| Событие | Действие |
|---------|----------|
| `payment.succeeded` | Активация premium на 1 месяц, включение автопродления |
| `payment.canceled` | Обновление статуса в БД, уведомление пользователя |
| `refund.succeeded` | Логирование |

Идемпотентность: повторный вебхук с тем же `payment_id` в статусе `succeeded` игнорируется.

### SubscriptionScheduler (subscription_scheduler.py)

Фоновая задача, запускаемая через `asyncio.create_task`. Интервал проверки — 6 часов. Начальная задержка — 30 секунд после старта приложения.

Логика:

1. Находит пользователей с истекающими подписками (за 1 день до окончания).
2. Если у пользователя включено автопродление и есть `charge_id` — пытается списать через `create_recurring_payment()`.
3. Классификация результата: `success` (продлено), `api_error` (transient — retry в следующем цикле), `payment_declined` (отключить автопродление, уведомить).
4. Если автопродление не настроено — отправляет напоминание.

---

## Партнёрская реферальная система

Система позволяет создавать партнёров с уникальными реферальными ссылками,
отслеживать переходы и привлечённых пользователей.

### Поток работы

1. Суперадмин создаёт партнёра в разделе «Настройки» → блок «Управление партнёрами».
2. Система автоматически создаёт AdminUser (role=partner) и Partner с уникальным 8-символьным кодом.
3. Суперадмин передаёт партнёру логин, пароль и URL входа.
4. Партнёр входит в админку → видит только кабинет партнёра (/partner).
5. В кабинете отображается реферальная ссылка вида `https://t.me/oracul_coffee_bot?start=КОД`.
6. Пользователь переходит по ссылке → бот обрабатывает `/start КОД`:
   - Записывает ReferralClick (partner_id, telegram_id, source).
   - Создаёт пользователя с referred_by_partner_id = partner.id.
7. Партнёр видит в кабинете: общее число переходов, переходы за сегодня,
   количество привлечённых пользователей, таблицу переходов по дням.

### Особенности

- Каждый переход записывается отдельно (без дедупликации), чтобы партнёр видел реальный трафик.
- Привязка пользователя к партнёру (referred_by_partner_id) сохраняется при первой регистрации.
- При удалении партнёра: ReferralClicks удаляются каскадно, referred_by_partner_id обнуляется (SET NULL).
- Реферальный код генерируется криптографически стойко через secrets.choice (8 символов: a-z, 0-9).
- Партнёрам недоступны остальные разделы админки (дашборд, пользователи, предсказания, подписки, настройки).

## Админ-панель

FastAPI-приложение (`Coffee Oracle Admin v2.0`) на порту `ADMIN_PORT` (по умолчанию 8000). Шаблоны — Jinja2. Стилизация — inline CSS с градиентным фоном (`#667eea → #764ba2`), glassmorphism-карточки, Chart.js для графиков.

### Аутентификация (auth.py)

Используется **JWT-токены в httpOnly cookies**, а не HTTP Basic.

**Поток авторизации:**

1. Пользователь открывает любую защищённую страницу → middleware проверяет cookie `access_token`.
2. Если cookie нет — перенаправление на `/login` (для HTML) или 401 JSON (для API).
3. На странице `/login` пользователь вводит логин и пароль.
4. `POST /login` — проверяет пароль через `bcrypt.checkpw()` против хеша в `admin_users`.
5. При успехе — создаётся JWT-токен (`HS256`, TTL 24 часа, подписан `SECRET_KEY`), устанавливается в cookie (`httponly=True`, `secure=config.secure_cookies`, `samesite=lax`).
6. `GET /logout` — удаляет cookie и редиректит на `/login`.

**Суперадмин при старте:** функция `ensure_superadmin()` вызывается при запуске приложения. Создаёт суперадмина из `ADMIN_USERNAME` / `ADMIN_PASSWORD`, или обновляет хеш пароля, если переменная окружения изменилась.

### Страницы

| URL | Шаблон | Описание | Доступ |
|-----|--------|----------|--------|
| `/login` | `login.html` | Форма входа (JWT cookie) | публичная |
| `/` | `dashboard.html` | Дашборд: KPI-карточки, графики активности (Chart.js), таблица ретенции | admin+ |
| `/users` | `users.html` | Таблица пользователей с поиском, пагинацией (50/стр), бейджами подписок | admin+ |
| `/predictions` | `predictions.html` | Таблица предсказаний с модалкой просмотра, фото, markdown-рендеринг (marked.js) | admin+ |
| `/subscriptions` | `subscriptions.html` | Управление подписками: статистика, VIP-назначение, premium-пользователи, история платежей | admin+ |
| `/settings` | `settings.html` | Редактор настроек: промпт, температура, тексты, цены, условия, конфиденциальность | superadmin |
| `/admins` | `admins.html` | Управление администраторами (временно отключено — редирект на `/`) | superadmin |
| `/terms` | `legal_page.html` | Условия использования (текст из `bot_settings`) | публичная |
| `/privacy` | `legal_page.html` | Политика конфиденциальности (текст из `bot_settings`) | публичная |
| `/health` | — | JSON health-check | публичная |
| `/logout` | — | Очистка cookie, редирект на `/login` | авторизованные |
| `/partner` | `partner_cabinet.html` | Кабинет партнёра: реферальная ссылка, KPI-карточки (всего переходов, за сегодня, привлечённых пользователей), таблица переходов по дням | partner |

### Роли администраторов

| Роль | Доступ |
|------|--------|
| `superadmin` | Полный доступ: настройки, управление VIP, ручное завершение платежей, CRUD админов |
| `restricted` | Дашборд, пользователи, предсказания, подписки (без настроек и управления админами) |
| `partner` |	Только кабинет партнёра (/partner): реферальная ссылка, статистика переходов |

### Настраиваемые параметры (страница Settings)

| Ключ | Тип | Описание |
|------|-----|----------|
| `system_prompt` | textarea (large) | Системный промпт для LLM |
| `temperature` | number (0–2) | Температура генерации |
| `analyze_all_photos` | select | Анализировать все фото или только первое |
| `welcome_message` | textarea | Приветственное сообщение `/start` |
| `photo_instruction` | textarea | Инструкция при запросе фото |
| `processing_message` | text | Сообщение во время обработки |
| `about_text` | textarea | Текст «О боте» |
| `filter_bad_words` | select | Фильтр негативных слов (вкл/выкл) |
| `free_predictions_limit` | number (1–100) | Лимит бесплатных гаданий |
| `subscription_price` | number (1–10000) | Цена подписки в рублях/мес |
| `terms_text` | textarea (large) | Текст условий использования |
| `privacy_text` | textarea (large) | Текст политики конфиденциальности |

Страница Settings также содержит блок «Управление партнёрами» (только superadmin):
форма создания партнёра (логин, пароль, описание), таблица существующих партнёров
с реферальными ссылками, статистикой переходов и кнопкой удаления.

### Статические файлы

Медиафайлы (фото пользователей) раздаются через FastAPI `StaticFiles` по пути `/media/<filename>`, маппинг на директорию с фото на диске.

---

## База данных

SQLite с асинхронным доступом через `aiosqlite`. WAL-режим включён для конкурентных чтений. Автоматические миграции при старте приложения.

### Модели

#### Partner

| Поле | Тип | Описание |
|------|-----|----------|
| `id` | Integer, PK | Автоинкрементный ID |
| `admin_user_id` | Integer, FK → admin_users.id, UNIQUE | Связь с AdminUser (роль partner) |
| `referral_code` | String(50), UNIQUE, INDEX | Уникальный реферальный код |
| `description` | String(500), nullable | Описание партнёра (компания, канал, блогер) |
| `created_at` | DateTime | Дата создания |

#### ReferralClick

| Поле | Тип | Описание |
|------|-----|----------|
| `id` | Integer, PK | Автоинкрементный ID |
| `partner_id` | Integer, FK → partners.id, INDEX | Связь с партнёром |
| `telegram_id` | BigInteger | ID пользователя, перешедшего по ссылке |
| `source` | String(10), default `tg` | Платформа перехода (tg/max) |
| `created_at` | DateTime | Дата перехода |

#### User

| Поле | Тип | Описание |
|------|-----|----------|
| `id` | Integer, PK | Автоинкрементный ID |
| `telegram_id` | BigInteger, INDEX | ID пользователя на платформе (Telegram или MAX) |
| `source` | String(10), default `tg` | Платформа-источник: `tg` (Telegram), `max` (MAX) |
| `username` | String(255), nullable | @username |
| `full_name` | String(255) | Отображаемое имя |
| `email` | String(255), nullable | Email для чеков |
| `subscription_type` | String(50), default `free` | Тип подписки: free, premium, vip |
| `subscription_until` | DateTime, nullable | Дата окончания подписки |
| `vip_reason` | String(255), nullable | Причина VIP-статуса |
| `recurring_payment_enabled` | Integer, default 0 | Автопродление включено (0/1) |
| `telegram_recurring_payment_charge_id` | String(255), nullable | ID метода оплаты для рекуррентов |
| `deleted_at` | DateTime, nullable | Soft delete |
| `created_at` | DateTime | Дата регистрации |
| `referred_by_partner_id` | Integer, FK → partners.id, nullable | ID партнёра, по чьей ссылке пришёл пользователь |

**Unique constraint:** `(telegram_id, source)` — гарантирует уникальность пользователя в пределах одной платформы. Один и тот же числовой ID из разных мессенджеров создаёт разных пользователей.

#### Prediction

| Поле | Тип | Описание |
|------|-----|----------|
| `id` | Integer, PK | Автоинкрементный ID |
| `user_id` | Integer, FK → users.id | Связь с пользователем |
| `photo_file_id` | String(255) | Telegram file_id фото |
| `photo_path` | String(500), nullable | Путь к файлу на диске |
| `user_request` | Text, nullable | Текст запроса (caption) |
| `prediction_text` | Text | Текст предсказания |
| `subscription_type` | String(50), nullable | Тип подписки на момент предсказания |
| `created_at` | DateTime | Дата создания |

#### PredictionPhoto

| Поле | Тип | Описание |
|------|-----|----------|
| `id` | Integer, PK | Автоинкрементный ID |
| `prediction_id` | Integer, FK → predictions.id | Связь с предсказанием |
| `file_path` | String(500) | Путь к файлу на диске |
| `file_id` | String(255) | Telegram file_id |
| `created_at` | DateTime | Дата создания |

#### Payment

| Поле | Тип | Описание |
|------|-----|----------|
| `id` | Integer, PK | Автоинкрементный ID |
| `user_id` | Integer, FK → users.id | Связь с пользователем |
| `amount` | Integer | Сумма в копейках |
| `label` | String(100), UNIQUE | Уникальный идентификатор платежа |
| `payment_id` | String(100), nullable | YooKassa payment ID |
| `status` | String(50), default `pending` | Статус: pending, succeeded, canceled, failed |
| `is_recurring` | Integer, default 0 | Рекуррентный платёж (0/1) |
| `telegram_recurring_payment_charge_id` | String(255), nullable | ID рекуррентного платежа |
| `created_at` | DateTime | Дата создания |
| `completed_at` | DateTime, nullable | Дата завершения |

#### BotSettings

| Поле | Тип | Описание |
|------|-----|----------|
| `id` | Integer, PK | Автоинкрементный ID |
| `key` | String(100), UNIQUE | Ключ настройки |
| `value` | Text | Значение |
| `description` | String(500), nullable | Описание |
| `updated_by` | String(255), nullable | Кто обновил |
| `updated_at` | DateTime | Дата обновления |

#### AdminUser

| Поле | Тип | Описание |
|------|-----|----------|
| `id` | Integer, PK | Автоинкрементный ID |
| `username` | String(255), UNIQUE | Логин |
| `password_hash` | String(255) | Хеш пароля |
| `role` | String(50), default `restricted` | Роль: superadmin, restricted, partner |
| `created_at` | DateTime | Дата создания |

### Связи

```
User 1 ──── * Prediction 1 ──── * PredictionPhoto
User 1 ──── * Payment
AdminUser 1 ──── 1 Partner 1 ──── * ReferralClick
Partner 1 ──── * User (referred_by_partner_id)
```

Каскадное удаление: удаление предсказания удаляет все связанные фото (`cascade="all, delete-orphan"`).

### Миграции (migrations.py)

Система миграций реализована через список `Migration` объектов, каждый содержит `check_fn` (проверка необходимости) и `apply_fn` (применение). Запускаются при каждом старте приложения.

Текущие миграции:

| Имя | Описание |
|-----|----------|
| `recurring_payments` | Добавление полей автопродления в users и payments |
| `prediction_subscription_type` | Добавление subscription_type в predictions |
| `soft_delete_users` | Добавление deleted_at в users |
| `payment_amount_to_integer_kopecks` | Конвертация amount из REAL (рубли) в INTEGER (копейки) |
| `user_email` | Добавление email в users |
| `partners_table` | Создание таблицы partners (реферальная система) |
| `referral_clicks_table` | Создание таблицы referral_clicks (учёт переходов) |
| `user_referred_by_partner` | Добавление referred_by_partner_id в users |

Дополнительно `DatabaseManager.check_and_migrate_db()` выполняет legacy-миграции через `ALTER TABLE` с проверкой существования колонок.

---

## API админ-панели

Все API-эндпоинты защищены JWT-аутентификацией (кроме `/health`, `/terms`, `/privacy`, `/login`, вебхука YooKassa).

### Управление партнёрами

| Метод | URL | Доступ | Описание |
|-------|-----|--------|----------|
| `GET` | `/api/partners` | superadmin | Список партнёров с реферальными ссылками и статистикой |
| `POST` | `/api/partners` | superadmin | Создать партнёра. Body: `{username, password, description}` |
| `DELETE` | `/api/partners/{partner_id}` | superadmin | Удалить партнёра (каскадно удаляет AdminUser и ReferralClicks) |
| `GET` | `/api/partner/stats` | partner | Статистика кабинета: реф. ссылка, total_clicks, today_clicks, referred_users, clicks_by_day |

### Аутентификация

| Метод | URL | Описание |
|-------|-----|----------|
| `GET` | `/login` | Страница входа |
| `POST` | `/login` | Авторизация, установка JWT cookie. Body: `{username, password}`. Ответ включает `redirect_url`: `/partner` для партнёров, `/` для остальных |
| `GET` | `/logout` | Удаление cookie, редирект на `/login` |

### Дашборд и аналитика

| Метод | URL | Описание |
|-------|-----|----------|
| `GET` | `/api/dashboard` | KPI-метрики: `total_users`, `new_users_today`, `total_predictions`, `predictions_today` |
| `GET` | `/api/analytics?period=24h\|7d\|4w\|12m` | Временные ряды для графиков (группировка по часу/дню/неделе/месяцу) |
| `GET` | `/api/retention` | Статистика ретенции по периодам: today, this_week, this_month, all_time |

### Пользователи и предсказания

| Метод | URL | Описание |
|-------|-----|----------|
| `GET` | `/api/users` | Список пользователей с количеством предсказаний и статусом подписки |
| `GET` | `/api/predictions` | Список предсказаний с данными пользователей, фото, текстом запроса |

### Настройки бота

| Метод | URL | Доступ | Описание |
|-------|-----|--------|----------|
| `GET` | `/api/settings` | admin+ | Все настройки бота (значения + описания + дата обновления) |
| `POST` | `/api/settings` | admin+ | Обновление настроек. Body: JSON `{key: value, ...}` |
| `POST` | `/api/settings/reset` | admin+ | Сброс всех настроек к значениям по умолчанию + очистка кэша LLM |
| `POST` | `/api/settings/clear-cache` | admin+ | Очистка кэша настроек LLM для немедленного применения |

### Управление подписками

| Метод | URL | Доступ | Описание |
|-------|-----|--------|----------|
| `GET` | `/api/subscriptions/stats` | admin+ | Статистика подписок (free/premium/vip/total) |
| `GET` | `/api/subscriptions/vip` | admin+ | Список VIP-пользователей |
| `POST` | `/api/subscriptions/vip` | superadmin | Назначить VIP. Body: `{user_id, reason}` |
| `DELETE` | `/api/subscriptions/vip/{user_id}` | superadmin | Снять VIP-статус |
| `GET` | `/api/subscriptions/premium` | admin+ | Список premium-пользователей |
| `DELETE` | `/api/subscriptions/premium/{user_id}` | superadmin | Снять premium-подписку |
| `POST` | `/api/subscriptions/complete-payment` | superadmin | Ручное завершение платежа. Body: `{label}` |
| `GET` | `/api/users/{user_id}/subscription` | admin+ | Детали подписки пользователя + история платежей |

### Управление администраторами

| Метод | URL | Доступ | Описание |
|-------|-----|--------|----------|
| `GET` | `/api/admin-users` | superadmin | Список администраторов |
| `POST` | `/api/admin-users` | superadmin | Создать админа. Body: `{username, password, role}` |
| `DELETE` | `/api/admin-users/{user_id}` | superadmin | Удалить админа (нельзя удалить себя) |

### YooKassa вебхук

| Метод | URL | Описание |
|-------|-----|----------|
| `POST` | `/api/yookassa/webhook` | Приём уведомлений YooKassa. Проверка IP отправителя. Без авторизации. |

### Прочее

| Метод | URL | Описание |
|-------|-----|----------|
| `GET` | `/health` | Health-check: `{status: "healthy", timestamp}`. Без авторизации. |
| `GET` | `/media/<path>` | Статические файлы медиа (фото). Без авторизации. |
| `GET` | `/terms` | Условия использования (текст из `bot_settings`). Без авторизации. |
| `GET` | `/privacy` | Политика конфиденциальности (текст из `bot_settings`). Без авторизации. |

---

## Обработка фотографий

### PhotoProcessor (photo_processor.py)

Полный цикл работы с фото от Telegram до LLM API.

**Скачивание:** `bot.get_file()` → `bot.download_file()`.

**Ресайз:** изображения приводятся к максимальному размеру 800×800 пикселей с сохранением пропорций (LANCZOS). Формат конвертируется в JPEG. Прозрачные PNG получают белый фон. Если файл превышает 4 МБ после ресайза, качество JPEG итеративно снижается с шагом 10 (от 85 до 50).

**Сохранение:** файлы сохраняются с UUID-именами (`{uuid4}.jpg`).

**Валидация:** фото отклоняются, если размер превышает 20 МБ. Из массива `PhotoSize` выбирается самое большое (по `file_size`).

**Обработка нескольких фото:** при отправке media group все фото скачиваются, ресайзятся и отправляются в один запрос к LLM через `analyze_multiple_images()`.

---

## Интеграция с LLM

### LLMClient (openai_client.py)

Обёртка над `AsyncOpenAI` клиентом, совместимым с любым OpenAI-compatible API.

**Системный промпт:** загружается из `bot_settings` (ключ `system_prompt`) с fallback на `DEFAULT_SYSTEM_PROMPT`. Автоматически дополняется текущей датой, временем, днём недели и временем суток (по московскому часовому поясу), а также именем пользователя.

**Fallback-модель:** если основная модель (`config.litellm_model`) возвращает ошибку, запрос автоматически перенаправляется на `config.litellm_model_fallback` (если задана).

**Фильтрация контента:** ответ проверяется на наличие негативных слов (болезнь, смерть, неудача и др.). При обнаружении — возвращается безопасное fallback-предсказание из заранее заготовленного списка.

**Кэширование настроек:** настройки из БД кэшируются в `_settings_cache`. Кэш очищается через API (`/api/settings/clear-cache`) или при сохранении настроек.

**Классификация ошибок:** `rate_limit`, `auth`, `bad_request`, `generic` — каждый тип с user-friendly сообщением.

---

## Middleware

### MediaGroupMiddleware (middleware.py)

Telegram отправляет каждое фото из media group как отдельное сообщение. Middleware решает эту проблему.

**Механизм:** при получении первого фото с `media_group_id` создаётся запись в глобальном словаре и запускается отложенная задача (1 секунда таймаут). Последующие фото с тем же `media_group_id` добавляются в ту же запись. По истечении таймаута все фото передаются в обработчик одним пакетом.

**Данные в контексте обработчика:**

- `media_group_photos` — список всех сообщений с фото
- `is_media_group` — `True`, если фото пришли группой
- `media_group_caption` — подпись из любого фото группы

**Thread safety:** `asyncio.Lock()` для работы с общим словарём.

**Очистка:** после обработки запись удаляется. Поздно прибывшие фото (после `processed=True`) игнорируются.

---

## Обработка ошибок

### Иерархия исключений (errors.py)

```
CoffeeOracleError (базовый)
├── DatabaseError
├── OpenAIError
├── PhotoProcessingError
├── ConfigurationError
└── AuthenticationError
```

Каждое исключение содержит `message` (user-friendly текст) и `details` (технические детали для логов). `format_error_message()` выбирает формат в зависимости от контекста.

### ErrorNotifier (error_notifier.py)

Кастомный `logging.Handler`, который отправляет логи уровня `ERROR+` в Telegram указанным пользователям (`ERROR_NOTIFY_TELEGRAM_IDS`).

Особенности:

- Дедупликация одинаковых ошибок в окне 60 секунд
- Ограничение длины сообщения (4000 символов)
- Экранирование HTML
- Неблокирующая отправка через `asyncio.run_coroutine_threadsafe`

---

## Утилиты

### telegram.py

- `markdown_to_telegram_html(text)` — конвертация Markdown в подмножество HTML Telegram (`<b>`, `<i>`, `<s>`, `<code>`, `<pre>`, `<a>`). Сначала экранируются спецсимволы HTML, затем regex-замены. Результат проходит через `sanitize_telegram_html()`.
- `sanitize_telegram_html(text)` — исправление незакрытых и несовпадающих HTML-тегов, фильтрация только разрешённых тегов Telegram.
- `split_message(text, max_length=4096)` — разбиение длинного сообщения по параграфам → строкам → словам.
- `strip_html_tags(text)` — fallback для удаления всех тегов с восстановлением HTML-entities.

### logging.py

- `setup_logging(level, log_file, format_string)` — настройка с `RotatingFileHandler` (10 МБ, 1 бэкап). Логи в stdout + файл.
- `get_logger(name)` — получение именованного логгера.
- Логгеры `aiogram`, `httpx`, `uvicorn.access` приглушены до WARNING.

---

## Инфраструктура и деплой

### Текущая инфраструктура (VPS)

```
Internet
│
▼
Nginx (:80, :443) ← Let's Encrypt TLS (certbot)
│
└──► localhost:8000 → oracle-bot (tmux-сессия)
```

### Файловая структура на сервере

```
/opt/oracle-bot/
├── app/                    # Код приложения
│   ├── coffee_oracle/      # Основной пакет
│   ├── main.py             # Точка входа
│   ├── .env                # Переменные окружения
│   ├── venv/               # Виртуальное окружение
│   └── requirements.txt
├── data/
│   └── coffee_oracle.db    # SQLite база данных
└── media/                  # Фото пользователей
```

### Nginx конфигурация

Файл: `/etc/nginx/sites-available/oracle-bot`

Certbot автоматически добавляет HTTPS-конфигурацию и управляет обновлением сертификатов.

### Управление процессом

```bash
# Подключиться к сессии бота
tmux attach -t oracle-bot

# Перезапуск: Ctrl+C в tmux, затем
python main.py

# Отсоединиться: Ctrl+B, D
```

### Порты

- `80, 443` — Nginx (внешний доступ)
- `8000` — админ-панель и API (localhost, проксируется через Nginx)
- Telegram-бот работает через Long Polling и не требует открытых портов
- MAX-бот работает через Long Polling и не требует открытых портов

### Сигналы завершения

Приложение корректно обрабатывает SIGTERM и SIGINT: останавливает Telegram-бота (если запущен), останавливает MAX-бота (если запущен), закрывает HTTP-сессии, останавливает планировщик подписок, останавливает Uvicorn и закрывает соединение с БД.

---

## Диагностика проблем

### Бот не отвечает

```bash
# Проверить tmux-сессию
tmux attach -t oracle-bot

# Если сессия умерла — перезапустить
tmux new -s oracle-bot
cd /opt/oracle-bot/app && source venv/bin/activate && python main.py
```

### Ошибки в логах

```bash
# Последние логи (в tmux)
tmux attach -t oracle-bot

# Файл логов
tail -100 /opt/oracle-bot/app/logs/coffee_oracle.log

# Только ошибки
grep -i error /opt/oracle-bot/app/logs/coffee_oracle.log | tail -30
```

### Проблемы с платежами

```bash
# Логи платежей
grep -iE "yookassa|webhook|payment" /opt/oracle-bot/app/logs/coffee_oracle.log | tail -30
```

### Проблемы с базой данных

```bash
# Проверить целостность
sqlite3 /opt/oracle-bot/data/coffee_oracle.db "PRAGMA integrity_check;"

# Размер базы
ls -lh /opt/oracle-bot/data/coffee_oracle.db

# Количество пользователей
sqlite3 /opt/oracle-bot/data/coffee_oracle.db "SELECT COUNT(*) FROM users;"

# Последние предсказания
sqlite3 /opt/oracle-bot/data/coffee_oracle.db \
  "SELECT u.username, p.created_at, substr(p.prediction_text, 1, 80) FROM predictions p JOIN users u ON u.id = p.user_id ORDER BY p.created_at DESC LIMIT 10;"
```

### Проблемы с Nginx / HTTPS

```bash
# Проверить статус
systemctl status nginx

# Тест конфигурации
nginx -t

# Логи
tail -50 /var/log/nginx/error.log

# Обновление сертификата вручную
certbot renew
```

### Health-check

```bash
curl https://oracle.kachestvozhizni.ru/health
```

### MAX-бот не отвечает

```bash
# Проверить логи MAX-бота
grep -i "MAX-бот" /opt/oracle-bot/app/logs/coffee_oracle.log | tail -30

# Проверить ошибки API
grep -i "MAX API" /opt/oracle-bot/app/logs/coffee_oracle.log | tail -30

# Проверить, что MAX_BOT_TOKEN задан в .env
grep MAX_BOT_TOKEN /opt/oracle-bot/app/.env

---

## Ограничения

- SQLite не подходит для высоконагруженных сценариев. Для масштабирования — заменить на PostgreSQL (изменить `database_url` и драйвер на `asyncpg`).
- Фото хранятся на локальном диске. Для масштабирования — S3-совместимое хранилище.
- Pending-платежи хранятся in-memory (`_pending_payments`) — при перезапуске теряются. Вебхук YooKassa компенсирует это.
- Кэш настроек LLM не имеет TTL — очищается только вручную или при сохранении настроек.
- Подписки и платежи работают только в Telegram-боте. MAX-бот не поддерживает платежи — все пользователи MAX имеют бесплатный тариф без лимитов (проверка подписки в MAX-обработчиках не реализована).

---

## Лицензия

Проект разработан как приватный. Все права защищены.
