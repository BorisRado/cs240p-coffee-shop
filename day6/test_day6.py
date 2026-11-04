"""Tests for Lab 6. Run, in day6/:  python3 -m unittest -v test_day6

Copies day6/ to a temporary folder, starts the three services there on
their real ports (8000-8002 must be free), and plays the lab's steps.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
SAFE = '    return db.execute("SELECT * FROM orders WHERE customer = ?", ' \
       '(name,))\n'
ATTACK = "x' OR '1'='1"


def http(path, data=None, token=None):
    req = urllib.request.Request("http://127.0.0.1:8000" + path, data=(
        urllib.parse.urlencode(data).encode() if data else None))
    if token:
        req.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def run(*cmd, cwd):
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True,
                          check=True).stdout


class Lab6(unittest.TestCase):
    def setUp(self):
        self.dir = os.path.join(tempfile.mkdtemp(), "lab-6")
        shutil.copytree(HERE, self.dir, ignore=shutil.ignore_patterns(
            "*.db", "logs", "admin.log", "__pycache__"))
        out = run("./start.sh", cwd=self.dir)
        self.assertEqual(out.count(": OK"), 3, out)

    def tearDown(self):
        run("./stop.sh", cwd=self.dir)
        shutil.rmtree(os.path.dirname(self.dir))

    def restart(self):
        out = run("./start.sh", cwd=self.dir)
        self.assertEqual(out.count(": OK"), 3, out)

    def check(self):
        out = run(sys.executable, "check.py", cwd=self.dir)
        return dict(line.split(":", 1) for line in out.splitlines())

    def test_injection_and_fix(self):
        self.assertEqual(len(http("/orders?customer=emi")[1]["orders"]), 2)
        q = urllib.parse.urlencode({"customer": ATTACK})
        self.assertEqual(len(http("/orders?" + q)[1]["orders"]), 9)
        path = os.path.join(self.dir, "orders.py")
        lines = open(path).readlines()
        self.assertIn("customer = '\" + name", lines[31])   # line 32
        lines[31] = SAFE
        open(path, "w").writelines(lines)
        self.restart()
        status, body = http("/orders?" + q)
        self.assertEqual((status, body["orders"]), (200, []))
        self.assertEqual(body["params"], [ATTACK])
        self.assertEqual(len(http("/orders?customer=emi")[1]["orders"]), 2)
        self.assertEqual(self.check()["Injection returns"].strip(), "0 rows")

    def test_saga(self):
        status, body = http("/orders", {"customer": "emi", "drink": "latte"})
        self.assertEqual((status, body["status"]), (201, "done"))
        status, body = http("/orders", {"customer": "emi",
                                        "drink": "oat-latte"})
        self.assertEqual((status, body["status"]), (409, "cancelled"))
        self.assertIn("out of oat milk", body["saga"][1])
        self.assertIn("refunded 5.00", body["saga"][2])
        peek = run(sys.executable, "peek.py", cwd=self.dir)
        self.assertIn("refund  -5.00", peek)
        self.assertIn("beans     39", peek)       # the rollback kept beans
        self.assertEqual(self.check()["Saga refunds"].strip(), "1")

    def test_pause_shows_half_done_order(self):
        proc = subprocess.Popen(
            ["curl", "-s", "localhost:8000/orders", "-d", "customer=emi",
             "-d", "drink=latte", "-d", "pause=3"], stdout=subprocess.PIPE)
        time.sleep(1.5)
        peek = run(sys.executable, "peek.py", cwd=self.dir)
        ref = peek.split("charge")[0].split()[-2]
        self.assertTrue(ref.startswith("o-"))
        self.assertNotIn(ref, peek.split("orders.db")[1])
        proc.wait()
        peek = run(sys.executable, "peek.py", cwd=self.dir)
        self.assertIn(ref, peek.split("orders.db")[1])

    def test_jwt_crack_forge_and_new_secret(self):
        _, body = http("/login", {"user": "emi", "password": "latte2026"})
        token = body["token"]
        self.assertEqual(http("/admin/sales", token=token)[0], 403)
        out = run(sys.executable, "crack.py", token, "wordlist.txt",
                  cwd=self.dir)
        self.assertIn("Found the secret: arabica", out)
        forged = run(sys.executable, "forge.py", token, "arabica",
                     cwd=self.dir).strip()
        self.assertEqual(http("/admin/sales", token=forged)[0], 200)
        self.assertEqual(self.check()["Forged admin calls"].strip(), "1")
        self.assertEqual(self.check()["Secret in wordlist"].strip(), "yes")
        subprocess.run("head -c 32 /dev/urandom | base64 > jwt-secret",
                       shell=True, cwd=self.dir, check=True)
        self.restart()
        self.assertEqual(http("/admin/sales", token=forged),
                         (401, {"error": "bad signature"}))
        self.assertEqual(http("/admin/sales", token=token)[0], 401)
        _, body = http("/login", {"user": "emi", "password": "latte2026"})
        self.assertIn("Not found", run(sys.executable, "crack.py",
                                       body["token"], "wordlist.txt",
                                       cwd=self.dir))
        self.assertEqual(self.check()["Secret in wordlist"].strip(), "no")
        none = run(sys.executable, "forge.py", token, "--none",
                   cwd=self.dir).strip()
        self.assertEqual(http("/admin/sales", token=none)[0], 200)

    def test_menu_union(self):
        q = urllib.parse.urlencode(
            {"search": "x' UNION SELECT name, password FROM users --"})
        self.assertIn(["noura", "Barista#1"], http("/menu?" + q)[1]["menu"])

    def test_check_after_stop(self):
        run("./stop.sh", cwd=self.dir)
        c = self.check()
        self.assertEqual(c["Services running"].strip(), "0")
        self.assertEqual(c["Injection returns"].strip(), "9 rows")


if __name__ == "__main__":
    unittest.main()
