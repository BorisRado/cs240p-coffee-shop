#!/usr/bin/env python3
"""Lab 5: link the "anonymous" order export to the public leaderboard.

orders-anon.csv has a hashed member ID per order: no names. leaderboard.csv
is public, with names. This script finds, for each person on the
leaderboard, the hashed ID whose orders look like them (slide 124: auxiliary
information).

    python3 link.py            # how many can be linked, and the first ones
    python3 link.py 7          # all the orders of the person at rank 7
"""
import csv
import sys
from collections import Counter, defaultdict

orders = list(csv.DictReader(open("orders-anon.csv")))
board = list(csv.DictReader(open("leaderboard.csv")))

# From the export alone: for each hashed ID, how many orders, the branch
# they go to most, the drink they order most.
per_member = defaultdict(list)
for o in orders:
    per_member[o["member"]].append(o)
profile = {}
for m, os_ in per_member.items():
    profile[m] = (Counter(o["branch"] for o in os_).most_common(1)[0][0],
                  Counter(o["drink"] for o in os_).most_common(1)[0][0],
                  len(os_))


def unique_matches(key):
    """How many leaderboard rows match exactly one hashed ID, using key."""
    index = defaultdict(list)
    for m, p in profile.items():
        index[key(p)].append(m)
    found = {}
    for row in board:
        k = key((row["home_branch"], row["favourite_drink"],
                 int(row["orders_in_october"])))
        if len(index.get(k, [])) == 1:
            found[row["rank"]] = index[k][0]
    return found


if len(sys.argv) == 1:
    by_branch = unique_matches(lambda p: p[0])
    by_drink = unique_matches(lambda p: (p[0], p[1]))
    by_all = unique_matches(lambda p: (p[0], p[1], p[2]))
    print("Leaderboard rows that match exactly ONE hashed ID in the export,")
    print("using only what the leaderboard shows:")
    print("  home branch:                          %3d of %d" % (len(by_branch), len(board)))
    print("  home branch + favourite drink:        %3d of %d" % (len(by_drink), len(board)))
    print("  branch + drink + orders in October:   %3d of %d" % (len(by_all), len(board)))
    print()
    with open("linked.txt", "w") as f:
        for row in board:
            if row["rank"] in by_all:
                f.write("%s\t%s\t%s\n" % (row["rank"], row["name"],
                                          by_all[row["rank"]]))
    for row in board[:8]:
        print("  rank %3s  %-22s = %s" % (row["rank"], row["name"],
              by_all.get(row["rank"], "(more than one match)")))
    print("  ...")
    print("linked.txt: %d names, each with its hashed ID" % len(by_all))
else:
    rank = sys.argv[1]
    row = next(r for r in board if r["rank"] == rank)
    m = unique_matches(lambda p: (p[0], p[1], p[2])).get(rank)
    if not m:
        sys.exit("rank %s matches more than one ID" % rank)
    print("Rank %s: %s = %s. Every order in October 2026:" % (rank, row["name"], m))
    for o in per_member[m]:
        print("  %s  %-9s %s (%s)" % (o["time"], o["branch"], o["drink"], o["size"]))
    hours = sorted(int(o["time"][11:13]) for o in per_member[m])
    print("%d orders, between %02d:00 and %02d:59, at %s"
          % (len(hours), hours[0], hours[-1],
             ", ".join(sorted(set(o["branch"] for o in per_member[m])))))
