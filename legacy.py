"""legacy.py — ВРЕМЕННЫЙ адаптер.

Когда HighlightAnalyzer будет готов, в app.py меняется одна строка, а этот файл удаляется.
"""
from highlights.analyzer import HighlightAnalyzer


class LegacyAnalyzer(HighlightAnalyzer):
    """Просто переименование — чтобы не менять app.py."""
    pass
