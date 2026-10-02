# -*- coding: utf-8 -*-
# BAGAR BILLI v3 (Funny Edition)  -  Powered by Symiiii
#
# Pydroid 3: Pip > flask install > ye file run > Chrome me http://127.0.0.1:5000
# Dost (same WiFi/hotspot): http://TUMHARA_PHONE_IP:5000
# Internet par: 1 worker hi rakho (online/typing/game rooms memory me hain)
#   gunicorn -w 1 --threads 16 -b 0.0.0.0:8000 "bagar_billi_v3:app"   (pehle init() ek baar chalao)

import os, re, time, random, secrets, sqlite3
from flask import Flask, request, jsonify, Response
from werkzeug.security import generate_password_hash, check_password_hash

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE, "bagarbilli.db")
app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 8 * 1024 * 1024
rooms = {}      # truth & dare rooms
seen = {}       # username -> last request time (online status)
typing = {}     # chat key -> {user: time}
BOT = "billibot"


# ---------------------------------------------------------------- database
def q(sql, args=(), one=False, commit=False):
    c = sqlite3.connect(DB, timeout=15)
    c.row_factory = sqlite3.Row
    try:
        cur = c.execute(sql, args)
        if commit:
            c.commit()
            return cur.lastrowid
        rows = cur.fetchall()
        if one:
            return rows[0] if rows else None
        return rows
    finally:
        c.close()


def init():
    q("create table if not exists users(username text primary key, pw text, bio text default '', photo text default '')", commit=True)
    q("create table if not exists sessions(token text primary key, username text)", commit=True)
    q("create table if not exists groups(id integer primary key autoincrement, name text unique, owner text)", commit=True)
    q("create table if not exists members(gid integer, username text, primary key(gid, username))", commit=True)
    q("create table if not exists messages(id integer primary key autoincrement, key text, sender text, text text, img text, ts integer, reply text default '', deleted integer default 0)", commit=True)
    q("create table if not exists reacts(mid integer, username text, emoji text, primary key(mid, username))", commit=True)
    q("create table if not exists taps(username text primary key, n integer default 0)", commit=True)
    q("create index if not exists ix_msg on messages(key, id)", commit=True)
    # purane database ke liye naye columns
    for sql in ("alter table messages add column reply text default ''",
                "alter table messages add column deleted integer default 0"):
        try:
            q(sql, commit=True)
        except sqlite3.OperationalError:
            pass


def need():
    t = request.headers.get("X-Token", "")
    r = q("select username from sessions where token=?", (t,), one=True)
    if r:
        seen[r["username"]] = time.time()
        return r["username"]
    return None


def unauth():
    return jsonify(error="login"), 401


def is_online(u):
    return (time.time() - seen.get(u, 0)) < 25


def key_access(u, key):
    if key.startswith("dm:"):
        return u in key.split(":")[1:]
    if key.startswith("g:"):
        return q("select 1 from members where gid=? and username=?", (key[2:], u), one=True) is not None
    return False


def chat_key(u, kind, target):
    if kind == "dm":
        if target and target != BOT and q("select 1 from users where username=?", (target,), one=True):
            return "dm:" + ":".join(sorted([u, target]))
    elif kind == "g":
        if q("select 1 from members where gid=? and username=?", (target, u), one=True):
            return "g:" + str(target)
    return None


LEVELS = [(0, "Bachha Billi 🐾"), (30, "Gali ki Billi 🐈"), (150, "Sher Billi 🦁"),
          (500, "Billi King 👑"), (1500, "Billi Bhagwan 🌟")]


def level_of(n):
    name, nxt = LEVELS[0][1], LEVELS[1][0]
    for i, (th, nm) in enumerate(LEVELS):
        if n >= th:
            name = nm
            nxt = LEVELS[i + 1][0] if i + 1 < len(LEVELS) else None
    return name, nxt


def msg_count(u):
    return q("select count(*) c from messages where sender=? and deleted=0", (u,), one=True)["c"]


# ---------------------------------------------------------------- auth / profile
@app.post("/api/auth")
def auth():
    d = request.get_json(force=True, silent=True) or {}
    u = (d.get("username") or "").strip().lower()
    p = d.get("password") or ""
    if not re.fullmatch(r"[a-z0-9_]{3,20}", u) or u == BOT:
        return jsonify(error="Username 3-20 akshar: a-z, 0-9, _"), 400
    if len(p) < 4:
        return jsonify(error="Password kam se kam 4 akshar ka rakho"), 400
    row = q("select * from users where username=?", (u,), one=True)
    if row is None:
        q("insert into users(username,pw) values(?,?)", (u, generate_password_hash(p)), commit=True)
    elif not check_password_hash(row["pw"], p):
        return jsonify(error="Password galat hai"), 403
    t = secrets.token_hex(16)
    q("insert into sessions values(?,?)", (t, u), commit=True)
    seen[u] = time.time()
    return jsonify(token=t, username=u)


@app.get("/api/me")
def me():
    u = need()
    if not u:
        return unauth()
    r = dict(q("select username,bio,photo from users where username=?", (u,), one=True))
    n = msg_count(u)
    r["level"], r["next"] = level_of(n)
    r["msgs"] = n
    t = q("select n from taps where username=?", (u,), one=True)
    r["taps"] = t["n"] if t else 0
    return jsonify(r)


@app.post("/api/profile")
def profile():
    u = need()
    if not u:
        return unauth()
    d = request.get_json(force=True, silent=True) or {}
    q("update users set bio=? where username=?", ((d.get("bio") or "")[:200], u), commit=True)
    ph = d.get("photo")
    if ph and ph.startswith("data:image/") and len(ph) < 400000:
        q("update users set photo=? where username=?", (ph, u), commit=True)
    return jsonify(ok=True)


def user_row(r):
    x = dict(r)
    x["online"] = is_online(x["username"])
    x["level"] = level_of(msg_count(x["username"]))[0]
    return x


@app.get("/api/users")
def users():
    u = need()
    if not u:
        return unauth()
    s = (request.args.get("q") or "").strip().lower()
    if not s:
        return jsonify(users=[])
    like = "%" + s + "%"
    rows = q("select username,bio,photo from users where (username like ? or lower(bio) like ?) and username<>? limit 30", (like, like, u))
    return jsonify(users=[user_row(r) for r in rows])


@app.get("/api/online")
def online():
    u = need()
    if not u:
        return unauth()
    names = [n for n in list(seen) if n != u and is_online(n)][:30]
    out = []
    for n in names:
        r = q("select username,bio,photo from users where username=?", (n,), one=True)
        if r:
            out.append(user_row(r))
    return jsonify(users=out)


# ---------------------------------------------------------------- funny bot
JOKES = [
    "Teacher: Tum late kyun aaye? Student: Sir, board par likha tha 'School ahead, go slow' 🐢",
    "Billi ne sher se kaha: Tu bhi meri hi family hai, bas thoda bada hai 🦁",
    "Wifi aur crush me same baat hai - dono 'connected' dikhte hain par net nahi milta 📶",
    "Doctor: Aapko aaram chahiye. Patient: Wo to Monday ko bhi nahi milta 😴",
    "Maths ki book itni sad kyun thi? Kyunki uske paas bahut saari problems thi 📚",
    "Mobile 1% par bhi reply nahi dete, aur crush ka message aaye to charger dhoondte hain 🔋",
]
ROASTS = [
    "{n} ka WiFi signal bhi tumse zyada serious hai 📶",
    "{n} itna slow hai ki loading bhi 'Rukiye' bol deti hai 🐢",
    "{n} ki battery aur akal dono 1% par chalti hain 🔋",
    "{n} ki selfie dekh kar camera ne bhi 'Retake' maang liya 📸",
    "{n} ka dimaag Airplane Mode me hi rehta hai ✈️",
    "{n} bolta kam hai, bakchodi zyada karta hai 🤡",
]
BALL = ["Haan bilkul! ✅", "Bilkul nahi ❌", "Billi se pooch ke batata hoon 🐱", "Shayad... 🤔",
        "Pakka! 💯", "Dobara pooch, mood nahi hai 😴", "Sapne me haan, asli me na 😹"]
HELP = ("🤖 Billi Bot commands:\n/joke - joke\n/roast [naam] - roast\n/dice - pasa\n/flip - sikka\n"
        "/8ball sawaal - jawab\n/love naam1 naam2 - pyaar %\n/meow - meow 🐱")


def bot_reply(u, text):
    parts = text.split(None, 1)
    cmd = parts[0].lower()
    arg = parts[1].strip() if len(parts) > 1 else ""
    if cmd == "/help":
        return HELP
    if cmd == "/joke":
        return random.choice(JOKES)
    if cmd == "/roast":
        return random.choice(ROASTS).format(n=arg or u)
    if cmd == "/dice":
        return "🎲 Pasa bola: %d" % random.randint(1, 6)
    if cmd == "/flip":
        return "🪙 " + random.choice(["Heads (chit)", "Tails (patt)"])
    if cmd == "/8ball":
        return "🎱 " + random.choice(BALL)
    if cmd == "/meow":
        return "meow meow meow 🐱🐟"
    if cmd == "/love":
        names = arg.replace(",", " ").split()
        if len(names) < 2:
            return "Aise likho: /love Rahul Priya 💘"
        a, b = sorted([names[0].lower(), names[1].lower()])
        pct = (sum(map(ord, a + b)) * 7 + 13) % 61 + 40
        return "💘 %s + %s = %d%% match!" % (names[0], names[1], pct)
    return None


# ---------------------------------------------------------------- messages
@app.get("/api/chats")
def chats():
    u = need()
    if not u:
        return unauth()
    rows = q("select key, max(id) mid from messages where key like 'dm:%' group by key order by mid desc")
    out = []
    for r in rows:
        parts = r["key"].split(":")
        if u in parts[1:]:
            other = parts[2] if parts[1] == u else parts[1]
            last = q("select text,img,deleted from messages where id=?", (r["mid"],), one=True)
            ou = q("select photo from users where username=?", (other,), one=True)
            txt = "🚫 delete hua" if last["deleted"] else (last["text"] or "📷 Photo")
            out.append(dict(user=other, photo=ou["photo"] if ou else "", last=txt[:60], online=is_online(other)))
    return jsonify(chats=out)


@app.get("/api/msgs")
def msgs():
    u = need()
    if not u:
        return unauth()
    kind, target = request.args.get("kind"), request.args.get("target")
    key = chat_key(u, kind, target)
    if not key:
        return jsonify(error="no access"), 403
    try:
        after = int(request.args.get("after") or 0)
    except ValueError:
        after = 0
    rows = q("select id,sender,text,img,ts,reply,deleted from messages where key=? and id>? order by id limit 100", (key, after))
    recent = q("select id,deleted from messages where key=? order by id desc limit 60", (key,))
    ids = [r["id"] for r in recent]
    gone = [r["id"] for r in recent if r["deleted"]]
    reacts = {}
    if ids:
        rr = q("select mid,username,emoji from reacts where mid in (%s)" % ",".join("?" * len(ids)), ids)
        for r in rr:
            reacts.setdefault(r["mid"], {}).setdefault(r["emoji"], []).append(r["username"])
    now = time.time()
    typ = [t for t, ts in typing.get(key, {}).items() if now - ts < 4 and t != u]
    return jsonify(msgs=[dict(r) for r in rows], gone=gone, reacts=reacts, typing=typ,
                   online=is_online(target) if kind == "dm" else None)


@app.post("/api/send")
def send():
    u = need()
    if not u:
        return unauth()
    d = request.get_json(force=True, silent=True) or {}
    key = chat_key(u, d.get("kind"), d.get("target"))
    if not key:
        return jsonify(error="no access"), 403
    text = (d.get("text") or "")[:2000]
    img = d.get("img") or ""
    if img and not (img.startswith("data:image/") or img.startswith("http")):
        img = ""
    if len(img) > 4000000:
        return jsonify(error="Image bahut badi hai"), 400
    if not text and not img:
        return jsonify(error="empty"), 400
    reply = ""
    try:
        rid = int(d.get("reply") or 0)
    except ValueError:
        rid = 0
    if rid:
        rr = q("select sender,text from messages where id=? and key=?", (rid, key), one=True)
        if rr:
            reply = rr["sender"] + ": " + ((rr["text"] or "📷 Photo")[:60])
    now = int(time.time())
    q("insert into messages(key,sender,text,img,ts,reply,deleted) values(?,?,?,?,?,?,0)",
      (key, u, text, img, now, reply), commit=True)
    if text.startswith("/"):
        out = bot_reply(u, text)
        if out:
            q("insert into messages(key,sender,text,img,ts,reply,deleted) values(?,?,?,?,?,?,0)",
              (key, BOT, out, "", now, ""), commit=True)
    typing.get(key, {}).pop(u, None)
    return jsonify(ok=True)


@app.post("/api/typing")
def typing_ping():
    u = need()
    if not u:
        return unauth()
    d = request.get_json(force=True, silent=True) or {}
    key = chat_key(u, d.get("kind"), d.get("target"))
    if key:
        typing.setdefault(key, {})[u] = time.time()
    return jsonify(ok=True)


@app.post("/api/react")
def react():
    u = need()
    if not u:
        return unauth()
    d = request.get_json(force=True, silent=True) or {}
    emoji = (d.get("emoji") or "")[:8]
    m = q("select id,key from messages where id=?", (d.get("id"),), one=True)
    if not m or not emoji or not key_access(u, m["key"]):
        return jsonify(error="no access"), 403
    cur = q("select emoji from reacts where mid=? and username=?", (m["id"], u), one=True)
    if cur and cur["emoji"] == emoji:
        q("delete from reacts where mid=? and username=?", (m["id"], u), commit=True)
    else:
        q("insert or replace into reacts values(?,?,?)", (m["id"], u, emoji), commit=True)
    return jsonify(ok=True)


@app.post("/api/delete")
def delete_msg():
    u = need()
    if not u:
        return unauth()
    d = request.get_json(force=True, silent=True) or {}
    q("update messages set deleted=1, text='', img='', reply='' where id=? and sender=?", (d.get("id"), u), commit=True)
    return jsonify(ok=True)


# ---------------------------------------------------------------- groups
@app.post("/api/group/create")
def gcreate():
    u = need()
    if not u:
        return unauth()
    d = request.get_json(force=True, silent=True) or {}
    name = (d.get("name") or "").strip()[:30]
    if len(name) < 2:
        return jsonify(error="Group ka naam likho"), 400
    if q("select 1 from groups where lower(name)=lower(?)", (name,), one=True):
        return jsonify(error="Ye naam le liya gaya hai"), 400
    gid = q("insert into groups(name,owner) values(?,?)", (name, u), commit=True)
    q("insert into members values(?,?)", (gid, u), commit=True)
    return jsonify(id=gid)


@app.get("/api/groups")
def glist():
    u = need()
    if not u:
        return unauth()
    s = (request.args.get("q") or "").strip()
    if s:
        rows = q("select * from groups where name like ? limit 30", ("%" + s + "%",))
    else:
        rows = q("select g.* from groups g join members m on m.gid=g.id where m.username=?", (u,))
    out = []
    for g in rows:
        n = q("select count(*) c from members where gid=?", (g["id"],), one=True)["c"]
        j = q("select 1 from members where gid=? and username=?", (g["id"], u), one=True) is not None
        out.append(dict(id=g["id"], name=g["name"], members=n, joined=j))
    return jsonify(groups=out)


@app.post("/api/group/join")
def gjoin():
    u = need()
    if not u:
        return unauth()
    d = request.get_json(force=True, silent=True) or {}
    if not q("select 1 from groups where id=?", (d.get("id"),), one=True):
        return jsonify(error="group nahi mila"), 404
    q("insert or ignore into members values(?,?)", (d.get("id"), u), commit=True)
    return jsonify(ok=True)


@app.post("/api/group/add")
def gadd():
    u = need()
    if not u:
        return unauth()
    d = request.get_json(force=True, silent=True) or {}
    gid = d.get("id")
    who = (d.get("username") or "").strip().lower()
    if not q("select 1 from members where gid=? and username=?", (gid, u), one=True):
        return jsonify(error="no access"), 403
    if not q("select 1 from users where username=?", (who,), one=True):
        return jsonify(error="User nahi mila"), 404
    q("insert or ignore into members values(?,?)", (gid, who), commit=True)
    return jsonify(ok=True)


# ---------------------------------------------------------------- fun: taps + leaderboard
@app.post("/api/tap")
def tap():
    u = need()
    if not u:
        return unauth()
    d = request.get_json(force=True, silent=True) or {}
    try:
        n = max(1, min(40, int(d.get("n") or 0)))
    except ValueError:
        n = 1
    q("insert or ignore into taps values(?,0)", (u,), commit=True)
    q("update taps set n=n+? where username=?", (n, u), commit=True)
    return jsonify(n=q("select n from taps where username=?", (u,), one=True)["n"])


@app.get("/api/leaderboard")
def leaderboard():
    u = need()
    if not u:
        return unauth()
    t = q("select username user, n from taps where n>0 order by n desc limit 10")
    c = q("select sender user, count(*) n from messages where sender<>? and deleted=0 group by sender order by n desc limit 5", (BOT,))
    return jsonify(taps=[dict(r) for r in t], chat=[dict(r) for r in c])


# ---------------------------------------------------------------- truth & dare
TRUTHS = [
    "Aaj tak ka sabse bada jhooth kya bola hai?", "Tumhara pehla crush kaun tha?",
    "Phone me sabse embarrassing cheez kya hai?", "Kisi se chhupke kya karte ho?",
    "Sabse ajeeb sapna kaun sa dekha hai?", "Kis dost se sabse zyada jalte ho?",
    "Aakhri baar kab roye the aur kyun?", "Apni kaun si aadat tumhe pasand nahi?",
    "Kabhi kisi ka message bina bataye padha hai?", "Group me sabse irritating kaun lagta hai?",
    "Bathroom me sabse zyada time kya karte ho?", "Sabse bekaar gift kya mila tha?",
]
DARES = [
    "Apni sabse funny awaaz me gaana gao.", "10 push-ups karo abhi.",
    "Apne kisi dost ko 'I miss you' bhejo.", "1 minute bina hanse dikhao.",
    "Billi ki tarah 30 second tak meow karo.", "Apni sabse purani photo group me bhejo.",
    "Kisi bhi ek ko compliment do, over-acting ke saath.", "Ulti ginti 20 se 1 tak tez bolo.",
    "Apna naam ulta bolo 3 baar.", "Ek chhoti si shayari sunao.",
    "Murga bano 20 second ke liye.", "Apni best villain hasi hanso.",
]


def gstate(r, u):
    return dict(code=r["code"], players=r["players"], host=r["players"][0], turn=r["turn"],
                phase=r["phase"], mode=r["mode"], question=r["question"], asker=r["asker"],
                log=r["log"][-6:], you=u)


@app.post("/api/game/create")
def game_create():
    u = need()
    if not u:
        return unauth()
    code = str(random.randint(1000, 9999))
    while code in rooms:
        code = str(random.randint(1000, 9999))
    rooms[code] = dict(code=code, players=[u], turn=0, phase="lobby", mode=None,
                       question=None, asker=None, log=[])
    return jsonify(gstate(rooms[code], u))


@app.post("/api/game/join")
def game_join():
    u = need()
    if not u:
        return unauth()
    d = request.get_json(force=True, silent=True) or {}
    r = rooms.get(str(d.get("code")))
    if not r:
        return jsonify(error="Room nahi mila"), 404
    if u not in r["players"]:
        if len(r["players"]) >= 4:
            return jsonify(error="Room full hai (max 4)"), 400
        if r["phase"] != "lobby":
            return jsonify(error="Game shuru ho chuka hai"), 400
        r["players"].append(u)
    return jsonify(gstate(r, u))


@app.get("/api/game")
def game_get():
    u = need()
    if not u:
        return unauth()
    r = rooms.get(request.args.get("code", ""))
    if not r or u not in r["players"]:
        return jsonify(error="room band"), 404
    return jsonify(gstate(r, u))


@app.post("/api/game/act")
def game_act():
    u = need()
    if not u:
        return unauth()
    d = request.get_json(force=True, silent=True) or {}
    r = rooms.get(str(d.get("code")))
    if not r or u not in r["players"]:
        return jsonify(error="room band"), 404
    a = d.get("action")
    v = (d.get("value") or "").strip()[:300]
    cur = r["players"][r["turn"]]
    if a == "start" and r["phase"] == "lobby" and u == r["players"][0] and len(r["players"]) >= 2:
        r["phase"] = "choose"
    elif a == "choose" and r["phase"] == "choose" and u == cur and v in ("truth", "dare"):
        r["mode"] = v
        r["phase"] = "ask"
    elif a == "ask" and r["phase"] == "ask" and u != cur:
        if not v or v == "__random__":
            v = random.choice(TRUTHS if r["mode"] == "truth" else DARES)
        r["question"] = v
        r["asker"] = u
        r["phase"] = "answer"
    elif a == "done" and r["phase"] == "answer" and u == cur:
        r["log"].append(dict(player=cur, mode=r["mode"], q=r["question"], a=v or "done"))
        r["turn"] = (r["turn"] + 1) % len(r["players"])
        r["phase"] = "choose"
        r["mode"] = r["question"] = r["asker"] = None
    return jsonify(gstate(r, u))


# ---------------------------------------------------------------- frontend
PAGE = r"""<!DOCTYPE html>
<html lang="hi"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no">
<title>Bagar Billi</title>
<style>
:root{--acc:#ff7a1a;--acc2:#e1306c;--card:rgba(255,255,255,.09);--tx:#f1f1f5;--mut:#a3a0b8}
*{box-sizing:border-box;-webkit-tap-highlight-color:transparent}
html,body{margin:0;height:100%;color:var(--tx);font-family:system-ui,sans-serif}
body{background:linear-gradient(-45deg,#1a0b2e,#0f1115,#2b1055,#6b2a0c,#0f1115);background-size:400% 400%;animation:bgmove 20s ease infinite;-webkit-user-select:none;user-select:none;-webkit-touch-callout:none;overflow:hidden}
@keyframes bgmove{0%{background-position:0 50%}50%{background-position:100% 50%}100%{background-position:0 50%}}
input,textarea{-webkit-user-select:text;user-select:text}
#fx{position:fixed;inset:0;overflow:hidden;pointer-events:none;z-index:0}
#fx span{position:absolute;bottom:-70px;opacity:.2;animation:fl linear infinite}
@keyframes fl{0%{transform:translateY(0) rotate(0)}100%{transform:translateY(-120vh) rotate(360deg)}}
#run{position:fixed;bottom:62px;left:-90px;font-size:28px;z-index:2;pointer-events:none;animation:run 16s linear infinite}
@keyframes run{0%{left:-90px}100%{left:105%}}
#app{display:flex;flex-direction:column;height:100%;position:relative;z-index:1}
#main{flex:1;min-height:0;overflow-y:auto;padding:12px;display:flex;flex-direction:column}
#nav{display:flex;backdrop-filter:blur(14px);-webkit-backdrop-filter:blur(14px);background:rgba(15,10,30,.8);border-top:1px solid rgba(255,255,255,.1)}
#nav button{flex:1;background:none;border:0;color:var(--mut);padding:8px 0;font-size:10px}
#nav button span{display:block;font-size:20px}
#nav button.on{color:var(--acc)}
button{font:inherit}
.btn{background:linear-gradient(135deg,var(--acc),var(--acc2));color:#fff;border:0;border-radius:12px;padding:10px 14px;font-weight:600;box-shadow:0 3px 10px rgba(0,0,0,.3);text-decoration:none;display:inline-block}
.btn.alt{background:rgba(255,255,255,.14);box-shadow:none}
input,textarea{width:100%;background:rgba(255,255,255,.1);border:1px solid rgba(255,255,255,.12);color:var(--tx);border-radius:12px;padding:11px;font:inherit}
.row{display:flex;gap:8px;align-items:center;margin-bottom:8px}
.item,.card,.big{backdrop-filter:blur(8px);-webkit-backdrop-filter:blur(8px);border:1px solid rgba(255,255,255,.08);background:var(--card);border-radius:14px}
.item{display:flex;gap:10px;align-items:center;padding:10px;margin-bottom:8px}
.card{padding:12px;margin-bottom:12px}
.item .t{flex:1;min-width:0}.item small{color:var(--mut);display:block;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.avw{position:relative;flex:none}
.av{width:42px;height:42px;border-radius:50%;background:linear-gradient(135deg,var(--acc),var(--acc2));display:flex;align-items:center;justify-content:center;font-weight:700;object-fit:cover}
.dot{position:absolute;right:0;bottom:0;width:12px;height:12px;border-radius:50%;background:#2ecc71;border:2px solid #141020}
.top{display:flex;gap:10px;align-items:center;padding-bottom:8px;border-bottom:1px solid rgba(255,255,255,.1);margin-bottom:8px}
.top button{background:none;border:0;color:var(--tx);font-size:22px}
.msgs{flex:1;min-height:0;overflow-y:auto;display:flex;flex-direction:column;gap:6px;padding:8px;border-radius:14px;background-color:rgba(255,255,255,.04)}
.m{max-width:80%;padding:7px 11px;border-radius:14px;background:rgba(20,22,32,.88);align-self:flex-start;word-break:break-word;white-space:pre-wrap}
.m.me{background:linear-gradient(135deg,var(--acc),var(--acc2));align-self:flex-end}
.m.bot{background:rgba(88,60,160,.92);border:1px dashed #b39ddb;align-self:center;max-width:92%}
.m.gone{opacity:.5;font-style:italic;font-size:13px}
.m>b{display:block;font-size:11px}
.m img{max-width:100%;border-radius:10px;display:block;margin-top:4px;cursor:pointer}
.q{border-left:3px solid #fff8;padding:2px 6px;margin:2px 0 4px;font-size:12px;opacity:.85;background:rgba(255,255,255,.1);border-radius:4px}
.tm{display:block;font-size:10px;opacity:.55;text-align:right}
.rx{display:flex;gap:4px;flex-wrap:wrap}
.rx span{background:rgba(255,255,255,.18);border-radius:10px;padding:0 6px;font-size:13px;margin-top:2px}
.rx span.mine{outline:1px solid #fff}
.bg1{font-size:44px;line-height:1.15}
.inp{display:flex;gap:6px;align-items:center;padding-top:6px}
.ic{background:none;border:0;font-size:24px;padding:0 3px;color:inherit}
.rp{display:flex;align-items:center;gap:6px;background:rgba(255,255,255,.12);border-left:3px solid var(--acc);padding:6px 8px;border-radius:8px;font-size:12px;margin-top:6px}
.rp span{flex:1;overflow:hidden;white-space:nowrap;text-overflow:ellipsis}
.ep{background:rgba(25,18,45,.95);border-radius:12px;padding:8px;margin-top:6px}
.eg{display:flex;flex-wrap:wrap;gap:8px;font-size:26px}.eg.st{font-size:42px}
h2{margin:4px 0 12px}.mut{color:var(--mut)}
.tick{overflow:hidden;white-space:nowrap;background:rgba(255,255,255,.08);border-radius:10px;padding:6px 0;margin-bottom:10px;font-size:13px}
.tick span{display:inline-block;padding-left:100%;animation:tk 22s linear infinite}
@keyframes tk{to{transform:translateX(-100%)}}
#splash{position:fixed;inset:0;background:linear-gradient(160deg,#1a0b2e,#0f1115 50%,#7a2e0e);z-index:99;display:flex;flex-direction:column;align-items:center;justify-content:center;text-align:center;padding:20px}
#splash h1{font-size:42px;margin:10px 0;color:var(--acc)}
#splash .pw{position:absolute;bottom:28px;color:var(--mut);letter-spacing:1px}
#splash .cat{font-size:80px;animation:wob 1s ease-in-out infinite}
@keyframes wob{0%,100%{transform:rotate(-12deg)}50%{transform:rotate(12deg) scale(1.1)}}
#fab{position:fixed;right:12px;bottom:76px;width:50px;height:50px;border-radius:50%;background:linear-gradient(135deg,var(--acc),var(--acc2));border:0;font-size:22px;z-index:50;box-shadow:0 2px 10px #0008}
#mp{position:fixed;right:12px;bottom:134px;width:min(300px,90vw);background:rgba(25,18,45,.96);border:1px solid rgba(255,255,255,.12);border-radius:14px;padding:10px;z-index:50;display:none}
#mp.on{display:block}
#pl{max-height:140px;overflow-y:auto;margin:6px 0}
#pl div{padding:5px;border-radius:6px;font-size:13px}#pl div.cur{background:rgba(255,255,255,.12);color:var(--acc)}
.big{font-size:20px;text-align:center;padding:14px;margin:10px 0}
.err{color:#ff6b6b;margin:8px 0;min-height:18px}
.blur{filter:blur(18px)}
#wp,#vw{position:fixed;inset:0;z-index:90;background:rgba(0,0,0,.75);display:flex;align-items:flex-end;justify-content:center}
#vw{align-items:center;flex-direction:column;gap:12px}
#vw img{max-width:96%;max-height:78%;border-radius:10px}
.sheet{width:100%;max-width:480px;background:#1b1530;border-radius:18px 18px 0 0;padding:14px}
.sw{display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin:10px 0}
.sw .s{height:62px;border-radius:12px;display:flex;align-items:flex-end;justify-content:center;font-size:11px;padding:4px;color:#fff;text-shadow:0 1px 3px #000}
.rb{padding:2px 4px}
.tapb{font-size:84px;background:none;border:0;touch-action:manipulation;transition:transform .08s;color:inherit}
.tapb:active{transform:scale(.82) rotate(-10deg)}
.bu{position:fixed;bottom:70px;z-index:120;pointer-events:none;animation:rise 1.9s ease-out forwards}
@keyframes rise{to{transform:translateY(-72vh) rotate(40deg);opacity:0}}
.th{display:flex;gap:10px;margin:8px 0}
.th i{width:34px;height:34px;border-radius:50%;display:block}
</style></head><body>
<div id="fx"></div><div id="run">🐈💨</div>
<div id="splash"><div class="cat">🐱</div><h1>Bagar Billi</h1><div class="mut" id="stag"></div><div class="pw">Powered by Symiiii</div></div>
<div id="app"><div id="main"></div><div id="nav" style="display:none"></div></div>
<button id="fab" style="display:none">🎵</button>
<div id="mp">
 <div class="row"><label class="btn alt" style="flex:1;text-align:center">+ Gaane chuno<input type="file" id="mf" accept="audio/*" multiple hidden></label></div>
 <div id="pl" class="mut">Koi gaana nahi</div>
 <div class="row" style="justify-content:center;margin:0">
  <button class="btn alt" id="mprev">⏮</button><button class="btn" id="mpp">▶</button><button class="btn alt" id="mnext">⏭</button>
 </div>
 <audio id="au"></audio>
</div>
<script>
const $=s=>document.querySelector(s);
const main=$('#main'),nav=$('#nav');
let TOKEN=localStorage.getItem('bb_t'),ME=null,tab='chats',cur=null,room=null,tapTimer=null;
let soundOn=localStorage.getItem('bb_snd')!=='0';
const esc=s=>String(s==null?'':s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const pick=a=>a[Math.floor(Math.random()*a.length)];
const TAGS=["Bagar billi bhi aaj online hai 🐱","Chat kam, meow zyada 😹","Doodh nahi mila? Chat kar lo 🥛","Billi ne kaha: seen mat karna 🙈","Aaj ka plan: bakchodi 🤡","Charge 1% par bhi reply do 🔋","Billi rasta kaat gayi, ab chat karo 🐈‍⬛","Sab moh maya hai, meme bhejo 💬","Hasna mana hai... par hasoge zaroor 😂"];
const ticker=()=>`<div class="tick"><span>${[...TAGS].sort(()=>Math.random()-.5).slice(0,5).join('  •  ')}</span></div>`;
$('#stag').textContent=pick(TAGS);
async function api(p,b){
 const o={headers:{'X-Token':TOKEN||'','Content-Type':'application/json'}};
 if(b){o.method='POST';o.body=JSON.stringify(b)}
 let r;try{r=await fetch(p,o)}catch(e){return{error:'Server se connection nahi'}}
 const j=await r.json().catch(()=>({error:'Error'}));
 if(r.status==401&&TOKEN){logout();return{error:'login'}}
 return j;
}
function av(photo,name,on){
 const i=photo?`<img class="av" src="${photo}">`:`<div class="av">${esc((name||'?')[0].toUpperCase())}</div>`;
 return `<div class="avw">${i}${on?'<i class="dot"></i>':''}</div>`;
}
const col=n=>'hsl('+([...n].reduce((a,c)=>a*31+c.charCodeAt(0),7)%360)+',80%,72%)';
const tm=t=>new Date(t*1000).toLocaleTimeString([],{hour:'2-digit',minute:'2-digit'});
const EMOJI_ONLY=/^[\p{Extended_Pictographic}\uFE0F\u200D\s]+$/u;
// ---- funny floating background
(function(){
 const E=['🐱','😹','🐟','🥛','🤡','💩','🔥','👻','🍕','🙈','🐾','🧀','🐈','😎'];
 const f=$('#fx');
 for(let i=0;i<16;i++){
  const s=document.createElement('span');s.textContent=E[i%E.length];
  s.style.left=(i*6.2+Math.random()*4)+'%';s.style.fontSize=(18+Math.random()*28)+'px';
  s.style.animationDuration=(14+Math.random()*16)+'s';s.style.animationDelay=(-Math.random()*22)+'s';
  f.appendChild(s);
 }
})();
// ---- theme colours
const THEMES=[['#ff7a1a','#e1306c'],['#00b4ff','#7b61ff'],['#2ecc71','#00c9a7'],['#a855f7','#ec4899'],['#ef4444','#f59e0b'],['#14b8a6','#3b82f6']];
function setTheme(i){
 const t=THEMES[i]||THEMES[0];
 document.documentElement.style.setProperty('--acc',t[0]);document.documentElement.style.setProperty('--acc2',t[1]);
 localStorage.setItem('bb_th',i);
}
setTheme(+localStorage.getItem('bb_th')||0);
// ---- sounds + confetti
let AC;
function ac(){if(!AC)AC=new (window.AudioContext||window.webkitAudioContext)();return AC}
function beep(f,d){
 if(!soundOn)return;
 try{const c=ac(),o=c.createOscillator(),g=c.createGain();o.frequency.value=f||880;g.gain.setValueAtTime(.15,c.currentTime);
  g.gain.exponentialRampToValueAtTime(.001,c.currentTime+(d||.12));o.connect(g);g.connect(c.destination);o.start();o.stop(c.currentTime+(d||.12))}catch(e){}
}
function meow(){
 try{const c=ac(),o=c.createOscillator(),g=c.createGain(),t=c.currentTime;o.type='sawtooth';
  o.frequency.setValueAtTime(500,t);o.frequency.linearRampToValueAtTime(900,t+.18);o.frequency.linearRampToValueAtTime(380,t+.5);
  g.gain.setValueAtTime(.001,t);g.gain.linearRampToValueAtTime(.18,t+.08);g.gain.linearRampToValueAtTime(.001,t+.55);
  o.connect(g);g.connect(c.destination);o.start(t);o.stop(t+.6)}catch(e){}
}
function burst(e,n){
 for(let i=0;i<(n||14);i++){
  const s=document.createElement('span');s.className='bu';s.textContent=e;
  s.style.left=Math.random()*90+'%';s.style.animationDelay=Math.random()*.4+'s';s.style.fontSize=(20+Math.random()*26)+'px';
  document.body.appendChild(s);setTimeout(()=>s.remove(),2400);
 }
}
document.addEventListener('contextmenu',e=>e.preventDefault());
document.addEventListener('visibilitychange',()=>{document.body.classList.toggle('blur',document.hidden)});
// ---- start / login
setTimeout(async()=>{
 $('#splash').style.display='none';
 if(TOKEN){const m=await api('/api/me');if(m.username){ME=m;return startApp()}}
 loginView();
},2000);
function loginView(){
 nav.style.display='none';$('#fab').style.display='none';
 main.innerHTML=`<div style="margin:auto;width:100%;max-width:340px">
 <div style="text-align:center;font-size:60px">🐱</div><h2 style="text-align:center">Bagar Billi</h2>
 ${ticker()}
 <div class="row"><input id="lu" placeholder="Username" autocapitalize="none" autocomplete="off"></div>
 <div class="row"><input id="lp" type="password" placeholder="Password"></div>
 <div class="err" id="le"></div>
 <button class="btn" style="width:100%" id="lb">Login / Naya account 🐾</button>
 <p class="mut" style="text-align:center;font-size:12px">Username nahi hai to apne aap account ban jayega.<br>Password yaad rakhna - forgot password nahi hai 😹</p></div>`;
 $('#lb').onclick=async()=>{
  const j=await api('/api/auth',{username:$('#lu').value,password:$('#lp').value});
  if(j.error)return $('#le').textContent=j.error;
  TOKEN=j.token;localStorage.setItem('bb_t',TOKEN);
  ME=await api('/api/me');startApp();burst('🎉',16);meow();
 };
}
function logout(){TOKEN=null;localStorage.removeItem('bb_t');cur=null;room=null;ME=null;loginView()}
function startApp(){
 nav.style.display='flex';$('#fab').style.display='block';
 const T=[['chats','💬','Chats'],['groups','👥','Groups'],['search','🔍','Search'],['fun','🤪','Fun'],['game','🎲','Game'],['profile','👤','Profile']];
 nav.innerHTML=T.map(t=>`<button data-t="${t[0]}"><span>${t[1]}</span>${t[2]}</button>`).join('');
 nav.querySelectorAll('button').forEach(b=>b.onclick=()=>{tab=b.dataset.t;cur=null;show()});
 show();
}
function show(){
 clearInterval(tapTimer);
 nav.querySelectorAll('button').forEach(b=>b.classList.toggle('on',b.dataset.t==tab));
 ({chats:vChats,groups:vGroups,search:vSearch,fun:vFun,game:vGame,profile:vProfile})[tab]();
}
// ---- chats list
async function vChats(){
 main.innerHTML=`<h2>Chats</h2>${ticker()}<p class="mut" style="font-size:12px;margin:0 0 10px">Kisi bhi chat me <b>/help</b> likho - 🤖 Billi Bot mazedaar commands dega</p><div id="l"></div>`;
 const j=await api('/api/chats');
 const l=$('#l');if(!l)return;
 if(!j.chats||!j.chats.length){l.innerHTML='<p class="mut">Abhi koi chat nahi. Search tab me 🟢 online logon se baat shuru karo.</p>';return}
 l.innerHTML=j.chats.map((c,i)=>`<div class="item" data-i="${i}">${av(c.photo,c.user,c.online)}<div class="t"><b>${esc(c.user)}</b><small>${esc(c.last)}</small></div></div>`).join('');
 l.querySelectorAll('.item').forEach(e=>e.onclick=()=>{const c=j.chats[e.dataset.i];openChat('dm',c.user,c.user)});
}
function openChat(kind,target,title){cur={kind,target,title,last:0,reply:null,byId:{},init:false,tp:0};renderChat()}
const EMO=['😀','😂','🤣','😍','😎','🥺','😭','😡','🤡','💀','👻','🙈','😹','🐱','🐟','🔥','❤️','💔','👍','🙏','🎉','🍕','🥛','💩','🤝','😴','🤔','😏'];
const STK=['🐱','😹','🤡','💀','🔥','❤️','🎉','💩'];
function renderChat(){
 const c=cur;
 main.innerHTML=`<div class="top"><button id="bk">←</button><div style="flex:1;min-width:0"><b>${esc(c.title)}</b><small id="st" class="mut" style="display:block;height:14px"></small></div><button id="wb">🎨</button></div>
 <div class="msgs" id="msgs"></div>
 <div class="rp" id="rp" style="display:none"></div>
 <div class="ep" id="ep" style="display:none"><div class="eg" id="eg">${EMO.map(e=>`<span>${e}</span>`).join('')}</div>
  <div class="mut" style="font-size:11px;margin:6px 0 2px">Sticker (seedha send hota hai)</div><div class="eg st" id="es">${STK.map(e=>`<span>${e}</span>`).join('')}</div></div>
 <div class="inp"><label class="ic">🖼️<input type="file" id="fi" accept="image/*" multiple hidden></label><button class="ic" id="eb">😀</button>
 <input id="tx" placeholder="Message likho... (/help)" autocomplete="off"><button class="btn" id="sd">➤</button></div>`;
 $('#bk').onclick=()=>{cur=null;show()};
 $('#wb').onclick=wallPicker;
 $('#eb').onclick=()=>{const e=$('#ep');e.style.display=e.style.display==='none'?'block':'none'};
 $('#eg').onclick=e=>{if(e.target.tagName==='SPAN'){$('#tx').value+=e.target.textContent;$('#tx').focus()}};
 $('#es').onclick=e=>{if(e.target.tagName==='SPAN'){post({text:e.target.textContent});$('#ep').style.display='none'}};
 $('#msgs').onclick=e=>{
  if(e.target.tagName==='IMG')return viewer(e.target.src);
  const m=e.target.closest('.m');if(m&&!m.classList.contains('gone'))actions(m);
 };
 applyWall();
 $('#sd').onclick=sendText;
 $('#tx').onkeydown=e=>{if(e.key==='Enter')sendText()};
 $('#tx').oninput=()=>{const n=Date.now();if(cur===c&&n-c.tp>2500){c.tp=n;api('/api/typing',{kind:c.kind,target:c.target})}};
 $('#fi').onchange=async e=>{
  const fs=[...e.target.files];e.target.value='';
  for(const f of fs){
   if(f.type==='image/gif'){
    if(f.size>3000000){alert('GIF 3MB se choti rakho');continue}
    await post({img:await readURL(f)});
   }else await post({img:await shrink(f,1280,.8)});
  }
 };
 pull();
}
function mk(m){
 const d=document.createElement('div');d.dataset.id=m.id;
 const mine=m.sender===ME.username,bot=m.sender==='billibot';
 d.className='m'+(mine?' me':'')+(bot?' bot':'');
 if(m.deleted){d.classList.add('gone');d.textContent='🚫 Message delete ho gaya';return d}
 let h='';
 if(bot)h+='<b style="color:#d1c4e9">🤖 Billi Bot</b>';
 else if(!mine&&cur.kind==='g')h+=`<b style="color:${col(m.sender)}">${esc(m.sender)}</b>`;
 if(m.reply)h+=`<div class="q">${esc(m.reply)}</div>`;
 if(m.text){h+=(EMOJI_ONLY.test(m.text)&&m.text.length<=12)?`<div class="bg1">${esc(m.text)}</div>`:`<div>${esc(m.text)}</div>`}
 if(m.img)h+=`<img src="${esc(m.img)}">`;
 h+=`<small class="tm">${tm(m.ts)}</small><div class="rx"></div>`;
 d.innerHTML=h;return d;
}
function paintReacts(map){
 document.querySelectorAll('#msgs .m').forEach(el=>{
  const box=el.querySelector('.rx');if(!box)return;
  const r=map[el.dataset.id];
  box.innerHTML=r?Object.entries(r).map(([e,u])=>`<span class="${u.includes(ME.username)?'mine':''}">${e}${u.length>1?' '+u.length:''}</span>`).join(''):'';
 });
}
async function pull(){
 const c=cur;if(!c)return;
 const j=await api(`/api/msgs?kind=${c.kind}&target=${encodeURIComponent(c.target)}&after=${c.last}`);
 if(c!==cur||j.error)return;
 const box=$('#msgs');if(!box)return;
 const st=$('#st');
 if(st)st.textContent=(j.typing&&j.typing.length)?'✍️ '+j.typing.join(', ')+' likh raha hai...':(c.kind==='dm'?(j.online?'🟢 online':'⚫ offline'):'');
 const list=j.msgs||[],first=!c.init;c.init=true;
 const near=box.scrollHeight-box.scrollTop-box.clientHeight<150||first;
 let incoming=false;
 list.forEach(m=>{
  c.last=m.id;c.byId[m.id]=m;box.appendChild(mk(m));
  if(!first&&m.sender!==ME.username)incoming=true;
  if(!first&&/🎉|congrat/i.test(m.text||''))burst('🎉',12);
 });
 (j.gone||[]).forEach(id=>{
  const el=box.querySelector(`.m[data-id="${id}"]`);
  if(el&&!el.classList.contains('gone')){el.className='m gone';el.textContent='🚫 Message delete ho gaya'}
 });
 if(j.reacts)paintReacts(j.reacts);
 if(incoming)beep(880,.12);
 if(near&&(list.length||first))box.scrollTop=box.scrollHeight;
}
async function post(x){
 const c=cur;if(!c)return;
 const j=await api('/api/send',Object.assign({kind:c.kind,target:c.target,reply:c.reply||0},x));
 if(j.error)return alert(j.error);
 if(cur===c){c.reply=null;const r=$('#rp');if(r)r.style.display='none';pull();setTimeout(pull,700)}
}
function sendText(){
 const t=$('#tx').value.trim();if(!t)return;$('#tx').value='';
 if(/^https?:\/\/\S+$/.test(t)&&/(\.gif|\.png|\.jpe?g|\.webp)(\?|$)|giphy|tenor/i.test(t))post({img:t});
 else post({text:t});
}
function actions(el){
 const c=cur,id=+el.dataset.id,m=c.byId[id];if(!m)return;
 const d=document.createElement('div');d.id='wp';
 d.innerHTML=`<div class="sheet"><div class="row" style="justify-content:space-around;font-size:32px">${['❤️','😂','😮','😢','🔥','👍'].map(e=>`<span class="rb">${e}</span>`).join('')}</div>
 <div class="row"><button class="btn alt" style="flex:1" id="ar">↩ Reply</button><button class="btn alt" style="flex:1" id="ac">📋 Copy</button>${m.sender===ME.username?'<button class="btn alt" style="flex:1" id="ad">🗑 Delete</button>':''}</div></div>`;
 d.onclick=e=>{if(e.target===d)d.remove()};
 document.body.appendChild(d);
 d.querySelectorAll('.rb').forEach(b=>b.onclick=async()=>{
  d.remove();burst(b.textContent,10);await api('/api/react',{id,emoji:b.textContent});pull();
 });
 $('#ar').onclick=()=>{
  d.remove();c.reply=id;const r=$('#rp');
  r.innerHTML=`<span>↩ ${esc((m.text||'📷 Photo').slice(0,60))}</span><button class="ic" id="rx">✕</button>`;
  r.style.display='flex';$('#rx').onclick=()=>{c.reply=null;r.style.display='none'};$('#tx').focus();
 };
 $('#ac').onclick=async()=>{
  d.remove();const t=m.text||'';
  try{await navigator.clipboard.writeText(t)}catch(e){prompt('Copy karo:',t)}
 };
 const del=$('#ad');
 if(del)del.onclick=async()=>{d.remove();if(confirm('Sabke liye delete karein?')){await api('/api/delete',{id});pull()}};
}
// ---- image helpers
function readURL(f){return new Promise(r=>{const x=new FileReader();x.onload=()=>r(x.result);x.readAsDataURL(f)})}
function shrink(f,max,qlt){return new Promise(r=>{
 const im=new Image();im.onload=()=>{
  const k=Math.min(1,max/Math.max(im.width,im.height));
  const c=document.createElement('canvas');c.width=Math.round(im.width*k);c.height=Math.round(im.height*k);
  c.getContext('2d').drawImage(im,0,0,c.width,c.height);r(c.toDataURL('image/jpeg',qlt));
 };im.src=URL.createObjectURL(f);
})}
function viewer(src){
 const d=document.createElement('div');d.id='vw';
 d.innerHTML=`<img src="${esc(src)}"><div class="row"><a class="btn" download="bagarbilli.jpg" href="${esc(src)}">⬇ Save</a><button class="btn alt" id="vx">Close</button></div>`;
 d.onclick=e=>{if(e.target===d)d.remove()};
 document.body.appendChild(d);$('#vx').onclick=()=>d.remove();
}
// ---- chat wallpaper (funny patterns + gradients + apni photo)
const pat=(a,b,bg)=>`url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='96' height='96'><text x='6' y='40' font-size='30' opacity='.55'>${a}</text><text x='52' y='86' font-size='30' opacity='.55'>${b}</text></svg>") 0 0/96px 96px,${bg}`;
const WALLS=[
 ['Default',''],
 ['🐱 Billi',pat('🐱','🐾','#2a1747')],
 ['🐟 Machhli',pat('🐟','🥛','#0c3b5c')],
 ['🤡 Joker',pat('🤡','🎈','#4a1d5e')],
 ['🔥 Aag',pat('🔥','💥','#5a1a0c')],
 ['🍕 Pizza',pat('🍕','🧀','#5c3b0c')],
 ['👻 Bhoot',pat('👻','🎃','#16161e')],
 ['Sunset','linear-gradient(160deg,#ff7a1a,#c2185b,#4a148c)'],
 ['Ocean','linear-gradient(160deg,#00c6ff,#0072ff,#001f4d)'],
 ['Galaxy','radial-gradient(circle at 20% 20%,#7f00ff,transparent 50%),radial-gradient(circle at 80% 75%,#e100ff,transparent 45%),#0b0620'],
 ['Forest','linear-gradient(160deg,#134e5e,#71b280)'],
 ['Black','#000']
];
function wkey(){return 'bb_w_'+ME.username+'_'+cur.kind+'_'+cur.target}
function lget(k){try{return localStorage.getItem(k)||''}catch(e){return ''}}
function getWall(){return lget(wkey())||lget('bb_w_all_'+ME.username)}
function resolveWall(t){
 if(!t)return '';
 if(t.startsWith('data:'))return `url("${t}") center/cover`;
 if(t.startsWith('p:'))return (WALLS[+t.slice(2)]||['',''])[1];
 return t;
}
function applyWall(){const m=$('#msgs');if(m)m.style.background=resolveWall(getWall())}
function setWall(t,all){
 try{
  if(all)localStorage.removeItem(wkey());
  const k=all?'bb_w_all_'+ME.username:wkey();
  if(t)localStorage.setItem(k,t);else{localStorage.removeItem(k);if(all)localStorage.removeItem(wkey())}
 }catch(e){alert('Photo badi hai, dusri try karo')}
 applyWall();
}
function wallPicker(){
 const d=document.createElement('div');d.id='wp';
 d.innerHTML=`<div class="sheet" style="max-height:85%;overflow-y:auto"><b>🎨 Chat background</b>
 <div class="sw" id="sw"></div>
 <label class="row" style="gap:8px"><input type="checkbox" id="wall" style="width:20px"> Sab chats me lagao</label>
 <div class="row"><label class="btn" style="flex:1;text-align:center">📷 Apni photo lagao<input type="file" id="wf" accept="image/*" hidden></label>
 <button class="btn alt" id="wx">Close</button></div></div>`;
 d.onclick=e=>{if(e.target===d)d.remove()};
 document.body.appendChild(d);
 WALLS.forEach((w,i)=>{
  const s=document.createElement('div');s.className='s';s.textContent=w[0];s.style.background=w[1]||'#222';
  s.onclick=()=>{setWall(i?'p:'+i:'',$('#wall').checked);d.remove()};
  $('#sw').appendChild(s);
 });
 $('#wx').onclick=()=>d.remove();
 $('#wf').onchange=async e=>{const f=e.target.files[0];if(!f)return;setWall(await shrink(f,900,.65),$('#wall').checked);d.remove()};
}
// ---- groups
async function vGroups(){
 main.innerHTML=`<h2>Groups</h2>
 <div class="row"><input id="gn" placeholder="Naya group ka naam"><button class="btn" id="gc">Banao</button></div>
 <div class="row"><input id="gs" placeholder="Group search karo (join ke liye)"></div><div id="l"></div>`;
 $('#gc').onclick=async()=>{const j=await api('/api/group/create',{name:$('#gn').value});if(j.error)alert(j.error);else{$('#gn').value='';load()}};
 $('#gs').oninput=load;
 let list=[];
 async function load(){
  const j=await api('/api/groups?q='+encodeURIComponent($('#gs').value));
  list=j.groups||[];const l=$('#l');if(!l)return;
  l.innerHTML=list.length?list.map((g,i)=>`<div class="item"><div class="av">👥</div><div class="t"><b>${esc(g.name)}</b><small>${g.members} members</small></div>
   ${g.joined?`<button class="btn alt" data-a="add" data-i="${i}">+Add</button><button class="btn" data-a="open" data-i="${i}">Open</button>`:`<button class="btn" data-a="join" data-i="${i}">Join</button>`}</div>`).join(''):'<p class="mut">Koi group nahi</p>';
  l.querySelectorAll('button').forEach(b=>b.onclick=async()=>{
   const g=list[b.dataset.i],a=b.dataset.a;
   if(a==='open')openChat('g',g.id,g.name);
   else if(a==='join'){await api('/api/group/join',{id:g.id});openChat('g',g.id,g.name)}
   else{const u=prompt('Kis username ko add karna hai?');if(u){const j=await api('/api/group/add',{id:g.id,username:u});alert(j.error||'Add ho gaya');load()}}
  });
 }
 load();
}
// ---- search + online
function userItems(u){
 return u.map((x,i)=>`<div class="item" data-i="${i}">${av(x.photo,x.username,x.online)}<div class="t"><b>@${esc(x.username)}</b> <small style="display:inline;color:var(--acc)">${esc(x.level)}</small><small>${esc(x.bio)}</small></div><button class="btn">Message</button></div>`).join('');
}
async function vSearch(){
 main.innerHTML='<h2>Search</h2><div class="row"><input id="s" placeholder="Username ya bio se dhundo" autocapitalize="none"></div><div id="l"></div>';
 let t,res=[];
 const bind=()=>$('#l').querySelectorAll('.item').forEach(e=>e.onclick=()=>{const x=res[e.dataset.i];openChat('dm',x.username,x.username)});
 async function online(){
  const j=await api('/api/online');res=j.users||[];const l=$('#l');if(!l)return;
  l.innerHTML=res.length?'<p class="mut">🟢 Abhi online</p>'+userItems(res):'<p class="mut">Abhi koi aur online nahi. Naam se search karo.</p>';bind();
 }
 async function go(){
  const v=$('#s').value.trim();const l=$('#l');if(!l)return;
  if(!v)return online();
  const j=await api('/api/users?q='+encodeURIComponent(v));res=j.users||[];
  l.innerHTML=res.length?userItems(res):'<p class="mut">Koi nahi mila</p>';bind();
 }
 $('#s').oninput=()=>{clearTimeout(t);t=setTimeout(go,300)};
 online();
}
// ---- fun zone
const FORT=["Kal tumhe free ka khana milega... agar kisi aur ka bill pay karo to 🍕","Jaldi hi koi tumhe 'seen' karke ignore karega 🙈","Aaj ka din lucky hai - par WiFi nahi chalega 📶","Tumhari billi tumse zyada smart hai 🐱","Ek purana dost 'hi' bolega aur udhaar maangega 💸","Tumhara crush tumhe notice karega... galti se 😹","Is hafte neend poori hogi - sapne me 😴","Paise aayenge, par kharch hone ke liye 🤑"];
const JOKES=["Teacher: Tum late kyun aaye? Student: Sir, board par likha tha 'School ahead, go slow' 🐢","Wifi aur crush me same baat hai - dono 'connected' dikhte hain par net nahi milta 📶","Doctor: Aapko aaram chahiye. Patient: Wo to Monday ko bhi nahi milta 😴","Mobile 1% par bhi reply nahi dete, par crush ka message aaye to charger dhoondte hain 🔋"];
function vFun(){
 main.innerHTML=`<h2>Fun Zone 🤪</h2>
 <div class="card"><b>🐱 Billi Tap</b> <span class="mut" style="font-size:12px">sabse zyada tap karo, leaderboard me aao</span>
  <div style="text-align:center"><button id="tp" class="tapb">🐱</button><div class="big" style="padding:6px;margin:4px 0">Tumhare taps: <b id="tc">${ME.taps||0}</b></div></div>
  <div id="lb" class="mut">Leaderboard load ho raha...</div></div>
 <div class="card"><b>🔮 Bhavishyavani</b><div id="fo" class="big" style="font-size:16px;display:none"></div><button class="btn" id="fb">Meri kismat batao</button></div>
 <div class="card"><b>💘 Love Calculator</b><div class="row" style="margin-top:8px"><input id="l1" placeholder="Pehla naam"><input id="l2" placeholder="Dusra naam"></div><button class="btn" id="lv">Check karo</button><div id="lr" class="big" style="display:none"></div></div>
 <div class="card"><b>🎡 Kismat ka chakkar</b><input id="sp" style="margin:8px 0" value="Pizza, Chai, Sona, Padhai, Dance, Ghoomna"><div id="sr" class="big" style="display:none"></div><button class="btn" id="sb">Ghumao</button></div>
 <div class="card"><b>🎲 Quick</b><div class="row" style="margin-top:8px"><button class="btn alt" id="dc">🎲</button><button class="btn alt" id="fl">🪙</button><button class="btn alt" id="jk">😹 Joke</button><button class="btn alt" id="mw">🐱 Meow</button></div><div id="qr" class="big" style="display:none"></div></div>`;
 let pend=0,total=ME.taps||0;
 $('#tp').onclick=()=>{total++;pend++;$('#tc').textContent=total;if(total%10===0){meow();burst('🐾',4)}};
 async function flush(){
  if(pend>0){const n=Math.min(pend,40);pend-=n;const j=await api('/api/tap',{n});if(j.n!=null){ME.taps=j.n}}
  const l=await api('/api/leaderboard');const b=$('#lb');if(!b||!l.taps)return;
  const m=['🥇','🥈','🥉'];
  b.innerHTML='<b>🏆 Top Billi Tappers</b><br>'+(l.taps.map((x,i)=>`${m[i]||(i+1)+'.'} @${esc(x.user)} - ${x.n}`).join('<br>')||'Abhi koi nahi')+
   '<br><br><b>💬 Sabse bakchod (zyada messages)</b><br>'+(l.chat.map((x,i)=>`${m[i]||(i+1)+'.'} @${esc(x.user)} - ${x.n}`).join('<br>')||'Abhi koi nahi');
 }
 flush();tapTimer=setInterval(flush,3000);
 const out=(id,t)=>{const e=$(id);e.style.display='block';e.innerHTML=t};
 $('#fb').onclick=()=>{out('#fo',pick(FORT));burst('🔮',6)};
 $('#lv').onclick=()=>{
  const a=$('#l1').value.trim(),b=$('#l2').value.trim();if(!a||!b)return alert('Dono naam likho');
  const [x,y]=[a.toLowerCase(),b.toLowerCase()].sort();
  const p=([...(x+y)].reduce((s,c)=>s+c.charCodeAt(0),0)*7+13)%61+40;
  out('#lr',`💘 ${esc(a)} + ${esc(b)}<br><b style="font-size:32px;color:var(--acc)">${p}%</b>`);burst('❤️',12);
 };
 $('#sb').onclick=()=>{
  const items=$('#sp').value.split(',').map(s=>s.trim()).filter(Boolean);if(items.length<2)return alert('2 se zyada option likho');
  let n=0;const iv=setInterval(()=>{out('#sr','🎡 '+esc(pick(items)));beep(600+n*20,.05);if(++n>18){clearInterval(iv);out('#sr','🎉 <b>'+esc(pick(items))+'</b>');burst('🎉',10)}},90);
 };
 $('#dc').onclick=()=>out('#qr','🎲 '+(1+Math.floor(Math.random()*6)));
 $('#fl').onclick=()=>out('#qr','🪙 '+pick(['Heads (chit)','Tails (patt)']));
 $('#jk').onclick=()=>out('#qr',esc(pick(JOKES)));
 $('#mw').onclick=()=>{meow();out('#qr','meow meow 🐱');burst('🐟',8)};
}
// ---- profile
async function vProfile(){
 ME=await api('/api/me');
 const nxt=ME.next?`${ME.msgs}/${ME.next} messages agle level tak`:'Max level! 🌟';
 main.innerHTML=`<h2>Profile</h2><div style="text-align:center;margin-bottom:12px">
 <div id="pv" style="display:inline-block;transform:scale(1.8);margin:20px 0">${av(ME.photo,ME.username,true)}</div>
 <div><b>@${esc(ME.username)}</b></div>
 <div class="big" style="font-size:16px;padding:8px">${esc(ME.level)}<br><small class="mut">${nxt} • ${ME.taps||0} taps</small></div>
 <label class="btn alt" style="display:inline-block">📷 Photo badlo<input type="file" id="pf" accept="image/*" hidden></label></div>
 <textarea id="bio" rows="3" maxlength="200" placeholder="Bio likho...">${esc(ME.bio)}</textarea>
 <div class="mut" style="margin-top:10px">App ka rang:</div><div class="th" id="th"></div>
 <label class="row" style="gap:8px"><input type="checkbox" id="snd" style="width:20px" ${soundOn?'checked':''}> Message sound</label>
 <div class="row"><button class="btn" style="flex:1" id="sv">Save</button><button class="btn alt" id="lo">Logout</button></div>`;
 THEMES.forEach((t,i)=>{const e=document.createElement('i');e.style.background=`linear-gradient(135deg,${t[0]},${t[1]})`;e.onclick=()=>{setTheme(i);burst('🎨',6)};$('#th').appendChild(e)});
 $('#snd').onchange=e=>{soundOn=e.target.checked;localStorage.setItem('bb_snd',soundOn?'1':'0')};
 let photo=null;
 $('#pf').onchange=e=>{
  const f=e.target.files[0];if(!f)return;
  const im=new Image();im.onload=()=>{
   const c=document.createElement('canvas');c.width=c.height=256;const x=c.getContext('2d');
   const s=Math.min(im.width,im.height);x.drawImage(im,(im.width-s)/2,(im.height-s)/2,s,s,0,0,256,256);
   photo=c.toDataURL('image/jpeg',.8);$('#pv').innerHTML=av(photo,ME.username,true);
  };im.src=URL.createObjectURL(f);
 };
 $('#sv').onclick=async()=>{await api('/api/profile',{bio:$('#bio').value,photo});ME=await api('/api/me');alert('Save ho gaya');burst('✅',6)};
 $('#lo').onclick=logout;
}
// ---- truth & dare
function vGame(){
 if(room)return renderGame();
 main.innerHTML=`<h2>Truth &amp; Dare 🎭</h2><p class="mut">2 se 4 dost ek room me khel sakte hain.</p>
 <button class="btn" id="gc" style="margin-bottom:14px">Naya room banao</button>
 <div class="row"><input id="code" placeholder="Room code (4 ank)" inputmode="numeric"><button class="btn" id="gj">Join</button></div>`;
 $('#gc').onclick=async()=>{const j=await api('/api/game/create',{});if(j.code){room=j;renderGame()}};
 $('#gj').onclick=async()=>{const j=await api('/api/game/join',{code:$('#code').value.trim()});if(j.error)alert(j.error);else{room=j;renderGame()}};
}
async function gact(action,value){const j=await api('/api/game/act',{code:room.code,action,value});if(j.code){room=j;renderGame()}}
function renderGame(){
 if(tab!=='game')return;
 const r=room,me=ME.username,cu=r.players[r.turn];
 let body='';
 if(r.phase==='lobby'){
  body=`<div class="big">Room code: <b style="color:var(--acc)">${r.code}</b></div><p class="mut">Dosto ko ye code do. Players (${r.players.length}/4):</p>
  ${r.players.map(p=>`<div class="item"><b>@${esc(p)}</b></div>`).join('')}
  ${me===r.host?(r.players.length>=2?'<button class="btn" id="a1">Game shuru karo</button>':'<p class="mut">Kam se kam 2 players chahiye</p>'):'<p class="mut">Host ke start karne ka wait karo...</p>'}`;
 }else if(r.phase==='choose'){
  body=`<div class="big">Baari: <b>@${esc(cu)}</b></div>`+(cu===me?'<div class="row"><button class="btn" style="flex:1" id="a2">Truth 😇</button><button class="btn alt" style="flex:1" id="a3">Dare 😈</button></div>':'<p class="mut" style="text-align:center">@'+esc(cu)+' Truth ya Dare chun raha hai...</p>');
 }else if(r.phase==='ask'){
  body=`<div class="big">@${esc(cu)} ne <b style="color:var(--acc)">${r.mode.toUpperCase()}</b> chuna</div>`+(cu===me?'<p class="mut" style="text-align:center">Dusre players tumse sawaal / dare puchh rahe hain...</p>':`<div class="row"><input id="qs" placeholder="Apna ${r.mode} likho"><button class="btn" id="a4">Bhejo</button></div><button class="btn alt" id="a5" style="width:100%">🎲 Random do</button>`);
 }else{
  body=`<div class="big"><small class="mut">@${esc(r.asker)} ne puchha (${r.mode})</small><br>${esc(r.question)}</div>`+(cu===me?'<div class="row"><input id="an" placeholder="Jawab likho (ya sirf Done)"><button class="btn" id="a6">Done</button></div>':'<p class="mut" style="text-align:center">@'+esc(cu)+' jawab de raha hai...</p>');
 }
 const lg=r.log.length?'<h3>Pichle round</h3>'+r.log.slice().reverse().map(x=>`<div class="item"><div class="t"><b>@${esc(x.player)}</b> • ${x.mode}<small style="white-space:normal">${esc(x.q)}</small><small style="white-space:normal;color:var(--acc)">${esc(x.a)}</small></div></div>`).join(''):'';
 const focus=document.activeElement&&document.activeElement.id,val=document.activeElement&&document.activeElement.value;
 main.innerHTML=`<div class="top"><button id="bk">←</button><b>Room ${r.code}</b></div>${body}${lg}`;
 const on=(id,f)=>{const e=$('#'+id);if(e)e.onclick=f};
 on('bk',()=>{room=null;show()});
 on('a1',()=>gact('start'));on('a2',()=>gact('choose','truth'));on('a3',()=>gact('choose','dare'));
 on('a4',()=>gact('ask',$('#qs').value));on('a5',()=>gact('ask','__random__'));on('a6',()=>gact('done',$('#an').value));
 if(focus&&$('#'+focus)&&val){$('#'+focus).value=val;$('#'+focus).focus()}
}
async function pullGame(){
 if(!room)return;
 const j=await api('/api/game?code='+room.code);
 if(j.error){room=null;if(tab==='game')show();return}
 const typing=document.activeElement&&document.activeElement.tagName==='INPUT'&&document.activeElement.value;
 if(JSON.stringify(j)!==JSON.stringify(room)){room=j;if(!typing)renderGame()}
}
setInterval(()=>{if(!ME)return;if(cur)pull();else if(tab==='game')pullGame()},2000);
// ---- music player
const au=$('#au');let songs=[],si=-1;
$('#fab').onclick=()=>$('#mp').classList.toggle('on');
$('#mf').onchange=e=>{
 [...e.target.files].forEach(f=>songs.push({n:f.name.replace(/\.[^.]+$/,''),u:URL.createObjectURL(f)}));
 e.target.value='';drawPl();if(si<0&&songs.length)play(0);
};
function drawPl(){$('#pl').innerHTML=songs.length?songs.map((s,i)=>`<div class="${i===si?'cur':''}" data-i="${i}">${esc(s.n)}</div>`).join(''):'Koi gaana nahi';
 $('#pl').querySelectorAll('div[data-i]').forEach(d=>d.onclick=()=>play(+d.dataset.i))}
function play(i){if(!songs.length)return;si=(i+songs.length)%songs.length;au.src=songs[si].u;au.play();drawPl()}
$('#mpp').onclick=()=>{if(si<0)return play(0);au.paused?au.play():au.pause()};
$('#mnext').onclick=()=>play(si+1);$('#mprev').onclick=()=>play(si-1);
au.onplay=()=>$('#mpp').textContent='⏸';au.onpause=()=>$('#mpp').textContent='▶';
au.onended=()=>play(si+1);
</script></body></html>"""


@app.get("/")
def index():
    return Response(PAGE, mimetype="text/html")


if __name__ == "__main__":
    init()
    print("Bagar Billi v3 chalu hai -> http://127.0.0.1:5000")
    app.run(host="0.0.0.0", port=5000, debug=False, threaded=True)
