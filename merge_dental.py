# -*- coding: utf-8 -*-
"""
Merge dental_candidates.jsonl (raw scrape) into the dashboard's leads-data,
deduped against the 89 clinics already kept, formatted with the same schema.

Writes new_dental_leads.json (list of lead dicts, NOT yet inserted into the HTML)
and prints a summary.
"""
import json
import re

RAW_PATH = "dental_candidates.jsonl"
EXISTING_HTML = "leads_santiago_dashboard.html"
OUT_PATH = "new_dental_leads.json"

PHONE_RE = re.compile(r'^(9\s?\d{4}\s?\d{4}|\(2\)\s?\d{3,4}\s?\d{4}|600\s?\d{3}\s?\d{4}|\d{2}\s?\d{4}\s?\d{4})$')

# only these Maps category tags are unambiguously a dental clinic; anything else
# (Centro médico, Médico, CESFAM/Consultorio/SAPU, Hospital, Oficinas de empresa, etc.)
# must have a dental keyword in the name to be kept (mirrors the manual purge earlier)
CLEAR_DENTAL_TAGS = {
    'dentista', 'clínica dental', 'ortodoncista', 'clínica odontológica',
}
DENTAL_KEYWORDS = ['dental', 'odont', 'dentist', 'denti', 'sonrisa', 'ortodon']


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
    elif reviews >= 20:
        rb = 8
    else:
        rb = 4
    score += rb
    score += 20  # sin_web bonus
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


BUSINESS_TYPE = (
    "Clínica/consulta dental de tamaño chico-mediano — el dentista suele ser también "
    "el dueño y el que decide, buen candidato para ofrecerle una web con agenda de horas online."
)


def main():
    with open(EXISTING_HTML, encoding="utf-8") as f:
        html = f.read()
    start_tag = '<script id="leads-data" type="application/json">'
    start = html.index(start_tag) + len(start_tag)
    end = html.index("</script>", start)
    existing = json.loads(html[start:end])
    existing_names = {e["name"].strip().lower() for e in existing}
    print("existing dental leads:", len(existing))

    raw = []
    try:
        with open(RAW_PATH, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                raw.append(json.loads(line))
    except FileNotFoundError:
        print("no raw candidates file found yet")
        return

    print("raw scraped candidates:", len(raw))

    seen = set()
    new_leads = []
    idx = len(existing) + 1
    skipped_non_dental = 0
    skipped_dupe = 0
    skipped_low_rating = 0

    # sort by reviews desc so the best (highest-traffic) candidates get first pick
    raw_sorted = sorted(raw, key=lambda r: r.get("reviews", 0) or 0, reverse=True)

    for rec in raw_sorted:
        name = rec["name"].strip()
        key = name.lower()
        if key in existing_names or key in seen:
            skipped_dupe += 1
            continue

        category = (rec.get("category") or "").strip()
        name_l = name.lower()
        if category.lower() not in CLEAR_DENTAL_TAGS and not any(k in name_l for k in DENTAL_KEYWORDS):
            skipped_non_dental += 1
            continue

        rating = rec.get("rating")
        reviews = rec.get("reviews", 0)
        if rating is not None and rating < 3.0:
            skipped_low_rating += 1
            continue

        seen.add(key)

        phone = rec.get("phone", "").strip()
        if phone and not PHONE_RE.match(phone):
            phone = ""

        city = rec.get("comuna_query", "Santiago")
        cat_tag = category or "Clínica dental"
        cid = f"gm4_{idx}_{slugify(name)}"
        idx += 1

        rep = reputation_label(rating)
        if rating and reviews:
            satisfied = ", clientes consistentemente satisfechos" if rating >= 4.5 else ""
            summary = f"{cat_tag} en {city}. {rep}: {rating} en {reviews} reseñas{satisfied}."
        else:
            summary = f"{cat_tag} en {city}."

        addr = rec.get("address") or city
        maps_query = f"{name} {addr}".replace("&", "%26").replace("#", "%23")
        maps_url = "https://www.google.com/maps/search/?api=1&query=" + maps_query.replace(" ", "+")

        entry = {
            "cid": cid,
            "name": name,
            "phone": phone or None,
            "phone_e164": phone_e164(phone),
            "website": None,
            "has_website": False,
            "web_tier": "sin_web",
            "web_tier_label": "Sin sitio web",
            "web_note": "No tiene web — oportunidad clara para ofrecer una (verificado en Maps).",
            "city": city,
            "rating": rating,
            "reviews_count": reviews,
            "category_tag": cat_tag,
            "category_group": "clinica_dental",
            "category_label": "Clínica dental",
            "address": addr,
            "maps_url": maps_url,
            "score": score_for(rating, reviews),
            "chain_flag": False,
            "summary": summary,
            "business_type": BUSINESS_TYPE,
            "is_new_batch": True,
            "source_query": rec.get("source_query", ""),
        }
        new_leads.append(entry)

    print("skipped (duplicate of existing/seen):", skipped_dupe)
    print("skipped (non-dental category leaked through):", skipped_non_dental)
    print("skipped (rating < 3.0, quality floor):", skipped_low_rating)
    print("new unique qualifying dental leads:", len(new_leads))

    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(new_leads, f, ensure_ascii=False, indent=1)

    # quick distribution by comuna
    from collections import Counter
    c = Counter(e["city"] for e in new_leads)
    print("by comuna:")
    for k, v in c.most_common():
        print(f"  {v:3d}  {k}")


if __name__ == "__main__":
    main()
