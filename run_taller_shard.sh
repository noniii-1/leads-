#!/bin/bash
# Usage: run_taller_shard.sh <shard_index> <shard_count>
SHARD=$1
COUNT=$2
LOG="scrape_taller_shard${SHARD}.log"
cd "C:/Users/Admin/Desktop/Proyecto/Mods"
for i in $(seq 1 60); do
  echo "=== attempt $i ===" >> "$LOG"
  "./.venv-scrapling/Scripts/python.exe" scrape_taller.py "$SHARD" "$COUNT" >> "$LOG" 2>&1
  if grep -q "DONE ALL" "$LOG"; then
    echo "=== finished cleanly on attempt $i ===" >> "$LOG"
    break
  fi
  echo "=== attempt $i exited early, retrying ===" >> "$LOG"
done
