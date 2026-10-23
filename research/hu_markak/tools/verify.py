"""Verify Hungarian brand candidates from public pages only.

usage: python3 -I verify.py candidates.json out.json
candidates.json: [{"group": "...", "brand": "...", "website": "https://...", "company": optional}]

Per brand: homepage + impresszum/ÁSZF/kapcsolat (company name, Kft/Bt, TikTok/LinkedIn/Facebook links),
nemzeticegtar.hu public company page (revenue, headcount, signatory), public TikTok profile (ttSeller flag).
Stops using a source as soon as it returns a captcha/403/429 and records that instead.
"""
import html
import json
import re
import sys
import time
import urllib.parse

import requests

UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120 Safari/537.36",
      "Accept-Language": "hu-HU,hu;q=0.9"}
BLOCKED = {}
TODAY = time.strftime("%Y-%m-%d")


def get(url, **kw):
    try:
        return requests.get(url, headers=UA, timeout=25, **kw)
    except Exception:
        return None


def text_of(h):
    h = re.sub(r"<script.*?</script>|<style.*?</style>|<noscript.*?</noscript>", " ", h, flags=re.S | re.I)
    t = html.unescape(re.sub(r"<[^>]+>", " | ", h))
    t = re.sub(r"\s+", " ", t)
    return re.sub(r"(\|\s*)+", "| ", t)


COMPANY_RE = re.compile(
    r"([A-ZÁÉÍÓÖŐÚÜŰ0-9][\w&.\-’' ÁÉÍÓÖŐÚÜŰáéíóöőúüű]{1,60}?\s(?:Korlátolt Felelősségű Társaság|Betéti Társaság|Kft\.?|Bt\.?|Zrt\.?|Nyrt\.?|Kereskedelmi és Szolgáltató Kft\.?))")
CEGJ_RE = re.compile(r"\b(\d{2}[-\s]\d{2}[-\s]\d{6})\b")
SUBWORDS = ["impresszum", "impressum", "aszf", "általános szerződési", "altalanos-szerzodesi", "terms",
            "kapcsolat", "rolunk", "rólunk", "about", "jogi-nyilatkozat", "adatkezel", "szallitasi"]


def site_pages(website):
    pages = {}
    r = get(website)
    if r is None or r.status_code >= 400:
        return pages, (r.status_code if r is not None else "nem elérhető")
    pages[r.url] = r.text
    links = re.findall(r'href="([^"#]+)"', r.text)
    seen = []
    for l in links:
        u = urllib.parse.urljoin(r.url, html.unescape(l))
        low = urllib.parse.unquote(u).lower()
        if urllib.parse.urlparse(u).netloc.replace("www.", "") != urllib.parse.urlparse(r.url).netloc.replace("www.", ""):
            continue
        if any(w in low for w in SUBWORDS) and u not in seen:
            seen.append(u)
    rank = lambda u: next((i for i, w in enumerate(SUBWORDS) if w in urllib.parse.unquote(u).lower()), 99)
    for u in sorted(seen, key=rank)[:7]:
        if True:
            rr = get(u)
            if rr is not None and rr.status_code < 400:
                pages[rr.url] = rr.text
    return pages, r.status_code


def find_company(pages):
    best = None
    for url, h in pages.items():
        t = text_of(h)
        for m in COMPANY_RE.finditer(t):
            name = m.group(1).strip(" |,.")
            name = re.sub(r"^(?:(?:Üzemeltető|Szolgáltató|Cégnév|Név|Neve|cég|Cég)\s*[:\-]?\s*|(?:A|Az)\s+)", "", name)
            name = re.sub(r"^(?:©|Copyright|\(c\))?\s*(?:\d{4}(?:\s*[-–]\s*\d{4})?)?\s*[-–|,]?\s*", "", name).strip()
            if len(name) < 5 or re.search(r"Facebook|Google|Meta|Shopify|UNAS|Shoprenter|GLS|Magyar Posta|Foxpost|"
                                          r"Packeta|Barion|OTP|SimplePay|Simple|DPD|Expressone|Sprinter|Billingo|"
                                          r"Számlázz|KBOSS|Mailchimp|Wix|WooCommerce|Netlify|Rackhost|Tárhely|"
                                          r"MPL|Unas|ShopRenter|Klaviyo|Hotjar|Microsoft|Viva|Webmark|Innocode|"
                                          r"Árukereső|Arukereso|Compaya|NETRISE|Dotroll|Websupport|Szamlazz|"
                                          r"Pénzügyi|PayPal|Stripe|Revolut|Wise|Holding Zrt|Nemzeti",
                                          name, re.I):
                continue
            ctx = t[max(0, m.start() - 200):m.end() + 300]
            near = t[max(0, m.start() - 120):m.start()]
            if re.search(r"tárhely|hosting|adatfeldolgoz|futár|könyvel|webfejleszt|fejlesztő|kivitelez", near, re.I):
                continue
            score = 0
            if re.search(r"üzemeltet|szolgáltató|cégnév|impresszum|eladó|forgalmaz|székhely|adószám", ctx, re.I):
                score += 2
            if CEGJ_RE.search(ctx):
                score += 2
            if "impress" in url.lower() or "aszf" in url.lower():
                score += 1
            if best is None or score > best[0]:
                best = (score, name, url, ctx.strip()[:300])
    return best


def socials(pages):
    allh = " ".join(pages.values())
    out = {}
    m = re.findall(r"tiktok\.com/(@[\w.\-]+)", allh)
    out["tiktok"] = m[0] if m else ""
    m = re.findall(r"(https?://(?:[a-z]{2,3}\.)?linkedin\.com/company/[\w\-%.]+)", allh)
    out["linkedin"] = m[0].rstrip("/.") if m else ""
    m = [x for x in re.findall(r"facebook\.com/([\w.\-]+)", allh)
         if x.lower() not in ("sharer", "sharer.php", "tr", "plugins", "dialog", "share", "groups", "profile.php", "events", "watch", "help")]
    out["facebook"] = m[0] if m else ""
    m = re.findall(r"instagram\.com/([\w.\-]+)", allh)
    m = [x for x in m if x.lower() not in ("p", "explore", "reel")]
    out["instagram"] = m[0] if m else ""
    out["tiktok_shop_link"] = bool(re.search(r"shop\.tiktok\.com|tiktok\.com/shop|vt\.tiktok\.com", allh))
    return out


def nct_lookup(company, session):
    if "nemzeticegtar" in BLOCKED:
        return {"error": BLOCKED["nemzeticegtar"]}
    try:
        h = session.get("https://www.nemzeticegtar.hu/", headers=UA, timeout=30).text
        tok = re.search(r'name="csrf_nct_name" value="([^"]+)"', h).group(1)
        q = re.sub(r"\s(?:Korlátolt Felelősségű Társaság|Kft\.?|Bt\.?|Betéti Társaság|Zrt\.?)$", "", company).strip()
        r = session.post("https://www.nemzeticegtar.hu/nemzeticegtar/lista",
                         data={"csrf_nct_name": tok, "search": q, "honeypot": ""}, headers=UA, timeout=40)
    except Exception as e:
        return {"error": f"hiba: {e.__class__.__name__}"}
    if r.status_code in (403, 429) or re.search(r"captcha|robot", r.text[:3000], re.I):
        BLOCKED["nemzeticegtar"] = f"blokkolt ({r.status_code})"
        return {"error": BLOCKED["nemzeticegtar"]}
    url = r.url
    if "/nemzeticegtar/lista" in url:
        cands = re.findall(r'href="(https://www\.nemzeticegtar\.hu/[^"]+-[a-z]\d+\.html)"[^>]*>(.*?)</a>', r.text, re.S)
        if not cands:
            return {"error": "nincs találat"}
        # pick the first result whose name starts with the query
        pick = None
        for u, n in cands:
            n = text_of(n).strip(" |")
            if n.lower().startswith(q.lower()[:12]):
                pick = u
                break
        if not pick:
            return {"error": "nincs egyértelmű találat", "candidates": [text_of(n).strip(" |") for _, n in cands[:5]]}
        r = session.get(pick, headers=UA, timeout=40)
        url = r.url
    t = text_of(r.text)
    d = {"url": url}
    for key, pat in [("name", r"Rövidített név \| ([^|]+)"), ("full_name", r"Teljes név \| ([^|]+)"),
                     ("revenue", r"nettó árbevétel \| \((\d{4})\. évi adatok\) \| ([^|]+)"),
                     ("headcount", r"létszám \| ([^|]+)"), ("founded", r"Alapítás éve \| (\d{4})"),
                     ("seat", r"székhely \| (\d{4} [^,|]+)"), ("activity", r"Főtevékenység \| ([^|]+)")]:
        m = re.search(pat, t)
        if m:
            d[key] = " ".join(m.groups()).strip() if key == "revenue" else m.group(1).strip()
    m = re.search(r"Cégjegyzésre jogosultak \| (.*?)\| üzletkötési", t)
    if m:
        people = []
        for pm in re.finditer(r"([A-ZÁÉÍÓÖŐÚÜŰ][^|()]{3,60}?) \| (?:\(an: [^)]*\) )?([a-záéíóöőúüű ]*(?:ügyvezető|vezérigazgató|cégvezető|beltag|igazgatósági tag|vezető tisztségviselő)[^|(]*\([^)]*\)|[a-záéíóöőúüű ]*(?:ügyvezető|vezérigazgató|cégvezető|beltag|igazgató)[^|]*)",
                              m.group(1)):
            people.append(f"{pm.group(1).strip()} ({pm.group(2).strip().split(' (')[0]})")
        d["signatories"] = people
    return d


def tiktok_check(handle):
    if not handle:
        return None
    if "tiktok" in BLOCKED:
        return {"error": BLOCKED["tiktok"]}
    r = get(f"https://www.tiktok.com/{handle}")
    if r is None:
        return {"error": "nem elérhető"}
    if r.status_code in (403, 429):
        BLOCKED["tiktok"] = f"blokkolt ({r.status_code})"
        return {"error": BLOCKED["tiktok"]}
    m = re.search(r'<script id="__UNIVERSAL_DATA_FOR_REHYDRATION__"[^>]*>(.*?)</script>', r.text, re.S)
    try:
        info = json.loads(m.group(1))["__DEFAULT_SCOPE__"]["webapp.user-detail"]["userInfo"]
        user = info["user"]
        bio = user.get("signature", "") + " " + json.dumps(user.get("bioLink", ""))
        return {"seller": bool(user.get("ttSeller")) or "shop.tiktok.com" in bio,
                "followers": info.get("stats", {}).get("followerCount"), "url": f"https://www.tiktok.com/{handle}"}
    except Exception:
        return {"error": "profil nem olvasható (JS/bot-szűrés)"}


def main():
    cands = json.load(open(sys.argv[1]))
    out_path = sys.argv[2]
    try:
        done = {d["website"]: d for d in json.load(open(out_path))}
    except Exception:
        done = {}
    s = requests.Session()
    for c in cands:
        if c["website"] in done:
            continue
        pages, code = site_pages(c["website"])
        rec = dict(c, checked=TODAY, http=code, pages=list(pages)[:8])
        best = find_company(pages) if pages else None
        if c.get("company"):
            rec["company"] = c["company"]
            rec["company_src"] = c.get("company_src", "")
        elif best:
            rec["company"], rec["company_src"], rec["company_ctx"] = best[1], best[2], best[3]
        rec["social"] = socials(pages) if pages else {}
        if c.get("tiktok"):
            rec["social"]["tiktok"] = c["tiktok"]
        if rec.get("company"):
            rec["nct"] = nct_lookup(rec["company"], s)
            time.sleep(2)
        rec["tt"] = tiktok_check(rec["social"].get("tiktok", ""))
        done[c["website"]] = rec
        json.dump(list(done.values()), open(out_path, "w"), ensure_ascii=False, indent=1)
        print(c["brand"], "|", rec.get("company"), "|", (rec.get("nct") or {}).get("revenue"),
              (rec.get("nct") or {}).get("headcount"), (rec.get("nct") or {}).get("signatories"),
              (rec.get("nct") or {}).get("error"), "| tt:", rec["social"].get("tiktok"), rec.get("tt"), flush=True)
        time.sleep(1.5)
    print("BLOCKED:", BLOCKED)


if __name__ == "__main__":
    main()
