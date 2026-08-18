# subscriptions.py
SUBSCRIPTIONS = {
    "default": {
        "name": "Бесплатная",
        "video_limit": 3,
        "price": 0,
        "description": "3 видео в день с водяным знаком",
        "duration_days": 0
    },
    "pro31": {
        "name": "Про, на месяц",
        "video_limit": 100000,
        "price": 299,
        "description": "Без ограничений по количеству видео и без водяного знака",
        "duration_days": 31
    }
}

DEFAULT_SUB = "default"

def get_subscription(sub_id: str):
    """Возвращает данные подписки или default, если не найдена."""
    return SUBSCRIPTIONS.get(sub_id, SUBSCRIPTIONS[DEFAULT_SUB])