import asyncio
import logging
from collections import deque
from datetime import datetime
from html import escape
from secrets import token_hex

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import BadRequest
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from config import CHECK_INTERVAL, MAX_CONCURRENT_CHECKS, TIMEZONE, TOKEN
from scraper import (
    RailwayVerificationError,
    StationLookupError,
    check_tickets,
    close_browser,
    fetch_trains_list,
    search_stations,
)
import storage
from storage import (
    active_subscriptions,
    cleanup_expired,
    create_subscription,
    find_subscription,
    get_user_subs,
    load_subscriptions,
    remove_subscription,
)
from ui import (
    BOT_COMMANDS,
    BTN_HELP,
    BTN_MY_SUBS,
    BTN_NEW_SEARCH,
    HELP_TEXT,
    MAIN_KEYBOARD,
    WELCOME_TEXT,
    cancel_keyboard,
    date_calendar_keyboard,
    delete_confirm_keyboard,
    format_subscription_created,
    format_subscriptions_list,
    format_tickets_message,
    format_trains_list,
    main_menu_keyboard,
    parse_preference,
    popular_stations_keyboard,
    preference_label,
    retry_keyboard,
    seat_preference_keyboard,
    station_by_index,
    station_suggestions_keyboard,
    STATION_PAGE_SIZE,
    subscription_created_keyboard,
    subscriptions_list_keyboard,
    tickets_found_keyboard,
    train_schedule_label,
    trains_keyboard,
)

FROM_STATION, TO_STATION, DATE, SELECT_TRAIN, SELECT_PREFERENCE = range(5)
_subscription_checks_in_progress: set[tuple[str, str]] = set()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logging.getLogger("telegram").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("selenium").setLevel(logging.WARNING)
logging.getLogger("WDM").setLevel(logging.WARNING)

async def send_or_edit(update: Update, text: str, reply_markup=None, parse_mode="HTML"):
    """Отправляет или редактирует сообщение в зависимости от типа update."""
    if update.callback_query:
        query = update.callback_query
        try:
            await query.edit_message_text(text, reply_markup=reply_markup, parse_mode=parse_mode)
        except BadRequest as error:
            if "message is not modified" in str(error).lower():
                return
            logging.warning("Could not edit Telegram message; sending a new one: %s", error)
            await query.message.reply_text(text, reply_markup=reply_markup, parse_mode=parse_mode)
    elif update.message:
        await update.message.reply_text(
            text, reply_markup=reply_markup, parse_mode=parse_mode
        )


async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    text = WELCOME_TEXT
    markup = main_menu_keyboard()
    if update.callback_query:
        await update.callback_query.answer()
        await send_or_edit(update, text, markup)
    elif update.message:
        await update.message.reply_text(
            text, reply_markup=markup, parse_mode="HTML"
        )
        await update.message.reply_text(
            "Быстрые действия 👇", reply_markup=MAIN_KEYBOARD
        )
    return ConversationHandler.END


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    if update.message:
        await update.message.reply_text(HELP_TEXT, parse_mode="HTML", reply_markup=MAIN_KEYBOARD)
    return ConversationHandler.END


async def begin_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    text = (
        "📍 <b>Шаг 1 из 3</b> — станция отправления\n\n"
        "Выберите популярную станцию или введите город/вокзал для поиска:"
    )
    markup = popular_stations_keyboard("from")

    if update.callback_query:
        await update.callback_query.answer()
        await send_or_edit(update, text, markup)
    elif update.message:
        await update.message.reply_text(text, reply_markup=markup, parse_mode="HTML")

    return FROM_STATION


def _set_station(
    context: ContextTypes.DEFAULT_TYPE,
    prefix: str,
    value: str,
    label: str | None = None,
    exp: str | None = None,
) -> None:
    context.user_data[f"{prefix}_station"] = value
    context.user_data[f"{prefix}_station_label"] = label or value
    context.user_data[f"{prefix}_station_exp"] = exp
    context.user_data.pop(f"{prefix}_station_suggestions", None)
    context.user_data.pop(f"{prefix}_station_query", None)
    context.user_data.pop(f"{prefix}_station_search_id", None)


def _station_label(context: ContextTypes.DEFAULT_TYPE, prefix: str) -> str:
    return context.user_data.get(
        f"{prefix}_station_label",
        context.user_data.get(f"{prefix}_station", "—"),
    )


def _station_suggestions_text(
    query: str, suggestions: list[dict[str, str]], page: int
) -> str:
    page_count = max(
        1, (len(suggestions) + STATION_PAGE_SIZE - 1) // STATION_PAGE_SIZE
    )
    return (
        f"🔎 По запросу <b>{escape(query)}</b> найдено вариантов: "
        f"<b>{len(suggestions)}</b>.\n"
        "Выберите нужный вокзал или станцию — особенно важно для крупных городов.\n"
        f"Страница {page + 1} из {page_count}:"
    )


async def _search_station_input(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    prefix: str,
) -> int:
    query_text = update.message.text.strip()
    current_state = FROM_STATION if prefix == "from" else TO_STATION
    context.user_data.pop(f"{prefix}_station_suggestions", None)
    context.user_data.pop(f"{prefix}_station_query", None)
    context.user_data.pop(f"{prefix}_station_search_id", None)
    if len(query_text) < 2:
        await update.message.reply_text(
            "Введите не менее двух символов, чтобы найти станцию:",
            reply_markup=cancel_keyboard(),
        )
        return current_state

    progress = await update.message.reply_text(
        f"🔎 Ищу станции по запросу «{escape(query_text)}» на сайте БЖД…",
        parse_mode="HTML",
    )
    try:
        suggestions = await search_stations(query_text)
    except RailwayVerificationError:
        await progress.edit_text(
            "⚠️ Сайт БЖД временно показывает проверочную страницу. "
            "Попробуйте ввести запрос ещё раз чуть позже.",
            reply_markup=cancel_keyboard(),
        )
        return current_state
    except StationLookupError:
        await progress.edit_text(
            "⚠️ Не удалось получить список станций с сайта БЖД. "
            "Проверьте соединение и попробуйте ещё раз.",
            reply_markup=cancel_keyboard(),
        )
        return current_state

    if not suggestions:
        await progress.edit_text(
            f"Станции по запросу «{escape(query_text)}» не найдены.\n"
            "Попробуйте другое написание или более короткий запрос.",
            parse_mode="HTML",
            reply_markup=cancel_keyboard(),
        )
        return current_state

    context.user_data[f"{prefix}_station_query"] = query_text
    context.user_data[f"{prefix}_station_suggestions"] = suggestions
    search_id = token_hex(4)
    context.user_data[f"{prefix}_station_search_id"] = search_id
    await progress.edit_text(
        _station_suggestions_text(query_text, suggestions, 0),
        parse_mode="HTML",
        reply_markup=station_suggestions_keyboard(suggestions, prefix, search_id),
    )
    return current_state


async def _show_station_suggestions_page(
    query, context: ContextTypes.DEFAULT_TYPE, prefix: str, page: int
) -> int:
    suggestions = context.user_data.get(f"{prefix}_station_suggestions", [])
    query_text = context.user_data.get(f"{prefix}_station_query", "")
    if not suggestions:
        await query.edit_message_text(
            "Список станций устарел. Введите запрос ещё раз:",
            reply_markup=popular_stations_keyboard(prefix),
        )
        return FROM_STATION if prefix == "from" else TO_STATION

    search_id = context.user_data.get(f"{prefix}_station_search_id", "")
    page_count = max(
        1, (len(suggestions) + STATION_PAGE_SIZE - 1) // STATION_PAGE_SIZE
    )
    page = max(0, min(page, page_count - 1))
    await query.edit_message_text(
        _station_suggestions_text(query_text, suggestions, page),
        parse_mode="HTML",
        reply_markup=station_suggestions_keyboard(
            suggestions, prefix, search_id, page
        ),
    )
    return FROM_STATION if prefix == "from" else TO_STATION


async def get_from_station(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        query = update.callback_query
        await query.answer()
        data = query.data

        if data == "cancel_search":
            return await show_main_menu(update, context)
        if data == "from_manual":
            context.user_data.pop("from_station_suggestions", None)
            context.user_data.pop("from_station_search_id", None)
            await query.edit_message_text(
                "✏️ Введите город или станцию отправления (например: <i>Москва</i>):",
                parse_mode="HTML",
                reply_markup=cancel_keyboard(),
            )
            return FROM_STATION
        if data.startswith("from_page_"):
            try:
                search_id, page_text = data.removeprefix("from_page_").rsplit("_", 1)
                page = int(page_text)
            except ValueError:
                return FROM_STATION
            if search_id != context.user_data.get("from_station_search_id"):
                await query.edit_message_text(
                    "Этот список станций устарел. Используйте последний результат поиска."
                )
                return FROM_STATION
            return await _show_station_suggestions_page(query, context, "from", page)
        if data.startswith("from_pick_"):
            try:
                search_id, index_text = data.removeprefix("from_pick_").rsplit("_", 1)
                idx = int(index_text)
                if search_id != context.user_data.get("from_station_search_id"):
                    raise KeyError("Station search result is stale")
                suggestions = context.user_data["from_station_suggestions"]
                if idx < 0 or idx >= len(suggestions):
                    raise IndexError("Station selection is out of range")
                suggestion = suggestions[idx]
            except (KeyError, IndexError, ValueError):
                await query.edit_message_text(
                    "Список станций устарел. Введите запрос ещё раз:",
                    reply_markup=popular_stations_keyboard("from"),
                )
                return FROM_STATION
            _set_station(
                context,
                "from",
                suggestion["value"],
                suggestion["label"],
                suggestion["exp"],
            )
        elif data.startswith("from_"):
            try:
                idx = int(data.removeprefix("from_"))
                station = station_by_index(idx)
            except (IndexError, ValueError):
                return FROM_STATION
            _set_station(context, "from", station)
        else:
            return FROM_STATION
    else:
        return await _search_station_input(update, context, "from")

    from_st = _station_label(context, "from")
    text = (
        f"✅ Отправление: <b>{escape(from_st)}</b>\n\n"
        f"📍 <b>Шаг 2 из 3</b> — станция прибытия\n"
        "Выберите из списка или введите город/станцию для поиска:"
    )
    markup = popular_stations_keyboard("to")

    if update.callback_query:
        await query.edit_message_text(text, reply_markup=markup, parse_mode="HTML")
    else:
        await update.message.reply_text(text, reply_markup=markup, parse_mode="HTML")

    return TO_STATION


async def show_to_station_step(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from_st = _station_label(context, "from")
    text = (
        f"✅ Отправление: <b>{escape(from_st)}</b>\n\n"
        f"📍 <b>Шаг 2 из 3</b> — станция прибытия\n"
        "Выберите из списка или введите город/станцию для поиска:"
    )
    markup = popular_stations_keyboard("to")
    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=markup, parse_mode="HTML")
    elif update.message:
        await update.message.reply_text(text, reply_markup=markup, parse_mode="HTML")
    return TO_STATION


async def get_to_station(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        query = update.callback_query
        await query.answer()
        data = query.data

        if data == "cancel_search":
            return await show_main_menu(update, context)
        if data == "to_manual":
            context.user_data.pop("to_station_suggestions", None)
            context.user_data.pop("to_station_search_id", None)
            await query.edit_message_text(
                "✏️ Введите город или станцию прибытия (например: <i>Брест</i>):",
                parse_mode="HTML",
                reply_markup=cancel_keyboard(),
            )
            return TO_STATION
        if data.startswith("to_page_"):
            try:
                search_id, page_text = data.removeprefix("to_page_").rsplit("_", 1)
                page = int(page_text)
            except ValueError:
                return TO_STATION
            if search_id != context.user_data.get("to_station_search_id"):
                await query.edit_message_text(
                    "Этот список станций устарел. Используйте последний результат поиска."
                )
                return TO_STATION
            return await _show_station_suggestions_page(query, context, "to", page)
        if data.startswith("to_pick_"):
            try:
                search_id, index_text = data.removeprefix("to_pick_").rsplit("_", 1)
                idx = int(index_text)
                if search_id != context.user_data.get("to_station_search_id"):
                    raise KeyError("Station search result is stale")
                suggestions = context.user_data["to_station_suggestions"]
                if idx < 0 or idx >= len(suggestions):
                    raise IndexError("Station selection is out of range")
                suggestion = suggestions[idx]
            except (KeyError, IndexError, ValueError):
                await query.edit_message_text(
                    "Список станций устарел. Введите запрос ещё раз:",
                    reply_markup=popular_stations_keyboard("to"),
                )
                return TO_STATION
            _set_station(
                context,
                "to",
                suggestion["value"],
                suggestion["label"],
                suggestion["exp"],
            )
        elif data.startswith("to_"):
            try:
                idx = int(data.removeprefix("to_"))
                station = station_by_index(idx)
            except (IndexError, ValueError):
                return TO_STATION
            _set_station(context, "to", station)
        else:
            return TO_STATION
    else:
        return await _search_station_input(update, context, "to")

    to_st = _station_label(context, "to")
    text = (
        f"✅ Прибытие: <b>{escape(to_st)}</b>\n\n"
        f"📅 <b>Шаг 3 из 3</b> — дата поездки\n"
        "Выберите дату в календаре или введите её в формате <b>ДД.ММ.ГГГГ</b>:"
    )
    markup = date_calendar_keyboard()

    if update.callback_query:
        await query.edit_message_text(text, reply_markup=markup, parse_mode="HTML")
    else:
        await update.message.reply_text(text, reply_markup=markup, parse_mode="HTML")

    return DATE


async def process_date_and_search(update: Update, context: ContextTypes.DEFAULT_TYPE, date_str: str, date_display: str):
    context.user_data["date"] = date_str
    context.user_data["date_display"] = date_display

    wait_text = (
        f"🔍 Ищу поезда на <b>{date_display}</b>\n"
        f"📍 {escape(_station_label(context, 'from'))} → "
        f"{escape(_station_label(context, 'to'))}\n\n"
        "⏳ Это может занять до 25 секунд..."
    )

    if update.callback_query:
        await update.callback_query.edit_message_text(wait_text, parse_mode="HTML")
    else:
        wait_msg = await update.message.reply_text(wait_text, parse_mode="HTML")

    try:
        trains = await fetch_trains_list(
            context.user_data["from_station"],
            context.user_data["to_station"],
            date_str,
            from_exp=context.user_data.get("from_station_exp"),
            to_exp=context.user_data.get("to_station_exp"),
        )
    except RailwayVerificationError:
        verification_text = (
            "⚠️ Сайт БЖД временно показывает проверочную страницу, "
            "поэтому сейчас не удалось загрузить расписание.\n\n"
            "Подписка не создана. Подождите немного и попробуйте ещё раз."
        )
        if update.callback_query:
            await update.callback_query.edit_message_text(
                verification_text,
                reply_markup=retry_keyboard(),
                parse_mode="HTML",
            )
        else:
            await wait_msg.edit_text(
                verification_text,
                reply_markup=retry_keyboard(),
                parse_mode="HTML",
            )
        return ConversationHandler.END

    context.user_data["trains_found"] = trains

    if not trains:
        fail_text = (
            "❌ <b>Поезда не найдены</b>\n\n"
            "Возможные причины:\n"
            "• На эту дату нет рейсов\n"
            "• Неверно указаны станции\n"
            "• Временная проблема с сайтом БЖД"
        )
        markup = retry_keyboard()
        if update.callback_query:
            await update.callback_query.edit_message_text(fail_text, reply_markup=markup, parse_mode="HTML")
        else:
            await wait_msg.edit_text(fail_text, reply_markup=markup, parse_mode="HTML")
        return ConversationHandler.END

    success_text = (
        f"📋 Найдено <b>{len(trains)}</b> поездов на {date_display}\n\n"
        f"{format_trains_list(trains)}\n\n"
        "Выберите рейс по времени отправления:"
    )
    markup = trains_keyboard(trains)

    if update.callback_query:
        await update.callback_query.edit_message_text(success_text, reply_markup=markup, parse_mode="HTML")
    else:
        await wait_msg.edit_text(success_text, reply_markup=markup, parse_mode="HTML")

    return SELECT_TRAIN


async def get_date(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        query = update.callback_query
        data = query.data

        if data == "date_disabled":
            await query.answer("Выберите сегодняшнюю или будущую дату.")
            return DATE

        await query.answer()
        if data == "cancel_search":
            return await show_main_menu(update, context)
        if data == "back_to_station":
            return await show_to_station_step(update, context)
        if data.startswith("date_prev_") or data.startswith("date_next_"):
            direction = "prev" if data.startswith("date_prev_") else "next"
            month_text = data.removeprefix(f"date_{direction}_")
            try:
                year, month = (int(value) for value in month_text.split("-", 1))
            except ValueError:
                return DATE
            if not 1 <= year <= 9999 or not 1 <= month <= 12:
                return DATE
            if direction == "prev":
                month -= 1
                if month == 0:
                    year -= 1
                    month = 12
            else:
                month += 1
                if month == 13:
                    year += 1
                    month = 1
            today = datetime.now(TIMEZONE).date()
            if (year, month) < (today.year, today.month):
                year, month = today.year, today.month
            await query.edit_message_reply_markup(
                reply_markup=date_calendar_keyboard(year, month, today)
            )
            return DATE
        if data == "date_manual":
            await query.edit_message_text(
                "✏️ Введите дату в формате <b>ДД.ММ.ГГГГ</b> (например: 31.12.2026):",
                parse_mode="HTML",
                reply_markup=cancel_keyboard(),
            )
            return DATE
        if data.startswith("date_pick_"):
            date_str = data.removeprefix("date_pick_")
            try:
                dt = datetime.strptime(date_str, "%Y-%m-%d")
            except ValueError:
                return DATE
            if dt.date() < datetime.now(TIMEZONE).date():
                await query.edit_message_text(
                    "Эта дата уже прошла. Выберите сегодняшнюю или будущую дату:",
                    reply_markup=date_calendar_keyboard(),
                )
                return DATE
            return await process_date_and_search(update, context, date_str, dt.strftime("%d.%m.%Y"))
        return DATE

    date_text = update.message.text.strip()
    try:
        dt = datetime.strptime(date_text, "%d.%m.%Y")
        if dt.date() < datetime.now(TIMEZONE).date():
            await update.message.reply_text(
                "❌ Дата не может быть в прошлом. Попробуйте снова:",
                reply_markup=date_calendar_keyboard(),
            )
            return DATE
        return await process_date_and_search(update, context, dt.strftime("%Y-%m-%d"), date_text)
    except ValueError:
        await update.message.reply_text(
            "❌ Неверный формат. Используйте <b>ДД.ММ.ГГГГ</b> (например: 31.12.2026)",
            parse_mode="HTML",
            reply_markup=date_calendar_keyboard(),
        )
        return DATE


async def select_train(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "cancel_search":
        return await show_main_menu(update, context)
    if data == "back_to_date":
        text = (
            f"📅 <b>Шаг 3 из 3</b> — дата поездки\n"
            "Выберите дату в календаре или введите её в формате <b>ДД.ММ.ГГГГ</b>:"
        )
        await query.edit_message_text(text, reply_markup=date_calendar_keyboard(), parse_mode="HTML")
        return DATE
    if not data.startswith("select_train_"):
        return SELECT_TRAIN

    try:
        train_idx = int(data.replace("select_train_", ""))
    except ValueError:
        await query.edit_message_text("❌ Неверный выбор поезда.", reply_markup=retry_keyboard())
        return ConversationHandler.END

    trains = context.user_data.get("trains_found", [])
    if train_idx < 0 or train_idx >= len(trains):
        await query.edit_message_text(
            "❌ Список поездов устарел. Начните поиск заново.",
            reply_markup=retry_keyboard(),
        )
        return ConversationHandler.END

    train_info = trains[train_idx]
    context.user_data["selected_train_idx"] = train_idx
    dep = train_info.get("departure") or "??:??"
    arr = train_info.get("arrival") or "??:??"
    text = (
        f"🎯 <b>Шаг 4 — что отслеживать?</b>\n\n"
        f"🚂 Поезд №<b>{escape(train_info['number'])}</b>\n"
        f"🕐 {escape(dep)} → {escape(arr)}\n\n"
        "Выберите тип мест, за которым следить:"
    )
    await query.edit_message_text(
        text,
        parse_mode="HTML",
        reply_markup=seat_preference_keyboard(train_idx),
    )
    return SELECT_PREFERENCE


async def select_preference(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "cancel_search":
        return await show_main_menu(update, context)
    if data == "back_to_trains":
        trains = context.user_data.get("trains_found", [])
        date_display = context.user_data.get("date_display", "")
        text = (
            f"📋 Найдено <b>{len(trains)}</b> поездов на {date_display}\n\n"
            f"{format_trains_list(trains)}\n\n"
            "Выберите рейс по времени отправления:"
        )
        await query.edit_message_text(
            text,
            reply_markup=trains_keyboard(trains),
            parse_mode="HTML",
        )
        return SELECT_TRAIN

    car_type, seat_filter, idx_str = parse_preference(data)
    if idx_str is None:
        return SELECT_PREFERENCE

    try:
        train_idx = int(idx_str)
    except ValueError:
        await query.edit_message_text("❌ Неверный выбор.", reply_markup=retry_keyboard())
        return ConversationHandler.END

    trains = context.user_data.get("trains_found", [])
    if train_idx < 0 or train_idx >= len(trains):
        await query.edit_message_text(
            "❌ Список поездов устарел. Начните поиск заново.",
            reply_markup=retry_keyboard(),
        )
        return ConversationHandler.END

    train_info = trains[train_idx]
    train_num = train_info["number"]
    user_id = query.from_user.id
    from_st = context.user_data["from_station"]
    to_st = context.user_data["to_station"]
    date_str = context.user_data["date"]
    date_display = context.user_data["date_display"]

    sub = create_subscription(
        user_id,
        train_num,
        date_str,
        from_st,
        to_st,
        departure=train_info.get("departure", ""),
        arrival=train_info.get("arrival", ""),
        duration=train_info.get("duration", ""),
        car_type=car_type,
        seat_filter=seat_filter,
        from_exp=context.user_data.get("from_station_exp"),
        to_exp=context.user_data.get("to_station_exp"),
        from_label=_station_label(context, "from"),
        to_label=_station_label(context, "to"),
    )

    await query.edit_message_text(
        format_subscription_created(sub, date_display),
        parse_mode="HTML",
        reply_markup=subscription_created_keyboard(sub["id"]),
    )

    context.application.create_task(
        check_single_subscription(context, user_id, sub, is_first_check=True),
        update=update,
    )
    context.user_data.clear()
    return ConversationHandler.END


async def check_single_subscription(context, user_id, sub, is_first_check=False, edit_message=None):
    key = (str(user_id), str(sub["id"]))
    if key in _subscription_checks_in_progress:
        logging.debug(
            "Skipping overlapping check for subscription %s (user %s)",
            key[1],
            key[0],
        )
        return

    _subscription_checks_in_progress.add(key)
    try:
        await _check_single_subscription(
            context, user_id, sub, is_first_check, edit_message
        )
    finally:
        _subscription_checks_in_progress.discard(key)


async def _check_single_subscription(
    context, user_id, sub, is_first_check=False, edit_message=None
):
    train_num = sub["train"]
    date = sub["date"]
    from_st = sub["from"]
    to_st = sub["to"]
    sub_id = sub["id"]

    logging.info("Проверка: поезд %s, дата %s, подписка %s, user %s", train_num, date, sub_id, user_id)

    result = await check_tickets(
        from_st,
        to_st,
        date,
        train_num,
        car_type=sub.get("car_type"),
        seat_filter=sub.get("seat_filter"),
        from_exp=sub.get("from_exp"),
        to_exp=sub.get("to_exp"),
    )
    status = result["status"]
    schedule = train_schedule_label(sub)
    pref = preference_label(sub)

    if status == "page_error":
        if is_first_check:
            await context.bot.send_message(
                user_id,
                "❌ Не удалось загрузить расписание. Повторю при следующей проверке.",
                reply_markup=MAIN_KEYBOARD,
            )
        return

    if status == "train_not_found":
        if is_first_check:
            await context.bot.send_message(
                user_id,
                f"❌ Поезд <b>{escape(train_num)}</b> не найден на эту дату.",
                parse_mode="HTML",
                reply_markup=MAIN_KEYBOARD,
            )
        return

    if status == "error":
        if is_first_check:
            await context.bot.send_message(
                user_id,
                "⚠️ Ошибка при чтении данных. Повторю позже.",
                reply_markup=MAIN_KEYBOARD,
            )
        return

    if status == "no_tickets":
        if is_first_check:
            await context.bot.send_message(
                user_id,
                f"ℹ️ Билетов на рейс <b>{escape(schedule)}</b> ({date.replace('-', '.')}) пока нет.\n"
                f"Отслеживаю: {pref}\n"
                f"Продолжаю следить — уведомлю, когда появятся!",
                parse_mode="HTML",
                reply_markup=MAIN_KEYBOARD,
            )
            sub["first_check_done"] = True
            storage.save_subscriptions()
        if edit_message:
            await edit_message.edit_text(
                f"ℹ️ Билетов на поезд <b>{escape(train_num)}</b> пока нет.\nПродолжаю следить...",
                parse_mode="HTML",
                reply_markup=subscriptions_list_keyboard(get_user_subs(user_id)),
            )
        return

    if status == "no_matching_seats":
        if is_first_check:
            await context.bot.send_message(
                user_id,
                f"ℹ️ На рейс <b>{escape(schedule)}</b> ({date.replace('-', '.')}) билеты есть, "
                f"но нужных мест пока нет.\n"
                f"Отслеживаю: {pref}\n"
                f"Продолжаю следить!",
                parse_mode="HTML",
                reply_markup=MAIN_KEYBOARD,
            )
            sub["first_check_done"] = True
            storage.save_subscriptions()
        if edit_message:
            await edit_message.edit_text(
                f"ℹ️ Нужных мест ({pref}) пока нет.\nПродолжаю следить...",
                parse_mode="HTML",
                reply_markup=subscriptions_list_keyboard(get_user_subs(user_id)),
            )
        return

    if status == "tickets":
        message = format_tickets_message(
            train_num,
            date,
            result["items"],
            result["url"],
            departure=sub.get("departure", ""),
            arrival=sub.get("arrival", ""),
            seat_filter=sub.get("seat_filter"),
            matched_seats=result.get("matched_seats"),
            seats=result.get("seats"),
        )
        await context.bot.send_message(
            chat_id=user_id,
            text=message,
            reply_markup=tickets_found_keyboard(sub_id, result["url"]),
            parse_mode="HTML",
            disable_web_page_preview=False,
        )
        sub["notified"] = True
        sub["first_check_done"] = True
        storage.save_subscriptions()

        if edit_message:
            await edit_message.edit_text(
                "✅ Проверка завершена — билеты найдены! Смотрите сообщение выше 👆",
                reply_markup=subscriptions_list_keyboard(get_user_subs(user_id)),
            )


async def background_checker(context: ContextTypes.DEFAULT_TYPE):
    cleanup_expired()
    subs = list(active_subscriptions())
    if not subs:
        return

    pending = deque(subs)

    async def worker() -> None:
        while pending:
            uid, sub = pending.popleft()
            try:
                await check_single_subscription(
                    context, int(uid), sub, is_first_check=False
                )
            except Exception as error:
                logging.error(
                    "Subscription check failed for subscription %s (user %s)",
                    sub.get("id"),
                    uid,
                    exc_info=(type(error), error, error.__traceback__),
                )

    worker_count = min(MAX_CONCURRENT_CHECKS, len(subs))
    await asyncio.gather(*(worker() for _ in range(worker_count)))


async def show_user_subscriptions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    user_id = update.effective_user.id
    subs = get_user_subs(user_id)
    text = format_subscriptions_list(subs)

    if not subs:
        markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔍 Создать подписку", callback_data="start_search")],
            [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")],
        ])
    else:
        markup = subscriptions_list_keyboard(subs)

    if update.callback_query:
        await update.callback_query.answer()
        await send_or_edit(update, text, markup)
    elif update.message:
        await update.message.reply_text(text, reply_markup=markup, parse_mode="HTML")

    return ConversationHandler.END


async def handle_button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    user_id = query.from_user.id

    if data == "main_menu":
        return await show_main_menu(update, context)

    if data == "help":
        await query.edit_message_text(HELP_TEXT, parse_mode="HTML", reply_markup=main_menu_keyboard())
        return

    if data == "my_subscriptions":
        return await show_user_subscriptions(update, context)

    if data.startswith("check_sub_"):
        sub_id = data.replace("check_sub_", "")
        sub = find_subscription(user_id, sub_id)
        if not sub:
            await query.edit_message_text("❌ Подписка не найдена.", reply_markup=main_menu_keyboard())
            return
        msg = await query.edit_message_text("🔍 Проверяю билеты... Подождите до 25 сек.")
        await check_single_subscription(context, user_id, sub, is_first_check=True, edit_message=msg)
        return

    if data.startswith("delete_confirm_"):
        sub_id = data.replace("delete_confirm_", "")
        sub = find_subscription(user_id, sub_id)
        if not sub:
            await query.edit_message_text("❌ Подписка не найдена.")
            return
        await query.edit_message_text(
            f"🗑 Удалить подписку <b>{escape(train_schedule_label(sub))}</b> "
            f"({sub['date'].replace('-', '.')})?",
            parse_mode="HTML",
            reply_markup=delete_confirm_keyboard(sub_id),
        )
        return

    if data.startswith("delete_sub_"):
        sub_id = data.replace("delete_sub_", "")
        if remove_subscription(user_id, sub_id):
            await query.edit_message_text(f"✅ Подписка <code>{sub_id}</code> удалена.", parse_mode="HTML")
        else:
            await query.edit_message_text("❌ Подписка не найдена.")
        return await show_user_subscriptions(update, context)


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    if update.message:
        await update.message.reply_text(
            "❌ Действие отменено.",
            reply_markup=MAIN_KEYBOARD,
        )
        await update.message.reply_text(
            WELCOME_TEXT,
            reply_markup=main_menu_keyboard(),
            parse_mode="HTML",
        )
    return ConversationHandler.END


async def post_init(application: Application):
    load_subscriptions()
    await application.bot.set_my_commands(BOT_COMMANDS)


async def post_shutdown(application: Application):
    await close_browser()


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logging.error("Exception while handling update", exc_info=context.error)


def _conversation_menu_handlers() -> list[MessageHandler]:
    return [
        MessageHandler(filters.Regex(f"^{BTN_NEW_SEARCH}$"), begin_search),
        MessageHandler(filters.Regex(f"^{BTN_MY_SUBS}$"), show_user_subscriptions),
        MessageHandler(filters.Regex(f"^{BTN_HELP}$"), help_command),
    ]


def main():
    if not TOKEN:
        raise RuntimeError("BOT_TOKEN is not set. Add it to the environment or .env file.")

    app = (
        Application.builder()
        .token(TOKEN)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )

    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler("start", show_main_menu),
            CommandHandler("search", begin_search),
            CallbackQueryHandler(begin_search, pattern="^start_search$"),
            MessageHandler(filters.Regex(f"^{BTN_NEW_SEARCH}$"), begin_search),
        ],
        states={
            FROM_STATION: [
                *_conversation_menu_handlers(),
                CallbackQueryHandler(get_from_station, pattern="^(from_|cancel_search)"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, get_from_station),
            ],
            TO_STATION: [
                *_conversation_menu_handlers(),
                CallbackQueryHandler(get_to_station, pattern="^(to_|cancel_search)"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, get_to_station),
            ],
            DATE: [
                *_conversation_menu_handlers(),
                CallbackQueryHandler(get_date, pattern="^(date_|back_to_station|cancel_search)"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, get_date),
            ],
            SELECT_TRAIN: [
                *_conversation_menu_handlers(),
                CallbackQueryHandler(select_train, pattern="^(select_train_|back_to_date|cancel_search)"),
            ],
            SELECT_PREFERENCE: [
                *_conversation_menu_handlers(),
                CallbackQueryHandler(
                    select_preference,
                    pattern="^(pref_|back_to_trains|cancel_search)",
                ),
            ],
        },
        fallbacks=[
            CommandHandler("cancel", cancel),
            CommandHandler("help", help_command),
            CommandHandler("my", show_user_subscriptions),
            CommandHandler("my_subscription", show_user_subscriptions),
            CommandHandler("search", begin_search),
            CallbackQueryHandler(show_main_menu, pattern="^cancel_search$"),
            CommandHandler("start", show_main_menu),
        ],
        per_chat=True,
        per_user=True,
        allow_reentry=True,
    )

    app.add_handler(conv_handler)
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("my", show_user_subscriptions))
    app.add_handler(CommandHandler("my_subscription", show_user_subscriptions))
    app.add_handler(MessageHandler(filters.Regex(f"^{BTN_MY_SUBS}$"), show_user_subscriptions))
    app.add_handler(MessageHandler(filters.Regex(f"^{BTN_HELP}$"), help_command))
    app.add_handler(CallbackQueryHandler(handle_button_callback))
    app.add_error_handler(error_handler)

    if app.job_queue:
        app.job_queue.run_repeating(
            background_checker,
            interval=CHECK_INTERVAL,
            first=15,
            job_kwargs={"max_instances": 1},
        )

    print("TrainWaited bot started")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
