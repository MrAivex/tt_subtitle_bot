from max_bot_client import MaxBot
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from config import (MAX_TOKEN, WHISPER_MODEL, WHISPER_THREADS, WHISPER_WORKERS,
                    HL_WHISPER_MODEL, HL_WHISPER_THREADS, HL_WHISPER_WORKERS,
                    ASR_URL, ASR_TOKEN)
from core.ffmpeg_tools import FFmpeg
from core.transcriber import Transcriber
from core.remote_transcriber import RemoteTranscriber
from subtitles.font import SubtitleFont
from subtitles.line_breaker import LineBreaker
from subtitles.ass_builder import AssBuilder
from subtitles.renderer import SubtitleRenderer
from highlights.analyzer import HighlightAnalyzer
from sources import downloader


def _asr(model_size: str, cpu_threads: int, num_workers: int):
    """ASR_URL задан — делим один faster-whisper в asr_service.py со всеми
    процессами ботов (прод/тест/TG). Пусто — модель грузится у себя в процессе
    (как раньше; для локальной разработки)."""
    if ASR_URL:
        return RemoteTranscriber(ASR_URL, token=ASR_TOKEN)
    return Transcriber(device="cpu", model_size=model_size,
                       cpu_threads=cpu_threads, num_workers=num_workers)


bot = MaxBot(MAX_TOKEN)
scheduler = AsyncIOScheduler()

ffmpeg = FFmpeg()
# medium: субтитры
transcriber = _asr(WHISPER_MODEL, WHISPER_THREADS, WHISPER_WORKERS)
# small: быстрый текст для поиска хайлайтов
asr_fast = _asr(HL_WHISPER_MODEL, HL_WHISPER_THREADS, HL_WHISPER_WORKERS)
font = SubtitleFont()
renderer = SubtitleRenderer(ffmpeg, transcriber, LineBreaker(font), AssBuilder(font))
analyzer = HighlightAnalyzer(asr=asr_fast.text)
