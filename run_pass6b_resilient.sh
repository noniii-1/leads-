#!/bin/bash
# Restarts scrape_dental_pass6b.py up to 15 times if it exits early (watchdog
# kill, driver crash, etc). Resume is automatic via dental_candidates.jsonl.
cd "C:/Users/Admin/Desktop/Proyecto/Mods"
for i in $(seq 1 15); do
  echo "=== attempt $i ===" >> scrape_dental_pass6b.log
  "./.venv-scrapling/Scripts/python.exe" scrape_dental_pass6b.py >> scrape_dental_pass6b.log 2>&1
  if grep -q "DONE ALL" scrape_dental_pass6b.log; then
    echo "=== finished cleanly on attempt $i ===" >> scrape_dental_pass6b.log
    break
  fi
  echo "=== attempt $i exited early, retrying ===" >> scrape_dental_pass6b.log
done
