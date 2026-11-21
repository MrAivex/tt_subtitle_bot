# sources/file_source.py
import asyncio
import os

from .base import MediaSource


class FileSource(MediaSource):
    """Видео, загруженное пользователем с устройства."""

    def __init__(self, path: str, title: str, ffmpeg):
        self.path, self.title, self._ff = path, title, ffmpeg

    async def prepare_audio(self, out_wav):
        await asyncio.to_thread(self._ff.extract_wav, self.path, out_wav)
        return out_wav

    async def cut(self, start, end, out, max_height=None):
        if max_height:
            await asyncio.to_thread(self._ff.make_preview, self.path, start, end, out, max_height)
        else:
            await asyncio.to_thread(self._ff.cut_clip, self.path, start, end, out)
        return out


    async def duration(self):
        return await asyncio.to_thread(self._ff.duration, self.path)

    async def full_video(self, out):
        return self.path                 # исходник — не копируем

    def is_temp(self, path):
        return path != self.path         # исходник удалять нельзя

    def cleanup(self):
        if self.path and os.path.exists(self.path):
            try:
                os.remove(self.path)
            except OSError:
                pass

    async def audio_input(self, out_raw):
        return self.path
