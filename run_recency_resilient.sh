#!/bin/bash
cd "C:/Users/Admin/Desktop/Proyecto/Mods"
for i in $(seq 1 15); do
  echo "=== attempt $i ===" >> scrape_recency3.log
  "./.venv-scrapling/Scripts/python.exe" scrape_recency.py >> scrape_recency3.log 2>&1
  if grep -q "DONE ALL" scrape_recency3.log; then
    echo "=== finished cleanly on attempt $i ===" >> scrape_recency3.log
    break
  fi
  echo "=== attempt $i exited early, retrying ===" >> scrape_recency3.log
done
