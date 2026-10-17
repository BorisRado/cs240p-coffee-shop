#!/usr/bin/env python3
"""Redeem one gift card many times at the same moment (Day 3, slide 41).

Usage:  python3 race.py http://3.120.45.67 [number of requests, default 10]

It creates a new gift card with 5.00 on it, then sends the redeems for a
latte (4.50) all at once. One latte should be accepted, and the others
refused with 402. Standard library only: it runs in CloudShell as it is.
"""

import json
import sys
import threading
import urllib.error
import urllib.request


def call(method, url, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")
    except OSError as e:               # no answer at all
        return 0, {"error": str(e)}


def main():
    if len(sys.argv) < 2:
        sys.exit("Usage: python3 race.py http://YOUR-IP [requests]")
    shop = sys.argv[1].rstrip("/")
    if not shop.startswith("http"):
        shop = "http://" + shop
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 10

    status, card = call("POST", shop + "/giftcards")
    if status != 201:
        sys.exit("Could not create a gift card: %s %s" % (status, card))
    code = card["code"]
    print("New gift card %s with %.2f on it." % (code, card["balance"]))
    print("Sending %d redeems for a latte (4.50) at the same moment..." % n)

    results = [None] * n
    start = threading.Barrier(n)       # all threads wait, then go together

    def redeem(i):
        start.wait()
        results[i] = call("POST", shop + "/giftcards/" + code + "/redeem",
                          {"drink": "latte", "size": "M"})

    threads = [threading.Thread(target=redeem, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    for i, (status, body) in enumerate(results, 1):
        if status == 0:
            print("  request %2d: no answer (%s)" % (i, body["error"]))
            continue
        word = "accepted" if status == 200 else "refused "
        print("  request %2d: %d %s  balance after: %.2f"
              % (i, status, word, body.get("balance", 0)))
    accepted = sum(1 for s, _ in results if s == 200)
    _, card = call("GET", shop + "/giftcards/" + code)
    print("Lattes accepted: %d of %d" % (accepted, n))
    print("Final balance:   %.2f" % card["balance"])


if __name__ == "__main__":
    main()
