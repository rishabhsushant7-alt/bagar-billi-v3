# -*- coding: utf-8 -*-
# BAGAR BILLI  -  Powered by Symiiii
# Pydroid 3 me chalane ke liye:
#   1) Pydroid > Pip > "flask" install karo
#   2) Ye file run karo
#   3) Chrome me kholo:  http://127.0.0.1:5000
#   Dusre log (same WiFi / hotspot): http://TUMHARA_PHONE_IP:5000

import os, re, time, random, secrets, sqlite3
from flask import Flask, request, jsonify, Response
from werkzeug.security import generate_password_hash, check_password_hash

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE, "bagarbilli.db")
app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 8 * 1024 * 1024
rooms = {}


# ---------------------------------------------------------------- database
def q(sql, args=(), one=False, commit=False):
    c = sqlite3.connect(DB)
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
    q("create table if not exists messages(id integer primary key autoincrement, key text, sender text, text text, img text, ts integer)", commit=True)
    q("create index if not exists ix_msg on messages(key, id)", commit=True)


def need():
    t = request.headers.get("X-Token", "")
    r = q("select username from sessions where token=?", (t,), one=True)
    return r["username"] if r else None


def unauth():
    return jsonify(error="login"), 401


def chat_key(u, kind, target):
    if kind == "dm":
        if target and q("select 1 from users where username=?", (target,), one=True):
            return "dm:" + ":".join(sorted([u, target]))
    elif kind == "g":
        if q("select 1 from members where gid=? and username=?", (target, u), one=True):
            return "g:" + str(target)
    return None


# ---------------------------------------------------------------- auth / profile
@app.post("/api/auth")
def auth():
    d = request.get_json(force=True, silent=True) or {}
    u = (d.get("username") or "").strip().lower()
    p = d.get("password") or ""
    if not re.fullmatch(r"[a-z0-9_]{3,20}", u):
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
    return jsonify(token=t, username=u)


@app.get("/api/me")
def me():
    u = need()
    if not u:
        return unauth()
    r = q("select username,bio,photo from users where username=?", (u,), one=True)
    return jsonify(dict(r))


@app.post("/api/profile")
def profile():
    u = need()
    if not u:
        return unauth()
    d = request.get_json(force=True, silent=True) or {}
    bio = (d.get("bio") or "")[:200]
    q("update users set bio=? where username=?", (bio, u), commit=True)
    ph = d.get("photo")
    if ph and ph.startswith("data:image/") and len(ph) < 400000:
        q("update users set photo=? where username=?", (ph, u), commit=True)
    return jsonify(ok=True)


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
    return jsonify(users=[dict(r) for r in rows])


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
            last = q("select text,img from messages where id=?", (r["mid"],), one=True)
            ou = q("select photo from users where username=?", (other,), one=True)
            out.append(dict(user=other, photo=ou["photo"] if ou else "",
                            last=(last["text"] or "[media]")[:60]))
    return jsonify(chats=out)


@app.get("/api/msgs")
def msgs():
    u = need()
    if not u:
        return unauth()
    key = chat_key(u, request.args.get("kind"), request.args.get("target"))
    if not key:
        return jsonify(error="no access"), 403
    after = int(request.args.get("after") or 0)
    rows = q("select id,sender,text,img,ts from messages where key=? and id>? order by id limit 100", (key, after))
    return jsonify(msgs=[dict(r) for r in rows])


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
    q("insert into messages(key,sender,text,img,ts) values(?,?,?,?,?)", (key, u, text, img, int(time.time())), commit=True)
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
    gid = d.get("id")
    if not q("select 1 from groups where id=?", (gid,), one=True):
        return jsonify(error="group nahi mila"), 404
    q("insert or ignore into members values(?,?)", (gid, u), commit=True)
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


# ---------------------------------------------------------------- truth & dare
TRUTHS = [
    "Aaj tak ka sabse bada jhooth kya bola hai?", "Tumhara pehla crush kaun tha?",
    "Phone me sabse embarrassing cheez kya hai?", "Kisi se chhupke kya karte ho?",
    "Sabse ajeeb sapna kaun sa dekha hai?", "Kis dost se sabse zyada jalte ho?",
    "Aakhri baar kab roye the aur kyun?", "Apni kaun si aadat tumhe pasand nahi?",
    "Kabhi kisi ka message bina bataye padha hai?", "Group me sabse irritating kaun lagta hai?",
]
DARES = [
    "Apni sabse funny awaaz me gaana gao.", "10 push-ups karo abhi.",
    "Apne kisi dost ko 'I miss you' bhejo.", "1 minute bina hanse dikhao.",
    "Billi ki tarah 30 second tak meow karo.", "Apni sabse purani photo group me bhejo.",
    "Kisi bhi ek ko compliment do, over-acting ke saath.", "Ulti ginti 20 se 1 tak tez bolo.",
    "Apna naam ulta bolo 3 baar.", "Ek chhoti si shayari sunao.",
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
:root{--bg:#0f1115;--card:#1a1d24;--acc:#ff7a1a;--tx:#eee;--mut:#8b93a1}
*{box-sizing:border-box;-webkit-tap-highlight-color:transparent}
html,body{margin:0;height:100%;background:var(--bg);color:var(--tx);font-family:system-ui,sans-serif}
body{-webkit-user-select:none;user-select:none;-webkit-touch-callout:none}
input,textarea{-webkit-user-select:text;user-select:text}
#app{display:flex;flex-direction:column;height:100%}
#main{flex:1;overflow-y:auto;padding:12px;display:flex;flex-direction:column}
#nav{display:flex;background:var(--card);border-top:1px solid #2a2f3a}
#nav button{flex:1;background:none;border:0;color:var(--mut);padding:10px 0;font-size:11px}
#nav button span{display:block;font-size:20px}
#nav button.on{color:var(--acc)}
button{font:inherit}
.btn{background:var(--acc);color:#fff;border:0;border-radius:10px;padding:10px 14px;font-weight:600}
.btn.alt{background:#2a2f3a}
input,textarea{width:100%;background:var(--card);border:1px solid #2a2f3a;color:var(--tx);border-radius:10px;padding:11px;font:inherit}
.row{display:flex;gap:8px;align-items:center;margin-bottom:8px}
.item{display:flex;gap:10px;align-items:center;background:var(--card);border-radius:12px;padding:10px;margin-bottom:8px}
.item .t{flex:1;min-width:0}.item small{color:var(--mut);display:block;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.av{width:42px;height:42px;border-radius:50%;background:var(--acc);display:flex;align-items:center;justify-content:center;font-weight:700;object-fit:cover;flex:none}
.top{display:flex;gap:10px;align-items:center;padding-bottom:8px;border-bottom:1px solid #2a2f3a;margin-bottom:8px}
.top button{background:none;border:0;color:var(--tx);font-size:22px}
.msgs{flex:1;overflow-y:auto;display:flex;flex-direction:column;gap:6px;padding-bottom:6px}
.m{max-width:80%;padding:8px 11px;border-radius:14px;background:var(--card);align-self:flex-start;word-break:break-word}
.m.me{background:var(--acc);align-self:flex-end}
.m b{display:block;font-size:11px;opacity:.7}
.m img{max-width:100%;border-radius:10px;display:block;margin-top:4px;pointer-events:none}
.inp{display:flex;gap:6px;align-items:center;padding-top:6px}
.inp .ic{font-size:24px;padding:0 4px}
h2{margin:4px 0 12px}.mut{color:var(--mut)}
#splash{position:fixed;inset:0;background:var(--bg);z-index:99;display:flex;flex-direction:column;align-items:center;justify-content:center}
#splash h1{font-size:40px;margin:10px 0;color:var(--acc)}
#splash .pw{position:absolute;bottom:28px;color:var(--mut);letter-spacing:1px}
#fab{position:fixed;right:12px;bottom:76px;width:50px;height:50px;border-radius:50%;background:var(--acc);border:0;font-size:22px;z-index:50;box-shadow:0 2px 10px #0008}
#mp{position:fixed;right:12px;bottom:134px;width:min(300px,90vw);background:var(--card);border:1px solid #2a2f3a;border-radius:14px;padding:10px;z-index:50;display:none}
#mp.on{display:block}
#pl{max-height:140px;overflow-y:auto;margin:6px 0}
#pl div{padding:5px;border-radius:6px;font-size:13px}#pl div.cur{background:#2a2f3a;color:var(--acc)}
.big{font-size:20px;text-align:center;padding:16px;background:var(--card);border-radius:14px;margin:10px 0}
.err{color:#ff6b6b;margin:8px 0;min-height:18px}
.blur{filter:blur(18px)}
</style></head><body>
<div id="splash"><div style="font-size:70px">🐱</div><h1>Bagar Billi</h1><div class="mut">chat • group • game</div><div class="pw">Powered by Symiiii</div></div>
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
let TOKEN=localStorage.getItem('bb_t'),ME=null,tab='chats',cur=null,room=null;
const esc=s=>String(s==null?'':s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
async function api(p,b){
 const o={headers:{'X-Token':TOKEN||'','Content-Type':'application/json'}};
 if(b){o.method='POST';o.body=JSON.stringify(b)}
 let r;try{r=await fetch(p,o)}catch(e){return{error:'Server se connection nahi'}}
 const j=await r.json().catch(()=>({error:'Error'}));
 if(r.status==401&&TOKEN){logout();return{error:'login'}}
 return j;
}
function av(photo,name){
 if(photo)return `<img class="av" src="${photo}">`;
 return `<div class="av">${esc((name||'?')[0].toUpperCase())}</div>`;
}
// ---- no screenshot / copy deterrents (browser me full block possible nahi)
document.addEventListener('contextmenu',e=>e.preventDefault());
document.addEventListener('visibilitychange',()=>{document.body.classList.toggle('blur',document.hidden)});
// ---- start
setTimeout(async()=>{
 $('#splash').style.display='none';
 if(TOKEN){const m=await api('/api/me');if(m.username){ME=m;return startApp()}}
 loginView();
},1800);
function loginView(){
 nav.style.display='none';$('#fab').style.display='none';
 main.innerHTML=`<div style="margin:auto;width:100%;max-width:340px">
 <div style="text-align:center;font-size:56px">🐱</div><h2 style="text-align:center">Bagar Billi</h2>
 <div class="row"><input id="lu" placeholder="Username" autocapitalize="none" autocomplete="off"></div>
 <div class="row"><input id="lp" type="password" placeholder="Password"></div>
 <div class="err" id="le"></div>
 <button class="btn" style="width:100%" id="lb">Login / Naya account</button>
 <p class="mut" style="text-align:center;font-size:12px">Username nahi hai to apne aap account ban jayega.<br>Password yaad rakhna - forgot password nahi hai.</p></div>`;
 $('#lb').onclick=async()=>{
  const j=await api('/api/auth',{username:$('#lu').value,password:$('#lp').value});
  if(j.error)return $('#le').textContent=j.error;
  TOKEN=j.token;localStorage.setItem('bb_t',TOKEN);
  ME=await api('/api/me');startApp();
 };
}
function logout(){TOKEN=null;localStorage.removeItem('bb_t');cur=null;room=null;ME=null;loginView()}
function startApp(){
 nav.style.display='flex';$('#fab').style.display='block';
 const T=[['chats','💬','Chats'],['groups','👥','Groups'],['search','🔍','Search'],['game','🎲','Game'],['profile','👤','Profile']];
 nav.innerHTML=T.map(t=>`<button data-t="${t[0]}"><span>${t[1]}</span>${t[2]}</button>`).join('');
 nav.querySelectorAll('button').forEach(b=>b.onclick=()=>{tab=b.dataset.t;cur=null;show()});
 show();
}
function show(){
 nav.querySelectorAll('button').forEach(b=>b.classList.toggle('on',b.dataset.t==tab));
 ({chats:vChats,groups:vGroups,search:vSearch,game:vGame,profile:vProfile})[tab]();
}
// ---- chats
async function vChats(){
 main.innerHTML='<h2>Chats</h2><div id="l"></div>';
 const j=await api('/api/chats');
 const l=$('#l');if(!l)return;
 if(!j.chats||!j.chats.length){l.innerHTML='<p class="mut">Abhi koi chat nahi. Search tab se kisi ko dhundo.</p>';return}
 l.innerHTML=j.chats.map((c,i)=>`<div class="item" data-i="${i}">${av(c.photo,c.user)}<div class="t"><b>${esc(c.user)}</b><small>${esc(c.last)}</small></div></div>`).join('');
 l.querySelectorAll('.item').forEach(e=>e.onclick=()=>{const c=j.chats[e.dataset.i];openChat('dm',c.user,c.user)});
}
function openChat(kind,target,title){cur={kind,target,title,last:0};renderChat()}
function renderChat(){
 main.innerHTML=`<div class="top"><button id="bk">←</button><b>${esc(cur.title)}</b></div>
 <div class="msgs" id="msgs"></div>
 <div class="inp"><label class="ic">🖼️<input type="file" id="fi" accept="image/*" hidden></label>
 <input id="tx" placeholder="Message ya GIF link" autocomplete="off"><button class="btn" id="sd">➤</button></div>`;
 $('#bk').onclick=()=>{cur=null;show()};
 $('#sd').onclick=sendText;
 $('#tx').onkeydown=e=>{if(e.key==='Enter')sendText()};
 $('#fi').onchange=e=>{
  const f=e.target.files[0];if(!f)return;
  if(f.size>3000000)return alert('File 3MB se choti rakho');
  const r=new FileReader();r.onload=()=>post({img:r.result});r.readAsDataURL(f);e.target.value='';
 };
 pull();
}
async function post(x){
 const c=cur;
 const j=await api('/api/send',Object.assign({kind:c.kind,target:c.target},x));
 if(j.error)alert(j.error);else pull();
}
function sendText(){
 const t=$('#tx').value.trim();if(!t)return;$('#tx').value='';
 if(/^https?:\/\/\S+$/.test(t)&&/(\.gif|\.png|\.jpe?g|\.webp)(\?|$)|giphy|tenor/i.test(t))post({img:t});
 else post({text:t});
}
async function pull(){
 const c=cur;if(!c)return;
 const j=await api(`/api/msgs?kind=${c.kind}&target=${encodeURIComponent(c.target)}&after=${c.last}`);
 if(c!==cur||!j.msgs||!j.msgs.length)return;
 const box=$('#msgs');if(!box)return;
 const near=box.scrollHeight-box.scrollTop-box.clientHeight<120||c.last===0;
 j.msgs.forEach(m=>{
  c.last=m.id;
  const d=document.createElement('div');
  d.className='m'+(m.sender===ME.username?' me':'');
  d.innerHTML=(c.kind==='g'&&m.sender!==ME.username?`<b>${esc(m.sender)}</b>`:'')+(m.text?esc(m.text):'')+(m.img?`<img src="${esc(m.img)}">`:'');
  box.appendChild(d);
 });
 if(near)box.scrollTop=box.scrollHeight;
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
// ---- search
function vSearch(){
 main.innerHTML='<h2>Search</h2><div class="row"><input id="s" placeholder="Username ya bio se dhundo" autocapitalize="none"></div><div id="l"></div>';
 let t;$('#s').oninput=()=>{clearTimeout(t);t=setTimeout(go,300)};
 async function go(){
  const v=$('#s').value.trim();const l=$('#l');if(!l)return;
  if(!v){l.innerHTML='';return}
  const j=await api('/api/users?q='+encodeURIComponent(v));const u=j.users||[];
  l.innerHTML=u.length?u.map((x,i)=>`<div class="item" data-i="${i}">${av(x.photo,x.username)}<div class="t"><b>@${esc(x.username)}</b><small>${esc(x.bio)}</small></div><button class="btn">Message</button></div>`).join(''):'<p class="mut">Koi nahi mila</p>';
  l.querySelectorAll('.item').forEach(e=>e.onclick=()=>{const x=u[e.dataset.i];openChat('dm',x.username,x.username)});
 }
}
// ---- profile
function vProfile(){
 main.innerHTML=`<h2>Profile</h2><div style="text-align:center;margin-bottom:12px">
 <div id="pv" style="display:inline-block;transform:scale(1.8);margin:20px 0">${av(ME.photo,ME.username)}</div>
 <div><b>@${esc(ME.username)}</b></div>
 <label class="btn alt" style="display:inline-block;margin-top:10px">📷 Photo badlo<input type="file" id="pf" accept="image/*" hidden></label></div>
 <textarea id="bio" rows="3" maxlength="200" placeholder="Bio likho...">${esc(ME.bio)}</textarea>
 <div class="row" style="margin-top:10px"><button class="btn" style="flex:1" id="sv">Save</button><button class="btn alt" id="lo">Logout</button></div>`;
 let photo=null;
 $('#pf').onchange=e=>{
  const f=e.target.files[0];if(!f)return;
  const im=new Image();im.onload=()=>{
   const c=document.createElement('canvas');c.width=c.height=256;const x=c.getContext('2d');
   const s=Math.min(im.width,im.height);x.drawImage(im,(im.width-s)/2,(im.height-s)/2,s,s,0,0,256,256);
   photo=c.toDataURL('image/jpeg',.8);$('#pv').innerHTML=av(photo,ME.username);
  };im.src=URL.createObjectURL(f);
 };
 $('#sv').onclick=async()=>{
  await api('/api/profile',{bio:$('#bio').value,photo});
  ME=await api('/api/me');alert('Save ho gaya');
 };
 $('#lo').onclick=logout;
}
// ---- truth & dare
function vGame(){
 if(room)return renderGame();
 main.innerHTML=`<h2>Truth &amp; Dare</h2><p class="mut">2 se 4 dost ek room me khel sakte hain.</p>
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
  body=`<div class="big">Baari: <b>@${esc(cu)}</b></div>`+(cu===me?'<div class="row"><button class="btn" style="flex:1" id="a2">Truth</button><button class="btn alt" style="flex:1" id="a3">Dare</button></div>':'<p class="mut" style="text-align:center">@'+esc(cu)+' Truth ya Dare chun raha hai...</p>');
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
    print("Bagar Billi chalu hai -> http://127.0.0.1:5000")
    app.run(host="0.0.0.0", port=5000, debug=False)
