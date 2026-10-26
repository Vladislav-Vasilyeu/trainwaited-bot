from calendar import monthcalendar
from datetime import date, datetime
from html import escape

from telegram import BotCommand, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup

from config import CHECK_INTERVAL, POPULAR_STATIONS, TIMEZONE

# --- Reply keyboard ---

BTN_NEW_SEARCH = "🔍 Новый поиск"
BTN_MY_SUBS = "📋 Мои подписки"
BTN_HELP = "❓ Помощь"

MAIN_KEYBOARD = ReplyKeyboardMarkup(
    [[BTN_NEW_SEARCH, BTN_MY_SUBS], [BTN_HELP]],
    resize_keyboard=True,
    is_persistent=True,
)

STATION_PAGE_SIZE = 8


def main_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🔍 Найти билеты", callback_data="start_search")],
            [InlineKeyboardButton("📋 Мои подписки", callback_data="my_subscriptions")],
            [InlineKeyboardButton("❓ Как пользоваться", callback_data="help")],
        ]
    )


def cancel_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("❌ Отмена", callback_data="cancel_search")]]
    )


def popular_stations_keyboard(prefix: str) -> InlineKeyboardMarkup:
    rows = []
    row = []
    for i, station in enumerate(POPULAR_STATIONS):
        short = station.split("-")[0][:12]
        row.append(InlineKeyboardButton(short, callback_data=f"{prefix}_{i}"))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton("✏️ Ввести вручную", callback_data=f"{prefix}_manual")])
    rows.append([InlineKeyboardButton("❌ Отмена", callback_data="cancel_search")])
    return InlineKeyboardMarkup(rows)


def station_suggestions_keyboard(
    suggestions: list[dict[str, str]], prefix: str, search_id: str, page: int = 0
) -> InlineKeyboardMarkup:
    page_count = max(
        1, (len(suggestions) + STATION_PAGE_SIZE - 1) // STATION_PAGE_SIZE
    )
    page = max(0, min(page, page_count - 1))
    start = page * STATION_PAGE_SIZE
    rows = []
    for index, suggestion in enumerate(
        suggestions[start : start + STATION_PAGE_SIZE], start
    ):
        label = suggestion["label"]
        if len(label) > 64:
            label = f"{label[:61]}…"
        rows.append(
            [
                InlineKeyboardButton(
                    label,
                    callback_data=f"{prefix}_pick_{search_id}_{index}",
                )
            ]
        )

    if page_count > 1:
        navigation = []
        if page > 0:
            navigation.append(
                InlineKeyboardButton(
                    "⬅️",
                    callback_data=f"{prefix}_page_{search_id}_{page - 1}",
                )
            )
        navigation.append(
            InlineKeyboardButton(
                f"{page + 1}/{page_count}",
                callback_data=f"{prefix}_page_{search_id}_{page}",
            )
        )
        if page < page_count - 1:
            navigation.append(
                InlineKeyboardButton(
                    "➡️",
                    callback_data=f"{prefix}_page_{search_id}_{page + 1}",
                )
            )
        rows.append(navigation)

    rows.extend(
        [
            [InlineKeyboardButton("✏️ Другой запрос", callback_data=f"{prefix}_manual")],
            [InlineKeyboardButton("❌ Отмена", callback_data="cancel_search")],
        ]
    )
    return InlineKeyboardMarkup(rows)


_MONTH_NAMES = (
    "январь",
    "февраль",
    "март",
    "апрель",
    "май",
    "июнь",
    "июль",
    "август",
    "сентябрь",
    "октябрь",
    "ноябрь",
    "декабрь",
)


def date_calendar_keyboard(
    year: int | None = None,
    month: int | None = None,
    today: date | None = None,
) -> InlineKeyboardMarkup:
    today = today or datetime.now(TIMEZONE).date()
    year = year or today.year
    month = month or today.month
    current_month = (today.year, today.month)

    previous_year, previous_month = year, month - 1
    if previous_month == 0:
        previous_year -= 1
        previous_month = 12
    next_year, next_month = year, month + 1
    if next_month == 13:
        next_year += 1
        next_month = 1

    previous_callback = (
        f"date_prev_{year:04d}-{month:02d}"
        if (previous_year, previous_month) >= current_month
        else "date_disabled"
    )
    next_callback = (
        f"date_next_{year:04d}-{month:02d}"
        if year < 9999 or month < 12
        else "date_disabled"
    )
    rows = [
        [
            InlineKeyboardButton("◀️", callback_data=previous_callback),
            InlineKeyboardButton(
                f"{_MONTH_NAMES[month - 1].capitalize()} {year}",
                callback_data="date_disabled",
            ),
            InlineKeyboardButton("▶️", callback_data=next_callback),
        ],
        [
            InlineKeyboardButton(day, callback_data="date_disabled")
            for day in ("Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс")
        ],
    ]

    for week in monthcalendar(year, month):
        row = []
        for day in week:
            if not day:
                row.append(InlineKeyboardButton("·", callback_data="date_disabled"))
                continue
            selected_date = date(year, month, day)
            callback = (
                f"date_pick_{selected_date.isoformat()}"
                if selected_date >= today
                else "date_disabled"
            )
            row.append(
                InlineKeyboardButton(str(day), callback_data=callback)
            )
        rows.append(row)

    rows.extend(
        [
            [InlineKeyboardButton("✏️ Ввести дату вручную", callback_data="date_manual")],
            [InlineKeyboardButton("◀️ Назад", callback_data="back_to_station")],
            [InlineKeyboardButton("❌ Отмена", callback_data="cancel_search")],
        ]
    )
    return InlineKeyboardMarkup(rows)


def train_button_label(train: dict) -> str:
    dep = train.get("departure") or "??:??"
    arr = train.get("arrival") or "??:??"
    label = f"{dep} → {arr}"
    duration = train.get("duration")
    if duration:
        label += f" · {duration}"
    return label[:64]


def trains_keyboard(trains: list[dict]) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(train_button_label(t), callback_data=f"select_train_{i}")]
        for i, t in enumerate(trains)
    ]
    rows.append([InlineKeyboardButton("◀️ Изменить дату", callback_data="back_to_date")])
    rows.append([InlineKeyboardButton("❌ Отмена", callback_data="cancel_search")])
    return InlineKeyboardMarkup(rows)


SEAT_FILTER_LABELS = {
    None: "любые билеты",
    "any": "любые билеты",
    "lower": "плацкарт · нижнее",
    "lower_any": "плацкарт · любое нижнее",
    "lower_side": "плацкарт · нижнее боковое",
    "upper": "плацкарт · верхнее",
    "upper_any": "плацкарт · любое верхнее",
    "upper_side": "плацкарт · верхнее боковое",
    "side_any": "плацкарт · любое боковое",
}


def seat_preference_keyboard(train_idx: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🎫 Любые билеты", callback_data=f"pref_any_{train_idx}")],
            [InlineKeyboardButton("🛏 Плацкарт — любые", callback_data=f"pref_platzkart_{train_idx}")],
            [InlineKeyboardButton("🛋 Купе — любые", callback_data=f"pref_coupe_{train_idx}")],
            [
                InlineKeyboardButton(
                    "🛏 Плацкарт — нижнее",
                    callback_data=f"pref_lower_{train_idx}",
                )
            ],
            [
                InlineKeyboardButton(
                    "🛏 Плацкарт — любое нижнее",
                    callback_data=f"pref_lower_any_{train_idx}",
                )
            ],
            [InlineKeyboardButton("🛏 Плацкарт — верхнее", callback_data=f"pref_upper_{train_idx}")],
            [
                InlineKeyboardButton(
                    "🛏 Плацкарт — любое верхнее",
                    callback_data=f"pref_upper_any_{train_idx}",
                )
            ],
            [
                InlineKeyboardButton(
                    "🛏 Плацкарт — нижнее боковое",
                    callback_data=f"pref_lower_side_{train_idx}",
                )
            ],
            [InlineKeyboardButton("🛏 Плацкарт — верхнее боковое", callback_data=f"pref_upper_side_{train_idx}")],
            [InlineKeyboardButton("🛏 Плацкарт — любое боковое", callback_data=f"pref_side_any_{train_idx}")],
            [InlineKeyboardButton("◀️ Назад к поездам", callback_data="back_to_trains")],
            [InlineKeyboardButton("❌ Отмена", callback_data="cancel_search")],
        ]
    )


def parse_preference(data: str) -> tuple[str | None, str | None, str | None]:
    if data.startswith("pref_any_"):
        return None, None, data.removeprefix("pref_any_")
    if data.startswith("pref_platzkart_"):
        return "platzkart", None, data.removeprefix("pref_platzkart_")
    if data.startswith("pref_coupe_"):
        return "coupe", None, data.removeprefix("pref_coupe_")
    for preference in (
        "lower_any",
        "upper_any",
        "lower_side",
        "upper_side",
        "side_any",
        "lower",
        "upper",
    ):
        prefix = f"pref_{preference}_"
        if data.startswith(prefix):
            return "platzkart", preference, data.removeprefix(prefix)
    return None, None, None


def preference_label(sub: dict) -> str:
    seat_filter = sub.get("seat_filter")
    car_type = sub.get("car_type")
    if not seat_filter and not car_type:
        return "🎫 любые билеты"
    if seat_filter:
        return f"🎯 {SEAT_FILTER_LABELS.get(seat_filter, escape(str(seat_filter)))}"
    if car_type == "platzkart":
        return "🛏 плацкарт"
    if car_type == "coupe":
        return "🛋 купе"
    return "🎫 фильтр активен"


def format_trains_list(trains: list[dict]) -> str:
    lines = []
    for i, t in enumerate(trains, 1):
        dep = t.get("departure") or "??:??"
        arr = t.get("arrival") or "??:??"
        line = f"{i}. <b>{escape(str(dep))} → {escape(str(arr))}</b>"
        if t.get("duration"):
            line += f" ({escape(str(t['duration']))})"
        if t.get("number"):
            line += f" · №{escape(str(t['number']))}"
        lines.append(line)
    return "\n".join(lines)


def subscription_created_keyboard(sub_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🔍 Проверить сейчас", callback_data=f"check_sub_{sub_id}")],
            [InlineKeyboardButton("📋 Мои подписки", callback_data="my_subscriptions")],
            [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")],
        ]
    )


def train_schedule_label(sub: dict) -> str:
    dep = sub.get("departure")
    arr = sub.get("arrival")
    if dep and arr:
        return f"{dep}→{arr}"
    return sub.get("train", "поезд")


def subscriptions_list_keyboard(subs: list[dict]) -> InlineKeyboardMarkup:
    rows = []
    for sub in subs:
        label = f"{train_schedule_label(sub)} · {sub['date'].replace('-', '.')}"
        rows.append(
            [
                InlineKeyboardButton(f"🔍 {label}", callback_data=f"check_sub_{sub['id']}"),
                InlineKeyboardButton("🗑", callback_data=f"delete_confirm_{sub['id']}"),
            ]
        )
    rows.append([InlineKeyboardButton("➕ Новая подписка", callback_data="start_search")])
    rows.append([InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")])
    return InlineKeyboardMarkup(rows)


def delete_confirm_keyboard(sub_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("✅ Да, удалить", callback_data=f"delete_sub_{sub_id}"),
                InlineKeyboardButton("↩️ Нет", callback_data="my_subscriptions"),
            ]
        ]
    )


def tickets_found_keyboard(sub_id: str, url: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🛒 Купить на сайте БЖД", url=url)],
            [InlineKeyboardButton("🔍 Проверить ещё", callback_data=f"check_sub_{sub_id}")],
            [InlineKeyboardButton("📋 Мои подписки", callback_data="my_subscriptions")],
        ]
    )


def retry_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🔄 Попробовать снова", callback_data="start_search")],
            [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")],
        ]
    )


# --- Messages ---

WELCOME_TEXT = (
    "🚂 <b>TrainWaited — мониторинг билетов БЖД</b>\n\n"
    "Бот следит за наличием билетов на сайте pass.rw.by и сразу присылает уведомление, "
    "когда места появляются.\n\n"
    "<b>Как это работает:</b>\n"
    "1️⃣ Укажите станции отправления и прибытия\n"
    "2️⃣ Выберите дату, поезд и тип места\n"
    "3️⃣ Получите уведомление, когда подходящие билеты появятся\n\n"
    f"Проверка — каждые {CHECK_INTERVAL} секунд. Нажмите кнопку ниже, чтобы начать 👇"
)

HELP_TEXT = (
    "❓ <b>Справка</b>\n\n"
    "<b>Команды:</b>\n"
    "/start — главное меню\n"
    "/search — новый поиск билетов\n"
    "/my — список подписок\n"
    "/cancel — отменить текущий ввод\n"
    "/help — эта справка\n\n"
    "<b>Советы:</b>\n"
    "• Введите город или станцию — выберите точный вариант из списка БЖД "
    "(для Москвы, например, конкретный вокзал)\n"
    "• Можно выбрать популярную станцию кнопкой\n"
    "• Дату удобно выбрать в календаре; прошедшие дни недоступны\n"
    "• После создания подписки бот сразу делает первую проверку\n"
    "• Можно следить за конкретным типом места (например, нижнее в плацкарте)\n"
    "• Уведомление придёт один раз, когда билеты появятся\n"
    "• Просроченные подписки удаляются автоматически"
)

BOT_COMMANDS = [
    BotCommand("start", "Главное меню"),
    BotCommand("search", "Новый поиск билетов"),
    BotCommand("my", "Мои подписки"),
    BotCommand("help", "Справка"),
    BotCommand("cancel", "Отменить ввод"),
]


def format_subscription(sub: dict) -> str:
    status = "✅ Билеты найдены" if sub.get("notified") else "⏳ Ожидаю билеты"
    dep = sub.get("departure")
    arr = sub.get("arrival")
    if dep and arr:
        time_line = f"🕐 <b>{escape(str(dep))} → {escape(str(arr))}</b>"
        if sub.get("duration"):
            time_line += f" ({escape(str(sub['duration']))})"
        time_line += f" · №{escape(str(sub['train']))}"
    else:
        time_line = f"🚂 Поезд <b>{escape(str(sub['train']))}</b>"
    from_label = sub.get("from_label", sub["from"])
    to_label = sub.get("to_label", sub["to"])
    return (
        f"🆔 <code>{sub['id']}</code>\n"
        f"{time_line} · {sub['date'].replace('-', '.')}\n"
        f"📍 {escape(str(from_label))} → {escape(str(to_label))}\n"
        f"{preference_label(sub)}\n"
        f"🔔 {status}"
    )


def format_subscriptions_list(subs: list[dict]) -> str:
    if not subs:
        return "📋 У вас пока нет активных подписок."
    lines = [f"📋 <b>Ваши подписки ({len(subs)}):</b>\n"]
    for sub in subs:
        lines.append(format_subscription(sub))
        lines.append("")
    return "\n".join(lines).strip()


def format_subscription_created(sub: dict, date_display: str) -> str:
    dep = sub.get("departure")
    arr = sub.get("arrival")
    if dep and arr:
        schedule = (
            f"🕐 Отправление: <b>{escape(str(dep))}</b> → "
            f"прибытие <b>{escape(str(arr))}</b>"
        )
        if sub.get("duration"):
            schedule += f" ({escape(str(sub['duration']))})"
        schedule += f"\n🚂 Поезд №<b>{escape(str(sub['train']))}</b>"
    else:
        schedule = f"🚂 Поезд: <b>{escape(str(sub['train']))}</b>"
    from_label = sub.get("from_label", sub["from"])
    to_label = sub.get("to_label", sub["to"])
    return (
        f"✅ <b>Подписка создана!</b>\n\n"
        f"🆔 ID: <code>{escape(str(sub['id']))}</code>\n"
        f"{schedule}\n"
        f"📅 Дата: <b>{date_display}</b>\n"
        f"📍 Маршрут: <b>{escape(str(from_label))}</b> → "
        f"<b>{escape(str(to_label))}</b>\n"
        f"🎯 Отслеживаю: <b>{preference_label(sub).replace('🎯 ', '').replace('🎫 ', '')}</b>\n\n"
        f"⏰ Автопроверка каждые {CHECK_INTERVAL} сек\n"
        f"🔔 Уведомлю, как только появятся подходящие билеты!"
    )


def format_tickets_message(
    train_num: str,
    date: str,
    items: list[dict],
    url: str,
    departure: str = "",
    arrival: str = "",
    seat_filter: str | None = None,
    matched_seats: int | None = None,
    seats: dict | None = None,
) -> str:
    date_display = date.replace("-", ".")
    if departure and arrival:
        header = f"🔥 <b>БИЛЕТЫ ПОЯВИЛИСЬ!</b>\n🕐 <b>{escape(departure)} → {escape(arrival)}</b> · №{escape(train_num)} · {date_display}\n"
    else:
        header = f"🔥 <b>БИЛЕТЫ ПОЯВИЛИСЬ!</b>\n🚂 Поезд <b>{escape(train_num)}</b> · {date_display}\n"
    lines = [header]

    if seat_filter and seat_filter != "any" and matched_seats:
        label = SEAT_FILTER_LABELS.get(seat_filter, seat_filter)
        lines.append(f"🎯 Найдено <b>{matched_seats}</b> мест: {label}")

    for item in items:
        line = f"• {escape(str(item['type']))}: <b>{escape(str(item['quantity']))}</b> мест"
        if item.get("price"):
            line += f" — от {escape(str(item['price']))} BYN"
        lines.append(line)

    if seats:
        detail = []
        for label, count in sorted(seats.items()):
            if count:
                detail.append(f"{escape(str(label))}: {escape(str(count))}")
        if detail:
            lines.append("📊 " + " · ".join(detail))

    lines.append(f"\n🔗 <a href='{escape(url, quote=True)}'>Открыть на pass.rw.by</a>")
    return "\n".join(lines)


def station_by_index(index: int) -> str:
    if index < 0 or index >= len(POPULAR_STATIONS):
        raise IndexError("Popular station index is out of range")
    return POPULAR_STATIONS[index]