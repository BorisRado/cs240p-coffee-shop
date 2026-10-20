"""Tests for fleet.yaml, the CloudFormation template of Lab 4.1. Run:
python3 -m unittest -v test_fleet

They read the template as text (standard library only): the SHA-256 sums
in the user data must match the files of this release, and the settings
that the Lab 4.1 handout relies on must be there.
"""

import hashlib
import os
import re
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))


def read(name):
    with open(os.path.join(HERE, name), "rb") as f:
        return f.read()


TEMPLATE = read("fleet.yaml").decode()


def setting(name):
    """The value of `name: value` in the template (the only one)."""
    found = re.findall(r"^\s*-?\s*%s:\s*(.+?)\s*$" % re.escape(name),
                       TEMPLATE, re.M)
    if len(found) != 1:
        raise AssertionError("%s appears %d times" % (name, len(found)))
    return found[0].strip('"')


class Fleet(unittest.TestCase):

    def test_user_data_pins_the_files_of_this_release(self):
        for name in ["shop.py", "coffee.service"]:
            digest = hashlib.sha256(read(name)).hexdigest()
            self.assertRegex(
                TEMPLATE, r"\n\s+%s  %s\n" % (digest, re.escape(name)),
                "update the sum of %s in fleet.yaml: %s" % (name, digest))

    def test_user_data_downloads_the_tag_of_this_version(self):
        version = re.search(r'^VERSION = "(.+)"', read("shop.py").decode(),
                            re.M).group(1)
        self.assertIn("/cs240p-coffee-shop/v%s\n" % version, TEMPLATE)
        self.assertIn("sha256sum -c", TEMPLATE)

    def test_baristas_are_on(self):
        for line in ["COFFEE_BREW_SECONDS=0.4", "COFFEE_BARISTAS=2",
                     "COFFEE_QUEUE=5"]:
            self.assertIn("\n            %s\n" % line, TEMPLATE)

    def test_names_the_handout_uses(self):
        self.assertRegex(TEMPLATE, r"Type: AWS::ElasticLoadBalancingV2::"
                         r"LoadBalancer\n    Properties:\n"
                         r"      Name: coffee-fleet\n")
        self.assertEqual(setting("AutoScalingGroupName"), "coffee-fleet")
        self.assertEqual(setting("LaunchTemplateName"), "coffee-shop")
        self.assertIn("Name: coffee-shops", TEMPLATE)
        self.assertIn("Name: coffee-shop-role", TEMPLATE)
        for output in ["ShopUrl", "TargetGroupArn"]:
            self.assertRegex(TEMPLATE, r"\n  %s:\n" % output)

    def test_health_check_starts_slow_on_purpose(self):
        # Students make it faster in Step 3.4 and deeper in Step 4.4.
        self.assertEqual(setting("HealthCheckPath"), "/health")
        self.assertEqual(setting("HealthCheckIntervalSeconds"), "30")
        self.assertEqual(setting("HealthCheckTimeoutSeconds"), "5")
        self.assertEqual(setting("HealthyThresholdCount"), "2")
        self.assertEqual(setting("UnhealthyThresholdCount"), "2")
        self.assertIn("Key: deregistration_delay.timeout_seconds\n"
                      "          Value: \"10\"", TEMPLATE)

    def test_group_of_two_to_four_replaced_by_the_load_balancer(self):
        self.assertEqual(setting("MinSize"), "2")
        self.assertEqual(setting("DesiredCapacity"), "2")
        self.assertEqual(setting("MaxSize"), "4")
        self.assertEqual(setting("HealthCheckType"), "ELB")
        self.assertEqual(setting("HealthCheckGracePeriod"), "180")

    def test_students_add_the_scaling_policy_by_hand(self):
        self.assertNotIn("AWS::AutoScaling::ScalingPolicy", TEMPLATE)

    def test_no_ssh_and_imdsv2_only(self):
        ports = set(re.findall(r"(?:FromPort|ToPort):\s*(\d+)", TEMPLATE))
        self.assertEqual(ports, {"80"})
        self.assertEqual(setting("HttpTokens"), "required")
        self.assertIn("SourceSecurityGroupId: !Ref LoadBalancerSecurityGroup",
                      TEMPLATE)

    def test_no_secret_in_user_data(self):
        self.assertNotIn("PASSWORD", TEMPLATE)


if __name__ == "__main__":
    unittest.main()
