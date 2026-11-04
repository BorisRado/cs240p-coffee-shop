#!/usr/bin/env python3
"""Lab 5: k-means on the clients of the shop (Day 5, slides 77 and 82).

Reads features.tsv (the output of reduce.py): one client per line, with
its number of requests, its share of errors and its number of different
paths. Puts the clients in k groups and prints them. Then prints the
clients that are farthest from the centre of their group: the odd ones
out (slide 82), and writes them to odd.txt.

    python3 kmeans.py            # k = 3
    python3 kmeans.py 4          # k = 4
"""
import math
import random
import sys

K = int(sys.argv[1]) if len(sys.argv) > 1 else 3
FILE = "features.tsv"

clients = []
for line in open(FILE):
    ip, n, errors, paths, agent = line.rstrip("\n").split("\t")
    clients.append((ip, int(n), float(errors), int(paths), agent))
if len(clients) < K:
    sys.exit("fewer clients than groups")

# Each client becomes a point with three numbers. Requests and paths are
# on a log scale (1 000 requests is "far" from 10, not 100 times further
# than 10 is from 1). Each number is then scaled so that the three count
# the same (slide 82: scaling matters more than the algorithm).
raw = [(math.log10(c[1]), c[2], math.log10(c[3])) for c in clients]
means = [sum(p[i] for p in raw) / len(raw) for i in range(3)]
sds = [math.sqrt(sum((p[i] - means[i]) ** 2 for p in raw) / len(raw)) or 1
       for i in range(3)]
points = [tuple((p[i] - means[i]) / sds[i] for i in range(3)) for p in raw]


def dist(a, b):
    return math.sqrt(sum((a[i] - b[i]) ** 2 for i in range(3)))


def kmeans(points, k, seed):
    rnd = random.Random(seed)
    centres = rnd.sample(points, k)                # slide 77: random start
    for _ in range(100):
        groups = [[] for _ in range(k)]
        for p in points:                            # map: nearest centre
            groups[min(range(k), key=lambda i: dist(p, centres[i]))].append(p)
        new = [tuple(sum(p[i] for p in g) / len(g) for i in range(3))
               if g else centres[j] for j, g in enumerate(groups)]
        if new == centres:                          # stable: stop
            break
        centres = new
    cost = sum(dist(p, centres[j]) ** 2 for j, g in enumerate(groups)
               for p in g)
    return cost, centres


# The random start matters: run it ten times, keep the best result.
cost, centres = min(kmeans(points, K, seed) for seed in range(10))
groups = [[] for _ in range(K)]
far = []                                            # (distance, client)
for c, p in zip(clients, points):
    i = min(range(K), key=lambda i: dist(p, centres[i]))
    groups[i].append(c)
    far.append((dist(p, centres[i]), c))
groups.sort(key=len, reverse=True)


def row(c):
    return "%-16s %5d requests  %3d%% errors  %3d paths  %s" % (
        c[0], c[1], round(100 * c[2]), c[3], c[4])


for j, g in enumerate(groups, 1):
    n = len(g)
    print("Group %d: %d clients. Typical client: %d requests, %d%% errors, "
          "%d different paths" % (j, n, sum(c[1] for c in g) / n,
                                 round(100 * sum(c[2] for c in g) / n),
                                 sum(c[3] for c in g) / n))

far.sort(key=lambda x: -x[0])
print("\nThe 10 clients farthest from the centre of their group "
      "(the odd ones out):")
with open("odd.txt", "w") as f:
    for d, c in far[:10]:
        print("  " + row(c))
        f.write("%s\t%d\t%d\t%d\t%s\t%.1f\n"
                % (c[0], c[1], round(100 * c[2]), c[3], c[4], d))
print("odd.txt: these 10 clients, with the same columns")
