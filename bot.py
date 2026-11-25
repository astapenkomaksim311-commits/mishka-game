import telebot
import json
import os
import time
import hmac
import hashlib
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qsl
from telebot.types import LabeledPrice, InlineKeyboardMarkup, InlineKeyboardButton

# <<< ВСТАВЬ СЮДА НОВЫЙ ТОКЕН ОТ BOTFATHER (формат: 123456789:ABC...) >>>
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

# ================== СЕРВЕРНЫЙ БАЛАНС И ЛИДЕРБОРД ==================
PLAYERS_FILE = "/data/players.json"
PLAYERS = {}
LOCK = threading.Lock()
ONLINE_SEC = 180  # активность за 3 минуты = онлайн


def load_players():
    global PLAYERS
    try:
        with open(PLAYERS_FILE, "r", encoding="utf-8") as f:
            PLAYERS = json.load(f)
    except Exception:
        PLAYERS = {}


def save_players():
    try:
        os.makedirs(os.path.dirname(PLAYERS_FILE), exist_ok=True)
        with open(PLAYERS_FILE, "w", encoding="utf-8") as f:
            json.dump(PLAYERS, f, ensure_ascii=False)
    except Exception as e:
        print("save players error:", e)


def validate_init_data(init_data):
    """Проверяет подпись Telegram initData — только настоящие игроки попадают на сервер."""
    try:
        pairs = dict(parse_qsl(init_data, keep_blank_values=True))
        given_hash = pairs.pop("hash", None)
        if not given_hash:
            return None
        dcs = "\n".join(f"{k}={v}" for k, v in sorted(pairs.items()))
        secret = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
        calc = hmac.new(secret, dcs.encode(), hashlib.sha256).hexdigest()
        if calc != given_hash:
            return None
        return json.loads(pairs.get("user", "{}"))
    except Exception:
        return None


def display_name(p):
    if p.get("username"):
        return "@" + p["username"]
    return p.get("name") or "Игрок"


def merge_user(user, data):
    uid = str(user.get("id", ""))
    if not uid:
        return None
    with LOCK:
        old = PLAYERS.get(uid, {})
        rec = {
            "id": uid,
            "username": (user.get("username") or "").lstrip("@"),
            "name": user.get("first_name") or "Игрок",
            "wallet": max(int(old.get("wallet", 0) or 0), int(data.get("wallet", 0) or 0)),
            "stars": max(int(old.get("stars", 0) or 0), int(data.get("stars", 0) or 0)),
            "best": max(int(old.get("best", 0) or 0), int(data.get("best", 0) or 0)),
            "gifts": list(data.get("gifts", old.get("gifts", []))),
            "skins": sorted(set(old.get("skins", [])) | set(data.get("skins", []))),
            "boostUntil": max(int(old.get("boostUntil", 0) or 0), int(data.get("boostUntil", 0) or 0)),
            "ts": time.time(),
        }
        PLAYERS[uid] = rec
        save_players()
        return rec


class ApiHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _reply(self, code, body, ctype="application/json; charset=utf-8"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except Exception:
            pass

    def do_OPTIONS(self):
        self._reply(204, b"")

    def do_GET(self):
        try:
            if self.path.startswith("/api/leaderboard"):
                now = time.time()
                with LOCK:
                    players = [dict(p) for p in PLAYERS.values()]
                players.sort(key=lambda p: p.get("best", 0), reverse=True)
                top = players[:20]
                online = sum(1 for p in players if now - p.get("ts", 0) < ONLINE_SEC)
                payload = {
                    "ok": True,
                    "online": online,
                    "total": len(players),
                    "top": [
                        {"id": p["id"], "name": display_name(p), "best": p.get("best", 0),
                         "wallet": p.get("wallet", 0), "online": (now - p.get("ts", 0)) < ONLINE_SEC}
                        for p in top
                    ],
                }
                self._reply(200, json.dumps(payload, ensure_ascii=False).encode("utf-8"))
            elif self.path in ("/", "/index.html"):
                try:
                    with open("index.html", "rb") as f:
                        self._reply(200, f.read(), "text/html; charset=utf-8")
                except Exception:
                    self._reply(200, "<h1>Игра: открой через бота</h1>".encode("utf-8"), "text/html; charset=utf-8")
            elif self.path == "/api/ping":
                self._reply(200, b'{"ok": true}')
            else:
                self._reply(404, b'{"ok": false}')
        except Exception as e:
            print("GET error:", e)

    def do_POST(self):
        try:
            if self.path.startswith("/api/sync"):
                length = int(self.headers.get("Content-Length", 0) or 0)
                raw = self.rfile.read(length) if length else b"{}"
                try:
                    data = json.loads(raw)
                except Exception:
                    data = {}
                user = validate_init_data(data.get("initData", ""))
                if not user:
                    self._reply(401, b'{"ok": false, "error": "auth"}')
                    return
                rec = merge_user(user, data)
                if not rec:
                    self._reply(400, b'{"ok": false, "error": "bad user"}')
                    return
                self._reply(200, json.dumps({"ok": True, "you": rec}, ensure_ascii=False).encode("utf-8"))
            else:
                self._reply(404, b'{"ok": false}')
        except Exception as e:
            print("POST error:", e)

    def log_message(self, *args):
        pass  # не шумим в логи


def run_api():
    ports = []
    try:
        env_port = int(os.environ.get("PORT", 0) or 0)
        if env_port:
            ports.append(env_port)
    except Exception:
        pass
    ports += [8080, 5000, 80]
    for port in ports:
        try:
            ThreadingHTTPServer(("0.0.0.0", port), ApiHandler).serve_forever()
        except Exception as e:
            print("API port", port, "failed:", e)


load_players()
threading.Thread(target=run_api, daemon=True).start()
print("API-сервер запущен (порты 8080/5000/80)")

# ================== БОТ ==================
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
        markup.add(InlineKeyboardButton("🎮 Открыть игру", url=f"https://t.me/{BOT_USERNAME}/{APP_SHORT_NAME}?startapp=menu"))
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
        markup.add(InlineKeyboardButton("🎮 Забрать звёзды в игре",
                                        url=f"https://t.me/{BOT_USERNAME}/{APP_SHORT_NAME}?startapp=topup_{amount}"))
        bot.send_message(ADMIN_ID, f"💰 ПОПОЛНЕНИЕ! Игрок {name} купил {amount} звёзд.")
        bot.send_message(message.chat.id, "✅ Оплата прошла! Нажми кнопку — звёзды сразу начислятся в игре:",
                         reply_markup=markup)
    elif payload.startswith("pay_"):
        item_id = payload.split('_')[1]
        item = SKIN_PRICES.get(item_id, {})
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("🎮 Активировать в игре",
                                        url=f"https://t.me/{BOT_USERNAME}/{APP_SHORT_NAME}?startapp=boost_{item_id}"))
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

        if data.get('action') == 'withdraw_gift':
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
