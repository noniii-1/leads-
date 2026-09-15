# -*- coding: utf-8 -*-
"""
Second pass: more keyword variants over the same 33 comunas, appending to the
same dental_candidates.jsonl (resumable via seen_names, same as scrape_dental.py).
"""
import time
import json
from scrapling.fetchers import StealthySession
from parse_utils import parse_article

MIN_REVIEWS = 20
OUT_PATH = "dental_candidates.jsonl"

COMUNAS = [
    "Santiago Centro", "Providencia", "Las Condes", "Vitacura", "Lo Barnechea",
    "La Reina", "Ñuñoa", "Macul", "Peñalolén", "La Florida",
    "San Joaquín", "La Granja", "La Pintana", "San Ramón", "El Bosque",
    "La Cisterna", "San Miguel", "Pedro Aguirre Cerda", "Lo Espejo", "Estación Central",
    "Cerrillos", "Maipú", "Cerro Navia", "Pudahuel", "Lo Prado",
    "Quinta Normal", "Renca", "Quilicura", "Huechuraba", "Conchalí",
    "Independencia", "Recoleta", "Puente Alto", "San Bernardo",
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


def main():
    queries = build_queries()
    seen_names = set()
    qualifying_count = 0

    try:
        with open(OUT_PATH, "r", encoding="utf-8") as f:
            for line in f:
                rec = json.loads(line)
                seen_names.add(rec["name"].strip().lower())
                qualifying_count += 1
    except FileNotFoundError:
        pass

    print(f"[dental-extra] starting with {qualifying_count} already qualifying, {len(queries)} queries total", flush=True)

    with StealthySession(headless=True, network_idle=False, max_pages=1) as session:
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
                print(f"[dental-extra] [{qi}/{len(queries)}] '{query}' -> {len(articles)} items, +{new_this_query} qualifying (total {qualifying_count})", flush=True)
            except Exception as e:
                print(f"[dental-extra] [{qi}/{len(queries)}] '{query}' ERROR: {e}", flush=True)
            time.sleep(0.6)

    print(f"[dental-extra] DONE. total qualifying: {qualifying_count}", flush=True)


if __name__ == "__main__":
    main()
