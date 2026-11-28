# subtitles/renderer.py
"""Субтитры на видео: звук → Whisper → строки → ASS → ffmpeg.

Каждый шаг — отдельный объект, renderer только руководит порядком.
"""
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from utils import timed


@dataclass
class RenderResult:
    video_path: str
    srt_path: Optional[str] = None      # SRT больше не создаём: мини-апп его не отдаёт


class SubtitleRenderer:
    def __init__(self, ffmpeg, transcriber, breaker, ass):
        self._ff = ffmpeg
        self._transcriber = transcriber
        self._breaker = breaker
        self._ass = ass

    def render(self, src, *, premium: bool, vertical: bool,
               color: str = None, animated: bool = True) -> RenderResult:
        v = Path(src).resolve()
        out = v.with_name(f"{v.stem}_subtitled.mp4")
        wav = v.with_name(f"{v.stem}.wav")
        ass_path = v.with_name(f"{v.stem}.ass")
        try:
            with timed("clip: ffmpeg → wav"):
                self._ff.extract_wav_speech(v, wav)

            words = self._transcriber.words(wav)
            if not words:
                return self._passthrough(v, out, vertical)

            w, h, box = self._frame(v, vertical)          # размер кадра ПОСЛЕ обрезки
            lines = self._breaker.split(words, w, h)
            ass_text = self._ass.build(lines, w, h, self._ff.duration(v),
                                       watermark=not premium, color=color, animated=animated)
            ass_path.write_text(ass_text, encoding="utf-8")

            with timed("clip: рендер ffmpeg"):
                self._ff.burn_ass(v, ass_path, self._ass.font.directory, out, crop_box=box)
            return RenderResult(str(out))
        finally:
            for p in (ass_path, wav):
                if p.exists():
                    p.unlink()

    # ---------- шаги ----------
    def _frame(self, v: Path, vertical: bool):
        w, h = self._ff.resolution(v)
        if not vertical:
            return w, h, None
        box = self._ff.vertical_crop_box(w, h)
        return box[0], box[1], box

    def _passthrough(self, v: Path, out: Path, vertical: bool) -> RenderResult:
        """Речи нет — отдаём видео без субтитров (при необходимости в 9:16)."""
        if vertical:
            self._ff.crop_vertical(v, out)
        else:
            self._ff.copy(v, out)
        return RenderResult(str(out))
