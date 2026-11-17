# sources/base.py
from abc import ABC, abstractmethod


class MediaSource(ABC):
    """Откуда берётся видео. Сервисы miniapp не знают, ссылка это или файл."""
    title: str = ""

    @abstractmethod
    async def prepare_audio(self, out_wav: str) -> str:
        """Положить звук в out_wav (WAV 16 кГц моно)."""

    @abstractmethod
    async def cut(self, start: float, end: float, out: str, max_height: int = None) -> str:
        """Вырезать фрагмент. max_height задан — это превью, иначе полное качество."""

    @abstractmethod
    async def full_video(self, out: str) -> str:
        """Путь к полному видео (для ссылки — скачивает в out)."""

    def is_temp(self, path: str) -> bool:
        """Можно ли удалять файл path после рендера."""
        return True

    def cleanup(self) -> None:
        """Удалить всё, что источник хранит на диске."""
