"""miniapp/eta.py — оценка времени: base + k * длительность, k подстраивается по факту."""
import json
import os

PATH = "eta.json"
# base (сек, фиксированная часть), k (сек обработки на 1 сек видео)
DEFAULTS = {
    "scan_file": {"base": 90, "k": 0.02},
    "scan_link": {"base": 100, "k": 0.05},
    "clip":      {"base": 10, "k": 1.3},
    "full":      {"base": 20, "k": 1.5},
}


class Eta:
    def __init__(self):
        self.p = {k: dict(v) for k, v in DEFAULTS.items()}
        try:
            with open(PATH, encoding="utf-8") as f:
                for key, v in json.load(f).items():
                    if key in self.p:
                        self.p[key].update(v)
        except (OSError, ValueError):
            pass

    def estimate(self, key: str, sec: float) -> float:
        p = self.p[key]
        return p["base"] + p["k"] * max(sec, 0.0)

    def record(self, key: str, sec: float, took: float):
        """Сдвигаем k к реальному значению (сглаживание 30%), выбросы отсекаем."""
        if sec < 5:
            return
        p = self.p[key]
        real_k = max(0.0, (took - p["base"]) / sec)
        real_k = min(real_k, p["k"] * 4 + 0.5)
        p["k"] = round(0.7 * p["k"] + 0.3 * real_k, 4)
        try:
            with open(PATH, "w", encoding="utf-8") as f:
                json.dump(self.p, f)
        except OSError:
            pass


eta = Eta()