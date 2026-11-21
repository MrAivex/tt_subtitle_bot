# subtitles/style.py
"""Настройки вида субтитров, которые выбирает пользователь (положение, цвет, анимация)."""
from dataclasses import dataclass, asdict

POSITIONS = ("bottom", "middle", "top")
ANIMS = ("fly", "drop", "fade", "none")
# id -> (цвет текста RRGGBB, цвет плашки активного слова RRGGBB или None, если плашки нет)
COLORS = {
    "violet": ("FFFFFF", "9D4EDD"),
    "pink":   ("FFFFFF", "FF5FA2"),
    "red":    ("FFFFFF", "E5384F"),
    "green":  ("FFFFFF", "1FA971"),
    "yellow": ("FFD23F", None),
    "white":  ("FFFFFF", None),
}
_RISE = {"fly": 1.0, "drop": -1.0, "fade": 0.0, "none": 0.0}


def _ass_color(rgb: str) -> str:
    """RRGGBB -> &H00BBGGRR (порядок байт в ASS обратный)."""
    return f"&H00{rgb[4:6]}{rgb[2:4]}{rgb[0:2]}"


@dataclass(frozen=True)
class SubStyle:
    pos: str = "bottom"
    color: str = "violet"
    anim: str = "fly"

    @classmethod
    def from_dict(cls, d) -> "SubStyle":
        """Берём только известные значения: всё остальное — по умолчанию."""
        d = d if isinstance(d, dict) else {}
        pos, color, anim = d.get("pos"), d.get("color"), d.get("anim")
        return cls(pos if pos in POSITIONS else "bottom",
                   color if color in COLORS else "violet",
                   anim if anim in ANIMS else "fly")

    def as_dict(self) -> dict:
        return asdict(self)

    @property
    def text_ass(self) -> str:
        return _ass_color(COLORS[self.color][0])

    @property
    def plate_ass(self):
        p = COLORS[self.color][1]
        return _ass_color(p) if p else None

    @property
    def rise_dir(self) -> float:
        """+1: слово вылетает снизу, -1: падает сверху, 0: появляется на месте."""
        return _RISE[self.anim]
