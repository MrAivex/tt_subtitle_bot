# core/remote_transcriber.py
"""HTTP-клиент к asr_service.py. Интерфейс тот же, что у Transcriber.

words()/text() вызываются из рабочих потоков (рендер клипа, scorer.enrich),
поэтому клиент синхронный (requests). Все процессы на одном сервере:
WAV передаём абсолютным путём (гигабайты по HTTP не гоняем),
фрагменты — сырым PCM float32 (45 сек ≈ 2.9 МБ по localhost).
"""
from pathlib import Path
from typing import List

import numpy as np
import requests

from .words import Word


class RemoteTranscriber:
    """Дроп-ин замена Transcriber, когда в .env задан ASR_URL."""

    def __init__(self, base_url: str, token: str = "", timeout: float = 7200.0):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout   # распознавание 30-минутного видео небыстрое — не торопим

    def _headers(self, extra: dict = None) -> dict:
        h = {}
        if self.token:
            h["X-ASR-Token"] = self.token
        if extra:
            h.update(extra)
        return h

    def warmup(self):
        """Модели греет сам asr_service при старте — здесь только проверка связи."""
        r = requests.get(f"{self.base_url}/health", headers=self._headers(), timeout=30)
        r.raise_for_status()

    def words(self, wav_path) -> List[Word]:
        """Слова с таймингами для субтитров (модель для субтитров в asr_service)."""
        path = str(Path(wav_path).resolve())
        r = requests.post(f"{self.base_url}/v1/words", json={"path": path},
                          headers=self._headers(), timeout=self.timeout)
        if r.status_code != 200:
            raise RuntimeError(f"ASR /v1/words {r.status_code}: {r.text[:200]}")
        return [Word(w["word"], float(w["start"]), float(w["end"]))
                for w in r.json()["words"]]

    def text(self, audio: np.ndarray) -> str:
        """Текст фрагмента (модель для хайлайтов в asr_service). audio: float32, 16 кГц, моно."""
        payload = np.ascontiguousarray(audio, dtype="<f4").tobytes()
        r = requests.post(f"{self.base_url}/v1/text", data=payload,
                          headers=self._headers({"Content-Type": "application/octet-stream"}),
                          timeout=self.timeout)
        if r.status_code != 200:
            raise RuntimeError(f"ASR /v1/text {r.status_code}: {r.text[:200]}")
        return r.json()["text"]
