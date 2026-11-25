import os
from dotenv import load_dotenv

load_dotenv()

# MAX Bot
MAX_TOKEN = os.getenv("MAX_BOT_TOKEN")
MAX_WEBHOOK_URL = os.getenv("MAX_WEBHOOK_URL")
WEBHOOK_PATH = "/max-webhook"
PORT = int(os.getenv("PORT", "8081"))

MINIAPP_URL = os.getenv("MINIAPP_URL", "https://subtitle-bot.ru/app/")
PAYMENT_RETURN_URL = os.getenv("PAYMENT_RETURN_URL", MINIAPP_URL)

# Админы
ADMIN_IDS = set()
_admin_ids_str = os.getenv("MAX_ADMIN_IDS", "")
if _admin_ids_str:
    try:
        ADMIN_IDS = set(int(x.strip()) for x in _admin_ids_str.split(",") if x.strip().isdigit())
    except ValueError:
        pass

# Лимиты
MAX_FILE_SIZE_BYTES = 2_500_000_000  # 2.5 ГБ
MAX_FULL_VIDEO_SEC = 30 * 60         # 30 минут
MAX_HIGHLIGHTS = 5                   # максимум моментов при сканировании
MAX_CLIPS_PER_REQUEST = 3            # максимум клипов за одну нарезку

# Планировщик (часовой пояс)
from pytz import timezone
MOSCOW_TZ = timezone("Europe/Moscow")

# Прокси для заблокированных в РФ площадок (пусто = без прокси)
DOWNLOAD_PROXY = os.getenv("DOWNLOAD_PROXY", "")
# Домены, которые обязательно идут через прокси
PROXY_DOMAINS = ("youtube.com", "youtu.be", "twitch.tv", "drive.google.com")

BOT_USERNAME = os.getenv("MAX_BOT_USERNAME", "")

USE_ASR = os.getenv("HIGHLIGHT_ASR", "1") != "0"

# Бесплатный период: лимит видео в день не действует (FREE_PERIOD=0 в .env, чтобы вернуть лимиты)
FREE_PERIOD = os.getenv("FREE_PERIOD", "1") != "0"


# Whisper для субтитров (качество важно)
WHISPER_MODEL = os.getenv("WHISPER_MODEL", "medium")
WHISPER_THREADS = int(os.getenv("WHISPER_THREADS", "2"))
WHISPER_WORKERS = int(os.getenv("WHISPER_WORKERS", "2"))
RENDER_SLOTS = int(os.getenv("RENDER_SLOTS", "2"))

# Whisper для поиска хайлайтов (нужны только слова-маркеры)
HL_WHISPER_MODEL = os.getenv("HL_WHISPER_MODEL", "small")
HL_WHISPER_THREADS = int(os.getenv("HL_WHISPER_THREADS", "1"))
HL_WHISPER_WORKERS = int(os.getenv("HL_WHISPER_WORKERS", "3"))
HL_ASR_SEC = 45.0          # как было изначально, чтобы не терять слова в конце момента

WHISPER_BEAM = int(os.getenv("WHISPER_BEAM", "5"))   # 5 = максимум качества, 3 = компромисс, 1 = быстро
WHISPER_PROMPT = os.getenv(
    "WHISPER_PROMPT",
    "Привет! Сегодня мы играем, и вот что получилось. Ну что, поехали!")                                         # сколько секунд момента слушать для хайлайтов


# ============================================================
# ASR-сервис — общий faster-whisper для всех процессов ботов
# ============================================================
# Пусто — бот грузит модели у себя в процессе (как раньше; локальная разработка).
# Задан (например http://127.0.0.1:8090) — Whisper не грузится, распознавание
# уходит по HTTP в asr_service.py. Прописать в .env прода, теста и TG-бота.
ASR_URL = os.getenv("ASR_URL", "")
# Общий секрет для запросов к сервису (заголовок X-ASR-Token). Пусто — без проверки.
ASR_TOKEN = os.getenv("ASR_TOKEN", "")
# Настройки самого asr_service.py (порт слушает только localhost)
ASR_HOST = os.getenv("ASR_HOST", "127.0.0.1")
ASR_PORT = int(os.getenv("ASR_PORT", "8090"))


# ============================================================
# Telegram-бот (tg_main.py — отдельный процесс, отдельный порт)
# ============================================================
TG_TOKEN = os.getenv("TG_BOT_TOKEN")
TG_WEBHOOK_URL = os.getenv("TG_WEBHOOK_URL")             # https://<домен>/tg-webhook
TG_WEBHOOK_PATH = "/tg-webhook"
# secret_token: Telegram шлёт его в заголовке X-Telegram-Bot-Api-Secret-Token,
# подделать запросы мимо Telegram нельзя. Сгенерировать: openssl rand -hex 24
TG_WEBHOOK_SECRET = os.getenv("TG_WEBHOOK_SECRET", "")
TG_PORT = int(os.getenv("TG_PORT", "8083"))

TG_ADMIN_IDS = set()
_tg_admin_str = os.getenv("TG_ADMIN_IDS", "")
if _tg_admin_str:
    try:
        TG_ADMIN_IDS = set(int(x.strip()) for x in _tg_admin_str.split(",") if x.strip().isdigit())
    except ValueError:
        pass

# Жёсткие лимиты Telegram Bot API: бот скачивает файлы ≤ 20 МБ, отправляет ≤ 50 МБ.
# Длинные стримы в TG — ссылками (YouTube/Twitch/TikTok/...), их качает сервер через yt-dlp.
TG_DOWNLOAD_LIMIT = 20 * 1024 * 1024
TG_UPLOAD_LIMIT = 50 * 1024 * 1024


# ============================================================
# Единый веб-миниapp (web_main.py — отдельный процесс)
# ============================================================
# «Сайт»: то же приложение, что в MAX/TG, но открывается и как отдельный сайт
# с логином, и как миниapp Telegram/MAX. Все платформы — одна база users_web.
WEB_PORT = int(os.getenv("WEB_PORT", "8084"))
# Публичный адрес сайта (https обязателен для миниapp-кнопок), например https://app.subtitle-bot.ru/
WEB_PUBLIC_URL = os.getenv("WEB_PUBLIC_URL", "")
# Секрет для сессий сайта и подписи медиа-ссылок. Сгенерировать: openssl rand -hex 24.
# Пусто — берётся TG_BOT_TOKEN (стабилен между перезапусками).
WEB_SESSION_SECRET = os.getenv("WEB_SESSION_SECRET", "")
WEB_SESSION_TTL = int(os.getenv("WEB_SESSION_TTL", str(30 * 24 * 3600)))   # 30 дней
# Кнопка «Открыть приложение» в TG-боте: адрес сайта (https обязателен)
TG_WEBAPP_URL = os.getenv("TG_WEBAPP_URL", WEB_PUBLIC_URL)
