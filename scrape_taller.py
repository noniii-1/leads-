# -*- coding: utf-8 -*-
"""
Harvest AUTOMOTIVE leads (talleres mecanicos / car detailing) on Google Maps
in Gran Santiago that pass, in one detail-page visit per candidate:
- categoria automotriz independiente (excluye concesionarios/cadenas de marca)
- sin sitio web propio real (un link a Instagram/Facebook SI cuenta como "sin web")
- local propio y fijo (direccion fisica visible, no "area de servicio")
- antiguedad estimada 6 meses - 3 anios, best-effort SIN login (ver notas abajo)

Notas sobre antiguedad (criterio 4): Google Maps requiere sesion iniciada para
ordenar las resenas por "mas antiguas" o para paginar el historial completo sin
tope. Sin login, este script lee todas las resenas que alcanzan a cargar en la
vista y toma la mas antigua visible como una COTA INFERIOR de antiguedad, no
una medicion exacta. Como salvaguarda: negocios con muchas resenas (>MAX_
REVIEWS_FOR_AGE_CHECK, casi seguro >3 anios) se descartan directo sin abrir
ficha; los casos donde no se pudo leer ninguna fecha se INCLUYEN igual pero
marcados antiguedad_status="no_verificada_revisar" en vez de asumir que pasan.

Usage: python scrape_taller.py <shard_index> <shard_count>
  e.g. python scrape_taller.py 0 3
Writes verified_taller_shard<N>.jsonl (resumable, dedup por nombre).
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

# evita crashear con nombres de negocio que traen iconos/simbolos que el
# codepage de la consola de Windows no puede codificar (ya visto en dental)
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

MIN_REVIEWS = 10
MAX_REVIEWS_FOR_AGE_CHECK = 200
MIN_AGE_DAYS = 183
MAX_AGE_DAYS = 1095
WATCHDOG_SECS = 100

SHARD_INDEX = int(sys.argv[1]) if len(sys.argv) > 1 else 0
SHARD_COUNT = int(sys.argv[2]) if len(sys.argv) > 2 else 1
# modo opcional "detailing" (3er arg): solo corre las queries de detailing,
# en su propio archivo de salida, para ampliar ese rubro sin re-escanear
# todas las queries de taller mecanico ya cubiertas
DETAILING_ONLY = len(sys.argv) > 3 and sys.argv[3] == "detailing"
OUT_PATH = f"verified_detailing_shard{SHARD_INDEX}.jsonl" if DETAILING_ONLY else f"verified_taller_shard{SHARD_INDEX}.jsonl"

COMUNAS = [
    "Santiago Centro", "Providencia", "Las Condes", "Vitacura", "Lo Barnechea",
    "La Reina", "Ñuñoa", "Macul", "Peñalolén", "La Florida",
    "San Joaquín", "La Granja", "La Pintana", "San Ramón", "El Bosque",
    "La Cisterna", "San Miguel", "Pedro Aguirre Cerda", "Lo Espejo", "Estación Central",
    "Cerrillos", "Maipú", "Cerro Navia", "Pudahuel", "Lo Prado",
    "Quinta Normal", "Renca", "Quilicura", "Huechuraba", "Conchalí",
    "Independencia", "Recoleta", "Puente Alto", "San Bernardo",
]

MECHANIC_KEYWORDS = [
    "taller mecanico", "taller mecanico multimarca", "servicio automotriz",
    "mecanica automotriz", "taller de mantencion automotriz", "taller mecanico particular",
]
DETAILING_KEYWORDS = [
    "estetica automotriz", "detailing automotriz", "detailing de autos",
    "car detailing", "auto detailing", "pulido y detailing automotriz",
    "pulido de pintura automotriz", "encerado y pulido de autos",
    "sellado ceramico automotriz", "lavado premium de autos",
    "brillado de autos", "revitalizado automotriz", "limpieza premium de autos",
    "tapiceria y detailing", "vidrio ceramico automotriz", "pulido de faros y autos",
    "car care detailing", "detailing de lujo", "auto spa detailing",
    "taller de detailing",
]
DETAILING_MIN_REVIEWS = 10


def build_queries():
    queries = []
    for comuna in COMUNAS:
        if not DETAILING_ONLY:
            for kw in MECHANIC_KEYWORDS:
                queries.append((f"{kw} {comuna} Santiago Chile", comuna, "taller_mecanico"))
        for kw in DETAILING_KEYWORDS:
            queries.append((f"{kw} {comuna} Santiago Chile", comuna, "detailing_automotriz"))
    return [q for i, q in enumerate(queries) if i % SHARD_COUNT == SHARD_INDEX]


def _norm(s):
    s = unicodedata.normalize('NFKD', s or '')
    return ''.join(c for c in s if not unicodedata.combining(c)).lower()


CLEAR_AUTO_TAGS = {_norm(t) for t in [
    'taller mecánico', 'taller de reparación de automóviles',
    'taller de automóviles', 'servicio de reparación de automóviles',
    'taller multimarca', 'servicio automotriz',
    'servicio de detailing de automóviles', 'servicio de limpieza de automóviles',
    'taller de mantenimiento de automóviles',
]}
AUTO_KEYWORDS = [_norm(k) for k in [
    'taller mecanico', 'mecanica automotriz', 'servicio automotriz',
    'detailing automotriz', 'detailing de auto', 'taller multimarca',
    'auto repair', 'car detailing', 'pulido automotriz', 'car service',
]]

# is_real_auto necesita las frases exactas de arriba O esta combinacion mas
# flexible: una palabra de contexto automotriz + una palabra de servicio,
# en cualquier orden/posicion del nombre (no pegadas). Frase-exacta era
# demasiado rigida -- un negocio real como "DETAILING SU&PER AUTOMOTRIZ" se
# rechazaba porque "detailing automotriz" no aparecia pegado. "detailing" es
# suficientemente inequivoco en Chile como para aceptarlo solo.
AUTO_CONTEXT_TOKENS = [_norm(k) for k in ['automotriz', 'automotor', 'vehicular', 'de autos', 'de auto ']]
SERVICE_TOKENS = [_norm(k) for k in [
    'taller', 'mecanic', 'pulido', 'encerado', 'estetica', 'lavado', 'sellado',
    'multimarca', 'tapiceria', 'brillado', 'revitalizado', 'detailing',
]]

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

# El href de la tarjeta trae "@lat,lng,ZOOMz" -- un pin a nivel calle es
# ~16-19z; ~10z o menos es region/pais (geocodificacion ambigua o mala).
# Ademas de ser una mala senal para "local fijo", estos casos hacen que la
# ficha de detalle a veces no cargue bien y el fetch se cuelgue indefinidamente
# (visto en vivo: un candidato en Kentucky, EEUU quedo pineado a nivel pais y
# trababa el pipeline reintento tras reintento). Se descartan antes de abrir
# la ficha.
ZOOM_RE = re.compile(r'@-?\d+\.\d+,-?\d+\.\d+,(\d+(?:\.\d+)?)z')
MIN_ZOOM = 14


def is_imprecise_location(href):
    if not href:
        return False
    m = ZOOM_RE.search(href)
    if not m:
        return False
    return float(m.group(1)) < MIN_ZOOM

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
            print(f"[taller-{SHARD_INDEX}] WATCHDOG: no progress for {stale:.0f}s, force-exiting", flush=True)
            os._exit(1)


def is_real_auto(rec):
    cat_norm = _norm(rec.get("category") or "")
    if cat_norm in CLEAR_AUTO_TAGS:
        return True
    hay = _norm(f"{rec['name']} {rec.get('category') or ''}")
    if any(k in hay for k in AUTO_KEYWORDS):
        return True
    if 'detailing' in hay:
        return True
    has_context = any(t in hay for t in AUTO_CONTEXT_TOKENS)
    has_service = any(t in hay for t in SERVICE_TOKENS)
    return has_context and has_service


def is_chain_or_dealer(rec):
    hay = _norm(f" {rec['name']} {rec.get('category') or ''} ")
    return any(k in hay for k in EXCLUDE_KEYWORDS)


def is_service_area(rec):
    addr = (rec.get("address") or "").strip()
    if not addr:
        return True
    return bool(SERVICE_AREA_RE.search(addr))


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
    # el link "Sitio web" real (si existe) vive en el href del boton, no en el
    # texto visible -- lo leemos del DOM en vez de regex sobre texto renderizado
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
        if 'Sitio web' not in text and 'Visitar el sitio web' not in text:
            return False
        return False  # label present pero sin href capturado -> no confirmamos, no excluimos
    domain = href.lower()
    if any(sd in domain for sd in SOCIAL_DOMAINS) or 'google.' in domain:
        return False
    return True


# --- Instagram check (solo se usa en modo "detailing", donde el usuario
# pidio que Instagram activo sea requisito duro y no solo un dato anotado).
# Logica identica a la de check_instagram.py (detector corregido), duplicada
# aca en vez de importada para no re-disparar el wrapping de sys.stdout de
# ese modulo (romperia el stdout de este proceso si se importa dos veces).
IG_TITLE_HANDLE_RE = re.compile(r'\(@([A-Za-z0-9_.]+)\)')
IG_NOT_AVAILABLE_MARKERS = (
    "Página no disponible", "Page Not Found", "Sorry, this page isn't available",
    "content isn't available", "Profile isn't available", "isn't available",
)
IG_FOLLOWERS_LABELS = ("followers", "seguidores")


def ig_best_guess_handle(name):
    norm = unicodedata.normalize('NFKD', name).encode('ascii', 'ignore').decode('ascii')
    words = re.findall(r'[a-zA-Z0-9]+', norm.lower())
    return "".join(words)[:30] if words else None


def ig_do_open(url):
    def _action(page):
        page.wait_for_timeout(2000)
        return page
    return _action


def ig_check_profile(session, handle):
    url = f"https://www.instagram.com/{handle}/"
    try:
        page = session.fetch(url, page_action=ig_do_open(url), timeout=20000, network_idle=False)
        txt = page.get_all_text()
        lines = [l.strip() for l in txt.split("\n") if l.strip()]
        if not lines:
            return {"exists": None, "followers": None}
        title_match = IG_TITLE_HANDLE_RE.search(lines[0])
        if title_match and title_match.group(1).lower() == handle.lower():
            followers = None
            for i, l in enumerate(lines):
                if l.lower() in IG_FOLLOWERS_LABELS and i > 0:
                    followers = lines[i - 1]
                    break
            return {"exists": True, "followers": followers}
        if any(m in txt for m in IG_NOT_AVAILABLE_MARKERS):
            return {"exists": False, "followers": None}
        return {"exists": None, "followers": None}
    except Exception as e:
        print(f"[taller-{SHARD_INDEX}]   ig-check ERROR for @{handle}: {e}", flush=True)
        return {"exists": None, "followers": None}


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
            for _ in range(5):
                feed.evaluate("el => el.scrollTop = el.scrollHeight")
                page.wait_for_timeout(700)
        except Exception:
            pass
        return page
    return _action


def do_open_detail(url):
    def _action(page):
        page.wait_for_timeout(3500)
        # scroll defensivo del panel de detalle para lazy-load mas snippets de
        # resenas (best-effort, sin login no hay garantia de llegar al final)
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
        # "Ver fotos" solo aparece cuando hay al menos una foto real cargada
        # (validado en vivo) -- no mide calidad/si es "propia y cuidada" (eso
        # sigue siendo criterio manual, como identidad_visual_revisada), solo
        # presencia/ausencia de fotos
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
        print(f"[taller-{SHARD_INDEX}]   detail-check ERROR: {e}", flush=True)
        return {"ok": False}


def load_seen():
    seen = set()
    paths = [OUT_PATH] + glob.glob("verified_taller_shard*.jsonl") + glob.glob("verified_detailing_shard*.jsonl")
    for path in set(paths):
        try:
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    seen.add(json.loads(line)["name"].strip().lower())
        except FileNotFoundError:
            pass
    return seen


def run_batch(queries, session):
    seen_names = load_seen()
    verified_count = 0
    for i, (query, comuna, rubro) in enumerate(queries, start=1):
        url = "https://www.google.com/maps"
        try:
            page = session.fetch(url, page_action=do_search(query), timeout=30000, network_idle=False)
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
                min_reviews_floor = DETAILING_MIN_REVIEWS if DETAILING_ONLY else MIN_REVIEWS
                if rec["reviews"] < min_reviews_floor or rec["reviews"] > MAX_REVIEWS_FOR_AGE_CHECK:
                    continue
                if rec.get("rating") is not None and rec["rating"] < 3.0:
                    continue
                if not is_real_auto(rec):
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
                seen_names.add(key)

                detail = check_detail(session, href)
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
                    continue  # muy nuevo (<6 meses), descartar
                elif max_days > MAX_AGE_DAYS:
                    antiguedad_status = "no_verificada_revisar"  # vista limitada: no confiamos en que sea el maximo real
                else:
                    antiguedad_status = "en_rango"

                rec["city"] = comuna
                rec["rubro"] = rubro
                rec["source_query"] = query
                rec["antiguedad_dias_min"] = max_days
                rec["antiguedad_status"] = antiguedad_status
                rec["instagram_handle"] = detail["social_handle"] if detail["social_kind"] == "instagram" else None
                rec["instagram_source"] = "maps_link" if rec["instagram_handle"] else None
                rec["facebook_handle"] = detail["social_handle"] if detail["social_kind"] == "facebook" else None
                rec["identidad_visual_revisada"] = False
                rec["has_photos"] = detail["has_photos"]

                if DETAILING_ONLY:
                    # requisito duro: instagram encontrado y publico (no solo
                    # anotado). "activo en ultimos 30 dias" sigue sin poder
                    # verificarse sin login -- esto confirma existencia/perfil
                    # publico, que es el maximo automatizable.
                    if rec["instagram_handle"]:
                        ig_result = ig_check_profile(session, rec["instagram_handle"])
                        rec["instagram_status"] = (
                            "perfil_publico_confirmado_actividad_no_verificada"
                            if ig_result["exists"] else None
                        )
                    else:
                        guess = ig_best_guess_handle(rec["name"])
                        ig_result = ig_check_profile(session, guess) if guess else {"exists": None}
                        if ig_result["exists"]:
                            rec["instagram_handle"] = guess
                            rec["instagram_source"] = "adivinado_por_nombre"
                            rec["instagram_status"] = "perfil_encontrado_por_nombre_verificar_manualmente"
                        else:
                            rec["instagram_status"] = None
                    time.sleep(3.0)
                    if not rec["instagram_status"]:
                        continue  # sin instagram confirmado -> no cumple el requisito pedido

                with open(OUT_PATH, "a", encoding="utf-8") as fout:
                    fout.write(json.dumps(rec, ensure_ascii=False) + "\n")
                verified_count += 1
                new_this_query += 1
                _touch()
            print(f"[taller-{SHARD_INDEX}] [{i}/{len(queries)}] '{query}' -> {len(articles)} items, +{new_this_query} verified (total {verified_count})", flush=True)
            _touch()
        except Exception as e:
            print(f"[taller-{SHARD_INDEX}] [{i}/{len(queries)}] '{query}' ERROR: {e}", flush=True)
            _touch()
        time.sleep(0.5)


def main():
    t = threading.Thread(target=_watchdog, daemon=True)
    t.start()

    queries = build_queries()
    print(f"[taller-{SHARD_INDEX}] shard {SHARD_INDEX}/{SHARD_COUNT}: {len(queries)} queries", flush=True)

    CHUNK = 25
    for start in range(0, len(queries), CHUNK):
        chunk = queries[start:start + CHUNK]
        print(f"[taller-{SHARD_INDEX}] opening fresh session for {start+1}-{start+len(chunk)}", flush=True)
        _touch()
        try:
            with StealthySession(headless=True, network_idle=True, max_pages=1) as session:
                run_batch(chunk, session)
        except Exception as e:
            print(f"[taller-{SHARD_INDEX}] session-level ERROR: {e}", flush=True)
            _touch()

    print(f"[taller-{SHARD_INDEX}] DONE ALL", flush=True)


if __name__ == "__main__":
    main()
