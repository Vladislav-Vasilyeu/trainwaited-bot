import asyncio
import logging
import re
import time
from urllib.parse import urlencode

from playwright.async_api import TimeoutError as PlaywrightTimeout
from playwright.async_api import async_playwright

from config import BROWSER, CACHE_TTL, HEADLESS, MAX_CONCURRENT_CHECKS

_playwright = None
_browser = None
_context = None
_browser_lock = None
_semaphore = asyncio.Semaphore(MAX_CONCURRENT_CHECKS)
_cache: dict[tuple, tuple[float, dict]] = {}


class RailwayVerificationError(RuntimeError):
    pass


class StationLookupError(RuntimeError):
    pass


CAR_TYPE_CODES = {
    "platzkart": "3",
    "coupe": "4",
}


def parse_station_suggestions(raw_suggestions: object) -> list[dict[str, str]]:
    if not isinstance(raw_suggestions, list):
        raise StationLookupError("Railway site returned invalid station suggestions")

    suggestions = []
    for item in raw_suggestions:
        if not isinstance(item, dict):
            continue
        label = str(item.get("label") or "").strip()
        value = str(item.get("value") or "").strip()
        exp = str(item.get("exp") or "").strip()
        if label and value and exp:
            suggestions.append({"label": label, "value": value, "exp": exp})
    return suggestions


async def get_context():
    global _playwright, _browser, _context, _browser_lock
    if _browser_lock is None:
        _browser_lock = asyncio.Lock()
    async with _browser_lock:
        if _context is None:
            _playwright = await async_playwright().start()
            bt = _playwright.chromium if BROWSER == "chromium" else _playwright.firefox
            _browser = await bt.launch(headless=HEADLESS)
            _context = await _browser.new_context(
                locale="ru-RU",
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                ),
            )
            await _context.route(
                "**/*",
                lambda route: route.abort()
                if route.request.resource_type in ("image", "media", "font")
                else route.continue_(),
            )
            logging.info("Browser %s ready", BROWSER)
        return _context


async def close_browser():
    global _browser, _playwright, _context, _browser_lock
    if _browser_lock is None:
        return
    async with _browser_lock:
        try:
            if _context:
                await _context.close()
        finally:
            _context = None
            try:
                if _browser:
                    await _browser.close()
            finally:
                _browser = None
                try:
                    if _playwright:
                        await _playwright.stop()
                finally:
                    _playwright = None


def _route_url(
    from_station: str,
    to_station: str,
    date: str,
    from_exp: str | None = None,
    to_exp: str | None = None,
) -> str:
    params = {"from": from_station, "to": to_station, "date": date}
    if from_exp:
        params["from_exp"] = from_exp
    if to_exp:
        params["to_exp"] = to_exp
    query = urlencode(params)
    return f"https://pass.rw.by/ru/route/?{query}"


def _cache_key(
    from_station,
    to_station,
    date,
    train_num,
    car_type,
    seat_filter,
    from_exp=None,
    to_exp=None,
):
    return (
        from_station,
        to_station,
        date,
        train_num,
        car_type or "",
        seat_filter or "",
        from_exp or "",
        to_exp or "",
    )


def count_matching_seats(seats: dict[str, int], seat_filter: str | None) -> int:
    if not seat_filter or seat_filter == "any":
        return sum(seats.values())
    if seat_filter not in {
        "lower",
        "lower_any",
        "upper",
        "upper_any",
        "lower_side",
        "upper_side",
        "side_any",
    }:
        return 0

    total = 0
    for label, count in seats.items():
        normalized = label.casefold()
        is_lower = normalized.startswith("нижние")
        is_upper = normalized.startswith("верхние")
        is_side = "боковые" in normalized
        if seat_filter == "lower_any" and is_lower:
            total += count
        elif seat_filter == "upper_any" and is_upper:
            total += count
        elif seat_filter == "side_any" and is_side:
            total += count
        elif seat_filter == "lower" and is_lower and not is_side:
            total += count
        elif seat_filter == "upper" and is_upper and not is_side:
            total += count
        elif seat_filter == "lower_side" and is_lower and is_side:
            total += count
        elif seat_filter == "upper_side" and is_upper and is_side:
            total += count
    return total


async def _wait_for_schedule(page) -> None:
    if (await page.title()).strip().casefold() == "verification":
        raise RailwayVerificationError("Railway website returned a verification page")

    try:
        await page.wait_for_selector(".sch-table__row-wrap", timeout=20000)
    except PlaywrightTimeout:
        if (await page.title()).strip().casefold() == "verification":
            raise RailwayVerificationError("Railway website returned a verification page")
        return
    try:
        await page.wait_for_selector(
            ".sch-table__no-info, .sch-table__t-item, .sch-table__tickets",
            timeout=15000,
        )
    except PlaywrightTimeout:
        await page.wait_for_timeout(1500)


async def search_stations(query: str) -> list[dict[str, str]]:
    query = query.strip()
    if len(query) < 2:
        return []

    page = None
    try:
        async with _semaphore:
            context = await get_context()
            page = await context.new_page()
            await page.goto(
                "https://pass.rw.by/ru/route/",
                wait_until="domcontentloaded",
                timeout=45000,
            )
            if (await page.title()).strip().casefold() == "verification":
                raise RailwayVerificationError(
                    "Railway website returned a verification page"
                )

            selector = "#one-way-raspFormFromTitle"
            await page.locator(selector).fill(query)
            try:
                await page.wait_for_function(
                    """selector => {
                        const input = document.querySelector(selector);
                        const $ = window.jQuery;
                        const widget = input && $ && $(input).autocomplete("instance");
                        return widget && widget.term === input.value && widget.pending === 0;
                    }""",
                    arg=selector,
                    timeout=10000,
                )
            except PlaywrightTimeout as error:
                if (await page.title()).strip().casefold() == "verification":
                    raise RailwayVerificationError(
                        "Railway website returned a verification page"
                    ) from error
                raise StationLookupError(
                    "Railway station suggestions did not finish loading"
                ) from error

            raw_suggestions = await page.evaluate(
                """selector => {
                    const $ = window.jQuery;
                    const widget = $(selector).autocomplete("instance");
                    return widget.menu.element
                        .find("li.ui-menu-item")
                        .map((_, element) => $(element).data("ui-autocomplete-item"))
                        .get()
                        .filter(Boolean);
                }""",
                selector,
            )
            return parse_station_suggestions(raw_suggestions)
    except (RailwayVerificationError, StationLookupError):
        raise
    except Exception as error:
        logging.warning("Station lookup failed: %s", type(error).__name__)
        raise StationLookupError("Could not load railway station suggestions") from error
    finally:
        if page:
            await page.close()


async def _get_text(element, selector: str) -> str:
    try:
        el = await element.query_selector(selector)
        return (await el.inner_text()).strip() if el else ""
    except Exception:
        return ""


async def _parse_train_row(row) -> dict | None:
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
    except Exception:
        return None


async def _parse_ticket_items(cell4) -> list[dict]:
    items = await cell4.query_selector_all(".sch-table__t-item")
    ticket_items = []
    for item in items:
        try:
            type_name = await _get_text(item, ".sch-table__t-name")
            quant_elem = await item.query_selector(".sch-table__t-quant span")
            quantity = (await quant_elem.inner_text()).strip() if quant_elem else "?"
            price = await _get_text(item, ".ticket-cost")
            modal_link = await item.query_selector(".js-train-modal")
            car_type_code = ""
            if modal_link:
                car_type_code = await modal_link.get_attribute("data-car-type") or ""
            if type_name:
                ticket_items.append(
                    {
                        "type": type_name.strip(),
                        "quantity": quantity,
                        "price": price.strip(),
                        "car_type_code": car_type_code,
                    }
                )
        except Exception:
            continue
    return ticket_items


async def _fetch_seat_details(page, row, car_type_code: str) -> dict[str, int]:
    modal_link = await row.query_selector(
        f'.js-train-modal[data-car-type="{car_type_code}"]'
    )
    if not modal_link:
        return {}

    await modal_link.click()
    try:
        await page.wait_for_selector(".carriage-list__places-item", timeout=12000)
    except PlaywrightTimeout:
        await _close_modal(page)
        return {}

    seats: dict[str, int] = {}
    for item in await page.query_selector_all(".carriage-list__places-item"):
        text = (await item.inner_text()).strip()
        match = re.match(r"^(.+?)\s*[-–—]\s*(\d+)$", text)
        if match:
            label = match.group(1).strip()
            seats[label] = seats.get(label, 0) + int(match.group(2))

    await _close_modal(page)
    return seats


async def _close_modal(page) -> None:
    for selector in (
        ".carriage-modal .close",
        ".carriage-modal__close",
        "[data-dismiss='modal']",
        ".modal.in .close",
    ):
        btn = await page.query_selector(selector)
        if btn:
            await btn.click()
            await page.wait_for_timeout(300)
            return
    await page.keyboard.press("Escape")
    await page.wait_for_timeout(300)


async def _find_train_row(page, train_num: str):
    for row in await page.query_selector_all(".sch-table__row-wrap"):
        num_elem = await row.query_selector(".train-number")
        if not num_elem:
            continue
        current_num = (await num_elem.inner_text()).strip()
        if current_num == train_num:
            return row
    return None


async def _check_tickets_sync(
    from_station: str,
    to_station: str,
    date: str,
    train_num: str,
    car_type: str | None = None,
    seat_filter: str | None = None,
    retries: int = 3,
    from_exp: str | None = None,
    to_exp: str | None = None,
) -> dict:
    url = _route_url(from_station, to_station, date, from_exp, to_exp)
    car_type_code = CAR_TYPE_CODES.get(car_type or "")

    for attempt in range(1, retries + 1):
        page = None
        try:
            context = await get_context()
            page = await context.new_page()
            await page.goto(url, wait_until="domcontentloaded", timeout=45000)
            await _wait_for_schedule(page)

            row = await _find_train_row(page, train_num)
            if not row:
                return {"status": "train_not_found", "url": url, "items": [], "seats": {}}

            cell4 = await row.query_selector(".sch-table__cell.cell-4")
            if not cell4:
                return {"status": "error", "url": url, "items": [], "seats": {}}

            if await cell4.query_selector(".sch-table__no-info"):
                return {"status": "no_tickets", "url": url, "items": [], "seats": {}}

            ticket_items = await _parse_ticket_items(cell4)
            if not ticket_items:
                return {"status": "no_tickets", "url": url, "items": [], "seats": {}}

            if car_type_code:
                ticket_items = [
                    item
                    for item in ticket_items
                    if item.get("car_type_code") == car_type_code
                ]
                if not ticket_items:
                    return {"status": "no_tickets", "url": url, "items": [], "seats": {}}

            seats: dict[str, int] = {}
            if seat_filter and seat_filter != "any":
                code = car_type_code or ticket_items[0].get("car_type_code", "3")
                seats = await _fetch_seat_details(page, row, code)
                matched = count_matching_seats(seats, seat_filter)
                if matched <= 0:
                    return {
                        "status": "no_matching_seats",
                        "url": url,
                        "items": ticket_items,
                        "seats": seats,
                        "matched_seats": 0,
                    }
                return {
                    "status": "tickets",
                    "url": url,
                    "items": ticket_items,
                    "seats": seats,
                    "matched_seats": matched,
                }

            return {"status": "tickets", "url": url, "items": ticket_items, "seats": seats}

        except RailwayVerificationError:
            logging.warning("Ticket check blocked by railway-site verification")
            return {"status": "page_error", "url": url, "items": [], "seats": {}}
        except Exception as e:
            logging.warning("Ticket check attempt %s: %s", attempt, type(e).__name__)
        finally:
            if page:
                await page.close()

        await asyncio.sleep(min(attempt * 2, 6))

    return {"status": "error", "url": url, "items": [], "seats": {}}


async def _fetch_trains_sync(
    from_station: str,
    to_station: str,
    date: str,
    retries: int = 3,
    from_exp: str | None = None,
    to_exp: str | None = None,
) -> list:
    url = _route_url(from_station, to_station, date, from_exp, to_exp)

    for attempt in range(1, retries + 1):
        page = None
        try:
            context = await get_context()
            page = await context.new_page()
            await page.goto(url, wait_until="domcontentloaded", timeout=45000)
            await _wait_for_schedule(page)

            trains = []
            for row in await page.query_selector_all(".sch-table__row-wrap"):
                train = await _parse_train_row(row)
                if train:
                    trains.append(train)

            if trains:
                logging.info("Found %s trains", len(trains))
                return trains

        except RailwayVerificationError:
            raise
        except Exception as e:
            logging.warning("Train list attempt %s: %s", attempt, type(e).__name__)
        finally:
            if page:
                await page.close()

        await asyncio.sleep(min(attempt * 2, 6))

    return []


async def fetch_trains_list(
    from_station: str,
    to_station: str,
    date: str,
    retries: int = 3,
    from_exp: str | None = None,
    to_exp: str | None = None,
):
    async with _semaphore:
        return await _fetch_trains_sync(
            from_station,
            to_station,
            date,
            retries,
            from_exp=from_exp,
            to_exp=to_exp,
        )


async def check_tickets(
    from_station: str,
    to_station: str,
    date: str,
    train_num: str,
    car_type: str | None = None,
    seat_filter: str | None = None,
    from_exp: str | None = None,
    to_exp: str | None = None,
):
    key = _cache_key(
        from_station, to_station, date, train_num, car_type, seat_filter, from_exp, to_exp
    )
    now = time.monotonic()
    if len(_cache) > 1000:
        for cached_key, (cached_at, _) in list(_cache.items()):
            if now - cached_at >= CACHE_TTL:
                del _cache[cached_key]
    cached = _cache.get(key)
    if cached and now - cached[0] < CACHE_TTL:
        return cached[1]

    async with _semaphore:
        result = await _check_tickets_sync(
            from_station,
            to_station,
            date,
            train_num,
            car_type=car_type,
            seat_filter=seat_filter,
            from_exp=from_exp,
            to_exp=to_exp,
        )

    if result.get("status") != "error":
        _cache[key] = (time.monotonic(), result)
        if len(_cache) > 1000:
            oldest_key = min(_cache, key=lambda cached_key: _cache[cached_key][0])
            del _cache[oldest_key]
    return result
