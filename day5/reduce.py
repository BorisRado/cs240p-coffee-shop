#!/usr/bin/env python3
"""Lab 5, the REDUCE step.

Reads the SORTED output of map.py on standard input. All the records of
one client IP arrive one after the other, so one pass is enough. For each
client, writes one line:

    client IP   requests   share of errors (4xx)   different paths   program

    cat logs/*.log | python3 map.py | sort | python3 reduce.py
"""
import sys
from collections import Counter


def finish(ip, n, errors, paths, agents):
    print(ip, n, "%.2f" % (errors / n), len(paths), agents.most_common(1)[0][0],
          sep="\t")


ip = None
for line in sys.stdin:
    client_ip, status, path, agent = line.rstrip("\n").split("\t")
    if client_ip != ip:
        if ip is not None:
            finish(ip, n, errors, paths, agents)
        ip, n, errors, paths, agents = client_ip, 0, 0, set(), Counter()
    n += 1
    if status.startswith("4"):
        errors += 1
    paths.add(path)
    agents[agent] += 1
if ip is not None:
    finish(ip, n, errors, paths, agents)
