# Рекуррентные платежи в Coffee Oracle

## Обзор

Бот поддерживает автоматическое продление подписки через Telegram Recurring Payments. Это позволяет пользователям оплачивать подписку один раз, после чего она будет автоматически продлеваться каждый месяц.

## Как это работает

1. **Первый платёж**: Пользователь оплачивает подписку через Telegram Payments
2. **Сохранение метода оплаты**: Telegram сохраняет платёжный метод пользователя (с его согласия)
3. **Автоматическое списание**: Каждый месяц Telegram автоматически списывает деньги
4. **Уведомление бота**: Бот получает webhook о каждом успешном платеже
5. **Продление подписки**: Бот автоматически продлевает подписку на месяц

## Требования

### Платёжный провайдер

Рекуррентные платежи поддерживаются не всеми провайдерами. Проверенные провайдеры:

- ✅ **ЮKassa (YooMoney)** - полная поддержка
- ✅ **Stripe** - полная поддержка
- ❌ **Тестовый провайдер** - не поддерживает рекуррентные платежи

### Настройка провайдера

1. Получите токен провайдера от @BotFather:
   ```
   /mybots → Выбрать бота → Payments → Выбрать провайдера
   ```

2. Добавьте токен в `.env`:
   ```env
   PAYMENT_PROVIDER_TOKEN=your_real_provider_token
   ```

3. Для ЮKassa добавьте в `provider_data` параметр `save_payment_method: true`

## Миграция базы данных

Перед использованием рекуррентных платежей выполните миграцию:

```bash
python scripts/migrate_recurring_payments.py
```

Это добавит следующие поля:

**Таблица `users`:**
- `recurring_payment_enabled` - включено ли автопродление (0/1)
- `telegram_recurring_payment_charge_id` - ID рекуррентного платежа для отмены

**Таблица `payments`:**
- `is_recurring` - является ли платёж рекуррентным (0/1)
- `telegram_recurring_payment_charge_id` - ID рекуррентного платежа

## Использование

### Для пользователей

1. Нажать "💎 Подписка" или `/subscribe`
2. Нажать "💳 Оформить подписку"
3. Оплатить через Telegram Payments
4. Согласиться на сохранение платёжного метода
5. Подписка будет автоматически продлеваться каждый месяц

### Отмена автопродления

Пользователь может отменить автопродление в настройках Telegram:
```
Настройки → Конфиденциальность → Платежи и доставка → Управление подписками
```

### Для администраторов

В админ-панели (`/subscriptions`) можно:
- Просмотреть пользователей с активным автопродлением
- Вручную отключить автопродление для пользователя
- Просмотреть историю рекуррентных платежей

## API методы

### SubscriptionRepository

```python
# Включить автопродление
await subscription_repo.enable_recurring_payment(user_id, recurring_charge_id)

# Отключить автопродление
await subscription_repo.disable_recurring_payment(user_id)

# Проверить статус автопродления
enabled, charge_id = await subscription_repo.is_recurring_enabled(user_id)
```

## Обработка платежей

### Первый платёж

```python
# В successful_payment_handler
is_recurring = hasattr(payment_info, 'recurring_payment_charge_id')
recurring_charge_id = payment_info.recurring_payment_charge_id

if is_recurring:
    await subscription_repo.enable_recurring_payment(user_id, recurring_charge_id)
```

### Последующие платежи

Telegram автоматически отправляет те же события `successful_payment`, что и для первого платежа. Бот обрабатывает их одинаково:

1. Создаёт запись о платеже
2. Продлевает подписку на месяц
3. Отправляет уведомление пользователю

## Тестирование

### С тестовым провайдером

Тестовый провайдер НЕ поддерживает рекуррентные платежи. Для тестирования:

1. Используйте реальный провайдер в тестовом режиме (ЮKassa Sandbox)
2. Или тестируйте вручную через админ-панель

### Ручное тестирование

1. Создать платёж через админ-панель
2. Подтвердить платёж вручную
3. Проверить продление подписки

## Безопасность

- Бот НЕ хранит платёжные данные пользователей
- Все платёжные данные хранятся у провайдера
- Telegram передаёт только ID рекуррентного платежа
- Пользователь может отменить подписку в любой момент

## Логирование

Все рекуррентные платежи логируются:

```
INFO: Successful payment: user_id=123, amount=300, recurring=True, recurring_id=abc123
INFO: Enabled recurring payment for user 123 with charge_id abc123
INFO: Subscription activated for user 123 until 2026-03-18 (recurring: True)
```

## Troubleshooting

### Ошибка: PAYMENT_PROVIDER_INVALID

- Проверьте, что используете реальный токен провайдера
- Убедитесь, что провайдер поддерживает рекуррентные платежи

### Автопродление не работает

- Проверьте, что `provider_data` содержит `save_payment_method: true`
- Убедитесь, что пользователь согласился на сохранение платёжного метода
- Проверьте логи на наличие ошибок от Telegram

### Подписка не продлевается

- Проверьте, что `recurring_payment_enabled = 1` в таблице `users`
- Убедитесь, что обработчик `successful_payment_handler` вызывается
- Проверьте, что метод `activate_premium` корректно продлевает подписку

## Дополнительные возможности

### Уведомления о предстоящем списании

Можно добавить cron-задачу, которая за 3 дня до списания отправляет уведомление:

```python
# В cron-задаче
users_with_renewal = await subscription_repo.get_users_with_upcoming_renewal(days=3)
for user in users_with_renewal:
    await bot.send_message(
        user.telegram_id,
        "💳 Через 3 дня будет списана оплата за подписку (300₽)"
    )
```

### Отмена подписки через бота

Можно добавить кнопку "Отменить автопродление" в меню подписки:

```python
@router.callback_query(F.data == "cancel_recurring")
async def cancel_recurring_callback(callback: CallbackQuery):
    # Отключить в БД
    await subscription_repo.disable_recurring_payment(user_id)
    
    # Уведомить пользователя
    await callback.message.edit_text(
        "✅ Автопродление отключено\n\n"
        "Подписка будет действовать до конца оплаченного периода."
    )
```

## Ссылки

- [Telegram Payments API](https://core.telegram.org/bots/payments)
- [ЮKassa Recurring Payments](https://yookassa.ru/developers/payments/recurring-payments)
- [Stripe Subscriptions](https://stripe.com/docs/billing/subscriptions/overview)
