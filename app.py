from max_bot_client import MaxBot
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from config import (MAX_TOKEN, WHISPER_MODEL, WHISPER_THREADS, WHISPER_WORKERS,
                    HL_WHISPER_MODEL, HL_WHISPER_THREADS, HL_WHISPER_WORKERS)
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
# medium: субтитры
transcriber = Transcriber(device="cpu", model_size=WHISPER_MODEL,
                          cpu_threads=WHISPER_THREADS, num_workers=WHISPER_WORKERS)
# small: быстрый текст для поиска хайлайтов
asr_fast = Transcriber(device="cpu", model_size=HL_WHISPER_MODEL,
                       cpu_threads=HL_WHISPER_THREADS, num_workers=HL_WHISPER_WORKERS)
font = SubtitleFont()
renderer = SubtitleRenderer(ffmpeg, transcriber, LineBreaker(font), AssBuilder(font))
analyzer = HighlightAnalyzer(asr=asr_fast.text)