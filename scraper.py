import asyncio
import logging

from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout

from config import HEADLESS, MAX_CONCURRENT_CHECKS, BROWSER

_playwright = None
_browser = None
_semaphore = asyncio.Semaphore(MAX_CONCURRENT_CHECKS)


async def get_browser():
    global _playwright, _browser
    if _playwright is None:
        _playwright = await async_playwright().start()
        bt = _playwright.chromium if BROWSER == "chromium" else _playwright.firefox
        _browser = await bt.launch(headless=HEADLESS, slow_mo=100)
        logging.info(f"✅ Browser {BROWSER} запущен")
    return _browser


async def close_browser():
    global _browser, _playwright
    if _browser:
        await _browser.close()
    if _playwright:
        await _playwright.stop()


def _route_url(from_station: str, to_station: str, date: str) -> str:
    return f"https://pass.rw.by/ru/route/?from={from_station}&to={to_station}&date={date}"


async def _fetch_trains_sync(from_station: str, to_station: str, date: str, retries: int = 3) -> list:
    url = _route_url(from_station, to_station, date)
    
    for attempt in range(1, retries + 1):
        context = None
        try:
            browser = await get_browser()
            context = await browser.new_context()
            page = await context.new_page()
            
            await page.goto(url, wait_until="domcontentloaded", timeout=45000)
            await page.wait_for_timeout(5000)  # даём время на загрузку JS
            
            rows = await page.query_selector_all(".sch-table__row-wrap")
            
            trains = []
            for row in rows:
                train = await _parse_train_row(row)
                if train:
                    trains.append(train)
            
            if trains:
                logging.info(f"✅ Найдено {len(trains)} поездов")
                return trains
                
        except Exception as e:
            logging.warning(f"Попытка {attempt}: {type(e).__name__}")
        finally:
            if context:
                await context.close()
                
        await asyncio.sleep(2)
    
    return []


async def _parse_train_row(row):
    try:
        number = await _get_text(row, ".train-number")
        if not number:
            return None
        return {
            "number": number,
            "departure": await _get_text(row, ".train-from-time"),
            "arrival": await _get_text(row, ".train-to-time"),
            "duration": await _get_text(row, ".train-duration-time"),
        }
    except:
        return None


async def _get_text(element, selector):
    try:
        el = await element.query_selector(selector)
        return (await el.inner_text()).strip() if el else ""
    except:
        return ""


async def _check_tickets_sync(from_station, to_station, date, train_num):
    # (упрощённая версия - можно доработать позже)
    url = _route_url(from_station, to_station, date)
    return {"status": "no_tickets", "url": url, "items": []}  # временно


async def fetch_trains_list(from_station: str, to_station: str, date: str, retries: int = 3):
    async with _semaphore:
        return await _fetch_trains_sync(from_station, to_station, date, retries)


async def check_tickets(from_station: str, to_station: str, date: str, train_num: str):
    async with _semaphore:
        return await _check_tickets_sync(from_station, to_station, date, train_num)