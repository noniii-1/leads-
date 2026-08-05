# -*- coding: utf-8 -*-
import csv
import time
import sys
from urllib.parse import quote
from scrapling.fetchers import StealthySession

IN_PATH = r"C:\Users\Admin\AppData\Local\Temp\claude\C--Users-Admin-Desktop-Proyecto-claudeeecode\f6e4e56f-750f-41e1-a134-c8f3f3139b2c\scratchpad\leads_raw_v2.psv"
OUT_PATH = r"C:\Users\Admin\AppData\Local\Temp\claude\C--Users-Admin-Desktop-Proyecto-claudeeecode\f6e4e56f-750f-41e1-a134-c8f3f3139b2c\scratchpad\scraped_results.tsv"

rows = []
with open(IN_PATH, "r", encoding="utf-8") as f:
    for line in f:
        parts = line.rstrip("\n").split("|")
        rows.append(parts)

print(f"Total rows: {len(rows)}", flush=True)

results = []
with StealthySession(headless=True, network_idle=True, max_pages=1) as session:
    for i, parts in enumerate(rows, start=1):
        name = parts[3]
        city = parts[4]
        query = f"{name} {city}"
        url = "https://www.google.com/maps/search/" + quote(query)
        phone = ""
        website = ""
        rating = ""
        try:
            page = session.fetch(url, timeout=30000)

            # Strategy 1: semantic data-item-id attributes (stable across Google's obfuscated class names)
            phone_els = page.css('[data-item-id^="phone:tel:"]')
            if phone_els:
                item_id = phone_els[0].attrib.get("data-item-id", "")
                phone = item_id.replace("phone:tel:", "").strip()
            website_els = page.css('a[data-item-id="authority"]')
            if website_els:
                href = website_els[0].attrib.get("href", "")
                website = href.split("?rwg_token=")[0] if "?rwg_token=" in href else href

            # Strategy 2: fallback to the class-based selectors seen on "search panel" style pages
            if not phone:
                phones = page.css("span.UsdlK")
                if phones:
                    phone = phones[0].text.strip()
            if not website:
                sites = page.css("a.A1zNzb")
                if sites:
                    href = sites[0].attrib.get("href", "")
                    website = href.split("?rwg_token=")[0] if "?rwg_token=" in href else href

            ratings = page.css("span.MW4etd")
            if ratings:
                rating = ratings[0].text.strip()
            status = "OK"
        except Exception as e:
            status = f"ERROR: {e}"

        results.append((i, status, phone, website, rating))
        print(f"[{i}/{len(rows)}] {name} -> status={status} phone={phone!r} website={website!r} rating={rating!r}", flush=True)

        with open(OUT_PATH, "a", encoding="utf-8") as out:
            out.write(f"{i}\t{status}\t{phone}\t{website}\t{rating}\n")

        time.sleep(1.2)

print("DONE", flush=True)
