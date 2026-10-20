"""Tests for the coffee shop. Run:  python3 -m unittest -v test_shop

Each test class starts shop.py as a real process on a free port, with its
own settings, and talks to it over HTTP. Standard library only.
"""

import http.client
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class ShopProcess:
    def __init__(self, **env):
        self.port = free_port()
        full = dict(os.environ, COFFEE_PORT=str(self.port))
        full.update(env)
        self.proc = subprocess.Popen(
            [sys.executable, os.path.join(HERE, "shop.py")], env=full,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        for _ in range(100):
            try:
                socket.create_connection(("127.0.0.1", self.port),
                                         0.1).close()
                return
            except OSError:
                time.sleep(0.05)
        raise RuntimeError("shop did not start")

    def stop(self):
        self.proc.terminate()
        self.proc.wait(5)
        out = self.proc.stdout.read().decode()
        self.proc.stdout.close()
        return out

    def call(self, method, path, body=None, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        data = body if isinstance(body, (bytes, type(None))) \
            else json.dumps(body).encode()
        conn.request(method, path, body=data, headers=headers or {})
        r = conn.getresponse()
        raw = r.read()
        conn.close()
        ctype = r.getheader("Content-Type", "")
        parsed = json.loads(raw) if raw and "json" in ctype \
            else raw.decode()
        return r.status, parsed, r


class OpenShop(unittest.TestCase):
    """The shop as students run it: no API keys, an admin password."""

    @classmethod
    def setUpClass(cls):
        cls.shop = ShopProcess(COFFEE_ADMIN_PASSWORD="1234",
                               COFFEE_EXTRA_HEADERS='{"X-Clue": "beans"}')

    @classmethod
    def tearDownClass(cls):
        cls.log = cls.shop.stop()

    def test_home_page(self):
        status, body, r = self.shop.call("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn(socket.gethostname(), body)
        self.assertIn("not on EC2", body)
        self.assertEqual(r.getheader("Server"), "coffee-shop/1.2")
        self.assertIn("1.2", body)

    def test_health(self):
        self.assertEqual(self.shop.call("GET", "/health")[:2], (200, "OK\n"))

    def test_menu_has_latte_at_4_50(self):
        status, body, _ = self.shop.call("GET", "/menu")
        self.assertEqual(status, 200)
        self.assertIn({"drink": "latte", "size": "M", "price": 4.5},
                      body["menu"])

    def test_cookie_is_missing_its_flags(self):
        _, _, r = self.shop.call("GET", "/menu")
        cookie = r.getheader("Set-Cookie")
        self.assertTrue(cookie.startswith("session="))
        for flag in ("HttpOnly", "Secure", "SameSite"):
            self.assertNotIn(flag, cookie)
        _, _, r = self.shop.call("GET", "/menu",
                                 headers={"Cookie": "session=abc"})
        self.assertIsNone(r.getheader("Set-Cookie"))

    def test_extra_headers(self):
        _, _, r = self.shop.call("GET", "/health")
        self.assertEqual(r.getheader("X-Clue"), "beans")

    def test_order_life_cycle(self):
        order = {"drink": "latte", "size": "M", "to_go": True}
        status, body, r = self.shop.call("POST", "/orders", order)
        self.assertEqual(status, 201)
        oid = body["id"]
        self.assertEqual(r.getheader("Location"), "/orders/%d" % oid)
        self.assertEqual(body["price"], 4.5)
        self.assertTrue(body["to_go"])

        # Same order again: a second latte (POST is not idempotent).
        status, body2, _ = self.shop.call("POST", "/orders", order)
        self.assertEqual(status, 201)
        self.assertEqual(body2["id"], oid + 1)

        status, body, _ = self.shop.call("GET", "/orders/%d" % oid)
        self.assertEqual((status, body["drink"]), (200, "latte"))
        ids = [o["id"] for o in self.shop.call("GET", "/orders")[1]["orders"]]
        self.assertIn(oid, ids)
        self.assertIn(oid + 1, ids)

        status, body, _ = self.shop.call(
            "PUT", "/orders/%d" % oid, {"drink": "karak", "size": "S"})
        self.assertEqual((status, body["drink"], body["price"]),
                         (200, "karak", 2.0))

        status, body, r = self.shop.call("DELETE", "/orders/%d" % oid)
        self.assertEqual((status, body), (204, ""))
        self.assertIsNone(r.getheader("Content-Length"))
        self.assertEqual(self.shop.call("GET", "/orders/%d" % oid)[0], 404)

    def test_bad_requests(self):
        self.assertEqual(self.shop.call(
            "POST", "/orders", {"drink": "mocha"})[0], 400)
        self.assertEqual(self.shop.call(
            "POST", "/orders", {"drink": "espresso", "size": "L"})[0], 400)
        self.assertEqual(self.shop.call(
            "POST", "/orders", b"not json")[0], 400)
        self.assertEqual(self.shop.call("POST", "/orders", [1, 2])[0], 400)
        self.assertEqual(self.shop.call("GET", "/nothing")[0], 404)
        self.assertEqual(self.shop.call("GET", "/orders/999999")[0], 404)
        self.assertEqual(self.shop.call("GET", "/giftcards")[0], 405)
        self.assertEqual(self.shop.call("GET", "/giftcards/GC-NOPE")[0], 404)

    def test_gift_card_one_at_a_time(self):
        status, card, r = self.shop.call("POST", "/giftcards")
        self.assertEqual((status, card["balance"]), (201, 5.0))
        url = "/giftcards/" + card["code"]
        self.assertEqual(r.getheader("Location"), url)
        latte = {"drink": "latte", "size": "M"}
        status, body, _ = self.shop.call("POST", url + "/redeem", latte)
        self.assertEqual((status, body["balance"]), (200, 0.5))
        status, body, _ = self.shop.call("POST", url + "/redeem", latte)
        self.assertEqual((status, body["balance"]), (402, 0.5))
        self.assertEqual(self.shop.call("GET", url)[1]["balance"], 0.5)

    def test_race_script_overspends_the_card(self):
        out = subprocess.run(
            [sys.executable, os.path.join(HERE, "race.py"),
             "127.0.0.1:%d" % self.shop.port, "10"],
            capture_output=True, text=True, timeout=30)
        out = out.stdout + out.stderr
        accepted = int(out.split("Lattes accepted:")[1].split()[0])
        final = float(out.split("Final balance:")[1].split()[0])
        self.assertGreater(accepted, 1, out)
        self.assertLess(final, 0, out)
        self.assertAlmostEqual(final, 5.0 - 4.5 * accepted, places=2)

    def test_admin_reset(self):
        self.shop.call("POST", "/orders", {"drink": "espresso", "size": "S"})
        self.assertEqual(self.shop.call("POST", "/admin/reset")[0], 403)
        self.assertEqual(self.shop.call(
            "POST", "/admin/reset", headers={"X-Admin-Password": "0000"})[0],
            403)
        status, body, _ = self.shop.call(
            "POST", "/admin/reset", headers={"X-Admin-Password": "1234"})
        self.assertEqual((status, body["reset"]), (200, True))
        self.assertEqual(self.shop.call("GET", "/orders")[1]["orders"], [])

    def test_head(self):
        status, body, r = self.shop.call("HEAD", "/menu")
        self.assertEqual((status, body), (200, ""))
        self.assertGreater(int(r.getheader("Content-Length")), 0)


class NoPassword(unittest.TestCase):
    def test_admin_is_off_without_a_password(self):
        shop = ShopProcess()
        try:
            self.assertEqual(shop.call(
                "POST", "/admin/reset", headers={"X-Admin-Password": ""})[0],
                404)
        finally:
            shop.stop()


class KeyedShop(unittest.TestCase):
    """The shop as the TAs run it for Lab 2.1: API keys and a rate limit."""

    @classmethod
    def setUpClass(cls):
        cls.keys = tempfile.NamedTemporaryFile("w", suffix=".txt",
                                               delete=False)
        cls.keys.write("# key name\nkey-aaa student01\nkey-bbb student02\n")
        cls.keys.close()
        cls.shop = ShopProcess(COFFEE_API_KEYS=cls.keys.name,
                               COFFEE_RATE_LIMIT="40",
                               COFFEE_TRUST_PROXY="1")

    @classmethod
    def tearDownClass(cls):
        cls.shop.stop()
        os.unlink(cls.keys.name)

    def test_keys_and_object_level_authorization(self):
        A = {"X-API-Key": "key-aaa"}
        B = {"X-API-Key": "key-bbb"}
        self.assertEqual(self.shop.call("GET", "/menu")[0], 200)
        self.assertEqual(self.shop.call("GET", "/orders")[0], 401)
        self.assertEqual(self.shop.call(
            "GET", "/orders", headers={"X-API-Key": "wrong"})[0], 401)

        status, order, _ = self.shop.call(
            "POST", "/orders", {"drink": "latte"}, A)
        self.assertEqual((status, order["owner"]), (201, "student01"))
        path = "/orders/%d" % order["id"]

        # The bug: B can read A's order...
        status, body, _ = self.shop.call("GET", path, headers=B)
        self.assertEqual((status, body["owner"]), (200, "student01"))
        # ...but cannot list, change or delete it.
        self.assertEqual(self.shop.call("GET", "/orders",
                                        headers=B)[1]["orders"], [])
        self.assertEqual(self.shop.call(
            "PUT", path, {"drink": "karak"}, B)[0], 404)
        self.assertEqual(self.shop.call("DELETE", path, headers=B)[0], 404)
        self.assertEqual(self.shop.call("DELETE", path, headers=A)[0], 204)

    def test_rate_limit_per_client(self):
        ip = {"X-Forwarded-For": "203.0.113.9"}
        codes = [self.shop.call("GET", "/health", headers=ip)[0]
                 for _ in range(42)]
        self.assertEqual(codes[:40], [200] * 40)
        self.assertEqual(codes[40:], [429, 429])
        other = {"X-Forwarded-For": "203.0.113.10"}
        self.assertEqual(self.shop.call("GET", "/health",
                                        headers=other)[0], 200)


def fault_file(text):
    """A fault switch file, as the monkey writes it on EC2."""
    f = tempfile.NamedTemporaryFile("w", suffix=".fault", delete=False)
    f.write(text)
    f.close()
    return f.name


def at_once(n, fn):
    """Run fn(i) for i in range(n) in threads that start together."""
    results = [None] * n
    start = threading.Barrier(n)

    def run(i):
        start.wait()
        results[i] = fn(i)

    threads = [threading.Thread(target=run, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return results


class ServedBy(unittest.TestCase):
    """Lab 4.1: the scoreboard needs to know which server answered."""

    @classmethod
    def setUpClass(cls):
        cls.shop = ShopProcess()

    @classmethod
    def tearDownClass(cls):
        cls.shop.stop()

    def test_every_answer_names_the_server(self):
        # Off EC2 there is no instance ID: hostname and port instead.
        me = "%s:%d" % (socket.gethostname(), self.shop.port)
        for method, path in [("GET", "/health"), ("GET", "/menu"),
                             ("GET", "/nothing")]:
            _, _, r = self.shop.call(method, path)
            self.assertEqual(r.getheader("X-Served-By"), me, path)
        _, _, r = self.shop.call("POST", "/orders", {"drink": "latte"})
        self.assertEqual(r.getheader("X-Served-By"), me)

    def test_deep_health_check(self):
        self.assertEqual(self.shop.call("GET", "/health/deep")[:2],
                         (200, "OK\n"))

    def test_no_fault_file_means_no_fault(self):
        status, body, _ = self.shop.call("POST", "/orders",
                                         {"drink": "latte", "size": "M"})
        self.assertEqual((status, body["price"]), (201, 4.5))


class Liar(unittest.TestCase):
    """Lab 4.1, incident 4: a server that charges the wrong price."""

    @classmethod
    def setUpClass(cls):
        cls.fault = fault_file("liar\n")
        cls.shop = ShopProcess(COFFEE_FAULT_FILE=cls.fault)

    @classmethod
    def tearDownClass(cls):
        cls.shop.stop()
        os.unlink(cls.fault)

    def test_orders_cost_a_tenth(self):
        status, body, _ = self.shop.call("POST", "/orders",
                                         {"drink": "latte", "size": "M"})
        self.assertEqual((status, body["price"]), (201, 0.45))

    def test_menu_and_health_checks_look_fine(self):
        _, body, _ = self.shop.call("GET", "/menu")
        self.assertIn({"drink": "latte", "size": "M", "price": 4.5},
                      body["menu"])
        self.assertEqual(self.shop.call("GET", "/health")[:2], (200, "OK\n"))
        self.assertEqual(self.shop.call("GET", "/health/deep")[:2],
                         (200, "OK\n"))


class Slow(unittest.TestCase):
    """Lab 4.1, incident 2: orders are slow, /health is not."""

    @classmethod
    def setUpClass(cls):
        cls.fault = fault_file("slow")
        cls.shop = ShopProcess(COFFEE_FAULT_FILE=cls.fault,
                               COFFEE_SLOW_SECONDS="0.5",
                               COFFEE_BARISTAS="1",
                               COFFEE_BREW_SECONDS="0.01")

    @classmethod
    def tearDownClass(cls):
        cls.shop.stop()
        os.unlink(cls.fault)

    def timed(self, method, path, body=None):
        t = time.monotonic()
        status = self.shop.call(method, path, body)[0]
        return status, time.monotonic() - t

    def test_orders_are_slow(self):
        status, took = self.timed("POST", "/orders", {"drink": "latte"})
        self.assertEqual(status, 201)
        self.assertGreaterEqual(took, 0.5)

    def test_health_is_fast_but_deep_health_is_slow(self):
        status, took = self.timed("GET", "/health")
        self.assertEqual(status, 200)
        self.assertLess(took, 0.2)
        status, took = self.timed("GET", "/health/deep")
        self.assertEqual(status, 200)
        self.assertGreaterEqual(took, 0.5)

    def test_slowness_does_not_hold_a_barista(self):
        # One barista, three slow orders at once: they wait side by side,
        # so the slow server shows "slow", not "busy".
        t = time.monotonic()
        codes = at_once(3, lambda i: self.shop.call(
            "POST", "/orders", {"drink": "latte"})[0])
        self.assertEqual(codes, [201, 201, 201])
        self.assertLess(time.monotonic() - t, 1.0)

    def test_fault_file_is_read_on_every_request(self):
        with open(self.fault, "w") as f:
            f.write("")
        try:
            status, took = self.timed("POST", "/orders", {"drink": "latte"})
            self.assertEqual(status, 201)
            self.assertLess(took, 0.3)
        finally:
            with open(self.fault, "w") as f:
                f.write("slow")


class Baristas(unittest.TestCase):
    """Lab 4.1, incident 3: a server makes a few coffees at a time, lets a
    few customers wait, and sends the others away at once (load shedding,
    Day 4 slide 52)."""

    @classmethod
    def setUpClass(cls):
        cls.shop = ShopProcess(COFFEE_BARISTAS="1",
                               COFFEE_BREW_SECONDS="0.3",
                               COFFEE_QUEUE="2")

    @classmethod
    def tearDownClass(cls):
        cls.shop.stop()

    def test_full_shop_says_busy_at_once(self):
        def order(i):
            t = time.monotonic()
            status, body, _ = self.shop.call("POST", "/orders",
                                             {"drink": "latte"})
            return status, body, time.monotonic() - t

        results = at_once(6, order)
        made = [r for r in results if r[0] == 201]
        busy = [r for r in results if r[0] == 503]
        # 1 being made + 2 waiting; the other 3 are sent away.
        self.assertEqual((len(made), len(busy)), (3, 3), results)
        for _, body, took in busy:
            self.assertEqual(body["error"], "too busy, come back later")
            self.assertLess(took, 0.2)

    def test_deep_health_does_not_wait_in_line(self):
        def call(i):
            if i == 0:
                time.sleep(0.05)      # the orders are in line first
                t = time.monotonic()
                status = self.shop.call("GET", "/health/deep")[0]
                return status, time.monotonic() - t
            return self.shop.call("POST", "/orders", {"drink": "latte"})[0]

        results = at_once(4, call)
        status, took = results[0]
        self.assertEqual(status, 200)
        self.assertLess(took, 0.2)


class NoBrewing(unittest.TestCase):
    """Without COFFEE_BREW_SECONDS, the shop behaves as in v1.1."""

    def test_many_orders_at_once_are_all_made(self):
        shop = ShopProcess()
        try:
            codes = at_once(20, lambda i: shop.call(
                "POST", "/orders", {"drink": "karak", "size": "S"})[0])
            self.assertEqual(codes, [201] * 20)
        finally:
            shop.stop()


if __name__ == "__main__":
    unittest.main()
