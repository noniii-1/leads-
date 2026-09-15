# -*- coding: utf-8 -*-
"""
Phase 2: for every dental lead (the 89 kept from before + the ~147 freshly
scraped), open its Google Maps detail page and check:
- most recent visible review's relative date (proxy for "reseña reciente")
- whether "Sitio web" still shows (double-check no real website slipped through)

Writes recency_results.jsonl: {name, city, most_recent_days, has_website_detail, raw_dates}
Resumable via seen names already in the output file.
"""
import os
import json
import re
import sys
import io
import time
import threading
from scrapling.fetchers import StealthySession

# avoid crashing on business names with emoji/symbols the Windows console
# codepage can't encode (this silently orphaned ~49 items on the first run)
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

OUT_PATH = "recency_results.jsonl"
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
            print(f"[recency] WATCHDOG: no progress for {stale:.0f}s, force-exiting", flush=True)
            os._exit(1)

DATE_RE = re.compile(
    r'Hace\s+(un|una|\d+)\s+(d[ií]a|d[ií]as|semana|semanas|mes|meses|a[ñn]o|a[ñn]os)',
    re.IGNORECASE
)

UNIT_DAYS = {
    'dia': 1, 'día': 1, 'dias': 1, 'días': 1,
    'semana': 7, 'semanas': 7,
    'mes': 30, 'meses': 30,
    'ano': 365, 'año': 365, 'anos': 365, 'años': 365,
}


def parse_min_days(text):
    best = None
    for m in DATE_RE.finditer(text):
        n_raw, unit_raw = m.group(1), m.group(2).lower()
        n = 1 if n_raw.lower() in ('un', 'una') else int(n_raw)
        unit_key = unit_raw.replace('í', 'i').replace('ñ', 'n')
        # normalize back after stripping accents for dict lookup
        unit_key = {
            'dia': 'dia', 'dias': 'dia',
            'semana': 'semana', 'semanas': 'semana',
            'mes': 'mes', 'meses': 'mes',
            'ano': 'ano', 'anos': 'ano',
        }.get(unit_key, unit_key)
        base = {'dia': 1, 'semana': 7, 'mes': 30, 'ano': 365}.get(unit_key)
        if base is None:
            continue
        days = n * base
        if best is None or days < best:
            best = days
    return best


BAD_ADDR_RE = re.compile(r'[ሀ-፿]')  # garbled OCR (Ethiopic block) seen in a couple of records


def clean_addr(addr):
    addr = addr or ''
    if BAD_ADDR_RE.search(addr):
        return ''
    return addr


def load_targets():
    targets = []
    with open('dental_keep_step1.json', encoding='utf-8') as f:
        existing = json.load(f)
    for e in existing:
        targets.append({
            'name': e['name'],
            'city': e.get('city', ''),
            'address': clean_addr(e.get('address', '')),
            'source': 'existing',
        })
    with open('new_dental_leads.json', encoding='utf-8') as f:
        new = json.load(f)
    for e in new:
        targets.append({
            'name': e['name'],
            'city': e.get('city', ''),
            'address': clean_addr(e.get('address', '')),
            'source': 'new',
        })
    return targets


def do_open(query):
    def _action(page):
        page.wait_for_timeout(1200)
        box = page.locator('input[name="q"]')
        box.click()
        box.fill(query)
        box.press("Enter")
        page.wait_for_timeout(4500)
        return page
    return _action


def run_batch(targets, session):
    seen = set()
    try:
        with open(OUT_PATH, encoding='utf-8') as f:
            for line in f:
                rec = json.loads(line)
                seen.add(rec['name'].strip().lower())
    except FileNotFoundError:
        pass

    for i, t in enumerate(targets, start=1):
        key = t['name'].strip().lower()
        if key in seen:
            continue
        query = f"{t['name']} {t.get('address') or t.get('city') or ''} Santiago Chile"
        try:
            page = session.fetch("https://www.google.com/maps", page_action=do_open(query), timeout=45000)
            txt = page.get_all_text()
            min_days = parse_min_days(txt)
            has_website = ('Visitar el sitio web' in txt) or bool(re.search(r'https?://(?!www\.google)[^\s"]+\.(cl|com|net|org)', txt))
            result = {
                'name': t['name'],
                'city': t['city'],
                'source': t['source'],
                'most_recent_review_days': min_days,
                'has_website_detail': has_website,
            }
            with open(OUT_PATH, 'a', encoding='utf-8') as fout:
                fout.write(json.dumps(result, ensure_ascii=False) + "\n")
            print(f"[{i}/{len(targets)}] {t['name']!r} -> min_days={min_days} has_web={has_website}", flush=True)
            _touch()
        except Exception as e:
            print(f"[{i}/{len(targets)}] {t['name']!r} ERROR: {e}", flush=True)
            _touch()
        time.sleep(0.5)


def main():
    t = threading.Thread(target=_watchdog, daemon=True)
    t.start()

    targets = load_targets()
    print(f"[recency] {len(targets)} businesses to check", flush=True)

    CHUNK = 35
    for start in range(0, len(targets), CHUNK):
        chunk = targets[start:start + CHUNK]
        print(f"[recency] opening fresh session for {start+1}-{start+len(chunk)}", flush=True)
        _touch()
        try:
            with StealthySession(headless=True, network_idle=True, max_pages=1) as session:
                run_batch(chunk, session)
        except Exception as e:
            print(f"[recency] session-level ERROR: {e}", flush=True)
            _touch()

    print("[recency] DONE ALL", flush=True)


if __name__ == "__main__":
    main()
