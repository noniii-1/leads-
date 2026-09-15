# -*- coding: utf-8 -*-
"""
Insert new_dental_leads.json (output of merge_dental.py) into the dashboard's
leads-data JSON blob, next to the 89 already-kept clinics. Idempotent-ish:
re-running after re-generating new_dental_leads.json replaces the "is_new_batch2"
additions cleanly by first stripping any cid starting with gm4_.
"""
import json
import re

HTML_PATH = "leads_santiago_dashboard.html"
NEW_LEADS_PATH = "new_dental_leads.json"


def main():
    with open(HTML_PATH, encoding="utf-8") as f:
        content = f.read()

    m = re.search(r'(<script id="leads-data"[^>]*>)(.*?)(</script>)', content, re.S)
    assert m, "leads-data script tag not found"
    existing = json.loads(m.group(2))

    # drop any previous gm4_ batch so this script is safe to re-run
    existing = [e for e in existing if not str(e.get("cid", "")).startswith("gm4_")]

    with open(NEW_LEADS_PATH, encoding="utf-8") as f:
        new_leads = json.load(f)

    combined = existing + new_leads
    print("existing (kept):", len(existing))
    print("new leads added:", len(new_leads))
    print("combined total:", len(combined))

    new_json = json.dumps(combined, ensure_ascii=False, separators=(",", ":"))
    new_content = content[:m.start(2)] + new_json + content[m.end(2):]

    with open(HTML_PATH, "w", encoding="utf-8") as f:
        f.write(new_content)
    print("written OK")


if __name__ == "__main__":
    main()
