# core/transcriber.py
"""Whisper: единственное место, где распознаётся речь.

words() — для субтитров (слова с таймингами), text() — для поиска хайлайтов.
"""
import logging
import re
import threading
from typing import List

import numpy as np
from faster_whisper import WhisperModel

from utils import timed
from .words import Word

log = logging.getLogger("timing")

# Типичные галлюцинации Whisper на шуме/тишине (подписи из обучающих данных)
_HALLUCINATION_RE = re.compile(
    r"субтитр|корректор|dimatorzok|продолжение следует", re.IGNORECASE)


class Transcriber:
    def __init__(self, device: str = "cpu", model_size: str = "small"):
        self.device = device
        self.model_size = model_size
        self._model = None
        self._lock = threading.Lock()      # сканирование и рендер могут запросить модель одновременно

    @property
    def model(self) -> WhisperModel:
        """Ленивая загрузка: модель создаётся один раз при первом обращении."""
        if self._model is None:
            with self._lock:
                if self._model is None:
                    compute_type = "float16" if self.device == "cuda" else "int8"
                    self._model = WhisperModel(self.model_size, device=self.device,
                                               compute_type=compute_type, cpu_threads=2)
        return self._model

    def warmup(self):
        """Прогоняет по одному короткому распознаванию, чтобы первый пользователь не ждал."""
        with timed("whisper: прогрев"):
            audio = (np.random.randn(16000 * 3) * 0.01).astype(np.float32)
            # Сначала без VAD: гонит сам энкодер/декодер. Потом с VAD: подгружает его модель.
            for use_vad in (False, True):
                segs, _ = self.model.transcribe(
                    audio, language="ru", beam_size=1,
                    word_timestamps=True, vad_filter=use_vad,
                )
                list(segs)   # генератор ленивый, без этого ничего не посчитается

    def words(self, wav_path) -> List[Word]:
        """Слова с таймингами для субтитров (галлюцинации отфильтрованы)."""
        with timed("whisper: загрузка модели"):
            model = self.model
        with timed("whisper: распознавание"):
            segments, _ = model.transcribe(
                str(wav_path), language="ru", word_timestamps=True,
                beam_size=1, vad_filter=True, condition_on_previous_text=False,
                temperature=0.0,   # без повторных попыток с нагревом
            )
            seg_list = list(segments)   # генератор ленивый, считается именно здесь
        good = [s for s in seg_list if not self._is_garbage(s)]
        log.info(f"[WHISPER] сегментов={len(seg_list)}→{len(good)}, "
                 f"текст: {' '.join(s.text.strip() for s in good)[:200]!r}")
        return [Word(w.word.strip(), w.start, w.end)
                for seg in good if seg.words for w in seg.words]

    def text(self, audio: np.ndarray) -> str:
        """Просто текст фрагмента — для поиска ключевых слов в хайлайтах."""
        segs, _ = self.model.transcribe(audio, language="ru", beam_size=1, vad_filter=True,
                                        condition_on_previous_text=False, temperature=0.0)
        return " ".join(s.text.strip() for s in segs if not self._is_garbage(s))

    @staticmethod
    def _is_garbage(seg) -> bool:
        """Галлюцинации Whisper на шуме: 'ООООО...', зацикленный текст, фразы-подписи."""
        text = seg.text.strip()
        if not text:
            return True
        if re.search(r"(.)\1{7,}", text):         # один символ 8+ раз подряд
            return True
        if seg.compression_ratio > 2.4:           # сильно «сжимаемый» текст = зацикливание
            return True
        if _HALLUCINATION_RE.search(text):        # «Субтитры сделал ...» и подобное
            return True
        return False
