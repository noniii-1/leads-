# -*- coding: utf-8 -*-
"""
Filtro final sobre verified_pure_detailing_shard*.jsonl (acumula las 2
tandas de scraping). Cambio de diseno respecto a la version anterior:
categorias en LISTA BLANCA estricta en vez de lista negra -- la tanda 2
trajo keywords como "spa automotriz"/"car spa"/"ceramic coating" que
matchearon por accidente el sufijo legal chileno "SpA" (Sociedad por
Acciones) en negocios de CUALQUIER rubro (repuestos de moto, aire
acondicionado, cerrajeria, spa humano, neumaticos...). Una lista negra de
categorias malas es un juego de whack-a-mole que nunca termina; una lista
blanca de categorias de lavado/detailing real es mucho mas segura.
Tambien se saco "spa" suelto de las palabras de senal por nombre (por el
mismo motivo) -- ahora una categoria ambigua solo pasa con frases
compuestas tipo "auto spa"/"car spa", nunca con "spa" solo.
"""
import json, glob, re, csv, unicodedata

def norm(s):
    s = unicodedata.normalize('NFKD', s or '')
    return ''.join(c for c in s if not unicodedata.combining(c)).lower()

files = sorted(glob.glob('verified_pure_detailing_shard*.jsonl'))
seen = {}
for f in files:
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

recs = list(seen.values())

# lista blanca: categorias de Maps que confirman lavado/detailing real.
# Cualquier categoria FUERA de esta lista necesita una senal fuerte e
# inequivoca en el nombre para pasar (ver AMBIGUOUS_OK_WITH_SIGNAL) o se
# descarta directo.
ALLOWED_CATEGORIES = {norm(c) for c in [
    'Servicio de lavado de coches', 'Servicio de limpieza de automóviles',
    'Autoservicio de lavado de autos', 'Servicio de detallado de automóviles',
    'Servicio de encerado de automóviles', 'Servicio de lavado a presión',
]}
# categorias ambiguas: pueden ser detailing mal etiquetado por Maps
# (paso ya visto con "Aces Detail", "Detailing Center") o pueden ser un
# negocio de otro rubro (taller mecanico, moto, repuestos...) -- pasan
# SOLO si el nombre trae una frase inequivoca de detailing/lavado
AMBIGUOUS_CATEGORIES = {norm(c) for c in [
    'Taller de reparación de automóviles', 'Taller de chapa y pintura',
    'Taller mecánico', 'Taller de revisión de automóviles', 'Fábrica',
    'Tienda de automovilismo', 'Pintura de automóviles', 'Taller de automóviles',
    'Servicio de restauración de automóviles', 'Tapicería para automóviles',
]}
# frases (no palabras sueltas) -- "spa" solo se acepta pegado a auto/car,
# nunca suelto (choca con el sufijo legal "SpA" de cualquier empresa)
STRONG_SIGNAL = [norm(s) for s in [
    'detailing', 'detallado', 'pulido', 'pulida', 'encerado',
    'sellado ceramico', 'estetica automotriz', 'car wash', 'carwash',
    'auto spa', 'car spa', 'spa automotriz', 'spa de auto', 'spa del automovil',
    'autospa', 'carspa', 'ceramic coating', 'brillado',
]]
# todo lo que NO esta en la lista blanca ni pasa por AMBIGUOUS+STRONG_SIGNAL
# se descarta -- ya no hace falta una lista negra de categorias malas.

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


def has_distinctive_content(name):
    words = re.findall(r"[a-z0-9']+", norm(name))
    remaining = [w for w in words if w not in GENERIC_FILLER_TOKENS and w not in COMUNA_TOKENS]
    return len(remaining) > 0


MANUAL_REJECT = {norm(n) for n in [
    'La Dehesa Limitada', 'Mecanica preventiva, general', 'CAMBIO DE DUEÑO',
    'Víctor Gutiérrez Valenzuela "Cano"', 'Taller Innovaciones', 'Comercial C&I',
    'Bass Audio Chile', 'Lavamoto Chile',
    'Juan Diego Cabrera Palacios Ventas Y Servicios Automotrices E.I.R.L',
    'Rapido y Brilloso', 'Lavado de Autos Cecilia', 'Lavado de autos El Robert',
    'Lavados de Autos Cristián', 'Centro Link',
    'Fresh Market',                                    # mercado/almacen, no automotriz
    'Servicio De Mantencion Y Lavado De Vehiculos Motor',  # descripcion generica, no nombre
    'Focos',                                           # una sola palabra de servicio, sin marca
]}
MANUAL_KEEP = {norm(n) for n in [
    'KombiSpa',
]}


def decide(rec):
    name_n = norm(rec['name'])
    cat_n = norm(rec.get('category') or '')
    if name_n in MANUAL_REJECT:
        return False, 'manual-reject'
    if name_n in MANUAL_KEEP:
        return True, 'manual-keep'
    if any(b in name_n for b in EXTRA_BLOCK_SUBSTR):
        return False, 'block-substr'
    if cat_n in AMBIGUOUS_CATEGORIES:
        if not any(s in name_n for s in STRONG_SIGNAL):
            return False, 'ambiguous-category-no-strong-signal'
    elif cat_n not in ALLOWED_CATEGORIES:
        return False, 'category-not-whitelisted'
    if not has_distinctive_content(rec['name']):
        return False, 'no-distinctive-content'
    if BARRIO_RE.match(name_n.strip()):
        return False, 'barrio-pattern'
    return True, 'ok'


kept, rejected = [], []
for r in recs:
    ok, reason = decide(r)
    (kept if ok else rejected).append((r, reason))

print('total unique:', len(recs), 'kept:', len(kept), 'rejected:', len(rejected))

with open('pure_detailing_rejected.csv', 'w', newline='', encoding='utf-8-sig') as f:
    w = csv.writer(f)
    w.writerow(['reason', 'name', 'city', 'rating', 'reviews', 'category'])
    for r, reason in rejected:
        w.writerow([reason, r['name'], r.get('city', ''), r.get('rating', ''), r.get('reviews', ''), r.get('category', '')])

kept_recs = [r for r, _ in kept]
kept_recs.sort(key=lambda r: (-(r.get('rating') or 0), -(r.get('reviews') or 0)))
with open('pure_detailing_final.csv', 'w', newline='', encoding='utf-8-sig') as f:
    w = csv.writer(f)
    w.writerow(['#', 'Nombre', 'Comuna', 'Rating', 'Resenas', 'Telefono', 'Direccion', 'Instagram', 'Categoria'])
    for i, r in enumerate(kept_recs, 1):
        w.writerow([i, r['name'], r.get('city', ''), r.get('rating', ''), r.get('reviews', ''), r.get('phone', ''), r.get('address', ''), r.get('instagram_handle') or '', r.get('category', '')])
print('wrote pure_detailing_final.csv and pure_detailing_rejected.csv')
