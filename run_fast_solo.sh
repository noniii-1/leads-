#!/bin/bash
cd "C:/Users/Admin/Desktop/Proyecto/Mods"
LOG="scrape_fast_solo.log"
for i in $(seq 1 20); do
  echo "=== attempt $i ===" >> "$LOG"
  "./.venv-scrapling/Scripts/python.exe" scrape_fast.py 0 1 >> "$LOG" 2>&1
  if grep -q "DONE ALL" "$LOG"; then
    echo "=== finished cleanly on attempt $i ===" >> "$LOG"
    break
  fi
  echo "=== attempt $i exited early, retrying ===" >> "$LOG"
done
