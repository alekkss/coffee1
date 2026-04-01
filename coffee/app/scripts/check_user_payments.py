#!/usr/bin/env python3
"""Check user payments and subscription info."""

import asyncio
import sys
from coffee_oracle.database.connection import db_manager
from coffee_oracle.database.repositories import UserRepository, SubscriptionRepository


async def list_subscribers():
    """List all active subscribers."""
    async for session in db_manager.get_session():
        user_repo = UserRepository(session)
        
        # Get all users with active subscriptions
        users = await user_repo.get_all_users()
        subscribers = [u for u in users if u.subscription_type in ("premium", "vip") and u.subscription_until]
        
        if not subscribers:
            print("❌ Активных подписчиков не найдено")
            return
        
        print(f"\n📋 Активные подписчики ({len(subscribers)}):\n")
        for user in subscribers:
            print(f"👤 {user.full_name} (@{user.username})")
            print(f"   Telegram ID: {user.telegram_id}")
            print(f"   Тип: {user.subscription_type}")
            print(f"   До: {user.subscription_until}")
            print(f"   Автопродление: {'✅' if user.recurring_payment_enabled else '❌'}")
            print()


async def check_user(telegram_id: int):
    """Check user payments and subscription status."""
    async for session in db_manager.get_session():
        user_repo = UserRepository(session)
        sub_repo = SubscriptionRepository(session)
        
        # Get user
        user = await user_repo.get_user_by_telegram_id(telegram_id)
        if not user:
            print(f"❌ Пользователь с ID {telegram_id} не найден")
            return
        
        print(f"\n👤 Пользователь: {user.full_name} (@{user.username})")
        print(f"   ID: {user.id} | Telegram ID: {user.telegram_id}")
        print(f"   Создан: {user.created_at}")
        
        # Subscription info
        print(f"\n💎 Подписка:")
        print(f"   Тип: {user.subscription_type}")
        print(f"   До: {user.subscription_until}")
        print(f"   Автопродление: {'✅ Включено' if user.recurring_payment_enabled else '❌ Отключено'}")
        if user.telegram_recurring_payment_charge_id:
            print(f"   Charge ID: {user.telegram_recurring_payment_charge_id}")
        
        # Get payments
        payments = await sub_repo.get_user_payments(user.id)
        if payments:
            print(f"\n💳 Платежи ({len(payments)}):")
            for payment in payments:
                status_emoji = "✅" if payment.status == "completed" else "⏳" if payment.status == "pending" else "❌"
                amount_rub = payment.amount / 100
                print(f"   {status_emoji} {payment.created_at.strftime('%d.%m.%Y %H:%M')} | {amount_rub:.2f} ₽ | {payment.status}")
                print(f"      Label: {payment.label}")
                if payment.payment_id:
                    print(f"      YooKassa ID: {payment.payment_id}")
                if payment.is_recurring:
                    print(f"      Рекуррентный платёж")
        else:
            print(f"\n💳 Платежей не найдено")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Использование:")
        print("  python scripts/check_user_payments.py list          - показать всех подписчиков")
        print("  python scripts/check_user_payments.py <telegram_id> - показать платежи пользователя")
        print("\nПример: python scripts/check_user_payments.py 123456789")
        sys.exit(1)
    
    if sys.argv[1] == "list":
        asyncio.run(list_subscribers())
    else:
        telegram_id = int(sys.argv[1])
        asyncio.run(check_user(telegram_id))
