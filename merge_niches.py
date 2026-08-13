# -*- coding: utf-8 -*-
import json
import re

FILES = {
    "manicure": "niche_manicure.jsonl",
    "abogados": "niche_abogados.jsonl",
    "fotografos": "niche_fotografos.jsonl",
}

HOURS_WORDS = {"Abierto", "Cerrado", "Cierra pronto", "Abierto las 24 horas", "Cerrado temporalmente"}

BUSINESS_TYPE = {
    "manicure": "Negocio pequeño de trato directo, probablemente gestionado por su dueña/o — buen candidato para hablar con quien decide.",
    "abogados": "Presupuesto real y ROI directo — un cliente nuevo vale miles de dólares; decisor único y accesible por WhatsApp, ciclo de venta algo más formal.",
    "fotografos": "El producto se vende solo con su propio portafolio de fotos — bajo riesgo de objeción de confianza, ideal para mostrar un sitio nuevo hecho con su propio trabajo.",
}

PHONE_RE = re.compile(r'^(9\s?\d{4}\s?\d{4}|\(2\)\s?\d{3,4}\s?\d{4}|600\s?\d{3}\s?\d{4}|\d{2}\s?\d{4}\s?\d{4})$')


def clean_record(rec):
    address = rec.get("address", "").strip()
    category = rec.get("category", "").strip()

    # fix swapped address/category (address ended up holding an hours-status word)
    if address in HOURS_WORDS or address.startswith("Cierra") or address.startswith("Abre") or address == "":
        if any(ch.isdigit() for ch in category):
            address = category
            category = ""
        else:
            address = ""

    name = rec["name"].strip()
    # some names got polluted with trailing city words from the query itself; leave as-is (still a real name)

    phone = rec.get("phone", "").strip()
    if phone and not PHONE_RE.match(phone):
        phone = ""

    return {
        "name": name,
        "rating": rec.get("rating"),
        "reviews": rec.get("reviews", 0),
        "category": category,
        "address": address,
        "phone": phone,
        "niche": rec["niche"],
        "group": rec["group"],
        "label": rec["label"],
    }


def slugify(s):
    s = s.lower()
    s = re.sub(r"[^a-z0-9]+", "_", s)
    return s.strip("_")[:40]


def phone_e164(phone):
    if not phone:
        return None
    digits = re.sub(r"\D", "", phone)
    if digits.startswith("9") and len(digits) == 9:
        return "+56" + digits
    if digits.startswith("56"):
        return "+" + digits
    if digits.startswith("2") and len(digits) == 8:
        return "+562" + digits
    if len(digits) >= 7:
        return "+56" + digits
    return None


def score_for(rating, reviews):
    rating = rating or 0
    score = int(round(rating * 15))
    if reviews >= 300:
        rb = 25
    elif reviews >= 100:
        rb = 18
    elif reviews >= 30:
        rb = 12
    elif reviews >= 15:
        rb = 6
    else:
        rb = 0
    score += rb
    score += 20  # sin_web bonus (all of these qualify as no-website)
    return max(25, min(100, score))


def reputation_label(rating):
    if rating is None:
        return ""
    if rating >= 4.7:
        return "Reputación excelente"
    if rating >= 4.3:
        return "Reputación muy sólida"
    if rating >= 3.8:
        return "Reputación buena"
    return "Reputación mixta"


def main():
    # load existing dataset to dedupe against
    with open("leads_santiago_dashboard.html", encoding="utf-8") as f:
        html = f.read()
    start_tag = '<script id="leads-data" type="application/json">'
    start = html.index(start_tag) + len(start_tag)
    end = html.index("</script>", start)
    existing = json.loads(html[start:end])
    existing_names = {e["name"].strip().lower() for e in existing}
    print("existing leads:", len(existing), flush=True)

    all_new = []
    seen = set()
    idx = len(existing) + 1
    for niche, path in FILES.items():
        with open(path, encoding="utf-8") as f:
            for line in f:
                raw = json.loads(line)
                rec = clean_record(raw)
                key = rec["name"].strip().lower()
                if key in existing_names or key in seen:
                    continue
                seen.add(key)

                city = "Santiago"
                # try to pull a comuna hint from source_query if available
                sq = raw.get("source_query", "")
                m = re.search(r"(Santiago Centro|Providencia|Las Condes|Ñuñoa|La Florida|Maipú|Puente Alto|San Bernardo|Vitacura|Peñalolén|Macul|La Reina|Recoleta|Independencia|San Miguel|La Cisterna|Estación Central|Quinta Normal|Conchalí|Renca|Pudahuel|Cerrillos|Lo Barnechea|Huechuraba|Quilicura|Pedro Aguirre Cerda|San Joaquín|El Bosque|Lo Prado|Cerro Navia|Colina|Buin|Melipilla|Talagante|Peñaflor|San Ramón|La Granja|Padre Hurtado)", sq)
                if m:
                    city = m.group(1)

                cat_tag = rec["category"] or rec["label"]
                cid = f"gm2_{idx}_{slugify(rec['name'])}"
                idx += 1

                rating = rec["rating"]
                reviews = rec["reviews"]
                rep = reputation_label(rating)
                if rating and reviews:
                    satisfied = ", clientes consistentemente satisfechos" if rating >= 4.5 else ""
                    summary = f"{cat_tag} en {city}. {rep}: {rating} en {reviews} reseñas{satisfied}."
                else:
                    summary = f"{cat_tag} en {city}."

                addr = rec["address"] or city
                maps_query = f"{rec['name']} {addr}".replace("&", "%26").replace("#", "%23")
                maps_url = "https://www.google.com/maps/search/?api=1&query=" + maps_query.replace(" ", "+")

                entry = {
                    "cid": cid,
                    "name": rec["name"],
                    "phone": rec["phone"] or None,
                    "phone_e164": phone_e164(rec["phone"]),
                    "website": None,
                    "has_website": False,
                    "web_tier": "sin_web",
                    "web_tier_label": "Sin sitio web",
                    "web_note": "No tiene web — oportunidad clara para ofrecer una (verificado en Maps).",
                    "city": city,
                    "rating": rating,
                    "reviews_count": reviews,
                    "category_tag": cat_tag,
                    "category_group": rec["group"],
                    "category_label": rec["label"],
                    "address": addr,
                    "maps_url": maps_url,
                    "score": score_for(rating, reviews),
                    "chain_flag": False,
                    "summary": summary,
                    "business_type": BUSINESS_TYPE[niche],
                    "is_new_batch": True,
                }
                all_new.append(entry)

    print("new unique qualifying leads to add:", len(all_new), flush=True)
    by_niche = {}
    for e in all_new:
        by_niche[e["category_group"]] = by_niche.get(e["category_group"], 0) + 1
    print("by niche:", by_niche, flush=True)

    combined = existing + all_new

    total = len(combined)
    cities = len({e["city"] for e in combined})
    total_reviews = sum(e.get("reviews_count") or 0 for e in combined)
    rated = [e["rating"] for e in combined if e.get("rating")]
    avg_rating = sum(rated) / len(rated) if rated else 0

    stats = {
        "total": total,
        "cities": cities,
        "total_reviews": total_reviews,
        "avg_rating": avg_rating,
    }
    print("new stats:", stats, flush=True)

    with open("combined_leads.json", "w", encoding="utf-8") as f:
        json.dump(combined, f, ensure_ascii=False)
    with open("combined_stats.json", "w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False)

    print("DONE", flush=True)


if __name__ == "__main__":
    main()
