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
  

