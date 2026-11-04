#!/usr/bin/env python3
"""Orders, port 8000 (Lab 6, Day 6). The front of the shop, version 3.

THIS SERVICE HAS BUGS ON PURPOSE. Look for "BUG (on purpose)". Do not use
this code for a real shop.

  GET  /orders?customer=NAME   the orders of one customer (slide 37)
  GET  /menu?search=WORD       the drinks whose name contains WORD
  POST /login     user=NAME password=PW    gives a JWT (slide 84)
  GET  /admin/sales   header "Authorization: Bearer JWT", baristas only
  POST /orders    customer=NAME drink=NAME [pause=SECONDS]
                  runs the saga: payments, then stock, then orders
                  (slides 48-50); pause waits after the payment

Its own database: orders.db. The JWT secret is in the file jwt-secret.
"""


import base64
import hashlib
import hmac
import json
import os
import secrets
import time

import service


# BUG (on purpose): the customer's name is glued into the SQL (slide 37).
def find_orders(db, name):
    return db.execute("SELECT * FROM orders WHERE customer = '" + name + "'")


# BUG (on purpose): the same mistake, in a second place.
def find_drinks(db, word):
    return db.execute("SELECT * FROM menu WHERE drink LIKE '%" + word + "%'")


TOKEN_MINUTES = 30
MAX_PAUSE = 60
PRICES = {"espresso": 300, "latte": 450, "cappuccino": 450,
          "oat-latte": 500, "karak": 250}
USERS = [("emi", "latte2026", "customer"), ("sara", "s4ra!", "customer"),
         ("omar", "omar1990", "customer"), ("layla", "karak4ever",
         "customer"), ("noura", "Barista#1", "barista")]
ORDERS = [("emi", "latte"), ("sara", "cappuccino"), ("omar", "espresso"),
          ("emi", "espresso"), ("layla", "karak"), ("sara", "karak"),
          ("omar", "latte"), ("sara", "latte"), ("layla", "cappuccino")]

SCHEMA = """
CREATE TABLE IF NOT EXISTS orders (
  id INTEGER PRIMARY KEY, customer TEXT, drink TEXT, price INTEGER,
  order_ref TEXT);
CREATE TABLE IF NOT EXISTS users (name TEXT PRIMARY KEY, password TEXT,
  role TEXT);
CREATE TABLE IF NOT EXISTS menu (drink TEXT PRIMARY KEY, price INTEGER);
"""


def init():
    db = service.connect("orders.db")
    db.executescript(SCHEMA)
    if db.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
        # BUG (on purpose): passwords in clear text (not used in the lab).
        db.executemany("INSERT INTO users VALUES (?, ?, ?)", USERS)
        db.executemany("INSERT INTO menu VALUES (?, ?)", PRICES.items())
        db.executemany(
            "INSERT INTO orders (customer, drink, price, order_ref)"
            " VALUES (?, ?, ?, ?)",
            [(c, d, PRICES[d], "seed") for c, d in ORDERS])


class Recorder:
    """Wraps a connection and remembers the SQL it ran, so that the answer
    can show it. For the lab only: a real service would not show it."""

    def __init__(self, db):
        self.db, self.sql, self.params = db, None, []

    def execute(self, sql, params=()):
        self.sql, self.params = sql, list(params)
        return self.db.execute(sql, params)


# ---------- JWT, HS256 (RFC 7519), by hand ----------

def b64(data):
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def unb64(text):
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def sign(head, body, secret):
    msg = (head + "." + body).encode()
    return b64(hmac.new(secret.encode(), msg, hashlib.sha256).digest())


def make_token(claims, secret):
    head = b64(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    body = b64(json.dumps(claims).encode())
    return head + "." + body + "." + sign(head, body, secret)


def check_token(token, secret):
    """The claims, or ValueError with the reason."""
    try:
        head, body, sig = token.split(".")
        header = json.loads(unb64(head))
        claims = json.loads(unb64(body))
    except (ValueError, TypeError):
        raise ValueError("not a JWT")
    if header.get("alg") == "none":
        pass        # BUG (on purpose): no signature to check
    elif not hmac.compare_digest(sig, sign(head, body, secret)):
        raise ValueError("bad signature")
    if claims.get("exp", 0) < time.time():
        raise ValueError("token expired: log in again")
    return claims


def read_secret():
    with open(os.path.join(service.HERE, "jwt-secret")) as f:
        return f.read().strip()


SECRET = None          # read at start, from the file jwt-secret


class Orders(service.Handler):
    NAME = "orders"
    ROUTES = {
        ("GET", "/health"): "health",
        ("GET", "/orders"): "lookup",
        ("POST", "/orders"): "place",
        ("GET", "/menu"): "menu",
        ("POST", "/login"): "login",
        ("GET", "/admin/sales"): "sales",
    }

    def lookup(self):
        db = Recorder(service.connect("orders.db"))
        rows = find_orders(db, self.args.get("customer", ""))
        self.send(200, {"sql": db.sql, "params": db.params,
                        "orders": [dict(r) for r in rows]})

    def menu(self):
        db = Recorder(service.connect("orders.db"))
        rows = find_drinks(db, self.args.get("search", ""))
        self.send(200, {"sql": db.sql, "params": db.params,
                        "menu": [list(r) for r in rows]})

    def login(self):
        db = service.connect("orders.db")
        user = db.execute("SELECT name, role FROM users"
                          " WHERE name = ? AND password = ?",
                          (self.args.get("user", ""),
                           self.args.get("password", ""))).fetchone()
        if user is None:
            return self.error(401, "wrong user or password")
        claims = {"sub": user["name"], "role": user["role"],
                  "exp": int(time.time()) + TOKEN_MINUTES * 60}
        self.send(200, {"token": make_token(claims, SECRET)})

    def sales(self):
        auth = self.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            return self.error(401, "missing header Authorization: Bearer")
        try:
            claims = check_token(auth[len("Bearer "):].strip(), SECRET)
        except ValueError as e:
            return self.error(401, str(e))
        if claims.get("role") != "barista":
            return self.error(403, "baristas only; your token says role "
                              + str(claims.get("role")))
        db = service.connect("orders.db")
        real = db.execute("SELECT role FROM users WHERE name = ?",
                          (claims.get("sub"),)).fetchone()
        real = real["role"] if real else "no such user"
        # The service trusts the token. Only this log, written for the
        # lab, compares it with the users table.
        with open(os.path.join(service.HERE, "admin.log"), "a") as f:
            f.write("%s %s role=%s users-table=%s%s\n" % (
                time.strftime("%H:%M:%S"), claims.get("sub"),
                claims.get("role"), real,
                "" if real == "barista" else " FORGED"))
        rows = db.execute("SELECT drink, COUNT(*) AS sold, SUM(price)"
                          " AS cents FROM orders GROUP BY drink").fetchall()
        self.send(200, {
            "hello": claims.get("sub"),
            "sales": ["%-10s %2d sold  %6s" % (r["drink"], r["sold"],
                      service.money(r["cents"])) for r in rows]})

    def place(self):
        who = self.args.get("customer", "")
        drink = self.args.get("drink", "")
        if not who or drink not in PRICES:
            return self.error(400, "need customer and drink, one of "
                              + " ".join(PRICES))
        pause = min(int(self.args.get("pause", "0") or 0), MAX_PAUSE)
        ref = "o-" + secrets.token_hex(3)
        price = PRICES[drink]
        saga = []

        # Step 1, payments: charge the card. Committed at once.
        status, r = service.call("payments", "/charge", order=ref,
                                 customer=who, amount=price)
        if status != 200:
            return self.send(502, {"order": ref, "status": "failed",
                                   "saga": ["1 payments: FAILED, "
                                            + r.get("error", "")]})
        saga.append("1 payments: charged %s to %s" % (
            service.money(price), who))
        print("saga %s: %s" % (ref, saga[-1]), flush=True)
        if pause > 0:
            print("saga %s: pause %d s" % (ref, pause), flush=True)
            time.sleep(pause)

        # Step 2, stock: reserve the ingredients.
        status, r = service.call("stock", "/reserve", order=ref, drink=drink)
        if status != 200:
            saga.append("2 stock: FAILED, " + r.get("error", ""))
            # Compensation, backwards: give the money back.
            status, r = service.call("payments", "/refund", order=ref)
            saga.append("compensation, payments: " + (
                "refunded %s to %s" % (r["refunded"], who) if status == 200
                else "FAILED, " + r.get("error", "")))
            print("saga %s: %s" % (ref, " / ".join(saga[1:])), flush=True)
            return self.send(409, {"order": ref, "status": "cancelled",
                                   "saga": saga})
        saga.append("2 stock: reserved " + " and ".join(r["reserved"]))

        # Step 3, orders: create the order, in this service's database.
        db = service.connect("orders.db")
        cur = db.execute("INSERT INTO orders (customer, drink, price,"
                         " order_ref) VALUES (?, ?, ?, ?)",
                         (who, drink, price, ref))
        saga.append("3 orders: created order %d" % cur.lastrowid)
        print("saga %s: done" % ref, flush=True)
        self.send(201, {"order": ref, "status": "done", "saga": saga})


if __name__ == "__main__":
    init()
    SECRET = read_secret()
    service.serve(Orders)
