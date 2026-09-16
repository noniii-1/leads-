# -*- coding: utf-8 -*-
"""
Merge verified_taller_shard*.jsonl + taller_instagram_results.jsonl into the
dashboard schema. No aplica ningun filtro nuevo -- eso ya paso en
scrape_taller.py; esto solo junta, dedupea y da forma al output.

Writes final_taller_dataset.json (list of lead dicts, dashboard schema).
"""
import json
import re
import glob

PHONE_RE = re.compile(r'^(9\s?\d{4}\s?\d{4}|\(2\)\s?\d{3,4}\s?\d{4}|600\s?\d{3}\s?\d{4}|\d{2}\s?\d{4}\s?\d{4})$')

# parse_utils.parse_article a veces desalinea el campo direccion cuando la
# tarjeta de Maps trae una linea de horario ("Abierto las 24 horas", un
# icono de reloj sin texto, etc) antes de la direccion real -- el resultado
# es un telefono, un icono suelto (caracteres del area privada de Unicode) o
# un numero de local que no es una direccion. No se puede recuperar la
# direccion real sin volver a visitar la ficha, asi que estos leads no
# cumplen el criterio 3 (local fijo verificado) y se descartan aca en vez
# de mandarlos con una direccion inservible.
VALID_ADDRESS_RE = re.compile(r'[A-Za-zÀ-ÿ]{3,}')


def has_valid_address(rec):
    addr = (rec.get("address") or "").strip()
    return bool(VALID_ADDRESS_RE.search(addr))


# El usuario prioriza negocios con nombre de marca personal/distintivo
# ("Spa Cars Duque", "Alex Motriz", "CLSS Detailing") por sobre nombres
# genericos/institucionales ("Taller Automotriz", "Servicio Automotriz
# Fulano Ltda.") -- estos ultimos suelen ser negocios mas formales/viejo
# estilo, mientras que un nombre de marca sugiere un dueño que ya piensa en
# su negocio como marca, mejor candidato para venderle una web.
# anclado al final: "SpA" (sociedad por acciones) choca con la palabra
# inglesa "spa" (como en "Spa Cars Duque") si no se ancla -- el sufijo legal
# chileno siempre va al final del nombre, la palabra de marca no
LEGAL_SUFFIX_RE = re.compile(
    r'(ltda\.?|limitada|spa|e\.?i\.?r\.?l\.?|y\s+cia\.?|y\s+compa[ñn][ií]a)\s*\.?\s*$',
    re.IGNORECASE,
)
GENERIC_NAME_TOKENS = {
    'taller', 'servicio', 'servicios', 'automotriz', 'automotor', 'automotora',
    'mecanica', 'mecánica', 'mecanico', 'mecánico', 'autos', 'auto', 'multimarca',
    'particular', 'de', 'del', 'y', 'la', 'el', 'los', 'las',
}
BRAND_WORDS = {
    'spa', 'cars', 'car', 'studio', 'shop', 'garage', 'motors', 'motor', 'detail',
    'detailing', 'wash', 'house', 'club', 'works', 'pro', 'plus', 'prime', 'shine',
    'elite', 'premium', 'lab', 'crew', 'squad', 'group', 'design', 'style', 'center',
}


def _name_words(name):
    n = LEGAL_SUFFIX_RE.sub('', name)
    return [w.lower() for w in re.findall(r"[A-Za-zÀ-ÿ']+", n)]


def is_generic_name(name):
    # "Y Cia Limitada", "E.I.R.L.", etc: registro formal tipo antiguo, no
    # es el estilo de marca personal que se busca priorizar
    if LEGAL_SUFFIX_RE.search(name):
        return True
    words = _name_words(name)
    if not words:
        return True
    non_generic = [w for w in words if w not in GENERIC_NAME_TOKENS]
    # generico tambien si el nombre entero son puras palabras del rubro
    # ("Taller Automotriz", "Servicio Automotriz") -- una sola palabra propia
    # ya puede ser la marca entera ("Kaizen Automotriz"), no se penaliza esa
    return len(non_generic) == 0


def brand_personality_bonus(name):
    if is_generic_name(name):
        return -15
    words = _name_words(name)
    if any(w in BRAND_WORDS for w in words):
        return 20
    return 8

RUBRO_LABELS = {
    "taller_mecanico": ("Taller mecánico",
        "Taller mecánico independiente de tamaño chico-mediano — el dueño suele ser "
        "también el mecánico y el que decide, buen candidato para ofrecerle una web "
        "con agenda de horas online y catálogo de servicios."),
    "detailing_automotriz": ("Car detailing",
        "Servicio de detailing/pulido automotriz independiente — negocio visual por "
        "naturaleza, buen candidato para una web con galería de trabajos y agenda online."),
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
    elif reviews >= 20:
        rb = 8
    else:
        rb = 4
    score += rb
    score += 20
    # tope en 88, no 100 -- deja margen para que el bonus/penalizacion de
    # nombre de marca (brand_personality_bonus) realmente mueva el orden en
    # vez de quedar absorbido por el techo cuando rating+resenas ya son altos
    return max(25, min(88, score))


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


def load_leads():
    leads = []
    seen = set()
    paths = sorted(glob.glob("verified_taller_shard*.jsonl")) + sorted(glob.glob("verified_detailing_shard*.jsonl"))
    for path in paths:
        with open(path, encoding="utf-8") as f:
            for line in f:
                rec = json.loads(line)
                key = rec["name"].strip().lower()
                if key in seen:
                    continue
                seen.add(key)
                leads.append(rec)
    return leads


def load_instagram_results():
    by_name = {}
    try:
        with open("taller_instagram_results.jsonl", encoding="utf-8") as f:
            for line in f:
                r = json.loads(line)
                by_name[r["name"].strip().lower()] = r
    except FileNotFoundError:
        pass
    return by_name


def load_photo_enrichment():
    by_name = {}
    try:
        with open("photo_enrichment.jsonl", encoding="utf-8") as f:
            for line in f:
                r = json.loads(line)
                by_name[r["name"].strip().lower()] = r["has_photos"]
    except FileNotFoundError:
        pass
    return by_name


def classify(marca_clara, has_photos, tiene_ig):
    """
    DESCARTAR: nombre generico + sin fotos + sin instagram (ningun indicio
    de marca detectable automaticamente).
    PRIORIZAR: nombre con identidad de marca Y tiene fotos propias cargadas
    (instagram es plus, no requisito).
    REVISAR: todo lo demas -- cumple algun indicio pero no todos. Tambien
    cae aca si el dato de fotos todavia no se enriquecio (has_photos=None):
    nunca se descarta ni prioriza por un dato que no se pudo verificar.

    Ojo: "fotos propias" aca es presencia/ausencia (se detecta con
    confianza), NO calidad ni si el rotulo se ve cuidado -- eso sigue
    siendo criterio manual (identidad_visual_revisada), igual que si hay
    una descripcion redactada (no se pudo automatizar de forma confiable).
    """
    if has_photos is None:
        return "revisar"
    if not marca_clara and not has_photos and not tiene_ig:
        return "descartar"
    if marca_clara and has_photos:
        return "priorizar"
    return "revisar"


def main():
    leads = load_leads()
    ig_by_name = load_instagram_results()
    photo_by_name = load_photo_enrichment()
    print("raw verified leads:", len(leads))

    no_addr = [r for r in leads if not has_valid_address(r)]
    leads = [r for r in leads if has_valid_address(r)]
    print("descartados por direccion no recuperable (bug de parseo, no cumplen criterio 3):", len(no_addr))
    print("leads con direccion valida:", len(leads))

    # piso de calidad: leads con <10 resenas son mayormente "talleres de
    # barrio" chicos/informales -- no el perfil que se quiere para la venta.
    # Se filtra aca (retroactivo, sin re-scrapear) porque el harvester
    # original de taller_mecanico corrio con MIN_REVIEWS=1; las corridas
    # nuevas ya piden 10+ desde el harvest.
    low_reviews = [r for r in leads if (r.get("reviews") or 0) < 10]
    leads = [r for r in leads if (r.get("reviews") or 0) >= 10]
    print("descartados por <10 resenas (\"talleres de barrio\"):", len(low_reviews))
    print("leads con 10+ resenas:", len(leads))

    entries = []
    for i, rec in enumerate(leads, start=1):
        name = rec["name"].strip()
        phone = (rec.get("phone") or "").strip()
        if phone and not PHONE_RE.match(phone):
            phone = ""
        city = rec.get("city", "Santiago")
        rubro = rec.get("rubro", "taller_mecanico")
        cat_label, business_type = RUBRO_LABELS.get(rubro, RUBRO_LABELS["taller_mecanico"])
        cat_tag = rec.get("category") or cat_label
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

        ig = ig_by_name.get(name.lower(), {})
        instagram_handle = rec.get("instagram_handle") or ig.get("instagram_handle")
        instagram_status = ig.get("instagram_status", "no_verificado_pendiente")

        has_photos = rec.get("has_photos")
        if has_photos is None:
            has_photos = photo_by_name.get(name.lower())
        marca_clara = not is_generic_name(name)
        clasificacion = classify(marca_clara, has_photos, bool(instagram_handle))
        if clasificacion == "descartar":
            continue

        if instagram_handle:
            web_note = "No tiene sitio web propio — el único link en Maps es Instagram/Facebook."
        else:
            web_note = "No tiene sitio web propio (verificado en Maps)."

        entry = {
            "cid": f"gm_taller_{i}_{slugify(name)}",
            "name": name,
            "phone": phone or None,
            "phone_e164": phone_e164(phone),
            "website": None,
            "has_website": False,
            "web_tier": "sin_web",
            "web_tier_label": "Sin sitio web",
            "web_note": web_note,
            "city": city,
            "rating": rating,
            "reviews_count": reviews,
            "category_tag": cat_tag,
            "category_group": rubro,
            "category_label": cat_label,
            "address": addr,
            "maps_url": maps_url,
            "score": max(1, min(100, score_for(rating, reviews) + brand_personality_bonus(name))),
            "nombre_marca_personal": marca_clara,
            "has_photos": has_photos,
            "clasificacion": clasificacion,
            "chain_flag": False,
            "summary": summary,
            "business_type": business_type,
            "local_fijo": True,
            "antiguedad_dias_min": rec.get("antiguedad_dias_min"),
            "antiguedad_status": rec.get("antiguedad_status", "no_verificada_revisar"),
            "instagram_handle": instagram_handle,
            "instagram_source": rec.get("instagram_source") or ig.get("instagram_source"),
            "instagram_status": instagram_status,
            "instagram_last_post_days": ig.get("instagram_last_post_days"),
            "identidad_visual_revisada": False,
            "is_new_batch": True,
            "source_query": rec.get("source_query", ""),
        }
        entries.append(entry)

    descartados = len(leads) - len(entries)
    print("descartados por clasificacion (nombre generico + sin fotos + sin instagram):", descartados)

    CLASIF_ORDER = {"priorizar": 0, "revisar": 1}
    entries.sort(key=lambda e: (CLASIF_ORDER.get(e["clasificacion"], 1), -e["score"]))

    from collections import Counter
    print("por clasificacion:", Counter(e["clasificacion"] for e in entries).most_common())
    print("FINAL taller dataset total:", len(entries))
    with open("final_taller_dataset.json", "w", encoding="utf-8") as f:
        json.dump(entries, f, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
