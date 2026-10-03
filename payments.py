import os
from yookassa import Configuration, Payment
from dotenv import load_dotenv
import asyncio
import uuid
import traceback
import os
import logging
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

load_dotenv()

Configuration.account_id = os.getenv("YOOKASSA_SHOP_ID")
Configuration.secret_key = os.getenv("YOOKASSA_SECRET_KEY")

Configuration.timeout = 60   # секунд

YOOKASSA_PROXY = os.getenv("YOOKASSA_PROXY") 

if YOOKASSA_PROXY:
    _original_request = requests.Session.request
    def _patched_request(self, method, url, **kwargs):
        if "yookassa.ru" in url:
            kwargs.setdefault("proxies", {"https": YOOKASSA_PROXY, "http": YOOKASSA_PROXY})
        kwargs.setdefault("timeout", 30)
        return _original_request(self, method, url, **kwargs)
    requests.Session.request = _patched_request

_original_session_init = requests.Session.__init__
def _patched_session_init(self, *args, **kwargs):
    _original_session_init(self, *args, **kwargs)
    retry = Retry(total=0)
    self.mount("https://", HTTPAdapter(max_retries=retry))
    self.mount("http://", HTTPAdapter(max_retries=retry))
requests.Session.__init__ = _patched_session_init

async def create_payment(user_id: int, sub_id: str, email: str) -> tuple[str, str]:
    """Асинхронная обёртка: сам вызов ЮKassa идёт в отдельном потоке."""
    return await asyncio.to_thread(_create_payment_sync, user_id, sub_id, email)


def _create_payment_sync(user_id: int, sub_id: str, email: str) -> tuple[str, str]:
    from subscriptions import get_subscription
    sub = get_subscription(sub_id)
    if sub["price"] == 0:
        raise ValueError("Нельзя создать платёж для бесплатной подписки")

    idempotency_key = str(uuid.uuid4())
    logger.info(f"[PAYMENT] Создаю платёж: user={user_id}, sub={sub_id}, idem={idempotency_key}")
    try:
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
            }, idempotency_key)
        
        logger.info(f"[PAYMENT] Успех: {payment.id}")
        return payment.id, payment.confirmation.confirmation_url

    except Exception as e:
        logger.error(f"[PAYMENT ERROR] {type(e).__name__}: {e}")
        logger.error(traceback.format_exc())
        raise