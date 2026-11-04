#!/bin/bash
# Stops the three services of Lab 6. The databases (*.db) stay.
cd "$(dirname "$0")"
for s in payments stock orders; do
  if [ -f logs/$s.pid ]; then
    kill "$(cat logs/$s.pid)" 2> /dev/null
    rm -f logs/$s.pid
  fi
done
sleep 0.5
echo "Stopped: payments, stock, orders"
