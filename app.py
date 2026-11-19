from max_bot_client import MaxBot
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from config import MAX_TOKEN, WHISPER_MODEL, WHISPER_THREADS, WHISPER_WORKERS
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
transcriber = Transcriber(device="cpu", model_size=WHISPER_MODEL,
                          cpu_threads=WHISPER_THREADS, num_workers=WHISPER_WORKERS)
font = SubtitleFont()
renderer = SubtitleRenderer(ffmpeg, transcriber, LineBreaker(font), AssBuilder(font))
analyzer = HighlightAnalyzer(asr=transcriber.text)