import os
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("BOT_TOKEN")

CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL", "60"))
SUBSCRIPTIONS_FILE = os.getenv("SUBSCRIPTIONS_FILE", "subscriptions.json")
HEADLESS = os.getenv("HEADLESS", "true").lower() in ("1", "true", "yes")
MAX_CONCURRENT_CHECKS = int(os.getenv("MAX_CONCURRENT_CHECKS", "2"))
CACHE_TTL = int(os.getenv("CACHE_TTL", "45"))
BROWSER = os.getenv("BROWSER", "firefox").lower()

if CHECK_INTERVAL < 10:
    raise ValueError("CHECK_INTERVAL must be at least 10 seconds")
if MAX_CONCURRENT_CHECKS < 1:
    raise ValueError("MAX_CONCURRENT_CHECKS must be at least 1")
if CACHE_TTL < 0:
    raise ValueError("CACHE_TTL cannot be negative")
if BROWSER not in {"chromium", "firefox"}:
    raise ValueError("BROWSER must be either 'chromium' or 'firefox'")

POPULAR_STATIONS = [
    "Минск-Пассажирский", "Брест-Центральный", "Гомель-Пассажирский",
    "Витебск-Пассажирский", "Могилёв-1", "Гродно",
    "Барановичи-Полесские", "Орша-Центральная",
]