#!/usr/bin/env python3
"""Lab 5: make the data.

Writes, in the current directory:
  logs/hour-00.log ... logs/hour-23.log   one day of the coffee shop's
                                          load-balancer logs (ALB format)
  leaderboard.csv                         the shop's public loyalty leaderboard
  orders-anon.csv                         the "anonymous" order export

The output is the same for everyone (fixed random seed), so the numbers in
the handout match what you see. Python 3 standard library only.

The logs are synthetic. Real logs contain real people's addresses.
"""
import csv
import datetime as dt
import hashlib
import os
import random

random.seed(240)

DAY = dt.datetime(2026, 11, 4)
HOST = "coffee-branch-1704127836.eu-central-1.elb.amazonaws.com"
ELB = "app/coffee-branch/50dc6c495c0c9188"
TG = ("arn:aws:elasticloadbalancing:eu-central-1:111122223333:"
      "targetgroup/coffee-branch-shops/73e2d6bc24d8a067")
TARGETS = ["10.0.1.12", "10.0.2.47"]

BROWSERS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile/15E148 "
    "Safari/604.1",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_7) Gecko/20100101 "
    "Firefox/131.0",
    "Mozilla/5.0 (Linux; Android 14; SM-S921B) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0.0.0 Mobile Safari/537.36",
]
APP_UA = ["CoffeeApp/2.3 (Android 14)", "CoffeeApp/2.3 (iOS 18)"]
MONITOR_UA = "UptimeMonitor/1.4 (+https://example.com/monitor)"
SCANNER_UA = ["Mozilla/5.0 zgrab/0.x", "python-requests/2.32.3",
              "Mozilla/5.0 (compatible; Nmap Scripting Engine; "
              "https://nmap.org/book/nse.html)"]

SCAN_PATHS = [
    "/.env", "/wp-login.php", "/admin", "/admin/", "/phpmyadmin/",
    "/.git/config", "/backup.zip", "/config.php", "/xmlrpc.php",
    "/wp-admin/", "/.aws/credentials", "/api/v1/users", "/console",
    "/manager/html", "/actuator/env", "/.DS_Store", "/db.sql",
    "/server-status", "/cgi-bin/", "/shell.php", "/login.php",
    "/old/", "/test/", "/dev/", "/.svn/entries", "/debug", "/env",
    "/id_rsa", "/.htpasswd", "/web.config", "/robots.txt", "/sitemap.xml",
] + ["/wp-content/plugins/%s/readme.txt" % p for p in (
    "akismet", "jetpack", "elementor", "woocommerce", "wpforms",
    "contact-form-7", "yoast-seo", "wordfence", "revslider", "duplicator")]
SCAN_PATHS += ["/backup-%d.zip" % y for y in range(2015, 2027)]
SCAN_PATHS += ["/%s.php" % n for n in (
    "info", "phpinfo", "test", "upload", "install", "setup", "update",
    "adminer", "wp-config.bak", "index.bak")]
SCAN_PATHS += ["/api/%s" % n for n in (
    "v1", "v2", "users", "admin", "login", "token", "keys", "config",
    "health", "debug", "swagger.json", "graphql", "metrics", "status")]
while len(SCAN_PATHS) < 300:
    SCAN_PATHS.append("/%s%d/" % (random.choice(
        ["old", "bak", "tmp", "site", "app", "data", "files"]),
        random.randint(1, 99)))
SCAN_PATHS = list(dict.fromkeys(SCAN_PATHS))  # unique, order kept


# ---------- addresses ----------

def public_ip():
    """A random address that looks public (not private, not reserved)."""
    while True:
        a = random.choice([5, 37, 46, 51, 62, 77, 78, 79, 85, 86, 87, 92,
                           94, 95, 109, 151, 176, 178, 185, 188, 212, 213])
        ip = "%d.%d.%d.%d" % (a, random.randint(1, 254),
                              random.randint(0, 255), random.randint(1, 254))
        if not ip.startswith(("192.0.2.", "198.51.100.", "203.0.113.")):
            return ip


def hex_id(n):
    return "".join(random.choice("0123456789abcdef") for _ in range(n))


# ---------- one log line ----------

def alb_line(t, ip, verb, path, status, ua, sent):
    port = random.randint(1024, 65535)
    target = random.choice(TARGETS)
    tpt = random.uniform(0.001, 0.040)
    created = t - dt.timedelta(milliseconds=random.randint(1, 30))
    rcvd = random.randint(90, 420)
    return (
        'http %s %s %s:%d %s:80 0.000 %.3f 0.000 %d %d %d %d '
        '"%s http://%s:80%s HTTP/1.1" "%s" - - %s '
        '"Root=1-%s-%s" "-" "-" 0 %s "forward" "-" "-" '
        '"%s:80" "%d" "-" "-" TID_%s'
        % (t.strftime("%Y-%m-%dT%H:%M:%S.%fZ"), ELB, ip, port, target,
           tpt, status, status, rcvd, sent, verb, HOST, path, ua, TG,
           hex_id(8), hex_id(24), created.strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
           target, status, hex_id(16)))


def at(hour, minute=None, second=None):
    """A time on DAY. Random minute and second if not given."""
    m = random.randint(0, 59) if minute is None else minute
    s = random.uniform(0, 59.999) if second is None else second
    return DAY + dt.timedelta(hours=hour, minutes=m, seconds=s)


# Customers are awake from 06:00 to 23:00, with peaks at 08:00 and 13:00.
HOUR_WEIGHTS = [1, 1, 1, 1, 1, 2, 8, 20, 30, 22, 16, 18, 26, 30, 24, 18,
                16, 18, 20, 18, 14, 10, 6, 3]


def customer_requests(ip, ua):
    n = random.randint(4, 40)
    order_ids = []
    out = []
    for _ in range(n):
        h = random.choices(range(24), HOUR_WEIGHTS)[0]
        t = at(h)
        r = random.random()
        if r < 0.28:
            verb, path, status, sent = "GET", "/", 200, 1184
        elif r < 0.33:
            verb, path, status, sent = "GET", "/favicon.ico", 404, 153
        elif r < 0.66:
            verb, path, status, sent = "GET", "/menu", 200, 812
        elif r < 0.80:
            verb, path, sent = "POST", "/orders", 221
            status = 201 if random.random() > 0.03 else 401
            order_ids.append(random.randint(1, 900))
        elif r < 0.92 and order_ids:
            verb, path, status, sent = ("GET", "/orders/%d"
                                        % random.choice(order_ids), 200, 198)
        elif order_ids and random.random() < 0.5:
            verb, path, status, sent = ("DELETE", "/orders/%d"
                                        % random.choice(order_ids), 204, 0)
        else:
            verb, path, status, sent = "GET", "/orders", 200, 640
        out.append((t, alb_line(t, ip, verb, path, status, ua, sent)))
    return out


def app_requests(ip, ua):
    """The mobile app's backend: orders all day, no mistakes."""
    out = []
    for _ in range(random.randint(1600, 2200)):
        h = random.choices(range(24), HOUR_WEIGHTS)[0]
        t = at(h)
        if random.random() < 0.55:
            verb, path, status, sent = "POST", "/orders", 201, 221
        else:
            verb, path, status, sent = ("GET", "/orders/%d"
                                        % random.randint(1, 900), 200, 198)
        out.append((t, alb_line(t, ip, verb, path, status, ua, sent)))
    return out


def monitor_requests(ip):
    """An uptime monitor: /health every 30 seconds, all day."""
    out = []
    t = DAY + dt.timedelta(seconds=random.uniform(0, 30))
    while t < DAY + dt.timedelta(days=1):
        out.append((t, alb_line(t, ip, "GET", "/health", 200, MONITOR_UA, 16)))
        t += dt.timedelta(seconds=30, milliseconds=random.randint(-200, 200))
    return out


def fast_scanner(ip, ua):
    """1 200 requests in about 10 minutes, at night."""
    out = []
    t = at(3, 12, 4)
    for _ in range(1200):
        path = random.choice(SCAN_PATHS)
        status = 404 if random.random() < 0.96 else 200
        if path in ("/robots.txt", "/sitemap.xml"):
            status = 404
        out.append((t, alb_line(t, ip, "GET", path, status, ua, 153)))
        t += dt.timedelta(milliseconds=random.randint(300, 700))
    return out


def slow_scanner(ip, ua):
    """800 requests spread over the whole day: harder to see."""
    out = []
    for _ in range(800):
        t = at(random.randint(0, 23))
        path = random.choice(SCAN_PATHS)
        status = 404 if random.random() < 0.93 else 200
        out.append((t, alb_line(t, ip, "GET", path, status, ua, 153)))
    return out


def password_guesser(ip, ua):
    """400 tries of the admin password, one path only."""
    out = []
    t = at(22, 41, 10)
    for _ in range(400):
        out.append((t, alb_line(t, ip, "POST", "/admin/reset", 403, ua, 41)))
        t += dt.timedelta(seconds=random.uniform(1.5, 4.0))
    return out


def make_logs():
    events = []
    for _ in range(2000):
        events += customer_requests(public_ip(), random.choice(BROWSERS))
    for i in range(8):
        events += app_requests("185.60.%d.%d" % (216 + i // 4, 10 + i),
                               APP_UA[i % 2])
    events += monitor_requests("151.80.44.9")
    events += monitor_requests("178.62.17.113")
    events += fast_scanner("203.0.113.7", SCANNER_UA[0])
    events += slow_scanner("198.51.100.23", SCANNER_UA[1])
    events += password_guesser("192.0.2.99", SCANNER_UA[2])
    events.sort(key=lambda e: e[0])
    os.makedirs("logs", exist_ok=True)
    files = {}
    for t, line in events:
        h = t.hour
        if h not in files:
            files[h] = open("logs/hour-%02d.log" % h, "w")
        files[h].write(line + "\n")
    for f in files.values():
        f.close()
    return len(events)


# ---------- Part B: the loyalty data ----------

FIRST = ["Abdullah", "Mohammed", "Fahad", "Khalid", "Saud", "Faisal",
         "Turki", "Omar", "Yousef", "Nasser", "Bandar", "Sultan", "Majed",
         "Rayan", "Ziyad", "Hamad", "Salman", "Ibrahim", "Waleed", "Talal",
         "Noura", "Sara", "Lama", "Reem", "Hessa", "Maha", "Dana", "Jawaher",
         "Haya", "Shaden", "Aseel", "Ghada", "Lujain", "Raghad", "Munira",
         "Amal", "Nada", "Wafa", "Layan", "Deema"]
LAST = ["Al-Qahtani", "Al-Otaibi", "Al-Harbi", "Al-Ghamdi", "Al-Shehri",
        "Al-Dossari", "Al-Zahrani", "Al-Mutairi", "Al-Subaie", "Al-Anazi",
        "Al-Shammari", "Al-Malki", "Al-Amri", "Al-Juhani", "Al-Rashidi",
        "Al-Yami", "Al-Balawi", "Al-Hazmi", "Al-Sulami", "Al-Asiri",
        "Al-Saleh", "Al-Omari", "Al-Khalidi", "Al-Faraj", "Al-Tamimi",
        "Al-Dakhil", "Al-Ruwaili", "Al-Buqami", "Al-Sharif", "Al-Hamdan"]
BRANCHES = ["KFSC", "Olaya", "Airport", "Hospital"]
DRINKS = ["espresso", "double espresso", "latte", "cappuccino", "flat white",
          "americano", "karak", "saffron latte", "cold brew", "mocha",
          "hot chocolate", "matcha latte"]
SIZES = {"S": -0.5, "M": 0.0, "L": 0.7}
PRICES = {"espresso": 3.0, "double espresso": 3.5, "latte": 4.5,
          "cappuccino": 4.5, "flat white": 4.75, "americano": 3.5,
          "karak": 2.5, "saffron latte": 5.5, "cold brew": 4.0,
          "mocha": 5.0, "hot chocolate": 4.0, "matcha latte": 5.5}
MONTH = dt.datetime(2026, 10, 1)
SALT = "cs240p-loyalty-2026"


def member_id(name):
    return hashlib.sha256((name + "|" + SALT).encode()).hexdigest()[:10]


def make_loyalty():
    names = set()
    while len(names) < 1200:
        names.add(random.choice(FIRST) + " " + random.choice(LAST))
    names = sorted(names)
    random.shuffle(names)
    customers = []
    for name in names:
        n = min(60, 1 + int(random.expovariate(1 / 14.0)))
        customers.append({"name": name, "branch": random.choices(
            BRANCHES, [40, 30, 15, 15])[0], "drink": random.choice(DRINKS),
            "n": n, "night": False})
    # The planted story: one member who only ever orders at night, at the
    # Airport branch. On the leaderboard, with a hashed ID, in the export.
    night = customers[7]
    night.update({"branch": "Airport", "drink": "double espresso",
                  "n": 52, "night": True})
    orders = []
    for c in customers:
        mid = member_id(c["name"])
        for _ in range(c["n"]):
            day = random.randint(0, 30)
            if c["night"]:
                t = MONTH + dt.timedelta(days=day, hours=1,
                                         minutes=random.randint(30, 150))
            else:
                h = random.choices(range(24), HOUR_WEIGHTS)[0]
                t = MONTH + dt.timedelta(days=day, hours=h,
                                         minutes=random.randint(0, 59))
            branch = c["branch"] if random.random() < 0.85 else \
                random.choice(BRANCHES)
            drink = c["drink"] if random.random() < 0.7 else \
                random.choice(DRINKS)
            size = random.choice(list(SIZES))
            orders.append((mid, t.strftime("%Y-%m-%d %H:%M"), branch, drink,
                           size, "%.2f" % (PRICES[drink] + SIZES[size])))
    orders.sort(key=lambda o: o[1])
    with open("orders-anon.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["member", "time", "branch", "drink", "size", "price"])
        w.writerows(orders)
    top = sorted(customers, key=lambda c: (-c["n"], c["name"]))[:200]
    with open("leaderboard.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["rank", "name", "home_branch", "favourite_drink",
                    "orders_in_october"])
        for i, c in enumerate(top, 1):
            w.writerow([i, c["name"], c["branch"], c["drink"], c["n"]])
    return len(orders), len(top)


if __name__ == "__main__":
    n = make_logs()
    print("logs/hour-00.log ... logs/hour-23.log: %d requests on %s"
          % (n, DAY.strftime("%a %d %b %Y")))
    o, t = make_loyalty()
    print("orders-anon.csv: %d orders in October 2026 (member IDs hashed)"
          % o)
    print("leaderboard.csv: the public top %d of the loyalty programme" % t)
