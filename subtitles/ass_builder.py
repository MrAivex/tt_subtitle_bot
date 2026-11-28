# subtitles/ass_builder.py
"""Генерация ASS: слова вылетают снизу вверх, активное слово подсвечено плашкой.

Два режима: animated=True — караоке-вылет слов с бегущей плашкой (как было);
animated=False — статичные строки на плашке (без анимации). Цвет плашки
(параметр color, «#RRGGBB») настраивается пользователем в приложении.
"""
import re
from dataclasses import dataclass
from typing import Callable, List

# ---- анимация субтитров ----
ANIM_SEC = 0.32       # сколько слово «вылетает»
RISE_K = 0.55         # стартует ниже на столько размеров шрифта
EASE_STEPS = 5        # на сколько линейных отрезков режется кривая замедления
FADE_K = 1.7          # во сколько раз проявление быстрее движения
LINE_TAIL = 0.25      # сколько строка висит после последнего слова
LINE_FADE_OUT = 0.15  # плавное исчезновение строки
STATIC_FADE_IN = 0.15 # статичный режим: проявление строки

# ---- цвет плашки ----
DEFAULT_BOX_COLOR = "#9D4EDD"      # фиолетовая, как всегда
_HEX_RE = re.compile(r"^#?[0-9a-fA-F]{6}$")

# расположение субтитров (pos): якорь ASS и y-координата строки
#   bottom — низ по центру (an2), middle — центр кадра (an5), top — верх по центру (an8)
VALID_POS = ("bottom", "middle", "top")


def ass_box_color(hex_color: str) -> str:
    """'#RRGGBB' → '&H00BBGGRR'. ASS хранит цвета BGR с альфой впереди."""
    h = (hex_color or "").lstrip("#")
    if not _HEX_RE.match("#" + h):          # чужой формат — дефолт
        h = DEFAULT_BOX_COLOR.lstrip("#")
    r, g, b = h[0:2], h[2:4], h[4:6]
    return f"&H00{b}{g}{r}"


def _ease_out(p: float) -> float:
    return 1 - (1 - p) ** 2


def _ass_alpha(v: float) -> str:
    return f"&H{max(0, min(255, int(round(v)))):02X}&"


def _ass_time(t: float) -> str:
    cs = int(round(max(0.0, t) * 100))
    h, cs = divmod(cs, 360000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _ass_escape(text: str) -> str:
    """Убираем символы, которые ASS считает управляющими."""
    return text.replace("\\", "").replace("{", "(").replace("}", ")")


@dataclass(frozen=True)
class _Layout:
    """Все размеры, зависящие от кадра, считаются один раз."""
    w: int
    h: int
    family: str
    bold: int
    fs: int
    stroke: int
    pad: int
    margin_v: int
    wm_fs: int
    cx: float
    cy: float
    an: int                # якорь ASS: 2 низ / 5 центр / 8 верх
    off: tuple          # смещение вниз в узлах кривой вылета


class AssBuilder:
    def __init__(self, font, watermark_text: str = "@tt_subtitle_bot"):
        self.font = font
        self._wm = watermark_text
        # узлы кривой вылета по времени -> прозрачность (смещение зависит от кадра и лежит в _Layout)
        self._nodes = [k / EASE_STEPS for k in range(EASE_STEPS + 1)]
        self._alp = [255 * (1 - min(1.0, p * FADE_K)) for p in self._nodes]

    # ---------- публичный API ----------
    def build(self, lines: List, video_w: int, video_h: int, duration: float,
              watermark: bool, color: str = None, animated: bool = True,
              pos: str = "bottom") -> str:
        lay = self._layout(video_w, video_h, pos)
        out = self._header(lay, ass_box_color(color or DEFAULT_BOX_COLOR))
        for li, line in enumerate(lines):
            nxt = lines[li + 1] if li + 1 < len(lines) else None
            out += (self._line_events(lay, line, nxt) if animated
                    else self._static_line_events(lay, line, nxt))
        if watermark:
            out.append(self._watermark(duration))
        return "\n".join(out) + "\n"

    # ---------- части ----------
    def _layout(self, w: int, h: int, pos: str = "bottom") -> _Layout:
        fs = self.font.size_for(w, h)
        family, bold = self.font.describe(fs)
        margin_v = max(40, round(h * 0.07))                 # отступ от края (снизу или сверху)
        an, cy = {"bottom": (2, h - margin_v),
                  "middle": (5, h / 2),
                  "top": (8, margin_v)}[pos if pos in VALID_POS else "bottom"]
        rise = fs * RISE_K
        return _Layout(
            w=w, h=h, family=family, bold=-1 if bold else 0, fs=fs,
            stroke=max(2, round(fs / 18)),                  # обводка текста
            pad=max(4, round(fs * 0.16)),                   # «поля» плашки вокруг слова
            margin_v=margin_v,
            wm_fs=max(14, round(fs * 0.78)),
            cx=w / 2, cy=cy, an=an,                         # якорь строки: по центру
            off=tuple(rise * (1 - _ease_out(p)) for p in self._nodes),
        )

    @staticmethod
    def _header(L: _Layout, box_color: str) -> List[str]:
        b = L.bold
        return [
            "[Script Info]",
            "ScriptType: v4.00+",
            f"PlayResX: {L.w}",
            f"PlayResY: {L.h}",
            "WrapStyle: 2",
            "ScaledBorderAndShadow: yes",
            "",
            "[V4+ Styles]",
            "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
            "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, "
            "Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
            # Подложка: заливка текста прозрачна, «обводка» = цветная плашка (BorderStyle=3)
            f"Style: Box,{L.family},{L.fs},&HFFFFFFFF,&HFFFFFFFF,{box_color},&H00000000,",
            f"{b},0,0,0,100,100,0,0,3,{L.pad},0,2,10,10,{L.margin_v},1",
            # Текст: белый с чёрной обводкой
            f"Style: Text,{L.family},{L.fs},&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,",
            f"{b},0,0,0,100,100,0,0,1,{L.stroke},0,2,10,10,{L.margin_v},1",
            # Водяной знак: слева внизу, ~60% непрозрачности
            f"Style: Mark,{L.family},{L.wm_fs},&H66FFFFFF,&H66FFFFFF,&H66000000,&H00000000,",
            f"{b},0,0,0,100,100,0,0,1,{L.stroke},0,1,20,20,20,1",
            "",
            "[Events]",
            "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
        ]

    def _watermark(self, duration: float) -> str:
        return (f"Dialogue: 2,{_ass_time(0)},{_ass_time(duration + 1)},"
                f"Mark,,0,0,0,,{self._wm}")

    def _fly(self, L: _Layout, layer: int, style: str, t0: float, anim: float,
             t_stop: float, text_for: Callable) -> List[str]:
        """Анимация слова: EASE_STEPS коротких событий с \\move, режется по t_stop."""
        out = []
        for k in range(EASE_STEPS):
            s = t0 + self._nodes[k] * anim
            e = min(t0 + self._nodes[k + 1] * anim, t_stop)
            if e - s < 0.005:
                continue
            move = (f"{{\\an{L.an}\\move({L.cx:.1f},{L.cy + L.off[k]:.1f},"
                    f"{L.cx:.1f},{L.cy + L.off[k + 1]:.1f})}}")
            out.append(f"Dialogue: {layer},{_ass_time(s)},{_ass_time(e)},{style},,0,0,0,,"
                       f"{move}{text_for(self._alp[k], self._alp[k + 1])}")
        return out

    @staticmethod
    def _text_fn(words: List[str], i: int) -> Callable:
        """Слово i вылетает, остальные невидимы, но держат раскладку строки."""
        def fn(a0, a1):
            return " ".join(
                (f"{{\\alpha{_ass_alpha(a0)}\\t(\\alpha{_ass_alpha(a1)})}}" if j == i
                 else "{\\alpha&HFF&}") + wd
                for j, wd in enumerate(words))
        return fn

    @staticmethod
    def _box_fn(words: List[str], i: int) -> Callable:
        """Плашка проявляется только под словом i."""
        def fn(a0, a1):
            return " ".join(
                (f"{{\\3a{_ass_alpha(a0)}\\t(\\3a{_ass_alpha(a1)})}}" if j == i
                 else "{\\3a&HFF&}") + wd
                for j, wd in enumerate(words))
        return fn

    @staticmethod
    def _timing(line, next_line):
        """Моменты появления слов, длительности вылета и конец строки."""
        ws = line.words
        n = len(ws)
        t = []                                   # моменты появления слов (не убывают)
        for w in ws:
            t.append(max(w.start, t[-1] if t else 0.0))

        # Строка не живёт дольше начала следующей, иначе строки наложатся друг на друга
        hard_end = 1e9
        if next_line is not None:
            hard_end = max(line.end, next_line.words[0].start)
        # Последнему слову сокращаем полёт, если следующая строка начнётся скоро
        an = [ANIM_SEC] * n
        if hard_end < 1e8:
            an[-1] = min(ANIM_SEC, max(0.12, hard_end - t[-1] - 0.02))
        line_end = min(max(line.end + LINE_TAIL, t[-1] + an[-1] + 0.10), hard_end)
        return t, an, line_end

    def _static_line_events(self, L: _Layout, line, next_line) -> List[str]:
        """Без анимации: строка появляется целиком (текст + плашка) и мягко гаснет."""
        ws = line.words
        if not ws:
            return []
        words = [_ass_escape(w.word) for w in ws]
        t, _an, line_end = self._timing(line, next_line)
        start = t[0]
        pos = f"{{\\an{L.an}\\pos({L.cx:.1f},{L.cy:.1f})}}"
        fad = f"{{\\fad({int(STATIC_FADE_IN * 1000)},{int(LINE_FADE_OUT * 1000)})}}"
        text = " ".join(words)
        if line_end - start < 0.05:                 # защита от мгновенных строк
            line_end = start + 0.05
        return [
            f"Dialogue: 0,{_ass_time(start)},{_ass_time(line_end)},Box,,0,0,0,,{pos}{fad}{text}",
            f"Dialogue: 1,{_ass_time(start)},{_ass_time(line_end)},Text,,0,0,0,,{pos}{fad}{text}",
        ]

    def _line_events(self, L: _Layout, line, next_line) -> List[str]:
        ws = line.words
        n = len(ws)
        words = [_ass_escape(w.word) for w in ws]
        t, an, line_end = self._timing(line, next_line)
        pos = f"{{\\an{L.an}\\pos({L.cx:.1f},{L.cy:.1f})}}"

        out: List[str] = []
        for i in range(n):
            # 1) текст: слово i вылетает
            out += self._fly(L, 1, "Text", t[i], an[i], line_end, self._text_fn(words, i))

            # 2) текст: слова 0..i стоят на месте
            s0 = t[i] + an[i]
            e0 = min(t[i + 1] + an[i + 1] if i + 1 < n else line_end, line_end)
            if e0 - s0 >= 0.01:
                parts = [("{\\alpha&H00&}" if j <= i else "{\\alpha&HFF&}") + wd
                         for j, wd in enumerate(words)]
                fad = f"{{\\fad(0,{int(LINE_FADE_OUT * 1000)})}}" if i == n - 1 else ""
                out.append(f"Dialogue: 1,{_ass_time(s0)},{_ass_time(e0)},Text,,0,0,0,,"
                           f"{pos}{fad}{' '.join(parts)}")

            # 3) плашка активного слова: летит вместе со словом, потом стоит до его конца
            next_start = ws[i + 1].start if i + 1 < n else None
            hl_end = (ws[i].end if next_start is None
                      else min(next_start, max(ws[i].end + 0.3, ws[i].start + 0.05)))
            hl_end = min(max(hl_end, t[i] + 0.05), line_end)
            out += self._fly(L, 0, "Box", t[i], an[i], hl_end, self._box_fn(words, i))
            if hl_end - s0 >= 0.01:
                parts = [("{\\3a&H00&}" if j == i else "{\\3a&HFF&}") + wd
                         for j, wd in enumerate(words)]
                out.append(f"Dialogue: 0,{_ass_time(s0)},{_ass_time(hl_end)},Box,,0,0,0,,"
                            f"{pos}{' '.join(parts)}")
        return out
