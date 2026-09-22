# -*- coding: utf-8 -*-
"""
Convierte verified_pure_detailing_shard*.jsonl (las 3 tandas de scraping de
detailing puro) al esquema del dashboard y los mete en
leads_santiago_dashboard.html, sin duplicar los que ya estan ahi.

Reusa el mismo filtro que build_pure_final2.py (lista blanca de categorias
de Maps, sin choque/pintura, sin patron de nombre de barrio, con contenido
distintivo real) para que lo que entra al dashboard sea consistente con lo
que ya se le mando al usuario en los CSV.

Usage: python finalize_pure_detailing.py
"""
import json
import re
import glob
import hashlib
import unicodedata

HTML_PATH = "leads_santiago_dashboard.html"


def norm(s):
    s = unicodedata.normalize('NFKD', s or '')
    return ''.join(c for c in s if not unicodedata.combining(c)).lower()


ALLOWED_CATEGORIES = {norm(c) for c in [
    'Servicio de lavado de coches', 'Servicio de limpieza de automóviles',
    'Autoservicio de lavado de autos', 'Servicio de detallado de automóviles',
    'Servicio de encerado de automóviles', 'Servicio de lavado a presión',
]}
AMBIGUOUS_CATEGORIES = {norm(c) for c in [
    'Taller de reparación de automóviles', 'Taller de chapa y pintura',
    'Taller mecánico', 'Taller de revisión de automóviles', 'Fábrica',
    'Tienda de automovilismo', 'Pintura de automóviles', 'Taller de automóviles',
    'Servicio de restauración de automóviles', 'Tapicería para automóviles',
]}
STRONG_SIGNAL = [norm(s) for s in [
    'detailing', 'detallado', 'pulido', 'pulida', 'encerado',
    'sellado ceramico', 'estetica automotriz', 'car wash', 'carwash',
    'auto spa', 'car spa', 'spa automotriz', 'spa de auto', 'spa del automovil',
    'autospa', 'carspa', 'ceramic coating', 'brillado',
]]
GENERIC_FILLER_TOKENS = {norm(s) for s in [
    'taller', 'servicio', 'servicios', 'automotriz', 'automotor', 'autos', 'auto',
    'de', 'del', 'y', 'la', 'el', 'los', 'las', 'lavado', 'lavados', 'detailing',
    'detallado', 'estetica', 'car', 'wash', 'carwash', 'spa', 'limpieza', 'pulido',
    'pulida', 'encerado', 'brillado', 'sellado', 'ceramico', 'ceramica', 'premium',
    'express', 'central', 'economico', 'economica', 'rapido', 'rapida', 'lujo',
    'basico', 'basica', 'multimarca', 'particular', 'domicilio', 'en', 'a', 'un',
    'una', 'con', 'para', 'sin', 'autolavado', 'lavadero', 'centro',
]}
COMUNAS_ALL = [
    "Santiago Centro", "Providencia", "Las Condes", "Vitacura", "Lo Barnechea",
    "La Reina", "Ñuñoa", "Macul", "Peñalolén", "La Florida",
    "San Joaquín", "La Granja", "La Pintana", "San Ramón", "El Bosque",
    "La Cisterna", "San Miguel", "Pedro Aguirre Cerda", "Lo Espejo", "Estación Central",
    "Cerrillos", "Maipú", "Cerro Navia", "Pudahuel", "Lo Prado",
    "Quinta Normal", "Renca", "Quilicura", "Huechuraba", "Conchalí",
    "Independencia", "Recoleta", "Puente Alto", "San Bernardo",
    "Colina", "Lampa", "Buin", "Paine", "Melipilla", "Peñaflor",
    "Talagante", "Padre Hurtado", "Calera de Tango",
    "Isla de Maipo", "El Monte", "San José de Maipo", "Pirque", "Curacaví",
]
COMUNA_TOKENS = {norm(w) for c in COMUNAS_ALL for w in c.split()}
EXTRA_BLOCK_SUBSTR = ['desabolladur', 'chapa', 'pintura al horno', 'carrozzier',
                      'lubricentro', 'caneria', 'inmovilizador', 'neumatic',
                      'frenos', 'suspension', 'alineacion', 'balanceo',
                      'mecanica general', 'radiador', 'escape', 'repuestos',
                      'gps', 'vulcaniza', 'polarizado', 'lavaseco y lavanderia',
                      'estacionamiento', 'lavamoto', 'lavanderia', 'clinica',
                      'audio', 'cerrajeria', 'barber', 'copec', 'shell ',
                      'petrobras', 'terpel']
BARRIO_RE = re.compile(
    r"^(taller|servicio|lavado(s)?( de)?( autos?| auto| automotriz| vehiculos?)?|lavadero( de autos)?|autolavado)"
    r"\s+(el |la |don |dona |doña )?[a-z]{3,12}$"
)
MANUAL_REJECT = {norm(n) for n in [
    'La Dehesa Limitada', 'Mecanica preventiva, general', 'CAMBIO DE DUEÑO',
    'Víctor Gutiérrez Valenzuela "Cano"', 'Taller Innovaciones', 'Comercial C&I',
    'Bass Audio Chile', 'Lavamoto Chile',
    'Juan Diego Cabrera Palacios Ventas Y Servicios Automotrices E.I.R.L',
    'Rapido y Brilloso', 'Lavado de Autos Cecilia', 'Lavado de autos El Robert',
    'Lavados de Autos Cristián', 'Centro Link', 'Fresh Market',
    'Servicio De Mantencion Y Lavado De Vehiculos Motor', 'Focos',
]}
MANUAL_KEEP = {norm(n) for n in ['KombiSpa']}


def has_distinctive_content(name):
    words = re.findall(r"[a-z0-9']+", norm(name))
    remaining = [w for w in words if w not in GENERIC_FILLER_TOKENS and w not in COMUNA_TOKENS]
    return len(remaining) > 0


def passes_filter(rec):
    name_n = norm(rec['name'])
    cat_n = norm(rec.get('category') or '')
    if name_n in MANUAL_REJECT:
        return False
    if name_n in MANUAL_KEEP:
        return True
    if any(b in name_n for b in EXTRA_BLOCK_SUBSTR):
        return False
    if cat_n in AMBIGUOUS_CATEGORIES:
        if not any(s in name_n for s in STRONG_SIGNAL):
            return False
    elif cat_n not in ALLOWED_CATEGORIES:
        return False
    if not has_distinctive_content(rec['name']):
        return False
    if BARRIO_RE.match(name_n.strip()):
        return False
    return True


# --- esquema del dashboard (igual a finalize_taller_dataset.py, que ya no existe) ---
def slugify(s):
    s = s.lower()
    s = re.sub(r"[^a-z0-9]+", "_", s)
    return s.strip("_")[:40]


def stable_cid(name, address):
    h = hashlib.md5(f"{name.strip().lower()}|{(address or '').strip().lower()}".encode("utf-8")).hexdigest()[:10]
    return f"gm_detailing_{h}_{slugify(name)}"


PHONE_RE = re.compile(r'^(9\s?\d{4}\s?\d{4}|\(2\)\s?\d{3,4}\s?\d{4}|600\s?\d{3}\s?\d{4}|\d{2}\s?\d{4}\s?\d{4})$')


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
    score += rb + 20
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


def main():
    seen = {}
    for f in sorted(glob.glob('verified_pure_detailing_shard*.jsonl')):
        for line in open(f, encoding='utf-8'):
            line = line.strip()
            if not line:
                continue
            d = json.loads(line)
            key = d['name'].strip().lower()
            if key not in seen:
                seen[key] = d
            else:
                cur = seen[key]
                for k, v in d.items():
                    if not cur.get(k) and v:
                        cur[k] = v

    with open(HTML_PATH, encoding="utf-8") as f:
        content = f.read()
    m = re.search(r'(<script id="leads-data"[^>]*>)(.*?)(</script>)', content, re.S)
    assert m, "leads-data script tag not found"
    existing = json.loads(m.group(2))
    existing_names = {e['name'].strip().lower() for e in existing}

    entries = []
    for rec in seen.values():
        name = rec['name'].strip()
        if name.lower() in existing_names:
            continue
        if not passes_filter(rec):
            continue
        phone = (rec.get('phone') or '').strip()
        if phone and not PHONE_RE.match(phone):
            phone = ''
        city = rec.get('city', 'Santiago')
        rating = rec.get('rating')
        reviews = rec.get('reviews', 0)
        cat_tag = rec.get('category') or 'Car detailing'
        rep = reputation_label(rating)
        if rating and reviews:
            satisfied = ", clientes consistentemente satisfechos" if rating >= 4.5 else ""
            summary = f"{cat_tag} en {city}. {rep}: {rating} en {reviews} reseñas{satisfied}."
        else:
            summary = f"{cat_tag} en {city}."
        addr = rec.get('address') or city
        maps_query = f"{name} {addr}".replace("&", "%26").replace("#", "%23")
        maps_url = "https://www.google.com/maps/search/?api=1&query=" + maps_query.replace(" ", "+")
        instagram_handle = rec.get('instagram_handle')
        has_photos = rec.get('has_photos')

        entry = {
            "cid": stable_cid(name, addr),
            "name": name,
            "phone": phone or None,
            "phone_e164": phone_e164(phone),
            "website": None,
            "has_website": False,
            "web_tier": "sin_web",
            "web_tier_label": "Sin sitio web",
            "web_note": "No tiene sitio web propio — el único link en Maps es Instagram/Facebook." if instagram_handle else "No tiene sitio web propio (verificado en Maps).",
            "city": city,
            "rating": rating,
            "reviews_count": reviews,
            "category_tag": cat_tag,
            "category_group": "detailing_automotriz",
            "category_label": "Car detailing",
            "address": addr,
            "maps_url": maps_url,
            "score": max(1, min(100, score_for(rating, reviews))),
            "nombre_marca_personal": True,
            "has_photos": has_photos,
            "clasificacion": "priorizar" if has_photos else "revisar",
            "chain_flag": False,
            "summary": summary,
            "business_type": "Servicio de detailing/pulido automotriz independiente — negocio visual por naturaleza, buen candidato para una web con galería de trabajos y agenda online.",
            "local_fijo": True,
            "antiguedad_dias_min": rec.get("antiguedad_dias_min"),
            "antiguedad_status": rec.get("antiguedad_status", "no_verificada_revisar"),
            "instagram_handle": instagram_handle,
            "instagram_source": rec.get("instagram_source"),
            "instagram_status": "no_verificado_pendiente",
            "instagram_last_post_days": None,
            "identidad_visual_revisada": False,
            "is_new_batch": True,
            "source_query": rec.get("source_query", ""),
        }
        entries.append(entry)
        existing_names.add(name.lower())

    print("existentes en dashboard:", len(existing))
    print("nuevos detailing agregados:", len(entries))
    combined = existing + entries
    print("total combinado:", len(combined))

    new_json = json.dumps(combined, ensure_ascii=False, separators=(",", ":"))
    new_content = content[:m.start(2)] + new_json + content[m.end(2):]
    with open(HTML_PATH, "w", encoding="utf-8") as f:
        f.write(new_content)
    print("dashboard actualizado OK")


if __name__ == "__main__":
    main()
