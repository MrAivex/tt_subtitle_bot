from max_bot_client import MaxBot
from session_manager import SessionManager
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from types import SimpleNamespace
from config import MAX_TOKEN
from core.ffmpeg_tools import FFmpeg
from core.transcriber import Transcriber
from subtitles.font import SubtitleFont
from subtitles.line_breaker import LineBreaker
from subtitles.ass_builder import AssBuilder
from subtitles.renderer import SubtitleRenderer
from highlights.analyzer import HighlightAnalyzer
from sources import download_audio_only, download_section, download_by_link, get_title

bot = MaxBot(MAX_TOKEN)
session_manager = SessionManager()
scheduler = AsyncIOScheduler()

ffmpeg = FFmpeg()
transcriber = Transcriber(device="cpu")
font = SubtitleFont()
renderer = SubtitleRenderer(ffmpeg, transcriber, LineBreaker(font), AssBuilder(font))
analyzer = HighlightAnalyzer(asr=transcriber.text)

downloader = type("Downloader", (), {
    "audio_only": download_audio_only,
    "section": download_section,
    "by_link": download_by_link,
    "get_title": get_title,
})()

# Совместимость со старой логикой в handlers/video.py
engine = SimpleNamespace(
    get_video_duration=ffmpeg.duration,
    cut_clip=ffmpeg.cut_clip,
    scan_highlights=lambda path, n: analyzer.analyze(path, n),
    process_video=lambda src, user_id, premium, webcam_box=None, vertical=False: (
        renderer.render(src, premium=premium, vertical=vertical)
    ),
)