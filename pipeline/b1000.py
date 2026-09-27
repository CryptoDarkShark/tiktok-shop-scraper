"""brands_1000.xlsx: a long list of small/mid DTC brands for future outreach (no emails are sent from it).

Free sources only. Stages (all cached in data/b1000/, resumable):
    python pipeline/b1000.py names            # brand names from public brand lists / award pages
    python pipeline/b1000.py resolve          # official site for each name (domain guesses verified by page title)
    python pipeline/b1000.py enrich           # brand site pages -> facts
    python pipeline/b1000.py output [--batch N]   # brands_1000.xlsx, sorted by fit score, first N*200 rows

Rules: public pages only; robots.txt checked for Claude's agents on every site; a few seconds between requests
to the same site; skip anything that blocks automated access. Never guess emails or phones; empty cell if unknown.
TikTok and Instagram are not fetched (TikTok's robots.txt disallows Claude's agents; Instagram requires login).
"""
import argparse
import datetime as dt
import json
import random
import re
import socket
import sys
import threading
import time
import unicodedata
import urllib.robotparser as robotparser
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).resolve().parent))
import intl_pipeline as ip  # noqa: E402

D = ip.ROOT / "data" / "b1000"
UA = ip.UA
AGENTS = ("Claude-User", "ClaudeBot", "*")
PER_SITE_DELAY = 2.5
TODAY = dt.date.today().isoformat()

SOURCES = {
    "healf.com brand list": "https://www.healf.com/pages/brands",
    "Cult Beauty brand list": "https://www.cultbeauty.co.uk/brands",
    "Space NK brand list": "https://www.spacenk.com/uk/brands",
    "Lookfantastic brand list": "https://www.lookfantastic.com/brands.list",
    "Escentual brand list": "https://www.escentual.com/brands/",
    "Douglas IT brand list": "https://www.douglas.it/it/brands",
    "Rossmann PL brand list": "https://www.rossmann.pl/marki",
    "Douglas PL brand list": "https://www.douglas.pl/pl/brands",
    "Douglas NL brand list": "https://www.douglas.nl/nl/brands",
    "Douglas ES brand list": "https://www.douglas.es/es/brands",
    "Douglas BE brand list": "https://www.douglas.be/nl/brands",
    "Primor ES brand list": "https://www.primor.eu/marcas",
    "Druni ES brand list": "https://www.druni.es/marcas",
    "Arenal ES brand list": "https://www.arenal.com/marcas",
}

# Household names / big groups / retailers' own labels: never targets.
BIG = {n.strip() for n in """aesop, acqua di parma, clinique, estee lauder, estée lauder, lancome, lancôme, la roche-posay, cerave, the ordinary, nivea, garnier, loreal, l'oreal, l'oréal, maybelline, dior, chanel, gucci, prada, ysl, yves saint laurent, armani, giorgio armani, versace, dolce & gabbana, burberry, hugo boss, calvin klein, tom ford, jo malone, jo malone london, creed, kiehl's, origins, mac, nars, benefit, benefit cosmetics, too faced, urban decay, fenty beauty, charlotte tilbury, rituals, the body shop, neutrogena, olay, dove, vichy, avene, avène, eucerin, bioderma, nuxe, caudalie, clarins, shiseido, sisley, la mer, elemis, dermalogica, kerastase, kérastase, redken, olaplex, ghd, dyson, babyliss, philips, braun, oral-b, colgate, sensodyne, listerine, revlon, rimmel, max factor, bourjois, kiko, kiko milano, essence, catrice, nyx, nyx professional makeup, l'occitane, lush, sol de janeiro, drunk elephant, glossier, tatcha, fresh, sunday riley, paula's choice, the inkey list, revolution, makeup revolution, mac cosmetics, bobbi brown, laura mercier, hourglass, huda beauty, anastasia beverly hills, rare beauty, kylie cosmetics, morphe, e.l.f., elf cosmetics, physicians formula, milani, wet n wild, 4711, davidoff, lacoste, boss, moschino, valentino, givenchy, guerlain, hermes, hermès, marc jacobs, carolina herrera, paco rabanne, rabanne, jean paul gaultier, narciso rodriguez, chloe, chloé, mugler, azzaro, issey miyake, kenzo, abercrombie & fitch, myprotein, optimum nutrition, gymshark, nike, adidas, puma, under armour, lululemon, reebok, asics, new balance, skechers, huel, grenade, bulk, applied nutrition, holland & barrett, vitabiotics, centrum, solgar, nature's bounty, berocca, red bull, monster, innocent, nestle, kellogg's, nature valley, kind, graze, eat natural, cosrx, anua, beauty of joseon, laneige, innisfree, sulwhasoo, some by mi, skin1004, medicube, torriden, round lab, missha, etude, dr. jart+, erborian, aveda, bumble and bumble, moroccanoil, davines, living proof, ouai, briogeo, k18, clarins men, biotherm, helena rubinstein, yves rocher, garnier fructis, pantene, head & shoulders, tresemme, tresemmé, schwarzkopf, wella, john frieda, batiste, simple, cetaphil, aveeno, bioré, biore, st. tropez, st.tropez, bondi sands, tangle teezer, real techniques, ciaté, ciate, sleek, nails inc, barry m, collection, w7, mario badescu, the inkey list, medik8, murad, philosophy, clarisonic, foreo, nuface, currentbody, oskia, 111skin, dr dennis gross, zo skin health, skinceuticals, obagi, peter thomas roth""".split(",")}

# Retailer own labels (drop) and the retailer companies that own them.
OWN_LABELS = {n.strip() for n in """isana, alterra, babydream, rival de loop, sun ozon, domol, enerbio, facelle, prokudent,
profissimo, rossmann, altapharma, jessa, for your beauty, winston, ideenwelt, douglas, douglas collection, douglas essentials,
douglas naturals, douglas make-up, primor, druni, arenal, balea, alverde, ebelin, babylove, sundance, trend it up, s-he, dm,
no7, boots, botanics, boots essentials, superdrug, b. by superdrug, solait, studio london, hebe, cien, lacura, deliplus,
carrefour, hema, kruidvat, etos, trekpleister, rituals, sephora collection, notino, lookfantastic, cult beauty, space nk,
escentual, holland & barrett, h&b, marks & spencer, m&s, tesco, sainsbury's, asda, ocado, aldi, lidl, mercadona, auchan,
leclerc, monoprix, franprix, action""".split(",")}
RETAILER_ENTITIES = r"rossmann|douglas (?:gmbh|polska|italia|spain|nederland|belgium|group)|perfumer[ií]as primor|druni s\.?a|arenal perfumer|dm-drogerie|boots uk|walgreens boots|superdrug stores|hebe sp|a\.s\. watson|jeronimo martins|kruidvat|lidl|aldi|mercadona"
# Multinationals / large groups (drop when named as owner on the brand's own pages).
GROUPS = r"l['’]or[eé]al|unilever|procter\s*&\s*gamble|p&g\b|beiersdorf|\bcoty\b|est[eé]e lauder|henkel|nestl[eé]|danone|shiseido|\bkao\b|johnson\s*&\s*johnson|kenvue|haleon|reckitt|colgate-palmolive|lvmh|\bpuig\b|revlon|amorepacific|pierre fabre|interparfums|natura\s*&\s*co|mondel[eē]z|pepsico|coca-cola|\bmars,? inc|ferrero|general mills|kellanova|kellogg|glanbia|bayer|sanofi|perrigo|wella company|the hut group|\bthg\b|kenvue|ab inbev|diageo|haleon|church\s*&\s*dwight|edgewell|spectrum brands|newell|conair|helen of troy|kkr|l catterton|cvc capital|bain capital|blackstone"
OWNER_CTX = r"(?:owned by|part of|a subsidiary of|subsidiary|member of|a brand of|brand of|division of|belongs to|acquired by|©\s*\d{4})"


CATS = {
    "skincare/haircare/oral care": {
        "skincare": r"serum|moisturi[sz]er|cleanser|face (?:cream|mask|oil)|skin ?care|spf|sunscreen|toner|exfoliat|retinol|niacinamide|eye cream|lip (?:balm|oil|mask)|body (?:butter|lotion|scrub)",
        "haircare": r"hair (?:oil|serum|mask|growth|care)|shampoo|conditioner|scalp|leave-in",
        "oral care": r"whitening strips?|teeth whitening|toothpaste|oral care|mouthwash|tooth powder",
        "self-tan": r"self[- ]tan|tanning (?:mousse|drops|water)|bronz",
    },
    "supplements & gummies": {
        "gummies": r"gumm(?:y|ies)",
        "collagen": r"collagen",
        "sleep": r"sleep|melatonin",
        "magnesium": r"magnesium",
        "hair/skin/nails supplements": r"biotin|hair vitamins|skin supplement",
        "vitamins & supplements": r"supplement|vitamin|capsules|probiotic|ashwagandha|omega",
    },
    "healthy snacks": {
        "freeze-dried": r"freeze[- ]dried",
        "protein snacks": r"protein (?:bar|bites|crisps|chips|cookie|snack)",
        "snacks": r"snacks?|crisps|granola|nut butter|energy balls|popcorn|chocolate",
    },
    "activewear & basics": {
        "leggings & sets": r"leggings|sports bra|matching set|co-?ord|seamless",
        "activewear": r"activewear|gym ?wear|workout|yoga (?:wear|pants)|athleisure",
        "basics": r"basics|essentials tee|bodysuit|loungewear",
    },
    "functional drinks & powders": {
        "electrolytes/hydration": r"electrolyte|hydration (?:powder|tablets|sticks)",
        "greens/superfood powders": r"greens powder|superfood powder|super greens",
        "functional drinks": r"adaptogen|functional (?:drink|soda)|prebiotic (?:soda|drink)|kombucha|energy drink|matcha|mushroom coffee|drink powder",
    },
}
CAT_ORDER = list(CATS)

# Legal-page evidence per country (company registries, VAT ids, legal forms, addresses).
COUNTRY_RX = {
    "United Kingdom": [r"registered in (?:england|scotland|wales|northern ireland)", r"laws of (?:england|scotland|the united kingdom|united kingdom)",
                       r"companies house", r"company (?:registration )?(?:number|no\.?)\s*:?\s*(?:sc|ni)?\d{6,8}", r"\bgb ?\d{3} ?\d{4} ?\d{2}\b",
                       r"\b[a-z]{1,2}\d[a-z\d]? ?\d[a-z]{2}\b.{0,30}(?:united kingdom|uk|england)"],
    "Ireland": [r"registered in (?:the republic of )?ireland", r"laws of ireland", r"\bcro\b.{0,20}\d{5,6}", r"\bie ?\d{7}[a-z]{1,2}\b",
                r"co\. (?:dublin|cork|galway|kerry|wicklow|kildare|meath|limerick|mayo|sligo)", r"dublin \d{1,2}\b.{0,20}ireland"],
    "Poland": [r"\bnip\b\s*:?\s*\d", r"\bkrs\b\s*:?\s*\d", r"\bregon\b", r"sp\. ?z ?o\.? ?o", r"\bpolska\b", r"z siedzibą"],
    "Spain": [r"\bcif\b\s*:?\s*[a-z]-?\d{7,8}", r"\bnif\b\s*:?\s*[a-z]-?\d{7,8}", r"registro mercantil", r"\bs\.l\.u?\b", r"\bespaña\b", r"domicilio social"],
    "France": [r"\bsiret\b", r"\bsiren\b", r"\brcs\b", r"si[èe]ge social", r"\bsas\b|\bsarl\b|\bsasu\b", r"\bfrance\b"],
    "Italy": [r"partita iva|p\.? ?iva", r"\brea\b", r"s\.r\.l\.", r"\bitalia\b", r"sede legale"],
    "Netherlands": [r"\bkvk\b|kamer van koophandel", r"\bb\.v\.", r"\bnederland\b|the netherlands", r"\bnl ?\d{9}b\d{2}\b"],
    "Belgium": [r"\bbe ?0?\d{3}\.?\d{3}\.?\d{3}\b", r"ondernemingsnummer|numéro d'entreprise|kbo|bce", r"\bbelgi[eëu]m?\b|\bbelgique\b"],
    "Germany": [r"handelsregister|amtsgericht", r"\bhrb\b", r"\bgmbh\b", r"ust-?id", r"\bde ?\d{9}\b", r"\bdeutschland\b"],
    "Austria": [r"firmenbuch", r"\bfn ?\d+ ?[a-z]\b", r"\batu ?\d{8}\b", r"\bösterreich\b|\baustria\b"],
}
EMAIL_COUNTRIES = ip.EMAIL_COUNTRIES
PHONE_RX = re.compile(r"(?:tel(?:efon|ephone)?|phone|telefono|téléphone|tél|call us)\.?\s*[:\-]?\s*(\+?\d[\d ()\-.]{7,18}\d)", re.I)
LEGAL_WORDS = ["impressum", "imprint", "legal", "mentions", "aviso", "note-legali", "terms", "conditions", "regulamin",
               "privacy", "polityka", "contact", "kontakt", "contatti", "contacto", "about", "our-story", "o-nas"]


# ---------------------------------------------------------------- polite fetching

_robots, _last, _lock = {}, {}, threading.Lock()


def allowed(url):
    host = urlparse(url).netloc
    if host not in _robots:
        p = robotparser.RobotFileParser()
        try:
            r = requests.get(f"https://{host}/robots.txt", headers={"User-Agent": UA}, timeout=10)
            p.parse(r.text.splitlines() if r.status_code == 200 and "html" not in r.headers.get("content-type", "") else [])
        except requests.RequestException:
            p.parse([])
        _robots[host] = p
    return all(_robots[host].can_fetch(a, url) for a in AGENTS)


def polite_get(url, timeout=15):
    """GET with robots check (Claude agents) and a per-site delay. Returns (final_url, html) or (None, None)."""
    host = urlparse(url).netloc
    if not allowed(url):
        return None, "ROBOTS"
    with _lock:
        wait = _last.get(host, 0) + PER_SITE_DELAY - time.time()
        _last[host] = max(time.time(), _last.get(host, 0) + PER_SITE_DELAY)
    if wait > 0:
        time.sleep(wait)
    try:
        r = requests.get(url, headers={"User-Agent": UA, "Accept-Language": "en,pl;q=0.8"}, timeout=timeout)
        if r.status_code == 200 and "html" in r.headers.get("content-type", ""):
            if r.encoding in (None, "ISO-8859-1"):
                r.encoding = r.apparent_encoding
            return r.url, r.text
        if r.status_code in (401, 403, 429):
            return None, "BLOCKED"
    except requests.RequestException:
        pass
    return None, None


def get_json(url):
    if not allowed(url):
        return None
    host = urlparse(url).netloc
    with _lock:
        wait = _last.get(host, 0) + PER_SITE_DELAY - time.time()
        _last[host] = max(time.time(), _last.get(host, 0) + PER_SITE_DELAY)
    if wait > 0:
        time.sleep(wait)
    try:
        r = requests.get(url, headers={"User-Agent": UA}, timeout=15)
        return r.json() if r.status_code == 200 else None
    except Exception:
        return None


# ---------------------------------------------------------------- names

def clean_name(t):
    t = re.sub(r"\s+(shop now|new|nuovo|nieuw)$", "", t.strip(), flags=re.I)
    return re.sub(r"\s+", " ", t).strip(" -|")


def norm(s):
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]", "", s.lower())


def cmd_names(args):
    D.mkdir(parents=True, exist_ok=True)
    out = ip.load_json(D / "names.json", {})
    for label, url in SOURCES.items():
        if not allowed(url):
            print(f"skip {label}: robots.txt"); continue
        f, h = polite_get(url, timeout=30)
        if not h or h in ("ROBOTS", "BLOCKED"):
            print(f"skip {label}: {h or 'unreachable'}"); continue
        s = BeautifulSoup(h, "html.parser")
        n = 0
        for a in s.find_all("a", href=True):
            href, t = a["href"].lower(), clean_name(a.get_text(" ", strip=True))
            if not (2 <= len(t) <= 40) or re.search(r"shop all|view all|see all|^brands?$|^all ", t, re.I):
                continue
            if re.search(r"/(brands?|merken|marques|marcas?|marki|brand)/[^/?#]+|/collections/[^/?#]+|/b/|brand=|/marka/", href):
                k = norm(t)
                if not k:
                    continue
                if k not in out:
                    out[k] = {"name": t, "source": label, "sources": [label]}
                    n += 1
                elif label not in out[k].setdefault("sources", [out[k]["source"]]):
                    out[k]["sources"].append(label)
        print(f"{label}: +{n}")
    (D / "names.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print(f"{len(out)} unique names")


# ---------------------------------------------------------------- resolve names to official sites

TLDS = [".com", ".co.uk", ".pl", ".es", ".fr", ".it", ".nl", ".be", ".ie", ".eu", ".uk", ".co"]
SUFFIXES = ["", "beauty", "skincare", "skin", "cosmetics", "london", "uk", "official", "nutrition", "health"]


def dns_ok(host):
    try:
        socket.getaddrinfo(host, 443)
        return True
    except OSError:
        return False


def resolve_one(item):
    k, name = item["key"], item["name"]
    slug = norm(name)
    hy = re.sub(r"[^a-z0-9]+", "-", unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()).strip("-")
    tried = []
    for base in dict.fromkeys([slug, hy]):
        for suf in SUFFIXES:
            for tld in TLDS:
                host = f"{base}{suf}{tld}"
                if host in tried or len(tried) > 60:
                    continue
                tried.append(host)
                if not dns_ok(host):
                    continue
                f, h = polite_get(f"https://{host}/", timeout=12)
                if not h or h in ("ROBOTS", "BLOCKED"):
                    continue
                s = BeautifulSoup(h, "html.parser")
                title = (s.title.get_text(" ", strip=True) if s.title else "")
                og = s.find("meta", property="og:site_name")
                label = norm(title + " " + (og.get("content", "") if og else ""))
                parked = re.search(r"domain (?:is )?for sale|buy this domain|parked|godaddy|sedo|hugedomains|aftermarket|dan\.com|domain name is available", h[:5000], re.I)
                if slug and slug in label and not parked:
                    return k, {"domain": ip.domain_of(f), "website": f"https://{urlparse(f).netloc}/", "title": title[:120]}
    return k, None


def cmd_resolve(args):
    names = ip.load_json(D / "names.json", {})
    res = ip.load_json(D / "resolved.json", {})
    skip = existing_domains()
    todo = [{"key": k, **v} for k, v in names.items()
            if k not in res and v["name"].lower() not in BIG and k not in {norm(b) for b in BIG}]
    random.seed(1)
    todo = todo[: args.limit] if args.limit else todo
    print(f"resolving {len(todo)} names ({len(res)} done)")
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        for i, (k, r) in enumerate(ex.map(resolve_one, todo), 1):
            if r and r["domain"] in skip:
                r["skip"] = "already in log.csv or an earlier batch"
            res[k] = r
            if i % 50 == 0:
                (D / "resolved.json").write_text(json.dumps(res, ensure_ascii=False, indent=1))
                print(f"  {i}/{len(todo)} resolved {sum(1 for v in res.values() if v)}")
    (D / "resolved.json").write_text(json.dumps(res, ensure_ascii=False, indent=1))
    print(f"resolved {sum(1 for v in res.values() if v)} / {len(res)}")


def existing_domains():
    cur = ip.load_json(ip.CURATION, {"brands": {}, "skip": {}})
    doms = set(cur["brands"]) | set(cur["skip"]) | {r["domain"] for r in ip.read_log()}
    return doms | {ip.domain_of(b.get("website", "")) for b in cur["brands"].values()}


# ---------------------------------------------------------------- enrich

def text_of(h):
    s = BeautifulSoup(h, "html.parser")
    for t in s(["script", "style", "noscript"]):
        t.decompose()
    return s, re.sub(r"\s+", " ", s.get_text(" "))


def confirm_country(pages):
    """(country, 'url — snippet') if legal/imprint/terms/contact text gives >=2 independent signals, else ('', hint)."""
    best, best_hits = "", []
    for country, rxs in COUNTRY_RX.items():
        hits = []
        for url, t in pages:
            low = t.lower()
            for rx in rxs:
                m = re.search(rx, low)
                if m and rx not in [h[0] for h in hits]:
                    hits.append((rx, url, t[max(0, m.start() - 70): m.end() + 50]))
        if len(hits) > len(best_hits):
            best, best_hits = country, hits
    if len(best_hits) >= 2:
        rx, url, snip = best_hits[0]
        return best, f"{url} — '…{snip.strip()}…'"
    return "", (f"weak signal: {best}" if best else "")


def categorize(text):
    low = text.lower()
    scores = []
    for cat, subs in CATS.items():
        for sub, rx in subs.items():
            n = len(re.findall(rx, low))
            if n:
                scores.append((n, -CAT_ORDER.index(cat), cat, sub))
    if not scores:
        return "", ""
    scores.sort(reverse=True)
    return scores[0][2], scores[0][3]


def best_seller(site, home_html):
    """(name, price, currency, url) of a best-seller / featured product, from the site's own catalogue."""
    for handle in ("best-sellers", "bestsellers", "best-seller", "bestseller", "best-selling", "top-sellers", "shop-all", "all"):
        j = get_json(urljoin(site, f"/collections/{handle}/products.json?limit=5"))
        if j and j.get("products"):
            p = j["products"][0]
            v = p["variants"][0]
            return p["title"], v.get("price"), "", urljoin(site, f"/products/{p['handle']}"), f"{handle} collection"
    s = BeautifulSoup(home_html, "html.parser")
    for tag in s.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(tag.string or "")
        except Exception:
            continue
        for x in (data if isinstance(data, list) else [data]):
            if isinstance(x, dict) and x.get("@type") == "Product":
                off = x.get("offers") or {}
                off = off[0] if isinstance(off, list) and off else off
                return x.get("name", ""), off.get("price", ""), off.get("priceCurrency", ""), x.get("url", site), "homepage product data"
    return "", "", "", "", ""


def currency_of(site_text, url):
    if re.search(r"£\s?\d", site_text):
        return "GBP"
    if re.search(r"\d\s?zł|PLN", site_text):
        return "PLN"
    if re.search(r"€\s?\d|\d\s?€|EUR", site_text):
        return "EUR"
    return {"uk": "GBP", "pl": "PLN"}.get(url.rstrip("/").rsplit(".", 1)[-1], "")


def enrich_brand(item):
    k, r = item
    site = r["website"]
    f, home = polite_get(site)
    if not home or home in ("ROBOTS", "BLOCKED"):
        return k, {"status": home or "unreachable"}
    hs, htext = text_of(home)
    pages, raw = [(f, htext)], home
    for u in ip.find_links(hs, f, LEGAL_WORDS, limit=7):
        f2, h2 = polite_get(u)
        if h2 and h2 not in ("ROBOTS", "BLOCKED"):
            pages.append((f2, text_of(h2)[1]))
            raw += h2
    country, where = confirm_country(pages[1:] or pages)
    blob = " ".join(t for _, t in pages)
    name, price, cur, purl, how = best_seller(site, home)
    cur = cur or currency_of(htext, site)
    cat, sub = categorize(blob + " " + name)
    # emails (published only) with context for named-contact detection
    emails, ctx = set(), {}
    for u, t in pages:
        for e in set(ip.EMAIL_RE.findall(t)) | set(ip.cf_emails(raw)):
            m = ip.EMAIL_RE.search(e)
            if m:
                e = m.group(0).lower().strip(".")
                emails.add(e)
                i = t.lower().find(e)
                ctx.setdefault(e, t[max(0, i - 120): i + 40] if i >= 0 else "")
    ranked = ip.pick_emails(emails, r["domain"], ctx)
    own = [e for e in ranked if r["domain"].split(".")[-2] in e.split("@")[1]]
    mkt = next((e for e in own if ip.email_tier(e, ctx.get(e, "")) <= 2), "")
    gen = next((e for e in own if ip.email_tier(e, ctx.get(e, "")) >= 3), "")
    phone = ""
    for u, t in pages[1:]:
        if re.search(r"contact|kontakt|contatt|legal|impress|mention|aviso|terms", u, re.I):
            m = PHONE_RX.search(t)
            if m:
                phone = re.sub(r"\s+", " ", m.group(1)).strip()
                break
    founder = ""
    for u, t in pages:
        m = re.search(r"(?:(?:co-?)?founder|founded by|założyciel\w*|fondat\w+)[,:]?\s+([A-Z][a-zà-ž]+(?:\s[A-Z][a-zà-ž'\-]+){0,2})", t)
        if m and norm(m.group(1)) not in norm(r.get("title", "")):
            founder = f"{m.group(1)} (founder, {u})"
            break
    li = re.search(r"https?://(?:[a-z]{2,3}\.)?linkedin\.com/in/[\w\-%]+", raw)
    ig = ip.social_handle(hs, "instagram.com")
    tt = ip.social_handle(hs, "tiktok.com")
    tts_links = sorted({m.group(0)[:120] for rx in ip.TTS_PATTERNS for m in rx.finditer(raw)})
    tts_badge = bool(re.search(r"tiktok\s?shop", blob, re.I))
    hu = ip.hu_evidence(r["domain"], [hs], [home], blob)
    legal_blob = " ".join(t for u, t in pages[1:])
    owner = ""
    for m in re.finditer(GROUPS, legal_blob, re.I):
        near = legal_blob[max(0, m.start() - 90): m.end() + 60]
        if re.search(OWNER_CTX, near, re.I) or re.search(r"\b(?:s\.a\.|gmbh|ltd|limited|inc|plc|b\.v\.)", near, re.I):
            owner = f"{m.group(0)}: …{near.strip()}…"
            break
    retailer = ""
    m = re.search(RETAILER_ENTITIES, legal_blob, re.I)
    if m:
        retailer = f"…{legal_blob[max(0, m.start() - 60): m.end() + 60].strip()}…"
    hreflangs = len({l.get("hreflang", "").lower() for l in hs.find_all("link", hreflang=True)} - {"x-default", ""})
    stores = bool(re.search(r"(?:find|visit) (?:a|our|your nearest) (?:store|shop|boutique)|store locator|our stores|nasze sklepy|nuestras tiendas|nos boutiques", blob, re.I))
    return k, {"status": "ok", "country": country, "country_where": where, "category": cat, "subcategory": sub,
               "product": name, "price": price, "currency": cur, "product_url": purl, "product_how": how,
               "marketing_email": mkt, "general_email": gen, "phone": phone, "contact": founder,
               "linkedin": li.group(0) if li else "", "instagram": ig, "tiktok": tt,
               "tts": "on" if (tts_links or tts_badge) else "unverified", "tts_evidence": (tts_links or [""])[0] or
               ("'TikTok Shop' mentioned on site" if tts_badge else ""),
               "hu": "yes" if hu else "unknown", "hu_evidence": (hu or [""])[0][:120],
               "owner": owner[:220], "retailer_entity": retailer[:200], "hreflangs": hreflangs, "stores": stores,
               "title": r.get("title", ""), "desc": (hs.find("meta", attrs={"name": "description"}) or {}).get("content", "")[:200]
               if hs.find("meta", attrs={"name": "description"}) else ""}


def cmd_enrich(args):
    res = ip.load_json(D / "resolved.json", {})
    out = ip.load_json(D / "enriched.json", {})
    # (re)do anything not yet enriched with the ownership/size fields
    todo = [(k, r) for k, r in res.items() if r and not r.get("skip")
            and (k not in out or (out[k].get("status") == "ok" and "owner" not in out[k]))]
    todo = todo[: args.limit] if args.limit else todo
    print(f"enriching {len(todo)} brands")
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        for i, (k, e) in enumerate(ex.map(enrich_brand, todo), 1):
            out[k] = e
            if i % 25 == 0:
                (D / "enriched.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
                print(f"  {i}/{len(todo)}")
    (D / "enriched.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))


# ---------------------------------------------------------------- output

COLUMNS = ["Brand", "Website", "Home country + where confirmed", "Category", "Subcategory", "Best-seller product",
           "Product price", "Product URL", "Why it works on TikTok", "Marketing email", "General email", "Company phone",
           "Contact name + role", "LinkedIn URL", "Instagram", "Instagram followers", "TikTok handle",
           "TikTok Shop status", "Ships to Hungary", "List", "Fit score", "Source", "Notes", "Date found"]
WHY = {"skincare": "Easy to show on camera: apply it and show the result in one short clip.",
       "haircare": "Hair routines film well: before/after and application in one short video.",
       "oral care": "Whitening is a classic before/after TikTok format.",
       "self-tan": "Self-tan before/after is visible in a single short video.",
       "gummies": "Colourful daily habit, easy to show in a 'what I take every day' clip.",
       "collagen": "Fits daily routine videos; creators can show it going into coffee or water.",
       "sleep": "Night-routine videos are an easy, repeatable format.",
       "magnesium": "Simple to show in a daily routine or wind-down video.",
       "hair/skin/nails supplements": "Progress-update videos over a few weeks suit this product.",
       "vitamins & supplements": "Fits 'what I take every day' routine videos.",
       "freeze-dried": "The crunch and texture are the demo: made for taste-test videos.",
       "protein snacks": "Taste-test and 'what I eat in a day' videos sell snacks.",
       "snacks": "Taste-test videos are one of the easiest TikTok formats.",
       "leggings & sets": "Try-on and fit videos sell activewear on TikTok.",
       "activewear": "Try-on and workout videos show fit and stretch.",
       "basics": "Try-on hauls are a core TikTok Shop format.",
       "electrolytes/hydration": "Mixing the drink on camera is a quick, visual demo.",
       "greens/superfood powders": "Morning-routine videos with the mix-and-drink moment.",
       "functional drinks": "Unboxing and first-sip reactions are easy to film."}


def eur(price, cur, rates):
    try:
        v = float(price)
    except (TypeError, ValueError):
        return None
    if cur and cur != "EUR" and cur in rates:
        v = v / rates[cur]
    return round(v, 2)


def fit_score(e, peur):
    s = 5
    if not e.get("category"):
        s -= 2
    if peur is None:
        s -= 1
    elif not 10 <= peur <= 40:
        s -= 1 if 6 <= peur <= 60 else 2
    if not e.get("marketing_email"):
        s -= 1
        if not e.get("general_email"):
            s -= 1
    if not e.get("instagram"):
        s -= 1
    return max(1, s)


BIG_RETAILER_LISTS = 5   # in >= 5 of the big-retailer brand lists -> "present in most big European retailers"
REVIEW_RETAILER_LISTS = 3


def size_check(n, r, e):
    """('main'|'review'|'drop', reason). Independent small/mid brands stay in the main list."""
    name = (n.get("name") or "").strip().lower()
    if name in OWN_LABELS or norm(name) in {norm(x) for x in OWN_LABELS}:
        return "drop", "retailer own label"
    if e.get("retailer_entity"):
        return "drop", f"retailer own label: {e['retailer_entity']}"
    if e.get("owner"):
        return "drop", f"owned by a large group: {e['owner']}"
    # Distinct retailers (Douglas IT/PL/NL/ES/BE count once).
    k = len({re.sub(r" (?:[A-Z]{2} )?brand list$", "", x).replace("healf.com", "Healf")
             for x in n.get("sources", [n.get("source")]) if x})
    if k >= BIG_RETAILER_LISTS:
        return "drop", f"stocked by {k} big retailers' brand lists"
    reasons = []
    if k >= REVIEW_RETAILER_LISTS:
        reasons.append(f"stocked by {k} big retailers' brand lists")
    if e.get("hreflangs", 0) >= 8:
        reasons.append(f"{e['hreflangs']} country/language storefronts")
    if e.get("stores"):
        reasons.append("has physical stores / store locator")
    return ("review", "; ".join(reasons)) if reasons else ("main", "")


def cmd_output(args):
    names = ip.load_json(D / "names.json", {})
    res = ip.load_json(D / "resolved.json", {})
    enr = ip.load_json(D / "enriched.json", {})
    try:
        import intl_pipeline as _
        rates = __import__("launch_plan").eur_rates()
    except Exception:
        rates = {"EUR": 1.0, "GBP": 0.84, "PLN": 4.25}
    rows, de_at, review, stats = [], [], [], {"not_target_country": 0, "unconfirmed_country": 0, "no_category": 0, "unreachable": 0}
    for k, e in enr.items():
        if e.get("status") != "ok":
            stats["unreachable"] += 1
            continue
        r, n = res[k], names.get(k, {})
        if not e["category"]:
            stats["no_category"] += 1
            continue
        if not e["country"]:
            stats["unconfirmed_country"] += 1
            continue
        verdict, why_ = size_check(n, r, e)
        if verdict == "drop":
            stats[f"dropped: {why_.split(':')[0]}"] = stats.get(f"dropped: {why_.split(':')[0]}", 0) + 1
            continue
        peur = eur(e["price"], e["currency"], rates)
        price = f"{e['price']} {e['currency']}".strip() + (f" (~€{peur:.0f})" if peur and e["currency"] != "EUR" else "") if e["price"] else ""
        notes = []
        if not e["marketing_email"] and not e["general_email"]:
            notes.append("NO EMAIL FOUND")
        if e["tts"] == "unverified":
            notes.append("TikTok not checked (robots.txt); no TikTok Shop link on site")
        if e.get("product_how"):
            notes.append(f"product from {e['product_how']}")
        row = [n.get("name") or r.get("title"), r["website"], f"{e['country']} — {e['country_where']}", e["category"],
               e["subcategory"], e["product"], price, e["product_url"], WHY.get(e["subcategory"], ""),
               e["marketing_email"], e["general_email"], e["phone"], e["contact"], e["linkedin"],
               e["instagram"], "", e["tiktok"], e["tts"] if e["tts"] == "on" else "unverified",
               e["hu"], "A" if e["tts"] == "on" else "B", fit_score(e, peur), n.get("source", ""), "; ".join(notes), TODAY]
        if verdict == "review":
            row[22] = (row[22] + "; " if row[22] else "") + f"REVIEW: {why_}"
        if e["country"] in ("Germany", "Austria"):
            de_at.append(row)
        elif e["country"] in EMAIL_COUNTRIES:
            (review if verdict == "review" else rows).append(row)
        else:
            stats["not_target_country"] += 1
    rows.sort(key=lambda x: (-x[20], CAT_ORDER.index(x[3]) if x[3] in CAT_ORDER else 9, x[0].lower()))
    limit = args.batch * 200 if args.batch else len(rows)
    from openpyxl import Workbook
    from openpyxl.styles import Font
    wb = Workbook()
    review.sort(key=lambda x: (-x[20], x[0].lower()))
    for title, data in (("Brands", rows[:limit]), ("Review", review), ("DE_AT_LinkedIn_only", de_at)):
        ws = wb.active if title == "Brands" else wb.create_sheet(title)
        ws.title = title
        ws.append(COLUMNS)
        for c in ws[1]:
            c.font = Font(bold=True)
        for r in data:
            ws.append(r)
        ws.freeze_panes = "A2"
        for col in ws.columns:
            ws.column_dimensions[col[0].column_letter].width = min(45, max(10, *(len(str(c.value or "")) for c in col)) + 2)
    wb.save(ip.ROOT / "brands_1000.xlsx")
    out = rows[:limit]
    from collections import Counter
    print(f"rows written: {len(out)} (of {len(rows)} qualifying); review: {len(review)}; DE/AT: {len(de_at)}; excluded: {stats}")
    print("by category:", dict(Counter(r[3] for r in out)))
    print("by country:", dict(Counter(r[2].split(' — ')[0] for r in out)))
    print("marketing email:", sum(1 for r in out if r[9]), "| any email:", sum(1 for r in out if r[9] or r[10]),
          "| avg fit:", round(sum(r[20] for r in out) / max(1, len(out)), 2))
    print("by source:", dict(Counter(r[21] for r in out)))
    print("List A:", sum(1 for r in out if r[19] == "A"), "| ships to HU:", sum(1 for r in out if r[18] == "yes"))


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("names")
    for c in ("resolve", "enrich"):
        p = sub.add_parser(c)
        p.add_argument("--limit", type=int)
        p.add_argument("--workers", type=int, default=16)
    o = sub.add_parser("output")
    o.add_argument("--batch", type=int)
    a = ap.parse_args()
    {"names": cmd_names, "resolve": cmd_resolve, "enrich": cmd_enrich, "output": cmd_output}[a.cmd](a)


if __name__ == "__main__":
    main()
