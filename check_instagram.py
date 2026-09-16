# -*- coding: utf-8 -*-
"""
Best-effort Instagram check for leads en verified_taller_shard*.jsonl.

Dos casos:
1) El lead ya trae instagram_handle porque Maps mostraba ese link como "Sitio
   web" (alta confianza, viene de scrape_taller.py) -> solo confirmamos que el
   perfil siga existiendo/publico.
2) No hay handle conocido -> se prueban variantes del nombre del negocio
   (baja confianza, es una adivinanza).

LIMITACION IMPORTANTE: sin sesion de Instagram logueada, el perfil publico
anonimo normalmente solo expone nombre/bio/conteo de seguidores en las meta
tags -- NO expone la fecha del ultimo post. Por eso este script nunca
confirma "actividad en los ultimos 30 dias" de forma automatica; solo separa
"perfil publico encontrado" de "no encontrado / privado / bloqueado", y deja
la verificacion de actividad reciente para revision manual, tal como pide el
criterio 5 del brief cuando no se puede automatizar con confianza.

Usage: python check_instagram.py
Writes taller_instagram_results.jsonl (resumable, dedup por nombre).
"""
import os
import re
import sys
import io
import time
import json
import glob
import unicodedata
import threading
from scrapling.fetchers import StealthySession

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

OUT_PATH = "taller_instagram_results.jsonl"
WATCHDOG_SECS = 120
REQUEST_DELAY = 3.0

# El HTML actual de Instagram (verificado en vivo) NO trae el viejo formato
# "X Followers, Y Following, Z Posts" en una linea -- el numero de seguidores
# y la palabra "followers"/"seguidores" quedan en lineas separadas, y la
# PRIMERA linea de texto de un perfil publico real es
# "NOMBRE (@handle) - Instagram photos and videos". Esa primera linea es la
# senal confiable de que el perfil existe y es publico (mucho mas confiable
# que buscar "Log in" en el texto, que aparece SIEMPRE por el navbar incluso
# cuando el perfil cargo bien).
TITLE_HANDLE_RE = re.compile(r'\(@([A-Za-z0-9_.]+)\)')
NOT_AVAILABLE_MARKERS = (
    "Página no disponible", "Page Not Found", "Sorry, this page isn't available",
    "content isn't available", "Profile isn't available", "isn't available",
)
FOLLOWERS_LABELS = ("followers", "seguidores")

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
            print(f"[ig] WATCHDOG: no progress for {stale:.0f}s, force-exiting", flush=True)
            os._exit(1)


def slugify_variants(name):
    norm = unicodedata.normalize('NFKD', name).encode('ascii', 'ignore').decode('ascii')
    words = re.findall(r'[a-zA-Z0-9]+', norm.lower())
    if not words:
        return []
    joined = "".join(words)[:30]
    underscored = "_".join(words)[:30]
    dotted = ".".join(words)[:30]
    variants = [joined, underscored, dotted]
    seen = set()
    out = []
    for v in variants:
        if v and v not in seen:
            seen.add(v)
            out.append(v)
    return out


def load_leads():
    leads = []
    seen = set()
    for path in sorted(glob.glob("verified_taller_shard*.jsonl")):
        with open(path, encoding="utf-8") as f:
            for line in f:
                rec = json.loads(line)
                key = rec["name"].strip().lower()
                if key in seen:
                    continue
                seen.add(key)
                leads.append(rec)
    return leads


def load_done():
    done = set()
    try:
        with open(OUT_PATH, encoding="utf-8") as f:
            for line in f:
                done.add(json.loads(line)["name"].strip().lower())
    except FileNotFoundError:
        pass
    return done


def do_open(url):
    def _action(page):
        page.wait_for_timeout(2000)
        return page
    return _action


def check_profile(session, handle):
    url = f"https://www.instagram.com/{handle}/"
    try:
        page = session.fetch(url, page_action=do_open(url), timeout=20000, network_idle=False)
        txt = page.get_all_text()
        lines = [l.strip() for l in txt.split("\n") if l.strip()]
        if not lines:
            return {"exists": None, "followers": None}

        title_match = TITLE_HANDLE_RE.search(lines[0])
        if title_match and title_match.group(1).lower() == handle.lower():
            followers = None
            for i, l in enumerate(lines):
                if l.lower() in FOLLOWERS_LABELS and i > 0:
                    followers = lines[i - 1]
                    break
            return {"exists": True, "followers": followers}

        if any(m in txt for m in NOT_AVAILABLE_MARKERS):
            return {"exists": False, "followers": None}  # confirmado que no existe / fue removido

        return {"exists": None, "followers": None}  # ambiguo (bloqueo, privado, etc) -> revisar manualmente
    except Exception as e:
        print(f"[ig]   fetch ERROR for @{handle}: {e}", flush=True)
        return {"exists": None, "followers": None}


def resolve_lead(session, lead):
    name = lead["name"]
    known_handle = lead.get("instagram_handle")

    if known_handle:
        result = check_profile(session, known_handle)
        if result["exists"]:
            status = "perfil_publico_confirmado_actividad_no_verificada"
        else:
            status = "link_de_maps_no_confirmable_revisar_manualmente"
        return {
            "name": name,
            "instagram_handle": known_handle,
            "instagram_source": "maps_link",
            "instagram_status": status,
            "instagram_followers": result["followers"],
            "instagram_last_post_days": None,
        }

    # Solo se prueba 1 variante (la union sin separadores, la mas comun) en
    # vez de las 3 -- probar las otras 2 casi nunca sumaba un match real (el
    # detector ya corregido confirma que la mayoria de los "encontrados" caen
    # en la primera variante) y triplicaba el tiempo/requests por lead sin
    # handle conocido.
    for handle in slugify_variants(name)[:1]:
        result = check_profile(session, handle)
        _touch()
        time.sleep(REQUEST_DELAY)
        if result["exists"]:
            return {
                "name": name,
                "instagram_handle": handle,
                "instagram_source": "adivinado_por_nombre",
                "instagram_status": "perfil_encontrado_por_nombre_verificar_manualmente",
                "instagram_followers": result["followers"],
                "instagram_last_post_days": None,
            }

    return {
        "name": name,
        "instagram_handle": None,
        "instagram_source": None,
        "instagram_status": "no_encontrado_verificar_manualmente",
        "instagram_followers": None,
        "instagram_last_post_days": None,
    }


def main():
    t = threading.Thread(target=_watchdog, daemon=True)
    t.start()

    leads = load_leads()
    done = load_done()
    pending = [l for l in leads if l["name"].strip().lower() not in done]
    print(f"[ig] {len(leads)} leads total, {len(pending)} pending", flush=True)

    CHUNK = 20
    for start in range(0, len(pending), CHUNK):
        chunk = pending[start:start + CHUNK]
        print(f"[ig] opening fresh session for {start+1}-{start+len(chunk)}", flush=True)
        _touch()
        try:
            with StealthySession(headless=True, network_idle=False, max_pages=1) as session:
                for i, lead in enumerate(chunk, start=1):
                    result = resolve_lead(session, lead)
                    with open(OUT_PATH, "a", encoding="utf-8") as fout:
                        fout.write(json.dumps(result, ensure_ascii=False) + "\n")
                    print(f"[ig] [{start+i}/{len(pending)}] {lead['name']!r} -> {result['instagram_status']}", flush=True)
                    _touch()
                    time.sleep(REQUEST_DELAY)
        except Exception as e:
            print(f"[ig] session-level ERROR: {e}", flush=True)
            _touch()

    print("[ig] DONE ALL", flush=True)


if __name__ == "__main__":
    main()
