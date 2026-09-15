# -*- coding: utf-8 -*-
"""
Continuation of scrape_dental_extra.py after it died mid-run (crashed silently,
exit code 4, no traceback). Covers only the remaining comunas with the same
extra keyword set, appending to the same dental_candidates.jsonl.
"""
import time
import json
from scrapling.fetchers import StealthySession
from parse_utils import parse_article

MIN_REVIEWS = 20
OUT_PATH = "dental_candidates.jsonl"

# comunas NOT yet covered by the extra-keyword pass (it died partway through Lo Espejo)
COMUNAS = [
    "Lo Espejo", "Estación Central", "Cerrillos", "Maipú", "Cerro Navia",
    "Pudahuel", "Lo Prado", "Quinta Normal", "Renca", "Quilicura",
    "Huechuraba", "Conchalí", "Independencia", "Recoleta", "Puente Alto",
    "San Bernardo",
]

KEYWORDS = [
    "clinica odontologica", "urgencia dental", "ortodoncia",
    "implantes dentales", "endodoncia", "dentista de confianza",
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


def run_batch(queries, session):
    seen_names = set()
    try:
        with open(OUT_PATH, "r", encoding="utf-8") as f:
            for line in f:
                rec = json.loads(line)
                seen_names.add(rec["name"].strip().lower())
    except FileNotFoundError:
        pass

    qualifying_count = len(seen_names)
    for qi, (query, comuna) in enumerate(queries, start=1):
        url = "https://www.google.com/maps"
        try:
            page = session.fetch(url, page_action=do_search(query), timeout=45000)
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
            print(f"[dental-extra2] [{qi}/{len(queries)}] '{query}' -> {len(articles)} items, +{new_this_query} qualifying (total {qualifying_count})", flush=True)
        except Exception as e:
            print(f"[dental-extra2] [{qi}/{len(queries)}] '{query}' ERROR: {e}", flush=True)
        time.sleep(0.6)


def main():
    queries = build_queries()
    print(f"[dental-extra2] {len(queries)} queries total across {len(COMUNAS)} comunas", flush=True)

    # restart the whole session every 40 queries to reduce the chance of a long-lived
    # browser process crashing and killing the whole run (previous run died silently)
    CHUNK = 40
    for start in range(0, len(queries), CHUNK):
        chunk = queries[start:start + CHUNK]
        print(f"[dental-extra2] opening fresh session for queries {start+1}-{start+len(chunk)}", flush=True)
        try:
            with StealthySession(headless=True, network_idle=False, max_pages=1) as session:
                run_batch(chunk, session)
        except Exception as e:
            print(f"[dental-extra2] session-level ERROR: {e}", flush=True)

    print("[dental-extra2] DONE ALL", flush=True)


if __name__ == "__main__":
    main()
