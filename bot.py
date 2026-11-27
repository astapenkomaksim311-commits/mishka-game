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

TOPUP_MIN = 10
TOPUP_MAX = 200
DUEL_TIMEOUT = 45
MARKET_FEE = 0.05
SEASON_PRIZES = [50, 15, 10, 5, 5, 3, 3, 3, 3, 3]
CLAN_WAR_PRIZE = 200
LEVEL_GIFTS = {30: "tg15", 35: "tg15", 40: "tg15", 45: "tg15", 50: "tg100"}

bot = telebot.TeleBot(BOT_TOKEN)

PLAYERS_FILE = "/data/players.json"
REQUESTS_FILE = "/data/requests.json"
CLANS_FILE = "/data/clans.json"
MARKET_FILE = "/data/market.json"
SEASON_FILE = "/data/season.json"

PLAYERS = {}
REQUESTS = []
CLANS = {}
MARKET = []
SEASON = {"num": "", "paid": False}
QUEUE = []
DUELS = {}
RESULTS = {}
LOCK = threading.Lock()
ONLINE_SEC = 180


def load_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def save_json(path, obj):
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False)
    except Exception as e:
        print("save error:", path, e)


def load_all():
    global PLAYERS, REQUESTS, CLANS, MARKET, SEASON
    PLAYERS = load_json(PLAYERS_FILE, {})
    REQUESTS = load_json(REQUESTS_FILE, [])
    CLANS = load_json(CLANS_FILE, {})
    MARKET = load_json(MARKET_FILE, [])
    SEASON = load_json(SEASON_FILE, {"num": "", "paid": False})


def save_players():
    save_json(PLAYERS_FILE, PLAYERS)


def save_all():
    save_players()
    save_json(REQUESTS_FILE, REQUESTS)
    save_json(CLANS_FILE, CLANS)
    save_json(MARKET_FILE, MARKET)
    save_json(SEASON_FILE, SEASON)


def week_num():
    return time.strftime("%G-%V")


def crash_round(now=None):
    EPOCH, BET_MS, COOL_MS, GROWTH = 1767225600000, 10000, 2500, 0.2
    now = now or int(time.time() * 1000)

    def c_hash(n):
        h = n & 0xFFFFFFFF
        h = ((h ^ (h >> 16)) * 2246822519) & 0xFFFFFFFF
        h = ((h ^ (h >> 13)) * 3266489917) & 0xFFFFFFFF
        h = (h ^ (h >> 16)) & 0xFFFFFFFF
        return h / 4294967296.0

    def cp_of(i):
        r = c_hash((i * 2654435761) % 4294967296)
        if r < 0.45:
            return round(1.0 + (r / 0.45) * 0.6, 2)
        if r < 0.85:
            return round(1.6 + ((r - 0.45) / 0.4) * 1.4, 2)
        return round(3.0 + ((r - 0.85) / 0.15) * 2.0, 2)

    s, i = EPOCH, 0
    guard = now + 86400000
    while True:
        cp = cp_of(i)
        d = (int(__import__("math").log(cp) / GROWTH * 1000)) if cp > 1 else 0
        end = s + BET_MS + d + COOL_MS
        if end > now or s > guard:
            return i
        s = end
        i += 1


def player_level(p):
    return min(50, 1 + int(p.get("best", 0) or 0) // 300)


def ensure_season():
    """Смена недели: выплата призов сезона и война кланов, сброс очков у ВСЕХ."""
    global SEASON
    wk = week_num()
    with LOCK:
        if SEASON.get("num") == wk:
            return
        prev = SEASON.get("num", "")
        if prev:
            ranked = []
            for uid, p in PLAYERS.items():
                if p.get("seasonNum") == prev:
                    pts = int(p.get("seasonPts", 0) or 0)
                    if pts > 0:
                        ranked.append((uid, pts, p))
            ranked.sort(key=lambda x: x[1], reverse=True)
            if ranked:
                winner = ranked[0][2].get("name") or "игрок"
                for i, (uid, pts, p) in enumerate(ranked[:10]):
                    if i < len(SEASON_PRIZES):
                        p["sdelta"] = int(p.get("sdelta", 0) or 0) + SEASON_PRIZES[i]
                save_players()
                try:
                    bot.send_message(ADMIN_ID, f"🏆 Сезон {prev} завершён! Победитель: {winner}. Топ-10 получил звёзды.")
                except Exception:
                    pass
            # Война кланов за прошлую неделю
            if CLANS:
                powers = {}
                for name, cl in CLANS.items():
                    powers[name] = sum(int(PLAYERS[m].get("best", 0) or 0) for m in cl.get("members", []) if m in PLAYERS)
                if powers and max(powers.values()) > 0:
                    win_clan = max(powers, key=powers.get)
                    for m in CLANS[win_clan].get("members", []):
                        if m in PLAYERS:
                            PLAYERS[m]["delta"] = int(PLAYERS[m].get("delta", 0) or 0) + CLAN_WAR_PRIZE
                    save_players()
                    try:
                        bot.send_message(ADMIN_ID, f"⚔️ Война кланов: победил «{win_clan}»! Участникам +{CLAN_WAR_PRIZE} 🪙")
                    except Exception:
                        pass
        SEASON = {"num": wk, "paid": True}
        for p in PLAYERS.values():
            p["seasonNum"] = wk
            p["seasonStart"] = int(p.get("best", 0) or 0)
            p["seasonPts"] = 0
        save_json(SEASON_FILE, SEASON)


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


def add_request(req):
    if not isinstance(req, dict):
        return None
    req["time"] = req.get("time") or int(time.time() * 1000)
    req["id"] = req.get("id") or f"{req.get('uid')}_{req['time']}"
    with LOCK:
        if any(r.get("id") == req["id"] for r in REQUESTS):
            return req["id"]
        REQUESTS.append(req)
        save_json(REQUESTS_FILE, REQUESTS)
    return req["id"]


def remove_request(rid):
    with LOCK:
        REQUESTS[:] = [r for r in REQUESTS if r.get("id") != rid]
        save_json(REQUESTS_FILE, REQUESTS)


def merge_user(user, data):
    """Баланс = клиент + серверные начисления. Очки сезона = рекорд − старт недели."""
    uid = str(user.get("id", ""))
    if not uid:
        return None
    wk = week_num()
    with LOCK:
        old = PLAYERS.get(uid, {})
        delta = int(old.get("delta", 0) or 0)
        sdelta = int(old.get("sdelta", 0) or 0)
        grants = old.get("grants", [])
        skins = sorted(set(old.get("skins", []) or []) | set(data.get("skins", []) or []))
        if grants:
            for g in grants:
                if g.get("type") == "skin" and g.get("id") and g["id"] not in skins:
                    skins.append(g["id"])
            grants = []
        best_new = max(int(old.get("best", 0) or 0), int(data.get("best", 0) or 0))
        inv = list(data.get("gifts", []) or []) if isinstance(data.get("gifts"), list) else list(old.get("inv", []) or [])
        # Сезон: старт недели фиксируем на рекорде игрока на момент смены недели
        if old.get("seasonNum") == wk:
            season_start = int(old.get("seasonStart", 0) or 0)
            if season_start <= 0:
                season_start = best_new
                if old.get("best", 0):
                    season_start = int(old.get("best", 0) or 0)
        else:
            season_start = int(old.get("best", 0) or 0) if old else best_new
        pts = max(0, best_new - season_start)
        rec = {
            "id": uid,
            "username": (user.get("username") or "").lstrip("@"),
            "name": user.get("first_name") or "Игрок",
            "wallet": int(data.get("wallet", old.get("wallet", 0)) or 0) + delta,
            "stars": int(data.get("stars", old.get("stars", 0)) or 0) + sdelta,
            "best": best_new,
            "inv": inv,
            "skins": skins,
            "currentSkin": data.get("currentSkin") if data.get("currentSkin") in skins else old.get("currentSkin") or "bear",
            "boostUntil": max(int(old.get("boostUntil", 0) or 0), int(data.get("boostUntil", 0) or 0)),
            "passUntil": max(int(old.get("passUntil", 0) or 0), int(data.get("passUntil", 0) or 0)),
            "clan": old.get("clan"),
            "gifted": old.get("gifted", []) or [],
            "delta": 0, "sdelta": 0, "grants": [],
            "seasonNum": wk, "seasonStart": season_start, "seasonPts": pts,
            "ts": time.time(),
        }
        PLAYERS[uid] = rec
        save_players()
        out = dict(rec)
        return out


def grant_or_create(uid, kind, n):
    """Начисление звёзд/монет/буста, даже если игрок ещё ни разу не синхронизировался."""
    with LOCK:
        p = PLAYERS.get(uid)
        if not p:
            PLAYERS[uid] = {"id": uid, "username": "", "name": "Игрок",
                            "wallet": 0, "stars": 0, "best": 0, "inv": [], "skins": [],
                            "currentSkin": "bear", "boostUntil": 0, "passUntil": 0,
                            "clan": None, "gifted": [],
                            "delta": 0, "sdelta": 0, "grants": [],
                            "seasonNum": week_num(), "seasonStart": 0, "seasonPts": 0, "ts": 0}
            p = PLAYERS[uid]
        if kind == "stars":
            p["sdelta"] = int(p.get("sdelta", 0) or 0) + n
        elif kind == "coins":
            p["delta"] = int(p.get("delta", 0) or 0) + n
        elif kind == "skin":
            if n not in (p.get("skins") or []):
                p.setdefault("skins", []).append(n)
        elif kind == "boost":
            base = int(p.get("boostUntil", 0) or 0)
            p["boostUntil"] = max(base, int(time.time() * 1000)) + n * 86400000
        elif kind == "pass":
            base = int(p.get("passUntil", 0) or 0)
            p["passUntil"] = max(base, int(time.time() * 1000)) + 30 * 86400000
        save_players()
        return True


def notify_admin(text):
    try:
        bot.send_message(ADMIN_ID, text, parse_mode="HTML")
    except Exception:
        pass


def notify_admin_request(req):
    try:
        name = esc(req.get("name") or "игрок")
        uid = str(req.get("uid") or "?")
        uname = (req.get("username") or "").strip()
        markup = InlineKeyboardMarkup()
        if uname:
            markup.add(InlineKeyboardButton(f"💬 Написать @{uname}", url=f"https://t.me/{uname}"))
        if req.get("type") == "stars":
            n = req.get("n", 0)
            markup.add(
                InlineKeyboardButton("✅ Отправил", callback_data=f"wd_ok_{uid}_{n}"),
                InlineKeyboardButton("❌ Отклонить", callback_data=f"wd_no_{uid}_{n}"))
            bot.send_message(ADMIN_ID,
                             f"💸💸💸 ВЫВОД ЗВЁЗД!\n\nИгрок: {name}\nID: <code>{uid}</code>\nСумма: {n} ⭐\n\n"
                             f"👉 Переведи игроку {n} звёзд и нажми «Отправил».",
                             parse_mode="HTML", reply_markup=markup)
        else:
            gift = esc(req.get("gift", "?"))
            stars = req.get("stars", 0)
            markup.add(
                InlineKeyboardButton("✅ Отправил", callback_data=f"gft_ok_{uid}"),
                InlineKeyboardButton("❌ Отклонить", callback_data=f"gft_no_{uid}"))
            bot.send_message(ADMIN_ID,
                             f"🔔🔔🔔 ЗАЯВКА НА ВЫВОД ПОДАРКА!\n\nИгрок: {name}\nID: <code>{uid}</code>\nПодарок: {gift} ({stars} ⭐)\n\n"
                             f"👉 Отправь подарок игроку в Telegram и нажми «Отправил».",
                             parse_mode="HTML", reply_markup=markup)
    except Exception as e:
        print("notify_admin_request error:", e)


@bot.message_handler(commands=['data'])
def cmd_data(message):
    if message.from_user.id != ADMIN_ID:
        return
    now = time.time()
    online = sum(1 for p in PLAYERS.values() if now - float(p.get("ts", 0) or 0) < ONLINE_SEC)
    named = sum(1 for p in PLAYERS.values() if p.get("username"))
    txt = (f"📊 <b>Данные сервера</b>\n\n"
           f"Игроков всего: <b>{len(PLAYERS)}</b>\n"
           f"С юзернеймом: <b>{named}</b>\n"
           f"Онлайн (посл. {ONLINE_SEC // 60} мин): <b>{online}</b>\n"
           f"Заявок на вывод: <b>{len(REQUESTS)}</b>\n"
           f"Лотов на обмене: <b>{len(MARKET)}</b>\n"
           f"Кланов: <b>{len(CLANS)}</b>\n"
           f"Сезон: <b>{SEASON.get('num', '—')}</b>")
    bot.send_message(message.chat.id, txt, parse_mode="HTML")


@bot.message_handler(content_types=['successful_payment'])
def got_payment(message):
    payload = message.successful_payment.invoice_payload
    amount = message.successful_payment.total_amount
    uid = str(message.from_user.id)
    name = display_name(message.from_user)

    if payload.startswith("pay_"):
        item_id = payload.split('_', 1)[1]
        if item_id.startswith("boost"):
            days = {"boost1": 1, "boost2": 2, "boost3": 5}.get(item_id, 1)
            grant_or_create(uid, "boost", days)
            text = "✅ Оплата прошла: буст x3!\nОткрой игру — буст активируется автоматически:"
        elif item_id == "pass":
            grant_or_create(uid, "pass", 1)
            text = "✅ Оплата прошла: Пропуск активирован!\nОткрой игру — он включится автоматически:"
        else:
            text = "✅ Оплата прошла!\nОткрой игру:"
        notify_admin(f"💰 ПОКУПКА! Игрок {esc(name)} купил {esc(item_id)}.")
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("🎮 Открыть игру",
                                        url=f"https://t.me/{BOT_USERNAME}/{APP_SHORT_NAME}?startapp=menu"))
        bot.send_message(message.chat.id, text, reply_markup=markup)
        return

    grant_or_create(uid, "stars", amount)
    notify_admin(f"💰 ПОПОЛНЕНИЕ! Игрок {esc(name)} купил {amount} звёзд — начислено на сервере.")
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("🎮 Открыть игру",
                                    url=f"https://t.me/{BOT_USERNAME}/{APP_SHORT_NAME}?startapp=menu"))
    bot.send_message(message.chat.id,
                     f"✅ Оплата прошла! {amount} ⭐ уже зачислены.\n"
                     "Открой игру — звёзды будут на месте (перезайди, если она уже открыта):",
                     reply_markup=markup)


@bot.callback_query_handler(func=lambda c: c.data.startswith(("wd_ok_", "wd_no_", "gft_ok_", "gft_no_")))
def cb_requests(c):
    try:
        d = c.data
        if d.startswith("wd_ok_") or d.startswith("wd_no_"):
            parts = d.split("_")
            uid, n = parts[2], int(parts[3])
            rid = None
            with LOCK:
                for r in REQUESTS:
                    if r.get("uid") == uid and r.get("type") == "stars" and int(r.get("n", 0)) == n:
                        rid = r["id"]
                        break
            if d.startswith("wd_ok_"):
                if rid:
                    remove_request(rid)
                try:
                    bot.send_message(int(uid), f"✅ Админ перевёл тебе {n} ⭐! Проверь баланс Telegram.")
                except Exception:
                    pass
                try:
                    bot.edit_message_text("✅ Отмечено: звёзды переведены.", c.message.chat.id, c.message.message_id)
                except Exception:
                    pass
            else:
                if rid:
                    remove_request(rid)
                try:
                    bot.send_message(int(uid), "❌ Твоя заявка на вывод отклонена админом.")
                except Exception:
                    pass
                try:
                    bot.edit_message_text("❌ Заявка отклонена.", c.message.chat.id, c.message.message_id)
                except Exception:
                    pass
        else:
            parts = d.split("_")
            uid = parts[2]
            with LOCK:
                rids = [r["id"] for r in REQUESTS if r.get("uid") == uid and r.get("type") != "stars"]
            for rid in rids:
                remove_request(rid)
            if d.startswith("gft_ok_"):
                try:
                    bot.send_message(int(uid), "✅ Подарок отправлен! Проверь свои подарки в Telegram.")
                except Exception:
                    pass
                try:
                    bot.edit_message_text("✅ Отмечено: подарок выдан.", c.message.chat.id, c.message.message_id)
                except Exception:
                    pass
            else:
                try:
                    bot.send_message(int(uid), "❌ Твоя заявка на вывод отклонена админом.")
                except Exception:
                    pass
                try:
                    bot.edit_message_text("❌ Заявка отклонена.", c.message.chat.id, c.message.message_id)
                except Exception:
                    pass
        bot.answer_callback_query(c.id)
    except Exception as e:
        print("callback error:", e)
        try:
            bot.answer_callback_query(c.id)
        except Exception:
            pass
def grant_to(uid, kind, n, note=""):
    """Начисление между заходами: монеты/звёзды/скин/подарок."""
    with LOCK:
        p = PLAYERS.get(uid)
        if not p:
            return False
        if kind == "coins":
            p["delta"] = int(p.get("delta", 0) or 0) + n
        elif kind == "stars":
            p["sdelta"] = int(p.get("sdelta", 0) or 0) + n
        elif kind == "skin":
            if n not in (p.get("skins") or []):
                p.setdefault("skins", []).append(n)
        elif kind == "gift":
            if n not in (p.get("inv") or []):
                p.setdefault("inv", []).append(n)
        save_players()
        return True


def duel_join(uid, stake):
    with LOCK:
        if any(q["uid"] == uid for q in QUEUE):
            return {"ok": True}
        for q in list(QUEUE):
            if q["stake"] == stake and q["uid"] != uid:
                QUEUE.remove(q)
                pa = PLAYERS.get(q["uid"])
                pb = PLAYERS.get(uid)
                if not pa or not pb:
                    QUEUE.append(q)
                    return {"ok": True}
                pa["sdelta"] = int(pa.get("sdelta", 0) or 0) - stake
                pb["sdelta"] = int(pb.get("sdelta", 0) or 0) - stake
                save_players()
                rnd = crash_round()
                DUELS[q["uid"]] = {"stake": stake, "mate": uid, "created": time.time(), "round": rnd}
                DUELS[uid] = {"stake": stake, "mate": q["uid"], "created": time.time(), "round": rnd}
                notify_admin(f"⚔️ ДУЭЛЬ! {pa.get('name')} vs {pb.get('name')} на {stake} ⭐ (раунд #{rnd})")
                return {"ok": True}
        QUEUE.append({"uid": uid, "stake": stake, "created": time.time()})
        return {"ok": True}


def duel_status(uid):
    now = time.time()
    with LOCK:
        res = RESULTS.pop(uid, None)
        d = DUELS.get(uid)
        if d and now - d["created"] > DUEL_TIMEOUT:
            mate = d["mate"]

            def roll(x):
                h = hmac.new(str(x).encode(), str(d["created"]).encode(), hashlib.sha256).hexdigest()
                return int(h[:8], 16)

            r1, r2 = roll(uid), roll(mate)
            if r1 == r2:
                RESULTS[uid] = {"win": None, "payout": d["stake"]}
                if mate in DUELS:
                    RESULTS[mate] = {"win": None, "payout": d["stake"]}
                    grant_to(mate, "stars", d["stake"])
                grant_to(uid, "stars", d["stake"])
            else:
                winner = uid if r1 > r2 else mate
                loser = mate if r1 > r2 else uid
                payout = d["stake"] * 2
                grant_to(winner, "stars", payout)
                RESULTS[winner] = {"win": True, "payout": payout}
                RESULTS[loser] = {"win": False, "payout": 0}
                notify_admin(f"⚔️ Дуэль завершена: победил {PLAYERS.get(winner, {}).get('name')} (+{payout} ⭐)")
            DUELS.pop(uid, None)
            DUELS.pop(mate, None)
            save_players()
            d = None
            res = RESULTS.pop(uid, None)
        if d:
            return {"ok": True, "duel": {"stake": d["stake"]}, "result": None}
        if res:
            return {"ok": True, "duel": None, "result": res}
        return {"ok": True, "duel": None, "result": None}


def duel_cancel(uid):
    with LOCK:
        DUELS.pop(uid, None)
        QUEUE[:] = [q for q in QUEUE if q["uid"] != uid]


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
                ensure_season()
                now = time.time()
                with LOCK:
                    players = [dict(p) for p in PLAYERS.values()]
                online = sum(1 for p in players if now - p.get("ts", 0) < ONLINE_SEC)
                named = [p for p in players if p.get("username")]
                named.sort(key=lambda p: p.get("best", 0), reverse=True)
                top = [{"id": p["id"], "name": "@" + p["username"], "best": p.get("best", 0),
                        "wallet": p.get("wallet", 0),
                        "online": (now - p.get("ts", 0)) < ONLINE_SEC} for p in named[:20]]
                self._reply(200, json.dumps({"ok": True, "online": online, "total": len(players),
                                             "top": top}, ensure_ascii=False).encode("utf-8"))
            elif self.path.startswith("/api/season"):
                ensure_season()
                with LOCK:
                    ranked = sorted([(uid, p) for uid, p in PLAYERS.items()
                                     if p.get("username") and p.get("seasonNum") == week_num()],
                                    key=lambda kv: int(kv[1].get("seasonPts", 0) or 0), reverse=True)[:20]
                    top = [{"id": uid, "name": "@" + p["username"],
                            "pts": int(p.get("seasonPts", 0) or 0)}
                           for uid, p in ranked if int(p.get("seasonPts", 0) or 0) > 0]
                secs_left = 7 * 86400 - (time.gmtime().tm_wday * 86400 + time.gmtime().tm_hour * 3600 +
                                         time.gmtime().tm_min * 60 + time.gmtime().tm_sec)
                secs_left = max(0, secs_left)
                days = secs_left // 86400
                hours = (secs_left % 86400) // 3600
                self._reply(200, json.dumps({"ok": True, "num": week_num(), "top": top,
                                             "endsIn": f"{days}д {hours}ч"}, ensure_ascii=False).encode("utf-8"))
            elif self.path.startswith("/api/clans"):
                ensure_season()
                with LOCK:
                    players = dict(PLAYERS)
                lst = []
                for name, cl in CLANS.items():
                    members = [m for m in cl.get("members", []) if m in players]
                    power = sum(int(players[m].get("best", 0) or 0) for m in members)
                    lst.append({"name": name, "members": len(members), "power": power})
                lst.sort(key=lambda x: x["power"], reverse=True)
                self._reply(200, json.dumps({"ok": True, "clans": lst[:20]}, ensure_ascii=False).encode("utf-8"))
            elif self.path.startswith("/api/market"):
                with LOCK:
                    lst = list(MARKET)
                self._reply(200, json.dumps({"ok": True, "list": lst[-40:]}, ensure_ascii=False).encode("utf-8"))
            elif self.path.startswith("/api/requests"):
                with LOCK:
                    lst = list(REQUESTS)
                self._reply(200, json.dumps({"ok": True, "list": lst}, ensure_ascii=False).encode("utf-8"))
            else:
                self._reply(404, b'{"ok": false}')
        except Exception as e:
            print("GET error:", e)
            self._reply(500, b'{"ok": false}')

    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length", 0) or 0)
            raw = self.rfile.read(length) if length else b"{}"
            try:
                data = json.loads(raw)
            except Exception:
                data = {}

            if self.path.startswith("/api/requests/done"):
                remove_request(data.get("id"))
                self._reply(200, b'{"ok": true}')

            elif self.path.startswith("/api/sync"):
                user = validate_init_data(data.get("initData", ""))
                if not user:
                    self._reply(401, b'{"ok": false, "error": "auth"}')
                    return
                uid = str(user.get("id", ""))
                uname = (user.get("username") or "").lstrip("@")
                if uname:
                    with LOCK:
                        p = PLAYERS.get(uid)
                        if p and p.get("username") != uname:
                            p["username"] = uname
                            save_players()
                        changed = False
                        for r in REQUESTS:
                            if r.get("uid") == uid and r.get("username") != uname:
                                r["username"] = uname
                                changed = True
                        if changed:
                            save_json(REQUESTS_FILE, REQUESTS)
                for r in (data.get("requests") or []):
                    if isinstance(r, dict) and str(r.get("uid") or "") == uid and r.get("id"):
                        add_request(r)
                rec = merge_user(user, data)
                if not rec:
                    self._reply(400, b'{"ok": false, "error": "bad user"}')
                    return
                lvl = player_level(rec)
                now = time.time()
                with LOCK:
                    online = sum(1 for p in PLAYERS.values()
                                 if now - float(p.get("ts", 0) or 0) < ONLINE_SEC)
                payload = {"ok": True,
                           "you": {"id": rec["id"], "name": rec["name"], "wallet": rec["wallet"],
                                   "stars": rec["stars"], "best": rec["best"], "inv": rec.get("inv", []),
                                   "skins": rec.get("skins", []), "currentSkin": rec.get("currentSkin"),
                                   "boostUntil": rec.get("boostUntil", 0), "level": lvl,
                                   "seasonPts": rec.get("seasonPts", 0)},
                           "clanName": rec.get("clan"),
                           "grant": [],
                           "online": online, "total": len(PLAYERS),
                           "week": SEASON.get("num", "")}
                self._reply(200, json.dumps(payload, ensure_ascii=False).encode("utf-8"))

            elif self.path.startswith("/api/request"):
                user = validate_init_data(data.get("initData", ""))
                if not user:
                    self._reply(401, b'{"ok": false, "error": "auth"}')
                    return
                req = data.get("req") or {}
                req["uid"] = str(user.get("id", "")) or str(req.get("uid", ""))
                req["username"] = (user.get("username") or "").lstrip("@")
                req["name"] = display_name(user)
                rid = add_request(req)
                if rid:
                    notify_admin_request(req)
                self._reply(200, json.dumps({"ok": True, "id": rid}, ensure_ascii=False).encode("utf-8"))

            elif self.path.startswith("/api/clan"):
                user = validate_init_data(data.get("initData", ""))
                if not user:
                    self._reply(401, b'{"ok": false, "error": "auth"}')
                    return
                uid = str(user.get("id", ""))
                action = data.get("action", "")
                name = str(data.get("name", "")).strip()[:16]
                ensure_season()
                with LOCK:
                    me = PLAYERS.get(uid)
                    if not me:
                        self._reply(200, b'{"ok": false, "error": "nouser"}')
                        return
                    if action == "create":
                        if len(name) < 3 or name in CLANS:
                            self._reply(200, b'{"ok": false, "error": "name"}')
                            return
                        if me.get("clan"):
                            old_cl = CLANS.get(me["clan"])
                            if old_cl and uid in old_cl.get("members", []):
                                old_cl["members"].remove(uid)
                                if not old_cl["members"]:
                                    CLANS.pop(me["clan"], None)
                        CLANS[name] = {"owner": uid, "members": [uid], "created": time.time()}
                        me["clan"] = name
                        save_players()
                        save_json(CLANS_FILE, CLANS)
                        self._reply(200, json.dumps({"ok": True, "clanName": name}).encode("utf-8"))
                        return
                    if action == "join":
                        if name not in CLANS:
                            self._reply(200, b'{"ok": false, "error": "noclan"}')
                            return
                        if len(CLANS[name].get("members", [])) >= 50:
                            self._reply(200, b'{"ok": false, "error": "full"}')
                            return
                        if me.get("clan") and me["clan"] in CLANS and uid in CLANS[me["clan"]].get("members", []):
                            CLANS[me["clan"]]["members"].remove(uid)
                        if uid not in CLANS[name]["members"]:
                            CLANS[name]["members"].append(uid)
                        me["clan"] = name
                        save_players()
                        save_json(CLANS_FILE, CLANS)
                        self._reply(200, json.dumps({"ok": True, "clanName": name}).encode("utf-8"))
                        return
                    if action == "leave":
                        if me.get("clan") and me["clan"] in CLANS:
                            cl = CLANS[me["clan"]]
                            if uid in cl.get("members", []):
                                cl["members"].remove(uid)
                            if not cl.get("members"):
                                CLANS.pop(me["clan"], None)
                                save_json(CLANS_FILE, CLANS)
                        me["clan"] = None
                        save_players()
                        self._reply(200, b'{"ok": true}')
                        return
                self._reply(200, b'{"ok": false}')

            elif self.path.startswith("/api/duel"):
                user = validate_init_data(data.get("initData", ""))
                if not user:
                    self._reply(401, b'{"ok": false, "error": "auth"}')
                    return
                uid = str(user.get("id", ""))
                action = data.get("action", "")
                if action == "join":
                    ensure_season()
                    stake = int(data.get("stake") or 0)
                    if stake not in (10, 25, 50):
                        self._reply(200, b'{"ok": false, "error": "stake"}')
                        return
                    with LOCK:
                        me = PLAYERS.get(uid)
                        if not me or (me.get("stars", 0) + me.get("sdelta", 0)) < stake:
                            self._reply(200, b'{"ok": false, "error": "stars"}')
                            return
                    out = duel_join(uid, stake)
                    self._reply(200, json.dumps(out).encode("utf-8"))
                    return
                if action == "cancel":
                    duel_cancel(uid)
                    self._reply(200, b'{"ok": true}')
                    return
                self._reply(200, json.dumps(duel_status(uid)).encode("utf-8"))

            elif self.path.startswith("/api/market"):
                user = validate_init_data(data.get("initData", ""))
                if not user:
                    self._reply(401, b'{"ok": false, "error": "auth"}')
                    return
                uid = str(user.get("id", ""))
                action = data.get("action", "")
                with LOCK:
                    me = PLAYERS.get(uid)
                    if not me:
                        self._reply(200, b'{"ok": false, "error": "nouser"}')
                        return
                    if action == "add":
                        sid = str(data.get("sid") or "")[:24]
                        price = int(data.get("price") or 0)
                        if not sid or price < 100:
                            self._reply(200, b'{"ok": false, "error": "bad"}')
                            return
                        if sid not in (me.get("skins") or []):
                            self._reply(200, b'{"ok": false, "error": "noskin"}')
                            return
                        me["skins"] = [s for s in me["skins"] if s != sid]
                        save_players()
                        MARKET.append({"id": f"{uid}_{int(time.time()*1000)}", "seller": uid,
                                       "sellerName": display_name(me), "sid": sid, "price": price,
                                       "created": int(time.time()*1000)})
                        save_json(MARKET_FILE, MARKET)
                        self._reply(200, b'{"ok": true}')
                        return
                    if action == "buy":
                        lot_id = str(data.get("lot") or data.get("id") or "")
                        lot = next((m for m in MARKET if m.get("id") == lot_id), None)
                        if not lot:
                            self._reply(200, b'{"ok": false, "error": "nolot"}')
                            return
                        price = int(lot.get("price", 0) or 0)
                        if int(me.get("wallet", 0) or 0) < price:
                            self._reply(200, b'{"ok": false, "error": "wallet"}')
                            return
                        me["wallet"] = int(me["wallet"]) - price
                        seller = PLAYERS.get(lot.get("seller"))
                        if seller:
                            seller["delta"] = int(seller.get("delta", 0) or 0) + int(price * (1 - MARKET_FEE))
                        sid = lot.get("sid")
                        if sid and sid not in (me.get("skins") or []):
                            me.setdefault("skins", []).append(sid)
                        MARKET[:] = [m for m in MARKET if m.get("id") != lot_id]
                        save_players()
                        save_json(MARKET_FILE, MARKET)
                        self._reply(200, b'{"ok": true}')
                        return
                self._reply(200, b'{"ok": false}')

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
                    self._reply(200, json.dumps({"ok": True, "invoice": link}).encode("utf-8"))
                except Exception as e:
                    print("topup error:", e)
                    self._reply(200, b'{"ok": false}')

            elif self.path.startswith("/api/giftcoins"):
                user = validate_init_data(data.get("initData", ""))
                if not user:
                    self._reply(401, b'{"ok": false, "error": "auth"}')
                    return
                to = str(data.get("to") or "")
                try:
                    n = int(data.get("n") or 0)
                except Exception:
                    n = 0
                if n < 10 or not to:
                    self._reply(200, b'{"ok": false, "error": "bad"}')
                    return
                with LOCK:
                    if to not in PLAYERS:
                        self._reply(200, b'{"ok": false, "error": "nouser"}')
                        return
                grant_to(to, "coins", n)
                notify_admin(f"🪙 Подарок монет: {display_name(user)} → {PLAYERS.get(to, {}).get('name')}: {n} 🪙")
                self._reply(200, b'{"ok": true}')

            else:
                self._reply(404, b'{"ok": false}')
        except Exception as e:
            print("POST error:", e)
            traceback.print_exc()
            try:
                self._reply(500, b'{"ok": false}')
            except Exception:
                pass

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
@bot.message_handler(commands=['start'])
def cmd_start(message):
    ensure_season()
    uid = str(message.from_user.id)
    uname = (message.from_user.username or "").lstrip("@")
    with LOCK:
        p = PLAYERS.get(uid)
        if p is not None and uname and p.get("username") != uname:
            p["username"] = uname
            save_players()
        changed = False
        for r in REQUESTS:
            if r.get("uid") == uid and uname and r.get("username") != uname:
                r["username"] = uname
                changed = True
        if changed:
            save_json(REQUESTS_FILE, REQUESTS)
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("🎮 Открыть игру",
                                    url=f"https://t.me/{BOT_USERNAME}/{APP_SHORT_NAME}"))
    bot.send_message(message.chat.id,
                     "Привет! Играй в игру по кнопке ниже 👇\nДля пополнения нажми ⭐ в самой игре",
                     reply_markup=markup)


def run_bot():
    bot.infinity_polling(timeout=25, long_polling_timeout=25)


if __name__ == "__main__":
    load_all()
    ensure_season()
    threading.Thread(target=run_api, daemon=True).start()
    run_bot()
