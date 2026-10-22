"""usage: python3 -I linkedin.py out_dir : fill 'LinkedIn cég-URL' in group CSVs from public company pages.

A guessed slug is accepted only if the public page (no login) links to the brand's own domain.
Stops at the first 429/999 (rate limit / bot wall) and leaves the rest empty.
"""
import csv
import glob
import re
import sys
import time
import unicodedata
import urllib.parse

import requests

UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120 Safari/537.36"}


def slug(s):
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"\(.*?\)", "", s)
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")


blocked = None
for path in sorted(glob.glob(f"{sys.argv[1]}/[0-9]_*.csv")):
    rows = list(csv.DictReader(open(path, encoding="utf-8-sig")))
    for r in rows:
        if r["LinkedIn cég-URL"] or blocked or not r["cégforma"]:
            continue
        dom = urllib.parse.urlparse(r["weboldal"]).netloc.replace("www.", "")
        comp = re.sub(r"^\w+\. \((.*)\)$", r"\1", r["cégforma"])
        base = slug(r["márka"])
        cands = list(dict.fromkeys([base, base + "-kft", slug(dom.split(".")[0]), slug(comp),
                                    slug(re.sub(r"\s(Kft|Bt|Zrt)\.?$", "", comp, flags=re.I))]))
        for c in cands:
            if not c:
                continue
            u = f"https://www.linkedin.com/company/{c}/"
            try:
                resp = requests.get(u, headers=UA, timeout=20)
            except Exception:
                continue
            time.sleep(2)
            if resp.status_code in (429, 999):
                blocked = f"LinkedIn {resp.status_code}"
                break
            if resp.status_code == 200 and dom.split(".")[0] in resp.text.lower() and dom in resp.text.lower():
                r["LinkedIn cég-URL"] = u
                print(r["márka"], u, flush=True)
                break
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
print("blocked:", blocked)
