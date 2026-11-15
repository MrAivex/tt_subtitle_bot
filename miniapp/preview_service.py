"""miniapp/preview_service.py — лёгкие превью (360p) для плеера."""
import asyncio
import os
import traceback


class PreviewService:
    HEIGHT = 360

    def __init__(self, ffmpeg, slots: int = 2):
        self._ffmpeg = ffmpeg
        self._slots = asyncio.Semaphore(slots)   # превью не занимают слоты сканирования

    async def run(self, job):
        try:
            async with self._slots:
                for i, m in enumerate(job.moments):
                    job.progress = f"Превью {i + 1}/{len(job.moments)}"
                    job.previews.append(await self._one(job, i, m))
            job.previews_status = "done"
            job.progress = ""
        except Exception:
            traceback.print_exc()
            job.previews_status = "error"

    async def _one(self, job, i: int, m: dict) -> dict:
        prev = job.preview_path(i)
        try:
            got = await job.source.cut(m["start"], m["end"], prev, max_height=self.HEIGHT)
            if got != prev and os.path.exists(got):
                os.replace(got, prev)
            # moov в начало — чтобы браузер мотал превью, не скачав его целиком
            await asyncio.to_thread(self._ffmpeg.faststart, prev)
            return {"idx": i, "status": "ready"}
        except Exception as e:
            traceback.print_exc()
            return {"idx": i, "status": "error", "error": str(e)[:100]}
