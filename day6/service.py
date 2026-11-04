"""What the three services of Lab 6 share (Day 6): a small HTTP server that
reads form fields and answers JSON, a SQLite connection, and a client to
call the other services. Standard library only.

Every service listens on 127.0.0.1 only: in CloudShell, nobody else can
reach it.
"""

import json
import os
import sqlite3
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
PORTS = {"orders": 8000, "payments": 8001, "stock": 8002}
MAX_BODY = 10000               # bytes


def connect(name):
    """One connection per request. Autocommit: BEGIN ... COMMIT by hand."""
    db = sqlite3.connect(os.path.join(HERE, name), timeout=10,
                         isolation_level=None)
    db.row_factory = sqlite3.Row
    return db


def money(cents):
    return "%d.%02d" % (cents // 100, cents % 100)


def pretty(body):
    """JSON with one line per list item, so that a table fits a terminal."""
    if not isinstance(body, dict):
        return json.dumps(body)
    lines = []
    for key, value in body.items():
        if isinstance(value, list) and value:
            items = ",\n".join("    " + json.dumps(v) for v in value)
            lines.append("  %s: [\n%s\n  ]" % (json.dumps(key), items))
        else:
            lines.append("  %s: %s" % (json.dumps(key), json.dumps(value)))
    return "{\n" + ",\n".join(lines) + "\n}"


def call(service, path, **fields):
    """POST form fields to another service. Returns (status, JSON body).
    A service that does not answer gives (503, {"error": ...})."""
    data = urllib.parse.urlencode(fields).encode()
    url = "http://127.0.0.1:%d%s" % (PORTS[service], path)
    try:
        with urllib.request.urlopen(url, data, timeout=5) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")
    except OSError as e:
        return 503, {"error": "%s does not answer (%s)" % (service, e)}


class Handler(BaseHTTPRequestHandler):
    """Subclasses fill ROUTES: {("GET", "/path"): "method_name"}."""

    ROUTES = {}
    NAME = "service"

    def version_string(self):
        return "coffee-" + self.NAME

    def send(self, status, body):
        data = (pretty(body) + "\n").encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def error(self, status, message):
        self.send(status, {"error": message})

    def handle_any(self, method):
        url = urllib.parse.urlsplit(self.path)
        # Form fields from the URL (?a=1) and, for POST, from the body.
        self.args = dict(urllib.parse.parse_qsl(url.query))
        if method == "POST":
            length = int(self.headers.get("Content-Length") or 0)
            if length > MAX_BODY:
                return self.error(400, "body too large")
            body = self.rfile.read(length).decode("utf-8", "replace")
            self.args.update(urllib.parse.parse_qsl(body))
        name = self.ROUTES.get((method, url.path.rstrip("/") or "/"))
        if name is None:
            return self.error(404, "no such page: %s %s" % (method, url.path))
        try:
            getattr(self, name)()
        except sqlite3.Error as e:
            # The database's own error message goes back to the client.
            # A real service would log it and say less.
            self.error(500, "database error: %s" % e)

    def do_GET(self):
        self.handle_any("GET")

    def do_POST(self):
        self.handle_any("POST")

    def health(self):
        self.send(200, {"status": "OK", "service": self.NAME})

    def log_message(self, fmt, *args):
        sys.stderr.write("%s %s %s\n" % (
            time.strftime("%H:%M:%S"), self.NAME, fmt % args))


def serve(handler):
    port = PORTS[handler.NAME]
    server = ThreadingHTTPServer(("127.0.0.1", port), handler)
    server.daemon_threads = True
    print("%s %s listening on 127.0.0.1:%d" % (
        time.strftime("%H:%M:%S"), handler.NAME, port), flush=True)
    server.serve_forever()
