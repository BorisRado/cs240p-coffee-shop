#!/usr/bin/env python3
"""The scoreboard of Lab 4.1 (Day 4): it plays your customers.

Usage:  python3 customers.py             (finds the stack coffee-fleet)
        python3 customers.py --url http://SHOP

It orders coffee through the load balancer, 2 orders per second (12 during
the rush that monkey.py starts), and shows every 2 seconds what each server
did in the last 30 seconds. Stop it with Ctrl+C: it prints your GameDay and
saves your score in ~/coffee-score.txt.

The monkey writes its incidents in ~/.coffee-game/monkey.json; this script
keeps its counts in ~/.coffee-game/customers.json, so a restart goes on
where it stopped. Standard library and the AWS CLI only: it runs in
CloudShell as it is.
"""

import json
import math
import os
import random
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import deque

STACK = "coffee-fleet"
LB = "(load balancer)"
WINDOW = 30            # seconds shown on the scoreboard
QUIET = 30             # seconds without trouble: the incident is fixed
SLOW = 2.0             # an order that takes longer is "slow"
TIMEOUT = 5.0          # a customer waits at most this long
NORMAL_RATE = 2        # orders per second
RUSH_RATE = 12         # orders per second from incident 3 on
KINDS = ["ok", "error", "slow", "busy", "wrong"]
# What each incident does to the customers, and its name.
INCIDENTS = {1: ("error", "crash"), 2: ("slow", "slow"),
             3: ("busy", "rush"), 4: ("wrong", "wrong price")}
CLEAR = "\033[H\033[2J"


def classify(status, served_by, body, latency, prices):
    """Return (row, kind) for one order: which row of the scoreboard it
    counts in, and whether it was ok, an error, slow, busy or wrong."""
    if status is None or not served_by:
        return LB, "error"         # no answer, or the load balancer's own
    if status == 503 and isinstance(body, dict) \
            and "busy" in body.get("error", ""):
        return served_by, "busy"
    if status != 201 or not isinstance(body, dict):
        return served_by, "error"
    price = prices.get((body.get("drink"), body.get("size")))
    if price is None or abs(body.get("price", -1) - price) > 0.001:
        return served_by, "wrong"
    if latency > SLOW:
        return served_by, "slow"
    return served_by, "ok"


def clock(t):
    return time.strftime("%H:%M:%S", time.localtime(t))


def minutes(seconds):
    seconds = int(round(seconds))
    return "%d min %02d s" % (seconds // 60, seconds % 60)


class Game:
    """Everything the scoreboard counts. Times are Unix times (seconds)."""

    def __init__(self, home, url):
        self.dir = os.path.join(home, ".coffee-game")
        self.score_file = os.path.join(home, "coffee-score.txt")
        self.url = url
        self.lock = threading.Lock()
        self.events = deque()      # (time, row, kind, latency)
        self.order = []            # rows, in the order first seen
        self.incidents = {}        # number -> start time (from the monkey)
        self.total = self.ok = 0
        self.track = {}            # number -> {start, last_bad, fixed_after}
        self.frozen = None         # the score once all four are fixed
        saved = self._load("customers.json")
        if saved.get("url") == url:
            self.total = saved.get("total", 0)
            self.ok = saved.get("ok", 0)
            self.track = {int(n): t for n, t in saved["track"].items()}
            self.frozen = saved.get("frozen")

    def _load(self, name):
        try:
            with open(os.path.join(self.dir, name)) as f:
                return json.load(f)
        except (OSError, ValueError):
            return {}

    def reload(self):
        """Read the incidents that the monkey started."""
        state = self._load("monkey.json")
        if state.get("url") != self.url:
            state = {}
        with self.lock:
            self.incidents = {int(n): t for n, t in
                              state.get("incidents", {}).items()}
            for n, start in self.incidents.items():
                if self.track.get(n, {}).get("start") != start:
                    self.track[n] = {"start": start}   # started (again)

    def rate(self):
        return RUSH_RATE if 3 in self.incidents else NORMAL_RATE

    def record(self, t, row, kind, latency):
        with self.lock:
            self.events.append((t, row, kind, latency))
            if row not in self.order:
                self.order.append(row)
            self.total += 1
            self.ok += kind == "ok"
            for n, start in self.incidents.items():
                tr = self.track[n]
                if kind == INCIDENTS[n][0] and t >= start \
                        and "fixed_after" not in tr:
                    tr["last_bad"] = t

    def update(self, now):
        """Close the incidents that have been quiet for QUIET seconds."""
        with self.lock:
            while self.events and self.events[0][0] <= now - 3 * WINDOW:
                self.events.popleft()
            for tr in self.track.values():
                if "last_bad" in tr and "fixed_after" not in tr \
                        and now - tr["last_bad"] >= QUIET:
                    tr["fixed_after"] = tr["last_bad"] - tr["start"]

    def incident(self, n, now):
        """("not started", None), ("open", seconds so far) or
        ("fixed", seconds it lasted)."""
        if n not in self.incidents:
            return "not started", None
        tr = self.track[n]
        if "fixed_after" in tr:
            return "fixed", tr["fixed_after"]
        return "open", now - tr["start"]

    def fixed(self):
        return sum(1 for tr in self.track.values() if "fixed_after" in tr)

    def happy(self):
        return 100.0 if not self.total else \
            round(100.0 * self.ok / self.total, 1)

    def rows(self, now):
        """[(row, counts, p95)] for the last WINDOW seconds; the load
        balancer's row comes last and is always there."""
        with self.lock:
            recent = [e for e in self.events if e[0] > now - WINDOW]
            order = list(self.order)
        rows = []
        for row in [r for r in order if r != LB] + [LB]:
            mine = [e for e in recent if e[1] == row]
            if not mine and row != LB:
                continue
            counts = {k: sum(1 for e in mine if e[2] == k) for k in KINDS}
            served = sorted(e[3] for e in mine
                            if e[2] in ("ok", "slow", "wrong"))
            p95 = served[math.ceil(0.95 * len(served)) - 1] \
                if served else None
            rows.append((row, counts, p95))
        return rows

    def score_line(self):
        return self.frozen or "%.1f%% happy, %d of 4 incidents fixed" % (
            self.happy(), self.fixed())

    def save(self):
        if self.frozen is None and self.fixed() == 4:
            self.frozen = self.score_line()
        os.makedirs(self.dir, exist_ok=True)
        with self.lock:
            state = {"url": self.url, "total": self.total, "ok": self.ok,
                     "track": self.track, "frozen": self.frozen}
        with open(os.path.join(self.dir, "customers.json"), "w") as f:
            json.dump(state, f)
        with open(self.score_file, "w") as f:
            f.write(self.score_line() + "\n")

    def render(self, now):
        host = urllib.parse.urlparse(self.url).netloc
        name = STACK if host.startswith(STACK) else host
        lines = ["%-55s%s" % ("Sunday rush at " + name, clock(now)),
                 "Customers: %d orders per second.      Stop with Ctrl+C."
                 % self.rate(), "",
                 "%-19s %4s %6s %5s %5s %6s %6s" % (
                     "Last 30 s", "ok", "error", "slow", "busy", "wrong",
                     "p95")]
        for row, c, p95 in self.rows(now):
            if row == LB:
                lines.append("%-19s %4s %6d %5s %5s %6s %6s" % (
                    LB, "-", c["error"], "-", "-", "-", "-"))
            else:
                lines.append("%-19s %4d %6d %5d %5d %6d %6s" % (
                    row[:19], c["ok"], c["error"], c["slow"], c["busy"],
                    c["wrong"], "-" if p95 is None else "%.1f s" % p95))
        lines += ["", "Happy customers since the start: %.1f%%"
                  % self.happy()]
        for n in sorted(self.incidents):
            state, seconds = self.incident(n, now)
            what = "fixed after " if state == "fixed" else "open for "
            lines.append("Incident %d   started %s   %s%s" % (
                n, clock(self.incidents[n]), what, minutes(seconds)))
        return "\n".join(lines)

    def summary(self, now):
        lines = ["Your GameDay"]
        for n, (_, name) in sorted(INCIDENTS.items()):
            state, seconds = self.incident(n, now)
            if state == "fixed":
                state = "fixed after " + minutes(seconds)
            elif state == "open":
                state = "not fixed yet"
            lines.append("%-25s %s" % ("Incident %d (%s)" % (n, name),
                                       state))
        happy = self.frozen.split("%")[0] + "%" if self.frozen \
            else "%.1f%%" % self.happy()
        lines += ["Happy customers: " + happy,
                  "Saved in " + os.path.basename(self.score_file)]
        return "\n".join(lines)


def call(method, url, body=None):
    """(status, X-Served-By, body) or (None, None, None) if no answer."""
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            status, headers, raw = r.status, r.headers, r.read()
    except urllib.error.HTTPError as e:
        status, headers, raw = e.code, e.headers, e.read()
    except (OSError, ValueError):     # refused, reset, timed out
        return None, None, None
    try:
        parsed = json.loads(raw)
    except ValueError:
        parsed = raw.decode(errors="replace")
    return status, headers.get("X-Served-By"), parsed


def stack_url():
    """The ShopUrl output of the stack coffee-fleet (aws CLI)."""
    try:
        out = subprocess.run(
            ["aws", "cloudformation", "describe-stacks", "--stack-name",
             STACK, "--query", "Stacks[0].Outputs", "--output", "json"],
            capture_output=True, text=True, timeout=60)
        outputs = json.loads(out.stdout) if out.returncode == 0 else None
    except (OSError, ValueError, subprocess.TimeoutExpired):
        outputs = None
    for o in outputs or []:
        if o["OutputKey"] == "ShopUrl":
            return o["OutputValue"]
    sys.exit("Cannot find the stack %s. Check that CloudShell runs in "
             "eu-central-1, and that Step 1.4 finished." % STACK)


def wait_for_menu(url):
    """The true prices, {(drink, size): price}, from GET /menu."""
    while True:
        status, _, body = call("GET", url + "/menu")
        if status == 200 and isinstance(body, dict):
            return {(m["drink"], m["size"]): m["price"]
                    for m in body["menu"]}
        print("Waiting for your shop at %s to answer... Are your targets "
              "healthy (Step 1.6)?" % url, flush=True)
        time.sleep(3)


def customer(url, prices, game):
    drink, size = random.choice(sorted(prices))
    start = time.monotonic()
    status, served_by, body = call(
        "POST", url + "/orders", {"drink": drink, "size": size,
                                  "to_go": True})
    latency = time.monotonic() - start
    row, kind = classify(status, served_by, body, latency, prices)
    game.record(time.time(), row, kind, latency)


def main():
    args = sys.argv[1:]
    if len(args) == 2 and args[0] == "--url":
        url = args[1]
    elif not args:
        url = stack_url()
    else:
        sys.exit("Usage: python3 customers.py [--url http://SHOP]")
    url = url.rstrip("/")
    if not url.startswith("http"):
        url = "http://" + url
    prices = wait_for_menu(url)
    game = Game(os.path.expanduser("~"), url)
    game.reload()
    next_order = next_draw = time.monotonic()
    try:
        while True:
            now = time.monotonic()
            if now >= next_order:
                threading.Thread(target=customer, daemon=True,
                                 args=(url, prices, game)).start()
                next_order = max(next_order + 1.0 / game.rate(), now - 1)
            if now >= next_draw:
                game.reload()
                game.update(time.time())
                game.save()
                print(CLEAR + game.render(time.time()), flush=True)
                next_draw += 2
            time.sleep(max(0, min(next_order, next_draw) - time.monotonic()))
    except KeyboardInterrupt:
        game.update(time.time())
        game.save()
        print("\n" + game.summary(time.time()), flush=True)


if __name__ == "__main__":
    main()
