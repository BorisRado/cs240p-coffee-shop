#!/usr/bin/env python3
"""The CS 240P coffee shop: a small REST API (Day 2, slide 97).

Standard library only, so it runs on a fresh Amazon Linux 2023 server with
no `pip install`. Everything is kept in memory: a restart empties the shop.

THIS SHOP HAS BUGS ON PURPOSE. Look for the lines marked "BUG (on purpose)".
Do not use this code for a real shop.

Settings come from environment variables (all optional):

  COFFEE_PORT          port to listen on (default 80)
  COFFEE_MANAGER_PIN   PIN for POST /admin/reset (unset: no admin endpoint)
  COFFEE_RACE_DELAY    seconds between the check and the use of a gift card
                       (default 0.3)
  COFFEE_API_KEYS      file with one "key name" pair per line; when set,
                       /orders and /giftcards need the header X-API-Key
  COFFEE_RATE_LIMIT    requests per minute per client (default 0: no limit)
  COFFEE_EXTRA_HEADERS JSON object of headers added to every response
  COFFEE_TRUST_PROXY   "1": take the client address from X-Forwarded-For
"""

import json
import os
import re
import secrets
import socket
import threading
import time
import urllib.request
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

VERSION = "1.0"

# Prices in cents, so that 4.50 - 4.50 is exactly 0.
MENU = {
    "espresso":   {"S": 250, "M": 300},
    "latte":      {"S": 400, "M": 450, "L": 500},
    "cappuccino": {"S": 400, "M": 450, "L": 500},
    "karak":      {"S": 200, "M": 250},
}
GIFT_CARD_VALUE = 500          # a new gift card holds 5.00 (slide 41)
MAX_ORDERS = 10000             # keeps memory small on a public server
MAX_BODY = 10000               # bytes

PORT = int(os.environ.get("COFFEE_PORT", "80"))
MANAGER_PIN = os.environ.get("COFFEE_MANAGER_PIN", "")
RACE_DELAY = float(os.environ.get("COFFEE_RACE_DELAY", "0.3"))
RATE_LIMIT = int(os.environ.get("COFFEE_RATE_LIMIT", "0"))
EXTRA_HEADERS = json.loads(os.environ.get("COFFEE_EXTRA_HEADERS", "{}"))
TRUST_PROXY = os.environ.get("COFFEE_TRUST_PROXY", "") == "1"


def load_api_keys(path):
    """Read "key name" lines. Returns {} when no file is set (open shop)."""
    keys = {}
    if path:
        with open(path) as f:
            for line in f:
                parts = line.split()
                if len(parts) >= 2 and not parts[0].startswith("#"):
                    keys[parts[0]] = parts[1]
    return keys


API_KEYS = load_api_keys(os.environ.get("COFFEE_API_KEYS", ""))


def ec2_metadata():
    """Ask the instance metadata service (IMDSv2, slide 88) where we run.

    First a PUT for a session token, then GETs that send the token.
    Off EC2 there is no answer, and the shop says "not on EC2".
    """
    base = "http://169.254.169.254/latest"
    info = {"zone": "not on EC2", "instance_id": "not on EC2"}
    try:
        req = urllib.request.Request(
            base + "/api/token", method="PUT",
            headers={"X-aws-ec2-metadata-token-ttl-seconds": "60"})
        token = urllib.request.urlopen(req, timeout=1).read().decode()
        for key, path in [("zone", "placement/availability-zone"),
                          ("instance_id", "instance-id")]:
            req = urllib.request.Request(
                base + "/meta-data/" + path,
                headers={"X-aws-ec2-metadata-token": token})
            info[key] = urllib.request.urlopen(req, timeout=1).read().decode()
    except OSError:
        pass
    return info


def money(cents):
    return round(cents / 100, 2)


class Shop:
    """All the shop's data, in memory."""

    def __init__(self):
        self.lock = threading.Lock()   # protects orders and next_id
        self.orders = {}               # id -> order
        self.next_id = 1
        self.cards = {}                # code -> {"balance": cents}
        self.started = datetime.now(timezone.utc)
        self.hits = {}                 # client -> (minute, count)

    def reset(self):
        with self.lock:
            self.orders.clear()
            self.cards.clear()

    def rate_ok(self, client):
        if RATE_LIMIT <= 0:
            return True
        minute = int(time.time() // 60)
        with self.lock:
            start, count = self.hits.get(client, (minute, 0))
            if start != minute:
                start, count = minute, 0
                if len(self.hits) > 10000:     # forget old clients
                    self.hits.clear()
            self.hits[client] = (start, count + 1)
            return count < RATE_LIMIT


SHOP = Shop()
HOST = {"hostname": socket.gethostname(),
        "zone": "not on EC2", "instance_id": "not on EC2"}


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def version_string(self):
        # The Server header. Do not advertise the Python version.
        return "coffee-shop/" + VERSION

    # ---------- helpers ----------

    def client(self):
        if TRUST_PROXY and self.headers.get("X-Forwarded-For"):
            return self.headers["X-Forwarded-For"].split(",")[0].strip()
        return self.client_address[0]

    def send(self, status, body=None, ctype="application/json",
             headers=None):
        if body is None:
            data = b""
        elif ctype == "application/json":
            data = (json.dumps(body, indent=2) + "\n").encode()
        else:
            data = body.encode()
        self.send_response(status)
        if data:
            self.send_header("Content-Type", ctype + "; charset=utf-8")
        if status != 204:
            self.send_header("Content-Length", str(len(data)))
        if "session=" not in self.headers.get("Cookie", ""):
            # BUG (on purpose): no HttpOnly, no Secure, no SameSite (Day 2).
            self.send_header("Set-Cookie",
                             "session=" + secrets.token_hex(8) + "; Path=/")
        for name, value in EXTRA_HEADERS.items():
            self.send_header(name, value)
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        if data and self.command != "HEAD":
            self.wfile.write(data)

    def error(self, status, message):
        self.send(status, {"error": message})

    def read_json(self):
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY:
            raise ValueError("body too large")
        raw = self.rfile.read(length) if length else b"{}"
        body = json.loads(raw or b"{}")
        if not isinstance(body, dict):
            raise ValueError('send a JSON object: {"drink": "latte"}')
        return body

    def owner(self):
        """Who is asking? With API keys: the key's name. Without: guest."""
        if not API_KEYS:
            return "guest"
        return API_KEYS.get(self.headers.get("X-API-Key", ""))

    def price_of(self, body):
        drink = str(body.get("drink", "")).lower()
        size = str(body.get("size", "M")).upper()
        if drink not in MENU:
            raise ValueError("unknown drink; see GET /menu")
        if size not in MENU[drink]:
            raise ValueError(drink + " has no size " + size)
        return drink, size, MENU[drink][size]

    # ---------- routing ----------

    def handle_any(self, method):
        path = self.path.split("?")[0].rstrip("/") or "/"
        if not SHOP.rate_ok(self.client()):
            return self.send(429, {"error": "too many requests"},
                             headers={"Retry-After": "60"})
        try:
            if path == "/" and method == "GET":
                return self.home()
            if path == "/health" and method == "GET":
                return self.send(200, "OK\n", "text/plain")
            if path == "/menu" and method == "GET":
                return self.menu()
            if path == "/admin/reset" and method == "POST":
                return self.admin_reset()
            if path.startswith("/orders") or path.startswith("/giftcards"):
                who = self.owner()
                if who is None:
                    return self.error(401, "missing or wrong X-API-Key")
                m = re.fullmatch(r"/orders(?:/(\d+))?", path)
                if m:
                    return self.orders(method, m.group(1), who)
                m = re.fullmatch(r"/giftcards(?:/([\w-]+))?(/redeem)?", path)
                if m:
                    return self.giftcards(method, m.group(1), m.group(2))
            return self.error(404, "no such page: " + method + " " + path)
        except ValueError as e:        # bad JSON, bad drink, bad length
            self.close_connection = True
            return self.error(400, str(e))

    def do_GET(self):
        self.handle_any("GET")

    def do_HEAD(self):
        self.handle_any("GET")

    def do_POST(self):
        self.handle_any("POST")

    def do_PUT(self):
        self.handle_any("PUT")

    def do_DELETE(self):
        self.handle_any("DELETE")

    # ---------- pages ----------

    def home(self):
        up = datetime.now(timezone.utc) - SHOP.started
        page = """<!doctype html>
<html><head><meta charset="utf-8"><title>Coffee shop</title></head>
<body style="font-family: sans-serif; max-width: 40em; margin: 2em auto">
<h1>&#9749; Coffee shop</h1>
<table>
<tr><td>Server (hostname)</td><td><b>{host}</b></td></tr>
<tr><td>Availability Zone</td><td><b>{zone}</b></td></tr>
<tr><td>Instance ID</td><td><b>{iid}</b></td></tr>
<tr><td>Shop started (UTC)</td><td>{started}</td></tr>
<tr><td>Running for</td><td>{up} seconds</td></tr>
<tr><td>Orders in memory</td><td>{orders}</td></tr>
<tr><td>Version</td><td>{version}</td></tr>
</table>
<p>The API: <a href="/menu">/menu</a>, /orders, /giftcards,
<a href="/health">/health</a></p>
</body></html>
""".format(host=HOST["hostname"], zone=HOST["zone"],
           iid=HOST["instance_id"],
           started=SHOP.started.strftime("%d %b %Y %H:%M:%S"),
           up=int(up.total_seconds()), orders=len(SHOP.orders),
           version=VERSION)
        self.send(200, page, "text/html")

    def menu(self):
        items = [{"drink": d, "size": s, "price": money(c)}
                 for d, sizes in MENU.items() for s, c in sizes.items()]
        self.send(200, {"menu": items})

    def admin_reset(self):
        if not MANAGER_PIN:
            return self.error(404, "no admin on this shop")
        if self.headers.get("X-Manager-Pin", "") != MANAGER_PIN:
            return self.error(403, "wrong manager PIN")
        SHOP.reset()
        self.send(200, {"reset": True,
                        "message": "all orders and gift cards deleted"})

    # ---------- orders (slide 97) ----------

    def orders(self, method, oid, who):
        if oid is None and method == "GET":
            mine = [o for o in SHOP.orders.values() if o["owner"] == who]
            return self.send(200, {"orders": mine})
        if oid is None and method == "POST":
            # BUG (on purpose): POST is not idempotent. The same order sent
            # twice makes two orders (two clicks, two lattes; Day 2).
            body = self.read_json()
            drink, size, cents = self.price_of(body)
            with SHOP.lock:
                if len(SHOP.orders) >= MAX_ORDERS:
                    return self.error(503, "the shop is full; try later")
                order = {"id": SHOP.next_id, "drink": drink, "size": size,
                         "to_go": bool(body.get("to_go", False)),
                         "price": money(cents), "owner": who,
                         "server": HOST["hostname"],
                         "time": datetime.now(timezone.utc).isoformat(
                             timespec="seconds")}
                SHOP.orders[order["id"]] = order
                SHOP.next_id += 1
            return self.send(201, order,
                             headers={"Location": "/orders/%d" % order["id"]})
        if oid is None:
            return self.error(405, "use GET or POST on /orders")

        order = SHOP.orders.get(int(oid))
        if method == "GET":
            # BUG (on purpose): no check that the order is yours. Change the
            # number in the URL and you read another customer's order
            # (Broken Object Level Authorization; Day 2, slide 96).
            if order is None:
                return self.error(404, "no order " + oid)
            return self.send(200, order)
        # PUT and DELETE do check the owner. Compare with GET above.
        if order is None or order["owner"] != who:
            return self.error(404, "no order " + oid)
        if method == "PUT":
            body = self.read_json()
            drink, size, cents = self.price_of(body)
            with SHOP.lock:
                order.update(drink=drink, size=size, price=money(cents),
                             to_go=bool(body.get("to_go", False)))
            return self.send(200, order)
        if method == "DELETE":
            with SHOP.lock:
                SHOP.orders.pop(order["id"], None)
            return self.send(204)
        return self.error(405, "use GET, PUT or DELETE on /orders/" + oid)

    # ---------- gift cards (Day 3, slide 41) ----------

    def giftcards(self, method, code, redeem):
        if code is None and method == "POST":
            code = "GC-" + secrets.token_hex(3).upper()
            SHOP.cards[code] = {"balance": GIFT_CARD_VALUE}
            return self.send(201, {"code": code,
                                   "balance": money(GIFT_CARD_VALUE)},
                             headers={"Location": "/giftcards/" + code})
        if code is None:
            return self.error(405, "use POST /giftcards for a new card")
        card = SHOP.cards.get(code or "")
        if card is None:
            return self.error(404, "no gift card " + code)
        if not redeem and method == "GET":
            return self.send(200, {"code": code,
                                   "balance": money(card["balance"])})
        if redeem and method == "POST":
            drink, size, price = self.price_of(self.read_json())
            # BUG (on purpose): check, then use, with a gap in between.
            # Two requests at the same time both pass the check (TOCTOU).
            if card["balance"] >= price:                    # check
                time.sleep(RACE_DELAY)      # <- other requests run here
                card["balance"] -= price                    # use
                return self.send(200, {"paid": money(price),
                                       "drink": drink, "size": size,
                                       "balance": money(card["balance"])})
            return self.send(402, {"error": "not enough money on the card",
                                   "balance": money(card["balance"])})
        return self.error(405, "use GET /giftcards/CODE or "
                               "POST /giftcards/CODE/redeem")

    def log_message(self, fmt, *args):
        # One line per request; systemd keeps it (journalctl -u coffee).
        print("%s %s" % (self.client(), fmt % args), flush=True)


class Server(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 128       # the default, 5, drops a burst of clients


def main():
    HOST.update(ec2_metadata())
    server = Server(("0.0.0.0", PORT), Handler)
    print("Coffee shop %s on port %d, server %s, zone %s"
          % (VERSION, PORT, HOST["hostname"], HOST["zone"]), flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
