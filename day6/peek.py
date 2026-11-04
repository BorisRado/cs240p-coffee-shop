#!/usr/bin/env python3
"""Look into the three databases of Lab 6, as a database administrator
would: straight into the files, not through the services.

  python3 peek.py
"""

import os
import sqlite3

import service


def show(title, dbname, sql):
    print(title)
    path = os.path.join(service.HERE, dbname)
    if not os.path.exists(path):
        print("  (no database yet: run ./start.sh)\n")
        return
    db = sqlite3.connect(path)
    cur = db.execute(sql)
    names = [c[0] for c in cur.description]
    rows = cur.fetchall()
    widths = [max([len(n)] + [len(str(r[i])) for r in rows])
              for i, n in enumerate(names)]
    for row in [names] + rows:
        print("  " + "  ".join(str(v).ljust(w) for v, w in zip(row, widths)))
    print()


def main():
    show("payments.db (the last 4 rows)", "payments.db",
         "SELECT * FROM (SELECT id, at, order_ref, customer, kind,"
         " printf('%.2f', amount / 100.0) AS amount FROM payments"
         " ORDER BY id DESC LIMIT 4) ORDER BY id")
    show("stock.db", "stock.db", "SELECT item, qty FROM stock")
    show("orders.db (the last 4 rows)", "orders.db",
         "SELECT * FROM (SELECT id, order_ref, customer, drink,"
         " printf('%.2f', price / 100.0) AS price FROM orders"
         " ORDER BY id DESC LIMIT 4) ORDER BY id")


if __name__ == "__main__":
    main()
