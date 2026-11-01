"""Build uj_markak_230plus.csv (repo root) from rows230.json.

usage: python3 -I build_230.py
Skips every brand already in matchly_kizart_markak.csv or uj_markak_100.csv (and Out of Mood / SideQuest).
"""
import csv
import json
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
COLS = ["niche", "márka", "magyar szál", "magyar cég", "név", "pozíció", "forrás", "megjegyzés"]
NICHES = ["ruha", "kiegészítő", "táplálékkiegészítő", "smink", "skincare"]


def norm(s):
    s = re.sub(r"\(.*?\)", "", s)
    return re.sub(r"[^a-z0-9áéíóöőúüű]", "", s.lower())


excl = {norm(r["marka"]) for r in csv.DictReader(open(os.path.join(ROOT, "matchly_kizart_markak.csv"), encoding="utf-8-sig"))}
excl |= {norm(r["márka"]) for r in csv.DictReader(open(os.path.join(ROOT, "uj_markak_100.csv"), encoding="utf-8-sig"))}
excl |= {norm("Out of Mood"), norm("SideQuest")}

rows = json.load(open(os.path.join(HERE, "rows230.json"), encoding="utf-8"))
out, seen = [], set()
for niche in NICHES:
    for r in rows.get(niche, []):
        key = norm(r["márka"])
        if key in excl or key in seen:
            print("SKIP (kizárt/duplikált):", r["márka"])
            continue
        if not (r.get("magyar cég") and r.get("név") and r.get("forrás")):
            raise SystemExit(f"hiányos sor: {r}")
        seen.add(key)
        out.append({c: r.get(c, "") for c in COLS} | {"niche": niche})

with open(os.path.join(ROOT, "uj_markak_230plus.csv"), "w", newline="", encoding="utf-8-sig") as f:
    w = csv.DictWriter(f, COLS)
    w.writeheader()
    w.writerows(out)
print(len(out), "sor;", {n: sum(r["niche"] == n for r in out) for n in NICHES})
