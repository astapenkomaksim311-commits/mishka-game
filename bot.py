import telebot
import json
from telebot.types import LabeledPrice, InlineKeyboardMarkup, InlineKeyboardButton

# <<< ИЗМЕНИ ЭТИ ТРИ СТРОЧКИ ПОД СЕБЯ >>>
BOT_TOKEN = "9174710090:AAELUzQyyWbPxlZEMPtIIH0haf7ijYYNmMA"   # сначала /revoke в @BotFather, потом новый токен!
ADMIN_ID = 8834515141                          # твой Telegram ID
APP_SHORT_NAME = "@MishkaRunGame_bot"                         # короткое имя мини-аппа из /newapp

SKIN_PRICES = {
    "boost5": {"name": "Буст x5 (1 день)", "price": 30},
}

bot = telebot.TeleBot(BOT_TOKEN)


def game_url(startapp: str) -> str:
    """Ссылка, которая открывает мини-апп и передаёт ему, что куплено."""
    return f"https://t.me/{BOT_USERNAME}/{APP_SHORT_NAME}?startapp={startapp}"


# --- ПОПОЛНЕНИЕ ---
@bot.message_handler(commands=['topup'])
def topup_menu(message):
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("⭐ 50 Звёзд (50 ⭐)", callback_data="buy_stars_50"))
    markup.add(InlineKeyboardButton("⭐ 100 Звёзд (100 ⭐)", callback_data="buy_stars_100"))
    bot.send_message(message.chat.id, "Выбери пакет пополнения Telegram Stars:", reply_markup=markup)


@bot.callback_query_handler(func=lambda call: call.data.startswith('buy_stars_'))
def process_topup(call):
    amount = int(call.data.split('_')[2])
    prices = [LabeledPrice(label=f"Пополнение на {amount} Stars", amount=amount)]
    bot.send_invoice(
        chat_id=call.message.chat.id,
        title="Пополнение баланса",
        description=f"Покупка {amount} звёзд для игры",
        invoice_payload=f"topup_{amount}",
        provider_token="",      # для звёзд оставляем пустым
        currency="XTR",
        prices=prices,
        start_parameter="topup"
    )


# --- СТАРТ / DEEP-LINK ---
@bot.message_handler(commands=['start'])
def start(message):
    text = message.text or ""
    payload = text.replace("/start", "", 1).strip() if text.startswith("/start") else ""

    # Заявка на вывод подарка: /start w_<user_id>_<coins>
    if payload.startswith("w_"):
        try:
            data = payload[2:].split("_")
            user_id = int(data[0])
            coins = int(data[1])
            markup = InlineKeyboardMarkup()
            markup.add(
                InlineKeyboardButton("🎁 Выдать", callback_data=f"gift_ok_{user_id}"),
                InlineKeyboardButton("❌ Отклонить", callback_data=f"gift_no_{user_id}"),
            )
            bot.send_message(ADMIN_ID, f"🚨 ЗАЯВКА НА ВЫВОД\n\nИгрок: {user_id}\nМонет: {coins}\n\nВыдать подарок?",
                             parse_mode="Markdown", reply_markup=markup)
            bot.send_message(user_id, "✅ Заявка принята! Админ свяжется с вами.")
        except Exception as e:
            print("w_ error:", e)

    # Покупка скина за звёзды: /start buy_<skin_id>
    elif payload.startswith("buy_"):
        try:
            skin_id = payload[4:]
            if skin_id in SKIN_PRICES:
                item = SKIN_PRICES[skin_id]
                prices = [LabeledPrice(label=item["name"], amount=item["price"])]
                bot.send_invoice(
                    chat_id=message.chat.id,
                    title=f"Покупка: {item['name']}",
                    description="Разблокировка предмета",
                    invoice_payload=f"pay_{skin_id}",
                    provider_token="",
                    currency="XTR",
                    prices=prices,
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


# --- КНОПКИ ВЫДАЧИ ПОДАРКА (только админ) ---
@bot.callback_query_handler(func=lambda call: call.data.startswith("gift_ok_") or call.data.startswith("gift_no_"))
def gift_decision(call):
    if call.from_user.id != ADMIN_ID:
        bot.answer_callback_query(call.id, "Только для админа!")
        return
    action, user_id = call.data.split("_")[1], int(call.data.split("_")[2])
    if action == "ok":
        bot.send_message(user_id, "🎁 Твой подарок отправлен! Проверь подарки в Telegram.")
        bot.edit_message_text("✅ Подарок выдан.", call.message.chat.id, call.message.message_id)
    else:
        bot.send_message(user_id, "❌ К сожалению, заявку на подарок отклонили.")
        bot.edit_message_text("❌ Заявка отклонена.", call.message.chat.id, call.message.message_id)
    bot.answer_callback_query(call.id)


# --- ОПЛАТА ПРОШЛА ---
@bot.pre_checkout_query_handler(func=lambda query: True)
def checkout(pre_checkout_query):
    bot.answer_pre_checkout_query(pre_checkout_query.id, ok=True)


@bot.message_handler(content_types=['successful_payment'])
def got_payment(message):
    payload = message.successful_payment.invoice_payload
    amount = message.successful_payment.total_amount
    name = f"@{message.from_user.username}" if message.from_user.username else str(message.from_user.id)

    if payload.startswith("topup"):
        # Кнопка открывает игру с параметром topup_N — игра сама начислит звёзды
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("🎮 Забрать звёзды в игре", url=game_url(f"topup_{amount}")))
        bot.send_message(ADMIN_ID, f"💰 ПОПОЛНЕНИЕ!\n\nИгрок {name} купил {amount} звёзд.", parse_mode="Markdown")
        bot.send_message(message.chat.id,
                         f"✅ Оплата прошла! Нажми кнопку — звёзды сразу начислятся в игре:",
                         reply_markup=markup)
    elif payload.startswith("pay_"):
        # Кнопка открывает игру с параметром skin_<id> — игра сама выдаст скин
        item_id = payload.split('_')[1]
        item = SKIN_PRICES.get(item_id, {})
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("🎮 Забрать скин в игре", url=game_url(f"skin_{item_id}")))
        bot.send_message(ADMIN_ID, f"💰 ПОКУПКА СКИНА!\n\nИгрок {name} купил `{item_id}` за {amount}⭐!",
                         parse_mode="Markdown")
        bot.send_message(message.chat.id,
                         f"✅ Оплата прошла: {item.get('name', item_id)}!\nНажми кнопку — скин сразу наденется:",
                         reply_markup=markup)


# --- ДАННЫЕ ИЗ ИГРЫ ---
@bot.message_handler(content_types=['web_app_data'])
def web_app_data(message):
    try:
        data = json.loads(message.web_app_data.data)
        name = f"@{message.from_user.username}" if message.from_user.username else str(message.from_user.id)
        if data.get('action') == 'crash_lose':
            bot.send_message(ADMIN_ID, f"🚀 КРАШ: ПРОИГРЫШ\n\nИгрок {name} проиграл {data.get('bet')} ⭐.",
                             parse_mode="Markdown")
        elif data.get('action') == 'withdraw_gift':
            markup = InlineKeyboardMarkup()
            markup.add(
                InlineKeyboardButton("🎁 Выдать", callback_data=f"gift_ok_{message.from_user.id}"),
                InlineKeyboardButton("❌ Отклонить", callback_data=f"gift_no_{message.from_user.id}"),
            )
            bot.send_message(ADMIN_ID,
                             f"🎁 ЗАЯВКА НА ПОДАРОК!\n\nИгрок: {name}\nID: `{message.from_user.id}`\nПодарок: **{data.get('gift')}**",
                             parse_mode="Markdown", reply_markup=markup)
            bot.send_message(message.chat.id, f"✅ Заявка на «{data.get('gift')}» создана! Админ свяжется с вами.")
    except Exception as e:
        print("WebApp Error:", e)


print("Бот запущен...")
bot.polling(none_stop=True)
