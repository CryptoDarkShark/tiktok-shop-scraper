"""Hungarian brand outreach pipeline (see hu-pipeline-prompt.md).

Steps implemented: source (SerpAPI Google HU), filter, TikTok Shop check,
enrich (homepage / impresszum / aszf / kapcsolat / rolunk), output to
brands.xlsx + review.xlsx. Meta Ad Library sourcing is not wired in yet,
so "Advertised Product" stays empty. Nothing here sends email.

Usage:
    python pipeline/hu_pipeline.py source      # SerpAPI -> data/candidates.json
    python pipeline/hu_pipeline.py enrich      # fetch sites -> data/enriched.json
    python pipeline/hu_pipeline.py output --limit 50   # applies pipeline/curation.json
"""
import argparse
import datetime as dt
import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")

# Category -> search queries. Phrased to surface small brands selling their
# own products rather than resellers.
QUERIES = {
    "Bőrápolás": ["magyar natúr kozmetikum márka webshop", "magyar bőrápolási márka saját termékek"],
    "Kozmetikum": ["magyar kozmetikai márka webáruház", "kézműves magyar kozmetikum webshop"],
    "Étrend-kiegészítő": ["magyar étrend-kiegészítő márka webshop", "magyar gyártó étrend-kiegészítő webáruház"],
    "Vitamin": ["magyar vitamin márka webshop"],
    "Fitnesz": ["magyar fitnesz ruházat márka webshop", "magyar sporttáplálék márka webshop"],
    "Kisállat": ["magyar kutyás termékek márka webshop", "magyar kisállat termék gyártó webshop"],
    "Lakberendezés": ["magyar lakberendezési márka webshop", "magyar design lakásdekor webshop"],
    "Divat": ["magyar divatmárka webshop", "magyar tervező ruha márka webshop"],
    "Ékszer": ["magyar ékszer márka webshop", "kézműves ékszer márka magyar webshop"],
    "Baba": ["magyar babatermék márka webshop", "magyar babaruha márka webshop"],
    "Játék": ["magyar fajáték márka webshop", "magyar játék márka webshop"],
    "Sport": ["magyar sportruházat márka webshop"],
}
# Second pass: phrasing that favours makers over resellers.
QUERIES_OWN = {
    "Bőrápolás": ["kézműves szappan saját gyártás webshop", "saját gyártású natúrkozmetikum webshop"],
    "Lakberendezés": ["magyar gyártású illatgyertya webshop", "magyar kézműves kerámia webshop", "magyar ágynemű márka webshop"],
    "Divat": ["magyar tervezésű táska webshop", "magyar fürdőruha márka webshop", "magyar cipőmárka webshop"],
    "Kisállat": ["kutyahám saját gyártás magyar webshop"],
    "Baba": ["magyar gyerekruha márka saját tervezés webshop"],
}

PAGES_PER_QUERY = 2

# Marketplaces, big retailers, multinationals, media, social: never targets.
BLOCKED_DOMAINS = {
    "arukereso.hu", "argep.hu", "emag.hu", "notino.hu", "douglas.hu", "rossmann.hu",
    "dm.hu", "pepita.hu", "vatera.hu", "jofogas.hu", "szallas.hu", "alza.hu",
    "decathlon.hu", "zalando.hu", "aboutyou.hu", "answear.hu", "reserved.com",
    "hm.com", "ikea.com", "jysk.hu", "pepco.hu", "tesco.hu", "spar.hu", "auchan.hu",
    "benu.hu", "pingvinpatika.hu", "herbaline.hu", "szepsegcenter.hu", "cosibella.hu",
    "koreashop.hu", "skinshop.hu", "bioszeretet.hu", "biobolt.eu", "gymbeam.hu",
    "builder.hu", "myprotein.hu", "scitec.hu", "biotechusa.hu", "vitaking.hu",
    "tchibo.hu", "lidl.hu", "aldi.hu", "mediamarkt.hu", "extreme-digital.hu",
    "bonprix.hu", "shein.com", "temu.com", "amazon.com", "ebay.com", "etsy.com",
    "facebook.com", "instagram.com", "tiktok.com", "youtube.com", "linkedin.com",
    "pinterest.com", "reddit.com", "wikipedia.org", "google.com", "index.hu",
    "telex.hu", "444.hu", "hvg.hu", "nlc.hu", "femina.hu", "wmn.hu", "divany.hu",
    "blikk.hu", "origo.hu", "portfolio.hu", "forbes.hu", "kreativ.hu",
    "startlap.hu", "koponyeg.hu", "glamour.hu", "elle.hu", "marieclaire.hu",
    "hellobaby.hu", "kiskegyed.hu", "cosmopolitan.hu", "joy.hu", "noizz.hu",
    "pandora.net", "swarovski.com", "tchibo.com", "kika.hu", "praktiker.hu",
    "obi.hu", "fressnapf.hu", "zooplus.hu", "maxizoo.hu", "bestbyte.hu",
    "regio.hu", "jatekshop.eu", "brendon.hu", "baby-nest.hu", "libri.hu",
    "bookline.hu", "muller.hu", "hervis.hu", "intersport.hu", "sportisimo.hu",
    "humanic.net", "deichmann.com", "ccc.eu", "orsay.com", "mohito.com",
    "sinsay.com", "housebrand.com", "cropp.com", "zara.com", "mango.com",
    "shoprenter.hu", "unas.hu", "wordpress.com", "blogspot.com", "gov.hu",
    "egeszsegkalauz.hu", "hazipatika.com", "webbeteg.hu",
    "magyartermek.hu", "vatera.hu", "meska.hu", "szimpla.hu", "bdk.hu",
}
BLOCKED_TLDS = (".gov", ".edu")

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
GENERIC_PREFIXES = ("info", "hello", "ugyfelszolgalat", "ügyfélszolgálat", "shop",
                    "webshop", "rendeles", "order", "contact", "kapcsolat", "office",
                    "iroda", "bolt", "support", "sales", "customerservice", "mail")
FOUNDER_RE = re.compile(
    r"(?:alapító(?:ja|nk)?|tulajdonos(?:a)?|ügyvezető(?:je)?|founder)\s*[:\-–,]?\s*"
    r"([A-ZÁÉÍÓÖŐÚÜŰ][a-záéíóöőúüű]+)\s+([A-ZÁÉÍÓÖŐÚÜŰ][a-záéíóöőúüű]+)",
)
SUBPAGES = ["", "impresszum", "aszf", "kapcsolat", "rolunk"]
SOCIAL_SKIP = {"p", "reel", "explore", "share", "sharer", "intent", "tr", "plugins",
               "stories", "accounts", "about", "legal", "discover", "tag"}


def domain_of(url):
    host = urlparse(url).netloc.lower()
    return host[4:] if host.startswith("www.") else host


def is_blocked(domain):
    if not domain.endswith(".hu") and not domain.endswith(".com") and not domain.endswith(".eu"):
        return True
    if domain.endswith(BLOCKED_TLDS):
        return True
    return any(domain == b or domain.endswith("." + b) for b in BLOCKED_DOMAINS)


# ---------------------------------------------------------------- source

def serp(query, start):
    key = os.environ.get("SERPAPI_KEY")
    if not key:
        sys.exit("SERPAPI_KEY is not set")
    r = requests.get("https://serpapi.com/search.json", params={
        "q": query, "gl": "hu", "hl": "hu", "google_domain": "google.hu",
        "start": start, "api_key": key,
    }, timeout=60)
    r.raise_for_status()
    d = r.json()
    if d.get("error"):
        raise RuntimeError(d["error"])
    return d.get("organic_results", [])


def cmd_source(args):
    DATA.mkdir(exist_ok=True)
    out = DATA / "candidates.json"
    cands = json.loads(out.read_text()) if out.exists() else {}
    done = {(c["query"], c["start"]) for c in cands.get("_searches", [])}
    searches = cands.pop("_searches", [])
    for cat, qs in (QUERIES_OWN if args.own else QUERIES).items():
        for q in qs:
            for page in range(PAGES_PER_QUERY):
                start = page * 10
                if (q, start) in done:
                    continue
                try:
                    results = serp(q, start)
                except Exception as e:  # keep what we have
                    print(f"search failed: {q!r} {start}: {e}")
                    continue
                searches.append({"query": q, "start": start, "n": len(results)})
                for r in results:
                    d = domain_of(r.get("link", ""))
                    if not d or d in cands:
                        continue
                    cands[d] = {"domain": d, "url": f"https://{urlparse(r['link']).netloc}/",
                                "title": r.get("title", ""), "snippet": r.get("snippet", ""),
                                "category": cat, "query": q, "source": "SerpAPI"}
                print(f"{cat:18} {q!r} p{page + 1}: {len(results)} results, {len(cands)} unique domains")
                time.sleep(0.5)
    cands["_searches"] = searches
    out.write_text(json.dumps(cands, ensure_ascii=False, indent=1))
    print(f"{len(searches)} searches, {len(cands) - 1} unique domains -> {out}")


# ---------------------------------------------------------------- enrich

def fetch(url):
    try:
        r = requests.get(url, headers={"User-Agent": UA, "Accept-Language": "hu-HU,hu;q=0.9"},
                         timeout=15, allow_redirects=True)
        if r.status_code == 200 and "html" in r.headers.get("content-type", ""):
            r.encoding = r.apparent_encoding if r.encoding in (None, "ISO-8859-1") else r.encoding
            return r.url, r.text
    except requests.RequestException:
        pass
    return None, None


def find_links(soup, base, words):
    hits = []
    for a in soup.find_all("a", href=True):
        text = (a.get_text(" ", strip=True) + " " + a["href"]).lower()
        if any(w in text for w in words):
            u = urljoin(base, a["href"])
            if domain_of(u) == domain_of(base) and u not in hits:
                hits.append(u)
    return hits[:3]


def pick_email(emails, domain):
    emails = [e.lower().strip(".") for e in emails]
    emails = [e for e in emails if not re.search(r"\.(png|jpe?g|gif|webp|svg)$", e)
              and "sentry" not in e and "example" not in e and "wixpress" not in e
              and "domain.com" not in e and "email.com" not in e]
    if not emails:
        return ""
    root = domain.split(".")[-2]

    def score(e):
        local, _, host = e.partition("@")
        s = 0
        if root in host:
            s += 10
        if local.startswith(GENERIC_PREFIXES):
            s += 5
        if "nav.gov" in host or "gov.hu" in host or "bekeltetes" in host or "fogyaszto" in host:
            s -= 50
        return s

    best = max(emails, key=score)
    return best if score(best) > -10 else ""


def handle(soup, host):
    for a in soup.find_all("a", href=True):
        u = urlparse(a["href"])
        if host in u.netloc:
            parts = [p for p in u.path.split("/") if p]
            if parts and parts[0].lstrip("@").lower() not in SOCIAL_SKIP:
                return "@" + parts[0].lstrip("@")
    return ""


COMPANY_LABELED_RE = re.compile(
    r"(?:Cégnév|Cég neve|Üzemeltető|Szolgáltató neve|Szolgáltató|Tulajdonos|Kereskedő|Eladó|Vállalkozás neve|Név)"
    r"\s*[:\-–]?\s*((?:[\w\.\-&'’+]+\s){0,6}?(?:Kft|Bt|Zrt|Kkt|Nonprofit Kft)\.?)",
)
COMPANY_BARE_RE = re.compile(r"((?:[A-ZÁÉÍÓÖŐÚÜŰ0-9][\w\.\-&'’+]*\s){1,4}(?:Kft|Bt|Zrt|Kkt)\.?)")
STREET_WORDS = r"(?:utca|u\.|út|útja|tér|krt|körút|köz|sor|sétány|dűlő|park|fasor|lakótelep|hrsz)"
CITY_RE = re.compile(r"\b[1-9]\d{3}\s*,?\s*([A-ZÁÉÍÓÖŐÚÜŰ][a-záéíóöőúüű]+(?:-[a-záéíóöőúüűA-ZÁÉÍÓÖŐÚÜŰ]+)?)\s*,?\s*"
                     r"(?:[\wÁÉÍÓÖŐÚÜŰáéíóöőúüű\.\- ]{1,40}?)" + STREET_WORDS)
BAD_COMPANY_WORDS = {"a", "az", "és", "the", "cégnév", "név", "neve", "szolgáltató", "üzemeltető", "eladó"}


def extract_company(blob):
    for rx in (COMPANY_LABELED_RE, COMPANY_BARE_RE):
        found = [m.strip() for m in rx.findall(blob)]
        found = [f for f in found if f.split()[0].lower() not in BAD_COMPANY_WORDS and len(f) < 60]
        if found:
            return max(set(found), key=found.count)
    return ""


def extract_city(blob):
    m = re.search(r"(?:Székhely|Cím|Telephely)\s*[:\-]?\s*" + CITY_RE.pattern, blob)
    m = m or CITY_RE.search(blob)
    return m.group(1) if m else ""


def enrich_one(c):
    base = c["url"]
    pages, texts, soups = {}, [], []
    final, html = fetch(base)
    if not html:
        return {**c, "status": "unreachable"}
    base = f"{urlparse(final).scheme}://{urlparse(final).netloc}/"
    home = BeautifulSoup(html, "html.parser")
    pages["home"] = final
    soups.append(home)
    texts.append(home.get_text(" ", strip=True))
    extra = find_links(home, base, ["impresszum", "impressum", "aszf", "általános szerződési",
                                    "kapcsolat", "rolunk", "rólunk"])
    for sp in SUBPAGES[1:]:
        extra.append(urljoin(base, sp))
    seen = {final}
    for u in extra:
        if u in seen or len(seen) > 8:
            continue
        seen.add(u)
        f, h = fetch(u)
        if h:
            s = BeautifulSoup(h, "html.parser")
            soups.append(s)
            texts.append(s.get_text(" ", strip=True))
            pages[u] = f
    blob = " \n ".join(texts)
    raw_html = html + "".join(str(s) for s in soups[1:])

    blob_n = re.sub(r"\s*(?:\[@\]|\(@\)|\(kukac\)|\[kukac\]|\s kukac \s)\s*", "@", blob)
    emails = set(EMAIL_RE.findall(blob_n))
    for s in soups:
        for a in s.select("a[href^=mailto]"):
            emails.add(a["href"][7:].split("?")[0])
    return_company = extract_company(blob)
    city = extract_city(blob)
    first = ""
    fm = FOUNDER_RE.search(blob)
    if fm:
        # Hungarian order is family name first: take the second token.
        first = fm.group(2)

    og = home.find("meta", property="og:site_name")
    brand = og["content"].strip() if og and og.get("content") else ""
    if not brand or len(brand) > 30 or brand.lower() in {"webshop", "home", "főoldal", "kezdőlap"}:
        brand = c["domain"].rsplit(".", 1)[0].replace("-", " ").title()

    tts = ("shop.tiktok.com" in raw_html or "tiktokshop" in raw_html.lower().replace(" ", "")
           or "vt.tokopedia" in raw_html)
    return {
        **c, "status": "ok", "brand": brand, "company": return_company, "website": base,
        "email": pick_email(emails, c["domain"]), "city": city, "first_name": first,
        "instagram": handle(home, "instagram.com") or next((handle(s, "instagram.com") for s in soups if handle(s, "instagram.com")), ""),
        "tiktok": handle(home, "tiktok.com") or next((handle(s, "tiktok.com") for s in soups if handle(s, "tiktok.com")), ""),
        "tiktok_shop": "on TikTok Shop" if tts else "unverified",
        "has_impresszum": any("impress" in k for k in pages),
        "text_len": len(blob), "pages": list(pages.values()),
        "reseller_hint": sum(blob.lower().count(w) for w in ["márkáink", "márkák", "forgalmazott márkák", "brands"]),
    }


def cmd_enrich(args):
    cands = json.loads((DATA / "candidates.json").read_text())
    cands.pop("_searches", None)
    prev = json.loads((DATA / "enriched.json").read_text()) if (DATA / "enriched.json").exists() else []
    known = {r["domain"] for r in prev}
    todo = [c for d, c in cands.items() if not is_blocked(d) and d not in known]
    print(f"{len(cands)} domains, {len(todo)} new after blocklist; enriching...")
    with ThreadPoolExecutor(max_workers=12) as ex:
        res = prev + list(ex.map(enrich_one, todo))
    (DATA / "enriched.json").write_text(json.dumps(res, ensure_ascii=False, indent=1))
    ok = [r for r in res if r["status"] == "ok"]
    print(f"reachable {len(ok)}, with email {sum(1 for r in ok if r['email'])}")


# ---------------------------------------------------------------- output

COLUMNS = ["Brand", "Company", "Website", "Email", "City", "Category", "Advertised Product",
           "Instagram", "TikTok", "First Name", "TikTok Shop Status", "Date Found"]


def row(r, today):
    return [r["brand"], r["company"], r["website"], r["email"], r["city"], r["category"], "",
            r["instagram"], r["tiktok"], r["first_name"], r["tiktok_shop"], today]


def write_xlsx(path, rows, extra_cols=()):
    from openpyxl import Workbook
    from openpyxl.styles import Font
    wb = Workbook()
    ws = wb.active
    ws.title = "Brands"
    ws.append(COLUMNS + list(extra_cols))
    for c in ws[1]:
        c.font = Font(bold=True)
    for r in rows:
        ws.append(r)
    for col in ws.columns:
        ws.column_dimensions[col[0].column_letter].width = min(45, max(12, *(len(str(c.value or "")) for c in col)) + 2)
    ws.freeze_panes = "A2"
    wb.save(path)


def tiktok_profile(handle):
    """Return (is_seller, bio) from a public TikTok profile, or (None, "") if unreadable."""
    try:
        r = requests.get(f"https://www.tiktok.com/{handle}", headers={"User-Agent": UA}, timeout=20)
        m = re.search(r'<script id="__UNIVERSAL_DATA_FOR_REHYDRATION__"[^>]*>(.*?)</script>', r.text, re.S)
        user = json.loads(m.group(1))["__DEFAULT_SCOPE__"]["webapp.user-detail"]["userInfo"]["user"]
        bio = user.get("signature", "") + " " + json.dumps(user.get("bioLink", ""))
        return bool(user.get("ttSeller")) or "shop.tiktok.com" in bio, bio
    except Exception:
        return None, ""


def tiktok_shop_status(r):
    if r["tiktok_shop"] == "on TikTok Shop":
        return "on TikTok Shop"
    if r["tiktok"]:
        seller, _ = tiktok_profile(r["tiktok"])
        if seller:
            return "on TikTok Shop"
    # No evidence either way: never claim "not on TikTok Shop".
    return "unverified"


def cmd_output(args):
    res = {r["domain"]: r for r in json.loads((DATA / "enriched.json").read_text())}
    cur = json.loads((ROOT / "pipeline" / "curation.json").read_text())
    today = dt.date.today().isoformat()
    kept, review, dropped = [], [], {}

    def drop(reason):
        dropped[reason] = dropped.get(reason, 0) + 1

    for d, r in res.items():
        if d in cur["keep"]:
            continue
        if d in cur["review"] and r["status"] == "ok" and r["email"]:
            review.append({**r, "review_reason": cur["review"][d]})
        elif r["status"] != "ok":
            drop("site unreachable")
        elif not r["email"]:
            drop("no email found")
        else:
            drop("not an own-brand small webshop (reseller, marketplace, media, big or foreign brand)")

    candidates = [{**res[d], **fields} for d, fields in cur["keep"].items() if d in res]
    with ThreadPoolExecutor(max_workers=6) as ex:
        statuses = list(ex.map(tiktok_shop_status, candidates))
    for r, st in zip(candidates, statuses):
        r["tiktok_shop"] = st
        if st == "on TikTok Shop":
            drop("already on TikTok Shop")
        elif len(kept) < args.limit:
            kept.append(r)
        else:
            review.append({**r, "review_reason": f"verified, outside this {args.limit}-brand run"})

    write_xlsx(ROOT / "brands.xlsx", [row(r, today) for r in kept])
    write_xlsx(ROOT / "review.xlsx", [row(r, today) + [r["review_reason"]] for r in review], ["Review Reason"])
    total = len(json.loads((DATA / "candidates.json").read_text())) - 1
    print(f"found: {total} unique domains")
    print(f"filtered out: {total - len(res)} blocklisted (marketplaces, big retailers, media, social)")
    for k, v in sorted(dropped.items(), key=lambda x: -x[1]):
        print(f"filtered out: {v} {k}")
    print(f"review.xlsx: {len(review)}")
    print(f"kept: {len(kept)} -> brands.xlsx")


def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    src = sub.add_parser("source")
    src.add_argument("--own", action="store_true", help="run the second, maker-focused query set")
    sub.add_parser("enrich")
    o = sub.add_parser("output")
    o.add_argument("--limit", type=int, default=50)
    a = p.parse_args()
    {"source": cmd_source, "enrich": cmd_enrich, "output": cmd_output}[a.cmd](a)


if __name__ == "__main__":
    main()
