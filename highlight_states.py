# highlight_states.py
"""Временные состояния пользователей в процессе поиска хайлайтов."""

_user_states = {}

def set_awaiting_video(user_id: int, chat_id: int):
    """Пользователь нажал 'Найти хайлайты', ждём от него видео."""
    _user_states[user_id] = {"stage": "awaiting_video", "chat_id": chat_id}

def set_awaiting_selection(user_id: int, chat_id: int, video_path: str, moments: list):
    """Скан готов, ждём выбор моментов номерами."""
    _user_states[user_id] = {
        "stage": "awaiting_selection",
        "chat_id": chat_id,
        "video_path": video_path,
        "moments": moments,
    }

def get_state(user_id: int):
    return _user_states.get(user_id)

def clear_state(user_id: int):
    _user_states.pop(user_id, None)