from collections import deque
from typing import Dict, Deque

user_history: Dict[int, Deque[str]] = {}


def dobavit(user_id: int, message: str) -> None:
    if user_id not in user_history:
        user_history[user_id] = deque(maxlen=5)
    user_history[user_id].append(message)


def historyy(user_id: int) -> str:
    history = user_history.get(user_id, deque())
    if not history:
        return "Здесь пока ничего нет..."
    return "Вот последние 5 запросов:\n" + "\n".join(f"• {msg}" for msg in history)
