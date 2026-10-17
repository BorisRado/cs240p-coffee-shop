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
        self.assertEqual(r.getheader("Server"), "coffee-shop/1.0")

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


if __name__ == "__main__":
    unittest.main()
