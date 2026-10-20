#!/usr/bin/env python3
"""The monkey of Lab 4.1 (Day 4): it breaks your coffee shop on purpose.

Usage:  python3 monkey.py 1 | 2 | 3 | 4 | kill | all-slow

  1         stops the shop on one server (a crash)
  2         makes one server slow
  3         starts the lunch rush (customers.py sends more orders)
  4         makes one server charge the wrong price
  kill      Extra A: kills the shop on one server; systemd restarts it
  all-slow  Extra B: makes every server slow

The monkey picks a healthy server at random and does not tell you which:
finding it is your job. It reaches the server with Systems Manager Run
Command, so it needs no SSH: the server's role (coffee-shop-role) lets the
SSM agent take the command, and your IAM permissions decide who may send
one (Day 4, slide 54). The incidents go in ~/.coffee-game/monkey.json,
where customers.py reads them. Standard library and the AWS CLI only.
"""

import json
import os
import random
import subprocess
import sys
import time

STACK = "coffee-fleet"
FAULT = "/etc/coffee-fault"
# What to run on the server(s), and whether it goes on the scoreboard.
ACTIONS = {
    "1": (["systemctl stop coffee"], "one", True),
    "2": (["echo slow > " + FAULT], "one", True),
    "3": (None, None, True),
    "4": (["echo liar > " + FAULT], "one", True),
    "kill": (["systemctl kill --signal=KILL coffee"], "one", False),
    "all-slow": (["echo slow > " + FAULT], "all", False),
}
SAY = {
    "1": "Incident 1 has started on one of your servers. "
         "Watch your scoreboard.",
    "2": "Incident 2 has started on one of your servers. "
         "Watch your scoreboard.",
    "3": "Incident 3 has started: a bus of hungry tourists has arrived!\n"
         "Customers now send 12 orders per second. Watch your scoreboard.",
    "4": "Incident 4 has started on one of your servers. "
         "Watch your scoreboard.",
    "kill": "Extra A: the monkey killed the shop on one server. "
            "Watch your scoreboard.",
    "all-slow": "Extra B: every server is slow now. "
                "Watch your scoreboard and your targets.",
}
USAGE = "Usage: python3 monkey.py 1 | 2 | 3 | 4 | kill | all-slow"


def aws(*args):
    """Run the aws CLI; return (parsed JSON or None, error text)."""
    try:
        r = subprocess.run(["aws"] + list(args) + ["--output", "json"],
                           capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as e:
        return None, str(e)
    if r.returncode != 0:
        return None, r.stderr.strip() or "aws exited with %d" % r.returncode
    try:
        return json.loads(r.stdout or "null"), ""
    except ValueError:
        return None, "unexpected answer from aws: " + r.stdout[:200]


def stack_outputs():
    out, err = aws("cloudformation", "describe-stacks",
                   "--stack-name", STACK)
    if out is None:
        sys.exit("Cannot find the stack %s. Check that CloudShell runs in "
                 "eu-central-1, and that Step 1.4 finished.\n(%s)"
                 % (STACK, err))
    return {o["OutputKey"]: o["OutputValue"]
            for o in out["Stacks"][0].get("Outputs", [])}


def healthy_servers(target_group):
    out, err = aws("elbv2", "describe-target-health",
                   "--target-group-arn", target_group)
    if out is None:
        sys.exit("Cannot read the health of your targets.\n(%s)" % err)
    return [t["Target"]["Id"] for t in out["TargetHealthDescriptions"]
            if t["TargetHealth"]["State"] == "healthy"]


def run_on(servers, commands):
    """Run commands on the servers with Run Command; wait until done."""
    out, err = aws("ssm", "send-command",
                   "--document-name", "AWS-RunShellScript",
                   "--comment", "Lab 4.1 monkey",
                   "--parameters", json.dumps({"commands": commands}),
                   "--instance-ids", *servers)
    if out is None:
        sys.exit("The monkey could not reach your servers. Check your role "
                 "(Step 1.1).\n(%s)" % err)
    command = out["Command"]["CommandId"]
    print("The monkey is at work...", flush=True)
    for server in servers:
        for _ in range(60):
            out, err = aws("ssm", "get-command-invocation",
                           "--command-id", command, "--instance-id", server)
            status = (out or {}).get("Status")
            if status == "Success":
                break
            if status in ("Failed", "Cancelled", "TimedOut"):
                sys.exit("The command failed on your server: %s\n%s"
                         % (status, out.get("StandardErrorContent", "")))
            time.sleep(1)    # Pending, InProgress, or not there yet
        else:
            sys.exit("The command did not finish within 60 seconds. "
                     "Run the monkey again.")


def remember(incident, url):
    """Write the incident's start time for customers.py."""
    d = os.path.join(os.path.expanduser("~"), ".coffee-game")
    path = os.path.join(d, "monkey.json")
    try:
        with open(path) as f:
            state = json.load(f)
    except (OSError, ValueError):
        state = {}
    if state.get("url") != url:        # a new fleet: a new game
        state = {"url": url, "incidents": {}}
    state["incidents"][incident] = time.time()
    os.makedirs(d, exist_ok=True)
    with open(path, "w") as f:
        json.dump(state, f)


def main():
    if len(sys.argv) != 2 or sys.argv[1] not in ACTIONS:
        sys.exit(USAGE)
    what = sys.argv[1]
    commands, where, incident = ACTIONS[what]
    outputs = stack_outputs()
    if commands:
        servers = healthy_servers(outputs["TargetGroupArn"])
        if not servers:
            sys.exit("Wait until your servers are healthy (Step 1.6), then "
                     "run the monkey again.")
        if where == "one":
            servers = [random.choice(servers)]
        run_on(servers, commands)
    if incident:
        remember(what, outputs["ShopUrl"])
    print(SAY[what])


if __name__ == "__main__":
    main()
