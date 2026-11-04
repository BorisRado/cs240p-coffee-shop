#!/bin/bash
# Starts (or restarts) the three services of Lab 6 in the background.
# Their logs go to logs/. The databases (*.db) stay between restarts.
cd "$(dirname "$0")"
./stop.sh > /dev/null
mkdir -p logs
for s in payments stock orders; do
  nohup python3 $s.py >> logs/$s.log 2>&1 &
  echo $! > logs/$s.pid
done
sleep 1
for s in payments:8001 stock:8002 orders:8000; do
  name=${s%%:*}
  port=${s##*:}
  if curl -fs localhost:$port/health > /dev/null; then
    printf "%-9s port %s: OK\n" $name $port
  else
    printf "%-9s port %s: FAILED. The end of logs/%s.log:\n" \
      $name $port $name
    tail -n 5 logs/$name.log
  fi
done
