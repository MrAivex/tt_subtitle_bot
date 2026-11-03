import os
import aiohttp


def extract_video_attachment(attachments: list):
    """Ищет видео среди вложений type=video и type=file (файл без сжатия)."""
    for att in attachments:
        t = str(att.get("type", "")).lower()
        payload = att.get("payload") or {}
        name = str(payload.get("filename") or att.get("filename") or "").lower()
        size = payload.get("size") or att.get("size") or 0
        url = payload.get("url")
        token = payload.get("token")

        if t == "video":
            if token or url:
                return {"kind": "video", "token": token, "url": url,
                        "filename": name, "size": size}
        if t == "file":
            if name.endswith((".mp4", ".mov", ".avi", ".mkv", ".webm")):
                return {"kind": "file", "token": token, "url": url,
                        "filename": name, "size": size}
    return None


async def download_video(video_url: str, output_path: str):
    """Скачивает видео потоком (экономит RAM)."""
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=False)) as session:
        async with session.get(video_url) as r:
            if r.status != 200:
                raise Exception(f"HTTP {r.status}")
            with open(output_path, "wb") as f:
                async for chunk in r.content.iter_chunked(1024 * 1024):
                    f.write(chunk)


def format_moment_time(seconds: float) -> str:
    """Форматирует секунды в MM:SS."""
    m = int(seconds // 60)
    s = int(seconds % 60)
    return f"{m}:{s:02d}"