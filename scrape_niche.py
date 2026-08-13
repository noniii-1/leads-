# -*- coding: utf-8 -*-
"""
Discover businesses on Google Maps for a given niche that have:
- reviews_count >= 15
- NO website registered on Maps

Usage: python scrape_niche.py <niche_key>
niche_key in {abogados, fotografos, manicure}
"""
import sys
import time
import json
import re
from scrapling.fetchers import StealthySession
from parse_utils import parse_article

TARGET = 129
MIN_REVIEWS = 15

COMUNAS = [
    "Santiago Centro", "Providencia", "Las Condes", "Ñuñoa", "La Florida",
    "Maipú", "Puente Alto", "San Bernardo", "Vitacura", "Peñalolén",
    "Macul", "La Reina", "Recoleta", "Independencia", "San Miguel",
    "La Cisterna", "Estación Central", "Quinta Normal", "Conchalí", "Renca",
    "Pudahuel", "Cerrillos", "Lo Barnechea", "Huechuraba", "Quilicura",
    "Pedro Aguirre Cerda", "San Joaquín", "El Bosque", "Lo Prado", "Cerro Navia",
    "Colina", "Buin", "Melipilla", "Talagante", "Peñaflor", "San Ramón",
    "La Granja", "Padre Hurtado",
]

NICHES = {
    "abogados": {
        "group": "legal_contable",
        "label": "Abogados / contadores independientes",
        "keywords": [
            "abogado laboral", "abogado familia", "abogado penalista", "abogado civil",
            "estudio juridico abogado", "abogado tributario", "bufete abogados",
            "abogado divorcio pension alimentos", "contador auditor independiente",
            "asesoria contable tributaria", "abogado comercial empresas",
            "abogado inmobiliario", "abogado migracion extranjeria", "notaria abogado",
            "abogado transito accidentes", "abogado seguros", "abogado herencias posesion efectiva",
            "abogado arriendos", "estudio contable pyme", "contador independiente",
            "abogado constitucion empresas", "abogado deudas dicom", "abogado consumidor sernac",
            "asesoria juridica online", "abogado querella denuncia",
        ],
    },
    "fotografos": {
        "group": "fotografia_eventos",
        "label": "Fotografía / video de bodas y eventos",
        "keywords": [
            "fotografo matrimonios", "fotografo eventos", "fotografo retratos estudio",
            "estudio fotografico", "videografo bodas", "fotografo quinceanos",
            "fotografo familiar sesion", "fotografo newborn embarazo",
            "fotografo corporativo eventos", "fotografo book",
            "fotografo producto ecommerce", "fotografo graduacion", "fotografo mascotas",
            "fotografo maternidad", "fotografo moda editorial", "drone fotografia video",
            "fotografo freelance", "estudio de imagen fotografia", "fotografia carnet pasaporte",
            "fotografo cumpleanos", "video producciones audiovisuales", "fotografo deportivo",
            "fotografo inmobiliario", "fotografo comida gastronomia",
        ],
    },
    "manicure": {
        "group": "manicure",
        "label": "Manicure / uñas / lifting",
        "keywords": [
            "manicure pedicure", "salon de unas", "lifting de pestanas",
            "centro de estetica unas", "unas acrilicas gel", "microblading cejas",
            "extension de pestanas", "spa de unas", "nail salon", "unas semipermanente",
        ],
    },
}


def build_queries(niche_key):
    n = NICHES[niche_key]
    queries = []
    for kw in n["keywords"]:
        for comuna in COMUNAS:
            queries.append(f"{kw} {comuna} Santiago")
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
                page.wait_for_timeout(1000)
        except Exception:
            pass
        return page
    return _action


def main():
    niche_key = sys.argv[1]
    n = NICHES[niche_key]
    queries = build_queries(niche_key)

    out_path = f"niche_{niche_key}.jsonl"
    seen_names = set()
    qualifying_count = 0

    # resume support: load already-seen qualifying names
    try:
        with open(out_path, "r", encoding="utf-8") as f:
            for line in f:
                rec = json.loads(line)
                seen_names.add(rec["name"].strip().lower())
                qualifying_count += 1
    except FileNotFoundError:
        pass

    print(f"[{niche_key}] starting with {qualifying_count} already qualifying, target {TARGET}", flush=True)

    with StealthySession(headless=True, network_idle=False, max_pages=1) as session:
        for qi, query in enumerate(queries, start=1):
            if qualifying_count >= TARGET:
                print(f"[{niche_key}] target reached, stopping", flush=True)
                break
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
                        rec["niche"] = niche_key
                        rec["group"] = n["group"]
                        rec["label"] = n["label"]
                        rec["source_query"] = query
                        with open(out_path, "a", encoding="utf-8") as fout:
                            fout.write(json.dumps(rec, ensure_ascii=False) + "\n")
                        qualifying_count += 1
                        new_this_query += 1
                print(f"[{niche_key}] [{qi}/{len(queries)}] '{query}' -> {len(articles)} items, +{new_this_query} qualifying (total {qualifying_count})", flush=True)
            except Exception as e:
                print(f"[{niche_key}] [{qi}/{len(queries)}] '{query}' ERROR: {e}", flush=True)
            time.sleep(0.8)

    print(f"[{niche_key}] DONE. total qualifying: {qualifying_count}", flush=True)


if __name__ == "__main__":
    main()
