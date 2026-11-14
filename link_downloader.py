"""Скачивание видео по ссылке: YouTube, Twitch, TikTok, Google Drive, Яндекс.Диск."""
import re
import logging
import asyncio
import os
import hashlib
import shutil
import time
from urllib.parse import urlparse, quote

import aiohttp

from config import DOWNLOAD_PROXY, PROXY_DOMAINS, MAX_FILE_SIZE_BYTES

logger = logging.getLogger(__name__)

URL_RE = re.compile(r"https?://[^\s]+")

PLATFORMS = {
    "youtube.com": "YouTube", "youtu.be": "YouTube",
    "twitch.tv": "Twitch",
    "tiktok.com": "TikTok",
    "drive.google.com": "Google Drive",
    "disk.yandex.ru": "Яндекс.Диск", "disk.yandex.com": "Яндекс.Диск",
}

# Браузерный UA — иначе Яндекс/Google принимают нас за бота и чаще банят
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
}

# Защита от повторных скачиваний одной ссылки одновременно
_INFLIGHT: dict = {}

# Названия роликов, которые узнали при скачивании звука (url -> title)
TITLES: dict = {}


def get_title(url: str) -> str:
    """Название ролика/стрима, если yt-dlp его узнал (для подписи клипов)."""
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
    host = (urlparse(url).hostname or "").lower()
    return any(host == d or host.endswith("." + d) for d in PROXY_DOMAINS)

def _final_path(ydl, info, stem: str) -> str:
    """Реальный путь скачанного файла (yt-dlp сам решает, какое будет расширение)."""
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


def _progress_hook_factory(tag: str):
    """Логирует прогресс скачивания раз в 20 секунд."""
    last = {"t": 0.0}
    def hook(d):
        if d.get("status") != "downloading":
            return
        now = time.time()
        if now - last["t"] < 20:
            return
        last["t"] = now
        done = d.get("downloaded_bytes") or 0
        total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
        pct = f"{done / total * 100:.0f}%" if total else "?"
        logger.info(f"[LINK] {tag}: {done / 1e6:.1f} / {total / 1e6:.1f} MB ({pct})")
    return hook


def _ytdlp_download_sync(url: str, output_path: str) -> str:
    import yt_dlp
    stem = output_path[:-4] if output_path.endswith(".mp4") else output_path
    opts = {
        "outtmpl": stem + ".%(ext)s",
        "format": "bv*[height<=1080][ext=mp4]+ba[ext=m4a]/bv*[height<=1080]+ba/b",
        "merge_output_format": "mp4",
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "socket_timeout": 15,
        "retries": 3,
        "fragment_retries": 3,
        "max_filesize": MAX_FILE_SIZE_BYTES,
        "concurrent_fragment_downloads": 8,
        "progress_hooks": [_progress_hook_factory("video")],
    }
    if DOWNLOAD_PROXY and _needs_proxy(url):
        opts["proxy"] = DOWNLOAD_PROXY
        logger.info(f"[LINK] Качаю через прокси: {url}")
    else:
        logger.info(f"[LINK] Качаю напрямую: {url}")

    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)
        return _final_path(ydl, info, stem)


async def _download_yandex_disk(url: str, output_path: str) -> str:
    """Яндекс.Диск через публичный API + обработка 429 (лимит запросов)."""
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
    return await asyncio.to_thread(_ytdlp_download_sync, url, output_path)


def _clone_file(src: str, dst: str) -> str:
    """Даёт вызывающему свой собственный файл (жёсткая ссылка, иначе копия)."""
    # путь назначения берём с расширением реально скачанного файла
    dst = os.path.splitext(dst)[0] + os.path.splitext(src)[1]
    if os.path.abspath(src) == os.path.abspath(dst):
        return dst
    try:
        os.link(src, dst)
    except OSError:
        shutil.copy2(src, dst)
    return dst


async def download_by_link(url: str, output_path: str) -> str:
    """Скачивает видео по ссылке. Одна и та же ссылка одновременно качается один раз,
    но каждый вызывающий получает свой файл."""
    key = hashlib.md5(url.encode()).hexdigest()

    existing = _INFLIGHT.get(key)
    if existing:
        logger.info(f"[LINK] Эта ссылка уже качается — присоединяюсь: {url}")
        # shield: отмена ожидающего не должна ронять общую загрузку
        src = await asyncio.shield(existing)
        return await asyncio.to_thread(_clone_file, src, output_path)

    task = asyncio.create_task(_download_core(url, output_path))
    _INFLIGHT[key] = task
    try:
        return await task
    finally:
        _INFLIGHT.pop(key, None)



def _ytdlp_audio_sync(url: str, stem: str) -> str:
    import yt_dlp
    opts = {
        "outtmpl": stem,
        "format": "worstaudio/bestaudio[abr<=96]/bestaudio",  # звук минимального веса
        "noplaylist": True, "quiet": True, "no_warnings": True,
        "socket_timeout": 15, "retries": 3,
        "concurrent_fragment_downloads": 8,   # ← 8 параллельных фрагментов HLS
        "external_downloader_args": {"ffmpeg": ["-nostats", "-loglevel", "error"]},
        "progress_hooks": [_progress_hook_factory("audio")],
    }
    if DOWNLOAD_PROXY and _needs_proxy(url):
        opts["proxy"] = DOWNLOAD_PROXY
        logger.info(f"[LINK] Аудио через прокси: {url}")
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)
        if len(TITLES) > 500:
            TITLES.clear()
        TITLES[url] = (info.get("title") or "").strip()
        return ydl.prepare_filename(info)


async def download_audio_only(url: str, out_wav: str) -> str:
    """Быстро качает только звук и конвертит в WAV 16 kHz mono."""
    import subprocess
    from utils import timed

    with timed("аудио: yt-dlp"):
        raw = await asyncio.to_thread(_ytdlp_audio_sync, url, out_wav[:-4] + "_raw")
    with timed("аудио: ffmpeg → wav"):
        await asyncio.to_thread(
            subprocess.run,
            ["ffmpeg", "-y", "-i", raw, "-vn", "-ar", "16000", "-ac", "1", out_wav],
            check=True, capture_output=True, text=True,
        )
    if os.path.exists(raw):
        os.remove(raw)
    return out_wav


def _ytdlp_section_sync(url: str, start: float, end: float, stem: str, max_height: int = 1080) -> str:
    import yt_dlp
    from yt_dlp.utils import download_range_func
    h = int(max_height)
    opts = {
        "outtmpl": stem + ".%(ext)s",
        "format": f"bv*[height<={h}][ext=mp4]+ba[ext=m4a]/bv*[height<={h}]+ba/b[height<={h}]/b",
        "merge_output_format": "mp4",
        "noplaylist": True, "quiet": True, "no_warnings": True,
        "socket_timeout": 15, "retries": 3,
        # ВАЖНО: в Python API ключ называется download_ranges, а не download_sections
        "download_ranges": download_range_func([], [(start, end)]),
        # force_keyframes_at_cuts не ставим: без него ffmpeg режет с -c copy (без перекодирования).
        # Начало клипа может сдвинуться на пару секунд к ближайшему ключевому кадру,
        # у нас уже есть pad_before=3.
        "concurrent_fragment_downloads": 8,
        "external_downloader_args": {"ffmpeg": ["-nostats", "-loglevel", "error"]},
        "progress_hooks": [_progress_hook_factory("clip")],
    }
    if DOWNLOAD_PROXY and _needs_proxy(url):
        opts["proxy"] = DOWNLOAD_PROXY
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)
        return _final_path(ydl, info, stem)


async def download_section(url: str, start: float, end: float, out_path: str,
                           max_height: int = 1080) -> str:
    """Качает из интернета ТОЛЬКО фрагмент видео (для ссылок). max_height — потолок качества (превью: 360)."""
    stem = out_path[:-4] if out_path.endswith(".mp4") else out_path
    return await asyncio.to_thread(_ytdlp_section_sync, url, start, end, stem, max_height)