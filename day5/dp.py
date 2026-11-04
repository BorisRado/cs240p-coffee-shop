#!/usr/bin/env python3
"""Lab 5: a differentially private count (Day 5, slides 128-134).

Question: how many MEMBERS ordered at a branch between two hours?
The true answer is never printed. The answer gets Laplace noise, and each
answer costs epsilon from a privacy budget of 1.0 (budget.json).

    python3 dp.py Airport 1 4             # between 01:00 and 03:59
    python3 dp.py Airport 1 4 --epsilon 0.5
    python3 dp.py Airport 1 4 --without a1b2c3d4e5   # the slide 129 experiment
    python3 dp.py --reset                 # a new budget (start again)
"""
import csv
import json
import math
import os
import random
import sys

BUDGET_FILE = "budget.json"
BUDGET_MAX = 1.0

args, epsilon, without = [], 0.1, None
rest = sys.argv[1:]
while rest:
    a = rest.pop(0)
    if a == "--reset":
        if os.path.exists(BUDGET_FILE):
            os.remove(BUDGET_FILE)
        print("New budget: %.1f" % BUDGET_MAX)
        sys.exit()
    elif a == "--epsilon" and rest:
        epsilon = float(rest.pop(0))
    elif a == "--without" and rest:
        without = rest.pop(0)
    else:
        args.append(a)
if len(args) != 3 or epsilon <= 0:
    sys.exit(__doc__)
branch, h1, h2 = args[0], int(args[1]), int(args[2])


def true_count(skip=None):
    members = set()
    for o in csv.DictReader(open("orders-anon.csv")):
        if o["branch"] == branch and h1 <= int(o["time"][11:13]) < h2 \
                and o["member"] != skip:
            members.add(o["member"])
    return len(members)


def laplace(scale):
    """Slide 133: noise from a Laplace distribution."""
    u = random.random() - 0.5
    return -scale * math.copysign(1, u) * math.log(1 - 2 * abs(u))


# One member can change the count by at most 1 (sensitivity 1), so the
# noise scale is 1 / epsilon (slide 133).
scale = 1 / epsilon

if without:
    print("Members at %s between %02d:00 and %02d:59, with and without %s."
          % (branch, h1, h2 - 1, without))
    print("Ten noisy answers each (epsilon %.1f). Can you tell the columns apart?"
          % epsilon)
    a, b = true_count(), true_count(skip=without)
    print("  %8s  %8s" % ("with", "without"))
    for _ in range(10):
        print("  %8d  %8d" % (round(a + laplace(scale)), round(b + laplace(scale))))
    print("(The data owner knows the true answers differ by %d. The querier "
          "cannot tell.)" % (a - b))
    sys.exit()

budget = json.load(open(BUDGET_FILE)) if os.path.exists(BUDGET_FILE) \
    else {"spent": 0.0, "answers": []}
if budget["spent"] + epsilon > BUDGET_MAX + 1e-9:
    answers = budget["answers"]
    print("Privacy budget exhausted: %.1f of %.1f spent. No more answers."
          % (budget["spent"], BUDGET_MAX))
    if answers:
        print("Your %d answers: %s" % (len(answers), " ".join(map(str, answers))))
        print("Their average: %.1f.  The true answer was %d."
              % (sum(answers) / len(answers), true_count()))
    sys.exit()

answer = round(true_count() + laplace(scale))
budget["spent"] = round(budget["spent"] + epsilon, 6)
budget["answers"].append(answer)
json.dump(budget, open(BUDGET_FILE, "w"))
print("Members at %s between %02d:00 and %02d:59: about %d   "
      "(epsilon %.1f; budget left %.1f)"
      % (branch, h1, h2 - 1, answer, epsilon, BUDGET_MAX - budget["spent"]))
