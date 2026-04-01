# Система миграций базы данных

## Обзор

Проект использует простую систему миграций, которая автоматически применяется при старте приложения. Миграции проверяются и применяются каждый раз при запуске, что обеспечивает актуальность схемы базы данных.

## Как это работает

1. При старте приложения вызывается `setup_database()` в `main.py`
2. После создания таблиц запускается `run_migrations()` из `coffee_oracle/database/migrations.py`
3. Каждая миграция проверяется функцией `check_fn` - нужно ли её применять
4. Если миграция нужна, вызывается функция `apply_fn`
5. Все миграции применяются в порядке их определения в списке `MIGRATIONS`

## Структура миграции

Каждая миграция состоит из трёх частей:

```python
Migration(
    name="migration_name",           # Уникальное имя миграции
    check_fn=check_migration,        # Функция проверки (нужна ли миграция)
    apply_fn=apply_migration         # Функция применения миграции
)
```

### Функция проверки (check_fn)

Возвращает `True`, если миграция нужна, `False` если уже применена:

```python
async def check_migration(session: AsyncSession) -> bool:
    """Check if migration is needed."""
    try:
        # Try to use new feature
        await session.execute(text("SELECT new_column FROM table LIMIT 1"))
        return False  # Migration not needed
    except Exception:
        return True   # Migration needed
```

### Функция применения (apply_fn)

Применяет изменения к базе данных:

```python
async def apply_migration(session: AsyncSession) -> None:
    """Apply migration."""
    await session.execute(text("ALTER TABLE table ADD COLUMN new_column VARCHAR(255)"))
    await session.commit()
```

## Добавление новой миграции

1. Откройте `coffee_oracle/database/migrations.py`

2. Создайте функции проверки и применения:

```python
async def check_my_new_feature(session: AsyncSession) -> bool:
    """Check if my new feature migration is needed."""
    try:
        await session.execute(text("SELECT my_new_column FROM users LIMIT 1"))
        return False
    except Exception:
        return True


async def apply_my_new_feature(session: AsyncSession) -> None:
    """Apply my new feature migration."""
    logger.info("Applying my new feature migration...")
    
    await session.execute(text(
        "ALTER TABLE users ADD COLUMN my_new_column VARCHAR(255)"
    ))
    
    await session.commit()
    logger.info("✅ My new feature migration completed")
```

3. Добавьте миграцию в список `MIGRATIONS`:

```python
MIGRATIONS: List[Migration] = [
    Migration(
        name="recurring_payments",
        check_fn=check_recurring_payments_migration,
        apply_fn=apply_recurring_payments_migration
    ),
    Migration(
        name="my_new_feature",  # Новая миграция
        check_fn=check_my_new_feature,
        apply_fn=apply_my_new_feature
    ),
]
```

## Ручной запуск миграций

Если нужно запустить миграции вручную (без перезапуска приложения):

```bash
# Локально
python scripts/migrate_recurring_payments.py

# В Docker
docker exec coffee_oracle_bot python scripts/migrate_recurring_payments.py
```

## Обработка ошибок

### Дублирование колонок

Если колонка уже существует, миграция пропускает её:

```python
try:
    await session.execute(text("ALTER TABLE users ADD COLUMN new_column VARCHAR(255)"))
except Exception as e:
    if "duplicate column name" not in str(e).lower():
        raise  # Re-raise if it's not a duplicate column error
```

### Откат миграций

Система не поддерживает автоматический откат. Для отката:

1. Создайте новую миграцию, которая отменяет изменения
2. Или вручную выполните SQL-команды для отката

Пример отката:

```python
async def rollback_my_feature(session: AsyncSession) -> None:
    """Rollback my feature migration."""
    # SQLite не поддерживает DROP COLUMN, нужно пересоздать таблицу
    # Или просто оставить колонку (она не помешает)
    pass
```

## Логирование

Все миграции логируются:

```
INFO: Checking for pending migrations...
INFO: Applying migration: recurring_payments
INFO: Applying recurring payments migration...
INFO: Added recurring_payment_enabled to users
INFO: Added telegram_recurring_payment_charge_id to users
INFO: Added is_recurring to payments
INFO: Added telegram_recurring_payment_charge_id to payments
INFO: ✅ Recurring payments migration completed
INFO: ✅ Applied 1 migration(s)
```

Если миграции уже применены:

```
INFO: Checking for pending migrations...
INFO: ✅ All migrations up to date
```

## Особенности SQLite

SQLite имеет ограничения на изменение схемы:

- ❌ Нельзя удалить колонку (`DROP COLUMN`)
- ❌ Нельзя изменить тип колонки
- ❌ Нельзя переименовать колонку (в старых версиях)
- ✅ Можно добавить колонку (`ADD COLUMN`)
- ✅ Можно создать новую таблицу и скопировать данные

Для сложных изменений используйте подход с пересозданием таблицы:

```python
async def complex_migration(session: AsyncSession) -> None:
    """Complex migration with table recreation."""
    # 1. Создать новую таблицу с нужной схемой
    await session.execute(text("""
        CREATE TABLE users_new (
            id INTEGER PRIMARY KEY,
            -- новая схема
        )
    """))
    
    # 2. Скопировать данные
    await session.execute(text("""
        INSERT INTO users_new SELECT * FROM users
    """))
    
    # 3. Удалить старую таблицу
    await session.execute(text("DROP TABLE users"))
    
    # 4. Переименовать новую таблицу
    await session.execute(text("ALTER TABLE users_new RENAME TO users"))
    
    await session.commit()
```

## Best Practices

1. **Всегда тестируйте миграции** на копии базы данных
2. **Делайте резервные копии** перед применением миграций
3. **Пишите идемпотентные миграции** - они должны безопасно выполняться несколько раз
4. **Логируйте каждый шаг** миграции для отладки
5. **Обрабатывайте ошибки** - не падайте на дублирующихся колонках
6. **Документируйте миграции** - объясняйте, зачем нужны изменения

## Альтернативы

Для более сложных проектов рассмотрите использование:

- **Alembic** - полноценная система миграций для SQLAlchemy
- **Flyway** - миграции на основе SQL-файлов
- **Liquibase** - миграции с XML/YAML конфигурацией

Текущая система подходит для простых проектов с небольшим количеством миграций.
