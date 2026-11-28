"""ASR-сервис: faster-whisper запущен ОДИН раз на весь сервер.

Раньше каждый процесс бота (прод 8081, тест 8082) грузил свои копии моделей
(medium + small) — итого 4 загрузки в RAM. Теперь все процессы ходят сюда по
HTTP, модели загружены один раз. Побочно: распознавание больше не делит CPU
с ffmpeg/анализатором в процессе бота.

Запуск: python asr_service.py  (порт ASR_PORT, по умолчанию 8090; слушает
только 127.0.0.1 — наружу не открывать, доступ по пути к файлу).

API:
  GET  /health    — жив ли сервис, какие модели
  POST /v1/words  — {"path": "/abs/path.wav"} → {"words": [{word, start, end}…]}
                    модель для субтитров (WHISPER_MODEL)
  POST /v1/text   — тело: PCM float32 16 кГц моно → {"text": "..."}
                    модель для поиска хайлайтов (HL_WHISPER_MODEL)

Примеры:
  curl http://127.0.0.1:8090/health
  curl -X POST http://127.0.0.1:8090/v1/words -H 'Content-Type: application/json' \
       -d '{"path": "/opt/tt-bot/downloads/scan_1_abc.wav"}'
"""
import asyncio
import logging
from pathlib import Path

import numpy as np
from aiohttp import web

from config import (ASR_HOST, ASR_PORT, ASR_TOKEN,
                    WHISPER_MODEL, WHISPER_THREADS, WHISPER_WORKERS,
                    HL_WHISPER_MODEL, HL_WHISPER_THREADS, HL_WHISPER_WORKERS)
from core.transcriber import Transcriber

# ============================================================
# Логирование (как в main.py: тихо, кроме своих сообщений)
# ============================================================
logging.basicConfig(
    level=logging.WARNING,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
)
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

for _name in ("aiohttp", "aiohttp.access", "aiohttp.server",
              "faster_whisper", "huggingface_hub", "urllib3", "httpcore"):
    logging.getLogger(_name).setLevel(logging.ERROR)

_fh = logging.FileHandler("timing.log", encoding="utf-8")
_fh.setFormatter(logging.Formatter("%(asctime)s %(message)s", "%H:%M:%S"))
_tlg = logging.getLogger("timing")
_tlg.setLevel(logging.INFO)
_tlg.addHandler(_fh)
# ============================================================

# Те же две модели, что раньше грузил каждый бот
transcriber = Transcriber(device="cpu", model_size=WHISPER_MODEL,
                          cpu_threads=WHISPER_THREADS, num_workers=WHISPER_WORKERS)
asr_fast = Transcriber(device="cpu", model_size=HL_WHISPER_MODEL,
                       cpu_threads=HL_WHISPER_THREADS, num_workers=HL_WHISPER_WORKERS)

# Параллельных вызовов не больше, чем workers у модели — быстрее всё равно не станет,
# а потоков в сервисе не копится
WORDS_SLOTS = asyncio.Semaphore(max(1, WHISPER_WORKERS))
TEXT_SLOTS = asyncio.Semaphore(max(1, HL_WHISPER_WORKERS))


def _auth(request):
    if ASR_TOKEN and request.headers.get("X-ASR-Token") != ASR_TOKEN:
        return web.json_response({"error": "unauthorized"}, status=401)
    return None


async def health(request):
    return web.json_response({"ok": True,
                              "models": {"subs": WHISPER_MODEL,
                                         "highlights": HL_WHISPER_MODEL}})


async def words(request):
    err = _auth(request)
    if err:
        return err
    try:
        path = Path((await request.json())["path"]).resolve()
    except Exception:
        return web.json_response({"error": "bad request: жду {\"path\": ...}"}, status=400)
    if path.suffix.lower() != ".wav" or not path.is_file():
        return web.json_response({"error": f"нет такого wav-файла: {path}"}, status=400)
    try:
        async with WORDS_SLOTS:
            ws = await asyncio.to_thread(transcriber.words, str(path))
    except Exception as e:
        logger.exception("ASR /v1/words")
        return web.json_response({"error": f"{type(e).__name__}: {e}"}, status=500)
    return web.json_response({"words": [{"word": w.word, "start": w.start, "end": w.end}
                                        for w in ws]})


async def text(request):
    err = _auth(request)
    if err:
        return err
    raw = await request.read()
    if not raw or len(raw) % 4:
        return web.json_response({"error": "тело запроса — PCM float32 (16 кГц, моно)"},
                                 status=400)
    audio = np.frombuffer(raw, dtype="<f4")
    try:
        async with TEXT_SLOTS:
            t = await asyncio.to_thread(asr_fast.text, audio)
    except Exception as e:
        logger.exception("ASR /v1/text")
        return web.json_response({"error": f"{type(e).__name__}: {e}"}, status=500)
    return web.json_response({"text": t})


async def main():
    # Модели греем в фоне: порт открывается сразу (как в main.py)
    asyncio.create_task(asyncio.to_thread(transcriber.warmup))
    asyncio.create_task(asyncio.to_thread(asr_fast.warmup))

    # PCM-фрагменты хайлайтов: 45 сек float32 ≈ 2.9 МБ; берём с запасом
    app = web.Application(client_max_size=100 * 1024 * 1024)
    app.router.add_get("/health", health)
    app.router.add_post("/v1/words", words)
    app.router.add_post("/v1/text", text)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, ASR_HOST, ASR_PORT)
    await site.start()
    print(f"✅ ASR-сервис на {ASR_HOST}:{ASR_PORT} "
          f"(субтитры: {WHISPER_MODEL}, хайлайты: {HL_WHISPER_MODEL}) — грею модели…",
          flush=True)
    try:
        while True:
            await asyncio.sleep(3600)
    finally:
        await runner.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
