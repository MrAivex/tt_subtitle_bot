import time
import logging
from contextlib import contextmanager


_tlog = logging.getLogger("timing")


@contextmanager
def timed(label: str):
    """Пишет в лог, сколько заняла операция."""
    t = time.perf_counter()
    try:
        yield
    finally:
        _tlog.info(f"[TIME] {label}: {time.perf_counter() - t:.1f} сек")

    
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

