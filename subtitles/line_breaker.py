# subtitles/line_breaker.py
"""Разбивка потока слов на строки по реальной ширине текста."""
from dataclasses import dataclass
from typing import List

from core.words import Word


@dataclass
class Line:
    words: List[Word]

    @property
    def start(self) -> float:
        return self.words[0].start

    @property
    def end(self) -> float:
        return self.words[-1].end


class LineBreaker:
    def __init__(self, font, max_width_ratio: float = 0.88):
        self._font = font
        self._ratio = max_width_ratio

    def split(self, words: List[Word], video_w: int, video_h: int) -> List[Line]:
        font = self._font.load(self._font.size_for(video_w, video_h))
        max_width = video_w * self._ratio
        space_w = font.getlength(" ")

        lines, cur, cur_w = [], [], 0.0
        for src in words:
            word = src.word.lower()            # мерим уже в нижнем регистре — так и показываем
            if not word:
                continue
            ww = font.getlength(word)
            gap = space_w if cur else 0.0
            if cur and cur_w + gap + ww > max_width:
                lines.append(Line(cur))
                cur, cur_w, gap = [], 0.0, 0.0
            cur.append(Word(word, src.start, src.end))
            cur_w += gap + ww
        if cur:
            lines.append(Line(cur))
        return lines
