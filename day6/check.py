#!/usr/bin/env python3
"""The final check of Lab 6: one line per part. It reads the files, so it
works after ./stop.sh.

  python3 check.py
"""

import os
import socket
import sqlite3

import service


def running():
    n = 0
    for port in service.PORTS.values():
        try:
            socket.create_connection(("127.0.0.1", port), 0.5).close()
            n += 1
        except OSError:
            pass
    return n


def injection():
    """Runs the student's find_orders with the attack of Part 2."""
    try:
        from orders import find_orders
        db = sqlite3.connect(os.path.join(service.HERE, "orders.db"))
        n = len(find_orders(db, "x' OR '1'='1").fetchall())
    except Exception as e:
        return "error (%s)" % e.__class__.__name__
    return "%d rows" % n


def menu(word, unit):
    """Runs the student's find_drinks (Step 2.5) with one search."""
    try:
        from orders import find_drinks
        db = sqlite3.connect(os.path.join(service.HERE, "orders.db"))
        n = len(find_drinks(db, word).fetchall())
    except Exception as e:
        return "error (%s)" % e.__class__.__name__
    return "%d %s" % (n, unit)


def lost():
    """Charges with no order and no refund (Step 3.4)."""
    paths = [os.path.join(service.HERE, n) for n in ("payments.db",
                                                     "orders.db")]
    if not all(os.path.exists(p) for p in paths):
        return 0
    db = sqlite3.connect(paths[0])
    db.execute("ATTACH ? AS o", (paths[1],))
    return db.execute(
        "SELECT COUNT(*) FROM payments WHERE kind = 'charge'"
        " AND order_ref NOT IN (SELECT order_ref FROM payments"
        " WHERE kind = 'refund')"
        " AND order_ref NOT IN (SELECT order_ref FROM o.orders)"
    ).fetchone()[0]


def refunds():
    path = os.path.join(service.HERE, "payments.db")
    if not os.path.exists(path):
        return 0
    return sqlite3.connect(path).execute(
        "SELECT COUNT(*) FROM payments WHERE kind = 'refund'").fetchone()[0]


def forged():
    try:
        with open(os.path.join(service.HERE, "admin.log")) as f:
            return sum(1 for line in f if line.rstrip().endswith("FORGED"))
    except OSError:
        return 0


def weak_secret():
    here = service.HERE
    with open(os.path.join(here, "jwt-secret")) as f:
        secret = f.read().strip()
    with open(os.path.join(here, "wordlist.txt")) as f:
        words = {w.strip() for w in f}
    return "yes" if secret in words else "no"


def main():
    print("Services running:   %d" % running())
    print("Injection returns:  %s" % injection())
    print("Menu injection:     %s" % menu("' OR 1=1 --", "rows"))
    print("Menu search lat:    %s" % menu("lat", "drinks"))
    print("Saga refunds:       %d" % refunds())
    print("Money lost:         %d" % lost())
    print("Forged admin calls: %d" % forged())
    print("Secret in wordlist: %s" % weak_secret())


if __name__ == "__main__":
    main()
