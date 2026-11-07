"""The coffee shop's menu, as an AWS Lambda function (Lab 8).

Paste this whole file into the Lambda code editor (lambda_function.py)
and click Deploy.

  GET /                   the menu, and which instance served you
  GET /?wait=2            the same, 2 seconds slower (Part 2, the rush)
  GET /?photo=<address>   fetches a drink's photo from our supplier
"""

import base64
import json
import time
import urllib.request

MENU = {"espresso": 2.50, "latte": 4.50, "cappuccino": 4.00,
        "oat-latte": 5.00, "mint-tea": 3.00}

# This code runs once, when a new instance of the function starts.
STARTED = time.time()
served = 0


def answer(status, data):
    return {"statusCode": status,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps(data, indent=2) + "\n"}


def lambda_handler(event, context):
    # This code runs for every request.
    global served
    served += 1
    params = event.get("queryStringParameters") or {}

    photo = params.get("photo")
    if photo:
        # Our supplier keeps the photos of the drinks. The shop fetches
        # them, so the menu page needs only one address.
        try:
            with urllib.request.urlopen(photo, timeout=5) as r:
                body = r.read()
        except Exception as e:
            return answer(502, {"error": "cannot fetch the photo: %s" % e})
        return {"statusCode": 200,
                "headers": {"Content-Type": "application/octet-stream"},
                "body": base64.b64encode(body).decode(),
                "isBase64Encoded": True}

    wait = min(float(params.get("wait", 0)), 5)
    time.sleep(wait)
    return answer(200, {
        "menu": MENU,
        "instance": context.log_stream_name[-8:],
        "instance_age_seconds": round(time.time() - STARTED),
        "requests_served_by_this_instance": served,
    })
