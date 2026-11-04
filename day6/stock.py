#!/usr/bin/env python3
"""Stock, port 8002 (Lab 6, Day 6 slides 41-43 and 48-50).

Reserves the ingredients of a drink. Its own database: stock.db. One
reservation is one local transaction: all the ingredients, or none
(atomicity, slide 42). There is no oat milk left, on purpose.

  POST /reserve  order=REF drink=NAME
"""

import service

RECIPES = {
    "espresso":   ["beans"],
    "latte":      ["beans", "milk"],
    "cappuccino": ["beans", "milk"],
    "oat-latte":  ["beans", "oat milk"],
    "karak":      ["tea", "milk"],
}
START = {"beans": 40, "milk": 30, "oat milk": 0, "tea": 20}

SCHEMA = """
CREATE TABLE IF NOT EXISTS stock (item TEXT PRIMARY KEY, qty INTEGER);
CREATE TABLE IF NOT EXISTS reservations (order_ref TEXT, item TEXT);
"""


def init():
    db = service.connect("stock.db")
    db.executescript(SCHEMA)
    db.executemany("INSERT OR IGNORE INTO stock VALUES (?, ?)",
                   START.items())


class Stock(service.Handler):
    NAME = "stock"
    ROUTES = {
        ("GET", "/health"): "health",
        ("POST", "/reserve"): "reserve",
    }

    def reserve(self):
        ref = self.args.get("order", "")
        drink = self.args.get("drink", "")
        if drink not in RECIPES:
            return self.error(400, "unknown drink: " + drink)
        db = service.connect("stock.db")
        db.execute("BEGIN IMMEDIATE")
        try:
            for item in RECIPES[drink]:
                cur = db.execute("UPDATE stock SET qty = qty - 1"
                                 " WHERE item = ? AND qty > 0", (item,))
                if cur.rowcount == 0:
                    # The beans taken above go back too: ROLLBACK.
                    db.execute("ROLLBACK")
                    return self.error(409, "out of " + item)
                db.execute("INSERT INTO reservations VALUES (?, ?)",
                           (ref, item))
            db.execute("COMMIT")
        except Exception:
            db.execute("ROLLBACK")
            raise
        self.send(200, {"order": ref, "reserved": RECIPES[drink]})


if __name__ == "__main__":
    init()
    service.serve(Stock)
