import telebot
import json
from telebot.types import LabeledPrice, InlineKeyboardMarkup, InlineKeyboardButton

# <<< ВСТАВЬ СЮДА НОВЫЙ ТОКЕН ОТ BOTFATHER МЕЖДУ КАВЫЧЕК (формат: 123456789:ABC...) >>>
BOT_TOKEN = "9174710090:AAELUzQyyWbPxlZEMPtIIH0haf7ijYYNmMA"
ADMIN_ID = 8834515141
APP_SHORT_NAME = "app"
BOT_USERNAME = "MishkaRunGame_bot"

SKIN_PRICES = {
    "boost1": {"name": "Буст x3 на 1 день", "price": 30},
    "boost2": {"name": "Буст x3 на 2 дня",  "price": 50},
    "boost3": {"name": "Буст x3 на 5 дней", "price": 100},
}

bot = telebot.TeleBot(BOT_TOKEN)


def game_url(startapp: str) -> str:
    return f"https://t.me/{BOT_USERNAME}/{APP_SHORT_NAME}?startapp={startapp}"


@bot.message_handler(commands=['topup'])
def topup_menu(message):
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("⭐ 50 Звёзд (50 ⭐)", callback_data="buy_stars_50"))
    markup.add(InlineKeyboardButton("⭐ 100 Звёзд (100 ⭐)", callback_data="buy_stars_100"))
    bot.send_message(message.chat.id, "Выбери пакет пополнения Telegram Stars:", reply_markup=markup)


@bot.callback_query_handler(func=lambda call: call.data.startswith('buy_stars_'))
def process_topup(call):
    amount = int(call.data.split('_')[2])
    bot.send_invoice(
        chat_id=call.message.chat.id,
        title="Пополнение баланса",
        description=f"Покупка {amount} звёзд для игры",
        invoice_payload=f"topup_{amount}",
        provider_token="",
        currency="XTR",
        prices=[LabeledPrice(label=f"Пополнение на {amount} Stars", amount=amount)],
        start_parameter="topup"
    )


@bot.message_handler(commands=['start'])
def start(message):
    text = message.text or ""
    payload = text.replace("/start", "", 1).strip() if text.startswith("/start") else ""
    name = f"@{message.from_user.username}" if message.from_user.username else f"id{message.from_user.id}"

    if payload.startswith("w_"):
        try:
            data = payload[2:].split("_")
            stars = int(data[1])
            gift_names = {15: "🧸 Мишка", 25: "🎁 Подарочек", 50: "🍾 Шампанское", 100: "💍 Колечко"}
            gift = gift_names.get(stars, f"подарок на {stars}⭐")
            markup = InlineKeyboardMarkup()
            markup.add(
                InlineKeyboardButton("✅ Отправил", callback_data=f"gift_ok_{message.from_user.id}"),
                InlineKeyboardButton("❌ Отклонить", callback_data=f"gift_no_{message.from_user.id}"),
            )
            bot.send_message(ADMIN_ID,
                             f"🔔🔔🔔 ЗАЯВКА НА ВЫВОД ПОДАРКА!\n\n"
                             f"Игрок: {name}\nID: `{message.from_user.id}`\n"
                             f"Подарок: {gift} ({stars}⭐)\n\n"
                             f"👉 Открой чат с игроком → скрепка → Подарок → выбери на {stars} звёзд → Отправить.",
                             parse_mode="Markdown", reply_markup=markup)
            bot.send_message(message.chat.id, "✅ Заявка принята! Скоро отправим 🎁")
        except Exception as e:
            print("w_ error:", e)
    elif payload.startswith("buy_"):
        try:
            item_id = payload[4:]
            if item_id in SKIN_PRICES:
                item = SKIN_PRICES[item_id]
                bot.send_invoice(
                    chat_id=message.chat.id,
                    title=f"Покупка: {item['name']}",
                    description="Активация буста в игре",
                    invoice_payload=f"pay_{item_id}",
                    provider_token="",
                    currency="XTR",
                    prices=[LabeledPrice(label=item["name"], amount=item["price"])],
                    start_parameter="buy-item"
                )
            else:
                bot.reply_to(message, "Такого товара нет 🤷")
        except Exception as e:
            print("buy_ error:", e)
    else:
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("🎮 Открыть игру", url=game_url("menu")))
        bot.reply_to(message, "Привет! Играй в игру по кнопке ниже 👇\nДля пополнения баланса напиши /topup",
                     reply_markup=markup)


@bot.callback_query_handler(func=lambda call: call.data.startswith("gift_ok_") or call.data.startswith("gift_no_"))
def gift_decision(call):
    if call.from_user.id != ADMIN_ID:
        bot.answer_callback_query(call.id, "Только для админа!")
        return
    action, user_id = call.data.split("_")[1], int(call.data.split("_")[2])
    if action == "ok":
        bot.send_message(user_id, "🎁 Подарок отправлен! Проверь его в Telegram.")
        bot.edit_message_text("✅ Отмечено: подарок выдан.", call.message.chat.id, call.message.message_id)
    else:
        bot.send_message(user_id, "❌ К сожалению, заявку на подарок отклонили.")
        bot.edit_message_text("❌ Заявка отклонена.", call.message.chat.id, call.message.message_id)
    bot.answer_callback_query(call.id)


@bot.pre_checkout_query_handler(func=lambda query: True)
def checkout(pre_checkout_query):
    bot.answer_pre_checkout_query(pre_checkout_query.id, ok=True)


@bot.message_handler(content_types=['successful_payment'])
def got_payment(message):
    payload = message.successful_payment.invoice_payload
    amount = message.successful_payment.total_amount
    name = f"@{message.from_user.username}" if message.from_user.username else f"id{message.from_user.id}"

    if payload.startswith("topup"):
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("🎮 Забрать звёзды в игре", url=game_url(f"topup_{amount}")))
        bot.send_message(ADMIN_ID, f"💰 ПОПОЛНЕНИЕ! Игрок {name} купил {amount} звёзд.")
        bot.send_message(message.chat.id, "✅ Оплата прошла! Нажми кнопку — звёзды сразу начислятся в игре:",
                         reply_markup=markup)
    elif payload.startswith("pay_"):
        item_id = payload.split('_')[1]
        item = SKIN_PRICES.get(item_id, {})
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("🎮 Активировать в игре", url=game_url(f"boost_{item_id}")))
        bot.send_message(ADMIN_ID, f"💰 ПОКУПКА! Игрок {name} купил `{item_id}` за {amount}⭐!")
        bot.send_message(message.chat.id,
                         f"✅ Оплата прошла: {item.get('name', item_id)}!\nНажми кнопку — буст активируется:",
                         reply_markup=markup)


@bot.message_handler(content_types=['web_app_data'])
def web_app_data(message):
    try:
        data = json.loads(message.web_app_data.data)
        name = f"@{message.from_user.username}" if message.from_user.username else f"id{message.from_user.id}"
        uid = message.from_user.id

        if data.get('action') == 'crash_lose':
            bot.send_message(ADMIN_ID, f"🚀 КРАШ: ПРОИГРЫШ. Игрок {name} проиграл {data.get('bet')} ⭐.")
        elif data.get('action') == 'crash_win':
            bot.send_message(ADMIN_ID, f"🚀 КРАШ: ВЫИГРЫШ. Игрок {name} поставил {data.get('bet')} ⭐, забрал {data.get('win')} ⭐.")
        elif data.get('action') == 'withdraw_gift':
            gift = data.get('gift', '?')
            stars = data.get('stars', '?')
            markup = InlineKeyboardMarkup()
            markup.add(
                InlineKeyboardButton("✅ Отправил", callback_data=f"gift_ok_{uid}"),
                InlineKeyboardButton("❌ Отклонить", callback_data=f"gift_no_{uid}"),
            )
            bot.send_message(ADMIN_ID,
                             f"🔔🔔🔔 ЗАЯВКА НА ВЫВОД ПОДАРКА!\n\n"
                             f"Игрок: {name}\nID: `{uid}`\nПодарок: {gift} ({stars}⭐)\n\n"
                             f"👉 Открой чат с игроком → скрепка → Подарок → выбери на {stars} звёзд → Отправить.",
                             parse_mode="Markdown", reply_markup=markup)
            bot.send_message(message.chat.id, f"✅ Заявка на «{gift}» принята! Скоро отправим 🎁")
    except Exception as e:
        print("WebApp Error:", e)


print("Бот запущен...")
bot.polling(none_stop=True)
