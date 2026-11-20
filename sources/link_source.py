# sources/link_source.py
from .base import MediaSource
from . import downloader


class LinkSource(MediaSource):
    """YouTube / Twitch / TikTok / Диск. Хранит только ссылку, на диске ничего не держит."""

    def __init__(self, url: str):
        self.url = url
        self.title = ""

    async def prepare_audio(self, out_wav):
        await downloader.download_audio_only(self.url, out_wav)
        self.title = downloader.get_title(self.url)
        return out_wav

    async def cut(self, start, end, out, max_height=None):
        return await downloader.download_section(self.url, start, end, out, max_height or 1080)

    async def full_video(self, out):
        return await downloader.download_by_link(self.url, out)


    async def duration(self):
        return await downloader.get_duration(self.url)
    

    def cleanup(self):
        pass  # ничего не храним на диске
