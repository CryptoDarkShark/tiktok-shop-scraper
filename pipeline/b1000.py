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

# Legal-page evidence per country. STRONG = company registry / VAT / legal registration identifiers;
# a country is confirmed only by a strong identifier on a legal-type page, backed by a second strong identifier
# or the country's name/city within 300 characters of it. Country names alone never count (currency selectors).
STRONG = {
    "United Kingdom": [r"registered in (?:england|scotland|wales|northern ireland)", r"laws of (?:england|scotland)",
                       r"companies house", r"company (?:registration )?(?:number|no\.?)\s*:?\s*(?:sc|ni)?\d{6,8}\b",
                       r"\bvat (?:reg(?:istration|istered)?\.? )?(?:number|no\.?)?\s*:?\s*gb ?\d{3} ?\d{4} ?\d{2}\b"],
    "Ireland": [r"registered in (?:the republic of )?ireland", r"laws of ireland", r"\bcro (?:number|no\.?)?\s*:?\s*\d{5,6}\b",
                r"\bie ?\d{7}[a-w]{1,2}\b"],
    "Poland": [r"\bnip\s*:?\s*(?:pl)?\s?\d{3}[- ]?\d{3}[- ]?\d{2}[- ]?\d{2}\b", r"\bkrs\s*:?\s*\d{10}\b", r"\bregon\s*:?\s*\d{9}",
               r"sp\. ?z ?o\.? ?o\.?.{0,80}z siedzibą"],
    "Spain": [r"\b(?:cif|nif)\s*:?\s*[a-z]-?\d{7,8}\b", r"registro mercantil de", r"\bes ?[a-z]\d{7}[a-z0-9]\b"],
    "France": [r"\bsiret\s*:?\s*\d{3} ?\d{3} ?\d{3} ?\d{5}\b", r"\bsiren\s*:?\s*\d{3} ?\d{3} ?\d{3}\b",
               r"\brcs (?:de )?[a-zé\-]+(?: [a-z]\b)?", r"\bfr ?[0-9a-z]{2} ?\d{9}\b"],
    "Italy": [r"(?:partita iva|p\.? ?iva)\s*:?\s*(?:it)?\s?\d{11}\b", r"\brea\s*:?\s*[a-z]{2}[- ]?\d{4,7}\b", r"\bit ?\d{11}\b"],
    "Netherlands": [r"\bkvk(?:-nummer| nummer| number)?\s*:?\s*\d{8}\b", r"kamer van koophandel", r"\bnl ?\d{9} ?b ?\d{2}\b"],
    "Belgium": [r"\bbe ?0\d{3}[. ]?\d{3}[. ]?\d{3}\b", r"ondernemingsnummer", r"numéro d['’]entreprise", r"kbo-nummer"],
    "Germany": [r"handelsregister", r"\bhrb ?\d+", r"amtsgericht [a-zäöü]+", r"ust-?id(?:nr)?\.?\s*:?\s*de ?\d{9}"],
    "Austria": [r"firmenbuch(?:nummer)?", r"\bfn ?\d+ ?[a-z]\b", r"\batu ?\d{8}\b"],
}
NEAR = {
    "United Kingdom": r"united kingdom|\bengland\b|\bscotland\b|\bwales\b|\blondon\b|\b[a-z]{1,2}\d[a-z\d]? ?\d[a-z]{2}\b",
    "Ireland": r"\bireland\b|\bdublin\b|\bcork\b|\bgalway\b|\beircode\b|\b[a-z]\d{2} ?[a-z0-9]{4}\b",
    "Poland": r"\bpolska\b|\bpoland\b|\bwarszaw|\bkrak[oó]w|\bwrocław|\bpoznań|\bgdańsk|\błódź|\b\d{2}-\d{3}\b",
    "Spain": r"\bespaña\b|\bspain\b|\bmadrid\b|\bbarcelona\b|\bvalencia\b|\bsevilla\b|\b\d{5}\b",
    "France": r"\bfrance\b|\bparis\b|\blyon\b|\bmarseille\b|\b\d{5}\b",
    "Italy": r"\bitalia\b|\bitaly\b|\bmilano\b|\broma\b|\btorino\b|\b\d{5}\b",
    "Netherlands": r"\bnederland\b|\bnetherlands\b|\bamsterdam\b|\brotterdam\b|\butrecht\b|\b\d{4} ?[a-z]{2}\b",
    "Belgium": r"\bbelgi[eëu]m?\b|\bbelgique\b|\bbrussel|\bbruxelles\b|\bantwerp|\bgent\b|\bghent\b",
    "Germany": r"\bdeutschland\b|\bgermany\b|\bberlin\b|\bmünchen\b|\bhamburg\b|\b\d{5}\b",
    "Austria": r"\bösterreich\b|\baustria\b|\bwien\b|\bvienna\b|\bgraz\b|\blinz\b|\b\d{4}\b",
}
LEGAL_URL_RX = re.compile(r"impress|imprint|legal|mention|aviso|note-legali|terms|conditions|regulamin|privacy|polityka|"
                          r"contact|kontakt|contatt|contacto|cgv|agb|datenschutz|voorwaarden|condiciones|termini", re.I)
SELECTOR_RX = re.compile(r"\((?:[A-Z]{3}) [^)]{1,4}\)|(?:[A-Z][a-z]+ \([A-Z]{3} [^)]{1,4}\) ){2,}")
COUNTRY_RX = STRONG  # backwards name used elsewhere


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


REP_RX = re.compile(r"(?:eu|uk|european) (?:authori[sz]ed )?representative|responsible person|authori[sz]ed representative|importer|"
                    r"imported by|distributed by|distributor|dystrybutor|importador|distribuidor|distributeur|importateur|"
                    r"distributore|importatore|verantwoordelijke persoon|gpsr", re.I)


def confirm_country(pages):
    """(country, 'url — snippet') from legal-type pages only; ('', hint) if not confirmed."""
    best = None
    for url, t in pages:
        if not LEGAL_URL_RX.search(url):
            continue
        low = SELECTOR_RX.sub(" ", t).lower()
        for country, rxs in STRONG.items():
            hits = []
            for rx in rxs:
                for m in re.finditer(rx, low):
                    ctx = low[max(0, m.start() - 250): m.end() + 150]
                    if REP_RX.search(ctx):
                        continue  # EU representative / importer / distributor address
                    hits.append(m)
                    break
            if not hits:
                continue
            m0 = hits[0]
            near = re.search(NEAR[country], low[max(0, m0.start() - 300): m0.end() + 300])
            if len(hits) >= 2 or near:
                cand = (len(hits) + (1 if near else 0), country, url, t[max(0, m0.start() - 80): m0.end() + 60])
                if not best or cand[0] > best[0]:
                    best = cand
    if best:
        return best[1], f"{best[2]} — '…{best[3].strip()}…'"
    return "", ""


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


def shop_base_currency(html):
    """Shop's base currency only when the page shows it unconverted (Shopify rate 1.0); else ''."""
    m = re.search(r'Shopify\.currency\s*=\s*\{"active":"([A-Z]{3})","rate":"([\d.]+)"', html or "")
    return m.group(1) if m and float(m.group(2)) == 1.0 else ""


def shop_currency(html):
    m = re.search(r'Shopify\.currency\s*=\s*\{"active":"([A-Z]{3})"', html) or \
        re.search(r'"(?:priceCurrency|currencyCode|shop_currency|currency)"\s*:\s*"([A-Z]{3})"', html) or \
        re.search(r'property="og:price:currency"\s+content="([A-Z]{3})"', html)
    return m.group(1) if m else ""


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
    country, where = confirm_country(pages)
    blob = " ".join(t for _, t in pages)
    name, price, cur, purl, how = best_seller(site, home)
    if "collection" in how:  # Shopify catalogue JSON: prices are in the shop's base currency
        cur = shop_base_currency(home) or {"United Kingdom": "GBP", "Poland": "PLN"}.get(country, "EUR" if country else "")
    cur = cur or shop_currency(home) or currency_of(htext, site)
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
               "rules": 2, "owner": owner[:220], "retailer_entity": retailer[:200], "hreflangs": hreflangs, "stores": stores,
               "title": r.get("title", ""), "desc": (hs.find("meta", attrs={"name": "description"}) or {}).get("content", "")[:200]
               if hs.find("meta", attrs={"name": "description"}) else ""}


def cmd_enrich(args):
    res = ip.load_json(D / "resolved.json", {})
    out = ip.load_json(D / "enriched.json", {})
    # (re)do anything not yet enriched with the ownership/size fields
    todo = [(k, r) for k, r in res.items() if r and not r.get("skip")
            and (k not in out or (out[k].get("status") == "ok" and out[k].get("rules") != 2))]
    todo = todo[: args.limit] if args.limit else todo
    print(f"enriching {len(todo)} brands")
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        for i, (k, e) in enumerate(ex.map(enrich_brand, todo), 1):
            out[k] = e
            if i % 25 == 0:
                (D / "enriched.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
                print(f"  {i}/{len(todo)}")
    (D / "enriched.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))


BIG_RETAILER_LISTS = 5   # distinct big retailers -> 'stocked in most big European retailers'
REVIEW_RETAILER_LISTS = 3


# ---------------------------------------------------------------- signals (size / sales / social, public data only)

YT_RX = re.compile(r"https?://(?:www\.)?youtube\.com/(?:@[\w.\-]+|channel/[\w\-]+|c/[\w\-]+|user/[\w\-]+)")
REVIEWS_RX = re.compile(r"([\d][\d.,\s]{0,8}\d|\d)\s*\+?\s*(?:verified\s+)?(?:reviews|recenzj\w*|opini\w*|avis|reseñas|opiniones|recensioni|beoordelingen|reviews?\b)", re.I)
CUSTOMERS_RX = re.compile(r"(?:over|more than|ponad|más de|plus de|oltre|meer dan|join)\s+([\d][\d.,]*)\s*(k|m|000)?\s*\+?\s*(?:happy |satisfied |loyal )?(?:customers|clients|klient\w*|clientes|clients|clienti|klanten|community|followers)", re.I)
EU_SHIP_RX = re.compile(r"ship(?:ping)? (?:to|across|throughout) (?:the )?(?:eu|europe|european union)|(?:we )?ship (?:worldwide|internationally)|"
                        r"worldwide (?:shipping|delivery)|international (?:shipping|delivery)|eu[- ]wide (?:shipping|delivery)|"
                        r"wysyłka (?:do|na terenie) (?:ue|unii|europy)|wysyłka zagraniczna|envíos? (?:a|internacionales|a toda) europa|"
                        r"livraison (?:en|dans toute l['’]) ?europe|spedizion[ei] in (?:tutta )?europa|verzending (?:naar|binnen) europa", re.I)
CH_NUM_RX = re.compile(r"(?:company (?:registration )?(?:number|no\.?)|registered (?:number|no\.?)|company no\.?)\s*:?\s*((?:SC|NI|OC)?\d{6,8})", re.I)


def parse_count(num, mult=""):
    try:
        v = float(num.replace(" ", "").replace(",", "").replace(".", "") if re.search(r"[.,]\d{3}\b", num) else num.replace(",", "."))
    except ValueError:
        return None
    return int(v * {"k": 1_000, "m": 1_000_000}.get((mult or "").lower(), 1))


def youtube_subs(url):
    f, h = polite_get(url.rstrip("/") + "/about" if "/@" in url else url)
    if not h or h in ("ROBOTS", "BLOCKED"):
        return None
    m = re.search(r'"subscriberCountText":\{[^}]*?"(?:simpleText|content)":"([\d.,]+)\s*([KMkm])?', h) or \
        re.search(r"([\d.,]+)\s*([KMkm])?\s+subscribers", h)
    return parse_count(m.group(1), m.group(2)) if m else None


def companies_house(number):
    """Latest accounts type from the public Companies House filing history (UK)."""
    f, h = polite_get(f"https://find-and-update.company-information.service.gov.uk/company/{number}/filing-history")
    if not h or h in ("ROBOTS", "BLOCKED"):
        return ""
    t = re.sub(r"\s+", " ", BeautifulSoup(h, "html.parser").get_text(" "))
    m = re.search(r"(Micro company accounts|Accounts for a (?:small|medium|dormant) company|Total exemption (?:full|small) accounts|"
                  r"Unaudited abridged accounts|Abridged accounts|Full accounts|Group of companies' accounts|Audit exemption subsidiary accounts)"
                  r"[^.]{0,40}?made up to (\d{1,2} \w+ \d{4})", t)
    return f"{m.group(1)} (made up to {m.group(2)})" if m else ""


def signals_one(item):
    k, r, e = item
    site = r["website"]
    out = {"products": None, "reviews": None, "customers": None, "youtube": None, "yt_url": "", "ch": "", "ch_number": "",
           "eu_ship": False, "restock": False}
    # product count (Shopify catalogue, public JSON)
    n, page = 0, 1
    while page <= 4:
        j = get_json(urljoin(site, f"/products.json?limit=250&page={page}"))
        if not j or not j.get("products"):
            break
        n += len(j["products"])
        if len(j["products"]) < 250:
            break
        page += 1
    out["products"] = n or None
    f, h = polite_get(site)
    pages = [h] if h and h not in ("ROBOTS", "BLOCKED") else []
    out["currency"] = shop_currency(h) if pages else ""
    # re-verify the home-country evidence: it must not be an EU representative / importer address
    out["country_ok"] = True
    src_url = (re.findall(r"https?://\S+", e.get("country_where", "")) or [""])[0]
    snip = re.sub(r"^.*?'…|…'$", "", e.get("country_where", ""))[:60].strip().lower()
    if src_url and snip:
        f4, h4 = polite_get(src_url)
        if h4 and h4 not in ("ROBOTS", "BLOCKED"):
            low = re.sub(r"\s+", " ", BeautifulSoup(h4, "html.parser").get_text(" ")).lower()
            i = low.find(snip[:40])
            if i >= 0 and REP_RX.search(low[max(0, i - 250): i + 200]):
                out["country_ok"] = False
    if e.get("product_url"):
        f2, h2 = polite_get(e["product_url"])
        if h2 and h2 not in ("ROBOTS", "BLOCKED"):
            pages.append(h2)
    best_reviews = 0
    for html in pages:
        for m in re.finditer(r'"reviewCount"\s*:\s*"?(\d+)', html):
            best_reviews = max(best_reviews, int(m.group(1)))
        t = re.sub(r"\s+", " ", BeautifulSoup(html, "html.parser").get_text(" "))
        for m in REVIEWS_RX.finditer(t):
            c = parse_count(m.group(1))
            if c and c < 2_000_000:
                best_reviews = max(best_reviews, c)
        for m in CUSTOMERS_RX.finditer(t):
            c = parse_count(m.group(1), m.group(2))
            if c:
                out["customers"] = max(out["customers"] or 0, c)
        if EU_SHIP_RX.search(t):
            out["eu_ship"] = True
        if re.search(r"back in stock|restock|sold out|wyprzedane|agotado|épuisé|esaurito|uitverkocht", t, re.I):
            out["restock"] = True
        y = YT_RX.search(html)
        if y and not out["yt_url"]:
            out["yt_url"] = y.group(0)
    out["reviews"] = best_reviews or None
    if out["yt_url"]:
        out["youtube"] = youtube_subs(out["yt_url"])
    if e.get("country") == "United Kingdom":
        m = CH_NUM_RX.search(" ".join([e.get("country_where", "")] + [BeautifulSoup(x, "html.parser").get_text(" ") for x in pages]))
        if not m:  # legal pages carry the number most often
            for u in [w for w in re.findall(r"https?://\S+", e.get("country_where", ""))][:1]:
                f3, h3 = polite_get(u)
                if h3 and h3 not in ("ROBOTS", "BLOCKED"):
                    m = CH_NUM_RX.search(BeautifulSoup(h3, "html.parser").get_text(" "))
        if m:
            out["ch_number"] = m.group(1).upper().zfill(8)
            out["ch"] = companies_house(out["ch_number"])
    return k, out


def qualifies_for_signals(n, r, e):
    return e.get("status") == "ok" and e.get("category") and e.get("country") in (EMAIL_COUNTRIES | {"Germany", "Austria"}) \
        and size_check(n, r, e, None)[0] != "drop"


def cmd_signals(args):
    names, res = ip.load_json(D / "names.json", {}), ip.load_json(D / "resolved.json", {})
    enr, sig = ip.load_json(D / "enriched.json", {}), ip.load_json(D / "signals.json", {})
    todo = [(k, res[k], e) for k, e in enr.items() if k not in sig and qualifies_for_signals(names.get(k, {}), res[k], e)]
    todo = todo[: args.limit] if args.limit else todo
    print(f"collecting signals for {len(todo)} brands")
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        for i, (k, o) in enumerate(ex.map(signals_one, todo), 1):
            sig[k] = o
            if i % 25 == 0:
                (D / "signals.json").write_text(json.dumps(sig, ensure_ascii=False, indent=1))
                print(f"  {i}/{len(todo)}")
    (D / "signals.json").write_text(json.dumps(sig, ensure_ascii=False, indent=1))


# ---------------------------------------------------------------- output

COLUMNS = ["Brand", "Website", "Home country + where confirmed", "Category", "Subcategory", "Best-seller product",
           "Product price", "Product URL", "Why it works on TikTok", "Marketing email", "General email", "Company phone",
           "Contact name + role", "LinkedIn URL", "Instagram", "Instagram followers", "TikTok handle",
           "TikTok Shop status", "Ships to Hungary", "List", "Fit score", "Source", "Notes", "Date found",
           "Largest follower count (platform)", "Estimated revenue band", "Founder name", "Last Instagram post date",
           "Running Meta ads"]
FIT, NOTES = 20, 22
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
HIGH_MARGIN = {"skincare/haircare/oral care", "supplements & gummies", "healthy snacks"}


def eur(price, cur, rates):
    try:
        v = float(price)
    except (TypeError, ValueError):
        return None
    if cur and cur != "EUR" and cur in rates:
        v = v / rates[cur]
    return round(v, 2)


def retailer_count(n):
    """Distinct retailers (Douglas IT/PL/NL/ES/BE count once)."""
    return len({re.sub(r" (?:[A-Z]{2} )?brand list$", "", x).replace("healf.com", "Healf")
                for x in n.get("sources", [n.get("source")]) if x and not x.startswith("SerpAPI")})


def revenue_band(n, e, s):
    """(band, reasons). Estimated from public signals only; 'unknown' when they don't point anywhere."""
    over, under, why = [], [], []
    ch = (s or {}).get("ch", "")
    if re.search(r"Full accounts|Group of companies|medium company|Audit exemption subsidiary", ch):
        over.append(f"Companies House: {ch}")
    if re.search(r"Micro company", ch):
        under.append(f"Companies House: {ch} (micro entity: turnover under ~£1M)")
    k = retailer_count(n)
    if k >= REVIEW_RETAILER_LISTS:
        over.append(f"stocked by {k} big retailers")
    rv, pr, cu, yt = (s or {}).get("reviews"), (s or {}).get("products"), (s or {}).get("customers"), (s or {}).get("youtube")
    if rv and rv >= 10_000:
        over.append(f"{rv:,} reviews")
    if cu and cu >= 250_000:
        over.append(f"claims {cu:,}+ customers")
    if yt and yt > 100_000:
        over.append(f"{yt:,} YouTube subscribers")
    if pr and pr >= 300:
        over.append(f"{pr}+ products")
    if over:
        return "over 1M", over
    if under:
        small = (rv or 0) < 300 and (pr or 0) < 25
        return ("under 250K" if small else "250K-1M"), under
    if (rv or 0) >= 500 or (pr or 0) >= 40 or (cu or 0) >= 20_000 or k == 2:
        return "250K-1M", [x for x in (f"{rv:,} reviews" if rv else "", f"{pr} products" if pr else "",
                                        f"{k} retailers" if k > 1 else "") if x]
    if rv is not None and rv < 50 and (pr or 0) < 12 and k <= 1:
        return "under 250K", [f"{rv or 0} reviews, {pr or '?'} products, not stocked by big retailers"]
    return "unknown", []


def size_check(n, r, e, s=None):
    """('main'|'review'|'drop', reason) for the size and ownership rules."""
    name = (n.get("name") or "").strip().lower()
    if name in OWN_LABELS or norm(name) in {norm(x) for x in OWN_LABELS}:
        return "drop", "retailer own label"
    if e.get("retailer_entity"):
        return "drop", f"retailer own label: {e['retailer_entity']}"
    if e.get("owner"):
        return "drop", f"owned by a large group: {e['owner']}"
    k = retailer_count(n)
    if k >= BIG_RETAILER_LISTS:
        return "drop", f"stocked by {k} big retailers' brand lists"
    if s is None:
        return "main", ""
    band, why = revenue_band(n, e, s)
    yt = s.get("youtube")
    if yt and yt > 100_000:
        return "drop", f"too big: {yt:,} YouTube subscribers (limit ~100K)"
    if band == "over 1M" and re.search(r"Full accounts|Group|medium", s.get("ch", "")):
        return "drop", f"too big: {'; '.join(why)}"
    reasons = []
    if band == "over 1M":
        reasons.append("possibly over ~USD 1M: " + "; ".join(why))
    if e.get("hreflangs", 0) >= 8:
        reasons.append(f"{e['hreflangs']} country/language storefronts")
    if e.get("stores"):
        reasons.append("has physical stores / store locator")
    # too small to afford a monthly service: no follower data (Instagram/TikTok not readable) and no sign of sales
    sales = (s.get("reviews") or 0) >= 25 or (s.get("customers") or 0) >= 1_000 or s.get("restock") or k >= 1 and (s.get("reviews") or 0) >= 10
    if not sales and not (yt and yt >= 3_000):
        if (s.get("products") or 0) < 5 and not s.get("reviews"):
            return "drop", "too small: no sign of regular sales (no reviews, under 5 products)"
        reasons.append("no clear sign of regular sales found (reviews, restocks, customer counts)")
    return ("review", "; ".join(reasons)) if reasons else ("main", "")


def fit(e, s, peur, founder, email_ok):
    """Fit score 1-5 from the 'likely to sign' signs. Unknown signs (Instagram activity/followers, Meta ads,
    TikTok strength: not readable without Meta API / TikTok access) don't lower the score; known-missing ones do."""
    known_missing, unknown = [], []
    if not founder:
        known_missing.append("founder not named")
    fol = (s or {}).get("youtube")
    if fol is None:
        unknown.append("followers")
    elif not 10_000 <= fol <= 100_000:
        known_missing.append("followers outside 10K-100K")
    unknown.append("Instagram activity")
    if e.get("tiktok"):
        unknown.append("TikTok strength")  # handle linked on site; size not readable
    demo = peur is not None and 10 <= peur <= 40 and e.get("category") in HIGH_MARGIN
    if not demo:
        known_missing.append("hero product not EUR 10-40 in a high-margin category" if peur is not None else "hero price unknown")
    if not (e.get("hu") == "yes" or (s or {}).get("eu_ship")):
        if s is None:
            unknown.append("EU shipping (signals in progress)")
        else:
            known_missing.append("no Hungary/EU shipping found")
    if not email_ok:
        known_missing.append("no marketing or founder email")
    unknown.append("Meta ads")
    return max(1, 5 - len(known_missing)), known_missing, unknown


def cmd_output(args):
    names = ip.load_json(D / "names.json", {})
    res = ip.load_json(D / "resolved.json", {})
    enr = ip.load_json(D / "enriched.json", {})
    sig = ip.load_json(D / "signals.json", {})
    try:
        rates = __import__("launch_plan").eur_rates()
    except Exception:
        rates = {"EUR": 1.0, "GBP": 0.84, "PLN": 4.25}
    rows, de_at, review, dropped = [], [], [], []
    stats = {"not_target_country": 0, "unconfirmed_country": 0, "no_category": 0, "unreachable": 0, "signals_pending": 0}

    def drop(n, r, e, reason):
        dropped.append([n.get("name") or r.get("title") or r.get("domain"), r.get("website", ""),
                        (e or {}).get("country", ""), (e or {}).get("category", ""), reason,
                        ", ".join(n.get("sources", [n.get("source", "")])), TODAY])
    for k, e in enr.items():
        r, n = res.get(k, {}), names.get(k, {})
        if e.get("status") == "ok" and e.get("rules") != 2:
            stats["being re-checked under current rules"] = stats.get("being re-checked under current rules", 0) + 1
            continue
        if e.get("status") != "ok":
            stats["unreachable"] += 1
            drop(n, r, None, f"site not readable ({e.get('status')}: unreachable, blocked or robots.txt)")
            continue
        if not e["category"]:
            stats["no_category"] += 1
            drop(n, r, e, "not in a target category (skincare/haircare/oral, supplements, snacks, activewear, drinks)")
            continue
        if not e["country"]:
            stats["unconfirmed_country"] += 1
            drop(n, r, e, "home country not confirmed on a legal page")
            continue
        if e["country"] not in EMAIL_COUNTRIES | {"Germany", "Austria"}:
            stats["not_target_country"] += 1
            drop(n, r, e, f"home country {e['country']} not in target countries")
            continue
        s = sig.get(k)
        verdict, why_ = size_check(n, r, e, s)
        if verdict == "drop":
            key = "dropped: " + why_.split(":")[0]
            stats[key] = stats.get(key, 0) + 1
            drop(n, r, e, why_)
            continue
        if s is None:
            stats["signals_pending"] += 1
        if s and s.get("country_ok") is False:
            stats["dropped: country evidence is an EU representative/importer address"] = \
                stats.get("dropped: country evidence is an EU representative/importer address", 0) + 1
            drop(n, r, e, "country evidence is an EU representative/importer address")
            continue
        pending = s is None
        s = s or {}
        peur = eur(e["price"], e["currency"], rates)
        price = f"{e['price']} {e['currency']}".strip() + (f" (~€{peur:.0f})" if peur and e["currency"] != "EUR" else "") if e["price"] else ""
        founder = re.sub(r"\s*\(.*$", "", e.get("contact", ""))
        first = founder.split()[0].lower() if founder else ""
        founder_email = next((x for x in (e["marketing_email"], e["general_email"]) if first and x and x.split("@")[0].startswith(first)), "")
        email_ok = bool(e["marketing_email"] or founder_email)
        score, missing, unknown = fit(e, None if pending else s, peur, founder, email_ok)
        band, band_why = ("in progress", []) if pending else revenue_band(n, e, s)
        notes = ["SIGNALS IN PROGRESS (size, reviews, shipping still being collected)"] if pending else []
        if not e["marketing_email"] and not e["general_email"]:
            notes.append("NO EMAIL FOUND")
        if verdict == "review":
            notes.append(f"REVIEW: {why_}")
        if missing:
            notes.append("missing: " + ", ".join(missing))
        notes.append("not readable: " + ", ".join(unknown))
        if band_why:
            notes.append("revenue estimate from: " + "; ".join(band_why))
        if s.get("reviews"):
            notes.append(f"{s['reviews']:,} reviews on site")
        if s.get("products"):
            notes.append(f"{s['products']} products")
        ship = "yes" if e["hu"] == "yes" else ("EU-wide" if s.get("eu_ship") else ("in progress" if pending else "unknown"))
        largest = f"{s['youtube']:,} (YouTube)" if s.get("youtube") else ("in progress" if pending else "unknown")
        row = [n.get("name") or r.get("title"), r["website"], f"{e['country']} — {e['country_where']}", e["category"],
               e["subcategory"], e["product"], price, e["product_url"], WHY.get(e["subcategory"], ""),
               e["marketing_email"] or founder_email, e["general_email"], e["phone"], e["contact"], e["linkedin"],
               e["instagram"], "unknown", e["tiktok"], "on" if e["tts"] == "on" else "unverified", ship,
               "A" if e["tts"] == "on" else "B", score, ", ".join(n.get("sources", [n.get("source", "")])), "; ".join(notes), TODAY,
               largest, band, founder, "unknown", "unknown"]
        if e["country"] in ("Germany", "Austria"):
            de_at.append(row)
        else:
            (review if verdict == "review" else rows).append(row)
    key = lambda x: (-x[FIT], CAT_ORDER.index(x[3]) if x[3] in CAT_ORDER else 9, x[0].lower())
    rows.sort(key=key)
    review.sort(key=key)
    de_at.sort(key=key)
    limit = args.batch * 200 if args.batch else len(rows)
    from openpyxl import Workbook
    from openpyxl.styles import Font
    wb = Workbook()
    dropped.sort(key=lambda x: (x[4], str(x[0]).lower()))
    sheets = (("Brands", rows[:limit], COLUMNS), ("Review", review, COLUMNS), ("DE_AT_LinkedIn_only", de_at, COLUMNS),
              ("Dropped", dropped, ["Brand", "Website", "Home country", "Category", "Reason dropped", "Source", "Date checked"]))
    for title, data, cols in sheets:
        ws = wb.active if title == "Brands" else wb.create_sheet(title)
        ws.title = title
        ws.append(cols)
        for c in ws[1]:
            c.font = Font(bold=True)
        for r_ in data:
            ws.append(r_)
        ws.freeze_panes = "A2"
        for col in ws.columns:
            ws.column_dimensions[col[0].column_letter].width = min(45, max(10, *(len(str(c.value or "")) for c in col)) + 2)
    wb.save(ip.ROOT / "brands_1000.xlsx")
    out = rows[:limit]
    from collections import Counter
    print(f"main list: {len(out)} written (of {len(rows)} qualifying, {sum(1 for x in out if 'SIGNALS IN PROGRESS' in x[NOTES])} "
          f"with signals in progress); review: {len(review)}; DE/AT: {len(de_at)}; dropped: {len(dropped)}")
    print("excluded:", stats)
    print("by category:", dict(Counter(x[3] for x in out)))
    print("by country:", dict(Counter(x[2].split(' — ')[0] for x in out)))
    print("fit 4-5:", sum(1 for x in out if x[FIT] >= 4), "| by score:", dict(sorted(Counter(x[FIT] for x in out).items(), reverse=True)))
    print("marketing/founder email:", sum(1 for x in out if x[9]), "| any email:", sum(1 for x in out if x[9] or x[10]),
          "| avg fit:", round(sum(x[FIT] for x in out) / max(1, len(out)), 2))
    print("founder named:", sum(1 for x in out if x[26]), "| revenue band:", dict(Counter(x[25] for x in out)))
    print("ships HU/EU:", dict(Counter(x[18] for x in out)), "| List A:", sum(1 for x in out if x[19] == "A"))
    src = Counter()
    for x in out:
        for y in x[21].split(", "):
            src[y] += 1
    print("sources:", dict(src.most_common()))


SERP_QUERIES = {
    "healthy snacks": [
        ("uk", "en", "UK healthy snack brand freeze dried fruit"), ("uk", "en", "independent UK protein snack brand"),
        ("uk", "en", "best small healthy snack brands UK"), ("ie", "en", "Irish healthy snack brand"),
        ("pl", "pl", "polska marka zdrowych przekąsek"), ("pl", "pl", "liofilizowane owoce polska marka"),
        ("pl", "pl", "polska marka batonów proteinowych"), ("es", "es", "marca española snacks saludables"),
        ("es", "es", "marca española fruta liofilizada snack"), ("fr", "fr", "marque française snacks sains"),
        ("fr", "fr", "marque française biscuits protéinés"), ("it", "it", "marca italiana snack salutari"),
        ("nl", "nl", "Nederlands merk gezonde snacks"), ("be", "nl", "Belgisch merk gezonde snacks"),
    ],
    "activewear & basics": [
        ("uk", "en", "independent UK activewear brand leggings"), ("uk", "en", "small British activewear brands women"),
        ("ie", "en", "Irish activewear brand"), ("pl", "pl", "polska marka odzieży sportowej legginsy"),
        ("es", "es", "marca española ropa deportiva mujer leggings"), ("fr", "fr", "marque française vêtements de sport femme leggings"),
        ("it", "it", "marchio italiano abbigliamento sportivo donna leggings"), ("nl", "nl", "Nederlands activewear merk"),
        ("be", "nl", "Belgisch sportkleding merk vrouwen"),
    ],
    "functional drinks & powders": [
        ("uk", "en", "UK functional drink brand adaptogen"), ("uk", "en", "UK electrolyte drink powder brand"),
        ("uk", "en", "UK greens powder brand"), ("uk", "en", "UK prebiotic soda brand"), ("ie", "en", "Irish functional drinks brand"),
        ("pl", "pl", "polska marka napojów funkcjonalnych"), ("pl", "pl", "polska marka elektrolity w proszku"),
        ("es", "es", "marca española bebidas funcionales"), ("es", "es", "marca española electrolitos en polvo"),
        ("fr", "fr", "marque française boisson fonctionnelle"), ("fr", "fr", "marque française kombucha"),
        ("it", "it", "marchio italiano bevande funzionali"), ("nl", "nl", "Nederlands merk functionele dranken"),
        ("nl", "nl", "Nederlandse kombucha merk"), ("be", "nl", "Belgisch merk kombucha"),
    ],
}
NOT_BRANDS = re.compile(r"amazon|ebay|allegro|ceneo|tesco|sainsbury|ocado|waitrose|asda|morrisons|boots|superdrug|holland|"
                        r"hollandandbarrett|bol\.com|albert ?heijn|ah\.nl|jumbo|delhaize|colruyt|carrefour|mercadona|elcorteingles|"
                        r"esselunga|coop|monoprix|franprix|leclerc|auchan|intermarche|lidl|aldi|zalando|decathlon|sportsdirect|"
                        r"jdsports|asos|next\.co|trustpilot|reddit|quora|instagram|facebook|tiktok|youtube|pinterest|linkedin|"
                        r"wikipedia|google|apple|glassdoor|indeed|crunchbase|companieshouse|gov\.|yelp|tripadvisor|notino|douglas|"
                        r"rossmann|hebe|dm\.de|kruidvat|etos|druni|primor|arenal|sephora|lookfantastic|cultbeauty|feelunique", re.I)
MEDIA = re.compile(r"magazine|news|blog|times|guardian|vogue|elle\.|cosmopolitan|glamour|marieclaire|womenshealth|menshealth|"
                   r"independent|telegraph|standard\.co|mirror|dailymail|bbc|forbes|businessinsider|thegrocer|foodnavigator|"
                   r"bevnet|drinks|retail|marketing|wprost|onet|interia|wp\.pl|elpais|elmundo|abc\.es|lefigaro|lemonde|"
                   r"corriere|repubblica|nu\.nl|ad\.nl|hln\.be|nieuwsblad|best-|top-|/best|/top|ranking|lista|meilleur|migliori|mejores", re.I)


def cmd_serp(args):
    """Gap-filling with SerpAPI (snacks, activewear, drinks). Keeps a reserve of searches."""
    key = __import__("os").environ.get("SERPAPI_KEY")
    left = requests.get("https://serpapi.com/account.json", params={"api_key": key}, timeout=30).json().get("total_searches_left", 0)
    budget = max(0, min(args.max, left - args.reserve))
    res = ip.load_json(D / "resolved.json", {})
    names = ip.load_json(D / "names.json", {})
    done = ip.load_json(D / "serp_done.json", [])
    known = {v["domain"] for v in res.values() if v} | existing_domains()
    added, used = 0, 0
    for cat, qs in SERP_QUERIES.items():
        for gl, hl, q in qs:
            if q in done:
                continue
            if used >= budget:
                print(f"search budget reached ({used} used, reserve {args.reserve} kept)")
                break
            try:
                results = ip.serp(q, gl, hl)
            except Exception as ex:
                print(f"search failed {q!r}: {ex}")
                continue
            used += 1
            done.append(q)
            label = f"SerpAPI: {q}"
            cands = []
            for r in results:
                link = r.get("link", "")
                d = ip.domain_of(link)
                if not d or NOT_BRANDS.search(d):
                    continue
                if MEDIA.search(d) or MEDIA.search(urlparse(link).path):
                    f, h = polite_get(link)  # article / list page: harvest the brand links it points to
                    if h and h not in ("ROBOTS", "BLOCKED"):
                        for a in BeautifulSoup(h, "html.parser").find_all("a", href=True):
                            u = urljoin(f, a["href"])
                            dd = ip.domain_of(u)
                            if u.startswith("http") and dd and dd != d and not NOT_BRANDS.search(dd) and not MEDIA.search(dd) \
                                    and not ip.is_blocked(dd):
                                cands.append((dd, a.get_text(" ", strip=True)[:60]))
                    continue
                cands.append((d, r.get("title", "")[:80]))
            n = 0
            for d, title in dict(cands).items():
                if d in known:
                    continue
                known.add(d)
                k = "d:" + d
                res[k] = {"domain": d, "website": f"https://{d}/", "title": title}
                names[k] = {"name": "", "source": label, "sources": [label]}
                n += 1
            added += n
            print(f"[{cat}] {q!r}: {len(results)} results, +{n} candidate sites")
            (D / "resolved.json").write_text(json.dumps(res, ensure_ascii=False, indent=1))
            (D / "names.json").write_text(json.dumps(names, ensure_ascii=False, indent=1))
            (D / "serp_done.json").write_text(json.dumps(done, indent=1))
    print(f"{used} searches used, {added} candidate sites added")


# ---------------------------------------------------------------- more free sources

AWARD_INDEX = ["https://www.freefromfoodawards.co.uk/winners/"]
AWARD_EXTRA = ["https://freefrom.evessiocloud.com/ffa2026/en/page/drinks-awards-finalists",
               "https://freefrom.evessiocloud.com/ffa2026/en/page/food-awards-finalists-2026",
               "https://freefrom.evessiocloud.com/ffa2026/en/page/nutritional-supplements-awards-finalists-2026"]
RETAIL_HOST = re.compile(r"waitrose|tesco|sainsbury|ocado|asda|morrisons|m&s|marksandspencer|boots|superdrug|holland|amazon|"
                         r"lidl|aldi|coop|co-op|iceland|booths|wholefoods|planetorganic|ebay|etsy|allergyshow|twitter|facebook|"
                         r"instagram|evessio|freefrom|google", re.I)


def add_candidate(names, res, known, label, brand, site=None):
    """Add a brand name (and its site, when the source gives it) as a candidate; returns 1 if new."""
    k = norm(brand)
    if not k or len(k) < 3:
        return 0
    if site:
        d = ip.domain_of(site)
        if not d or RETAIL_HOST.search(d) or d in known:
            site = None
    if k in names:
        if label not in names[k].setdefault("sources", [names[k].get("source")]):
            names[k]["sources"].append(label)
        return 0
    names[k] = {"name": brand, "source": label, "sources": [label]}
    if site:
        d = ip.domain_of(site)
        known.add(d)
        res[k] = {"domain": d, "website": f"https://{urlparse(site).netloc}/", "title": brand}
    return 1


def cmd_awards(args):
    names, res = ip.load_json(D / "names.json", {}), ip.load_json(D / "resolved.json", {})
    known = {v["domain"] for v in res.values() if v} | existing_domains()
    pages = set(AWARD_EXTRA)
    for idx in AWARD_INDEX:
        f, h = polite_get(idx, timeout=30)
        if h and h not in ("ROBOTS", "BLOCKED"):
            pages |= {urljoin(f, a["href"]).split("#")[0] for a in BeautifulSoup(h, "html.parser").find_all("a", href=True)
                      if "evessiocloud.com" in a["href"] and "admin" not in a["href"]}
    total = 0
    for u in sorted(pages):
        f, h = polite_get(u, timeout=40)
        if not h or h in ("ROBOTS", "BLOCKED"):
            print(f"skip {u}: {h or 'unreachable'}"); continue
        soup = BeautifulSoup(h, "html.parser")
        label = "Free From Awards: " + re.sub(r"https?://freefrom\.evessiocloud\.com/", "", u)
        n = 0
        for h4 in soup.find_all("h4", class_="nomination-name"):
            brand = h4.get_text(" ", strip=True).split(",")[0].strip()
            brand = re.sub(r"\s+(?:ltd|limited|llp|plc)\.?$", "", brand, flags=re.I)
            box = h4.find_parent(attrs={"data-slug": True}) or h4.parent.parent
            site = None
            if box:
                m = re.search(r"Where to buy\s*(https?://\S+)", box.get_text(" ", strip=True))
                site = m.group(1).rstrip(".,)") if m else None
            n += add_candidate(names, res, known, label, brand, site)
        total += n
        print(f"{label}: +{n}")
    (D / "names.json").write_text(json.dumps(names, ensure_ascii=False, indent=1))
    (D / "resolved.json").write_text(json.dumps(res, ensure_ascii=False, indent=1))
    print(f"awards: {total} new brand names")


def cmd_lookalike(args):
    """Brands with fit >= 3 -> their stockists -> small independent shops -> brands those shops also stock
    (Shopify shops publish their catalogue at /products.json; 'vendor' is the brand)."""
    from openpyxl import load_workbook
    names, res = ip.load_json(D / "names.json", {}), ip.load_json(D / "resolved.json", {})
    known = {v["domain"] for v in res.values() if v} | existing_domains()
    done = ip.load_json(D / "lookalike_done.json", {"brands": [], "shops": []})
    wb = load_workbook(ip.ROOT / "brands_1000.xlsx", read_only=True)
    seeds = [(r[0], r[1]) for sh in ("Brands", "Review") for r in wb[sh].iter_rows(min_row=2, values_only=True)
             if r and isinstance(r[FIT], int) and r[FIT] >= 3 and r[1] not in done["brands"]]
    print(f"{len(seeds)} seed brands (fit >= 3)")
    shops = set()
    for brand, site in seeds:
        done["brands"].append(site)
        f, h = polite_get(site)
        if not h or h in ("ROBOTS", "BLOCKED"):
            continue
        for u in ip.find_links(BeautifulSoup(h, "html.parser"), f, ["stockist", "where-to-buy", "where to buy", "retailers",
                                                                      "find-us", "punkty-sprzedazy", "revendeurs", "puntos-de-venta"], limit=2):
            f2, h2 = polite_get(u)
            if not h2 or h2 in ("ROBOTS", "BLOCKED"):
                continue
            for a in BeautifulSoup(h2, "html.parser").find_all("a", href=True):
                d = ip.domain_of(urljoin(f2, a["href"]))
                if d and d != ip.domain_of(site) and not NOT_BRANDS.search(d) and not RETAIL_HOST.search(d) \
                        and not MEDIA.search(d) and not ip.is_blocked(d):
                    shops.add(d)
    shops -= set(done["shops"])
    print(f"{len(shops)} independent shops to read")
    total = 0
    for d in sorted(shops):
        done["shops"].append(d)
        vendors = set()
        for page in (1, 2):
            j = get_json(f"https://{d}/products.json?limit=250&page={page}")
            if not j or not j.get("products"):
                break
            vendors |= {p.get("vendor", "").strip() for p in j["products"] if p.get("vendor")}
        vendors = {v for v in vendors if norm(v) != norm(d.split(".")[0]) and len(v) <= 40}
        n = sum(add_candidate(names, res, known, f"lookalike: stocked by {d}", v) for v in vendors)
        total += n
        if vendors:
            print(f"  {d}: {len(vendors)} brands, +{n} new")
    (D / "names.json").write_text(json.dumps(names, ensure_ascii=False, indent=1))
    (D / "resolved.json").write_text(json.dumps(res, ensure_ascii=False, indent=1))
    (D / "lookalike_done.json").write_text(json.dumps(done, indent=1))
    print(f"lookalike: {total} new brand names")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("names")
    for c in ("resolve", "enrich", "signals"):
        p = sub.add_parser(c)
        p.add_argument("--limit", type=int)
        p.add_argument("--workers", type=int, default=16)
    sp = sub.add_parser("serp")
    sp.add_argument("--max", type=int, default=75)
    sp.add_argument("--reserve", type=int, default=30)
    sub.add_parser("awards")
    sub.add_parser("lookalike")
    o = sub.add_parser("output")
    o.add_argument("--batch", type=int)
    a = ap.parse_args()
    {"names": cmd_names, "resolve": cmd_resolve, "enrich": cmd_enrich, "signals": cmd_signals, "serp": cmd_serp, "awards": cmd_awards, "lookalike": cmd_lookalike, "output": cmd_output}[a.cmd](a)


if __name__ == "__main__":
    main()
