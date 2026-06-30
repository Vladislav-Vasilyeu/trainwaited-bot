from datetime import datetime, timedelta

from telegram import BotCommand, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup

from config import POPULAR_STATIONS

# --- Reply keyboard ---

BTN_NEW_SEARCH = "🔍 Новый поиск"
BTN_MY_SUBS = "📋 Мои подписки"
BTN_HELP = "❓ Помощь"

MAIN_KEYBOARD = ReplyKeyboardMarkup(
    [[BTN_NEW_SEARCH, BTN_MY_SUBS], [BTN_HELP]],
    resize_keyboard=True,
    is_persistent=True,
)


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


def date_quick_keyboard() -> InlineKeyboardMarkup:
    today = datetime.now().date()
    buttons = []
    for label, offset in [("Сегодня", 0), ("Завтра", 1), ("+3 дня", 3), ("+7 дней", 7)]:
        d = today + timedelta(days=offset)
        buttons.append(
            InlineKeyboardButton(
                f"{label} ({d.strftime('%d.%m')})",
                callback_data=f"date_pick_{d.strftime('%Y-%m-%d')}",
            )
        )
    return InlineKeyboardMarkup(
        [
            buttons[:2],
            buttons[2:],
            [InlineKeyboardButton("✏️ Ввести дату вручную", callback_data="date_manual")],
            [InlineKeyboardButton("◀️ Назад", callback_data="back_to_station")],
            [InlineKeyboardButton("❌ Отмена", callback_data="cancel_search")],
        ]
    )


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


def format_trains_list(trains: list[dict]) -> str:
    lines = []
    for i, t in enumerate(trains, 1):
        dep = t.get("departure") or "??:??"
        arr = t.get("arrival") or "??:??"
        line = f"{i}. <b>{dep} → {arr}</b>"
        if t.get("duration"):
            line += f" ({t['duration']})"
        if t.get("number"):
            line += f" · №{t['number']}"
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
    "2️⃣ Выберите дату и поезд\n"
    "3️⃣ Получите уведомление, когда билеты появятся\n\n"
    "Проверка — каждые 60 секунд. Нажмите кнопку ниже, чтобы начать 👇"
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
    "• Пишите станции как на сайте БЖД (например: <i>Минск-Пассажирский</i>)\n"
    "• Можно выбрать популярную станцию кнопкой\n"
    "• После создания подписки бот сразу делает первую проверку\n"
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
        time_line = f"🕐 <b>{dep} → {arr}</b>"
        if sub.get("duration"):
            time_line += f" ({sub['duration']})"
        time_line += f" · №{sub['train']}"
    else:
        time_line = f"🚂 Поезд <b>{sub['train']}</b>"
    return (
        f"🆔 <code>{sub['id']}</code>\n"
        f"{time_line} · {sub['date'].replace('-', '.')}\n"
        f"📍 {sub['from']} → {sub['to']}\n"
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
        schedule = f"🕐 Отправление: <b>{dep}</b> → прибытие <b>{arr}</b>"
        if sub.get("duration"):
            schedule += f" ({sub['duration']})"
        schedule += f"\n🚂 Поезд №<b>{sub['train']}</b>"
    else:
        schedule = f"🚂 Поезд: <b>{sub['train']}</b>"
    return (
        f"✅ <b>Подписка создана!</b>\n\n"
        f"🆔 ID: <code>{sub['id']}</code>\n"
        f"{schedule}\n"
        f"📅 Дата: <b>{date_display}</b>\n"
        f"📍 Маршрут: <b>{sub['from']}</b> → <b>{sub['to']}</b>\n\n"
        f"⏰ Автопроверка каждые 60 сек\n"
        f"🔔 Уведомлю, как только появятся билеты!"
    )


def format_tickets_message(
    train_num: str,
    date: str,
    items: list[dict],
    url: str,
    departure: str = "",
    arrival: str = "",
) -> str:
    date_display = date.replace("-", ".")
    if departure and arrival:
        header = f"🔥 <b>БИЛЕТЫ ПОЯВИЛИСЬ!</b>\n🕐 <b>{departure} → {arrival}</b> · №{train_num} · {date_display}\n"
    else:
        header = f"🔥 <b>БИЛЕТЫ ПОЯВИЛИСЬ!</b>\n🚂 Поезд <b>{train_num}</b> · {date_display}\n"
    lines = [header]
    for item in items:
        line = f"• {item['type']}: <b>{item['quantity']}</b> мест"
        if item.get("price"):
            line += f" — от {item['price']} BYN"
        lines.append(line)
    lines.append(f"\n🔗 <a href='{url}'>Открыть на pass.rw.by</a>")
    return "\n".join(lines)


def station_by_index(index: int) -> str:
    return POPULAR_STATIONS[index]