# core/words.py
"""Общая модель слова: её производит Transcriber и потребляют субтитры."""
from dataclasses import dataclass


@dataclass(frozen=True)
class Word:
    word: str
    start: float
    end: float
