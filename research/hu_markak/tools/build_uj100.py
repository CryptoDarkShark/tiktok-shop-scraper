"""Build uj_markak_100.csv (repo root) from the curated rows in uj100_rows.json.

usage: python3 -I build_uj100.py
Rows are kept per niche in the JSON in fame order; this script only checks the
exclusion lists and writes the CSV, so it can be re-run after every edit.
"""
import csv
import json
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
COLS = ["niche", "márka", "weboldal", "magyar szál", "név", "pozíció", "linkedin_url", "megjegyzés"]
NICHES = ["ruha", "kiegészítő", "táplálékkiegészítő", "smink", "skincare"]


def norm(s):
    return re.sub(r"[^a-z0-9áéíóöőúüű]", "", s.lower())


excl = {norm(r["marka"]) for r in csv.DictReader(open(os.path.join(ROOT, "matchly_kizart_markak.csv"), encoding="utf-8-sig"))}
excl |= {norm("Out of Mood"), norm("SideQuest")}

rows = json.load(open(os.path.join(HERE, "uj100_rows.json"), encoding="utf-8"))
out, seen = [], set()
for niche in NICHES:
    for r in rows.get(niche, []):
        key = norm(r["márka"])
        if key in excl or key in seen:
            print("SKIP (kizárt/duplikált):", r["márka"])
            continue
        seen.add(key)
        if r.get("linkedin_url") and not r["linkedin_url"].startswith("https://"):
            raise SystemExit(f"bad linkedin url: {r}")
        out.append({c: r.get(c, "") for c in COLS} | {"niche": niche})

with open(os.path.join(ROOT, "uj_markak_100.csv"), "w", newline="", encoding="utf-8-sig") as f:
    w = csv.DictWriter(f, COLS)
    w.writeheader()
    w.writerows(out)
print(len(out), "sor;", {n: sum(r["niche"] == n for r in out) for n in NICHES},
      "; LinkedIn:", sum(bool(r["linkedin_url"]) for r in out))
