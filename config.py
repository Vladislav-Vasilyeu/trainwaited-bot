import os
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("BOT_TOKEN")
if not TOKEN:
    raise ValueError("Установите переменную окружения BOT_TOKEN")

CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL", "60"))
SUBSCRIPTIONS_FILE = os.getenv("SUBSCRIPTIONS_FILE", "subscriptions.json")
HEADLESS = os.getenv("HEADLESS", "true").lower() in ("1", "true", "yes")
MAX_CONCURRENT_CHECKS = int(os.getenv("MAX_CONCURRENT_CHECKS", "2"))
BROWSER = os.getenv("BROWSER", "firefox").lower()

POPULAR_STATIONS = [
    "Минск-Пассажирский", "Брест-Центральный", "Гомель-Пассажирский",
    "Витебск-Пассажирский", "Могилёв-1", "Гродно",
    "Барановичи-Полесские", "Орша-Центральная",
]