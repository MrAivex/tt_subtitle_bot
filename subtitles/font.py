# subtitles/font.py
"""Шрифт субтитров: где лежит файл, какой размер для кадра, как мерить текст."""
from functools import cached_property
from pathlib import Path

from PIL import ImageFont


class SubtitleFont:
    def __init__(self, fonts_dir=None):
        # по умолчанию папка fonts/ лежит в корне проекта (рядом с app.py)
        root = Path(__file__).resolve().parent.parent
        base = Path(fonts_dir) if fonts_dir else root / "fonts"
        self._candidates = [
            base / "roboto-bold.ttf",
            base / "arial.ttf",
            Path("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"),
            Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
            Path("/usr/share/fonts/truetype/ubuntu/Ubuntu-R.ttf"),
        ]

    @cached_property
    def path(self) -> str:
        for p in self._candidates:
            if p.exists():
                return str(p)
        return "arial.ttf"

    @property
    def directory(self) -> str:
        return str(Path(self.path).parent)

    @staticmethod
    def size_for(video_w: int, video_h: int) -> int:
        """Размер шрифта от размера кадра: вертикальное — от ширины, горизонтальное — от высоты."""
        fs = round(video_w * 0.06) if video_h > video_w else round(video_h * 0.05)
        return max(fs, 18)

    def load(self, size: int) -> ImageFont.FreeTypeFont:
        return ImageFont.truetype(self.path, size)

    def describe(self, size: int) -> tuple:
        """(название семейства, жирный ли) — нужно для строки Style в ASS."""
        family, style = self.load(size).getname()
        return family, "bold" in (style or "").lower()
