# -*- coding: utf-8 -*-
"""
Segunda corrida de detailing, mas angosta que scrape_taller.py: el usuario
detecto que la corrida anterior mezclaba negocios de choque/pintura
(desabolladura, pintura al horno, chapa) y el patron de taller de barrio
("Taller Miguel", "Juan Rojas Servicio Automotriz") dentro del rubro
"detailing_automotriz" -- esos NO son detailing puro y no tienen identidad
de marca aunque tengan un nombre propio.

Cambios respecto a scrape_taller.py (modo detailing):
  - keywords de busqueda: se saca "pulido de pintura automotriz" (atrae
    talleres de choque por la palabra "pintura") y variantes ambiguas;
    se agregan mas variantes de lavado/spa/ceramico puro.
  - filtro a nivel de tarjeta (antes de abrir la ficha, ahorra tiempo):
      * bloquea por substring si el nombre menciona choque/pintura al
        horno/carrozziere/lubricentro/caneria/gps/neumaticos/frenos/etc.
      * exige que el nombre tenga una palabra de senal de detailing
        (detailing, lavado, pulido, encerado, sellado, brillado, spa,
        ceramico, carwash...) O que la categoria de Maps sea explicitamente
        de lavado/detailing (no "taller de reparacion", no "chapa y
        pintura", no "taller mecanico").
      * exige contenido distintivo: si despues de sacar las palabras de
        rubro/relleno (lavado, de, autos, taller, servicio, premium,
        express, central...) y los nombres de comuna no queda ninguna
        palabra propia, se descarta -- este es el filtro que saca
        "Lavado de Autos Macul" aunque tenga la palabra "lavado".
  - resto del pipeline (sin sitio web real, local fijo, antiguedad
    6 meses-3 anios, no cadena/concesionario) igual a scrape_taller.py.

Usage: python scrape_pure_detailing.py <shard_index> <shard_count>
Writes verified_pure_detailing_shard<N>.jsonl (resumable, dedup por nombre,
tambien contra todo lo ya visto en verified_taller_shard*.jsonl y
verified_detailing_shard*.jsonl para no reprocesar negocios ya evaluados).
"""
import os
import re
import sys
import io
import time
import json
import glob
import threading
import unicodedata
from scrapling.fetchers import StealthySession
from parse_utils import parse_article

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

MIN_REVIEWS = 1
MAX_REVIEWS_FOR_AGE_CHECK = 200
MIN_AGE_DAYS = 183
MAX_AGE_DAYS = 1095
WATCHDOG_SECS = 100

SHARD_INDEX = int(sys.argv[1]) if len(sys.argv) > 1 else 0
SHARD_COUNT = int(sys.argv[2]) if len(sys.argv) > 2 else 1
OUT_PATH = f"verified_pure_detailing_shard{SHARD_INDEX}.jsonl"

COMUNAS = [
    "Santiago Centro", "Providencia", "Las Condes", "Vitacura", "Lo Barnechea",
    "La Reina", "Ñuñoa", "Macul", "Peñalolén", "La Florida",
    "San Joaquín", "La Granja", "La Pintana", "San Ramón", "El Bosque",
    "La Cisterna", "San Miguel", "Pedro Aguirre Cerda", "Lo Espejo", "Estación Central",
    "Cerrillos", "Maipú", "Cerro Navia", "Pudahuel", "Lo Prado",
    "Quinta Normal", "Renca", "Quilicura", "Huechuraba", "Conchalí",
    "Independencia", "Recoleta", "Puente Alto", "San Bernardo",
    # comunas satelite de la RM no tocadas en las corridas anteriores --
    # el resto de la lista ya se scrapeo a fondo con estas mismas keywords,
    # asi que Maps devuelve el mismo top-40 ya conocido y el dedup lo come
    # todo; aca hay superficie nueva de verdad.
    "Colina", "Lampa", "Buin", "Paine", "Melipilla", "Peñaflor",
    "Talagante", "Padre Hurtado", "Calera de Tango",
    # tanda 3: mas comunas satelite de la RM sin tocar todavia
    "Isla de Maipo", "El Monte", "San José de Maipo", "Pirque", "Curacaví",
]

DETAILING_KEYWORDS = [
    # tanda 3 (tandas 1 y 2 ya agotadas por dedup): frases nuevas para que
    # Maps devuelva otro top-40 en las comunas ya cubiertas
    "detailer de autos", "auto detailer", "detailing profesional automotriz",
    "wrapping y detailing automotriz", "ppf autos", "vinilo y detailing automotriz",
    "lavado y encerado a domicilio", "detailing movil automotriz",
    "limpieza ceramica de autos", "auto shine", "car care center",
    "detailing boutique automotriz",
]


def build_queries():
    queries = []
    for comuna in COMUNAS:
        for kw in DETAILING_KEYWORDS:
            queries.append((f"{kw} {comuna} Santiago Chile", comuna))
    return [q for i, q in enumerate(queries) if i % SHARD_COUNT == SHARD_INDEX]


def _norm(s):
    s = unicodedata.normalize('NFKD', s or '')
    return ''.join(c for c in s if not unicodedata.combining(c)).lower()


# --- filtro de "detailing puro + nombre con identidad" a nivel de tarjeta ---
# Incluye las reglas que hubo que agregar a mano en la revision de la tanda 1
# (categorias de otro rubro, talleres con senal debil, frases de relleno).
BLOCK_NAME_SUBSTR = [_norm(s) for s in [
    'desabolladur', 'chapa', 'pintura al horno', 'carrozzier',
    'lubricentro', 'caneria', 'inmovilizador', ' gps ', 'gps', 'neumatic',
    'frenos', 'suspension', 'alineacion', 'balanceo', 'repuestos',
    'mecanica general', 'remolque', 'grua ', 'radiador', 'escape',
    'vulcaniza', 'polarizado', 'estacionamiento', 'lavaseco y lavanderia',
    'lavamoto', 'lavanderia', 'clinica', 'audio',
]]
# OJO: 'spa' NO va suelta aca -- choca con el sufijo legal chileno "SpA"
# (Sociedad por Accciones) que aparece en el nombre de empresas de CUALQUIER
# rubro. Solo cuenta como senal si viene pegada a auto/car (ver mas abajo).
DETAILING_SIGNAL_WORDS_NAME = [_norm(s) for s in [
    'detailing', 'detallado', 'estetica', 'wash', 'lavado', 'pulido',
    'pulida', 'encerado', 'sellado', 'brillado', 'carwash', 'ceramico',
    'ceramica', 'lavamovil', 'shine', 'polish', 'clean', 'car care',
    'auto spa', 'car spa', 'spa automotriz', 'spa de auto', 'autospa', 'carspa',
]]
ALLOWED_CATEGORY_SIGNALS = {_norm(s) for s in [
    'Servicio de limpieza de automóviles', 'Servicio de lavado de coches',
    'Autoservicio de lavado de autos', 'Servicio de detallado de automóviles',
    'Servicio de detallado de embarcaciones', 'Servicio de encerado de automóviles',
    'Servicio de lavado a presión',
]}
# categorias de Maps de otro rubro: se descartan siempre
HARD_BLOCK_CATEGORIES = {_norm(c) for c in [
    'Clínica especializada', 'Esteticista', 'Centro de estética',
    'Servicio de autos compartidos', 'Aparcamiento de coches compartidos',
    'Lavandería', 'Servicio de polarizado de autos', 'Mercado de automóviles',
]}
# categorias ambiguas (taller/tienda mal etiquetado): solo pasan si el nombre
# trae una senal fuerte de detailing
AMBIGUOUS_CATEGORIES = {_norm(c) for c in [
    'Taller de reparación de automóviles', 'Taller de chapa y pintura',
    'Taller mecánico', 'Taller de revisión de automóviles', 'Fábrica',
    'Tienda de automovilismo', 'Pintura de automóviles',
]}
STRONG_SIGNAL = [_norm(s) for s in [
    'detailing', 'detallado', 'pulido', 'pulida', 'encerado',
    'sellado ceramico', 'estetica automotriz', 'car wash', 'carwash',
]]
GENERIC_FILLER_TOKENS = {_norm(s) for s in [
    'taller', 'servicio', 'servicios', 'automotriz', 'automotor', 'autos', 'auto',
    'de', 'del', 'y', 'la', 'el', 'los', 'las', 'lavado', 'lavados', 'detailing',
    'detallado', 'estetica', 'car', 'wash', 'carwash', 'spa', 'limpieza', 'pulido',
    'pulida', 'encerado', 'brillado', 'sellado', 'ceramico', 'ceramica', 'premium',
    'express', 'central', 'economico', 'economica', 'rapido', 'rapida', 'lujo',
    'basico', 'basica', 'multimarca', 'particular', 'domicilio', 'en', 'a', 'un',
    'una', 'con', 'para', 'sin', 'autolavado', 'lavadero', 'centro',
]}
COMUNA_TOKENS = {_norm(w) for c in COMUNAS for w in c.split()}
# nombre propio pelado con servicio generico ("Lavado de Autos Cecilia",
# "Taller Miguel"): patron de barrio que el usuario pidio evitar
BARRIO_RE = re.compile(
    r"^(taller|servicio|lavado(s)?( de)?( autos?| auto| automotriz| vehiculos?)?|lavadero( de autos)?|autolavado)"
    r"\s+(el |la |don |dona |doña )?[a-z]{3,12}$"
)


def _name_words(name):
    return [w for w in re.findall(r"[A-Za-zÀ-ÿ0-9']+", _norm(name))]


def has_distinctive_content(name):
    words = _name_words(name)
    remaining = [w for w in words if w not in GENERIC_FILLER_TOKENS and w not in COMUNA_TOKENS]
    return len(remaining) > 0


def is_pure_detailing_brand(rec):
    name_n = _norm(rec["name"])
    if any(b in name_n for b in BLOCK_NAME_SUBSTR):
        return False
    cat_n = _norm(rec.get("category") or "")
    if cat_n in HARD_BLOCK_CATEGORIES:
        return False
    if cat_n in AMBIGUOUS_CATEGORIES and not any(sg in name_n for sg in STRONG_SIGNAL):
        return False
    has_name_signal = any(sg in name_n for sg in DETAILING_SIGNAL_WORDS_NAME)
    has_cat_signal = cat_n in ALLOWED_CATEGORY_SIGNALS
    if not (has_name_signal or has_cat_signal):
        return False
    if not has_distinctive_content(rec["name"]):
        return False
    if BARRIO_RE.match(name_n.strip()):
        return False
    return True


# --- resto del pipeline (sin sitio web real, local fijo, antiguedad, no cadena) ---
DEALER_WORDS = ['concesionario', 'distribuidor oficial', 'servicio oficial', 'agencia oficial', 'sucursal']
BRANDS = [
    'toyota', 'chevrolet', 'nissan', 'hyundai', ' kia ', 'kia motors', 'suzuki',
    'mazda', 'ford', 'peugeot', 'citroen', 'renault', 'volkswagen',
    ' vw ', 'mitsubishi', 'subaru', 'great wall', 'jac motors', 'chery',
    'mg motor', 'byd', 'ram trucks', 'ssangyong', 'ds automobiles', 'honda',
    'jeep', 'fiat', 'isuzu', 'foton', 'dfsk', 'baic',
]
CHAIN_NAMES = ['midas', 'feuerhand', 'full motor', 'kovacs', 'derco', 'salfa',
               'gildemeister', 'autoplaza', 'indumotora']
EXCLUDE_KEYWORDS = [_norm(k) for k in DEALER_WORDS + BRANDS + CHAIN_NAMES]

SERVICE_AREA_RE = re.compile(r'[áa]rea de servicio|sin ubicaci[óo]n f[íi]sica|servicio a domicilio', re.IGNORECASE)
ZOOM_RE = re.compile(r'@-?\d+\.\d+,-?\d+\.\d+,(\d+(?:\.\d+)?)z')
MIN_ZOOM = 14


def is_imprecise_location(href):
    if not href:
        return False
    m = ZOOM_RE.search(href)
    if not m:
        return False
    return float(m.group(1)) < MIN_ZOOM


def is_chain_or_dealer(rec):
    hay = _norm(f" {rec['name']} {rec.get('category') or ''} ")
    return any(k in hay for k in EXCLUDE_KEYWORDS)


def is_service_area(rec):
    addr = (rec.get("address") or "").strip()
    if not addr:
        return True
    return bool(SERVICE_AREA_RE.search(addr))


DATE_RE = re.compile(
    r'Hace\s+(un|una|\d+)\s+(d[ií]a|d[ií]as|semana|semanas|mes|meses|a[ñn]o|a[ñn]os)',
    re.IGNORECASE
)
SOCIAL_DOMAINS = ('instagram.com', 'facebook.com', 'fb.com', 'fb.watch',
                   'whatsapp.com', 'wa.me', 'linktr.ee', 'goo.gl', 'g.page')
IG_HANDLE_RE = re.compile(r'instagram\.com/([A-Za-z0-9_.]+)', re.IGNORECASE)
FB_HANDLE_RE = re.compile(r'facebook\.com/([A-Za-z0-9_.]+)', re.IGNORECASE)

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
            print(f"[pure-{SHARD_INDEX}] WATCHDOG: no progress for {stale:.0f}s, force-exiting", flush=True)
            os._exit(1)


def _days_for_match(n_raw, unit_raw):
    n = 1 if n_raw.lower() in ('un', 'una') else int(n_raw)
    unit_key = unit_raw.lower().replace('í', 'i').replace('ñ', 'n')
    unit_key = {
        'dia': 'dia', 'dias': 'dia',
        'semana': 'semana', 'semanas': 'semana',
        'mes': 'mes', 'meses': 'mes',
        'ano': 'ano', 'anos': 'ano',
    }.get(unit_key, unit_key)
    base = {'dia': 1, 'semana': 7, 'mes': 30, 'ano': 365}.get(unit_key)
    return n * base if base else None


def parse_review_days(text):
    days = []
    for m in DATE_RE.finditer(text):
        d = _days_for_match(m.group(1), m.group(2))
        if d is not None:
            days.append(d)
    if not days:
        return None, None
    return min(days), max(days)


def extract_social_handle(page, text):
    href = None
    try:
        els = page.css('a[data-item-id="authority"]')
        if els:
            href = els[0].attrib.get('href')
    except Exception:
        pass
    haystack = f"{href or ''} {text}"
    m = IG_HANDLE_RE.search(haystack)
    if m:
        return href, "instagram", m.group(1)
    m = FB_HANDLE_RE.search(haystack)
    if m:
        return href, "facebook", m.group(1)
    return href, None, None


def has_real_website(href, text):
    if not href:
        return False
    domain = href.lower()
    if any(sd in domain for sd in SOCIAL_DOMAINS) or 'google.' in domain:
        return False
    return True


def do_search(query):
    def _action(page):
        page.wait_for_timeout(800)
        box = page.locator('input[name="q"]')
        box.click()
        box.fill(query)
        box.press("Enter")
        try:
            page.wait_for_selector('div[role="feed"] > div', timeout=8000)
        except Exception:
            page.wait_for_timeout(2000)
        feed = page.locator('div[role="feed"]')
        try:
            # 5 scrolls (el valor original de scrape_taller.py) se quedaba en
            # el top-40 de siempre -- son justo los negocios grandes/con mas
            # resenas que ya estaban capturados de corridas anteriores. Mas
            # scroll llega a negocios chicos/nuevos mas abajo en el ranking.
            for _ in range(16):
                feed.evaluate("el => el.scrollTop = el.scrollHeight")
                page.wait_for_timeout(600)
        except Exception:
            pass
        return page
    return _action


def do_open_detail(url):
    def _action(page):
        page.wait_for_timeout(3500)
        try:
            pane = page.locator('div[role="main"]')
            for _ in range(6):
                pane.evaluate("el => el.scrollBy(0, 800)")
                page.wait_for_timeout(500)
        except Exception:
            pass
        return page
    return _action


def check_detail(session, href):
    try:
        page = session.fetch(href, page_action=do_open_detail(href), timeout=30000, network_idle=False)
        txt = page.get_all_text()
        link_href, social_kind, social_handle = extract_social_handle(page, txt)
        real_site = has_real_website(link_href, txt)
        service_area = bool(SERVICE_AREA_RE.search(txt)) if not link_href else False
        min_days, max_days = parse_review_days(txt)
        has_photos = "Ver fotos" in txt
        return {
            "ok": True,
            "has_real_website": real_site,
            "is_service_area_detail": service_area,
            "social_kind": social_kind,
            "social_handle": social_handle,
            "min_review_days": min_days,
            "max_review_days": max_days,
            "has_photos": has_photos,
        }
    except Exception as e:
        print(f"[pure-{SHARD_INDEX}]   detail-check ERROR: {e}", flush=True)
        return {"ok": False}


def load_seen():
    seen = set()
    paths = [OUT_PATH] + glob.glob("verified_taller_shard*.jsonl") + \
        glob.glob("verified_detailing_shard*.jsonl") + glob.glob("verified_pure_detailing_shard*.jsonl")
    for path in set(paths):
        try:
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    seen.add(json.loads(line)["name"].strip().lower())
        except FileNotFoundError:
            pass
    return seen


# --- progreso por query, persistido en disco -------------------------------
# El bug de '%2f' hacia que TODO se rechazara, asi que nunca se veia, pero
# ademas la sesion de scrapling se cuelga sola cada ~10-15 fetches seguidos
# (visto en vivo). Con el diseno anterior, cada vez que el proceso se
# reinicia (el wrapper bash lo relanza), build_queries() vuelve a dar la
# MISMA lista desde el principio -- el shard se queda pegado reprocesando
# la query 1 por 40 intentos y nunca llega a la query 2. Esto guarda que
# queries ya se terminaron de procesar (todos sus candidatos revisados) en
# un archivo por shard, y al arrancar se saltan -- asi un reinicio avanza
# en vez de repetir.
PROGRESS_PATH = f"pure_detailing_progress_shard{SHARD_INDEX}.txt"


def load_done_queries():
    try:
        with open(PROGRESS_PATH, "r", encoding="utf-8") as f:
            return {line.rstrip("\n") for line in f}
    except FileNotFoundError:
        return set()


def mark_query_done(query):
    with open(PROGRESS_PATH, "a", encoding="utf-8") as f:
        f.write(query + "\n")


def run_batch(queries, session, done_queries):
    seen_names = load_seen()
    verified_count = 0
    for i, (query, comuna) in enumerate(queries, start=1):
        if query in done_queries:
            continue
        url = "https://www.google.com/maps"
        try:
            page = session.fetch(url, page_action=do_search(query), timeout=30000, network_idle=False)
            articles = page.css('div.Nv2PK')
            new_this_query = 0
            for a in articles:
                _touch()
                try:
                    rec = parse_article(a.get_all_text())
                except Exception:
                    rec = None
                if not rec:
                    continue
                key = rec["name"].strip().lower()
                if key in seen_names:
                    continue
                if rec["reviews"] < MIN_REVIEWS or rec["reviews"] > MAX_REVIEWS_FOR_AGE_CHECK:
                    continue
                if rec.get("rating") is not None and rec["rating"] < 3.0:
                    continue
                if not is_pure_detailing_brand(rec):
                    continue
                if is_chain_or_dealer(rec):
                    continue
                if is_service_area(rec):
                    continue
                link_els = a.css('a.hfpxzc')
                href = link_els[0].attrib.get('href') if link_els else None
                if not href:
                    continue
                if is_imprecise_location(href):
                    seen_names.add(key)
                    continue
                if '/' in rec["name"]:
                    # OJO: ya no se chequea '%2f' en el href -- Maps ahora
                    # mete un segmento interno "16s%2Fg%2F..." (knowledge
                    # graph id) en TODA ficha, tenga o no "/" el nombre, asi
                    # que esa condicion rechazaba el 100% de los candidatos
                    # (bug encontrado en vivo: 340 queries, 0 verificados).
                    seen_names.add(key)
                    continue
                seen_names.add(key)

                detail = check_detail(session, href)
                _touch()
                if not detail["ok"]:
                    continue
                if detail["has_real_website"]:
                    continue
                if detail["is_service_area_detail"]:
                    continue

                max_days = detail["max_review_days"]
                if max_days is None:
                    antiguedad_status = "no_verificada_revisar"
                elif max_days < MIN_AGE_DAYS:
                    continue
                elif max_days > MAX_AGE_DAYS:
                    antiguedad_status = "no_verificada_revisar"
                else:
                    antiguedad_status = "en_rango"

                rec["city"] = comuna
                rec["rubro"] = "detailing_automotriz"
                rec["source_query"] = query
                rec["antiguedad_dias_min"] = max_days
                rec["antiguedad_status"] = antiguedad_status
                rec["instagram_handle"] = detail["social_handle"] if detail["social_kind"] == "instagram" else None
                rec["instagram_source"] = "maps_link" if rec["instagram_handle"] else None
                rec["facebook_handle"] = detail["social_handle"] if detail["social_kind"] == "facebook" else None
                rec["identidad_visual_revisada"] = False
                rec["has_photos"] = detail["has_photos"]

                with open(OUT_PATH, "a", encoding="utf-8") as fout:
                    fout.write(json.dumps(rec, ensure_ascii=False) + "\n")
                verified_count += 1
                new_this_query += 1
                _touch()
            print(f"[pure-{SHARD_INDEX}] [{i}/{len(queries)}] '{query}' -> {len(articles)} items, +{new_this_query} verified (total {verified_count})", flush=True)
            mark_query_done(query)
            done_queries.add(query)
            _touch()
        except Exception as e:
            print(f"[pure-{SHARD_INDEX}] [{i}/{len(queries)}] '{query}' ERROR: {e}", flush=True)
            # NO se marca done -- una query que exploto a mitad de camino
            # (la sesion se cayo) se reintenta en el proximo arranque, capaz
            # con menos candidatos porque los ya vistos quedan en seen_names
            # via los archivos jsonl que si alcanzaron a escribirse.
            _touch()
        time.sleep(0.5)


def main():
    t = threading.Thread(target=_watchdog, daemon=True)
    t.start()

    queries = build_queries()
    done_queries = load_done_queries()
    print(f"[pure-{SHARD_INDEX}] shard {SHARD_INDEX}/{SHARD_COUNT}: {len(queries)} queries, {len(done_queries)} ya completadas en corridas previas", flush=True)

    # CHUNK chico (no 25 como en scrape_taller.py): una sola query de
    # detailing puede traer hasta 40 candidatos, cada uno con su propio
    # fetch de ficha de detalle -- con CHUNK=25 la sesion podia acumular
    # cientos de fetches antes de reciclarse y terminaba colapsando sola a
    # mitad de una query, perdiendo el progreso de esa query (aunque ahora
    # con done_queries igual no se pierde el shard entero, solo esa query
    # se reintenta). CHUNK chico + reintento por proceso (via el wrapper
    # bash) es mas confiable que reciclar la sesion a mano adentro del
    # proceso (probado en vivo: abrir/cerrar StealthySession seguido cuelga
    # el browser con "context or browser has been closed").
    CHUNK = 6
    remaining = [q for q in queries if q[0] not in done_queries]
    for start in range(0, len(remaining), CHUNK):
        chunk = remaining[start:start + CHUNK]
        print(f"[pure-{SHARD_INDEX}] opening fresh session for {start+1}-{start+len(chunk)} of {len(remaining)} pendientes", flush=True)
        _touch()
        try:
            with StealthySession(headless=True, network_idle=True, max_pages=1) as session:
                run_batch(chunk, session, done_queries)
        except Exception as e:
            print(f"[pure-{SHARD_INDEX}] session-level ERROR: {e}", flush=True)
            _touch()

    print(f"[pure-{SHARD_INDEX}] DONE ALL", flush=True)


if __name__ == "__main__":
    main()
