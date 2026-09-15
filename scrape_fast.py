# -*- coding: utf-8 -*-
"""
Faster combined pipeline: for each search query, harvest candidates AND verify
recency in the same pass (no separate recency-check run afterward), with
shorter scroll waits, and shardable so several instances can run in parallel.

Usage: python scrape_fast.py <shard_index> <shard_count>
  e.g. python scrape_fast.py 0 3   (this is shard 0 of 3 parallel workers)

Writes verified_leads_shard<N>.jsonl with fully-verified records:
  name, rating, reviews, category, address, phone, city,
  most_recent_review_days, source_query
"""
import os
import re
import sys
import time
import json
import threading
from scrapling.fetchers import StealthySession
from parse_utils import parse_article
from scrape_recency import parse_min_days

MIN_REVIEWS = 10
RECENCY_MAX_DAYS = 183
WATCHDOG_SECS = 100

CLEAR_DENTAL_TAGS = {'dentista', 'clínica dental', 'ortodoncista', 'clínica odontológica'}
DENTAL_KEYWORDS = ['dental', 'odont', 'dentist', 'denti', 'sonrisa', 'ortodon']


def is_real_dental(rec):
    if (rec.get("category") or "").strip().lower() in CLEAR_DENTAL_TAGS:
        return True
    name_l = rec["name"].strip().lower()
    return any(k in name_l for k in DENTAL_KEYWORDS)

SHARD_INDEX = int(sys.argv[1]) if len(sys.argv) > 1 else 0
SHARD_COUNT = int(sys.argv[2]) if len(sys.argv) > 2 else 1
OUT_PATH = f"verified_leads_shard{SHARD_INDEX}.jsonl"

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
            print(f"[fast-{SHARD_INDEX}] WATCHDOG: no progress for {stale:.0f}s, force-exiting", flush=True)
            os._exit(1)


COMUNAS = [
    "Santiago Centro", "Providencia", "Las Condes", "Vitacura", "Lo Barnechea",
    "La Reina", "Ñuñoa", "Macul", "Peñalolén", "La Florida",
    "San Joaquín", "La Granja", "La Pintana", "San Ramón", "El Bosque",
    "La Cisterna", "San Miguel", "Pedro Aguirre Cerda", "Lo Espejo", "Estación Central",
    "Cerrillos", "Maipú", "Cerro Navia", "Pudahuel", "Lo Prado",
    "Quinta Normal", "Renca", "Quilicura", "Huechuraba", "Conchalí",
    "Independencia", "Recoleta", "Puente Alto", "San Bernardo",
]

# fresh keyword angles not yet tried at MIN_REVIEWS=10
KEYWORDS = [
    "clinica dental vanguardia", "dentista recomendado", "clinica dental bienestar",
    "consulta particular dental", "clinica dental full", "dentista especializado",
    "clinica dental profesional", "odontologo particular",
]


def build_queries():
    all_q = []
    for comuna in COMUNAS:
        for kw in KEYWORDS:
            all_q.append((f"{kw} {comuna} Santiago Chile", comuna))
    # round-robin shard split so each shard gets a mix of comunas, not a block
    return [q for i, q in enumerate(all_q) if i % SHARD_COUNT == SHARD_INDEX]


def do_search(query):
    def _action(page):
        page.wait_for_timeout(800)
        box = page.locator('input[name="q"]')
        box.click()
        box.fill(query)
        box.press("Enter")
        # wait for the real results feed to attach instead of a blind guess —
        # faster on quick responses, still safe on slow ones
        try:
            page.wait_for_selector('div[role="feed"] > div', timeout=8000)
        except Exception:
            page.wait_for_timeout(2000)
        feed = page.locator('div[role="feed"]')
        try:
            for _ in range(5):
                feed.evaluate("el => el.scrollTop = el.scrollHeight")
                page.wait_for_timeout(700)
        except Exception:
            pass
        return page
    return _action


def do_open_url(url):
    def _action(page):
        page.wait_for_timeout(4000)
        return page
    return _action


def check_recency_inline(session, name, href):
    """Open the place page for a qualifying candidate and check its recency
    right away, in the same session/pass."""
    try:
        page = session.fetch(href, page_action=do_open_url(href), timeout=25000,
                              network_idle=True, disable_resources=True)
        txt = page.get_all_text()
        min_days = parse_min_days(txt)
        has_web_detail = ('Visitar el sitio web' in txt) or bool(
            re.search(r'https?://(?!www\.google)[^\s"]+\.(cl|com|net|org)', txt)
        )
        return min_days, has_web_detail
    except Exception as e:
        print(f"[fast-{SHARD_INDEX}]   recency-check ERROR for {name!r}: {e}", flush=True)
        return None, False


def load_all_known_names():
    """Every business already found across passes 1-11 (raw candidates, both
    qualifying and not) plus the original 89 kept clinics — so this fast pass
    never re-fetches a detail page we've already spent time on."""
    names = set()
    for path in ("dental_candidates.jsonl",):
        try:
            with open(path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    names.add(json.loads(line)["name"].strip().lower())
        except FileNotFoundError:
            pass
    for path in ("dental_keep_step1.json",):
        try:
            with open(path, encoding="utf-8") as f:
                for d in json.load(f):
                    names.add(d["name"].strip().lower())
        except FileNotFoundError:
            pass
    return names


_ALL_KNOWN_NAMES = load_all_known_names()
print(f"[fast-{SHARD_INDEX}] seeded {len(_ALL_KNOWN_NAMES)} already-known business names to skip", flush=True)


def run_batch(queries, session):
    seen_names = set(_ALL_KNOWN_NAMES)
    try:
        with open(OUT_PATH, "r", encoding="utf-8") as f:
            for line in f:
                rec = json.loads(line)
                seen_names.add(rec["name"].strip().lower())
    except FileNotFoundError:
        pass

    verified_count = 0
    for i, (query, comuna) in enumerate(queries, start=1):
        url = "https://www.google.com/maps"
        try:
            # NOTE: disable_resources=True breaks this fetch — with resources
            # blocked, the map canvas overlay intercepts the click on the
            # search box (page_action needs real interaction here), so it's
            # only safe on the read-only detail-page fetch below.
            page = session.fetch(url, page_action=do_search(query), timeout=30000,
                                  network_idle=False)
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
                if key in seen_names or rec["reviews"] < MIN_REVIEWS or rec["has_website"]:
                    continue
                if rec.get("rating") is not None and rec["rating"] < 3.0:
                    continue
                if not is_real_dental(rec):
                    continue
                link_els = a.css('a.hfpxzc')
                href = link_els[0].attrib.get('href') if link_els else None
                if not href:
                    continue
                seen_names.add(key)  # mark seen even if it fails recency, to avoid re-checking
                min_days, has_web_detail = check_recency_inline(session, rec["name"], href)
                if min_days is not None and min_days <= RECENCY_MAX_DAYS and not has_web_detail:
                    rec["city"] = comuna
                    rec["source_query"] = query
                    rec["most_recent_review_days"] = min_days
                    with open(OUT_PATH, "a", encoding="utf-8") as fout:
                        fout.write(json.dumps(rec, ensure_ascii=False) + "\n")
                    verified_count += 1
                    new_this_query += 1
                _touch()
            print(f"[fast-{SHARD_INDEX}] [{i}/{len(queries)}] '{query}' -> {len(articles)} items, +{new_this_query} verified (total {verified_count})", flush=True)
            _touch()
        except Exception as e:
            print(f"[fast-{SHARD_INDEX}] [{i}/{len(queries)}] '{query}' ERROR: {e}", flush=True)
            _touch()
        time.sleep(0.4)


def main():
    t = threading.Thread(target=_watchdog, daemon=True)
    t.start()

    queries = build_queries()
    print(f"[fast-{SHARD_INDEX}] shard {SHARD_INDEX}/{SHARD_COUNT}: {len(queries)} queries", flush=True)

    CHUNK = 25
    for start in range(0, len(queries), CHUNK):
        chunk = queries[start:start + CHUNK]
        print(f"[fast-{SHARD_INDEX}] opening fresh session for {start+1}-{start+len(chunk)}", flush=True)
        _touch()
        try:
            with StealthySession(headless=True, network_idle=True, max_pages=1) as session:
                run_batch(chunk, session)
        except Exception as e:
            print(f"[fast-{SHARD_INDEX}] session-level ERROR: {e}", flush=True)
            _touch()

    print(f"[fast-{SHARD_INDEX}] DONE ALL", flush=True)


if __name__ == "__main__":
    main()
