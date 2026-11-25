import telebot
import json
from telebot.types import LabeledPrice, InlineKeyboardMarkup, InlineKeyboardButton

BOT_TOKEN = '9174710090:AAELUzQyyWbPxlZEMPtIIH0haf7ijYYNmMA'
ADMIN_ID = 8834515141

bot = telebot.TeleBot(BOT_TOKEN)

SKIN_PRICES = {
    "boost5": {"name": "Буст x5 (1 день)", "price": 30},
}

# Меню пополнения
@bot.message_handler(commands=['topup'])
def topup_menu(message):
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("⭐ 50 Звезд (100 руб)", callback_data="buy_stars_50"))
    markup.add(InlineKeyboardButton("⭐ 100 Звезд (200 руб)", callback_data="buy_stars_100"))
    bot.send_message(message.chat.id, "Выбери пакет пополнения Telegram Stars:", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith('buy_stars_'))
def process_topup(call):
    amount = int(call.data.split('_')[2])
    # ВАЖНО: В Telegram Stars нельзя напрямую списать деньги с карты через бота. 
    # Мы используем встроенную систему Telegram.
    prices = [LabeledPrice(label=f"Пополнение на {amount} Stars", amount=amount)]
    bot.send_invoice(
        chat_id=call.message.chat.id,
        title="Пополнение баланса",
        description=f"Покупка {amount} звезд для игры",
        invoice_payload=f"topup_{amount}",
        provider_token="", # Для звезд оставляем пустым
        currency="XTR", # Код Telegram Stars
        prices=prices,
        start_parameter="topup"
    )

@bot.message_handler(commands=['start'])
def start(message):
    text = message.text
    if "w_" in text:
        try:
            parts = text.split("w_")
            data = parts[1].split("_")
            user_id = int(data[0])
            coins = int(data[1])
            
            admin_text = f"🚨 **ЗАЯВКА НА ВЫВОД**\n\nИгрок: {user_id}\nМонет: {coins}\n\nВыдать подарок?"
            markup = InlineKeyboardMarkup()
            markup.add(InlineKeyboardButton("🎁 Выдать", callback_data=f"gift_{user_id}"))
            bot.send_message(ADMIN_ID, admin_text, reply_markup=markup)
            bot.send_message(user_id, "✅ Заявка принята!")
        except Exception as e: print(e)

    elif "buy_" in text:
        try:
            skin_id = text.split("buy_")[1]
            if skin_id in SKIN_PRICES:
                item = SKIN_PRICES[skin_id]
                prices = [LabeledPrice(label=item["name"], amount=item["price"])]
                bot.send_invoice(
                    chat_id=message.chat.id, title=f"Покупка: {item['name']}", description="Разблокировка предмета",
                    invoice_payload=f"pay_{skin_id}", provider_token="", currency="XTR", prices=prices, start_parameter="buy-item"
                )
        except Exception as e: print(e)
    else:
        bot.reply_to(message, "Привет! Играй в игру по кнопке внизу 👇\nДля пополнения баланса напиши /topup")

@bot.pre_checkout_query_handler(func=lambda query: True)
def checkout(pre_checkout_query):
    bot.answer_pre_checkout_query(pre_checkout_query.id, ok=True)

@bot.message_handler(content_types=['successful_payment'])
def got_payment(message):
    payload = message.successful_payment.invoice_payload
    amount = message.successful_payment.total_amount
    
    if "topup" in payload:
        bot.send_message(ADMIN_ID, f"💰 **ПОПОЛНЕНИЕ!**\n\nИгрок @{message.from_user.username} купил {amount} звезд.")
        bot.send_message(message.chat.id, f"✅ Баланс пополнен на {amount}⭐!\nОбнови игру (закрой и открой заново), чтобы увидеть их.")
    elif "pay_" in payload:
        item_id = payload.split('_')[1]
        bot.send_message(ADMIN_ID, f"💰 **ПОКУПКА СКИНА!**\n\nИгрок @{message.from_user.username} купил `{item_id}` за {amount}⭐!")
        bot.send_message(message.chat.id, f"✅ Оплата прошла! Скин куплен.")

@bot.message_handler(content_types=['web_app_data'])
def web_app_data(message):
    try:
        data = json.loads(message.web_app_data.data)
        if data['action'] == 'crash_lose':
            bot.send_message(ADMIN_ID, f"🚀 **КРАШ: ПРОИГРЫШ**\n\nИгрок @{message.from_user.username} проиграл {data['bet']} ⭐.")
        elif data['action'] == 'withdraw_gift':
            bot.send_message(ADMIN_ID, f"🎁 **ЗАЯВКА НА ПОДАРОК!**\n\nИгрок: @{message.from_user.username}\nID: `{message.from_user.id}`\nПодарок: **{data['gift']}**")
            bot.send_message(message.chat.id, f"✅ Заявка на '{data['gift']}' создана! Админ свяжется с вами.")
    except Exception as e: print("WebApp Error:", e)

print("Бот запущен...")
bot.polling(none_stop=True)
