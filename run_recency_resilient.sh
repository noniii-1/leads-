#!/bin/bash
cd "C:/Users/Admin/Desktop/Proyecto/Mods"
for i in $(seq 1 15); do
  echo "=== attempt $i ===" >> scrape_recency8.log
  "./.venv-scrapling/Scripts/python.exe" scrape_recency.py >> scrape_recency8.log 2>&1
  if grep -q "DONE ALL" scrape_recency8.log; then
    echo "=== finished cleanly on attempt $i ===" >> scrape_recency8.log
    break
  fi
  echo "=== attempt $i exited early, retrying ===" >> scrape_recency8.log
done
