"""Build one CSV per product group from verify.py results.

usage: python3 -I build_csv.py extra.json out_dir res1.json [res2.json ...]
extra.json: {website: {"skip": reason, "founder": "Name (role) — url", "marketing": "Name — url",
             "hungarian": "igen/nem/részleges", "note": "..."}}
"""
import csv
import json
import re
import sys
import urllib.parse

COLS = ["termékcsoport", "márka", "márkatípus", "weboldal", "cégforma", "becsült méret", "magyar-e", "TikTok Shop-jelenlét",
        "tulajdonos/döntéshozó (név + forrás)", "marketingvezető (név + forrás)", "LinkedIn cég-URL",
        "Meta Ad Library-link", "forrás", "forrás dátuma", "státusz"]
FILES = {"Skincare": "1_skincare.csv", "Supplement": "2_supplement.csv", "Smink": "3_smink.csv",
         "Ruházat": "4_ruhazat.csv", "Sportkiegészítő": "5_sportkiegeszito.csv", "Hajápolás": "6_hajapolas.csv",
         "Kiegészítők": "7_kiegeszitok.csv"}


def revenue_m(rev):
    # "2025 316 200 ezer Ft" -> (2025, 316.2)
    m = re.match(r"(\d{4}) ([\d ]+) ezer Ft", rev or "")
    return (int(m.group(1)), int(m.group(2).replace(" ", "")) / 1000) if m else (None, None)


def headcount_range(hc):
    nums = [int(x) for x in re.findall(r"\d+", hc or "")]
    return (min(nums), max(nums)) if nums else (None, None)


def size_ok(n):
    year, rev = revenue_m(n.get("revenue"))
    lo, hi = headcount_range(n.get("headcount"))
    if rev is not None and rev > 2000:
        return False, "túl nagy (árbevétel > 2 Mrd Ft)"
    if rev is not None and 100 <= rev <= 2000:
        return True, ""
    if lo is not None and lo >= 5 and (hi or lo) <= 50:
        return True, ""
    if rev is None and lo is None:
        return None, "méret nem igazolt"
    return False, "túl kicsi (< 100 M Ft és < 5 fő)"


def form_of(company):
    if re.search(r"Zrt", company or "", re.I):
        return "Zrt."
    if re.search(r"Betéti|Bt\b", company or "", re.I):
        return "Bt."
    if re.search(r"Korlátolt|Kft", company or "", re.I):
        return "Kft."
    return ""


def main():
    extra = json.load(open(sys.argv[1]))
    out_dir = sys.argv[2]
    merged = {}
    for p in sys.argv[3:]:
        for r in json.load(open(p)):
            merged[r["website"]] = r
    recs = list(merged.values())
    by_group, skipped = {}, []
    host = lambda u: urllib.parse.urlparse(u).netloc.replace("www.", "")
    extra_h = {}
    for k, v in extra.items():
        extra_h.setdefault(host(k), {}).update(v)
    for r in recs:
        x = extra.get(r["website"]) or extra_h.get(host(r["website"]), {})
        n = r.get("nct") or {}
        ok, why = size_ok(n) if n and not n.get("error") else (None, "cégadat nem található a nemzeticegtar.hu-n")
        if x.get("skip"):
            skipped.append((r["group"], r["brand"], r["website"], x["skip"]))
            continue
        if ok is False:
            skipped.append((r["group"], r["brand"], r["website"], why))
            continue
        company = n.get("name") or r.get("company") or ""
        if not company and not x.get("note"):
            skipped.append((r["group"], r["brand"], r["website"],
                            "üzemeltető Kft./Bt. nem azonosítható a weboldal impresszumában/ÁSZF-ében"))
            continue
        if n.get("error") and not x.get("note"):
            skipped.append((r["group"], r["brand"], r["website"],
                            f"a weboldalon talált cég ({company}) nem található a nemzeticegtar.hu-n"))
            continue
        if '"v. a."' in (n.get("name") or "") or "v. a." in (n.get("name") or ""):
            skipped.append((r["group"], r["brand"], r["website"], f"végelszámolás alatt ({n.get('url')})"))
            continue
        year, rev = revenue_m(n.get("revenue"))
        size = []
        if rev is not None:
            size.append(f"nettó árbevétel {year}: {rev:,.1f} M Ft".replace(",", " ").replace(".", ","))
        if n.get("headcount"):
            size.append(f"létszám: {n['headcount'].replace(' Fő', ' fő')}")
        size = "; ".join(size) + (f" (forrás: {n['url']})" if size else "")
        sig = [re.sub(r"\(([^()0-9]+?)\s+\d{4}[^()]*\)", r"(\1)", x) for x in dict.fromkeys(n.get("signatories") or [])]
        owner = "; ".join(f"{s} — {n['url']}" for s in sig)
        if x.get("founder"):
            owner = (owner + "; " if owner else "") + x["founder"]
        tt = r.get("tt") or {}
        soc = r.get("social") or {}
        if soc.get("tiktok_shop_link") or tt.get("seller"):
            tts = "igen"
        elif tt.get("seller") is False:
            tts = "nem"
        else:
            tts = "nem ellenőrizve"
        if x.get("tiktok_shop"):
            tts = x["tiktok_shop"]
        q = urllib.parse.quote(r["brand"])
        meta = (f"https://www.facebook.com/ads/library/?active_status=all&ad_type=all&country=HU&q={q}"
                f"&search_type=keyword_unordered")
        sources = [s for s in [r.get("company_src"), n.get("url"), tt.get("url")] if s]
        notes = []
        if tt.get("error"):
            notes.append(f"TikTok: {tt['error']}")
        elif not soc.get("tiktok"):
            notes.append("TikTok-fiók nem található a weboldalon; TikTok Shop publikus kereső nem ellenőrizve")
        elif tt.get("seller") is False:
            notes.append(f"TikTok-profil ({soc['tiktok']}, {tt.get('followers')} követő) nem TikTok Shop-eladó jelölésű")
        notes.append("Meta Ad Library: nyilvános felület 403-at adott, nem ellenőrizve")
        if x.get("note"):
            notes.append(x["note"])
        have_company = bool(company)
        have_size = bool(size)
        have_owner = bool(owner)
        if have_company and have_size and have_owner:
            status = "ellenőrzött"
        elif have_company:
            status = "részleges"
        else:
            status = "nem igazolt"
        if x.get("status"):
            status = x["status"]
        status += " — " + "; ".join(notes)
        row = {
            "termékcsoport": r["group"], "márka": r["brand"], "márkatípus": x.get("type", "saját márka"), "weboldal": r["website"],
            "cégforma": f"{form_of(company)} ({company})" if company else "",
            "becsült méret": size or "", "magyar-e": x.get("hungarian", "igen" if have_company else ""),
            "TikTok Shop-jelenlét": tts, "tulajdonos/döntéshozó (név + forrás)": owner,
            "marketingvezető (név + forrás)": x.get("marketing", ""),
            "LinkedIn cég-URL": x.get("linkedin", soc.get("linkedin", "")), "Meta Ad Library-link": meta,
            "forrás": " | ".join(dict.fromkeys(sources + x.get("sources", []))), "forrás dátuma": r.get("checked", ""),
            "státusz": status,
        }
        by_group.setdefault(r["group"], []).append(row)
    seen_sites = {host(r["website"]) for r in recs}
    for k, v in extra.items():
        if v.get("skip") and v.get("group") and host(k) not in seen_sites:
            skipped.append((v["group"], v.get("brand", ""), k, v["skip"]))
    for g, rows in by_group.items():
        with open(f"{out_dir}/{FILES[g]}", "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, COLS)
            w.writeheader()
            w.writerows(rows)
        print(g, len(rows))
    with open(f"{out_dir}/kihagyott.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["termékcsoport", "márka", "weboldal", "kihagyás oka"])
        w.writerows(skipped)
    print("skipped", len(skipped))


if __name__ == "__main__":
    main()
