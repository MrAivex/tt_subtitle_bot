# sources/downloader.py
"""Скачивание видео по ссылке: YouTube, Twitch, TikTok, Google Drive, Яндекс.Диск.

Единственное место, где работает yt-dlp и внешние API.
"""
import asyncio
import hashlib
import logging
import os
import re
import shutil
import time
import glob
from urllib.parse import quote, urlparse

logger = logging.getLogger(__name__)

URL_RE = re.compile(r"https?://[^\s]+")

PLATFORMS = {
    "youtube.com": "YouTube", "youtu.be": "YouTube",
    "twitch.tv": "Twitch",
    "tiktok.com": "TikTok",
    "drive.google.com": "Google Drive",
    "disk.yandex.ru": "Яндекс.Диск", "disk.yandex.com": "Яндекс.Диск",
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
}

_INFLIGHT: dict = {}
TITLES: dict = {}
PROGRESS: dict = {}   # url -> "37%"
CANCELLED: set = set()

FRAG_CONC = int(os.getenv("FRAG_CONC", "32"))


class _QuietLogger:
    """Глушит сообщения yt-dlp (предупреждения о пуле соединений и т.п.), ошибки оставляет."""
    def debug(self, msg): pass
    def info(self, msg): pass
    def warning(self, msg): pass
    def error(self, msg): logger.error(f"[YTDLP] {msg}")

def get_title(url: str) -> str:
    return TITLES.get(url, "")


def extract_url(text: str):
    m = URL_RE.search(text or "")
    return m.group(0) if m else None


def detect_platform(url: str):
    host = (urlparse(url).hostname or "").lower()
    for domain, name in PLATFORMS.items():
        if host == domain or host.endswith("." + domain):
            return name
    return None


def _needs_proxy(url: str) -> bool:
    from config import PROXY_DOMAINS
    host = (urlparse(url).hostname or "").lower()
    return any(host == d or host.endswith("." + d) for d in PROXY_DOMAINS)

def _apply_safe(opts: dict, safe: bool):
    """Запасной режим: HLS качает ffmpeg, фрагменты по одному."""
    if safe:
        opts["concurrent_fragment_downloads"] = 1
        opts["hls_prefer_native"] = False
        opts["external_downloader"] = {"m3u8": "ffmpeg"}


def _retry_fragments(fn, stem, *args):
    import yt_dlp
    try:
        return fn(*args)
    except yt_dlp.utils.DownloadError as e:
        if "fragment" not in str(e).lower():
            raise
        logger.warning(f"[LINK] ошибка фрагментов, повторяю через ffmpeg: {str(e)[:150]}")
        for p in glob.glob(glob.escape(stem) + "*"):
            try:
                os.remove(p)
            except OSError:
                pass
        return fn(*args, True)


def _final_path(ydl, info, stem: str) -> str:
    try:
        fp = info["requested_downloads"][0]["filepath"]
        if fp and os.path.exists(fp):
            return fp
    except (KeyError, IndexError, TypeError):
        pass
    for ext in (".mp4", ".mkv", ".webm", ".mov", ""):
        if os.path.exists(stem + ext):
            return stem + ext
    guess = ydl.prepare_filename(info)
    logger.warning(f"[LINK] файл не найден по stem={stem}, prepare_filename={guess}")
    return guess


def _progress_hook_factory(tag: str, url: str = "", key: str = ""):
    last = {"t": 0.0}
    def hook(d):
        if key and key in CANCELLED:
            raise RuntimeError("cancelled")
        if d.get("status") != "downloading":
            return
        done = d.get("downloaded_bytes") or 0
        total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
        if url and total:
            PROGRESS[url] = f"{done / total * 100:.0f}%"
        now = time.time()
        if now - last["t"] < 20:
            return
        last["t"] = now
        pct = f"{done / total * 100:.0f}%" if total else "?"
        logger.info(f"[LINK] {tag}: {done / 1e6:.1f} / {total / 1e6:.1f} MB ({pct})")
    return hook


def _ytdlp_download_sync(url: str, output_path: str, safe: bool = False) -> str:
    from config import DOWNLOAD_PROXY, MAX_FILE_SIZE_BYTES
    import yt_dlp
    stem = output_path[:-4] if output_path.endswith(".mp4") else output_path
    opts = {
        "outtmpl": stem + ".%(ext)s",
        "format": "bv*[height<=1080][ext=mp4]+ba[ext=m4a]/bv*[height<=1080]+ba/b",
        "merge_output_format": "mp4",
        "noplaylist": True, "quiet": True, "no_warnings": True,
        "socket_timeout": 15, "retries": 3,
        "fragment_retries": 3,
        "max_filesize": MAX_FILE_SIZE_BYTES,
        "concurrent_fragment_downloads": FRAG_CONC,
        "progress_hooks": [_progress_hook_factory("video")],
        "continuedl": False,   # не продолжаем битый частичный фай
        "logger": _QuietLogger(),
    }
    if DOWNLOAD_PROXY and _needs_proxy(url):
        opts["proxy"] = DOWNLOAD_PROXY
        logger.info(f"[LINK] Качаю через прокси: {url}")
    else:
        logger.info(f"[LINK] Качаю напрямую: {url}")

    _apply_safe(opts, safe)

    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)
        return _final_path(ydl, info, stem)


async def _download_yandex_disk(url: str, output_path: str) -> str:
    import aiohttp
    api = "https://cloud-api.yandex.net/v1/disk/public/resources/download?public_key=" + quote(url, safe="")

    href = None
    for attempt in range(4):
        async with aiohttp.ClientSession() as session:
            async with session.get(api, headers=HEADERS) as resp:
                if resp.status == 429:
                    wait = int(resp.headers.get("Retry-After") or 15 * (attempt + 1))
                    logger.warning(f"[LINK] Яндекс.Диск 429 (лимит). Жду {wait} сек, попытка {attempt + 1}/4")
                    await asyncio.sleep(wait)
                    continue
                if resp.status != 200:
                    raise Exception(f"Яндекс.Диск API: HTTP {resp.status} (ссылка публичная?)")
                data = await resp.json()
                href = data.get("href")
        if href:
            break

    if not href:
        raise Exception("Яндекс.Диск ограничил частоту запросов (429). Попробуй через 5-10 минут.")

    async with aiohttp.ClientSession() as session:
        async with session.get(href, headers=HEADERS) as resp:
            if resp.status != 200:
                raise Exception(f"Яндекс.Диск: HTTP {resp.status}")
            with open(output_path, "wb") as f:
                async for chunk in resp.content.iter_chunked(1024 * 1024):
                    f.write(chunk)
    return output_path


async def _download_core(url: str, output_path: str) -> str:
    platform = detect_platform(url)
    if platform == "Яндекс.Диск":
        return await _download_yandex_disk(url, output_path)
    return await asyncio.to_thread(_retry_fragments, _ytdlp_download_sync, output_path[:-4], url, output_path)


def _clone_file(src: str, dst: str) -> str:
    dst = os.path.splitext(dst)[0] + os.path.splitext(src)[1]
    if os.path.abspath(src) == os.path.abspath(dst):
        return dst
    try:
        os.link(src, dst)
    except OSError:
        shutil.copy2(src, dst)
    return dst


async def download_by_link(url: str, output_path: str) -> str:
    key = hashlib.md5(url.encode()).hexdigest()

    existing = _INFLIGHT.get(key)
    if existing:
        logger.info(f"[LINK] Эта ссылка уже качается — присоединяюсь: {url}")
        src = await asyncio.shield(existing)
        return await asyncio.to_thread(_clone_file, src, output_path)

    task = asyncio.create_task(_download_core(url, output_path))
    _INFLIGHT[key] = task
    try:
        return await task
    finally:
        _INFLIGHT.pop(key, None)


def _ytdlp_audio_sync(url: str, stem: str, safe: bool = False) -> str:
    import yt_dlp
    opts = {
        "outtmpl": stem,
        "format": "worstaudio/bestaudio[abr<=96]/bestaudio",
        "noplaylist": True, "quiet": True, "no_warnings": True,
        "socket_timeout": 15, "retries": 3,
        "concurrent_fragment_downloads": FRAG_CONC,
        "external_downloader_args": {"ffmpeg": ["-nostats", "-loglevel", "error"]},
        "progress_hooks": [_progress_hook_factory("audio", url, stem)],
        "continuedl": False,   # не продолжаем битый частичный файл
        "logger": _QuietLogger(),
    }
    if _needs_proxy(url):
        from config import DOWNLOAD_PROXY
        opts["proxy"] = DOWNLOAD_PROXY
        logger.info(f"[LINK] Аудио через прокси: {url}")

    _apply_safe(opts, safe)
    
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            if len(TITLES) > 500:
                TITLES.clear()
            TITLES[url] = (info.get("title") or "").strip()
            return ydl.prepare_filename(info)
    finally:
        CANCELLED.discard(stem)


async def download_audio_raw(url: str, out_raw: str) -> str:
    """Скачивает звук как есть (без конвертации). out_raw — полный stem вида «..._raw»."""
    from utils import timed
    with timed("аудио: yt-dlp"):
        return await asyncio.to_thread(_retry_fragments, _ytdlp_audio_sync, out_raw, url, out_raw)


async def download_audio_only(url: str, out_wav: str) -> str:
    import subprocess
    from utils import timed

    raw = await download_audio_raw(url, out_wav[:-4] + "_raw")
    with timed("аудио: ffmpeg → wav"):
        await asyncio.to_thread(
            subprocess.run,
            ["ffmpeg", "-y", "-i", raw, "-vn", "-ar", "16000", "-ac", "1", out_wav],
            check=True, capture_output=True, text=True,
        )
    if os.path.exists(raw):
        os.remove(raw)
    return out_wav


def _ytdlp_section_sync(url: str, start: float, end: float, stem: str, max_height: int = 1080, safe: bool = False) -> str:
    import yt_dlp
    from yt_dlp.utils import download_range_func
    h = int(max_height)
    opts = {
        "outtmpl": stem + ".%(ext)s",
        "format": f"bv*[height<={h}][ext=mp4]+ba[ext=m4a]/bv*[height<={h}]+ba/b[height<={h}]/b",
        "merge_output_format": "mp4",
        "noplaylist": True, "quiet": True, "no_warnings": True,
        "socket_timeout": 15, "retries": 3,
        "download_ranges": download_range_func([], [(start, end)]),
        "concurrent_fragment_downloads": FRAG_CONC,
        "external_downloader_args": {"ffmpeg": ["-nostats", "-loglevel", "error"]},
        "progress_hooks": [_progress_hook_factory("clip")],
        "continuedl": False,   # не продолжаем битый частичный файл
        "logger": _QuietLogger(),
    }
    if _needs_proxy(url):
        from config import DOWNLOAD_PROXY
        opts["proxy"] = DOWNLOAD_PROXY

    _apply_safe(opts, safe)

    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)
        return _final_path(ydl, info, stem)


async def download_section(url: str, start: float, end: float, out_path: str,
                           max_height: int = 1080) -> str:
    stem = out_path[:-4] if out_path.endswith(".mp4") else out_path
    return await asyncio.to_thread(_retry_fragments, _ytdlp_section_sync, stem, url, start, end, stem, max_height)


def _ytdlp_duration_sync(url: str) -> float:
    import yt_dlp
    opts = {"quiet": True, "no_warnings": True, "noplaylist": True,
            "skip_download": True, "socket_timeout": 15}
    if _needs_proxy(url):
        from config import DOWNLOAD_PROXY
        opts["proxy"] = DOWNLOAD_PROXY
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)
        return float(info.get("duration") or 0)


async def get_duration(url: str) -> float:
    if detect_platform(url) == "Яндекс.Диск":
        return 0.0
    return await asyncio.to_thread(_ytdlp_duration_sync, url)
