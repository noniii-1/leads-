# -*- coding: utf-8 -*-
"""
Tercera pasada de filtrado sobre verified_pure_detailing_shard*.jsonl.
La corrida en vivo (is_pure_detailing_brand dentro del scraper) ya saco
mucha basura, pero al revisar a mano una muestra aparecieron fugas por
categoria de Maps (polarizado, clinicas esteticas humanas, lavanderia de
ropa, estacionamiento, taller de reparacion generico sin ninguna senal real
de detailing mas alla de la palabra "auto") y nombres puramente
descriptivos tipo "Lavado de autos a domicilio en <comuna>" que la
verificacion de "contenido distintivo" no agarraba porque "domicilio"/"en"
no estaban en la lista de relleno.
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

# categorias de Maps que indican otro rubro por completo (no automotriz) --
# se descartan siempre, sin excepcion de nombre
HARD_BLOCK_CATEGORIES = {norm(c) for c in [
    'Clínica especializada', 'Esteticista', 'Centro de estética',
    'Servicio de autos compartidos', 'Aparcamiento de coches compartidos',
    'Lavandería', 'Servicio de polarizado de autos', 'Mercado de automóviles',
]}
# categorias ambiguas (podrian ser un negocio de detailing mal etiquetado
# por Maps, o un taller/tienda que no tiene nada que ver) -- se aceptan
# SOLO si el nombre trae una senal fuerte e inequivoca de detailing
AMBIGUOUS_CATEGORIES = {norm(c) for c in [
    'Taller de reparación de automóviles', 'Taller de chapa y pintura',
    'Taller mecánico', 'Taller de revisión de automóviles', 'Fábrica',
    'Tienda de automovilismo', 'Pintura de automóviles',
]}
STRONG_SIGNAL = ['detailing', 'detallado', 'pulido', 'pulida', 'encerado',
                 'sellado ceramico', 'sellado cerámico', 'estetica automotriz',
                 'estética automotriz', 'car wash', 'carwash']

GENERIC_FILLER_TOKENS = {norm(s) for s in [
    'taller', 'servicio', 'servicios', 'automotriz', 'automotor', 'autos', 'auto',
    'de', 'del', 'y', 'la', 'el', 'los', 'las', 'lavado', 'lavados', 'detailing',
    'detallado', 'estetica', 'car', 'wash', 'carwash', 'spa', 'limpieza', 'pulido',
    'pulida', 'encerado', 'brillado', 'sellado', 'ceramico', 'ceramica', 'premium',
    'express', 'central', 'economico', 'economica', 'rapido', 'rapida', 'lujo',
    'basico', 'basica', 'multimarca', 'particular', 'domicilio', 'en', 'a', 'un',
    'una', 'con', 'para', 'el.', 'sin',
]}
COMUNAS_ALL = [
    "Santiago Centro", "Providencia", "Las Condes", "Vitacura", "Lo Barnechea",
    "La Reina", "Ñuñoa", "Macul", "Peñalolén", "La Florida",
    "San Joaquín", "La Granja", "La Pintana", "San Ramón", "El Bosque",
    "La Cisterna", "San Miguel", "Pedro Aguirre Cerda", "Lo Espejo", "Estación Central",
    "Cerrillos", "Maipú", "Cerro Navia", "Pudahuel", "Lo Prado",
    "Quinta Normal", "Renca", "Quilicura", "Huechuraba", "Conchalí",
    "Independencia", "Recoleta", "Puente Alto", "San Bernardo",
    "Colina", "Lampa", "Buin", "Paine", "Melipilla", "Peñalolén",
    "Talagante", "Padre Hurtado", "Calera de Tango",
]
COMUNA_TOKENS = {norm(w) for c in COMUNAS_ALL for w in c.split()}

EXTRA_BLOCK_SUBSTR = ['desabolladur', 'chapa', 'pintura al horno', 'carrozzier',
                      'lubricentro', 'caneria', 'inmovilizador', 'neumatic',
                      'frenos', 'suspension', 'alineacion', 'balanceo',
                      'mecanica general', 'radiador', 'escape', 'repuestos',
                      'gps', 'vulcaniza', 'polarizado', 'lavaseco y lavanderia',
                      'estacionamiento']


def has_distinctive_content(name):
    words = re.findall(r"[a-z0-9']+", norm(name))
    remaining = [w for w in words if w not in GENERIC_FILLER_TOKENS and w not in COMUNA_TOKENS]
    return len(remaining) > 0


# overrides puntuales encontrados al revisar a mano la lista completa --
# casos donde la regla general (categoria + contenido distintivo) se
# equivoca para ese nombre puntual
MANUAL_REJECT = {norm(n) for n in [
    'La Dehesa Limitada',            # nombre de barrio + sufijo legal, cero marca
    'Mecanica preventiva, general',  # es una descripcion de categoria, no un nombre
    'CAMBIO DE DUEÑO',               # parece un rotulo de estado del listado, no un negocio
    'Víctor Gutiérrez Valenzuela "Cano"',  # nombre propio pelado, mismo patron "Taller Miguel"
    'Taller Innovaciones',           # "Taller + palabra generica", sin marca real
    'Comercial C&I',                 # sin ninguna senal automotriz/de marca
    'Bass Audio Chile',              # instalador de audio, no detailing
    'Lavamoto Chile',                # lavado de MOTOS, no autos
    'Juan Diego Cabrera Palacios Ventas Y Servicios Automotrices E.I.R.L',  # registro formal EIRL, sin marca
    'Rapido y Brilloso',             # frase generica, aparece repetida en 2 comunas distintas
    'Lavado de Autos Cecilia',       # "servicio generico + nombre de pila pelado", mismo patron "Taller Miguel"
    'Lavado de autos El Robert',     # idem, "servicio generico + El + nombre de pila"
    'Lavados de Autos Cristián',     # idem
    'Centro Link',                   # cero referencia automotriz/de marca en el nombre
]}
MANUAL_KEEP = {norm(n) for n in [
    'KombiSpa',  # "Kombi" = furgon VW, Maps lo categoriza mal como centro de estetica humano
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
    if cat_n in HARD_BLOCK_CATEGORIES:
        return False, 'hard-block-category'
    if cat_n in AMBIGUOUS_CATEGORIES:
        if not any(s in name_n for s in STRONG_SIGNAL):
            return False, 'ambiguous-category-no-strong-signal'
    if not has_distinctive_content(rec['name']):
        return False, 'no-distinctive-content'
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
