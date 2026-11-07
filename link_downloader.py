"""Скачивание видео по ссылке: YouTube, Twitch, TikTok, Google Drive, Яндекс.Диск."""
import re
import logging
import asyncio
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
    api = "https://cloud-api.yandex.net/v1/disk/public/resources/download?public_key=" + quote(url, safe="")
    async with aiohttp.ClientSession() as session:
        async with session.get(api) as resp:
            if resp.status != 200:
                raise Exception(f"Яндекс.Диск API: HTTP {resp.status} (ссылка публичная?)")
            data = await resp.json()
            href = data.get("href")
            if not href:
                raise Exception("Яндекс.Диск не дал прямую ссылку")
        async with session.get(href) as resp:
            if resp.status != 200:
                raise Exception(f"Яндекс.Диск: HTTP {resp.status}")
            with open(output_path, "wb") as f:
                async for chunk in resp.content.iter_chunked(1024 * 1024):
                    f.write(chunk)
    return output_path


async def download_by_link(url: str, output_path: str) -> str:
    platform = detect_platform(url)
    if platform == "Яндекс.Диск":
        return await _download_yandex_disk(url, output_path)
    return await asyncio.to_thread(_ytdlp_download_sync, url, output_path)