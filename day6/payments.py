#!/usr/bin/env python3
"""Payments, port 8001 (Lab 6, Day 6 slides 48-50).

Charges and refunds cards. Its own database: payments.db. A refund never
deletes the charge: it adds a second row (a compensation is not an undo).

  POST /charge   order=REF customer=NAME amount=CENTS
  POST /refund   order=REF   (safe to send twice: one refund per order)
"""

import time

import service

SCHEMA = """
CREATE TABLE IF NOT EXISTS payments (
  id       INTEGER PRIMARY KEY,
  at       TEXT,
  order_ref TEXT,
  customer TEXT,
  amount   INTEGER,       -- cents; a refund is negative
  kind     TEXT           -- 'charge' or 'refund'
);
"""


def init():
    service.connect("payments.db").executescript(SCHEMA)


class Payments(service.Handler):
    NAME = "payments"
    ROUTES = {
        ("GET", "/health"): "health",
        ("POST", "/charge"): "charge",
        ("POST", "/refund"): "refund",
    }

    def charge(self):
        ref = self.args.get("order", "")
        who = self.args.get("customer", "")
        amount = int(self.args.get("amount", "0"))
        if not ref or not who or amount <= 0:
            return self.error(400, "need order, customer and amount")
        db = service.connect("payments.db")
        cur = db.execute(
            "INSERT INTO payments (at, order_ref, customer, amount, kind)"
            " VALUES (?, ?, ?, ?, 'charge')",
            (time.strftime("%H:%M:%S"), ref, who, amount))
        self.send(200, {"payment": cur.lastrowid, "order": ref,
                        "charged": service.money(amount), "customer": who})

    def refund(self):
        ref = self.args.get("order", "")
        db = service.connect("payments.db")
        db.execute("BEGIN IMMEDIATE")
        try:
            charge = db.execute(
                "SELECT customer, amount FROM payments"
                " WHERE order_ref = ? AND kind = 'charge'", (ref,)).fetchone()
            if charge is None:
                db.execute("ROLLBACK")
                return self.error(404, "no charge for order " + ref)
            done = db.execute(
                "SELECT id FROM payments"
                " WHERE order_ref = ? AND kind = 'refund'", (ref,)).fetchone()
            if done is None:
                db.execute(
                    "INSERT INTO payments (at, order_ref, customer, amount,"
                    " kind) VALUES (?, ?, ?, ?, 'refund')",
                    (time.strftime("%H:%M:%S"), ref, charge["customer"],
                     -charge["amount"]))
            db.execute("COMMIT")
        except Exception:
            db.execute("ROLLBACK")
            raise
        self.send(200, {"order": ref, "refunded": service.money(
            charge["amount"]), "customer": charge["customer"]})


if __name__ == "__main__":
    init()
    service.serve(Payments)
