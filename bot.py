import telebot
import json
from telebot.types import LabeledPrice

BOT_TOKEN = '9174710090:AAHz2xfn6cmYjwlCavw7grQNr5K5MVx6IEs'
ADMIN_ID = 8834515141

bot = telebot.TeleBot(BOT_TOKEN)

SKIN_PRICES = {
    "boost5": {"name": "Буст x5 (1 день)", "price": 30},
    "boost7": {"name": "Буст x7 (2 дня)", "price": 50},
    "boost10": {"name": "Буст x10 (3 дня)", "price": 100}
}

@bot.message_handler(commands=['start'])
def start(message):
    text = message.text
    if "w_" in text:
        try:
            parts = text.split("w_")
            data = parts[1].split("_")
            user_id = int(data[0])
            coins = int(data[1])
            
            admin_text = f"🚨 **ЗАЯВКА НА ВЫВОД**\n\nИгрок: {user_id}\nМонет: {coins}\n\nВыдать подарок (15⭐)?"
            markup = telebot.types.InlineKeyboardMarkup()
            markup.add(telebot.types.InlineKeyboardButton("🎁 Выдать", callback_data=f"gift_{user_id}"))
            bot.send_message(ADMIN_ID, admin_text, reply_markup=markup)
            bot.send_message(user_id, "✅ Заявка на вывод принята!")
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
        bot.reply_to(message, "Привет! Играй в игру по кнопке внизу 👇")

@bot.pre_checkout_query_handler(func=lambda query: True)
def checkout(pre_checkout_query):
    bot.answer_pre_checkout_query(pre_checkout_query.id, ok=True)

@bot.message_handler(content_types=['successful_payment'])
def got_payment(message):
    payload = message.successful_payment.invoice_payload
    item_id = payload.split('_')[1]
    bot.send_message(ADMIN_ID, f"💰 **ПОКУПКА!**\n\nИгрок {message.from_user.first_name} (@{message.from_user.username}) купил `{item_id}` за {message.successful_payment.total_amount}⭐!")
    bot.send_message(message.chat.id, f"✅ Оплата прошла! Предмет куплен.")

@bot.message_handler(content_types=['web_app_data'])
def web_app_data(message):
    try:
        data = json.loads(message.web_app_data.data)
        
        # Уведомление о проигрыше в Краше
        if data['action'] == 'crash_lose':
            bet = data['bet']
            bot.send_message(ADMIN_ID, f"🚀 **КРАШ: ПРОИГРЫШ**\n\nИгрок @{message.from_user.username} (ID: {message.from_user.id}) проиграл {bet} ⭐.")
        
        # Уведомление о выводе подарка
        elif data['action'] == 'withdraw_gift':
            gift_name = data['gift']
            bot.send_message(ADMIN_ID, f"🎁 **ЗАЯВКА НА ПОДАРОК!**\n\nИгрок: {message.from_user.first_name} (@{message.from_user.username})\nID: `{message.from_user.id}`\n\nХочет вывести: **{gift_name}**")
            bot.send_message(message.chat.id, f"✅ Заявка на подарок '{gift_name}' создана. Админ скоро свяжется с вами!")
            
    except Exception as e:
        print("WebApp Error:", e)

print("Бот запущен...")
bot.polling(none_stop=True)
