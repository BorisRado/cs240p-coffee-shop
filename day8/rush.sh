#!/bin/bash
# Lab 8, Part 2: the Sunday rush. 30 customers at the same moment; each
# request takes 2 seconds (?wait=2), so each one needs its own instance.
. "$(dirname "$0")/names.sh"
URL=$(function_url)
if [ -z "$URL" ] || [ "$URL" = None ]; then
  echo "$FN has no function URL. Do Step 1.4."
  exit 1
fi
python3 "$HERE/calls.py" at-once 30 "${URL}?wait=2" "$LOG"
