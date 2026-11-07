import os
from dotenv import load_dotenv

load_dotenv()

# MAX Bot
MAX_TOKEN = os.getenv("MAX_BOT_TOKEN")
MAX_WEBHOOK_URL = os.getenv("MAX_WEBHOOK_URL")
WEBHOOK_PATH = "/max-webhook"
PORT = 8081

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