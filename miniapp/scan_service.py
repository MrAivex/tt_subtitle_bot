"""miniapp/scan_service.py — поиск моментов."""
import asyncio
import traceback

from .jobs import rm
from .tasks import spawn


class ScanService:
    def __init__(self, analyzer, previews, max_moments: int, slots: int = 2):
        self._analyzer = analyzer
        self._previews = previews
        self._max = max_moments
        self._slots = asyncio.Semaphore(slots)

    async def run(self, job):
        wav = f"downloads/scan_{job.user_id}_{job.id}.wav"
        try:
            async with self._slots:
                job.progress = "Готовлю звук"
                await job.source.prepare_audio(wav)
                job.progress = "Ищу громкие моменты"
                res = await asyncio.to_thread(self._analyzer.analyze, wav, self._max, job.clip_sec)
            job.duration = max(res["duration"], 1.0)
            job.moments = res["moments"]
            job.status = "ready"
            job.progress = ""
            if job.moments:
                spawn(self._previews.run(job))
            else:
                job.previews_status = "done"
        except Exception as e:
            traceback.print_exc()
            job.status, job.error = "error", f"{type(e).__name__}: {str(e)[:150]}"
            job.source.cleanup()
        finally:
            rm(wav)       # wav нужен только для анализа
