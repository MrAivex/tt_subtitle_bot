from typing import Dict, List, Optional
from dataclasses import dataclass, field


@dataclass
class ProcessingOptions:
    """Настройки обработки видео."""
    mode: str = "highlights"  # "highlights" или "full"
    has_webcam: bool = False
    has_subtitles: bool = True  # ← НОВОЕ ПОЛЕ
    format: str = "original"    # "original" или "vertical_9_16"
    selected_moments: List[int] = field(default_factory=list)


@dataclass
class SessionState:
    chat_id: int
    stage: str
    video_path: str = ""
    video_token: str = ""
    moments: List[Dict] = field(default_factory=list)
    options: ProcessingOptions = field(default_factory=ProcessingOptions)
    message_id: str = ""
    processing: bool = False
    webcam_box: Optional[Dict] = None  # ← ДЛЯ БУДУЩЕГО: {"x", "y", "w", "h", "confidence"}


class SessionManager:
    def __init__(self):
        self._states: Dict[int, SessionState] = {}

    def set_awaiting_video(self, user_id: int, chat_id: int):
        self._states[user_id] = SessionState(
            chat_id=chat_id,
            stage="awaiting_options"
        )

    def set_video_path(self, user_id: int, video_path: str):
        if state := self._states.get(user_id):
            state.video_path = video_path

    def set_awaiting_moment_selection(self, user_id: int, moments: List[Dict]):
        if state := self._states.get(user_id):
            state.stage = "awaiting_moment_selection"
            state.moments = moments

    def update_options(self, user_id: int, **kwargs):
        if state := self._states.get(user_id):
            for key, value in kwargs.items():
                if hasattr(state.options, key):
                    setattr(state.options, key, value)

    def get_state(self, user_id: int) -> Optional[SessionState]:
        return self._states.get(user_id)

    def clear_state(self, user_id: int):
        state = self._states.pop(user_id, None)
        if state and state.video_path:
            import os
            if os.path.exists(state.video_path):
                os.remove(state.video_path)

    def clear_state_if_same_video(self, user_id: int, video_path: str):
        """Чистит состояние ТОЛЬКО если это та же сессия."""
        state = self._states.get(user_id)
        if state and state.video_path == video_path:
            self.clear_state(user_id)
        else:
            import os
            if os.path.exists(video_path):
                os.remove(video_path)