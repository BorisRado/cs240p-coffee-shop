#!/usr/bin/env python3
"""Lab 8: calls the menu function and shows what happened.

  python3 calls.py one-by-one 5 URL LOG   five calls, one after the other
  python3 calls.py at-once 30 URL LOG     thirty calls at the same moment

Each answer is one of: served (HTTP 200, with the instance that served
it), throttled (HTTP 429: Lambda refused to start one more instance), or
another error. One line goes to LOG for the final check.
Python 3.9 standard library only (CloudShell).
"""

import json
import sys
import threading
import time
import urllib.error
import urllib.request


def call(url):
    """Returns (HTTP status, seconds, answer as a dict or None)."""
    t = time.time()
    try:
        with urllib.request.urlopen(url, timeout=30) as r:
            status, body = r.status, r.read()
    except urllib.error.HTTPError as e:
        status, body = e.code, e.read()
    except Exception as e:
        return 0, time.time() - t, {"error": str(e)}
    try:
        data = json.loads(body)
    except ValueError:
        data = None
    return status, time.time() - t, data


def log(path, line):
    with open(path, "a") as f:
        f.write(time.strftime("%Y-%m-%dT%H:%M:%SZ ", time.gmtime()) + line
                + "\n")


def one_by_one(n, url, path):
    for i in range(1, n + 1):
        status, secs, data = call(url)
        data = data or {}
        print("Call %d: %5.2f s  HTTP %d  instance %s, its request number %s"
              % (i, secs, status, data.get("instance", "?"),
                 data.get("requests_served_by_this_instance", "?")))
        log(path, "one-by-one call=%d status=%d secs=%.2f n=%s"
            % (i, status, secs, data.get("requests_served_by_this_instance",
                                         0)))


def at_once(n, url, path):
    results = [None] * n
    start = threading.Barrier(n)

    def worker(i):
        start.wait()
        results[i] = call(url)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    served = [r for r in results if r[0] == 200]
    throttled = [r for r in results if r[0] == 429]
    other = [r for r in results if r[0] not in (200, 429)]
    instances = {(r[2] or {}).get("instance") for r in served}
    print("%d requests at the same moment:" % n)
    print("  served (HTTP 200):     %d, by %d different instances"
          % (len(served), len(instances)))
    print("  throttled (HTTP 429):  %d" % len(throttled))
    if other:
        print("  other errors:          %d, for example: HTTP %d %s"
              % (len(other), other[0][0], other[0][2]))
    log(path, "at-once %d requests, %d served, %d throttled, %d instances"
        % (n, len(served), len(throttled), len(instances)))


if __name__ == "__main__":
    mode, n, url, path = sys.argv[1], int(sys.argv[2]), sys.argv[3], \
        sys.argv[4]
    {"one-by-one": one_by_one, "at-once": at_once}[mode](n, url, path)
