# -*- coding: utf-8 -*-
"""
Build the final dental-clinic dataset:
- From the 89 originally-kept clinics: keep only the ones whose most recent
  review is <=183 days old (per recency_results.jsonl) and no website leak.
- From the "new" pool (main pipeline's new_dental_leads.json + the fast
  pipeline's verified_leads_shard0.jsonl): keep the ones that pass all
  criteria, deduped by name.
Writes final_dental_dataset.json (list of lead dicts in the dashboard schema).
"""
import json
import re

RECENCY_MAX_DAYS = 183


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


PHONE_RE = re.compile(r'^(9\s?\d{4}\s?\d{4}|\(2\)\s?\d{3,4}\s?\d{4}|600\s?\d{3}\s?\d{4}|\d{2}\s?\d{4}\s?\d{4})$')


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
    score += 20
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
    # ---- recency lookup ----
    recency_by_name = {}
    with open("recency_results.jsonl", encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            recency_by_name[r["name"].strip().lower()] = r

    def passes_recency(name):
        r = recency_by_name.get(name.strip().lower())
        if not r:
            return False
        if r["most_recent_review_days"] is None:
            return False
        if r["most_recent_review_days"] > RECENCY_MAX_DAYS:
            return False
        if r.get("has_website_detail"):
            return False
        return True

    # ---- 1) existing 89, filtered ----
    with open("dental_keep_step1.json", encoding="utf-8") as f:
        existing89 = json.load(f)
    existing_final = [e for e in existing89 if passes_recency(e["name"])]
    print("existing 89 -> passing recency:", len(existing_final))

    # ---- 2) new leads from main pipeline, filtered ----
    with open("new_dental_leads.json", encoding="utf-8") as f:
        new_main = json.load(f)
    new_main_final = [e for e in new_main if passes_recency(e["name"])]
    print("new (main pipeline) -> passing recency:", len(new_main_final))

    # ---- 3) new leads from fast pipeline (already recency-verified inline) ----
    fast_leads = []
    for path in ("verified_leads_shard0.jsonl", "verified_leads_shard2.jsonl"):
        try:
            with open(path, encoding="utf-8") as f:
                for line in f:
                    fast_leads.append(json.loads(line))
        except FileNotFoundError:
            pass
    print("new (fast pipeline):", len(fast_leads))

    # dedupe fast_leads against new_main_final and existing_final by name
    known_names = {e["name"].strip().lower() for e in existing_final} | {e["name"].strip().lower() for e in new_main_final}
    fast_leads = [e for e in fast_leads if e["name"].strip().lower() not in known_names]
    print("new (fast pipeline) -> unique after dedup:", len(fast_leads))

    # convert fast_leads (raw parse_article schema) into the dashboard schema
    idx_start = len(existing89) + len(new_main) + 1
    fast_final = []
    for i, rec in enumerate(fast_leads):
        name = rec["name"].strip()
        phone = (rec.get("phone") or "").strip()
        if phone and not PHONE_RE.match(phone):
            phone = ""
        city = rec.get("city", "Santiago")
        cat_tag = rec.get("category") or "Clínica dental"
        rating = rec.get("rating")
        reviews = rec.get("reviews", 0)
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
            "cid": f"gm5_{idx_start + i}_{slugify(name)}",
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
        fast_final.append(entry)

    all_new = new_main_final + fast_final
    combined = existing_final + all_new

    print()
    print("FINAL existing (recency-passing):", len(existing_final))
    print("FINAL new total:", len(all_new))
    print("FINAL combined total:", len(combined))

    with open("final_dental_dataset.json", "w", encoding="utf-8") as f:
        json.dump(combined, f, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
