#!/bin/bash
LOG="check_instagram.log"
cd "C:/Users/Admin/Desktop/Proyecto/Mods"
for i in $(seq 1 60); do
  echo "=== attempt $i ===" >> "$LOG"
  "./.venv-scrapling/Scripts/python.exe" check_instagram.py >> "$LOG" 2>&1
  if grep -q "DONE ALL" "$LOG"; then
    echo "=== finished cleanly on attempt $i ===" >> "$LOG"
    break
  fi
  echo "=== attempt $i exited early, retrying ===" >> "$LOG"
done
