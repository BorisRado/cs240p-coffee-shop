"""Tests for the monkey of Lab 4.1. Run:  python3 -m unittest -v test_monkey

monkey.py talks to AWS through the aws CLI. These tests put a fake `aws`
first on the PATH: it answers with made-up API responses and writes down
every call. Standard library only.
"""

import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
URL = "http://coffee-fleet-1.eu-central-1.elb.amazonaws.com"
TG = "arn:aws:elasticloadbalancing:eu-central-1:1:targetgroup/coffee-shops/1"

FAKE_AWS = r'''#!/usr/bin/env python3
import json, os, sys
d = os.environ["FAKE_AWS"]
with open(os.path.join(d, "calls.jsonl"), "a") as f:
    f.write(json.dumps(sys.argv[1:]) + "\n")
with open(os.path.join(d, "answers.json")) as f:
    answers = json.load(f)
key = " ".join(sys.argv[1:3])
answer = answers.get(key, {"code": 254, "err": "no fake answer: " + key})
if isinstance(answer, list):          # one answer per call, the last repeats
    n = sum(1 for line in open(os.path.join(d, "calls.jsonl"))
            if " ".join(json.loads(line)[:2]) == key)
    answer = answer[min(n, len(answer)) - 1]
sys.stdout.write(json.dumps(answer["out"]) if "out" in answer else "")
sys.stderr.write(answer.get("err", ""))
sys.exit(answer.get("code", 0))
'''


def targets(**states):
    return {"out": {"TargetHealthDescriptions": [
        {"Target": {"Id": i, "Port": 80}, "TargetHealth": {"State": s}}
        for i, s in states.items()]}}


class Monkey(unittest.TestCase):

    def setUp(self):
        self.home = tempfile.mkdtemp()
        self.fake = tempfile.mkdtemp()
        aws = os.path.join(self.fake, "aws")
        with open(aws, "w") as f:
            f.write(FAKE_AWS)
        os.chmod(aws, os.stat(aws).st_mode | stat.S_IEXEC)
        self.answers = {
            "cloudformation describe-stacks": {"out": {"Stacks": [{
                "Outputs": [
                    {"OutputKey": "ShopUrl", "OutputValue": URL},
                    {"OutputKey": "TargetGroupArn", "OutputValue": TG}]}]}},
            "elbv2 describe-target-health": targets(
                **{"i-aaa": "healthy", "i-bbb": "unhealthy",
                   "i-ccc": "healthy"}),
            "ssm send-command": {"out": {"Command": {"CommandId": "c-1"}}},
            "ssm get-command-invocation": {"out": {"Status": "Success"}},
        }

    def run_monkey(self, *args):
        with open(os.path.join(self.fake, "answers.json"), "w") as f:
            json.dump(self.answers, f)
        env = dict(os.environ, HOME=self.home, FAKE_AWS=self.fake,
                   PATH=self.fake + os.pathsep + os.environ["PATH"])
        return subprocess.run(
            [sys.executable, os.path.join(HERE, "monkey.py")] + list(args),
            env=env, capture_output=True, text=True, timeout=30)

    def calls(self, key=None):
        try:
            with open(os.path.join(self.fake, "calls.jsonl")) as f:
                calls = [json.loads(line) for line in f]
        except OSError:
            return []
        return [c for c in calls if key is None or " ".join(c[:2]) == key]

    def sent(self):
        """[(instance IDs, commands)] for every send-command."""
        out = []
        for c in self.calls("ssm send-command"):
            ids = c[c.index("--instance-ids") + 1:]
            ids = ids[:next((i for i, a in enumerate(ids)
                             if a.startswith("--")), len(ids))]
            params = json.loads(c[c.index("--parameters") + 1])
            out.append((ids, params["commands"]))
        return out

    def state(self):
        try:
            with open(os.path.join(self.home, ".coffee-game",
                                   "monkey.json")) as f:
                return json.load(f)
        except OSError:
            return None

    def test_incident_1_stops_the_shop_on_one_healthy_server(self):
        r = self.run_monkey("1")
        self.assertEqual(r.returncode, 0, r.stderr)
        [(ids, commands)] = self.sent()
        self.assertEqual(len(ids), 1)
        self.assertIn(ids[0], ["i-aaa", "i-ccc"])
        self.assertEqual(commands, ["systemctl stop coffee"])
        self.assertIn("Incident 1 has started on one of your servers.",
                      r.stdout)
        self.assertNotIn("i-", r.stdout)       # finding it is the game
        state = self.state()
        self.assertEqual(state["url"], URL)
        self.assertEqual(list(state["incidents"]), ["1"])

    def test_incidents_2_and_4_switch_the_fault_on(self):
        self.assertEqual(self.run_monkey("2").returncode, 0)
        self.assertEqual(self.run_monkey("4").returncode, 0)
        self.assertEqual([c for _, c in self.sent()],
                         [["echo slow > /etc/coffee-fault"],
                          ["echo liar > /etc/coffee-fault"]])
        self.assertEqual(sorted(self.state()["incidents"]), ["2", "4"])

    def test_the_rush_needs_no_server(self):
        r = self.run_monkey("3")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("bus of hungry tourists", r.stdout)
        self.assertEqual(self.calls("elbv2 describe-target-health"), [])
        self.assertEqual(self.sent(), [])
        self.assertEqual(list(self.state()["incidents"]), ["3"])

    def test_waits_for_the_command_to_finish(self):
        self.answers["ssm get-command-invocation"] = [
            {"code": 254, "err": "An error occurred "
                                 "(InvocationDoesNotExist)"},
            {"out": {"Status": "InProgress"}},
            {"out": {"Status": "Success"}}]
        r = self.run_monkey("2")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(len(self.calls("ssm get-command-invocation")), 3)

    def test_no_healthy_server(self):
        self.answers["elbv2 describe-target-health"] = targets(
            **{"i-aaa": "initial", "i-bbb": "unhealthy"})
        r = self.run_monkey("1")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("Wait until your servers are healthy",
                      r.stdout + r.stderr)
        self.assertEqual(self.sent(), [])
        self.assertIsNone(self.state())

    def test_no_stack(self):
        self.answers["cloudformation describe-stacks"] = {
            "code": 254, "err": "Stack with id coffee-fleet does not exist"}
        r = self.run_monkey("1")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("Cannot find the stack coffee-fleet",
                      r.stdout + r.stderr)

    def test_run_command_fails(self):
        self.answers["ssm send-command"] = {
            "code": 254, "err": "An error occurred (InvalidInstanceId)"}
        r = self.run_monkey("1")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("InvalidInstanceId", r.stdout + r.stderr)
        self.assertIn("Step 1.1", r.stdout + r.stderr)
        self.assertIsNone(self.state())

    def test_command_fails_on_the_server(self):
        self.answers["ssm get-command-invocation"] = {
            "out": {"Status": "Failed", "StandardErrorContent": "oops"}}
        r = self.run_monkey("1")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("oops", r.stdout + r.stderr)
        self.assertIsNone(self.state())

    def test_extra_kill(self):
        r = self.run_monkey("kill")
        self.assertEqual(r.returncode, 0, r.stderr)
        [(ids, commands)] = self.sent()
        self.assertEqual(commands, ["systemctl kill --signal=KILL coffee"])
        self.assertIsNone(self.state())        # not an incident

    def test_extra_all_slow_hits_every_healthy_server(self):
        r = self.run_monkey("all-slow")
        self.assertEqual(r.returncode, 0, r.stderr)
        [(ids, commands)] = self.sent()
        self.assertEqual(sorted(ids), ["i-aaa", "i-ccc"])
        self.assertEqual(commands, ["echo slow > /etc/coffee-fault"])

    def test_a_new_fleet_forgets_the_old_incidents(self):
        d = os.path.join(self.home, ".coffee-game")
        os.makedirs(d)
        with open(os.path.join(d, "monkey.json"), "w") as f:
            json.dump({"url": "http://old", "incidents": {"1": 5}}, f)
        self.assertEqual(self.run_monkey("2").returncode, 0)
        self.assertEqual(list(self.state()["incidents"]), ["2"])
        self.assertEqual(self.state()["url"], URL)

    def test_usage(self):
        for args in [(), ("5",), ("1", "2")]:
            r = self.run_monkey(*args)
            self.assertNotEqual(r.returncode, 0)
            self.assertIn("Usage", r.stdout + r.stderr)
        self.assertEqual(self.calls(), [])


if __name__ == "__main__":
    unittest.main()
