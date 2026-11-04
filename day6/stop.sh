#!/bin/bash
# Stops the services of Lab 6. The databases (*.db) stay.
#   ./stop.sh            all three
#   ./stop.sh payments   only payments (or stock, or orders)
cd "$(dirname "$0")"
names=${*:-payments stock orders}
for s in $names; do
  if [ -f logs/$s.pid ]; then
    kill "$(cat logs/$s.pid)" 2> /dev/null
    rm -f logs/$s.pid
  fi
done
sleep 0.5
echo "Stopped: $(echo $names | sed 's/ /, /g')"
