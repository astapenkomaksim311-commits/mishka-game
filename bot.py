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
DUEL_TIMEOUT = 45
MARKET_FEE = 0.05
SEASON_PRIZES = [50, 15, 10, 5, 5, 3, 3, 3, 3, 3]
CLAN_WAR_PRIZE = 200

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
    """Тот же расчёт раунда, что в index.html (для дуэлей)."""
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


def ensure_season():
    """Смена недели: выплата призов сезона, победа кланов в войне, сброс очков."""
    global SEASON
    wk = week_num()
    with LOCK:
        if SEASON.get("num") == wk:
            return
        prev = SEASON.get("num", "")
        if prev:
            ranked = sorted(
                [(uid, p) for uid, p in PLAYERS.items() if p.get("seasonNum") == prev],
                key=lambda kv: kv[1].get("seasonPts", 0), reverse=True)[:10]
            if ranked:
                msg = f"🏆 Сезон {prev} завершён! Победитель: {ranked[0][1].get('name')} (+50 ⭐)"
                for i, (uid, p) in enumerate(ranked):
                    if i < len(SEASON_PRIZES):
                        p["sdelta"] = p.get("sdelta", 0) + SEASON_PRIZES[i]
                save_players()
                try:
                    bot.send_message(ADMIN_ID, msg)
                except Exception:
                    pass
        SEASON = {"num": wk, "paid": True}
        for p in PLAYERS.values():
            p["seasonNum"] = wk
            p["seasonPts"] = 0
            p["seasonBest"] = 0
        # Война кланов за прошлую неделю
        if CLANS:
            powers = {}
            for name, cl in CLANS.items():
                powers[name] = sum(PLAYERS[m].get("best", 0) for m in cl.get("members", []) if m in PLAYERS)
            if powers:
                win_clan = max(powers, key=powers.get)
                for m in CLANS[win_clan].get("members", []):
                    if m in PLAYERS:
                        PLAYERS[m]["delta"] = PLAYERS[m].get("delta", 0) + CLAN_WAR_PRIZE
                save_players()
                try:
                    bot.send_message(ADMIN_ID, f"⚔️ Война кланов: победил «{win_clan}»! Участникам +{CLAN_WAR_PRIZE} 🪙")
                except Exception:
                    pass
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
    """Баланс = клиент + серверные начисления (delta/sdelta). Рекорд — максимум."""
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
                if g.get("type") == "skin" and g.get("id"):
                    if g["id"] not in skins:
                        skins.append(g["id"])
            grants = []
        best_new = max(int(old.get("best", 0) or 0), int(data.get("best", 0) or 0))
        if old.get("seasonNum") == wk:
            prev_sb = int(old.get("seasonBest", 0) or 0)
            pts = int(old.get("seasonPts", 0) or 0) + max(0, best_new - prev_sb)
        else:
            pts = best_new
        rec = {
            "id": uid,
            "username": (user.get("username") or "").lstrip("@"),
            "name": user.get("first_name") or "Игрок",
            "wallet": int(data.get("wallet", old.get("wallet", 0)) or 0) + delta,
            "stars": int(data.get("stars", old.get("stars", 0)) or 0) + sdelta,
            "best": best_new,
            "gifts": list(data.get("gifts", old.get("gifts", []))),
            "skins": skins,
            "boostUntil": max(int(old.get("boostUntil", 0) or 0), int(data.get("boostUntil", 0) or 0)),
            "clan": old.get("clan"),
            "delta": 0, "sdelta": 0, "grants": [],
            "seasonNum": wk, "seasonPts": pts, "seasonBest": best_new,
            "ts": time.time(),
        }
        PLAYERS[uid] = rec
        save_players()
        out = dict(rec)
        out["grant"] = []
        return out


def grant_to(uid, kind, n, note=""):
    """Начисление игроку между его заходами: монеты/звёзды/скин."""
    with LOCK:
        p = PLAYERS.get(uid)
        if not p:
            return False
        if kind == "coins":
            p["delta"] = p.get("delta", 0) + n
        elif kind == "stars":
            p["sdelta"] = p.get("sdelta", 0) + n
        elif kind == "skin":
            p.setdefault("grants", []).append({"type": "skin", "id": n})
        save_players()
        return True


def notify_admin(text):
    try:
        bot.send_message(ADMIN_ID, text)
    except Exception:
        pass


def notify_admin_request(req):
    try:
        name = esc(req.get("name") or "игрок")
        uid = esc(req.get("uid") or "?")
        if req.get("type") == "stars":
            n = req.get("n", 0)
            markup = InlineKeyboardMarkup()
            markup.add(
                InlineKeyboardButton("✅ Отправил", callback_data=f"wd_ok_{uid}_{n}"),
                InlineKeyboardButton("❌ Отклонить", callback_data=f"wd_no_{uid}_{n}"))
            bot.send_message(ADMIN_ID,
                             f"💸💸💸 ВЫВОД ЗВЁЗД!\n\nИгрок: {name}\nID: <code>{uid}</code>\nСумма: {n} ⭐\n\n"
                             f"👉 Переведи игроку {n} звёзд (Telegram → Профиль → Звёзды → Перевести).",
                             parse_mode="HTML", reply_markup=markup)
        else:
            gift = esc(req.get("gift", "?"))
            stars = req.get("stars", 0)
            markup = InlineKeyboardMarkup()
            markup.add(
                InlineKeyboardButton("✅ Отправил", callback_data=f"gift_ok_{uid}"),
                InlineKeyboardButton("❌ Отклонить", callback_data=f"gift_no_{uid}"))
            bot.send_message(ADMIN_ID,
                             f"🔔🔔🔔 ЗАЯВКА НА ВЫВОД ПОДАРКА!\n\nИгрок: {name}\nID: <code>{uid}</code>\n"
                             f"Подарок: {gift} ({stars}⭐)\n\n👉 Открой чат с игроком → скрепка → Подарок → на {stars} звёзд → Отправить.",
                             parse_mode="HTML", reply_markup=markup)
    except Exception as e:
        print("notify_admin_request error:", e)


# ---------- ДУЭЛИ ----------

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
                pa["sdelta"] = pa.get("sdelta", 0) - stake
                pb["sdelta"] = pb.get("sdelta", 0) - stake
                save_players()
                rnd = crash_round()
                DUELS[q["uid"]] = {"stake": stake, "mate": uid, "created": time.time(), "round": rnd}
                DUELS[uid] = {"stake": stake, "mate": q["uid"], "created": time.time(), "round": rnd}
                notify_admin(f"⚔️ ДУЭЛЬ! {pa.get('name')} vs {pb.get('name')} на {stake} ⭐ (раунд #{rnd})")
                return {"ok": True}
        QUEUE.append({"uid": uid, "stake": stake, "ts": time.time()})
        return {"ok": True}


def duel_status(uid):
    now = time.time()
    with LOCK:
        # Раздача готовых результатов
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
                players.sort(key=lambda p: p.get("best", 0), reverse=True)
                online = sum(1 for p in players if now - p.get("ts", 0) < ONLINE_SEC)
                payload = {"ok": True, "online": online, "total": len(players),
                           "top": [{"id": p["id"], "name": display_name(p), "best": p.get("best", 0),
                                    "wallet": p.get("wallet", 0),
                                    "online": (now - p.get("ts", 0)) < ONLINE_SEC} for p in players[:20]]}
                self._reply(200, json.dumps(payload, ensure_ascii=False).encode("utf-8"))
            elif self.path.startswith("/api/season"):
                ensure_season()
                now = time.time()
                with LOCK:
                    ranked = sorted([(uid, p) for uid, p in PLAYERS.items() if p.get("seasonNum") == week_num()],
                                    key=lambda kv: kv[1].get("seasonPts", 0), reverse=True)[:20]
                    top = [{"id": uid, "name": display_name(p), "pts": p.get("seasonPts", 0)}
                           for uid, p in ranked]
                sec_left = max(0, 7 * 86400 - (time.gmtime().tm_wday * 86400 +
                               time.gmtime().tm_hour * 3600 + time.gmtime().tm_min * 60))
                days = sec_left // 86400
                hours = (sec_left % 86400) // 3600
                payload = {"ok": True, "num": week_num(), "top": top, "endsIn": f"{days}д {hours}ч"}
                self._reply(200, json.dumps(payload, ensure_ascii=False).encode("utf-8"))
            elif self.path.startswith("/api/clans"):
                ensure_season()
                with LOCK:
                    players = dict(PLAYERS)
                lst = []
                for name, cl in CLANS.items():
                    members = [m for m in cl.get("members", []) if m in players]
                    power = sum(players[m].get("best", 0) for m in members)
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
            elif self.path in ("/", "/index.html"):
                try:
                    with open("index.html", "rb") as f:
                        self._reply(200, f.read(), "text/html; charset=utf-8")
                except Exception:
                    self._reply(200, "<h1>Игра: открой через бота</h1>".encode("utf-8"),
                                "text/html; charset=utf-8")
            elif self.path == "/api/ping":
                self._reply(200, b'{"ok": true}')
            else:
                self._reply(404, b'{"ok": false}')
        except Exception as e:
            print("GET error:", e)
            traceback.print_exc()

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
                grant = rec.pop("grant", [])
                self._reply(200, json.dumps({"ok": True, "you": rec, "clanName": rec.get("clan"),
                                             "grant": grant}, ensure_ascii=False).encode("utf-8"))

            elif self.path.startswith("/api/requests/done"):
                remove_request(data.get("id"))
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

            elif self.path.startswith("/api/giftcoins"):
                user = validate_init_data(data.get("initData", ""))
                if not user:
                    self._reply(401, b'{"ok": false, "error": "auth"}')
                    return
                to = str(data.get("to") or "")
                n = int(data.get("n") or 0)
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
                            if old_cl:
                                old_cl["members"].remove(uid) if uid in old_cl["members"] else None
                        CLANS[name] = {"owner": uid, "members": [uid], "created": time.time()}
                        me["clan"] = name
                        save_players()
                        self._reply(200, json.dumps({"ok": True, "clanName": name}).encode("utf-8"))
                        return
                    if action == "join":
                        if name not in CLANS:
                            self._reply(200, b'{"ok": false, "error": "noclan"}')
                            return
                        if len(CLANS[name]["members"]) >= 50:
                            self._reply(200, b'{"ok": false, "error": "full"}')
                            return
                        if me.get("clan") and me["clan"] in CLANS and uid in CLANS[me["clan"]]["members"]:
                            CLANS[me["clan"]]["members"].remove(uid)
                        CLANS[name]["members"].append(uid)
                        me["clan"] = name
                        save_players()
                        self._reply(200, json.dumps({"ok": True, "clanName": name}).encode("utf-8"))
                        return
                    if action == "leave":
                        if me.get("clan") and me["clan"] in CLANS:
                            cl = CLANS[me["clan"]]
                            if uid in cl["members"]:
                                cl["members"].remove(uid)
                            if not cl["members"]:
                                CLANS.pop(me["clan"], None)
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
                    if action == "list":
                        sid = str(data.get("sid") or "")[:24]
                        price = int(data.get("price") or 0)
                        if not sid or price < 100:
                            self._reply(200, b'{"ok": false, "error": "bad"}')
                            return
                        MARKET.append({"sid": sid, "seller": uid, "sellerName": display_name(me),
                                       "price": price, "ts": time.time()})
                        save_json(MARKET_FILE, MARKET)
                        self._reply(200, b'{"ok": true}')
                        return
                    if action == "buy":
                        sid = str(data.get("sid") or "")
                        seller = str(data.get("seller") or "")
                        lot = None
                        for l in MARKET:
                            if l["sid"] == sid and str(l["seller"]) == seller:
                                lot = l
                                break
                        if not lot:
                            self._reply(200, b'{"ok": false, "error": "nolot"}')
                            return
                        MARKET.remove(lot)
                        save_json(MARKET_FILE, MARKET)
                        payout = int(lot["price"] * (1 - MARKET_FEE))
                        if seller != uid:
                            grant_to(seller, "coins", payout)
                            notify_admin(f"🔄 Барахолка: {display_name(user)} купил {sid} у "
                                         f"{lot.get('sellerName')} за {lot['price']} 🪙 (комиссия 5%)")
                        self._reply(200, json.dumps({"ok": True, "payout": payout}).encode("utf-8"))
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


load_all()
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
        start_parameter="topup")


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
                    start_parameter="buy-item")
            else:
                bot.reply_to(message, "Такого товара нет 🤷")
        except Exception as e:
            print("buy_ error:", e)
    else:
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("🎮 Открыть игру",
                                        url=f"https://t.me/{BOT_USERNAME}/{APP_SHORT_NAME}?startapp=menu"))
        bot.reply_to(message, "Привет! Играй в игру по кнопке ниже 👇\nДля пополнения нажми ⭐ в самой игре",
                     reply_markup=markup)


@bot.callback_query_handler(func=lambda call: call.data.startswith("gift_ok_") or call.data.startswith("gift_no_")
                            or call.data.startswith("wd_ok_") or call.data.startswith("wd_no_"))
def decision(call):
    if call.from_user.id != ADMIN_ID:
        bot.answer_callback_query(call.id, "Только для админа!")
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
    except Exception as e:
        print("decision error:", e)
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
        notify_admin(f"💰 ПОПОЛНЕНИЕ! Игрок {esc(name)} купил {amount} звёзд.")
        bot.send_message(message.chat.id, "✅ Оплата прошла! Нажми кнопку — звёзды начислятся в игре:",
                         reply_markup=markup)
    elif payload.startswith("pay_"):
        item_id = payload.split('_')[1]
        item = SKIN_PRICES.get(item_id, {})
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("🎮 Активировать в игре",
                                        url=f"https://t.me/{BOT_USERNAME}/{APP_SHORT_NAME}?startapp=boost_{item_id}"))
        notify_admin(f"💰 ПОКУПКА! Игрок {esc(name)} купил {esc(item_id)} за {amount}⭐!")
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


def periodic():
    while True:
        try:
            ensure_season()
            time.sleep(1800)
        except Exception as e:
            print("periodic error:", e)
            time.sleep(60)


threading.Thread(target=periodic, daemon=True).start()

print("Бот запущен, жду сообщения...")
bot.infinity_polling(timeout=10, long_polling_timeout=5, skip_pending=True)
