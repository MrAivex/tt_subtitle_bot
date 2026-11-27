"""tg/app.py — общие объекты TG-процесса (аналог app.py для MAX)."""
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from core.ffmpeg_tools import FFmpeg
from core.transcriber import Transcriber
from highlights.analyzer import HighlightAnalyzer
from sources import downloader
from subtitles.ass_builder import AssBuilder
from subtitles.font import SubtitleFont
from subtitles.line_breaker import LineBreaker
from subtitles.renderer import SubtitleRenderer
from .client import TgBot
from .settings import TG_API_PROXY, TG_BOT_USERNAME, TG_TOKEN

bot = TgBot(TG_TOKEN, proxy=TG_API_PROXY)
scheduler = AsyncIOScheduler()

ffmpeg = FFmpeg()
transcriber = Transcriber(device="cpu")
font = SubtitleFont()
# водяной знак на бесплатном тарифе — имя TG-бота (если не задано, остаётся дефолт AssBuilder)
_ass = AssBuilder(font, watermark_text=f"@{TG_BOT_USERNAME}") if TG_BOT_USERNAME else AssBuilder(font)
renderer = SubtitleRenderer(ffmpeg, transcriber, LineBreaker(font), _ass)
analyzer = HighlightAnalyzer(asr=transcriber.text)
