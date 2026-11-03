from typing import Dict, List, Optional

class SessionState:
    def __init__(self, chat_id: int, stage: str, video_path: str = "", moments: Optional[List[Dict]] = None):
        self.chat_id = chat_id
        self.stage = stage  # "awaiting_video" или "awaiting_selection"
        self.video_path = video_path
        self.moments = moments or []

class SessionManager:
    def __init__(self):
        self._states: Dict[int, SessionState] = {}

    def set_awaiting_video(self, user_id: int, chat_id: int):
        self._states[user_id] = SessionState(chat_id=chat_id, stage="awaiting_video")

    def set_awaiting_selection(self, user_id: int, chat_id: int, video_path: str, moments: List[Dict]):
        self._states[user_id] = SessionState(
            chat_id=chat_id, 
            stage="awaiting_selection", 
            video_path=video_path, 
            moments=moments
        )

    def get_state(self, user_id: int) -> Optional[SessionState]:
        return self._states.get(user_id)

    def clear_state(self, user_id: int):
        self._states.pop(user_id, None)