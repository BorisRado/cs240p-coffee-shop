"""Tests for the scoreboard of Lab 4.1. Run:
python3 -m unittest -v test_customers

Most tests drive the Game object with made-up times. The last class runs
customers.py for real against a local shop. Standard library only.
"""

import json
import os
import signal
import socket
import subprocess
import sys
import tempfile
import time
import unittest

import customers
from customers import LB, Game, classify
from test_shop import ShopProcess

HERE = os.path.dirname(os.path.abspath(__file__))
URL = "http://coffee-fleet-1.eu-central-1.elb.amazonaws.com"
PRICES = {("latte", "M"): 4.5, ("karak", "S"): 2.0}
LATTE = {"drink": "latte", "size": "M", "price": 4.5}


class Classify(unittest.TestCase):

    def test_ok(self):
        self.assertEqual(classify(201, "i-1", LATTE, 0.4, PRICES),
                         ("i-1", "ok"))

    def test_wrong_price(self):
        cheap = dict(LATTE, price=0.45)
        self.assertEqual(classify(201, "i-1", cheap, 0.4, PRICES),
                         ("i-1", "wrong"))

    def test_slow(self):
        self.assertEqual(classify(201, "i-1", LATTE, 3.1, PRICES),
                         ("i-1", "slow"))

    def test_busy(self):
        body = {"error": "too busy, come back later"}
        self.assertEqual(classify(503, "i-1", body, 0.01, PRICES),
                         ("i-1", "busy"))

    def test_error_from_a_server(self):
        self.assertEqual(classify(500, "i-1", {}, 0.1, PRICES),
                         ("i-1", "error"))

    def test_error_from_the_load_balancer(self):
        # 502 Bad Gateway: the load balancer answers, no X-Served-By.
        self.assertEqual(classify(502, None, "<html>", 0.1, PRICES),
                         (LB, "error"))

    def test_no_answer_at_all(self):
        self.assertEqual(classify(None, None, None, 5.0, PRICES),
                         (LB, "error"))


class GameTest(unittest.TestCase):

    def setUp(self):
        self.home = tempfile.mkdtemp()

    def game(self, url=URL):
        return Game(self.home, url)

    def monkey(self, **state):
        """Write the monkey's state file, as monkey.py does."""
        state.setdefault("url", URL)
        d = os.path.join(self.home, ".coffee-game")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "monkey.json"), "w") as f:
            json.dump(state, f)

    def test_rows_count_the_last_30_seconds(self):
        g = self.game()
        g.record(100, "i-1", "ok", 0.4)
        g.record(125, "i-1", "ok", 0.5)
        g.record(126, "i-1", "slow", 3.0)
        g.record(127, "i-2", "busy", 0.0)
        rows = g.rows(now=140)
        self.assertEqual([r[0] for r in rows], ["i-1", "i-2", LB])
        i1 = rows[0][1]
        self.assertEqual((i1["ok"], i1["slow"], i1["error"]), (1, 1, 0))
        self.assertEqual(rows[1][1]["busy"], 1)

    def test_a_silent_server_disappears(self):
        g = self.game()
        g.record(100, "i-1", "ok", 0.4)
        g.record(100, "i-2", "ok", 0.4)
        g.record(125, "i-1", "ok", 0.4)
        self.assertEqual([r[0] for r in g.rows(now=140)], ["i-1", LB])

    def test_p95_of_served_orders(self):
        g = self.game()
        for i in range(19):
            g.record(100, "i-1", "ok", 0.4)
        g.record(100, "i-1", "slow", 3.0)
        g.record(100, "i-1", "busy", 0.0)
        self.assertEqual(g.rows(now=101)[0][2], 0.4)
        g.record(100, "i-1", "slow", 3.0)
        self.assertEqual(g.rows(now=101)[0][2], 3.0)

    def test_happy_customers(self):
        g = self.game()
        self.assertEqual(g.happy(), 100.0)
        for kind in ["ok", "ok", "ok", "wrong"]:
            g.record(100, "i-1", kind, 0.4)
        self.assertEqual(g.happy(), 75.0)

    def test_rate_follows_the_rush(self):
        g = self.game()
        g.reload()
        self.assertEqual(g.rate(), 2)
        self.monkey(incidents={"3": 100})
        g.reload()
        self.assertEqual(g.rate(), 12)

    def test_incident_waits_for_its_first_bad_order(self):
        self.monkey(incidents={"2": 100})
        g = self.game()
        g.reload()
        g.record(101, "i-1", "error", 0.1)      # not the kind for 2
        g.update(now=200)
        self.assertEqual(g.incident(2, now=200), ("open", 100))

    def test_incident_is_fixed_after_30_quiet_seconds(self):
        self.monkey(incidents={"1": 100})
        g = self.game()
        g.reload()
        g.record(105, LB, "error", 0.1)
        g.record(110, LB, "error", 0.1)
        g.record(111, "i-2", "ok", 0.1)
        g.update(now=139)
        self.assertEqual(g.incident(1, now=139), ("open", 39))
        g.update(now=140)
        self.assertEqual(g.incident(1, now=140), ("fixed", 10))

    def test_each_incident_has_its_own_kind(self):
        self.monkey(incidents={"2": 100, "3": 100, "4": 100})
        g = self.game()
        g.reload()
        g.record(101, "i-1", "slow", 3.0)
        g.record(101, "i-1", "busy", 0.0)
        g.record(101, "i-1", "wrong", 0.4)
        g.record(150, "i-1", "busy", 0.0)
        g.update(now=200)
        self.assertEqual(g.incident(2, now=200), ("fixed", 1))
        self.assertEqual(g.incident(3, now=200), ("fixed", 50))
        self.assertEqual(g.incident(4, now=200), ("fixed", 1))

    def test_an_incident_started_again_starts_from_zero(self):
        self.monkey(incidents={"4": 100})
        g = self.game()
        g.reload()
        g.record(101, "i-1", "wrong", 0.4)
        g.update(now=200)
        self.monkey(incidents={"4": 300})
        g.reload()
        self.assertEqual(g.incident(4, now=310), ("open", 10))

    def test_not_started(self):
        g = self.game()
        g.reload()
        self.assertEqual(g.incident(1, now=100), ("not started", None))

    def test_counts_survive_a_restart(self):
        self.monkey(incidents={"1": 100})
        g = self.game()
        g.reload()
        g.record(101, LB, "error", 0.1)
        g.record(102, "i-1", "ok", 0.1)
        g.update(now=140)
        g.save()
        g2 = self.game()
        g2.reload()
        self.assertEqual(g2.happy(), 50.0)
        self.assertEqual(g2.incident(1, now=500), ("fixed", 1))

    def test_a_new_fleet_starts_a_new_game(self):
        g = self.game()
        g.record(101, LB, "error", 0.1)
        g.save()
        self.monkey(url="http://old", incidents={"1": 100})
        g2 = self.game(url="http://coffee-fleet-2.example")
        g2.reload()
        self.assertEqual(g2.happy(), 100.0)
        self.assertEqual(g2.incident(1, now=200), ("not started", None))

    def test_score_file(self):
        g = self.game()
        for kind in ["ok", "ok", "ok", "wrong"]:
            g.record(100, "i-1", kind, 0.4)
        g.update(now=101)
        g.save()
        with open(os.path.join(self.home, "coffee-score.txt")) as f:
            self.assertEqual(f.read(),
                             "75.0% happy, 0 of 4 incidents fixed\n")

    def test_score_is_frozen_once_all_four_are_fixed(self):
        self.monkey(incidents={"1": 100, "2": 100, "3": 100, "4": 100})
        g = self.game()
        g.reload()
        for kind in ["error", "slow", "busy", "wrong"]:
            g.record(101, "i-1", kind, 0.4)
        g.update(now=200)
        g.save()
        g.record(201, "i-1", "error", 0.4)       # an Extra, later
        g.update(now=300)
        g.save()
        with open(os.path.join(self.home, "coffee-score.txt")) as f:
            self.assertEqual(f.read(),
                             "0.0% happy, 4 of 4 incidents fixed\n")

    def test_render(self):
        self.monkey(incidents={"1": 100})
        g = self.game()
        g.reload()
        g.record(101, "i-0a1b2c3d4e5f60718", "ok", 0.4)
        g.record(102, LB, "error", 0.1)
        frame = g.render(now=110)
        self.assertIn("Customers: 2 orders per second.", frame)
        self.assertIn(
            "Last 30 s             ok  error  slow  busy  wrong    p95",
            frame)
        self.assertIn(
            "i-0a1b2c3d4e5f60718    1      0     0     0      0  0.4 s",
            frame)
        self.assertIn(
            "(load balancer)        -      1     -     -      -      -",
            frame)
        self.assertIn("Happy customers since the start: 50.0%", frame)
        self.assertIn("Incident 1", frame)
        self.assertIn("open for 0 min 10 s", frame)

    def test_summary(self):
        self.monkey(incidents={"1": 100, "2": 300})
        g = self.game()
        g.reload()
        g.record(165, LB, "error", 0.1)
        g.update(now=200)
        text = g.summary(now=310)
        self.assertIn("Incident 1 (crash)        fixed after 1 min 05 s",
                      text)
        self.assertIn("Incident 2 (slow)         not fixed yet", text)
        self.assertIn("Incident 3 (rush)         not started", text)
        self.assertIn("Happy customers: 0.0%", text)


class RealRun(unittest.TestCase):
    """customers.py against a local shop that charges the wrong price."""

    def test_scoreboard_sees_the_liar(self):
        home = tempfile.mkdtemp()
        fault = os.path.join(home, "fault")
        with open(fault, "w") as f:
            f.write("liar")
        shop = ShopProcess(COFFEE_FAULT_FILE=fault)
        try:
            env = dict(os.environ, HOME=home)
            proc = subprocess.Popen(
                [sys.executable, os.path.join(HERE, "customers.py"),
                 "--url", "http://127.0.0.1:%d" % shop.port],
                env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True)
            time.sleep(4.5)
            proc.send_signal(signal.SIGINT)
            out = proc.communicate(timeout=10)[0]
        finally:
            shop.stop()
        self.assertIn("Your GameDay", out)
        self.assertIn("Happy customers: 0.0%", out)
        last = out.split("Last 30 s")[-1]
        row = [line for line in last.splitlines()
               if line.startswith("%s:%d" % (socket.gethostname(), shop.port))]
        self.assertTrue(row, out)
        wrong = int(row[0].split()[5])
        self.assertGreater(wrong, 3, out)
        with open(os.path.join(home, "coffee-score.txt")) as f:
            self.assertIn("0.0% happy", f.read())


if __name__ == "__main__":
    unittest.main()
