"""miniapp/render_service.py — рендер клипов и полного видео в полном качестве."""
import asyncio
import re
import traceback

from .errors import ApiError
from .jobs import FULL_VIDEO, rm

_BAD_NAME = re.compile(r'[\\/:*?"<>|\x00-\x1f]')


def safe_name(s: str, limit: int = 60) -> str:
    s = _BAD_NAME.sub(" ", s or "")
    s = re.sub(r"\s+", " ", s).strip(" .-")
    return s[:limit].rstrip(" .-")


def clip_name(title: str, n: int) -> str:
    """«Клип Стрим держи дверь 3.mp4». n — номер момента в списке (как в приложении)."""
    t = safe_name(title)
    return f"Клип {t} {n}.mp4" if t else f"clip_{n}.mp4"


def full_name(title: str) -> str:
    t = safe_name(title)
    return f"{t} (субтитры).mp4" if t else "full_subtitled.mp4"


class RenderService:
    def __init__(self, renderer, ffmpeg, billing, max_full_sec: int):
        self._renderer = renderer
        self._ffmpeg = ffmpeg
        self._billing = billing
        self._max_full_sec = max_full_sec
        self._slots = asyncio.Semaphore(1)

    async def run(self, job, idx: int, subs: bool, vertical: bool, style=None, opts=None):
        extra: list = []      # файлы, которые удаляются вместе с рендером
        try:
            async with self._slots:
                await self._charge_once(job)
                if idx == FULL_VIDEO:
                    res = await self._full(job, vertical, extra, style)
                else:
                    res = await self._clip(job, idx, subs, vertical, extra, style)
            job.renders[idx] = {**res, "opts": opts}
            job.progress = ""
        except ApiError as e:
            rm(*extra)
            job.renders[idx] = {"status": "error", "error": e.msg, "opts": opts}
        except Exception as e:
            traceback.print_exc()
            rm(*extra)
            job.renders[idx] = {"status": "error", "error": f"{type(e).__name__}: {str(e)[:120]}", "opts": opts}

    async def _charge_once(self, job):
        if not job.charged:
            job.premium = await self._billing.charge(job.user_id, job.chat_id)
            job.charged = True

    async def _clip(self, job, idx, subs, vertical, extra, style=None) -> dict:
        m = job.moments[idx]
        job.progress = f"Клип {idx + 1}"
        clip = await job.source.cut(m["start"], m["end"], f"downloads/clip_{job.id}_{idx}.mp4")
        extra.append(clip)
        final = clip
        if subs:
            res = await asyncio.to_thread(
                self._renderer.render, clip, premium=job.premium, vertical=vertical, style=style)
            final = res.video_path
            if res.srt_path:
                extra.append(res.srt_path)
        elif vertical:
            final = clip[:-4] + "_v.mp4"
            await asyncio.to_thread(self._ffmpeg.crop_vertical, clip, final)
        return {"status": "ready", "path": final,
                "name": clip_name(job.title, idx + 1), "extra": extra}

    async def _full(self, job, vertical, extra, style=None) -> dict:
        if job.duration > self._max_full_sec:
            raise ApiError(f"Видео длиннее {self._max_full_sec // 60} минут — только хайлайты")
        job.progress = "Готовлю полное видео"
        src = await job.source.full_video(f"downloads/full_{job.id}.mp4")
        if job.source.is_temp(src):
            extra.append(src)
        job.progress = "Субтитры на всё видео"
        res = await asyncio.to_thread(
            self._renderer.render, src, premium=job.premium, vertical=vertical, style=style)
        if res.srt_path:
            extra.append(res.srt_path)
        return {"status": "ready", "path": res.video_path,
                "name": full_name(job.title), "extra": extra}
