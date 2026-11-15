from max_bot_client import MaxBot
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from config import MAX_TOKEN
from core.ffmpeg_tools import FFmpeg
from core.transcriber import Transcriber
from subtitles.font import SubtitleFont
from subtitles.line_breaker import LineBreaker
from subtitles.ass_builder import AssBuilder
from subtitles.renderer import SubtitleRenderer
from highlights.analyzer import HighlightAnalyzer
from sources import downloader

bot = MaxBot(MAX_TOKEN)
scheduler = AsyncIOScheduler()

ffmpeg = FFmpeg()
transcriber = Transcriber(device="cpu")
font = SubtitleFont()
renderer = SubtitleRenderer(ffmpeg, transcriber, LineBreaker(font), AssBuilder(font))
analyzer = HighlightAnalyzer(asr=transcriber.text)