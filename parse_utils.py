# -*- coding: utf-8 -*-
import re

RATING_RE = re.compile(r'^\d\.\d$')
REVIEWS_RE = re.compile(r'^\(([\d.,]+)\)$')
PHONE_RE = re.compile(r'^(9\s?\d{4}\s?\d{4}|\(2\)\s?\d{3,4}\s?\d{4}|600\s?\d{3}\s?\d{4}|\d{2}\s?\d{4}\s?\d{4})$')


def parse_article(text):
    lines = [l.strip() for l in text.split("\n") if l.strip() != ""]
    if not lines:
        return None
    # drop "Patrocinado" marker lines
    lines = [l for l in lines if l != "Patrocinado"]
    if not lines:
        return None
    name = lines[0]
    # skip duplicate name line(s)
    i = 1
    while i < len(lines) and lines[i] == name:
        i += 1

    rating = None
    reviews = 0
    if i < len(lines) and lines[i] == "No hay opiniones":
        i += 1
    elif i < len(lines) and RATING_RE.match(lines[i]):
        rating = float(lines[i])
        i += 1
        if i < len(lines):
            m = REVIEWS_RE.match(lines[i])
            if m:
                reviews = int(m.group(1).replace(",", "").replace(".", ""))
                i += 1

    category = lines[i] if i < len(lines) else ""
    i += 1
    # skip a lone "." separator line if present
    if i < len(lines) and lines[i] in (".", "·"):
        i += 1

    address = lines[i] if i < len(lines) else ""
    i += 1

    # find phone anywhere in the remaining lines (search a window)
    phone = ""
    for j in range(i, min(i + 6, len(lines))):
        if PHONE_RE.match(lines[j]):
            phone = lines[j]
            break

    has_website = "Sitio web" in text

    return {
        "name": name,
        "rating": rating,
        "reviews": reviews,
        "category": category,
        "address": address,
        "phone": phone,
        "has_website": has_website,
    }
