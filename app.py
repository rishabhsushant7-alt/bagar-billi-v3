# -*- coding: utf-8 -*-
import os, re, time, random, secrets
from flask import Flask, request, jsonify
from werkzeug.security import generate_password_hash, check_password_hash

# Postgres support ke liye
DATABASE_URL = os.environ.get("DATABASE_URL")
USE_PG = bool(DATABASE_URL)

if USE_PG:
    import psycopg2
    import psycopg2.extras
else:
    import sqlite3

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE, "bagarbilli.db")
app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 8 * 1024 * 1024
rooms = {}

# ---------- database helper ----------
def get_conn():
    if USE_PG:
        return psycopg2.connect(DATABASE_URL, sslmode='require')
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    return c

def q(sql, args=(), one=False, commit=False):
    # sqlite me? aur postgres me %s
    if USE_PG:
        sql = sql.replace("?", "%s")
        sql = sql.replace("insert or ignore", "insert",) # pg ke liye alag handle
    conn = get_conn()
    try:
        if USE_PG:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute(sql, args)
            if commit:
                conn.commit()
                return cur.rowcount
            rows = cur.fetchall() if not one else cur.fetchone()
            return rows
        else:
            cur = conn.execute(sql, args)
            if commit:
                conn.commit()
                return cur.lastrowid
            rows = cur.fetchall()
            if one:
                return rows[0] if rows else None
            return rows
    except Exception as e:
        print("DB ERROR:", e, sql)
        if not USE_PG:
            raise
        # agar pg me insert or ignore fail hua toh ignore karo
        if "duplicate" in str(e).lower():
            conn.rollback()
            return None
        raise
    finally:
        conn.close()

def init():
    if USE_PG:
        q("create table if not exists users(username text primary key, pw text, bio text default '', photo text default '')", commit=True)
        q("create table if not exists sessions(token text primary key, username text)", commit=True)
        q("create table if not exists groups(id serial primary key, name text unique, owner text)", commit=True)
        q("create table if not exists members(gid integer, username text, primary key(gid, username))", commit=True)
        q("create table if not exists messages(id serial primary key, key text, sender text, text text, img text, ts integer)", commit=True)
    else:
        q("create table if not exists users(username text primary key, pw text, bio text default '', photo text default '')", commit=True)
        q("create table if not exists sessions(token text primary key, username text)", commit=True)
        q("create table if not exists groups(id integer primary key autoincrement, name text unique, owner text)", commit=True)
        q("create table if not exists members(gid integer, username text, primary key(gid, username))", commit=True)
        q("create table if not exists messages(id integer primary key autoincrement, key text, sender text, text text, img text, ts integer)", commit=True)
        q("create index if not exists ix_msg on messages(key, id)", commit=True)

# IMPORTANT: server start hote hi table bana do
init()

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
