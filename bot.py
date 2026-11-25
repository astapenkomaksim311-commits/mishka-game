import telebot
from telebot.types import LabeledPrice

# ТВОЙ ТОКЕН И ID
BOT_TOKEN = '9174710090:AAGFhA3l7MyEd9Y2hHMcpTLci08iDpbcrOc'
ADMIN_ID = 8834515141 

bot = telebot.TeleBot(BOT_TOKEN)

@bot.message_handler(commands=['start'])
def start(message):
    text = message.text
    # 1. Проверяем вывод подарка (1500 монет)
    if "w_" in text:
        try:
            parts = text.split("w_")
            data = parts[1].split("_")
            user_id = int(data[0])
            coins = int(data[1])
            
            if coins >= 1500:
                admin_text = f"🚨 **ЗАЯВКА НА ВЫВОД!**\n\nИгрок набрал {coins} монет.\nЕго ID: `{user_id}`\n\nНажми кнопку ниже, чтобы отправить ему подарок (15 звезд)."
                markup = telebot.types.InlineKeyboardMarkup()
                btn = telebot.types.InlineKeyboardButton(text="🎁 Выдать подарок", callback_data=f"gift_{user_id}")
                markup.add(btn)
                
                bot.send_message(ADMIN_ID, admin_text, reply_markup=markup, parse_mode='Markdown')
                bot.send_message(user_id, "✅ Заявка принята! Ожидай подарок.")
            else:
                bot.send_message(user_id, "❌ Ты набрал слишком мало монет.")
        except Exception as e:
            print("Ошибка:", e)

    # 2. Проверяем покупку скина за ЗВЕЗДЫ
    elif "buy_skin_" in text:
        try:
            skin_id = text.split("buy_skin_")[1]
            user_id = message.from_user.id
            
            # Устанавливаем цену (50 звезд для золотого мишки)
            prices = [LabeledPrice(label="Скин Золотой Мишка", amount=50)]
            
            bot.send_invoice(
                chat_id=user_id,
                title="Покупка скина 👑",
                description="Золотой мишка дает x5 монет в игре!",
                invoice_payload=f"skin_{skin_id}", # Сюда прячем ID скина
                provider_token="", # Для звезд оставляем пустым
                currency="XTR", # Код Telegram Stars
                prices=prices,
                start_parameter="buy-skin"
            )
        except Exception as e:
            bot.send_message(message.from_user.id, "Ошибка при создании счета. Попробуй позже.")
            print(e)
            
    # 3. Обычный старт
    else:
        bot.reply_to(message, "Привет! Играй в игру по кнопке внизу 👇")

# Обработка кнопки Выдать подарок (Админ)
@bot.callback_query_handler(func=lambda call: call.data.startswith('gift_'))
def send_gift(call):
    if call.from_user.id == ADMIN_ID:
        user_id = int(call.data.split('_')[1])
        try:
            gift_id = "5170145012310081615" 
            bot.send_gift(chat_id=user_id, gift_id=gift_id)
            bot.answer_callback_query(call.id, "Подарок отправлен!")
            bot.edit_message_text("✅ Подарок успешно выдан игроку!", chat_id=call.message.chat.id, message_id=call.message.message_id)
            bot.send_message(user_id, "🎁 Ура! Твой подарок за 1500 монет пришел! Проверь профиль.")
        except Exception as e:
            bot.answer_callback_query(call.id, f"Ошибка: {e}")

# Обработка ЗВЕЗД: Предварительная проверка (Telegram требует это)
@bot.pre_checkout_query_handler(func=lambda query: True)
def checkout(pre_checkout_query):
    bot.answer_pre_checkout_query(pre_checkout_query.id, ok=True, error_message="Оплата не прошла.")

# Обработка ЗВЕЗД: Успешная оплата
@bot.message_handler(content_types=['successful_payment'])
def got_payment(message):
    payload = message.successful_payment.invoice_payload
    skin_id = payload.split('_')[1]
    
    # Отправляем игроку сообщение, что скин куплен
    bot.send_message(
        message.chat.id, 
        f"✅ Оплата прошла успешно! Скин ({skin_id}) разблокирован.\n\nЗайди в игру и надень его в магазине!",
        parse_mode='Markdown'
    )

print("Бот запущен...")
bot.polling(none_stop=True)
