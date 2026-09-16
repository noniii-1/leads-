# -*- coding: utf-8 -*-
"""
Backfill has_photos para leads ya cosechados en verified_taller_shard*.jsonl
que no guardaron ese dato (se agrego el campo despues de esa corrida). Estos
archivos no guardan el href directo de la ficha, asi que se re-busca cada
negocio por nombre+direccion (misma tecnica que scrape_recency.py) y se lee
si aparece "Ver fotos" en el texto de la ficha.

Usage: python enrich_photos.py
Writes photo_enrichment.jsonl: {name, has_photos} (resumable, dedup por nombre).
"""
import os
import re
import sys
import io
import time
import json
import glob
import threading
from scrapling.fetchers import StealthySession

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

OUT_PATH = "photo_enrichment.jsonl"
WATCHDOG_SECS = 100

_last_progress = time.time()
_lock = threading.Lock()


def _touch():
    global _last_progress
    with _lock:
        _last_progress = time.time()


def _watchdog():
    while True:
        time.sleep(10)
        with _lock:
            stale = time.time() - _last_progress
        if stale > WATCHDOG_SECS:
            print(f"[photos] WATCHDOG: no progress for {stale:.0f}s, force-exiting", flush=True)
            os._exit(1)


def load_targets():
    targets = []
    seen = set()
    for path in sorted(glob.glob("verified_taller_shard*.jsonl")) + sorted(glob.glob("verified_detailing_shard*.jsonl")):
        with open(path, encoding="utf-8") as f:
            for line in f:
                rec = json.loads(line)
                if "has_photos" in rec:
                    continue  # ya lo tiene desde el harvest
                key = rec["name"].strip().lower()
                if key in seen:
                    continue
                seen.add(key)
                targets.append(rec)
    return targets


def load_done():
    done = set()
    try:
        with open(OUT_PATH, encoding="utf-8") as f:
            for line in f:
                done.add(json.loads(line)["name"].strip().lower())
    except FileNotFoundError:
        pass
    return done


def do_open(query):
    def _action(page):
        page.wait_for_timeout(1200)
        box = page.locator('input[name="q"]')
        box.click()
        box.fill(query)
        box.press("Enter")
        page.wait_for_timeout(3500)
        return page
    return _action


def run_batch(targets, session):
    for i, t in enumerate(targets, start=1):
        query = f"{t['name']} {t.get('address') or t.get('city') or ''} Santiago Chile"
        try:
            page = session.fetch("https://www.google.com/maps", page_action=do_open(query), timeout=30000, network_idle=False)
            txt = page.get_all_text()
            has_photos = "Ver fotos" in txt
            with open(OUT_PATH, "a", encoding="utf-8") as fout:
                fout.write(json.dumps({"name": t["name"], "has_photos": has_photos}, ensure_ascii=False) + "\n")
            print(f"[photos] [{i}/{len(targets)}] {t['name']!r} -> has_photos={has_photos}", flush=True)
            _touch()
        except Exception as e:
            print(f"[photos] [{i}/{len(targets)}] {t['name']!r} ERROR: {e}", flush=True)
            _touch()
        time.sleep(0.5)


def main():
    t = threading.Thread(target=_watchdog, daemon=True)
    t.start()

    all_targets = load_targets()
    done = load_done()
    pending = [x for x in all_targets if x["name"].strip().lower() not in done]
    print(f"[photos] {len(all_targets)} total, {len(pending)} pending", flush=True)

    CHUNK = 35
    for start in range(0, len(pending), CHUNK):
        chunk = pending[start:start + CHUNK]
        print(f"[photos] opening fresh session for {start+1}-{start+len(chunk)}", flush=True)
        _touch()
        try:
            with StealthySession(headless=True, network_idle=True, max_pages=1) as session:
                run_batch(chunk, session)
        except Exception as e:
            print(f"[photos] session-level ERROR: {e}", flush=True)
            _touch()

    print("[photos] DONE ALL", flush=True)


if __name__ == "__main__":
    main()
