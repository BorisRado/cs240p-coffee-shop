# CS 240P coffee shop

A small coffee-shop REST API for the labs of CS 240P Cloud Computing
(KAUST, Fall 2026). Students call a copy that the TAs run (Lab 2.1), then
deploy their own copy on EC2 (Lab 3.1).

> **This code has bugs on purpose.** They are marked `BUG (on purpose)` in
> `shop.py`. Do not use it for anything real.

Python 3.9+ standard library only, so it runs on a fresh Amazon Linux 2023
server with no `pip install`. All data is in memory: a restart empties the
shop.

## Files

| File | What it is |
|---|---|
| `shop.py` | The shop. |
| `coffee.service` | The systemd unit: starts the shop at boot, restarts it if it crashes, runs it as a throw-away user. |
| `race.py` | Redeems one gift card many times at once (Day 3, slide 41). Run it from CloudShell: `python3 race.py http://IP`. |
| `make-user-data.sh` | For TAs: prints the EC2 user data for a release tag, with the files' SHA-256 sums. |
| `test_shop.py` | Tests: `python3 -m unittest -v test_shop`. |

## The API

| Method | Path | Answer |
|---|---|---|
| `GET` | `/` | HTML page: hostname, Availability Zone, instance ID, uptime |
| `GET` | `/health` | `OK` |
| `GET` | `/menu` | The drinks, sizes and prices |
| `GET` | `/orders` | Your orders |
| `POST` | `/orders` | `{"drink": "latte", "size": "M", "to_go": true}` gives 201 and `Location: /orders/N` |
| `GET` | `/orders/N` | One order |
| `PUT` | `/orders/N` | Change your order |
| `DELETE` | `/orders/N` | Cancel your order: 204 |
| `POST` | `/giftcards` | A new gift card with 5.00 on it: 201 |
| `GET` | `/giftcards/CODE` | The balance |
| `POST` | `/giftcards/CODE/redeem` | `{"drink": "latte", "size": "M"}` gives 200, or 402 if the balance is too low |
| `POST` | `/admin/reset` | Header `X-Admin-Password`: deletes all orders and gift cards |

## Settings (environment variables, all optional)

| Variable | Default | Meaning |
|---|---|---|
| `COFFEE_PORT` | `80` | Port |
| `COFFEE_ADMIN_PASSWORD` | unset | Password for `/admin/reset`. Unset: no admin endpoint. |
| `COFFEE_RACE_DELAY` | `0.3` | Seconds between the check and the use of a gift card |
| `COFFEE_API_KEYS` | unset | File of `key name` lines. Set: `/orders` and `/giftcards` need `X-API-Key`, and each key sees its own orders. |
| `COFFEE_RATE_LIMIT` | `0` | Requests per minute per client (0: no limit). Answers 429. |
| `COFFEE_EXTRA_HEADERS` | `{}` | JSON object of headers to add to every response |
| `COFFEE_TRUST_PROXY` | unset | `1`: the client is the first address in `X-Forwarded-For` (behind a proxy) |

On EC2, `systemd` reads them from `/etc/coffee.env`.

## Running it

On your laptop:

```bash
COFFEE_PORT=8080 python3 shop.py
python3 race.py http://localhost:8080
```

On EC2 (Lab 3.1): paste the output of `./make-user-data.sh v1.0` into the
**User data** box of the launch wizard. It downloads `shop.py` and
`coffee.service` for that tag, checks their SHA-256 sums, and installs the
service. Its output is in `/var/log/cloud-init-output.log`.

## For TAs

**Lab 2.1 (the TAs' copy).** Run the same tag with API keys, a rate limit
and HTTPS in front, for example Caddy as a reverse proxy:

```bash
# /etc/coffee.env
COFFEE_PORT=8080
COFFEE_API_KEYS=/etc/coffee-keys.txt
COFFEE_RATE_LIMIT=120
COFFEE_TRUST_PROXY=1
COFFEE_ADMIN_PASSWORD=<a long random value>
COFFEE_EXTRA_HEADERS={"X-Clue": "..."}
```

Name keys `student01`, `student02`, ... and never by real name: the name is
the `owner` of an order, and the deliberate bug in `GET /orders/N` shows
it to other students. Keep escape-room clues and answers in this
deployment's settings, never in the repository.

**A new release.** Change the code, run the tests, then tag it
(`git tag v1.1 && git push --tags`), run `./make-user-data.sh v1.1`, and
paste the new user data into the Lab 3.1 handout. Never move a tag that
students already use: their sums would stop matching.
