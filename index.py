import asyncio
import logging
from datetime import datetime

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from config import CHECK_INTERVAL, TOKEN
from scraper import check_tickets, fetch_trains_list
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
    date_quick_keyboard,
    delete_confirm_keyboard,
    format_subscription_created,
    format_subscriptions_list,
    format_tickets_message,
    format_trains_list,
    main_menu_keyboard,
    popular_stations_keyboard,
    retry_keyboard,
    station_by_index,
    subscription_created_keyboard,
    subscriptions_list_keyboard,
    tickets_found_keyboard,
    train_schedule_label,
    trains_keyboard,
)

FROM_STATION, TO_STATION, DATE, SELECT_TRAIN = range(4)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logging.getLogger("telegram").setLevel(logging.WARNING)
logging.getLogger("selenium").setLevel(logging.WARNING)
logging.getLogger("WDM").setLevel(logging.WARNING)

load_subscriptions()


async def send_or_edit(update: Update, text: str, reply_markup=None, parse_mode="HTML"):
    """Отправляет или редактирует сообщение в зависимости от типа update."""
    if update.callback_query:
        query = update.callback_query
        try:
            await query.edit_message_text(text, reply_markup=reply_markup, parse_mode=parse_mode)
        except Exception:
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
    if update.message:
        await update.message.reply_text(HELP_TEXT, parse_mode="HTML", reply_markup=MAIN_KEYBOARD)
    return ConversationHandler.END


async def begin_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    text = (
        "📍 <b>Шаг 1 из 3</b> — станция отправления\n\n"
        "Выберите из списка или введите название вручную:"
    )
    markup = popular_stations_keyboard("from")

    if update.callback_query:
        await update.callback_query.answer()
        await send_or_edit(update, text, markup)
    elif update.message:
        await update.message.reply_text(text, reply_markup=markup, parse_mode="HTML")

    return FROM_STATION


async def get_from_station(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        query = update.callback_query
        await query.answer()
        data = query.data

        if data == "cancel_search":
            return await show_main_menu(update, context)
        if data == "from_manual":
            await query.edit_message_text(
                "✏️ Введите станцию отправления (например: <i>Минск-Пассажирский</i>):",
                parse_mode="HTML",
                reply_markup=cancel_keyboard(),
            )
            return FROM_STATION
        if data.startswith("from_"):
            idx = int(data.replace("from_", ""))
            context.user_data["from_station"] = station_by_index(idx)
        else:
            return FROM_STATION
    else:
        context.user_data["from_station"] = update.message.text.strip()

    from_st = context.user_data["from_station"]
    text = (
        f"✅ Отправление: <b>{from_st}</b>\n\n"
        f"📍 <b>Шаг 2 из 3</b> — станция прибытия\n"
        "Выберите из списка или введите вручную:"
    )
    markup = popular_stations_keyboard("to")

    if update.callback_query:
        await query.edit_message_text(text, reply_markup=markup, parse_mode="HTML")
    else:
        await update.message.reply_text(text, reply_markup=markup, parse_mode="HTML")

    return TO_STATION


async def show_to_station_step(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from_st = context.user_data.get("from_station", "—")
    text = (
        f"✅ Отправление: <b>{from_st}</b>\n\n"
        f"📍 <b>Шаг 2 из 3</b> — станция прибытия\n"
        "Выберите из списка или введите вручную:"
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
            await query.edit_message_text(
                "✏️ Введите станцию прибытия (например: <i>Брест-Центральный</i>):",
                parse_mode="HTML",
                reply_markup=cancel_keyboard(),
            )
            return TO_STATION
        if data.startswith("to_"):
            idx = int(data.replace("to_", ""))
            context.user_data["to_station"] = station_by_index(idx)
        else:
            return TO_STATION
    else:
        context.user_data["to_station"] = update.message.text.strip()

    to_st = context.user_data["to_station"]
    text = (
        f"✅ Прибытие: <b>{to_st}</b>\n\n"
        f"📅 <b>Шаг 3 из 3</b> — дата поездки\n"
        "Выберите дату кнопкой или введите в формате <b>ДД.ММ.ГГГГ</b>:"
    )
    markup = date_quick_keyboard()

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
        f"📍 {context.user_data['from_station']} → {context.user_data['to_station']}\n\n"
        "⏳ Это может занять до 40 секунд..."
    )

    if update.callback_query:
        await update.callback_query.edit_message_text(wait_text, parse_mode="HTML")
    else:
        wait_msg = await update.message.reply_text(wait_text, parse_mode="HTML")

    trains = await fetch_trains_list(
        context.user_data["from_station"],
        context.user_data["to_station"],
        date_str,
    )

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
        await query.answer()
        data = query.data

        if data == "cancel_search":
            return await show_main_menu(update, context)
        if data == "back_to_station":
            return await show_to_station_step(update, context)
        if data == "date_manual":
            await query.edit_message_text(
                "✏️ Введите дату в формате <b>ДД.ММ.ГГГГ</b> (например: 31.12.2026):",
                parse_mode="HTML",
                reply_markup=cancel_keyboard(),
            )
            return DATE
        if data.startswith("date_pick_"):
            date_str = data.replace("date_pick_", "")
            dt = datetime.strptime(date_str, "%Y-%m-%d")
            return await process_date_and_search(update, context, date_str, dt.strftime("%d.%m.%Y"))
        return DATE

    date_text = update.message.text.strip()
    try:
        dt = datetime.strptime(date_text, "%d.%m.%Y")
        if dt.date() < datetime.now().date():
            await update.message.reply_text(
                "❌ Дата не может быть в прошлом. Попробуйте снова:",
                reply_markup=cancel_keyboard(),
            )
            return DATE
        return await process_date_and_search(update, context, dt.strftime("%Y-%m-%d"), date_text)
    except ValueError:
        await update.message.reply_text(
            "❌ Неверный формат. Используйте <b>ДД.ММ.ГГГГ</b> (например: 31.12.2026)",
            parse_mode="HTML",
            reply_markup=cancel_keyboard(),
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
            "Выберите дату кнопкой или введите в формате <b>ДД.ММ.ГГГГ</b>:"
        )
        await query.edit_message_text(text, reply_markup=date_quick_keyboard(), parse_mode="HTML")
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
    )

    await query.edit_message_text(
        format_subscription_created(sub, date_display),
        parse_mode="HTML",
        reply_markup=subscription_created_keyboard(sub["id"]),
    )

    await check_single_subscription(context, user_id, sub, is_first_check=True)
    context.user_data.clear()
    return ConversationHandler.END


async def check_single_subscription(context, user_id, sub, is_first_check=False, edit_message=None):
    train_num = sub["train"]
    date = sub["date"]
    from_st = sub["from"]
    to_st = sub["to"]
    sub_id = sub["id"]

    logging.info("Проверка: поезд %s, дата %s, подписка %s, user %s", train_num, date, sub_id, user_id)

    result = await check_tickets(from_st, to_st, date, train_num)
    status = result["status"]

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
                f"❌ Поезд <b>{train_num}</b> не найден на эту дату.",
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
        schedule = train_schedule_label(sub)
        if is_first_check:
            await context.bot.send_message(
                user_id,
                f"ℹ️ Билетов на рейс <b>{schedule}</b> ({date.replace('-', '.')}) пока нет.\n"
                f"Продолжаю следить — уведомлю, когда появятся!",
                parse_mode="HTML",
                reply_markup=MAIN_KEYBOARD,
            )
            sub["first_check_done"] = True
            storage.save_subscriptions()
        if edit_message:
            await edit_message.edit_text(
                f"ℹ️ Билетов на поезд <b>{train_num}</b> пока нет.\nПродолжаю следить...",
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
    for uid, sub in active_subscriptions():
        await check_single_subscription(context, int(uid), sub, is_first_check=False)
        await asyncio.sleep(1)


async def show_user_subscriptions(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
        msg = await query.edit_message_text("🔍 Проверяю билеты... Подождите до 30 сек.")
        await check_single_subscription(context, user_id, sub, is_first_check=True, edit_message=msg)
        return

    if data.startswith("delete_confirm_"):
        sub_id = data.replace("delete_confirm_", "")
        sub = find_subscription(user_id, sub_id)
        if not sub:
            await query.edit_message_text("❌ Подписка не найдена.")
            return
        await query.edit_message_text(
            f"🗑 Удалить подписку <b>{train_schedule_label(sub)}</b> "
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
    await application.bot.set_my_commands(BOT_COMMANDS)


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logging.error("Exception while handling update: %s", context.error, exc_info=context.error)


def main():
    app = Application.builder().token(TOKEN).post_init(post_init).build()

    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler("start", show_main_menu),
            CommandHandler("search", begin_search),
            CallbackQueryHandler(begin_search, pattern="^start_search$"),
            MessageHandler(filters.Regex(f"^{BTN_NEW_SEARCH}$"), begin_search),
        ],
        states={
            FROM_STATION: [
                CallbackQueryHandler(get_from_station, pattern="^(from_|cancel_search)"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, get_from_station),
            ],
            TO_STATION: [
                CallbackQueryHandler(get_to_station, pattern="^(to_|cancel_search)"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, get_to_station),
            ],
            DATE: [
                CallbackQueryHandler(get_date, pattern="^(date_|back_to_station|cancel_search)"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, get_date),
            ],
            SELECT_TRAIN: [
                CallbackQueryHandler(select_train, pattern="^(select_train_|back_to_date|cancel_search)"),
            ],
        },
        fallbacks=[
            CommandHandler("cancel", cancel),
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
        app.job_queue.run_repeating(background_checker, interval=CHECK_INTERVAL, first=15)

    print("TrainWaited bot started")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
