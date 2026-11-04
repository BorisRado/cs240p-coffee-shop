#!/usr/bin/env python3
"""Lab 5, the MAP step.

Reads load-balancer log lines (ALB format) on standard input. For each
line, writes one record on standard output:

    client IP <tab> status code <tab> path <tab> client program

The key is the client IP (the first column). Numbers in the path are
replaced by N, so /orders/17 and /orders/18 are the same path.

    cat logs/*.log | python3 map.py | sort | python3 reduce.py
"""
import re
import sys

AGENTS = [("CoffeeApp", "CoffeeApp"), ("UptimeMonitor", "UptimeMonitor"),
          ("zgrab", "zgrab"), ("python-requests", "python-requests"),
          ("Nmap", "Nmap"), ("Firefox", "Firefox"), ("Chrome", "Chrome"),
          ("Safari", "Safari")]


def agent_name(user_agent):
    for word, name in AGENTS:
        if word in user_agent:
            return name
    return "other"


for line in sys.stdin:
    fields = line.split(" ")
    if len(fields) < 12 or fields[0] != "http" and fields[0] != "https":
        continue                       # not a request line: skip it
    client_ip = fields[3].rsplit(":", 1)[0]
    status = fields[8]
    quoted = line.split('"')           # "GET http://host:80/path HTTP/1.1"
    url = quoted[1].split(" ")[1]
    path = "/" + url.split("/", 3)[3] if url.count("/") >= 3 else "/"
    path = re.sub(r"[0-9]+", "N", path)
    print(client_ip, status, path, agent_name(quoted[3]), sep="\t")
