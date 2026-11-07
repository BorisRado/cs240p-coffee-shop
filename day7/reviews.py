#!/usr/bin/env python3
"""Lab 7: the coffee shop's reviews page, with two bugs on purpose.

Written for CS 240P (KAUST, Fall 2026). Python 3.9 standard library only,
so it runs on a fresh Amazon Linux 2023 server with no pip install. All
data is in memory. Orders are written to S3 with the `aws` CLI, using the
instance's role (no keys in this file).

BUGS ON PURPOSE (Day 7, slides "Attack: Cross-site scripting (XSS)" and
"Summary: Attacks and defenses"). Students read the page source in
Step 3.1, so the served JavaScript has no BUG/FIX comments:
  1. The reviews page builds each review with `innerHTML`, so a review
     that contains HTML is run as HTML, not shown as text (XSS).
  2. The session cookie is set without the `HttpOnly` flag, so a script
     on the page can read it with `document.cookie`.

Both are controlled by SECURE (off by default). The lab's fix turns
SECURE on: the page then uses `textContent`, and the cookie gets
`HttpOnly; SameSite=Lax`. In real life those are two code changes; here
the owner "ships the fix" with one request to /admin/config, so students
do not edit files on the server.

    POST /admin/config  (header X-Admin-Password)  secure=on | secure=off

Environment:
  ORDERS_BUCKET          where /checkout writes an order (optional)
  COFFEE_ADMIN_PASSWORD  the password for /admin/config (default below)
  PORT                   default 80
"""
import json
import os
import secrets
import subprocess
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

ADMIN_PASSWORD = os.environ.get("COFFEE_ADMIN_PASSWORD", "barista2019")
ORDERS_BUCKET = os.environ.get("ORDERS_BUCKET", "")
PORT = int(os.environ.get("PORT", "80"))

STATE = {
    "secure": os.environ.get("SECURE", "") not in ("", "0", "off", "false"),
    "reviews": [
        "Best karak in Riyadh, I come every morning.",
        "The latte art is beautiful. Friendly staff.",
    ],
    "sessions": {},        # cookie token -> created time
    "order_no": 0,
}

PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>The Coffee Shop - reviews</title>
<style>
 body{{font-family:system-ui,Arial,sans-serif;max-width:40em;margin:2em auto;
      padding:0 1em;color:#222}}
 h1{{color:#6f4e37}} li{{margin:.4em 0;border-bottom:1px solid #eee;padding:.4em 0}}
 input,button{{font-size:1em;padding:.4em}} #note{{color:#a00}}
</style></head><body>
<h1>The Coffee Shop</h1>
<p>Tell us what you think. Your review is shown to every visitor.</p>
<form id="f"><input id="t" name="text" size="40"
  placeholder="Write a review..."><button>Post</button></form>
<h2>Reviews</h2>
<ul id="reviews"></ul>
<p id="note"></p>
<script>
var SECURE = {secure};
function render(list) {{
  var ul = document.getElementById("reviews");
  ul.textContent = "";
  for (var i = 0; i < list.length; i++) {{
    var li = document.createElement("li");
    if (SECURE) {{
      li.textContent = list[i];
    }} else {{
      li.innerHTML = list[i];
    }}
    ul.appendChild(li);
  }}
}}
function load() {{
  fetch("/reviews").then(function(r){{return r.json();}}).then(render);
}}
document.getElementById("f").onsubmit = function(e) {{
  e.preventDefault();
  var t = document.getElementById("t").value;
  fetch("/review", {{method:"POST", headers:
    {{"Content-Type":"application/x-www-form-urlencoded"}},
    body:"text=" + encodeURIComponent(t)}}).then(function(){{
      document.getElementById("t").value = ""; load();}});
}};
load();
</script>
</body></html>
"""


class Handler(BaseHTTPRequestHandler):
    server_version = "CoffeeReviews/3.0"

    def log_message(self, *a):                   # keep the console quiet
        pass

    def _send(self, code, body, ctype="text/html; charset=utf-8",
              cookie=None):
        data = body.encode() if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.end_headers()
        self.wfile.write(data)

    def _session_cookie(self):
        """Return a Set-Cookie value if the caller has no session yet."""
        got = self.headers.get("Cookie", "")
        for part in got.split(";"):
            if part.strip().startswith("session="):
                return None
        token = secrets.token_hex(16)
        STATE["sessions"][token] = time.time()
        if STATE["secure"]:
            return "session=%s; Path=/; HttpOnly; SameSite=Lax" % token
        return "session=%s; Path=/" % token      # BUG: no HttpOnly

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/":
            self._send(200, PAGE.format(
                secure="true" if STATE["secure"] else "false"),
                cookie=self._session_cookie())
        elif path == "/reviews":
            self._send(200, json.dumps(STATE["reviews"]),
                       "application/json")
        elif path == "/health":
            self._send(200, "ok\n", "text/plain")
        elif path == "/mode":
            self._send(200, "secure\n" if STATE["secure"] else
                       "vulnerable\n", "text/plain")
        else:
            self._send(404, "not found\n", "text/plain")

    def _body(self):
        n = int(self.headers.get("Content-Length", "0"))
        return self.rfile.read(n).decode("utf-8", "replace") if n else ""

    def do_POST(self):
        path = urlparse(self.path).path
        if path == "/review":
            text = parse_qs(self._body()).get("text", [""])[0]
            if text.strip():
                STATE["reviews"].append(text)
            self._send(200, json.dumps({"ok": True}), "application/json")
        elif path == "/checkout":
            STATE["order_no"] += 1
            order = {"order": STATE["order_no"], "drink": "latte",
                     "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
            saved = "not saved (no bucket set)"
            if ORDERS_BUCKET:
                key = "orders/%05d.json" % STATE["order_no"]
                dest = "s3://%s/%s" % (ORDERS_BUCKET, key)
                p = subprocess.run(["aws", "s3", "cp", "-", dest,
                                    "--content-type", "application/json"],
                                   input=json.dumps(order), text=True,
                                   capture_output=True, timeout=20)
                saved = dest if p.returncode == 0 else \
                    "NOT saved: " + (p.stderr or "").strip()[:200]
            self._send(200, json.dumps({"order": order, "saved": saved}),
                       "application/json")
        elif path == "/admin/config":
            if self.headers.get("X-Admin-Password") != ADMIN_PASSWORD:
                self._send(403, "forbidden\n", "text/plain")
                return
            val = parse_qs(self._body()).get("secure", [""])[0]
            STATE["secure"] = val in ("on", "1", "true")
            self._send(200, "secure\n" if STATE["secure"] else
                       "vulnerable\n", "text/plain")
        else:
            self._send(404, "not found\n", "text/plain")


if __name__ == "__main__":
    print("reviews.py on port %d, mode=%s, bucket=%s" % (
        PORT, "secure" if STATE["secure"] else "vulnerable",
        ORDERS_BUCKET or "(none)"))
    ThreadingHTTPServer(("", PORT), Handler).serve_forever()
