"""Скачивание видео по ссылке: YouTube, Twitch, TikTok, Google Drive, Яндекс.Диск."""
import re
import logging
import asyncio
import hashlib
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


def _ytdlp_download_sync(url: str, output_path: str) -> str:
    import yt_dlp
    stem = output_path[:-4] if output_path.endswith(".mp4") else output_path
    opts = {
        "outtmpl": stem,
        "format": "bv*[height<=1080][ext=mp4]+ba[ext=m4a]/bv*[height<=1080]+ba/b",
        "merge_output_format": "mp4",
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "socket_timeout": 30,
        "retries": 3,
        "fragment_retries": 3,
        "max_filesize": MAX_FILE_SIZE_BYTES,
    }
    if DOWNLOAD_PROXY and _needs_proxy(url):
        opts["proxy"] = DOWNLOAD_PROXY
        logger.info(f"[LINK] Качаю через прокси: {url}")
    else:
        logger.info(f"[LINK] Качаю напрямую: {url}")

    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)
        return ydl.prepare_filename(info)


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


async def download_by_link(url: str, output_path: str) -> str:
    """Скачивает видео по ссылке. Одна и та же ссылка одновременно качается только один раз."""
    key = hashlib.md5(url.encode()).hexdigest()
    if key in _INFLIGHT:
        logger.info(f"[LINK] Эта ссылка уже качается — присоединяюсь: {url}")
        return await _INFLIGHT[key]

    task = asyncio.create_task(_download_core(url, output_path))
    _INFLIGHT[key] = task
    try:
        return await task
    finally:
        _INFLIGHT.pop(key, None)