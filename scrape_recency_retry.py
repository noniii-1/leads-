# -*- coding: utf-8 -*-
"""
Retry the "unknown" (no date parsed) businesses from scrape_recency.py, using:
- the precise maps_url for the 89 "existing" ones (more reliable than text search)
- a simplified name (before any "|") + city query for the "new" ones

Overwrites their entries in recency_results.jsonl (removes old unknown rows for
these names, appends fresh results) so the file stays one-row-per-business.
"""
import json
import re
import time
from scrapling.fetchers import StealthySession
from scrape_recency import parse_min_days  # this import already re-wraps stdout/stderr as UTF-8

OUT_PATH = "recency_results.jsonl"


def load_unknowns():
    recs = [json.loads(l) for l in open(OUT_PATH, encoding='utf-8')]
    unknown_names = {r['name'].strip().lower() for r in recs if r['most_recent_review_days'] is None}

    existing = {d['name'].strip().lower(): d for d in json.load(open('dental_keep_step1.json', encoding='utf-8'))}
    new = {d['name'].strip().lower(): d for d in json.load(open('new_dental_leads.json', encoding='utf-8'))}

    targets = []
    for r in recs:
        key = r['name'].strip().lower()
        if key not in unknown_names:
            continue
        if r['source'] == 'existing' and key in existing:
            targets.append({'name': r['name'], 'city': r['city'], 'source': 'existing',
                             'maps_url': existing[key].get('maps_url')})
        elif r['source'] == 'new' and key in new:
            targets.append({'name': r['name'], 'city': r['city'], 'source': 'new',
                             'maps_url': None})
    return targets


def do_open_url(url):
    def _action(page):
        page.wait_for_timeout(4500)
        return page
    return _action


def do_open_search(query):
    def _action(page):
        page.wait_for_timeout(1200)
        box = page.locator('input[name="q"]')
        box.click()
        box.fill(query)
        box.press("Enter")
        page.wait_for_timeout(4500)
        return page
    return _action


def main():
    targets = load_unknowns()
    print(f"[retry] {len(targets)} unknown businesses to retry", flush=True)

    results = {}
    with StealthySession(headless=True, network_idle=True, max_pages=1) as session:
        for i, t in enumerate(targets, start=1):
            try:
                if t['maps_url']:
                    page = session.fetch(t['maps_url'], page_action=do_open_url(t['maps_url']), timeout=45000)
                else:
                    simple_name = t['name'].split('|')[0].strip()
                    query = f"{simple_name} {t['city']} Chile"
                    page = session.fetch("https://www.google.com/maps", page_action=do_open_search(query), timeout=45000)
                txt = page.get_all_text()
                min_days = parse_min_days(txt)
                has_website = ('Visitar el sitio web' in txt) or bool(re.search(r'https?://(?!www\.google)[^\s"]+\.(cl|com|net|org)', txt))
                results[t['name'].strip().lower()] = {
                    'name': t['name'], 'city': t['city'], 'source': t['source'],
                    'most_recent_review_days': min_days, 'has_website_detail': has_website,
                }
                print(f"[{i}/{len(targets)}] {t['name']!r} -> min_days={min_days} has_web={has_website}", flush=True)
            except Exception as e:
                print(f"[{i}/{len(targets)}] {t['name']!r} ERROR: {e}", flush=True)
            time.sleep(0.5)

    # merge back into recency_results.jsonl: replace rows for retried names
    old = [json.loads(l) for l in open(OUT_PATH, encoding='utf-8')]
    merged = []
    for r in old:
        key = r['name'].strip().lower()
        if key in results:
            merged.append(results.pop(key))
        else:
            merged.append(r)
    # any leftover (shouldn't happen) append
    merged.extend(results.values())

    with open(OUT_PATH, 'w', encoding='utf-8') as f:
        for r in merged:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print("[retry] DONE, merged back into", OUT_PATH, flush=True)


if __name__ == "__main__":
    main()
