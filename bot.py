import telebot
import json
import os
import time
import hmac
import hashlib
import threading
import html
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qsl
from telebot.types import LabeledPrice, InlineKeyboardMarkup, InlineKeyboardButton

BOT_TOKEN = "9174710090:AAELUzQyyWbPxlZEMPtIIH0haf7ijYYNmMA"
ADMIN_ID = 8834515141
APP_SHORT_NAME = "app"
BOT_USERNAME = "MishkaRunGame_bot"

SKIN_PRICES = {
    "boost1": {"name": "Буст x3 на 1 день", "price": 30},
    "boost2": {"name": "Буст x3 на 2 дня",  "price": 50},
    "boost3": {"name": "Буст x3 на 5 дней", "price": 100},
}
TOPUP_MIN = 10
TOPUP_MAX = 200

bot = telebot.TeleBot(BOT_TOKEN)

# ================== ДАННЫЕ ==================
PLAYERS_FILE = "/data/players.json"
REQUESTS_FILE = "/data/requests.json"
PLAYERS = {}
REQUESTS = []
LOCK = threading.Lock()
ONLINE_SEC = 180


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


def load_requests():
    global REQUESTS
    try:
        with open(REQUESTS_FILE, "r", encoding="utf-8") as f:
            REQUESTS = json.load(f)
    except Exception:
        REQUESTS = []


def save_requests():
    try:
        os.makedirs(os.path.dirname(REQUESTS_FILE), exist_ok=True)
        with open(REQUESTS_FILE, "w", encoding="utf-8") as f:
            json.dump(REQUESTS, f, ensure_ascii=False)
    except Exception as e:
        print("save requests error:", e)


def add_request(req):
    if not isinstance(req, dict):
        return None
    req["time"] = req.get("time") or int(time.time() * 1000)
    req["id"] = req.get("id") or f"{req.get('uid')}_{req['time']}"
    with LOCK:
        if any(r.get("id") == req["id"] for r in REQUESTS):
            return req["id"]
        REQUESTS.append(req)
        save_requests()
    return req["id"]


def remove_request(rid):
    with LOCK:
        REQUESTS[:] = [r for r in REQUESTS if r.get("id") != rid]
        save_requests()


def validate_init_data(init_data):
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
    """Работает и с dict, и с объектом Telegram User."""
    if p is None:
        return "Игрок"
    if isinstance(p, dict):
        uname = p.get("username")
        fname = p.get("first_name")
    else:
        uname = getattr(p, "username", None)
        fname = getattr(p, "first_name", None)
    if uname:
        return "@" + uname
    return fname or "Игрок"


def esc(s):
    return html.escape(str(s or ""), quote=False)


def merge_user(user, data):
    """Баланс — истина от клиента (последняя запись), рекорд — только максимум."""
    uid = str(user.get("id", ""))
    if not uid:
        return None
    with LOCK:
        old = PLAYERS.get(uid, {})
        rec = {
            "id": uid,
            "username": (user.get("username") or "").lstrip("@"),
            "name": user.get("first_name") or "Игрок",
            "wallet": int(data.get("wallet", old.get("wallet", 0)) or 0),
            "stars": int(data.get("stars", old.get("stars", 0)) or 0),
            "best": max(int(old.get("best", 0) or 0), int(data.get("best", 0) or 0)),
            "gifts": list(data.get("gifts", old.get("gifts", []))),
            "skins": sorted(set(old.get("skins", [])) | set(data.get("skins", []))),
            "boostUntil": max(int(old.get("boostUntil", 0) or 0), int(data.get("boostUntil", 0) or 0)),
            "ts": time.time(),
        }
        PLAYERS[uid] = rec
        save_players()
        return rec


def notify_admin_request(req):
    """Заявка админу. HTML вместо Markdown — юзернеймы с _ не ломаются."""
    try:
        name = esc(req.get("name") or "игрок")
        uid = esc(req.get("uid") or "?")
        if req.get("type") == "stars":
            n = req.get("n", 0)
            markup = InlineKeyboardMarkup()
            markup.add(
                InlineKeyboardButton("✅ Отправил", callback_data=f"wd_ok_{uid}_{n}"),
                InlineKeyboardButton("❌ Отклонить", callback_data=f"wd_no_{uid}_{n}"),
            )
            bot.send_message(
                ADMIN_ID,
                f"💸💸💸 ВЫВОД ЗВЁЗД!\n\n"
                f"Игрок: {name}\nID: <code>{uid}</code>\n"
                f"Сумма: {n} ⭐\n\n"
                f"👉 Переведи игроку {n} звёзд (Telegram → Профиль → Звёзды → Перевести).",
                parse_mode="HTML", reply_markup=markup,
            )
        else:
            gift = esc(req.get("gift", "?"))
            stars = req.get("stars", 0)
            markup = InlineKeyboardMarkup()
            markup.add(
                InlineKeyboardButton("✅ Отправил", callback_data=f"gift_ok_{uid}"),
                InlineKeyboardButton("❌ Отклонить", callback_data=f"gift_no_{uid}"),
            )
            bot.send_message(
                ADMIN_ID,
                f"🔔🔔🔔 ЗАЯВКА НА ВЫВОД ПОДАРКА!\n\n"
                f"Игрок: {name}\nID: <code>{uid}</code>\n"
                f"Подарок: {gift} ({stars}⭐)\n\n"
                f"👉 Открой чат с игроком → скрепка → Подарок → на {stars} звёзд → Отправить.",
                parse_mode="HTML", reply_markup=markup,
            )
    except Exception as e:
        print("notify_admin_request error:", e)
        traceback.print_exc()


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
            elif self.path.startswith("/api/requests"):
                with LOCK:
                    lst = list(REQUESTS)
                self._reply(200, json.dumps({"ok": True, "list": lst}, ensure_ascii=False).encode("utf-8"))
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
            length = int(self.headers.get("Content-Length", 0) or 0)
            raw = self.rfile.read(length) if length else b"{}"
            try:
                data = json.loads(raw)
            except Exception:
                data = {}

            if self.path.startswith("/api/sync"):
                user = validate_init_data(data.get("initData", ""))
                if not user:
                    self._reply(401, b'{"ok": false, "error": "auth"}')
                    return
                rec = merge_user(user, data)
                if not rec:
                    self._reply(400, b'{"ok": false, "error": "bad user"}')
                    return
                self._reply(200, json.dumps({"ok": True, "you": rec}, ensure_ascii=False).encode("utf-8"))

            elif self.path.startswith("/api/requests/done"):
                rid = data.get("id")
                remove_request(rid)
                self._reply(200, b'{"ok": true}')

            elif self.path.startswith("/api/request"):
                user = validate_init_data(data.get("initData", ""))
                if not user:
                    self._reply(401, b'{"ok": false, "error": "auth"}')
                    return
                req = data.get("req") or {}
                req["uid"] = str(user.get("id", "")) or str(req.get("uid", ""))
                req["username"] = user.get("username") or ""
                req["name"] = display_name(user)
                rid = add_request(req)
                if rid:
                    notify_admin_request(req)
                self._reply(200, json.dumps({"ok": True, "id": rid}, ensure_ascii=False).encode("utf-8"))

            elif self.path.startswith("/api/topup"):
                user = validate_init_data(data.get("initData", ""))
                if not user:
                    self._reply(401, b'{"ok": false, "error": "auth"}')
                    return
                try:
                    n = int(data.get("stars") or 0)
                except Exception:
                    n = 0
                if n < TOPUP_MIN or n > TOPUP_MAX:
                    self._reply(200, b'{"ok": false, "error": "range"}')
                    return
                try:
                    link = bot.create_invoice_link(
                        provider_token="",
                        title=f"Пополнение {n} ⭐",
                        description=f"{n} звёзд для Mishka App",
                        payload=f"topup_{n}",
                        currency="XTR",
                        prices=[LabeledPrice(label=f"{n} ⭐", amount=n)],
                    )
                    print("topup OK:", n)
                    self._reply(200, json.dumps({"ok": True, "invoice": link}).encode("utf-8"))
                except Exception as e:
                    print("TOPUP FAILED:", repr(e))
                    traceback.print_exc()
                    self._reply(200, b'{"ok": false}')
            else:
                self._reply(404, b'{"ok": false}')
        except Exception as e:
            print("POST error:", e)
            traceback.print_exc()

    def log_message(self, *args):
        pass


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
load_requests()
threading.Thread(target=run_api, daemon=True).start()
print("API-сервер запущен")

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
    name = display_name(message.from_user)
    uid = message.from_user.id

    if payload.startswith("gift_") and uid != ADMIN_ID:
        try:
            parts = payload.split("_")
            stars = int(parts[2]) if len(parts) > 2 else 0
            req = {"type": "gift", "gift": "Подарок", "stars": stars, "uid": str(uid), "name": name}
            add_request(req)
            notify_admin_request(req)
            bot.send_message(message.chat.id, "✅ Заявка принята! Ожидай подарок 🎁")
        except Exception as e:
            print("gift_ error:", e)
    elif payload.startswith("wd_") and uid != ADMIN_ID:
        try:
            parts = payload.split("_")
            stars = int(parts[2]) if len(parts) > 2 else 0
            req = {"type": "stars", "n": stars, "uid": str(uid), "name": name}
            add_request(req)
            notify_admin_request(req)
            bot.send_message(message.chat.id, "✅ Заявка на вывод принята! 💸")
        except Exception as e:
            print("wd_ error:", e)
    elif payload.startswith("w_"):
        try:
            data = payload[2:].split("_")
            stars = int(data[1])
            gift_names = {15: "🧸 Мишка", 25: "🎁 Подарочек", 50: "🍾 Шампанское", 100: "💍 Колечко"}
            gift = gift_names.get(stars, f"подарок на {stars}⭐")
            req = {"type": "gift", "gift": gift, "stars": stars, "uid": str(uid), "name": name}
            add_request(req)
            notify_admin_request(req)
            bot.send_message(message.chat.id, "✅ Заявка принята! Ожидай подарок 🎁")
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
        bot.reply_to(message, "Привет! Играй в игру по кнопке ниже 👇\nДля пополнения нажми ⭐ в самой игре",
                     reply_markup=markup)


@bot.callback_query_handler(func=lambda call: call.data.startswith("gift_ok_") or call.data.startswith("gift_no_")
                            or call.data.startswith("wd_ok_") or call.data.startswith("wd_no_"))
def decision(call):
    """Уведомление получает ТОЛЬКО тот игрок, который подавал заявку."""
    if call.from_user.id != ADMIN_ID:
        bot.answer_callback_query(call.id, "Только для админa!")
        return
    try:
        parts = call.data.split("_")
        action, kind = parts[0], parts[1]
        user_id = int(parts[2])
        if kind == "ok":
            if action == "wd":
                bot.send_message(user_id, f"💸 Вывод {parts[3]} ⭐ отправлен! Проверь Telegram.")
                bot.edit_message_text(f"✅ Вывод {parts[3]} ⭐ выдан.", call.message.chat.id, call.message.message_id)
            else:
                bot.send_message(user_id, "🎁 Подарок отправлен! Проверь его в Telegram.")
                bot.edit_message_text("✅ Отмечено: подарок выдан.", call.message.chat.id, call.message.message_id)
        else:
            bot.send_message(user_id, "❌ К сожалению, твою заявку отклонили.")
            bot.edit_message_text("❌ Заявка отклонена.", call.message.chat.id, call.message.message_id)
    except Exception as new_e:
        print("decision error:", new_e)
        traceback.print_exc()
    bot.answer_callback_query(call.id)


@bot.pre_checkout_query_handler(func=lambda query: True)
def checkout(pre_checkout_query):
    bot.answer_pre_checkout_query(pre_checkout_query.id, ok=True)


@bot.message_handler(content_types=['successful_payment'])
def got_payment(message):
    payload = message.successful_payment.invoice_payload
    amount = message.successful_payment.total_amount
    name = display_name(message.from_user)

    if payload.startswith("topup"):
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("🎮 Забрать звёзды в игре",
                                        url=f"https://t.me/{BOT_USERNAME}/{APP_SHORT_NAME}?startapp=topup_{amount}"))
        bot.send_message(ADMIN_ID, f"💰 ПОПОЛНЕНИЕ! Игрок {esc(name)} купил {amount} звёзд.")
        bot.send_message(message.chat.id, "✅ Оплата прошла! Нажми кнопку — звёзды начислятся в игре:",
                         reply_markup=markup)
    elif payload.startswith("pay_"):
        item_id = payload.split('_')[1]
        item = SKIN_PRICES.get(item_id, {})
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("🎮 Активировать в игре",
                                        url=f"https://t.me/{BOT_USERNAME}/{APP_SHORT_NAME}?startapp=boost_{item_id}"))
        bot.send_message(ADMIN_ID, f"💰 ПОКУПКА! Игрок {esc(name)} купил {esc(item_id)} за {amount}⭐!")
        bot.send_message(message.chat.id,
                         f"✅ Оплата прошла: {item.get('name', item_id)}!\nНажми кнопку — буст активируется:",
                         reply_markup=markup)


@bot.message_handler(content_types=['web_app_data'])
def web_app_data(message):
    try:
        data = json.loads(message.web_app_data.data)
        name = display_name(message.from_user)
        uid = message.from_user.id
        if data.get('action') == 'withdraw_gift':
            req = {"type": "gift", "gift": data.get('gift', '?'), "stars": data.get('stars', 0),
                   "uid": str(uid), "name": name}
            add_request(req)
            notify_admin_request(req)
        elif data.get('action') == 'withdraw_stars':
            req = {"type": "stars", "n": data.get('stars', 0), "uid": str(uid), "name": name}
            add_request(req)
            notify_admin_request(req)
    except Exception as e:
        print("WebApp Error:", e)
        traceback.print_exc()


print("Бот запущен, жду сообщения...")
bot.infinity_polling(timeout=10, long_polling_timeout=5, skip_pending=True)
