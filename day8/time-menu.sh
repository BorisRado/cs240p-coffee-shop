#!/bin/bash
# Lab 8, Part 1: calls the menu 5 times, one after the other, and shows
# how long each call took and which instance answered.
. "$(dirname "$0")/names.sh"
URL=$(function_url)
if [ -z "$URL" ] || [ "$URL" = None ]; then
  echo "$FN has no function URL. Do Step 1.4."
  exit 1
fi
echo "Calling $FN, 5 times, one after the other."
python3 "$HERE/calls.py" one-by-one 5 "$URL" "$LOG"
