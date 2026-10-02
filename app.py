# -*- coding: utf-8 -*-
# BAGAR BILLI v3.2 - Powered by Symiiii
import os, re, time, random, secrets, string
from flask import Flask, request, jsonify, render_template
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__, template_folder="templates")
DATABASE_URL = os.environ.get("DATABASE_URL","").replace("postgres://","postgresql://",1)
USE_PG = bool(DATABASE_URL)

if USE_PG:
    import psycopg2, psycopg2.extras
    def get_conn(): return psycopg2.connect(DATABASE_URL, sslmode='require')
    def q(sql, args=(), one=False, commit=False):
        s=sql.replace("?", "%s").replace("integer primary key autoincrement","serial primary key")
        conn=get_conn()
        try:
            cur=conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            if "insert or ignore" in s.lower():
                s=re.sub(r"insert or ignore","INSERT",s,flags=re.I)+" ON CONFLICT DO NOTHING"
            cur.execute(s, args)
            if commit: conn.commit(); return True
            return cur.fetchone() if one else cur.fetchall()
        except Exception as e:
            try: conn.rollback()
            except: pass
            print("DB ERR:", e); return None if one else []
        finally:
            try: cur.close(); conn.close()
            except: pass
else:
    import sqlite3
    BASE=os.path.dirname(os.path.abspath(__file__)); DB=os.path.join(BASE,"bagarbilli.db")
    def get_conn():
        c=sqlite3.connect(DB); c.row_factory=sqlite3.Row; return c
    def q(sql, args=(), one=False, commit=False):
        c=get_conn()
        try:
            cur=c.execute(sql, args)
            if commit: c.commit(); return True
            rows=cur.fetchall(); return rows[0] if one and rows else (None if one else rows)
        finally: c.close()

def init():
    try:
        q("create table if not exists users(username text primary key, pw text, bio text default '', photo text default '')", commit=True)
        q("create table if not exists sessions(token text primary key, username text)", commit=True)
        q("create table if not exists groups(id serial primary key, name text unique, owner text)" if USE_PG else "create table if not exists groups(id integer primary key autoincrement, name text unique, owner text)", commit=True)
        q("create table if not exists messages(id serial primary key, key text, sender text, text text, img text, ts integer, reply integer default 0, deleted integer default 0)" if USE_PG else "create table if not exists messages(id integer primary key autoincrement, key text, sender text, text text, img text, ts integer, reply integer default 0, deleted integer default 0)", commit=True)
        q("create table if not exists members(gid integer, username text, primary key(gid, username))", commit=True)
        q("create table if not exists reacts(mid integer, username text, emoji text, primary key(mid, username))", commit=True)
        q("create table if not exists taps(username text primary key, n integer default 0)", commit=True)
        q("create table if not exists couples(id serial primary key, user1 text, user2 text, code text unique, since integer, score integer default 0)" if USE_PG else "create table if not exists couples(id integer primary key autoincrement, user1 text, user2 text, code text unique, since integer, score integer default 0)", commit=True)
        q("create table if not exists games(code text primary key, type text, host text, players text, state text)", commit=True)
    except Exception as e: print("init failed:", e)

try: init()
except: pass

rooms={}; typing={}
def need():
    try: init()
    except: pass
    t=request.headers.get("X-Token",""); r=q("select username from sessions where token=?",(t,),one=True)
    return r["username"] if r else (r.get("username") if isinstance(r,dict) else None)
def unauth(): return jsonify(error="login"), 401
def chat_key(u,kind,target):
    if kind=="dm":
        if target.lower()=="billibot": return "dm:" + ":".join(sorted([u,"billibot"]))
        if q("select 1 from users where username=?",(target,),one=True): return "dm:" + ":".join(sorted([u,target]))
    elif kind=="g":
        try:
            if q("select 1 from members where gid=? and username=?",(int(target),u),one=True): return f"g:{target}"
        except: pass
    return None

@app.get("/api/health")
def health(): return jsonify(ok=True)
@app.get("/")
def index(): return render_template("index.html")

@app.post("/api/auth")
def auth():
    d=request.get_json(force=True,silent=True) or {}; u=(d.get("username") or "").strip().lower(); p=d.get("password") or ""
    if not re.fullmatch(r"[a-z0-9_]{3,20}",u): return jsonify(error="Username 3-20: a-z 0-9 _"),400
    if len(p)<4: return jsonify(error="Password 4+ chars"),400
    row=q("select * from users where username=?",(u,),one=True)
    if row is None: q("insert into users(username,pw) values(?,?)",(u,generate_password_hash(p)),commit=True)
    else:
        pw=row["pw"] if isinstance(row,dict) else row[1]
        if not check_password_hash(pw,p): return jsonify(error="Password galat hai"),403
    t=secrets.token_hex(16); q("insert into sessions values(?,?)",(t,u),commit=True); return jsonify(token=t,username=u)

@app.get("/api/me")
def me():
    u=need()
    if not u: return unauth()
    r=q("select username,bio,photo from users where username=?",(u,),one=True)
    return jsonify(dict(r) if isinstance(r,dict) else {"username":u,"bio":"","photo":""})

@app.get("/api/chats")
def chats():
    u=need()
    if not u: return unauth()
    rows=q("select key, max(id) as mid from messages where key like 'dm:%' group by key order by mid desc") or []
    out=[]
    for r in rows:
        key=r["key"] if isinstance(r,dict) else r[0]; mid=r["mid"] if isinstance(r,dict) else r[1]
        if u not in key: continue
        parts=key.split(":"); other=parts[2] if parts[1]==u else parts[1]
        last=q("select text from messages where id=?",(mid,),one=True); txt=(last["text"] if isinstance(last,dict) else last[0]) if last else ""
        out.append(dict(user=other,last=txt[:60],photo=""))
    return jsonify(chats=out)

@app.get("/api/msgs")
def msgs():
    u=need()
    if not u: return unauth()
    key=chat_key(u,request.args.get("kind"),request.args.get("target"))
    if not key: return jsonify(error="no access"),403
    after=int(request.args.get("after") or 0)
    rows=q("select id,sender,text,img,ts from messages where key=? and id>? order by id limit 100",(key,after)) or []
    return jsonify(msgs=[dict(r) if isinstance(r,dict) else {"id":r[0],"sender":r[1],"text":r[2],"img":r[3],"ts":r[4]} for r in rows])

@app.post("/api/send")
def send():
    u=need()
    if not u: return unauth()
    d=request.get_json(force=True) or {}; key=chat_key(u,d.get("kind"),d.get("target"))
    if not key: return jsonify(error="no access"),403
    text=(d.get("text") or "")[:2000]; img=d.get("img") or ""
    if not text and not img: return jsonify(error="empty"),400
    q("insert into messages(key,sender,text,img,ts) values(?,?,?,?,?)",(key,u,text,img,int(time.time())),commit=True)
    if "billibot" in key and text.startswith("/"):
        jokes=["Teri harkate dekh ke billi boli - isse bada bakchod nahi dekha 😹","Tu itna slow hai, WiFi bhi tez hai!"]
        roasts=["Tu extra syllabus hai 😼","Tera attitude - sasta iPhone cover"]
        t=text.lower()
        if t.startswith("/joke"): rep=random.choice(jokes)
        elif t.startswith("/roast"): rep=random.choice(roasts)
        elif t.startswith("/dice"): rep=f"🎲 {random.randint(1,6)}"
        elif t.startswith("/8ball"): rep=random.choice(["Haan pakka","Bilkul nahi","Maybe"])
        elif t.startswith("/truth"): rep=random.choice(["Sabse bada jhooth?","Crush ka naam?"])
        elif t.startswith("/dare"): rep=random.choice(["Billi awaz nikal","Purani DP bhej"])
        else: rep="Commands: /joke /roast /love /dice /8ball /truth /dare"
        q("insert into messages(key,sender,text,img,ts) values(?,?,?,?,?)",(key,"billibot",rep,"",int(time.time())),commit=True)
    return jsonify(ok=True)

@app.get("/api/groups")
def glist():
    u=need()
    if not u: return unauth()
    rows=q("select g.* from groups g join members m on m.gid=g.id where m.username=?",(u,)) or []
    out=[dict(id=r["id"] if isinstance(r,dict) else r[0], name=r["name"] if isinstance(r,dict) else r[1], members=1, joined=True) for r in rows]
    return jsonify(groups=out)

@app.post("/api/group/create")
def gcreate():
    u=need()
    if not u: return unauth()
    name=(request.get_json().get("name") or "").strip()[:30]
    q("insert into groups(name,owner) values(?,?)",(name,u),commit=True)
    row=q("select id from groups where name=?",(name,),one=True); gid=row["id"] if isinstance(row,dict) else row[0]
    q("insert into members values(?,?)",(gid,u),commit=True); return jsonify(id=gid)

@app.post("/api/group/join")
def gjoin():
    u=need(); d=request.get_json(); q("insert into members values(?,?)",(d.get("id"),u),commit=True); return jsonify(ok=True)

@app.post("/api/typing")
def typing_api():
    u=need()
    if not u: return unauth()
    d=request.get_json() or {}; key=chat_key(u,d.get("kind"),d.get("target"))
    if key: typing.setdefault(key,{})[u]=time.time()
    return jsonify(ok=True)

# GAMES
@app.post("/api/game/create")
def game_create():
    u=need()
    if not u: return unauth()
    gtype=request.get_json().get("type","spin_bottle"); code="".join(random.choices(string.digits,k=4))
    rooms[code]={"code":code,"type":gtype,"host":u,"players":[u],"state":{"question":"Lobby - spin karo","turn":0,"votes":{}}}; return jsonify(rooms[code])

@app.post("/api/game/join")
def game_join():
    u=need(); code=str(request.get_json().get("code","")); r=rooms.get(code)
    if not r: return jsonify(error="Room nahi mila"),404
    if u not in r["players"]: r["players"].append(u)
    return jsonify(r)

@app.post("/api/game/spin")
def game_spin():
    u=need(); code=str(request.get_json().get("code","")); r=rooms.get(code)
    if not r: return jsonify(error="no room"),404
    chosen=random.choice(r["players"]); r["state"]["question"]=f"Bottle ghoomi - {chosen} ki baari! 😼"; r["state"]["turn"]=r["players"].index(chosen); return jsonify(r)

@app.get("/api/game")
def game_get():
    return jsonify(rooms.get(request.args.get("code",""),{}))

# CALC
@app.post("/api/calc/<typ>")
def calc(typ):
    d=request.get_json() or {}; n1=(d.get("n1") or "").strip(); n2=(d.get("n2") or "").strip()
    if not n1 or not n2: return jsonify(error="Naam dalo"),400
    pct=(sum(ord(c) for c in (n1+n2).lower()) % 80) + random.randint(0,20); pct=min(100,pct)
    roasts={"love":["Shaadi pakki? 😹","Billi approve nahi karti"],"friendship":["Tu iska ATM hai","Bromance overloaded"],"billi":["100% billi wali harkate","Billi boli bhag ja"],"ex":["Move on kar ja","Ex = purani jeans"],"rishta":["Mummy maan jayegi? doubt hai","Bio-data me jhooth?"]}
    title="Made For Each Other 😻" if pct>80 else "Baat ban sakti hai 😼" if pct>60 else "Timepass hai 😹" if pct>40 else "Billi mana kar rahi 😾"
    return jsonify(percent=pct,title=title,roast=random.choice(roasts.get(typ,roasts["love"])),share_text=f"{n1} ❤️ {n2} = {pct}% - {title} | Bagar Billi v3.2 😼")

# COUPLE
@app.post("/api/couple/create")
def couple_create():
    u=need()
    if not u: return unauth()
    code="".join(random.choices(string.digits,k=6)); q("insert into couples(user1,code,since,score) values(?,?,?,0)",(u,code,int(time.time())),commit=True); return jsonify(code=code)

@app.post("/api/couple/join")
def couple_join():
    u=need(); code=str(request.get_json().get("code","")); row=q("select * from couples where code=?",(code,),one=True)
    if not row: return jsonify(error="Code galat"),404
    r=dict(row) if isinstance(row,dict) else {"user1":row[1],"user2":row[2]}
    if r.get("user2"): return jsonify(error="Already paired"),400
    q("update couples set user2=? where code=?",(u,code),commit=True); return jsonify(ok=True,partner=r.get("user1"))

@app.post("/api/couple/match")
def couple_match():
    d=request.get_json() or {}; u1=(d.get("u1") or d.get("n1") or "")[:20]; u2=(d.get("u2") or d.get("n2") or "")[:20]
    if not u1 or not u2: return jsonify(error="Naam dalo"),400
    pct=(sum(ord(c) for c in (u1+u2).lower()) % 80)+random.randint(0,20); combo=u1[:3]+u2[-3:]; baby=random.choice(["Billi","Golumolu","Chintu"])+" "+combo
    return jsonify(percent=min(100,pct),combo_name=combo,baby_name=baby,breakup_days=random.randint(30,7000),tagline="Chipku Couple",badge="Made For Each Other" if pct>80 else "7 Day Chipku Couple")

@app.get("/api/users")
def users():
    u=need()
    if not u: return unauth()
    s=(request.args.get("q") or "").lower(); rows=q("select username from users where lower(username) like? limit 20",(f"%{s}%",)) or []
    return jsonify(users=[{"username":r["username"] if isinstance(r,dict) else r[0]} for r in rows])

if __name__=="__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT",5000)))
