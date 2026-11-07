"""Tests for Lab 8. Run, in day8/, on Linux (it reads /proc/self/environ):

  python3 -m unittest -v test_day8

No AWS. A local server plays the function URL: it runs menu.py's
lambda_handler for each request, with fake role keys in its environment,
and answers HTTP 429 when more than LIMIT requests run at once (the
account's concurrency limit). A fake `aws` command on the PATH plays the
AWS CLI for the scripts. What these tests cannot check (the console, the
real function URL, IAM) is in the dry-run list of the handout.
"""

import base64
import http.server
import importlib.util
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
KEYS = {"AWS_ACCESS_KEY_ID": "ASIAFAKEFAKEFAKE1234",
        "AWS_SECRET_ACCESS_KEY": "fakeSecret/abc+def=",
        "AWS_SESSION_TOKEN": "IQoJb3JpZ2luX2VjEFAKE/token+=="}
# The answer key of Step 3.6: two lines just below "if photo:".
FIX = ('        if not photo.startswith("https://"):\n'
       '            return answer(400, {"error": "https only"})\n')
LIMIT = 10


def load_menu(path):
    spec = importlib.util.spec_from_file_location("menu", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class Context:
    def __init__(self, n):
        self.log_stream_name = "2026/11/08/[$LATEST]abcdef%08d" % n


def serve(menu_path, port):
    """The fake function URL (runs in its own process)."""
    menu = load_menu(menu_path)
    lock = threading.Lock()
    state = {"running": 0}

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            q = urllib.parse.urlsplit(self.path).query
            params = dict(urllib.parse.parse_qsl(q)) or None
            with lock:
                if state["running"] >= LIMIT:
                    self.send_response(429)
                    self.end_headers()
                    self.wfile.write(b'{"Message":"Rate Exceeded."}')
                    return
                state["running"] += 1
                n = state["running"]
            try:
                r = menu.lambda_handler({"queryStringParameters": params},
                                        Context(n))
            finally:
                with lock:
                    state["running"] -= 1
            body = r["body"]
            body = (base64.b64decode(body) if r.get("isBase64Encoded")
                    else body.encode())
            self.send_response(r["statusCode"])
            self.end_headers()
            self.wfile.write(body)

    http.server.ThreadingHTTPServer(("127.0.0.1", port),
                                    Handler).serve_forever()


FAKE_AWS = r'''#!/bin/bash
# Fake AWS CLI for test_day8. State lives in $STATE.
args="$*"
case "$args" in
  "sts get-caller-identity"*)
    if [ -n "$AWS_ACCESS_KEY_ID" ]; then
      echo "arn:aws:sts::123456789012:assumed-role/coffee-menu-role-x1/coffee-menu"
    else
      echo "arn:aws:iam::123456789012:user/$FAKE_USER"
    fi ;;
  "lambda get-function-url-config"*) cat "$STATE/url" ;;
  "lambda get-function "*) [ -e "$STATE/function" ] ;;
  "lambda delete-function"*) rm "$STATE/function" ;;
  "iam list-roles"*length*) [ -e "$STATE/role" ] && echo 1 || echo 0 ;;
  "iam list-roles"*) [ -e "$STATE/role" ] && echo coffee-menu-role-x1 ;;
  "iam list-attached-role-policies"*)
    echo "arn:aws:iam::aws:policy/AmazonS3FullAccess"
    echo "arn:aws:iam::123456789012:policy/service-role/AWSLambdaBasicExecutionRole-1" ;;
  "iam detach-role-policy"*|"iam delete-role-policy"*) ;;
  "iam delete-policy"*) echo "$args" >> "$STATE/deleted-policies" ;;
  "iam list-role-policies"*) ;;
  "iam delete-role"*) rm "$STATE/role" ;;
  "logs describe-log-groups"*length*) [ -e "$STATE/logs" ] && echo 1 || echo 0 ;;
  "logs describe-log-groups"*) [ -e "$STATE/logs" ] && echo /aws/lambda/x ;;
  "logs delete-log-group"*) rm "$STATE/logs" ;;
  "s3api head-bucket"*) [ -e "$STATE/bucket" ] ;;
  "s3 mb"*) touch "$STATE/bucket" ;;
  "s3 cp"*|"s3 ls"*)
    if [ -n "$AWS_ACCESS_KEY_ID" ] && [ -e "$STATE/role-fixed" ]; then
      echo "An error occurred (AccessDenied) when calling the ListObjectsV2 operation" >&2
      exit 254
    fi
    echo "2026-11-08 10:00:00   1234 orders.json" ;;
  "s3 rb"*) rm "$STATE/bucket" ;;
  *) echo "fake aws: unknown: $args" >&2; exit 2 ;;
esac
'''


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


class MenuTests(unittest.TestCase):
    def setUp(self):
        self.menu = load_menu(os.path.join(HERE, "menu.py"))

    def test_menu_counts_requests_per_instance(self):
        a = json.loads(self.menu.lambda_handler({}, Context(1))["body"])
        b = json.loads(self.menu.lambda_handler(
            {"queryStringParameters": None}, Context(1))["body"])
        self.assertEqual(a["menu"]["latte"], 4.50)
        self.assertEqual(a["requests_served_by_this_instance"], 1)
        self.assertEqual(b["requests_served_by_this_instance"], 2)
        self.assertEqual(len(a["instance"]), 8)

    def test_wait_is_capped(self):
        t = time.time()
        self.menu.lambda_handler({"queryStringParameters": {"wait": "0.3"}},
                                 Context(1))
        self.assertGreater(time.time() - t, 0.25)

    def test_photo_reads_a_local_file(self):
        with tempfile.NamedTemporaryFile("wb", delete=False) as f:
            f.write(b"secret\0stuff")
        r = self.menu.lambda_handler(
            {"queryStringParameters": {"photo": "file://" + f.name}},
            Context(1))
        self.assertEqual(base64.b64decode(r["body"]), b"secret\0stuff")
        os.unlink(f.name)

    def test_bad_photo_is_a_502(self):
        r = self.menu.lambda_handler(
            {"queryStringParameters": {"photo": "file:///no/such/file"}},
            Context(1))
        self.assertEqual(r["statusCode"], 502)

    def test_the_fix_refuses_file_and_fits_python(self):
        src = open(os.path.join(HERE, "menu.py")).read()
        anchor = "    if photo:\n"
        self.assertIn(anchor, src)
        fixed = src.replace(anchor, anchor + FIX, 1)
        d = tempfile.mkdtemp()
        p = os.path.join(d, "menu.py")
        open(p, "w").write(fixed)
        menu = load_menu(p)
        r = menu.lambda_handler(
            {"queryStringParameters": {"photo": "file:///etc/hostname"}},
            Context(1))
        self.assertEqual(r["statusCode"], 400)
        shutil.rmtree(d)

    def test_menu_code_is_short_lines(self):
        for n, line in enumerate(open(os.path.join(HERE, "menu.py")), 1):
            self.assertLessEqual(len(line.rstrip("\n")), 78, n)


@unittest.skipUnless(os.path.exists("/proc/self/environ"), "Linux only")
class ScriptTests(unittest.TestCase):
    """Plays Parts 1 to 4 with the scripts, as the handout does."""

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        for f in os.listdir(HERE):
            if f.endswith((".sh", ".py", ".json", ".txt")):
                shutil.copy(os.path.join(HERE, f), self.dir)
        self.state = os.path.join(self.dir, "state")
        os.mkdir(self.state)
        bindir = os.path.join(self.dir, "bin")
        os.mkdir(bindir)
        with open(os.path.join(bindir, "aws"), "w") as f:
            f.write(FAKE_AWS)
        os.chmod(os.path.join(bindir, "aws"), 0o755)
        for f in os.listdir(self.dir):
            if f.endswith(".sh"):
                os.chmod(os.path.join(self.dir, f), 0o755)
        self.env = dict(os.environ, PATH=bindir + ":" + os.environ["PATH"],
                        STATE=self.state, FAKE_USER="admin",
                        AWS_REGION="eu-central-1")
        for k in KEYS:
            self.env.pop(k, None)
        for f in ("function", "role", "logs"):
            open(os.path.join(self.state, f), "w").close()
        self.start_server(os.path.join(self.dir, "menu.py"))

    def start_server(self, menu_path):
        self.port = free_port()
        env = dict(os.environ, **KEYS)
        self.server = subprocess.Popen(
            [sys.executable, os.path.abspath(__file__), "serve", menu_path,
             str(self.port)], env=env)
        url = "http://127.0.0.1:%d/" % self.port
        with open(os.path.join(self.state, "url"), "w") as f:
            f.write(url + "\n")
        for _ in range(50):
            try:
                urllib.request.urlopen(url, timeout=1).read()
                return
            except OSError:
                time.sleep(0.1)
        self.fail("fake function URL did not start")

    def tearDown(self):
        self.server.kill()
        self.server.wait()
        shutil.rmtree(self.dir)

    def run_sh(self, *cmd):
        r = subprocess.run(list(cmd), cwd=self.dir, env=self.env,
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                           universal_newlines=True, timeout=60)
        return r.stdout

    def test_whole_lab(self):
        out = self.run_sh("./time-menu.sh")
        self.assertEqual(out.count("HTTP 200"), 5, out)
        self.assertIn("its request number 5", out)

        out = self.run_sh("./rush.sh")
        self.assertIn("30 requests at the same moment", out)
        self.assertIn("served (HTTP 200):     10", out)
        self.assertIn("throttled (HTTP 429):  20", out)

        out = self.run_sh("./make-bucket.sh")
        self.assertIn("coffee-orders-123456789012", out)

        out = self.run_sh("./as-menu.sh", "aws", "s3", "ls")
        self.assertIn("No stolen keys yet", out)

        out = self.run_sh("./steal.sh")
        self.assertIn("assumed-role/coffee-menu-role-x1", out, out)
        self.assertIn("AWS_SESSION_TOKEN=", out)
        saved = open(os.path.join(self.dir, "stolen-keys.txt")).read()
        self.assertIn(KEYS["AWS_SECRET_ACCESS_KEY"], saved)

        out = self.run_sh("./as-menu.sh", "aws", "s3", "ls",
                          "s3://coffee-orders-123456789012/")
        self.assertIn("orders.json", out)

        open(os.path.join(self.state, "role-fixed"), "w").close()
        out = self.run_sh("./as-menu.sh", "aws", "s3", "ls",
                          "s3://coffee-orders-123456789012/")
        self.assertIn("AccessDenied", out)

        # Step 3.6: the student's fix, deployed.
        self.server.kill()
        self.server.wait()
        p = os.path.join(self.dir, "menu.py")
        src = open(p).read().replace("    if photo:\n",
                                     "    if photo:\n" + FIX, 1)
        open(p, "w").write(src)
        self.start_server(p)
        out = self.run_sh("./steal.sh")
        self.assertIn("No keys", out)
        self.assertIn("https only", out)

        out = self.run_sh("./check.sh")
        self.assertIn("still there", out)       # before the clean-up
        out = self.run_sh("./clean-up.sh")
        self.assertIn("Deleted the function coffee-menu", out)
        self.assertIn("Deleted the role coffee-menu-role-x1", out)
        self.assertIn("Deleted the policy AWSLambdaBasicExecutionRole-1",
                      out)
        self.assertIn("Deleted the bucket coffee-orders-123456789012", out)
        dp = open(os.path.join(self.state, "deleted-policies")).read()
        self.assertNotIn("AmazonS3FullAccess", dp)

        out = self.run_sh("./check.sh")
        print("\n" + out)
        for line in ("Signed in as:          arn:aws:iam::123456789012:"
                     "user/admin",
                     "Function coffee-menu:  deleted",
                     "Roles left:            0",
                     "Orders bucket:         deleted",
                     "Log group:             deleted",
                     "Menu calls (Part 1):   5 served",
                     "Rush (Part 2):         30 requests, 10 served, "
                     "20 throttled, 10 instances",
                     "Keys stolen:           yes",
                     "Stolen keys read S3:   yes",
                     "After the role fix:    AccessDenied",
                     "After the code fix:    file:// refused"):
            self.assertIn(line, out)
        self.assertNotIn("still there", out)

        out = self.run_sh("./clean-up.sh")      # twice is safe
        self.assertIn("Clean-up done.", out)

    def test_ta_account_names(self):
        self.env["FAKE_USER"] = "Ahmed-7"
        out = self.run_sh("./make-bucket.sh")
        self.assertIn("coffee-orders-123456789012-ahmed-7", out)
        out = self.run_sh("./check.sh")
        self.assertIn("Function coffee-menu-Ahmed-7:", out)

    def test_check_before_anything(self):
        os.remove(os.path.join(self.state, "function"))
        os.remove(os.path.join(self.state, "role"))
        os.remove(os.path.join(self.state, "logs"))
        out = self.run_sh("./check.sh")
        self.assertIn("Rush (Part 2):         not run", out)
        self.assertIn("Keys stolen:           no", out)
        self.assertIn("After the role fix:    not tested", out)


if __name__ == "__main__":
    if sys.argv[1:2] == ["serve"]:
        serve(sys.argv[2], int(sys.argv[3]))
    else:
        unittest.main()
