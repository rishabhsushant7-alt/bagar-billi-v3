# -*- coding: utf-8 -*-
# BAGAR BILLI v3 (Funny Edition) - Powered by Symiiii - DEPLOY READY
# Original logic preserved + Postgres (Supabase) support + Frontend route

import os, re, time, random, secrets
from flask import Flask, request, jsonify, Response, render_template
from werkzeug.security import generate_password_hash, check_password_hash

BASE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE, "bagarbilli.db")
DATABASE_URL = os.environ.get("DATABASE_URL")
USE_PG = bool(DATABASE_URL)

if USE_PG:
    import psycopg2
    import psycopg2.extras
    if DATABASE_URL.startswith("postgres://"):
        DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

app = Flask(__name__, template_folder="templates")
app.config["MAX_CONTENT_LENGTH"] = 8 * 1024 * 1024

rooms = {}
seen = {}
typing = {}
BOT = "billibot"

def get_conn():
    if USE_PG:
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        return conn
    else:
        import sqlite3
        c = sqlite3.connect(DB_PATH, timeout=15)
        c.row_factory = sqlite3.Row
        return c

def q(sql, args=(), one=False, commit=False):
    exec_sql = sql
    if USE_PG:
        exec_sql = re.sub(r'\?', '%s', sql)
    conn = get_conn()
    try:
        if USE_PG:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            try:
                cur.execute(exec_sql, args)
            except Exception as e:
                msg = str(e).lower()
                if "duplicate" in msg or "unique" in msg or "conflict" in msg:
                    conn.rollback()
                    if "into taps" in exec_sql.lower():
                        cur.execute(exec_sql + " on conflict (username) do nothing", args)
                    elif "into members" in exec_sql.lower():
                        cur.execute(exec_sql + " on conflict do nothing", args)
                    elif "into sessions" in exec_sql.lower():
                        cur.execute(exec_sql + " on conflict (token) do nothing", args)
                    else:
                        try:
                            cur.execute(exec_sql + " on conflict do nothing", args)
                        except:
                            pass
                else:
                    raise
            if commit:
                conn.commit()
                cur.close()
                return None
            rows = cur.fetchall()
            cur.close()
            if one:
                return rows[0] if rows else None
            return rows
        else:
            cur = conn.execute(exec_sql, args)
            if commit:
                conn.commit()
                lid = cur.lastrowid
                conn.close()
                return lid
            rows = cur.fetchall()
            conn.close()
            if one:
                return rows[0] if rows else None
            return rows
    except Exception as e:
        try: conn.rollback()
        except: pass
        try: conn.close()
        except: pass
        if USE_PG and "already exists" in str(e).lower():
            return None
        if USE_PG and commit and ("duplicate" in str(e).lower() or "unique" in str(e).lower()):
            return None
        raise e
    finally:
        try: conn.close()
        except: pass

def init():
    if USE_PG:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""
        create table if not exists users(username text primary key, pw text, bio text default '', photo text default '');
        create table if not exists sessions(token text primary key, username text);
        create table if not exists groups(id serial primary key, name text unique, owner text);
        create table if not exists members(gid integer, username text, primary key(gid, username));
        create table if not exists messages(id serial primary key, key text, sender text, text text, img text, ts bigint, reply text default '', deleted integer default 0);
        create table if not exists reacts(mid integer, username text, emoji text, primary key(mid, username));
        create table if not exists taps(username text primary key, n integer default 0);
        create index if not exists ix_msg on messages(key, id);
        """)
        conn.commit()
        cur.close()
        conn.close()
    else:
        q("create table if not exists users(username text primary key, pw text, bio text default '', photo text default '')", commit=True)
        q("create table if not exists sessions(token text primary key, username text)", commit=True)
        q("create table if not exists groups(id integer primary key autoincrement, name text unique, owner text)", commit=True)
        q("create table if not exists members(gid integer, username text, primary key(gid, username))", commit=True)
        q("create table if not exists messages(id integer primary key autoincrement, key text, sender text, text text, img text, ts integer, reply text default '', deleted integer default 0)", commit=True)
        q("create table if not exists reacts(mid integer, username text, emoji text, primary key(mid, username))", commit=True)
        q("create table if not exists taps(username text primary key, n integer default 0)", commit=True)
        q("create index if not exists ix_msg on messages(key, id)", commit=True)

def need():
    t = request.headers.get("X-Token", "")
    if not t: return None
    r = q("select username from sessions where token=?", (t,), one=True)
    if not r: return None
    uname = r["username"] if isinstance(r, dict) or hasattr(r, "__getitem__") else None
    try:
        if isinstance(r, dict): uname = r.get("username")
        else: uname = r["username"]
    except:
        try: uname = r[0]
        except: uname = None
    if uname: seen[uname] = time.time()
    return uname

def unauth(): return jsonify(error="login"), 401
def is_online(u): return (time.time() - seen.get(u, 0)) < 25
def key_access(u, key):
    if key.startswith("dm:"): return u in key.split(":")[1:]
    if key.startswith("g:"): return q("select 1 from members where gid=? and username=?", (key[2:], u), one=True) is not None
    return False
def chat_key(u, kind, target):
    if kind == "dm":
        if target and target!= BOT and q("select 1 from users where username=?", (target,), one=True):
            return "dm:" + ":".join(sorted([u, target]))
    elif kind == "g":
        if q("select 1 from members where gid=? and username=?", (target, u), one=True):
            return "g:" + str(target)
    return None

LEVELS = [(0, "Bachha Billi 🐾"), (30, "Gali ki Billi 🐈"), (150, "Sher Billi 🦁"), (500, "Billi King 👑"), (1500, "Billi Bhagwan 🌟")]
def level_of(n):
    name, nxt = LEVELS[0][1], LEVELS[1][0]
    for i, (th, nm) in enumerate(LEVELS):
        if n >= th:
            name = nm
            nxt = LEVELS[i + 1][0] if i + 1 < len(LEVELS) else None
    return name, nxt
def msg_count(u):
    r = q("select count(*) c from messages where sender=? and deleted=0", (u,), one=True)
    if not r: return 0
    if isinstance(r, dict): return r.get("c",0) or r.get("count",0) or 0
    try: return r["c"]
    except: return r[0]

@app.get("/")
def home():
    return render_template("index.html")

@app.get("/api/health")
def health():
    return jsonify(ok=True, mode="pg" if USE_PG else "sqlite", online=len([k for k in seen if is_online(k)]))

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
    else:
        pw_hash = row["pw"] if isinstance(row, dict) else None
        try:
            if isinstance(row, dict): pw_hash = row.get("pw")
            else: pw_hash = row["pw"]
        except: pw_hash = row[1]
        if not check_password_hash(pw_hash, p):
            return jsonify(error="Password galat hai"), 403
    t = secrets.token_hex(16)
    q("insert into sessions values(?,?)", (t, u), commit=True)
    seen[u] = time.time()
    return jsonify(token=t, username=u)

@app.get("/api/me")
def me():
    u = need()
    if not u: return unauth()
    r = q("select username,bio,photo from users where username=?", (u,), one=True)
    if not r: return unauth()
    rd = dict(r) if not isinstance(r, dict) else r
    n = msg_count(u)
    rd["level"], rd["next"] = level_of(n)
    rd["msgs"] = n
    tr = q("select n from taps where username=?", (u,), one=True)
    rd["taps"] = tr["n"] if tr and isinstance(tr, dict) else (tr[0] if tr else 0)
    if isinstance(tr, dict): rd["taps"] = tr.get("n",0)
    return jsonify(rd)

@app.post("/api/profile")
def profile():
    u = need()
    if not u: return unauth()
    d = request.get_json(force=True, silent=True) or {}
    q("update users set bio=? where username=?", ((d.get("bio") or "")[:200], u), commit=True)
    ph = d.get("photo")
    if ph and ph.startswith("data:image/") and len(ph) < 400000:
        q("update users set photo=? where username=?", (ph, u), commit=True)
    return jsonify(ok=True)

def user_row(r):
    x = dict(r) if not isinstance(r, dict) else dict(r)
    x["online"] = is_online(x["username"])
    x["level"] = level_of(msg_count(x["username"]))[0]
    return x

@app.get("/api/users")
def users():
    u = need()
    if not u: return unauth()
    s = (request.args.get("q") or "").strip().lower()
    if not s: return jsonify(users=[])
    like = "%" + s + "%"
    rows = q("select username,bio,photo from users where (username like? or lower(bio) like?) and username<>? limit 30", (like, like, u))
    return jsonify(users=[user_row(r) for r in rows])

@app.get("/api/online")
def online():
    u = need()
    if not u: return unauth()
    names = [n for n in list(seen) if n!= u and is_online(n)][:30]
    out = []
    for n in names:
        r = q("select username,bio,photo from users where username=?", (n,), one=True)
        if r: out.append(user_row(r))
    return jsonify(users=out)

JOKES = ["Teacher: Tum late kyun aaye? Student: Sir, board par likha tha 'School ahead, go slow' 🐢","Billi ne sher se kaha: Tu bhi meri hi family hai, bas thoda bada hai 🦁","Wifi aur crush me same baat hai - dono 'connected' dikhte hain par net nahi milta 📶","Doctor: Aapko aaram chahiye. Patient: Wo to Monday ko bhi nahi milta 😴","Maths ki book itni sad kyun thi? Kyunki uske paas bahut saari problems thi 📚","Mobile 1% par bhi reply nahi dete, aur crush ka message aaye to charger dhoondte hain 🔋"]
ROASTS = ["{n} ka WiFi signal bhi tumse zyada serious hai 📶","{n} itna slow hai ki loading bhi 'Rukiye' bol deti hai 🐢","{n} ki battery aur akal dono 1% par chalti hain 🔋","{n} ki selfie dekh kar camera ne bhi 'Retake' maang liya 📸","{n} ka dimaag Airplane Mode me hi rehta hai ✈️","{n} bolta kam hai, bakchodi zyada karta hai 🤡"]
BALL = ["Haan bilkul! ✅", "Bilkul nahi ❌", "Billi se pooch ke batata hoon 🐱", "Shayad... 🤔","Pakka! 💯", "Dobara pooch, mood nahi hai 😴", "Sapne me haan, asli me na 😹"]
HELP = ("🤖 Billi Bot commands:\n/joke - joke\n/roast [naam] - roast\n/dice - pasa\n/flip - sikka\n/8ball sawaal - jawab\n/love naam1 naam2 - pyaar %\n/meow - meow 🐱")

def bot_reply(u, text):
    parts = text.split(None, 1)
    cmd = parts[0].lower()
    arg = parts[1].strip() if len(parts) > 1 else ""
    if cmd == "/help": return HELP
    if cmd == "/joke": return random.choice(JOKES)
    if cmd == "/roast": return random.choice(ROASTS).format(n=arg or u)
    if cmd == "/dice": return "🎲 Pasa bola: %d" % random.randint(1, 6)
    if cmd == "/flip": return "🪙 " + random.choice(["Heads (chit)", "Tails (patt)"])
    if cmd == "/8ball": return "🎱 " + random.choice(BALL)
    if cmd == "/meow": return "meow meow meow 🐱🐟"
    if cmd == "/love":
        names = arg.replace(",", " ").split()
        if len(names) < 2: return "Aise likho: /love Rahul Priya 💘"
        a, b = sorted([names[0].lower(), names[1].lower()])
        pct = (sum(map(ord, a + b)) * 7 + 13) % 61 + 40
        return "💘 %s + %s = %d%% match!" % (names[0], names[1], pct)
    return None

@app.get("/api/chats")
def chats():
    u = need()
    if not u: return unauth()
    rows = q("select key, max(id) mid from messages where key like 'dm:%' group by key order by mid desc")
    out = []
    for r in rows:
        rd = dict(r) if not isinstance(r, dict) else r
        k = rd.get("key") or r[0]
        mid = rd.get("mid") or r[1]
        parts = k.split(":")
        if u in parts[1:]:
            other = parts[2] if parts[1] == u else parts[1]
            last = q("select text,img,deleted from messages where id=?", (mid,), one=True)
            if not last: continue
            ld = dict(last) if not isinstance(last, dict) else last
            ou = q("select photo from users where username=?", (other,), one=True)
            txt = "🚫 delete hua" if ld.get("deleted") else (ld.get("text") or "📷 Photo")
            photo = ""
            if ou:
                od = dict(ou) if not isinstance(ou, dict) else ou
                photo = od.get("photo","")
            out.append(dict(user=other, photo=photo, last=str(txt)[:60], online=is_online(other)))
    return jsonify(chats=out)

@app.get("/api/msgs")
def msgs():
    u = need()
    if not u: return unauth()
    kind, target = request.args.get("kind"), request.args.get("target")
    key = chat_key(u, kind, target)
    if not key: return jsonify(error="no access"), 403
    try: after = int(request.args.get("after") or 0)
    except: after = 0
    rows = q("select id,sender,text,img,ts,reply,deleted from messages where key=? and id>? order by id limit 100", (key, after))
    recent = q("select id,deleted from messages where key=? order by id desc limit 60", (key,))
    ids = []; gone = []
    for r in recent:
        rd = dict(r) if not isinstance(r, dict) else r
        iid = rd.get("id")
        ids.append(iid)
        if rd.get("deleted"): gone.append(iid)
    reacts = {}
    if ids:
        ph = ",".join(["?"]*len(ids))
        rr = q(f"select mid,username,emoji from reacts where mid in ({ph})", tuple(ids))
        for r in rr:
            rd = dict(r) if not isinstance(r, dict) else r
            reacts.setdefault(rd["mid"], {}).setdefault(rd["emoji"], []).append(rd["username"])
    now = time.time()
    typ = [t for t, ts in typing.get(key, {}).items() if now - ts < 4 and t!= u]
    clean_rows = [dict(r) if not isinstance(r, dict) else r for r in rows]
    return jsonify(msgs=clean_rows, gone=gone, reacts=reacts, typing=typ, online=is_online(target) if kind == "dm" else None)

@app.post("/api/send")
def send():
    u = need()
    if not u: return unauth()
    d = request.get_json(force=True, silent=True) or {}
    key = chat_key(u, d.get("kind"), d.get("target"))
    if not key: return jsonify(error="no access"), 403
    text = (d.get("text") or "")[:2000]
    img = d.get("img") or ""
    if img and not (img.startswith("data:image/") or img.startswith("http")): img = ""
    if len(img) > 4000000: return jsonify(error="Image bahut badi hai"), 400
    if not text and not img: return jsonify(error="empty"), 400
    reply = ""
    try: rid = int(d.get("reply") or 0)
    except: rid = 0
    if rid:
        rr = q("select sender,text from messages where id=? and key=?", (rid, key), one=True)
        if rr:
            rrd = dict(rr) if not isinstance(rr, dict) else rr
            reply = rrd.get("sender","") + ": " + ((rrd.get("text") or "📷 Photo")[:60])
    now = int(time.time())
    q("insert into messages(key,sender,text,img,ts,reply,deleted) values(?,?,?,?,?,?,0)", (key, u, text, img, now, reply), commit=True)
    if text.startswith("/"):
        out = bot_reply(u, text)
        if out:
            q("insert into messages(key,sender,text,img,ts,reply,deleted) values(?,?,?,?,?,?,0)", (key, BOT, out, "", now, ""), commit=True)
    typing.get(key, {}).pop(u, None)
    return jsonify(ok=True)

@app.post("/api/typing")
def typing_ping():
    u = need()
    if not u: return unauth()
    d = request.get_json(force=True, silent=True) or {}
    key = chat_key(u, d.get("kind"), d.get("target"))
    if key: typing.setdefault(key, {})[u] = time.time()
    return jsonify(ok=True)

@app.post("/api/react")
def react():
    u = need()
    if not u: return unauth()
    d = request.get_json(force=True, silent=True) or {}
    emoji = (d.get("emoji") or "")[:8]
    m = q("select id,key from messages where id=?", (d.get("id"),), one=True)
    if not m or not emoji: return jsonify(error="no access"), 403
    md = dict(m) if not isinstance(m, dict) else m
    if not key_access(u, md.get("key")): return jsonify(error="no access"), 403
    cur = q("select emoji from reacts where mid=? and username=?", (md["id"], u), one=True)
    if cur:
        cd = dict(cur) if not isinstance(cur, dict) else cur
        if cd.get("emoji") == emoji:
            q("delete from reacts where mid=? and username=?", (md["id"], u), commit=True)
            return jsonify(ok=True)
    if USE_PG:
        q("insert into reacts values(?,?,?) on conflict (mid,username) do update set emoji=excluded.emoji", (md["id"], u, emoji), commit=True)
    else:
        q("insert or replace into reacts values(?,?,?)", (md["id"], u, emoji), commit=True)
    return jsonify(ok=True)

@app.post("/api/delete")
def delete_msg():
    u = need()
    if not u: return unauth()
    d = request.get_json(force=True, silent=True) or {}
    q("update messages set deleted=1, text='', img='', reply='' where id=? and sender=?", (d.get("id"), u), commit=True)
    return jsonify(ok=True)

@app.post("/api/group/create")
def gcreate():
    u = need()
    if not u: return unauth()
    d = request.get_json(force=True, silent=True) or {}
    name = (d.get("name") or "").strip()[:30]
    if len(name) < 2: return jsonify(error="Group ka naam likho"), 400
    if q("select 1 from groups where lower(name)=lower(?)", (name,), one=True):
        return jsonify(error="Ye naam le liya gaya hai"), 400
    gid = q("insert into groups(name,owner) values(?,?)", (name, u), commit=True)
    if USE_PG:
        r = q("select id from groups where name=?", (name,), one=True)
        gid = dict(r)["id"] if r else gid
    q("insert into members values(?,?)", (gid, u), commit=True)
    return jsonify(id=gid)

@app.get("/api/groups")
def glist():
    u = need()
    if not u: return unauth()
    s = (request.args.get("q") or "").strip()
    if s: rows = q("select * from groups where name like? limit 30", ("%" + s + "%",))
    else: rows = q("select g.* from groups g join members m on m.gid=g.id where m.username=?", (u,))
    out = []
    for g in rows:
        gd = dict(g) if not isinstance(g, dict) else g
        gid = gd.get("id")
        nrow = q("select count(*) c from members where gid=?", (gid,), one=True)
        n = 0
        if nrow:
            nd = dict(nrow) if not isinstance(nrow, dict) else nrow
            n = nd.get("c",0) or nd.get("count",0)
        j = q("select 1 from members where gid=? and username=?", (gid, u), one=True) is not None
        out.append(dict(id=gid, name=gd.get("name"), members=n, joined=j))
    return jsonify(groups=out)

@app.post("/api/group/join")
def gjoin():
    u = need()
    if not u: return unauth()
    d = request.get_json(force=True, silent=True) or {}
    if not q("select 1 from groups where id=?", (d.get("id"),), one=True):
        return jsonify(error="group nahi mila"), 404
    q("insert into members values(?,?)", (d.get("id"), u), commit=True)
    return jsonify(ok=True)

@app.post("/api/group/add")
def gadd():
    u = need()
    if not u: return unauth()
    d = request.get_json(fo
