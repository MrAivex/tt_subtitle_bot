"""miniapp/tasks.py — фоновые задачи с удержанием ссылок (иначе их может собрать GC)."""
import asyncio

_tasks: set = set()


def spawn(coro) -> asyncio.Task:
    t = asyncio.create_task(coro)
    _tasks.add(t)
    t.add_done_callback(_tasks.discard)
    return t
