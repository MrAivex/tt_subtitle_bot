"""tg/settings.py — настройки Telegram-версии (все переменные с префиксом TG_).

ВАЖНО: этот модуль нужно импортировать ДО `config` и `payments`: он подменяет
PAYMENT_RETURN_URL для TG-процесса (возврат после оплаты — в Telegram, а не в MAX).
"""
import hashlib
import os

from dotenv import load_dotenv

load_dotenv()

TG_TOKEN = os.getenv("TG_BOT_TOKEN", "")
TG_BOT_USERNAME = os.getenv("TG_BOT_USERNAME", "").lstrip("@")

# Публичный HTTPS-адрес вебхука (его дергает Telegram), например https://tg.subtitle-bot.ru/tg-webhook
TG_WEBHOOK_URL = os.getenv("TG_WEBHOOK_URL", "")
TG_WEBHOOK_PATH = "/tg-webhook"
# Секрет вебхука. Если не задан — выводим из токена, чтобы не заводить ещё одну переменную.
TG_WEBHOOK_SECRET = os.getenv("TG_WEBHOOK_SECRET") or hashlib.sha256(
    ("webhook:" + TG_TOKEN).encode()).hexdigest()[:48]

TG_PORT = int(os.getenv("TG_PORT", "8082"))

# Публичный HTTPS-адрес мини-приложения (обязательно https), например https://tg.subtitle-bot.ru/app/
TG_MINIAPP_URL = os.getenv("TG_MINIAPP_URL", "")

# Прокси для api.telegram.org (пусто = напрямую), например socks5://user:pass@host:1080
TG_API_PROXY = os.getenv("TG_API_PROXY", "") or None

TG_ADMIN_IDS = {int(x) for x in os.getenv("TG_ADMIN_IDS", "").split(",") if x.strip().isdigit()}

# Куда вернуть человека после оплаты в ЮKassa
_ret = os.getenv("TG_PAYMENT_RETURN_URL") or (f"https://t.me/{TG_BOT_USERNAME}" if TG_BOT_USERNAME else "")
if _ret:
    os.environ["PAYMENT_RETURN_URL"] = _ret
