import telebot
import json
from telebot.types import LabeledPrice, WebAppInfo, InlineKeyboardMarkup, InlineKeyboardButton

BOT_TOKEN = '9174710090:AAF_sRinb4AIqQKNkbuftaFSKGhu1CHbT6c'
ADMIN_ID = 8834515141 # Твой ID

bot = telebot.TeleBot(BOT_TOKEN)

# Цены на скины за звезды
SKIN_PRICES = {
    "boost5": {"name": "Буст x5 (1 день)", "price": 30},
    "boost7": {"name": "Буст x7 (2 дня)", "price": 50},
    "boost10": {"name": "Буст x10 (3 дня)", "price": 100},
    "lion": {"name": "Король Лев (x8)", "price": 25} # Из прошлой версии
}

@bot.message_handler(commands=['start'])
def start(message):
    text = message.text
    # Обработка вывода монет в игре (1500 монет)
    if "w_" in text:
        try:
            parts = text.split("w_")
            data = parts[1].split("_")
            user_id = int(data[0])
            coins = int(data[1])
            
            admin_text = f"🚨 **ЗАЯВКА НА ВЫВОД**\n\nИгрок: {user_id}\nМонет: {coins}\n\nВыдать подарок (15⭐)?"
            markup = InlineKeyboardMarkup()
            markup.add(InlineKeyboardButton("🎁 Выдать подарок", callback_data=f"gift_{user_id}"))
            bot.send_message(ADMIN_ID, admin_text, reply_markup=markup)
            bot.send_message(user_id, "✅ Заявка на вывод принята!")
        except Exception as e: print(e)

    # Обработка покупки скина (buy_skin_id)
    elif "buy_" in text:
        try:
            skin_id = text.split("buy_")[1]
            if skin_id in SKIN_PRICES:
                item = SKIN_PRICES[skin_id]
                prices = [LabeledPrice(label=item["name"], amount=item["price"])]
                
                bot.send_invoice(
                    chat_id=message.chat.id,
                    title=f"Покупка: {item['name']}",
                    description="Разблокировка предмета в игре",
                    invoice_payload=f"pay_{skin_id}", 
                    provider_token="", 
                    currency="XTR", # Telegram Stars
                    prices=prices,
                    start_parameter="buy-item"
                )
        except Exception as e: print(e)

    # Обычный старт
    else:
        bot.reply_to(message, "Привет! Играй в игру по кнопке внизу 👇")

# Обработка успешной оплаты
@bot.pre_checkout_query_handler(func=lambda query: True)
def checkout(pre_checkout_query):
    bot.answer_pre_checkout_query(pre_checkout_query.id, ok=True)

@bot.message_handler(content_types=['successful_payment'])
def got_payment(message):
    payload = message.successful_payment.invoice_payload
    item_id = payload.split('_')[1]
    
    # Оповещаем ТЕБЯ (Админа)
    bot.send_message(ADMIN_ID, f"💰 **ПОКУПКА!**\n\nИгрок {message.from_user.first_name} (@{message.from_user.username}) купил `{item_id}` за {message.successful_payment.total_amount} звезд!")
    
    bot.send_message(message.chat.id, f"✅ Оплата прошла! Предмет куплен.\nЗайди в игру (нажми на кнопку игры заново), чтобы он появился в магазине.")

# Ловим данные из WebApp (Краш игра)
@bot.message_handler(content_types=['web_app_data'])
def web_app_data(message):
    try:
        data = json.loads(message.web_app_data.data)
        if data['action'] == 'crash_lose':
            bet = data['bet']
            bot.send_message(ADMIN_ID, f"🚀 **КРАШ: ПРОИГРЫШ**\n\nИгрок проиграл {bet} ⭐ (Ракета взорвалась). Эти звезды остались у тебя!")
            bot.send_message(message.chat.id, f"💥 Ракета взорвалась! Ты потерял {bet} ⭐.")
    except Exception as e:
        print("WebApp Error:", e)

print("Бот запущен...")
bot.polling(none_stop=True)
