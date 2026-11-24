import telebot

# ВСТАВЬ СЮДА ТОКЕН В КАВЫЧКАХ (тот, что дал BotFather)
BOT_TOKEN = '9174710090:AAGoBcR_3WcSZSoKFHuioG0v-WJFuXgNsxds'
# ВСТАВЬ СЮДА СВОЙ ID ЦИФРАМИ (без кавычек)
ADMIN_ID = 8834515141 

bot = telebot.TeleBot(BOT_TOKEN)

@bot.message_handler(commands=['start'])
def start(message):
    text = message.text
    if "w_" in text:
        try:
            parts = text.split("w_")
            data = parts[1].split("_")
            user_id = int(data[0])
            coins = int(data[1])
            
            if coins >= 1500:
                admin_text = f"🚨 ЗАЯВКА НА ВЫВОД!\n\nИгрок набрал {coins} монет.\nЕго ID: {user_id}"
                markup = telebot.types.InlineKeyboardMarkup()
                btn = telebot.types.InlineKeyboardButton(text="🎁 Выдать подарок", callback_data=f"gift_{user_id}")
                markup.add(btn)
                
                bot.send_message(ADMIN_ID, admin_text, reply_markup=markup)
                bot.send_message(user_id, "✅ Заявка принята! Ожидай подарок.")
            else:
                bot.send_message(user_id, "❌ Ты набрал слишком мало монет.")
        except Exception as e:
            print("Ошибка:", e)
    else:
        bot.reply_to(message, "Привет! Играй в игру по кнопке внизу 👇")

@bot.callback_query_handler(func=lambda call: call.data.startswith('gift_'))
def send_gift(call):
    if call.from_user.id == ADMIN_ID:
        user_id = int(call.data.split('_')[1])
        try:
            gift_id = "5170145012310081615" 
            bot.send_gift(chat_id=user_id, gift_id=gift_id)
            bot.answer_callback_query(call.id, "Подарок отправлен!")
            bot.edit_message_text("✅ Подарок выдан!", chat_id=call.message.chat.id, message_id=call.message.message_id)
            bot.send_message(user_id, "🎁 Твой подарок пришел!")
        except Exception as e:
            bot.answer_callback_query(call.id, f"Ошибка: {e}")

print("Бот запущен...")
bot.polling(none_stop=True)
