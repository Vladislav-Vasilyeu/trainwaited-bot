import json
import logging
import os
import uuid
from datetime import datetime

from config import SUBSCRIPTIONS_FILE

subscriptions: dict[str, list[dict]] = {}


def user_key(user_id: int | str) -> str:
    return str(user_id)


def load_subscriptions() -> None:
    global subscriptions
    if os.path.exists(SUBSCRIPTIONS_FILE):
        try:
            with open(SUBSCRIPTIONS_FILE, encoding="utf-8") as f:
                subscriptions = json.load(f)
            cleanup_expired()
            logging.info("Подписки загружены из %s", SUBSCRIPTIONS_FILE)
        except Exception as e:
            logging.error("Ошибка загрузки подписок: %s", e)
            subscriptions = {}
    else:
        subscriptions = {}


def save_subscriptions() -> None:
    try:
        with open(SUBSCRIPTIONS_FILE, "w", encoding="utf-8") as f:
            json.dump(subscriptions, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logging.error("Ошибка сохранения подписок: %s", e)


def get_user_subs(user_id: int | str) -> list[dict]:
    return subscriptions.get(user_key(user_id), [])


def add_subscription(user_id: int | str, sub: dict) -> None:
    key = user_key(user_id)
    if key not in subscriptions:
        subscriptions[key] = []
    subscriptions[key].append(sub)
    save_subscriptions()


def remove_subscription(user_id: int | str, sub_id: str) -> bool:
    key = user_key(user_id)
    subs = subscriptions.get(key, [])
    for sub in subs[:]:
        if sub["id"] == sub_id:
            subs.remove(sub)
            if not subs:
                del subscriptions[key]
            save_subscriptions()
            return True
    return False


def find_subscription(user_id: int | str, sub_id: str) -> dict | None:
    for sub in get_user_subs(user_id):
        if sub["id"] == sub_id:
            return sub
    return None


def create_subscription(
    user_id: int | str,
    train: str,
    date: str,
    from_station: str,
    to_station: str,
    departure: str = "",
    arrival: str = "",
    duration: str = "",
) -> dict:
    sub = {
        "id": str(uuid.uuid4())[:8],
        "train": train,
        "date": date,
        "from": from_station,
        "to": to_station,
        "departure": departure,
        "arrival": arrival,
        "duration": duration,
        "notified": False,
        "first_check_done": False,
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    add_subscription(user_id, sub)
    return sub


def cleanup_expired() -> None:
    today = datetime.now().date()
    changed = False
    for uid in list(subscriptions.keys()):
        active = []
        for sub in subscriptions[uid]:
            try:
                sub_date = datetime.strptime(sub["date"], "%Y-%m-%d").date()
                if sub_date >= today:
                    active.append(sub)
                else:
                    changed = True
            except (KeyError, ValueError):
                active.append(sub)
        if active:
            subscriptions[uid] = active
        else:
            del subscriptions[uid]
            changed = True
    if changed:
        save_subscriptions()


def active_subscriptions() -> list[tuple[str, dict]]:
    result = []
    for uid, subs in subscriptions.items():
        for sub in subs:
            if not sub.get("notified"):
                result.append((uid, sub))
    return result