# -*- coding: utf-8 -*-
"""
Continuation of scrape_dental_pass6.py, which hung for 5+ hours on a frozen
browser driver with no error (Playwright's own timeout didn't save us).
This version adds a hard watchdog: if no query finishes within WATCHDOG_SECS,
the whole process force-exits (os._exit) so an external loop can restart it.
Covers only the comunas pass6 hadn't reached yet.
"""
import os
import time
import json
import threading
from scrapling.fetchers import StealthySession
from parse_utils import parse_article

MIN_REVIEWS = 15
OUT_PATH = "dental_candidates.jsonl"
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
            print(f"[dental-p6b] WATCHDOG: no progress for {stale:.0f}s, force-exiting", flush=True)
            os._exit(1)


# comunas pass6 had NOT yet reached (it hung right as it started "La Pintana")
COMUNAS = [
    "La Pintana", "San Ramón", "El Bosque",
    "La Cisterna", "San Miguel", "Pedro Aguirre Cerda", "Lo Espejo", "Estación Central",
    "Cerrillos", "Maipú", "Cerro Navia", "Pudahuel", "Lo Prado",
    "Quinta Normal", "Renca", "Quilicura", "Huechuraba", "Conchalí",
    "Independencia", "Recoleta", "Puente Alto", "San Bernardo",
]

KEYWORDS = [
    "clinica dental moderna", "dentista general", "clinica dental particular",
    "consultorio odontologico", "dentista turno", "clinica smile dental",
]


def build_queries():
    queries = []
    for comuna in COMUNAS:
        for kw in KEYWORDS:
            queries.append((f"{kw} {comuna} Santiago Chile", comuna))
    return queries


def do_search(query):
    def _action(page):
        page.wait_for_timeout(1200)
        box = page.locator('input[name="q"]')
        box.click()
        box.fill(query)
        box.press("Enter")
        page.wait_for_timeout(2800)
        feed = page.locator('div[role="feed"]')
        try:
            for _ in range(8):
                feed.evaluate("el => el.scrollTop = el.scrollHeight")
                page.wait_for_timeout(900)
        except Exception:
            pass
        return page
    return _action


def run_batch(queries, session, global_start):
    seen_names = set()
    try:
        with open(OUT_PATH, "r", encoding="utf-8") as f:
            for line in f:
                rec = json.loads(line)
                seen_names.add(rec["name"].strip().lower())
    except FileNotFoundError:
        pass

    qualifying_count = len(seen_names)
    for i, (query, comuna) in enumerate(queries):
        gi = global_start + i
        url = "https://www.google.com/maps"
        try:
            page = session.fetch(url, page_action=do_search(query), timeout=30000)
            articles = page.css('div.Nv2PK')
            new_this_query = 0
            for a in articles:
                try:
                    rec = parse_article(a.get_all_text())
                except Exception:
                    rec = None
                if not rec:
                    continue
                key = rec["name"].strip().lower()
                if key in seen_names:
                    continue
                if rec["reviews"] >= MIN_REVIEWS and not rec["has_website"]:
                    seen_names.add(key)
                    rec["comuna_query"] = comuna
                    rec["source_query"] = query
                    with open(OUT_PATH, "a", encoding="utf-8") as fout:
                        fout.write(json.dumps(rec, ensure_ascii=False) + "\n")
                    qualifying_count += 1
                    new_this_query += 1
            print(f"[dental-p6b] [{gi}] '{query}' -> {len(articles)} items, +{new_this_query} qualifying (total {qualifying_count})", flush=True)
            _touch()
        except Exception as e:
            print(f"[dental-p6b] [{gi}] '{query}' ERROR: {e}", flush=True)
            _touch()
        time.sleep(0.6)


def main():
    t = threading.Thread(target=_watchdog, daemon=True)
    t.start()

    queries = build_queries()
    print(f"[dental-p6b] {len(queries)} queries total (global index shown), watchdog={WATCHDOG_SECS}s", flush=True)

    CHUNK = 30
    for start in range(0, len(queries), CHUNK):
        chunk = queries[start:start + CHUNK]
        print(f"[dental-p6b] opening fresh session for global queries {start+1}-{start+len(chunk)}", flush=True)
        _touch()
        try:
            with StealthySession(headless=True, network_idle=False, max_pages=1) as session:
                run_batch(chunk, session, start + 1)
        except Exception as e:
            print(f"[dental-p6b] session-level ERROR: {e}", flush=True)
            _touch()

    print("[dental-p6b] DONE ALL", flush=True)


if __name__ == "__main__":
    main()
