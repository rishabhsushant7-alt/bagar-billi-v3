# -*- coding: utf-8 -*-
import os, re, time, random, secrets
from flask import Flask, request, jsonify, Response
from werkzeug.security import generate_password_hash, check_password_hash

DATABASE_URL = os.environ.get("DATABASE_URL")
USE_PG = bool(DATABASE_URL)

if USE_PG:
    import psycopg2, psycopg2.extras
    if DATABASE_URL.startswith("postgres://"):
        DATABASE_URL = DATABASE_URL.replace("postgres://","postgresql://",1)
else:
    import sqlite3

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE, "bagarbilli.db")
app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 8*1024*1024
rooms, seen, typing = {}, {}, {}
BOT="billibot"

def get_conn():
    if USE_PG: return psycopg2.connect(DATABASE_URL)
    c=sqlite3.connect(DB,timeout=15)
    c.row_factory=sqlite3.Row
    return c

def q(sql, args=(), one=False, commit=False):
    _sql=sql
    if USE_PG:
        _sql=_sql.replace("?","%s")
        _sql=_sql.replace("integer primary key autoincrement","SERIAL PRIMARY KEY")
        if "insert or ignore into members values" in _sql.lower():
            _sql="insert into members (gid,username) values(%s,%s) ON CONFLICT DO NOTHING"
        elif "insert or ignore into taps values" in _sql.lower():
            _sql="insert into taps (username,n) values(%s,0) ON CONFLICT (username) DO NOTHING"
        elif "insert or replace into reacts" in _sql.lower():
            _sql=_sql.replace("insert or replace into reacts values","insert into reacts values")
            _sql+=" ON CONFLICT (mid,username) DO UPDATE SET emoji=EXCLUDED.emoji"
        else:
            _sql=_sql.replace("insert or ignore","insert").replace("insert or replace","insert")
    conn=get_conn()
    try:
        cur=conn.cursor(cursor_factory=psycopg2.extras.DictCursor) if USE_PG else conn.cursor()
        cur.execute(_sql, args)
        if commit:
            conn.commit()
            return 1
        rows=cur.fetchall()
        return (rows[0] if rows else None) if one else rows
    finally:
        try: cur.close()
        except: pass
        conn.close()

def init():
    q("create table if not exists users(username text primary key, pw text, bio text default '', photo text default '')",commit=True)
    q("create table if not exists sessions(token text primary key, username text)",commit=True)
    if USE_PG:
        q("create table if not exists groups(id SERIAL PRIMARY KEY, name text unique, owner text)",commit=True)
        q("create table if not exists messages(id SERIAL PRIMARY KEY, key text, sender text, text text, img text, ts integer, reply text default '', deleted integer default 0)",commit=True)
    else:
        q("create table if not exists groups(id integer primary key autoincrement, name text unique, owner text)",commit=True)
        q("create table if not exists messages(id integer primary key autoincrement, key text, sender text, text text, img text, ts integer, reply text default '', deleted integer default 0)",commit=True)
    q("create table if not exists members(gid integer, username text, primary key(gid, username))",commit=True)
    q("create table if not exists reacts(mid integer, username text, emoji text, primary key(mid, username))",commit=True)
    q("create table if not exists taps(username text primary key, n integer default 0)",commit=True)
    q("create index if not exists ix_msg on messages(key, id)",commit=True)

init()

def need():
    t=request.headers.get("X-Token","")
    r=q("select username from sessions where token=?",(t,),one=True)
    if r:
        seen[r["username"]]=time.time()
        return r["username"]
    return None
def unauth(): return jsonify(error="login"),401
def is_online(u): return (time.time()-seen.get(u,0))<25
def key_access(u,key):
    if key.startswith("dm:"): return u in key.split(":")[1:]
    if key.startswith("g:"): return q("select 1 from members where gid=? and username=?",(key[2:],u),one=True) is not None
    return False
def chat_key(u,kind,target):
    if kind=="dm":
        if target and target!=BOT and q("select 1 from users where username=?",(target,),one=True):
            return "dm:"+":".join(sorted([u,target]))
    elif kind=="g":
        if q("select 1 from members where gid=? and username=?",(target,u),one=True):
            return "g:"+str(target)
    return None

LEVELS=[(0,"Bachha Billi 🐾"),(30,"Gali ki Billi 🐈"),(150,"Sher Billi 🦁"),(500,"Billi King 👑"),(1500,"Billi Bhagwan 🌟")]
def level_of(n):
    name,nxt=LEVELS[0][1],LEVELS[1][0]
    for i,(th,nm) in enumerate(LEVELS):
        if n>=th:
            name=nm
            nxt=LEVELS[i+1][0] if i+1<len(LEVELS) else None
    return name,nxt
def msg_count(u): return q("select count(*) c from messages where sender=? and deleted=0",(u,),one=True)["c"]

@app.post("/api/auth")
def auth():
    d=request.get_json(force=True,silent=True) or {}
    u=(d.get("username") or "").strip().lower()
    p=d.get("password") or ""
    if not re.fullmatch(r"[a-z0-9_]{3,20}",u) or u==BOT:
        return jsonify(error="Username 3-20 akshar: a-z, 0-9, _"),400
    if len(p)<4: return jsonify(error="Password kam se kam 4 akshar"),400
    row=q("select * from users where username=?",(u,),one=True)
    if row is None:
        q("insert into users(username,pw) values(?,?)",(u,generate_password_hash(p)),commit=True)
    elif not check_password_hash(row["pw"],p):
        return jsonify(error="Password galat hai"),403
    t=secrets.token_hex(16)
    q("insert into sessions values(?,?)",(t,u),commit=True)
    seen[u]=time.time()
    return jsonify(token=t,username=u)

@app.get("/api/me")
def me():
    u=need()
    if not u: return unauth()
    r=dict(q("select username,bio,photo from users where username=?",(u,),one=True))
    n=msg_count(u)
    r["level"],r["next"]=level_of(n)
    r["msgs"]=n
    t=q("select n from taps where username=?",(u,),one=True)
    r["taps"]=t["n"] if t else 0
    return jsonify(r)

@app.post("/api/profile")
def profile():
    u=need()
    if not u: return unauth()
    d=request.get_json(force=True,silent=True) or {}
    q("update users set bio=? where username=?",((d.get("bio") or "")[:200],u),commit=True)
    ph=d.get("photo")
    if ph and ph.startswith("data:image/") and len(ph)<400000:
        q("update users set photo=? where username=?",(ph,u),commit=True)
    return jsonify(ok=True)

def user_row(r):
    x=dict(r); x["online"]=is_online(x["username"]); x["level"]=level_of(msg_count(x["username"]))[0]; return x

@app.get("/api/users")
def users():
    u=need()
    if not u: return unauth()
    s=(request.args.get("q") or "").strip().lower()
    if not s: return jsonify(users=[])
    like="%"+s+"%"; rows=q("select username,bio,photo from users where (username like? or lower(bio) like?) and username<>? limit 30",(like,like,u)); return jsonify(users=[user_row(r) for r in rows])

@app.get("/api/online")
def online():
    u=need()
    if not u: return unauth()
    names=[n for n in list(seen) if n!=u and is_online(n)][:30]; out=[]
    for n in names:
        r=q("select username,bio,photo from users where username=?",(n,),one=True)
        if r: out.append(user_row(r))
    return jsonify(users=out)

JOKES=["Teacher: Tum late kyun aaye? Student: Sir, board par likha tha 'School ahead, go slow' 🐢","Wifi aur crush me same baat hai - dono 'connected' dikhte hain par net nahi milta 📶"]
ROASTS=["{n} ka WiFi signal bhi tumse zyada serious hai 📶","{n} ki battery aur akal dono 1% par chalti hain 🔋"]
BALL=["Haan bilkul! ✅","Bilkul nahi ❌","Shayad... 🤔"]
HELP="/joke /roast /dice /flip /8ball /meow"

def bot_reply(u,text):
    parts=text.split(None,1); cmd=parts[0].lower(); arg=parts[1].strip() if len(parts)>1 else ""
    if cmd=="/joke": return random.choice(JOKES)
    if cmd=="/roast": return random.choice(ROASTS).format(n=arg or u)
    if cmd=="/dice": return "🎲 Pasa bola: %d"%random.randint(1,6)
    if cmd=="/flip": return "🪙 "+random.choice(["Heads","Tails"])
    if cmd=="/8ball": return "🎱 "+random.choice(BALL)
    if cmd=="/meow": return "meow meow 🐱"
    return None

@app.get("/api/chats")
def chats():
    u=need()
    if not u: return unauth()
    rows=q("select key, max(id) mid from messages where key like 'dm:%' group by key order by mid desc"); out=[]
    for r in rows:
        parts=r["key"].split(":")
        if u in parts[1:]:
            other=parts[2] if parts[1]==u else parts[1]
            last=q("select text,img,deleted from messages where id=?",(r["mid"],),one=True)
            ou=q("select photo from users where username=?",(other,),one=True)
            txt="🚫 delete hua" if last["deleted"] else (last["text"] or "📷 Photo")
            out.append(dict(user=other,photo=ou["photo"] if ou else "",last=txt[:60],online=is_online(other)))
    return jsonify(chats=out)

@app.get("/api/msgs")
def msgs():
    u=need()
    if not u: return unauth()
    kind,target=request.args.get("kind"),request.args.get("target"); key=chat_key(u,kind,target)
    if not key: return jsonify(error="no access"),403
    try: after=int(request.args.get("after") or 0)
    except: after=0
    rows=q("select id,sender,text,img,ts,reply,deleted from messages where key=? and id>? order by id limit 100",(key,after))
    recent=q("select id,deleted from messages where key=? order by id desc limit 60",(key,)); ids=[r["id"] for r in recent]; gone=[r["id"] for r in recent if r["deleted"]]; reacts={}
    if ids:
        rr=q("select mid,username,emoji from reacts where mid in (%s)"%",".join("?"*len(ids)),ids)
        for r in rr: reacts.setdefault(r["mid"],{}).setdefault(r["emoji"],[]).append(r["username"])
    now=time.time(); typ=[t for t,ts in typing.get(key,{}).items() if now-ts<4 and t!=u]
    return jsonify(msgs=[dict(r) for r in rows],gone=gone,reacts=reacts,typing=typ,online=is_online(target) if kind=="dm" else None)

@app.post("/api/send")
def send():
    u=need()
    if not u: return unauth()
    d=request.get_json(force=True,silent=True) or {}; key=chat_key(u,d.get("kind"),d.get("target"))
    if not key: return jsonify(error="no access"),403
    text=(d.get("text") or "")[:2000]; img=d.get("img") or ""
    if img and not (img.startswith("data:image/") or img.startswith("http")): img=""
    if len(img)>4000000: return jsonify(error="Image bahut badi hai"),400
    if not text and not img: return jsonify(error="empty"),400
    reply="";
    try: rid=int(d.get("reply") or 0)
    except: rid=0
    if rid:
        rr=q("select sender,text from messages where id=? and key=?",(rid,key),one=True)
        if rr: reply=rr["sender"]+": "+((rr["text"] or "📷 Photo")[:60])
    now=int(time.time())
    q("insert into messages(key,sender,text,img,ts,reply,deleted) values(?,?,?,?,?,?,0)",(key,u,text,img,now,reply),commit=True)
    if text.startswith("/"):
        out=bot_reply(u,text)
        if out: q("insert into messages(key,sender,text,img,ts,reply,deleted) values(?,?,?,?,?,?,0)",(key,BOT,out,"",now,""),commit=True)
    typing.get(key,{}).pop(u,None)
    return jsonify(ok=True)

@app.post("/api/typing")
def typing_ping():
    u=need()
    if not u: return unauth()
    d=request.get_json(force=True,silent=True) or {}; key=chat_key(u,d.get("kind"),d.get("target"))
    if key: typing.setdefault(key,{})[u]=time.time()
    return jsonify(ok=True)

@app.post("/api/react")
def react():
    u=need()
    if not u: return unauth()
    d=request.get_json(force=True,silent=True) or {}; emoji=(d.get("emoji") or "")[:8]
    m=q("select id,key from messages where id=?",(d.get("id"),),one=True)
    if not m or not emoji or not key_access(u,m["key"]): return jsonify(error="no access"),403
    cur=q("select emoji from reacts where mid=? and username=?",(m["id"],u),one=True)
    if cur and cur["emoji"]==emoji: q("delete from reacts where mid=? and username=?",(m["id"],u),commit=True)
    else: q("insert or replace into reacts values(?,?,?)",(m["id"],u,emoji),commit=True)
    return jsonify(ok=True)

@app.post("/api/delete")
def delete_msg():
    u=need()
    if not u: return unauth()
    d=request.get_json(force=True,silent=True) or {}; q("update messages set deleted=1, text='', img='', reply='' where id=? and sender=?",(d.get("id"),u),commit=True); return jsonify(ok=True)

@app.post("/api/group/create")
def gcreate():
    u=need()
    if not u: return unauth()
    d=request.get_json(force=True,silent=True) or {}; name=(d.get("name") or "").strip()[:30]
    if len(name)<2: return jsonify(error="Group ka naam likho"),400
    if q("select 1 from groups where lower(name)=lower(?)",(name,),one=True): return jsonify(error="Ye naam le liya gaya hai"),400
    gid=q("insert into groups(name,owner) values(?,?)",(name,u),commit=True)
    # lastrowid fix for PG
    if USE_PG:
        row=q("select id from groups where name=?",(name,),one=True); gid=row["id"]
    q("insert into members values(?,?)",(gid,u),commit=True); return jsonify(id=gid)

@app.get("/api/groups")
def glist():
    u=need()
    if not u: return unauth()
    s=(request.args.get("q") or "").strip()
    if s: rows=q("select * from groups where name like? limit 30",("%"+s+"%",))
    else: rows=q("select g.* from groups g join members m on m.gid=g.id where m.username=?",(u,))
    out=[]
    for g in rows:
        n=q("select count(*) c from members where gid=?",(g["id"],),one=True)["c"]; j=q("select 1 from members where gid=? and username=?",(g["id"],u),one=True) is not None
        out.append(dict(id=g["id"],name=g["name"],members=n,joined=j))
    return jsonify(groups=out)

@app.post("/api/group/join")
def gjoin():
    u=need()
    if not u: return unauth()
    d=request.get_json(force=True,silent=True) or {}
    if not q("select 1 from groups where id=?",(d.get("id"),),one=True): return jsonify(error="group nahi mila"),404
    q("insert or ignore into members values(?,?)",(d.get("id"),u),commit=True); return jsonify(ok=True)

@app.post("/api/group/add")
def gadd():
    u=need()
    if not u: return unauth()
    d=request.get_json(force=True,silent=True) or {}; gid=d.get("id"); who=(d.get("username") or "").strip().lower()
    if not q("select 1 from members where gid=? and username=?",(gid,u),one=True): return jsonify(error="no access"),403
    if not q("select 1 from users where username=?",(who,),one=True): return jsonify(error="User nahi mila"),404
    q("insert or ignore into members values(?,?)",(gid,who),commit=True); return jsonify(ok=True)

@app.post("/api/tap")
def tap():
    u=need()
    if not u: return unauth()
    d=request.get_json(force=True,silent=True) or {}
    try: n=max(1,min(40,int(d.get("n") or 0)))
    except: n=1
    q("insert or ignore into taps values(?,0)",(u,),commit=True); q("update taps set n=n+? where username=?",(n,u),commit=True); return jsonify(n=q("select n from taps where username=?",(u,),one=True)["n"])

@app.get("/api/leaderboard")
def leaderboard():
    u=need()
    if not u: return unauth()
    t=q("select username as user, n from taps where n>0 order by n desc limit 10")
    c=q("select sender as user, count(*) n from messages where sender<>? and deleted=0 group by sender order by n desc limit 5",(BOT,))
    return jsonify(taps=[dict(r) for r in t],chat=[dict(r) for r in c])

# Truth & Dare
TRUTHS=["Aaj tak ka sabse bada jhooth kya bola hai?","Tumhara pehla crush kaun tha?","Phone me sabse embarrassing cheez kya hai?"]
DARES=["Apni sabse funny awaaz me gaana gao.","10 push-ups karo abhi.","Billi ki tarah 30 sec meow karo."]

def gstate(r,u): return dict(code=r["code"],players=r["players"],host=r["players"][0],turn=r["turn"],phase=r["phase"],mode=r["mode"],question=r["question"],asker=r["asker"],log=r["log"][-6:],you=u)

@app.post("/api/game/create")
def game_create():
    u=need()
    if not u: return unauth()
    code=str(random.randint(1000,9999))
    while code in rooms: code=str(random.randint(1000,9999))
    rooms[code]=dict(code=code,players=[u],turn=0,phase="lobby",mode=None,question=None,asker=None,log=[]); return jsonify(gstate(rooms[code],u))

@app.post("/api/game/join")
def game_join():
    u=need()
    if not u: return unauth()
    d=request.get_json(force=True,silent=True) or {}; r=rooms.get(str(d.get("code")))
    if not r: return jsonify(error="Room nahi mila"),404
    if u not in r["players"]:
        if len(r["players"])>=4: return jsonify(error="Room full"),400
        if r["phase"]!="lobby": return jsonify(error="Game shuru ho chuka"),400
        r["players"].append(u)
    return jsonify(gstate(r,u))

@app.get("/api/game")
def game_get():
    u=need()
    if not u: return unauth()
    r=rooms.get(request.args.get("code",""))
    if not r or u not in r["players"]: return jsonify(error="room band"),404
    return jsonify(gstate(r,u))

@app.post("/api/game/act")
def game_act():
    u=need()
    if not u: return unauth()
    d=request.get_json(force=True,silent=True) or {}; r=rooms.get(str(d.get("code")))
    if not r or u not in r["players"]: return jsonify(error="room band"),404
    a=d.get("action"); cur=r["players"][r["turn"]]
    if a=="start":
        if r["players"][0]!=u: return jsonify(error="Sirf host start karega"),403
        if len(r["players"])<2: return jsonify(error="Kam se kam 2 log chahiye"),400
        r["phase"]="play"; r["log"].append(f"{u} ne game start kiya")
    elif a=="truth" or a=="dare":
        if cur!=u: return jsonify(error="Tumhari bari nahi"),403
        r["mode"]=a; r["question"]=random.choice(TRUTHS if a=="truth" else DARES); r["asker"]=u; r["phase"]="question"
    elif a=="next":
        r["turn"]=(r["turn"]+1)%len(r["players"]); r["phase"]="play"; r["question"]=None; r["mode"]=None
    elif a=="leave":
        r["players"].remove(u)
        if not r["players"]: del rooms[r["code"]]; return jsonify(ok=True)
        if r["turn"]>=len(r["players"]): r["turn"]=0
    return jsonify(gstate(r,u))

@app.get("/")
def home():
    # agar templates/index.html hai to wo dikhao warna simple message
    idx=os.path.join(BASE,"templates","index.html")
    if os.path.exists(idx):
        with open(idx,"r",encoding="utf-8",errors="ignore") as f: return Response(f.read(),mimetype="text/html")
    return "Bagar Billi v3 Running 🐱 - API OK"

if __name__=="__main__":
    app.run(host="0.0.0.0",port=5000,debug=True)
