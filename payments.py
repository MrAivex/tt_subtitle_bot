import os
from yookassa import Configuration, Payment
from dotenv import load_dotenv
import asyncio

load_dotenv()

Configuration.account_id = os.getenv("YOOKASSA_SHOP_ID")
Configuration.secret_key = os.getenv("YOOKASSA_SECRET_KEY")

import asyncio

async def create_payment(user_id: int, sub_id: str, email: str) -> tuple[str, str]:
    """Асинхронная обёртка: сам вызов ЮKassa идёт в отдельном потоке."""
    return await asyncio.to_thread(_create_payment_sync, user_id, sub_id, email)


def _create_payment_sync(user_id: int, sub_id: str, email: str) -> tuple[str, str]:
    """Синхронный вызов ЮKassa (не блокирует event loop, т.к. вызывается через to_thread)."""
    from subscriptions import get_subscription
    sub = get_subscription(sub_id)
    if sub["price"] == 0:
        raise ValueError("Нельзя создать платёж для бесплатной подписки")

    payment = Payment.create({
        "amount": {
            "value": str(sub["price"]) + ".00",
            "currency": "RUB"
        },
        "confirmation": {
            "type": "redirect",
            "return_url": "https://t.me/tt_subtitle_bot"
        },
        "capture": True,
        "description": f"Подписка {sub['name']}",
        "metadata": {
            "user_id": user_id,
            "sub_id": sub_id
        },
        "receipt": {
            "customer": {"email": email},
            "items": [
                {
                    "description": f"Подписка {sub['name']}",
                    "quantity": "1.00",
                    "amount": {
                        "value": str(sub["price"]) + ".00",
                        "currency": "RUB"
                    },
                    "vat_code": 1,
                    "payment_subject": "service",
                    "payment_mode": "full_payment"
                }
            ]
        }
    })
    return payment.id, payment.confirmation.confirmation_url