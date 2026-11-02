# highlight_states.py
"""Хранит временное состояние пользователей в процессе поиска хайлайтов."""

# {user_id: {"video_path": str, "moments": list, "chat_id": int}}
_user_states = {}

def set_state(user_id: int, chat_id: int, video_path: str, moments: list):
    _user_states[user_id] = {
        "chat_id": chat_id,
        "video_path": video_path,
        "moments": moments
    }

def get_state(user_id: int):
    return _user_states.get(user_id)

def clear_state(user_id: int):
    _user_states.pop(user_id, None)