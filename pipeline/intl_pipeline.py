"""International brand outreach pipeline (brands registered outside Hungary).

List A: already on TikTok Shop somewhere (site links to TikTok Shop / shows a badge).
List B: already sells to Hungary (.hu site, Hungarian webshop, ships to HU), no TikTok Shop link.

Stages:
    python pipeline/intl_pipeline.py source [--set NAME]   # SerpAPI -> data/intl/candidates.json
    python pipeline/intl_pipeline.py enrich [--domains a.com,b.pl]  # fetch sites -> data/intl/enriched.json
    python pipeline/intl_pipeline.py triage                 # data/intl/triage.xlsx for manual curation
    python pipeline/intl_pipeline.py output                 # curation -> brands_intl.xlsx, linkedin_only.xlsx
    python pipeline/intl_pipeline.py draft [--date D] [--size N] [--samples]
    python pipeline/intl_pipeline.py approve --date D [--only x.com,y.pl] [--exclude z.cz]
    python pipeline/intl_pipeline.py send --date D --go     # approved, unsent drafts, within daily cap
    python pipeline/intl_pipeline.py followup [--go]        # day 3 / day 7 follow-ups, same thread
    python pipeline/intl_pipeline.py mark EMAIL --replied|--bounced|--unsubscribed
    python pipeline/intl_pipeline.py sync                   # bounce status from Resend (needs a full-access key)
    python pipeline/intl_pipeline.py status

Manual curation lives in pipeline/intl_curation.json: every fact that ends up in an
email (country, product, opener, first name) is checked there by a person against the
brand's own site. Nothing is sent without `approve` + `send --go`.
"""
import argparse
import csv
import datetime as dt
import json
import os
import re
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urljoin, urlparse
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "intl"
DRAFTS = ROOT / "drafts" / "intl"
CURATION = ROOT / "pipeline" / "intl_curation.json"
QUERIES = ROOT / "pipeline" / "intl_queries.json"
LOG = ROOT / "log.csv"
TZ = ZoneInfo("Europe/Budapest")
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")

FROM = "Fazekas Viktor <viktor@outreach.joinmatchly.com>"
REPLY_TO = "info@joinmatchly.com"
START_PER_DAY, STEP_PER_DAY, MAX_PER_DAY = 20, 5, 40
FOLLOWUP_DAYS = (3, 7)
MAX_OPENER_WORDS = 35  # template text is fixed; only the opener is length-checked
# Rulebook section 2: who gets email, who goes to LinkedIn, who waits for ExpandNow.
EMAIL_COUNTRIES = {"United Kingdom", "Ireland", "Spain", "France", "Italy", "Netherlands", "Belgium", "Poland"}
LINKEDIN_ONLY = {"Germany", "Austria"}
SKIP_COUNTRIES = {"Hungary"}  # not in this pipeline
PRICE_RANGE_EUR = (10, 60)


def route(b):
    """'email', 'linkedin', 'later' or 'skip' for a curated brand."""
    c = b.get("country", "")
    if c in SKIP_COUNTRIES:
        return "skip"
    if c in LINKEDIN_ONLY:
        return "linkedin"
    if c in EMAIL_COUNTRIES:
        return "email"
    return "later"


def today():
    return dt.datetime.now(TZ).date()


# Marketplaces, retail chains, household-name brands, media and social: never targets.
BLOCKED_DOMAINS = {
    "amazon", "ebay", "etsy", "aliexpress", "temu", "shein", "allegro", "emag", "alza",
    "zalando", "aboutyou", "answear", "notino", "douglas", "sephora", "rossmann", "dm",
    "hm", "zara", "mango", "reserved", "sinsay", "ikea", "decathlon", "lidl", "aldi",
    "tesco", "boots", "superdrug", "asos", "primark", "next", "argos", "johnlewis",
    "marksandspencer", "lookfantastic", "cultbeauty", "facebook", "instagram", "tiktok",
    "youtube", "linkedin", "pinterest", "reddit", "wikipedia", "google", "x", "twitter",
    "threads", "apple", "microsoft", "shopify", "wix", "wordpress", "medium", "forbes",
    "vogue", "elle", "glamour", "cosmopolitan", "businessinsider", "theguardian", "bbc",
    "independent", "telegraph", "dailymail", "mirror", "thesun", "standard", "wizaz",
    "wiadomoscikosmetyczne", "dlahandlu", "pepita", "arukereso", "argep", "vatera",
    "jofogas", "xxxlutz", "butlers", "mediamarkt", "euronics", "kaufland", "auchan",
    "spar", "pepco", "tchibo", "lacoste", "nike", "adidas", "puma", "loreal", "nivea",
    "garnier", "cerave", "unilever", "pg", "samsung", "xiaomi", "huawei", "lenovo",
    "ceneo", "heureka", "mall", "kasa", "datart", "czc", "trustpilot", "shoptet",
    "shoprenter", "unas", "packeta", "gls-group", "dpd", "inpost", "ups", "dhl", "fedex",
    "paypal", "stripe", "klarna", "visa", "mastercard", "gov", "europa", "abiszoo",
    "linktr", "lnk", "beacons", "canva", "hubspot", "semrush", "statista", "similarweb",
    "glossy", "modernretail", "retailgazette", "drapersonline", "cosmeticsbusiness",
    "marketingweek", "thedrum", "campaignlive", "econsultancy", "ecommercenews",
    "sellerapp", "junglescout", "helium10", "tiktokshop", "seller-uk", "pl.linkedin",
}
BLOCKED_SUFFIXES = (".gov", ".edu", ".gov.uk", ".gov.pl", ".gov.hu", ".ac.uk")

COUNTRY_NAMES = {
    # country -> spellings in EN / local / HU / PL / CZ / DE
    "Poland": ["poland", "polska", "lengyelország", "polsko", "polen"],
    "Czech Republic": ["czech republic", "czechia", "česká republika", "česko", "csehország", "tschechien", "czechy"],
    "Slovakia": ["slovakia", "slovensko", "slovenská republika", "szlovákia", "słowacja", "slowakei"],
    "Romania": ["romania", "românia", "románia", "rumunia", "rumänien"],
    "United Kingdom": ["united kingdom", "england", "scotland", "wales", "egyesült királyság", "wielka brytania", "großbritannien"],
    "Ireland": ["ireland", "írország", "irlandia"],
    "Italy": ["italy", "italia", "olaszország", "włochy", "itálie", "italien"],
    "Spain": ["spain", "españa", "spanyolország", "hiszpania", "španělsko", "spanien"],
    "France": ["france", "franciaország", "francja", "francie", "frankreich"],
    "Netherlands": ["netherlands", "nederland", "the netherlands", "hollandia", "holandia", "nizozemsko", "niederlande"],
    "Belgium": ["belgium", "belgië", "belgique", "belgia", "belgie", "belgien"],
    "Slovenia": ["slovenia", "slovenija", "szlovénia", "słowenia", "slowenien"],
    "Croatia": ["croatia", "hrvatska", "horvátország", "chorwacja", "chorvatsko", "kroatien"],
    "Lithuania": ["lithuania", "lietuva", "litvánia", "litwa", "litauen"],
    "Latvia": ["latvia", "latvija", "lettország", "łotwa", "lettland"],
    "Estonia": ["estonia", "eesti", "észtország", "estonsko", "estland"],
    "Bulgaria": ["bulgaria", "българия", "bulgária", "bulharsko", "bulgarien"],
    "Denmark": ["denmark", "danmark", "dánia", "dania", "dänemark"],
    "Sweden": ["sweden", "sverige", "svédország", "szwecja", "schweden"],
    "Finland": ["finland", "suomi", "finnország", "finlandia"],
    "Portugal": ["portugal", "portugália", "portugalia"],
    "Greece": ["greece", "ελλάδα", "görögország", "grecja"],
    "Germany": ["germany", "deutschland", "németország", "niemcy", "německo"],
    "Austria": ["austria", "österreich", "ausztria", "rakousko"],
    "Switzerland": ["switzerland", "schweiz", "suisse", "svájc", "szwajcaria"],
    "United States": ["united states", "usa", "u.s.a."],
    "Hungary": ["hungary", "magyarország", "węgry", "maďarsko", "ungarn"],
}
VAT_PREFIX = {"PL": "Poland", "CZ": "Czech Republic", "SK": "Slovakia", "RO": "Romania",
              "GB": "United Kingdom", "IE": "Ireland", "IT": "Italy", "ES": "Spain", "FR": "France",
              "NL": "Netherlands", "BE": "Belgium", "SI": "Slovenia", "HR": "Croatia",
              "LT": "Lithuania", "LV": "Latvia", "EE": "Estonia", "BG": "Bulgaria", "DK": "Denmark",
              "SE": "Sweden", "FI": "Finland", "PT": "Portugal", "EL": "Greece", "DE": "Germany",
              "ATU": "Austria", "HU": "Hungary"}
VAT_RE = re.compile(r"\b(PL\d{10}|CZ\d{8,10}|SK\d{10}|RO\d{2,10}|GB\d{9}|IE\d{7}[A-Z]{1,2}|IT\d{11}|"
                    r"ES[A-Z0-9]\d{7}[A-Z0-9]|FR[A-Z0-9]{2}\d{9}|NL\d{9}B\d{2}|BE0?\d{9,10}|SI\d{8}|"
                    r"HR\d{11}|LT\d{9,12}|LV\d{11}|EE\d{9}|BG\d{9,10}|DK\d{8}|SE\d{12}|FI\d{8}|"
                    r"PT\d{9}|EL\d{9}|DE\d{9}|ATU\d{8}|HU\d{8})\b")
COMPANY_FORMS = [
    (r"\bsp\.\s?z\s?o\.\s?o\.?", "Poland"), (r"\bs\.\s?r\.\s?o\.?", "Czech Republic / Slovakia"),
    (r"\bspol\. s r\.o\.", "Czech Republic / Slovakia"), (r"\ba\.s\.", "Czech Republic / Slovakia"),
    (r"\bs\.r\.l\.", "Romania / Italy"), (r"\bs\.l\.u?\.?\b", "Spain"), (r"\bs\.a\.s\.?\b|\bsarl\b", "France"),
    (r"\bb\.v\.", "Netherlands"), (r"\bd\.o\.o\.", "Slovenia / Croatia"), (r"\bUAB\b", "Lithuania"),
    (r"\bSIA\b", "Latvia"), (r"\bOÜ\b", "Estonia"), (r"\bEOOD\b|\bOOD\b", "Bulgaria"), (r"\bApS\b", "Denmark"),
    (r"\bLtd\b|\bLimited\b", "United Kingdom / Ireland"), (r"\bGmbH\b", "Germany / Austria"),
    (r"\bKft\.?|\bZrt\.?|\bBt\.", "Hungary"),
]

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
GENERIC_PREFIXES = ("info", "hello", "hi", "contact", "kontakt", "hey", "team", "office", "shop",
                    "sales", "support", "care", "customercare", "service", "biuro", "sklep",
                    "obchod", "ugyfelszolgalat", "mail", "orders", "help", "partners", "business")
FOUNDER_RE = re.compile(
    r"(?:founder|co-founder|founded by|CEO|owner|e-?commerce manager|head of e-?commerce|"
    r"założyciel(?:ka)?|właściciel(?:ka)?|zakladatel(?:ka)?|majitel(?:ka)?|alapító|fondatrice|fondateur|"
    r"fondatrice|fondatore|fundador(?:a)?)\s*[:,\-–]?\s*"
    r"([A-ZÁČĎÉĚÍŇÓŘŠŤÚŮÝŽĄĆĘŁŃŚŹŻ][a-záčďéěíňóřšťúůýžąćęłńśźżöüőű]+)\s+([A-ZÁČĎÉĚÍŇÓŘŠŤÚŮÝŽĄĆĘŁŃŚŹŻ][a-záčďéěíňóřšťúůýžąćęłńśźżöüőű]+)",
)
LEGAL_WORDS = ["impressum", "imprint", "legal", "mentions", "note-legali", "aviso-legal", "terms",
               "regulamin", "obchodni-podminky", "obchodne-podmienky", "vop", "aszf", "impresszum",
               "about", "o-nas", "o-nás", "rolunk", "rólunk", "chi-siamo", "quienes-somos",
               "contact", "kontakt", "kapcsolat", "shipping", "delivery", "dostawa", "doprava",
               "szallitas", "szállítás", "wysylka", "wysyłka", "our-story", "company"]
TTS_PATTERNS = [
    re.compile(r"https?://(?:[a-z]+\.)?shop\.tiktok\.com[^\s\"'<>]*", re.I),
    re.compile(r"https?://(?:www\.)?tiktok\.com/(?:@[\w.]+/)?shop[^\s\"'<>]*", re.I),
    re.compile(r"https?://vt\.tiktok\.com/[^\s\"'<>]*", re.I),
    re.compile(r"https?://(?:www\.)?tiktok\.com/view/product[^\s\"'<>]*", re.I),
]
TTS_TEXT = re.compile(r"tik\s?tok\s?shop", re.I)


def cf_emails(html):
    """Decode Cloudflare-obfuscated addresses (data-cfemail / /cdn-cgi/l/email-protection#...)."""
    out = []
    for hexs in re.findall(r'(?:data-cfemail="|email-protection#)([0-9a-f]{6,})', html):
        key = int(hexs[:2], 16)
        out.append("".join(chr(int(hexs[i:i + 2], 16) ^ key) for i in range(2, len(hexs), 2)))
    return out


def domain_of(url):
    host = urlparse(url).netloc.lower().split(":")[0]
    return host[4:] if host.startswith("www.") else host


def is_blocked(domain):
    if not domain or "." not in domain or domain.endswith(BLOCKED_SUFFIXES):
        return True
    labels = domain.split(".")
    return any(l in BLOCKED_DOMAINS for l in labels[:-1])


# ---------------------------------------------------------------- source

def serp(query, gl, hl):
    key = os.environ.get("SERPAPI_KEY")
    if not key:
        sys.exit("SERPAPI_KEY is not set")
    r = requests.get("https://serpapi.com/search.json", params={
        "q": query, "gl": gl, "hl": hl, "num": 20, "api_key": key}, timeout=60)
    r.raise_for_status()
    d = r.json()
    if d.get("error") and "hasn't returned any results" not in d["error"]:
        raise RuntimeError(d["error"])
    return d.get("organic_results", [])


def fetch(url, lang="en,hu;q=0.8"):
    try:
        r = requests.get(url, headers={"User-Agent": UA, "Accept-Language": lang},
                         timeout=15, allow_redirects=True)
        if r.status_code == 200 and "html" in r.headers.get("content-type", ""):
            if r.encoding in (None, "ISO-8859-1"):
                r.encoding = r.apparent_encoding
            return r.url, r.text
    except requests.RequestException:
        pass
    return None, None


def harvest_links(url):
    """Outbound shop-looking links from an article page."""
    final, html = fetch(url)
    if not html:
        return []
    src = domain_of(final)
    out = []
    for a in BeautifulSoup(html, "html.parser").find_all("a", href=True):
        u = urljoin(final, a["href"])
        d = domain_of(u)
        if u.startswith("http") and d != src and not is_blocked(d) and d not in out:
            out.append(d)
    return out[:60]


def load_json(path, default):
    return json.loads(path.read_text()) if path.exists() else default


def cmd_source(args):
    DATA.mkdir(parents=True, exist_ok=True)
    out = DATA / "candidates.json"
    cands = load_json(out, {})
    searches = cands.pop("_searches", [])
    done = {s["query"] for s in searches}
    sets = load_json(QUERIES, {})
    budget = args.max_searches
    for name, cfg in sets.items():
        if name.startswith("_") or (args.set and name not in args.set.split(",")):
            continue
        for q in cfg["queries"]:
            if q in done:
                continue
            if budget <= 0:
                print("search budget reached; stopping")
                break
            budget -= 1
            try:
                results = serp(q, cfg["gl"], cfg["hl"])
            except Exception as e:
                print(f"search failed: {q!r}: {e}")
                continue
            searches.append({"query": q, "set": name, "n": len(results), "date": today().isoformat()})
            new = 0
            for r in results:
                link = r.get("link", "")
                d = domain_of(link)
                found = [d] if not is_blocked(d) else []
                if cfg["mode"] == "harvest":
                    found += harvest_links(link)
                for fd in found:
                    if fd in cands:
                        continue
                    cands[fd] = {"domain": fd, "url": f"https://{fd}/", "set": name, "query": q,
                                 "via": link if fd != d else "", "title": r.get("title", "") if fd == d else "",
                                 "snippet": r.get("snippet", "") if fd == d else "", "source": "SerpAPI"}
                    new += 1
            print(f"[{name}] {q!r}: {len(results)} results, {new} new domains ({len(cands)} total)")
            time.sleep(0.3)
    cands["_searches"] = searches
    out.write_text(json.dumps(cands, ensure_ascii=False, indent=1))
    print(f"{len(searches)} searches so far, {len(cands) - 1} candidate domains -> {out}")


# ---------------------------------------------------------------- enrich

def find_links(soup, base, words, limit=8):
    hits = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        text = (a.get_text(" ", strip=True) + " " + href).lower()
        if any(w in text for w in words):
            u = urljoin(base, href).split("#")[0]
            if domain_of(u) == domain_of(base) and u not in hits:
                hits.append(u)
    return hits[:limit]


# Contact priority (user rule): 1) marketing/partnerships/collab/influencer/creators/pr/affiliate,
# 2) a named marketing or e-commerce manager published on the site, 3) info/hello/contact,
# then any other address the brand publishes. Only addresses found on the brand's own pages.
TIER1 = ("marketing", "partnerships", "partnership", "partners", "partenariat", "collab", "influencer",
         "creators", "creator", "pr", "press", "media", "affiliate", "aff")
TIER3 = ("info", "hello", "contact")
ROLE_WORDS = re.compile(r"marketing|e-?commerce|ecommerce|digital|brand manager|partnership", re.I)
JUNK = ("sentry", "example", "wixpress", "domain.com", "email.com", "yourname", "godaddy", "@2x",
        "shoptet.cz", "privacy@", "your@")


def email_tier(email, context=""):
    """1-4 (lower is better) for an address the brand publishes; context = text around it on the page."""
    local = email.split("@")[0].lower()
    parts = re.split(r"[._\-+]", local)
    # Short tags (pr, aff, media, press) must match exactly; longer ones may be prefixes (partnerships2@).
    if any(p in TIER1 or (len(t) >= 6 and p.startswith(t)) for p in parts for t in TIER1):
        return 1
    if "." in local and not local.startswith(TIER3) and ROLE_WORDS.search(context or ""):
        return 2  # named person whose published role is marketing / e-commerce
    if local.startswith(TIER3):
        return 3
    return 4


def pick_emails(emails, domain, contexts=None):
    """Brand's own published addresses, best first. contexts: {email: surrounding text}."""
    contexts = contexts or {}
    emails = {m.group(0).lower().strip(".") for e in emails for m in [EMAIL_RE.search(e)] if m}
    emails = [e for e in emails if not re.search(r"\.(png|jpe?g|gif|webp|svg|js|css)$", e)
              and not any(b in e for b in JUNK)]
    root = domain.split(".")[-2] if "." in domain else domain

    def score(e):
        local, _, host = e.partition("@")
        own = root in host
        bad = any(w in local for w in ("gdpr", "rodo", "dpo", "privacy", "noreply", "no-reply", "reklamac",
                                        "claims", "returns", "jobs", "careers", "praca", "iod"))
        return (0 if own else 1, 1 if bad else 0, email_tier(e, contexts.get(e, "")))
    return sorted(emails, key=score)


def social_handle(soup, host):
    skip = {"p", "reel", "explore", "share", "sharer", "intent", "tr", "plugins", "stories",
            "accounts", "about", "legal", "discover", "tag", "embed", "shop", "view", "video"}
    for a in soup.find_all("a", href=True):
        u = urlparse(a["href"])
        if host in u.netloc and "shop.tiktok" not in u.netloc:
            parts = [p for p in u.path.split("/") if p]
            if parts and parts[0].lstrip("@").lower() not in skip:
                return "@" + parts[0].lstrip("@")
    return ""


def guess_country(legal_text):
    """Return (best guess, evidence) from imprint/legal text. Always confirmed by hand."""
    scores, evidence = {}, []
    for m in VAT_RE.finditer(legal_text):
        vat = m.group(1)
        c = VAT_PREFIX.get(vat[:3]) or VAT_PREFIX.get(vat[:2])
        if c:
            scores[c] = scores.get(c, 0) + 5
            evidence.append(f"VAT {vat}")
    low = legal_text.lower()
    for c, names in COUNTRY_NAMES.items():
        n = sum(len(re.findall(r"(?<![\w])" + re.escape(x) + r"(?![\w])", low)) for x in names)
        if n:
            scores[c] = scores.get(c, 0) + min(n, 4)
    for rx, c in COMPANY_FORMS:
        m = re.search(rx, legal_text)
        if m:
            evidence.append(f"company form '{m.group(0).strip()}' -> {c}")
    if not scores:
        return "", "; ".join(evidence)
    best = max(scores, key=scores.get)
    top = sorted(scores.items(), key=lambda x: -x[1])[:4]
    evidence.append("mentions " + ", ".join(f"{c}:{s}" for c, s in top))
    return best, "; ".join(evidence)


def hu_evidence(domain, soups, htmls, blob):
    ev = []
    if domain.endswith(".hu"):
        ev.append(".hu domain")
    for s in soups[:1]:
        h = s.find("html")
        if h and (h.get("lang") or "").lower().startswith("hu"):
            ev.append("site language hu")
        for l in s.find_all("link", hreflang=True):
            if l["hreflang"].lower().startswith("hu"):
                ev.append(f"hreflang hu {l.get('href', '')}")
                break
        for a in s.find_all("a", href=True):
            href = a["href"]
            if re.search(r"(^|//)hu\.|/hu(/|$)|\.hu(/|$)", href) and domain_of(urljoin(f"https://{domain}/", href)) != "":
                d = domain_of(urljoin(f"https://{domain}/", href))
                if not is_blocked(d):
                    ev.append(f"link to HU version {urljoin(f'https://{domain}/', href)}")
                    break
    low = blob.lower()
    for kw in ("hungary", "magyarország", "węgry", "maďarsko", "ungarn", "huf"):
        i = low.find(kw)
        if i >= 0:
            ev.append(f"mentions '{kw}': …{blob[max(0, i - 60): i + 60]}…")
            break
    return ev


def products(soups):
    names = []
    for s in soups:
        for tag in s.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(tag.string or "")
            except Exception:
                continue
            stack = data if isinstance(data, list) else [data]
            while stack:
                x = stack.pop()
                if isinstance(x, dict):
                    if x.get("@type") in ("Product", ["Product"]) and x.get("name"):
                        names.append(str(x["name"]))
                    stack.extend(v for v in x.values() if isinstance(v, (dict, list)))
                elif isinstance(x, list):
                    stack.extend(x)
        for a in s.find_all("a", href=True):
            if re.search(r"/(products?|produkt|produkty|p|termek|prodotto|producto|produit)/", a["href"]):
                t = a.get_text(" ", strip=True)
                if 4 < len(t) < 80 and t not in names:
                    names.append(t)
    return names[:15]


def bestseller_text(blob):
    m = re.search(r"(best[\s-]?sellers?|bestsellery?|most popular|nejprodávanější|najlepiej sprzedające|"
                  r"legnépszerűbb|bestseller|más vendidos|meilleures ventes|i più venduti)(.{0,400})", blob, re.I)
    return (m.group(1) + m.group(2)) if m else ""


def tiktok_user(handle):
    """Public TikTok profile as {'user': ..., 'stats': ...}, or None if unreadable."""
    try:
        r = requests.get(f"https://www.tiktok.com/{handle}", headers={"User-Agent": UA}, timeout=20)
        m = re.search(r'<script id="__UNIVERSAL_DATA_FOR_REHYDRATION__"[^>]*>(.*?)</script>', r.text, re.S)
        return json.loads(m.group(1))["__DEFAULT_SCOPE__"]["webapp.user-detail"]["userInfo"]
    except Exception:
        return None


def tiktok_profile(handle):
    """(is_seller, followers, bio) from a public TikTok profile; (None, None, '') if unreadable."""
    info = tiktok_user(handle)
    if not info:
        return None, None, ""
    user = info["user"]
    bio = (user.get("signature", "") + " " + json.dumps(user.get("bioLink", ""))).strip()
    return bool(user.get("ttSeller")) or "shop.tiktok.com" in bio, info.get("stats", {}).get("followerCount"), bio


def hu_tiktok_check(handle, brand):
    """Rulebook 3 (List A): look for signs the brand already sells to Hungarians on TikTok.
    Probes Hungarian account variants and the main profile bio. Returns 'none found (...)' or the evidence."""
    base = handle.lstrip("@").lower()
    stems = {base, re.sub(r"[._](official|pl|uk|cosmetics|kosmetyki|toys|shop|store)$", "", base),
             re.sub(r"[^a-z0-9]", "", brand.lower())}
    probes = sorted({f"@{s}{suf}" for s in stems if s for suf in (".hu", "_hu", "hu", ".hungary", "hungary", "_hungary", ".magyarorszag")})
    stem = re.sub(r"[^a-z0-9]", "", brand.lower())
    for p in probes:
        info = tiktok_user(p)
        if not info:
            continue
        user, stats = info["user"], info.get("stats", {})
        named = stem in re.sub(r"[^a-z0-9]", "", user.get("nickname", "").lower() + p.lower())
        active = user.get("ttSeller") or stats.get("videoCount", 0) > 0
        # Counts only if it is the brand's account and it sells or posts (an empty namesake doesn't).
        if named and active:
            return (f"Hungarian account {p} exists (seller={bool(user.get('ttSeller'))}, "
                    f"videos={stats.get('videoCount')}, followers={stats.get('followerCount')})")
    _, _, bio = tiktok_profile("@" + base)
    if re.search(r"magyar|hungary|\.hu\b|ft\b", bio, re.I):
        return f"main profile bio mentions Hungary: {bio[:80]}"
    return f"none found (checked @{base} bio and {', '.join(probes)})"


def hu_sibling(domain, brand):
    """A same-name .hu webshop (e.g. brand.pl -> brand.hu) that names the same brand."""
    label = domain.split(".")[-2] if domain.count(".") >= 1 else domain
    if domain.endswith(".hu"):
        return ""
    final, html = fetch(f"https://{label}.hu/", lang="hu")
    if not html:
        return ""
    if domain_of(final) == domain:
        return ""
    soup = BeautifulSoup(html, "html.parser")
    h = soup.find("html")
    title = (soup.title.get_text(" ", strip=True) if soup.title else "").lower()
    if brand.lower().split()[0] in title and h and (h.get("lang") or "").lower().startswith("hu"):
        return f"Hungarian webshop {final}"
    return ""


def enrich_one(c):
    domain = c["domain"]
    final, html = fetch(c["url"])
    if not html:
        return {**c, "status": "unreachable"}
    base = f"{urlparse(final).scheme}://{urlparse(final).netloc}/"
    home = BeautifulSoup(html, "html.parser")
    soups, htmls, texts, pages = [home], [html], [home.get_text(" ", strip=True)], [final]
    legal_texts = []
    for u in find_links(home, base, LEGAL_WORDS, limit=10):
        if u in pages:
            continue
        f, h = fetch(u)
        if h:
            s = BeautifulSoup(h, "html.parser")
            soups.append(s)
            htmls.append(h)
            t = s.get_text(" ", strip=True)
            texts.append(t)
            pages.append(f)
            if any(w in u.lower() for w in ("impress", "imprint", "legal", "mentions", "legali", "terms",
                                             "regulamin", "podminky", "podmienky", "vop", "aszf", "contact",
                                             "kontakt", "kapcsolat", "company")):
                legal_texts.append(t)
    blob = " \n ".join(texts)
    raw = "".join(htmls)
    legal = " \n ".join(legal_texts) or blob

    tts_links = sorted({m.group(0)[:160] for rx in TTS_PATTERNS for m in rx.finditer(raw)})
    tts_text = []
    for m in TTS_TEXT.finditer(blob):
        tts_text.append(blob[max(0, m.start() - 60): m.end() + 60])
    for img in home.find_all("img"):
        alt = (img.get("alt", "") + " " + img.get("src", "")).lower()
        if "tiktok" in alt and "shop" in alt:
            tts_text.append(f"image: {alt[:120]}")

    blob_n = re.sub(r"\s*(?:\[at\]|\(at\)|\[@\]|\(@\))\s*", "@", blob)
    emails = set(EMAIL_RE.findall(blob_n)) | set(cf_emails(raw))
    for s in soups:
        for a in s.select("a[href^=mailto]"):
            emails.add(a["href"][7:].split("?")[0])
    founder = ""
    fm = FOUNDER_RE.search(blob)
    if fm:
        founder = f"{fm.group(1)} {fm.group(2)} (…{blob[max(0, fm.start() - 40): fm.end() + 20]}…)"

    og = home.find("meta", property="og:site_name")
    brand = og["content"].strip() if og and og.get("content") else ""
    if not brand or len(brand) > 40:
        brand = domain.split(".")[0].replace("-", " ").title()
    title = home.title.get_text(strip=True) if home.title else ""
    desc = home.find("meta", attrs={"name": "description"})
    country, country_ev = guess_country(legal)
    tiktok = next((h for h in (social_handle(s, "tiktok.com") for s in soups) if h), "")
    seller, followers, bio = tiktok_profile(tiktok) if tiktok else (None, None, "")
    hu_ev = hu_evidence(domain, soups, htmls, blob)
    sib = hu_sibling(domain, brand)
    if sib:
        hu_ev.insert(0, sib)
    return {
        **c, "status": "ok", "brand": brand, "website": base, "title": title,
        "description": desc.get("content", "") if desc else "",
        "emails": pick_emails(emails, domain), "founder_hint": founder,
        "instagram": next((h for h in (social_handle(s, "instagram.com") for s in soups) if h), ""),
        "tiktok": tiktok, "tiktok_seller": seller, "tiktok_followers": followers, "tiktok_bio": bio[:200],
        "tts_links": tts_links, "tts_text": tts_text[:5],
        "hu_evidence": hu_ev,
        "country_guess": country, "country_evidence": country_ev,
        "products": products(soups), "bestseller": bestseller_text(blob),
        "home_excerpt": texts[0][:1500], "pages": pages,
    }


def cmd_enrich(args):
    cands = load_json(DATA / "candidates.json", {})
    cands.pop("_searches", None)
    extra = args.domains.split(",") if args.domains else []
    if args.seeds:
        extra += [l.strip() for l in (ROOT / "pipeline" / "intl_seeds.txt").read_text().splitlines()
                  if l.strip() and not l.startswith("#")]
    if extra:
        for d in extra:
            d = domain_of("https://" + d.strip().removeprefix("https://").removeprefix("http://"))
            cands.setdefault(d, {"domain": d, "url": f"https://{d}/", "set": "manual", "query": "",
                                 "via": "", "title": "", "snippet": "", "source": "manual"})
    prev = {r["domain"]: r for r in load_json(DATA / "enriched.json", [])}
    todo = [c for d, c in cands.items() if not is_blocked(d)
            and (d not in prev or d in extra)]
    print(f"{len(cands)} candidates, {len(todo)} to enrich")
    with ThreadPoolExecutor(max_workers=12) as ex:
        for r in ex.map(enrich_one, todo):
            prev[r["domain"]] = r
    DATA.mkdir(parents=True, exist_ok=True)
    (DATA / "enriched.json").write_text(json.dumps(list(prev.values()), ensure_ascii=False, indent=1))
    (DATA / "candidates.json").write_text(json.dumps({**cands, "_searches": load_json(
        DATA / "candidates.json", {}).get("_searches", [])}, ensure_ascii=False, indent=1))
    ok = [r for r in prev.values() if r["status"] == "ok"]
    print(f"reachable {len(ok)}; TikTok Shop link {sum(1 for r in ok if r['tts_links'])}; "
          f"TikTok seller profile {sum(1 for r in ok if r.get('tiktok_seller'))}; "
          f"HU evidence {sum(1 for r in ok if r['hu_evidence'])}; with email {sum(1 for r in ok if r['emails'])}")


# ---------------------------------------------------------------- triage / output

def auto_list(r):
    if r.get("tts_links") or r.get("tiktok_seller"):
        return "A"
    if r.get("hu_evidence"):
        return "B"
    return ""


def write_xlsx(path, header, rows, title="Brands"):
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font
    wb = Workbook()
    ws = wb.active
    ws.title = title
    ws.append(header)
    for c in ws[1]:
        c.font = Font(bold=True)
    for r in rows:
        ws.append(r)
    for col in ws.columns:
        width = min(60, max(10, *(len(str(c.value or "")) for c in col)) + 2)
        ws.column_dimensions[col[0].column_letter].width = width
        for c in col[1:]:
            c.alignment = Alignment(wrap_text=width >= 60, vertical="top")
    ws.freeze_panes = "A2"
    wb.save(path)


def cmd_triage(args):
    """Candidates with an automatic list guess, for manual curation."""
    res = load_json(DATA / "enriched.json", [])
    cur = load_json(CURATION, {"brands": {}, "skip": {}})
    rows = []
    for r in res:
        if r["status"] != "ok" or r["domain"] in cur["brands"] or r["domain"] in cur["skip"]:
            continue
        lst = auto_list(r)
        if not lst:
            continue
        rows.append([r["domain"], lst, r["brand"], r["country_guess"], r["country_evidence"][:200],
                     " | ".join(r["tts_links"][:2]), " | ".join(r["hu_evidence"][:2])[:200],
                     ", ".join(r["emails"][:3]), r["founder_hint"][:100], " | ".join(r["products"][:5])[:250],
                     r["title"][:120]])
    rows.sort(key=lambda x: (x[1], x[3]))
    write_xlsx(DATA / "triage.xlsx", ["Domain", "Auto List", "Brand", "Country Guess", "Country Evidence",
                                      "TikTok Shop Links", "HU Evidence", "Emails", "Founder Hint",
                                      "Products", "Title"], rows)
    print(f"{len(rows)} uncurated candidates with A/B signals -> {DATA / 'triage.xlsx'}")


BRAND_COLUMNS = ["Brand", "Website", "Home Country", "Country Confirmed On", "List", "Category",
                 "Featured Product", "Price", "Contact Email", "First Name", "TikTok Shop Evidence",
                 "TikTok Shop Market", "Hungarian TikTok Check", "Hungary Evidence", "Opening Line",
                 "Creator Type", "Flag", "Date Found"]


def curated():
    cur = load_json(CURATION, {"brands": {}, "skip": {}})
    return {d: {"domain": d, **b} for d, b in cur["brands"].items()}


def brand_row(b):
    market = b.get("tts_market", "") if b.get("tts_market_confirmed") else ""
    market = f"{market} (confirmed: {b.get('tts_market_note', '')})" if market else "not confirmed"
    return [b["brand"], b["website"], b["country"],
            b.get("legal_page", "") if b.get("country_confirmed") else "NOT CONFIRMED",
            b["list"], b["category"], b.get("product", ""), b.get("price", ""), b.get("email", ""),
            b.get("first_name", ""), b.get("tts_evidence", ""), market if b["list"] == "A" else "",
            b.get("hu_tiktok", "") if b["list"] == "A" else "", b.get("hu_evidence", ""),
            b.get("opener", ""), b.get("creators", ""), flag_of(b), b.get("date_found", "")]


def flag_of(b):
    """Everything that stops a brand from being emailed under the rulebook (empty = OK to draft)."""
    flags = []
    if not b.get("country_confirmed"):
        flags.append("home country not confirmed on the brand's legal/imprint/terms page")
    if b.get("list") not in ("A", "B"):
        flags.append("fits neither list")
    if b.get("list") == "A" and not str(b.get("hu_tiktok", "")).startswith("none"):
        flags.append("Hungarian TikTok presence not checked" if not b.get("hu_tiktok")
                     else f"sells to Hungarians on TikTok: {b['hu_tiktok']}")
    if b.get("price_eur") is not None and not PRICE_RANGE_EUR[0] <= b["price_eur"] <= PRICE_RANGE_EUR[1]:
        flags.append(f"featured product price ~{b['price_eur']} EUR outside {PRICE_RANGE_EUR[0]}-{PRICE_RANGE_EUR[1]} EUR")
    if not b.get("opener"):
        flags.append("no specific opener found on site")
    elif words(b["opener"]) >= MAX_OPENER_WORDS or len(re.findall(r"[.!?](?:\s|$)", b["opener"])) > 2:
        flags.append(f"opener too long ({words(b['opener'])} words, max 2 sentences)")
    if not b.get("product"):
        flags.append("no featured product")
    if not b.get("email"):
        flags.append("no email")
    if b.get("flag"):
        flags.append(b["flag"])
    return "; ".join(flags)


def cmd_output(args):
    brands = curated()
    email_rows = [b for b in brands.values() if route(b) == "email"]
    li_rows = [b for b in brands.values() if route(b) == "linkedin"]
    later_rows = [b for b in brands.values() if route(b) == "later"]
    later_rows.sort(key=lambda b: (b["country"], b["brand"].lower()))
    write_xlsx(ROOT / "later_expandnow.xlsx", BRAND_COLUMNS, [brand_row(b) for b in later_rows])
    email_rows.sort(key=lambda b: (b["list"], b["country"], b["brand"].lower()))
    write_xlsx(ROOT / "brands_intl.xlsx", BRAND_COLUMNS, [brand_row(b) for b in email_rows])
    write_xlsx(ROOT / "linkedin_only.xlsx",
               ["Brand", "Website", "Home Country", "List", "Category", "Featured Product",
                "First Name", "LinkedIn Company Search", "Notes", "Date Found"],
               [[b["brand"], b["website"], b["country"], b["list"], b["category"], b.get("product", ""),
                 b.get("first_name", ""),
                 "https://www.linkedin.com/search/results/companies/?keywords=" + requests.utils.quote(b["brand"]),
                 b.get("flag", ""), b.get("date_found", "")] for b in li_rows])
    for lst in "AB":
        n = [b for b in email_rows if b["list"] == lst]
        print(f"List {lst}: {len(n)} brands ({sum(1 for b in n if not flag_of(b))} ready, "
              f"{sum(1 for b in n if flag_of(b))} flagged)")
    print(f"linkedin_only.xlsx: {len(li_rows)} (Germany/Austria)")
    print(f"later_expandnow.xlsx: {len(later_rows)} ({', '.join(sorted({b['country'] for b in later_rows}))})")


# ---------------------------------------------------------------- drafts

ANETT_CATEGORIES = {"beauty", "lifestyle", "fitness"}


def creator_sentence(b):
    anett = ", including Anett, who has 37K followers on TikTok" if b.get("anett") else ""
    return (f"We already have {b['creators']} ready to promote your products{anett}. They're among the 300+ "
            f"vetted creators in our agency, and brands like GymBeam already work with us. Creators are paid "
            f"a percentage of the sales they drive, so there are no upfront creator fees.")


SIGNATURE = "Fazekas Viktor\nFounder, Matchly\n+36 30 690 0060"
UNSUBSCRIBE = 'If you\'d rather not hear from us, just reply "unsubscribe".'


def render(b):
    """(subject, text). Paragraphs are separated by a blank line; lines inside one paragraph
    (the signature) by a single newline. to_html() turns each paragraph into its own <p>."""
    name = b.get("first_name") or f"{b['brand']} team"
    brand = b["brand"]
    if b["list"] == "A":
        subject = f"{brand} on TikTok Shop in Hungary"
        market = b.get("tts_market", "") if b.get("tts_market_confirmed") else ""
        market = f"the {market}" if market in ("UK", "US", "Netherlands") else market
        where = f" in {market}" if market else ""  # rulebook 4: country only when confirmed
        noticed = (f"I noticed {brand} is already on TikTok Shop{where}. Since this summer, shoppers in Hungary "
                   f"can use TikTok Shop too. People buy straight from the video they're watching, and every sale "
                   f"can be traced back to the video that drove it. {brand} isn't reaching Hungarian shoppers yet, "
                   f"and I think it would be a great fit.")
        run = "We launch and run your whole Hungarian presence for you:"
        question = "Which product would you launch first in Hungary? Just reply with its name."
    else:
        subject = f"TikTok Shop for {brand} in Hungary"
        noticed = ("You already sell to Hungary, but you're not on TikTok Shop yet. Since this summer, it's open to "
                   "Hungarian shoppers. People buy straight from the video they're watching, and every sale can be "
                   "traced back to the video that drove it.")
        run = "We set up and run the whole shop for you:"
        question = "Which product would you launch first on TikTok Shop? Just reply with its name."
    paragraphs = [
        f"Hi {name},",
        b["opener"],
        noticed,
        "SEDLAK, a small eyewear brand, went from zero to millions of dollars in sales on TikTok Shop.",
        f"{run} Hungarian listings, your affiliate program, creator management, videos, promotions, customer "
        f"messages and weekly sales reports. You just send the products.",
        creator_sentence(b),
        f"We only take on a few new brands each month, so every shop gets proper attention. If you reply, I'll "
        f"send you a free Hungarian launch plan for {brand} within 24 hours: the creators I'd match and the first "
        f"month of videos.",
        question,
        SIGNATURE,
        UNSUBSCRIBE,
    ]
    return subject, "\n\n".join(paragraphs)


FOLLOWUPS = {
    1: ["Hi {name},",
        "Just bringing this back to the top of your inbox.",
        "If you tell me which {brand} product you'd start with, I'll send you the free Hungarian launch plan "
        "within 24 hours.",
        "Viktor"],
    2: ["Hi {name},",
        "Last note from me. If Hungary isn't a priority for {brand} right now, no problem at all.",
        "If it is, just reply with one product and I'll take it from there.",
        "Viktor"],
}


def render_followup(b, n, greeting=None):
    """greeting: the exact 'Hi …,' line of the first email, so the thread stays consistent."""
    name = b.get("first_name") or f"{b['brand']} team"
    paras = [p.format(name=name, brand=b["brand"]) for p in FOLLOWUPS[n]]
    if greeting:
        paras[0] = greeting
    return "\n\n".join(paras + [UNSUBSCRIBE])


def to_html(text):
    """Every email goes out as HTML + plain text: one <p> per paragraph, <br> between signature lines."""
    paras = [p for p in text.split("\n\n") if p.strip()]
    body = "".join(f"<p>{'<br>'.join(html_escape(l) for l in p.splitlines())}</p>" for p in paras)
    return f"<!doctype html><html><body>{body}</body></html>"


def html_escape(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def words(text):
    return len(text.split())


def ready(b):
    return not flag_of(b) and route(b) == "email"


def draft_md(items, title):
    out = [f"# {title}\n"]
    for b in items:
        subject, body = render(b)
        out.append(f"## {b['brand']} ({b['domain']}) - List {b['list']}\n")
        out.append(f"- To: {b['email']}\n- Country: {b['country']} (confirmed on {b.get('legal_page', '')})\n"
                   f"- Category: {b['category']}\n"
                   f"- Product: {b['product']}\n- Evidence: {b.get('opener_source', '')}\n"
                   f"- Opener words: {words(b['opener'])}\n")
        out.append(f"**Subject:** {subject}\n\n```\n{body}\n```\n")
    return "\n".join(out)


def logged_emails():
    return {row["email"].lower() for row in read_log()}


def cmd_draft(args):
    DRAFTS.mkdir(parents=True, exist_ok=True)
    brands = curated()
    if args.samples:
        md = []
        for lst in "AB":
            pick = [b for b in brands.values() if b["list"] == lst and ready(b)][:3]
            md.append(draft_md(pick, f"Sample drafts - List {lst}"))
        p = DRAFTS / "samples.md"
        p.write_text("\n\n".join(md))
        print(f"-> {p}")
        return
    date = args.date or today().isoformat()
    batch_path = DRAFTS / f"batch-{date}.json"
    if batch_path.exists() and not args.force:
        sys.exit(f"{batch_path} exists; use --force to rebuild it")
    sent = logged_emails()
    queued = set()
    for p in DRAFTS.glob("batch-*.json"):
        if p != batch_path:
            queued |= {x["domain"] for x in json.loads(p.read_text())["items"]}
    size = args.size or daily_cap(date)
    pool = [b for b in brands.values() if ready(b) and b["email"].lower() not in sent and b["domain"] not in queued]
    # Alternate lists so each day mixes A and B.
    a = [b for b in pool if b["list"] == "A"]
    bb = [b for b in pool if b["list"] == "B"]
    pick = []
    while len(pick) < size and (a or bb):
        for src in (a, bb):
            if src and len(pick) < size:
                pick.append(src.pop(0))
    batch = {"date": date, "items": [{"domain": b["domain"], "approved": False} for b in pick]}
    batch_path.write_text(json.dumps(batch, indent=1))
    review = [f"# Batch {date}: {len(pick)} brands (cap {daily_cap(date)})\n",
              "Approve with: `python pipeline/intl_pipeline.py approve --date " + date + "` "
              "(or `--exclude domain1,domain2` for \"OK except #n\")\n",
              "| # | Brand | Country (confirmed on) | List | Product | Opening line | Email |",
              "|---|---|---|---|---|---|---|"]
    for i, b in enumerate(pick, 1):
        review.append(f"| {i} | {b['brand']} | {b['country']} ({b.get('legal_page', '')}) | {b['list']} | "
                      f"{b['product']} | {b['opener']} | {b['email']} |")
    (DRAFTS / f"batch-{date}.md").write_text("\n".join(review) + "\n\n" + draft_md(pick, "Full drafts"))
    flagged = [b for b in brands.values() if flag_of(b) and route(b) == "email"]
    print(f"{len(pick)} drafts -> {DRAFTS / f'batch-{date}.md'} ({len(pool) - len(pick)} ready brands left, "
          f"{len(flagged)} flagged brands not drafted)")


def cmd_approve(args):
    p = DRAFTS / f"batch-{args.date}.json"
    batch = json.loads(p.read_text())
    only = set(args.only.split(",")) if args.only else None
    exclude = set(args.exclude.split(",")) if args.exclude else set()
    for it in batch["items"]:
        it["approved"] = (only is None or it["domain"] in only) and it["domain"] not in exclude
    p.write_text(json.dumps(batch, indent=1))
    print(f"approved {sum(it['approved'] for it in batch['items'])}/{len(batch['items'])} in {p.name}")


# ---------------------------------------------------------------- sending

LOG_FIELDS = ["brand", "list", "email", "date_sent", "followup1_date", "followup2_date", "replied",
              "bounced", "unsubscribed", "domain", "subject", "message_id", "resend_ids", "auto_reply", "stopped"]


def read_log():
    if not LOG.exists():
        return []
    with LOG.open(newline="") as f:
        return list(csv.DictReader(f))


def write_log(rows):
    with LOG.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=LOG_FIELDS)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in LOG_FIELDS})


def daily_cap(date):
    """20 on the first sending day, +5 each later sending day, max 40."""
    days = sorted({r["date_sent"] for r in read_log() if r["date_sent"]})
    n = len([d for d in days if d < date]) + 1
    return min(MAX_PER_DAY, START_PER_DAY + STEP_PER_DAY * (n - 1))


def resend_send(to, subject, text, headers, idem, html=None):
    key = os.environ.get("RESEND_API_KEY")
    if not key:
        sys.exit("RESEND_API_KEY is not set")
    r = requests.post("https://api.resend.com/emails", timeout=30, headers={
        "Authorization": f"Bearer {key}", "Content-Type": "application/json", "Idempotency-Key": idem},
        json={"from": FROM, "to": [to], "reply_to": REPLY_TO, "subject": subject, "text": text,
              "html": html or to_html(text), "headers": headers})
    if r.status_code >= 300:
        raise RuntimeError(f"Resend {r.status_code}: {r.text[:300]}")
    return r.json().get("id", "")


SENT = ROOT / "sent"  # exact copy of every email sent to a brand: <domain>-<n>.txt (0 = first email)


def save_sent(domain, n, subject, to, date, msg_id, body):
    SENT.mkdir(exist_ok=True)
    (SENT / f"{domain}-{n}.txt").write_text(
        f"Subject: {subject}\nTo: {to}\nDate: {date}\nMessage-ID: {msg_id}\n\n{body}\n")


def load_sent(domain, n=0):
    """(headers dict, body) of an email we sent, or (None, None) if there is no record of it."""
    p = SENT / f"{domain}-{n}.txt"
    if not p.exists():
        return None, None
    head, _, body = p.read_text().partition("\n\n")
    return dict(l.split(": ", 1) for l in head.splitlines()), body.rstrip("\n")


def quoted(original, date_iso):
    """Plain-text and HTML quote of the original email, like a normal mail client reply."""
    d = dt.date.fromisoformat(date_iso)
    intro = f"On {d.strftime('%a, %-d %b %Y')}, {FROM} wrote:"
    text = intro + "\n" + "\n".join(("> " + l) if l else ">" for l in original.splitlines())
    inner = to_html(original).replace("<!doctype html><html><body>", "").replace("</body></html>", "")
    html = (f"<p>{html_escape(intro)}</p><blockquote style=\"margin:0 0 0 .8ex;border-left:1px solid #ccc;"
            f"padding-left:1ex\">{inner}</blockquote>")
    return text, html


TEST_TO = "info@joinmatchly.com"
TESTS = ROOT / "pipeline" / "email_tests.json"
_DUMMY = {"brand": "Brand", "list": "A", "opener": "Opener.", "creators": "creators", "anett": True,
          "tts_market": "UK", "tts_market_confirmed": True}


def template_hash(kind):
    """Fingerprint of an email type's current wording/layout (initial_A, initial_B, followup1, followup2)."""
    import hashlib
    if kind.startswith("initial"):
        text = render({**_DUMMY, "list": kind[-1]})[1]
    else:
        text = render_followup(_DUMMY, int(kind[-1]))
    return hashlib.sha1(to_html(text).encode()).hexdigest()[:12]


def require_test(kind):
    """Rule: before any new type of email goes out, one test must have gone to info@joinmatchly.com."""
    done = load_json(TESTS, {})
    if done.get(kind, {}).get("hash") != template_hash(kind):
        sys.exit(f"No test sent for the current '{kind}' email. Run: test --kind {kind} (sends to {TEST_TO})")


def cmd_test(args):
    brands = curated()
    b = brands[args.domain] if args.domain else next(x for x in brands.values() if ready(x) and x["list"] == (
        args.kind[-1] if args.kind.startswith("initial") else "A"))
    if args.kind.startswith("initial"):
        b = {**b, "list": args.kind[-1]}
        subject, text = render(b)
    else:
        subject, text = "Re: " + render(b)[0], render_followup(b, int(args.kind[-1]))
    rid = resend_send(args.to, f"[TEST] {subject}", text, unsubscribe_header(),
                      idem=f"test-{args.kind}-{template_hash(args.kind)}-{b['domain']}-{args.to}")
    done = load_json(TESTS, {})
    done[args.kind] = {"hash": template_hash(args.kind), "sent_to": args.to, "brand": b["brand"],
                       "date": dt.datetime.now(TZ).isoformat(timespec="minutes"), "resend_id": rid}
    TESTS.write_text(json.dumps(done, indent=1))
    print(f"test '{args.kind}' ({b['brand']}) sent to {args.to}")


def unsubscribe_header():
    return {"List-Unsubscribe": f"<mailto:{REPLY_TO}?subject=unsubscribe>"}


def cmd_send(args):
    if args.go and args.date > today().isoformat():
        sys.exit(f"batch {args.date} is scheduled for {args.date}; refusing to send it early (today is {today()})")
    batch = json.loads((DRAFTS / f"batch-{args.date}.json").read_text())
    brands = curated()
    log = read_log()
    sent = {r["email"].lower() for r in log}
    now = today().isoformat()
    cap = daily_cap(now) - sum(1 for r in log if r["date_sent"] == now)
    todo = [brands[it["domain"]] for it in batch["items"] if it["approved"] and it["domain"] in brands
            and brands[it["domain"]]["email"].lower() not in sent]
    held = [b["brand"] for b in todo if not ready(b)]  # rules re-checked at send time
    if held:
        print(f"held back (no longer pass the rulebook): {', '.join(held)}")
    todo = [b for b in todo if ready(b)]
    todo = todo[:max(cap, 0)]
    if args.go:
        for kind in sorted({f"initial_{b['list']}" for b in todo}):
            require_test(kind)
    print(f"{len(todo)} to send today (cap left {cap})")
    for b in todo:
        subject, body = render(b)
        if not args.go:
            print(f"  would send: {b['brand']} <{b['email']}>")
            continue
        msg_id = f"<{uuid.uuid4()}@outreach.joinmatchly.com>"
        try:
            rid = resend_send(b["email"], subject, body, {"Message-ID": msg_id, **unsubscribe_header()},
                              idem=f"intl-{b['domain']}-0")
        except Exception as e:
            print(f"  FAILED {b['brand']}: {e}")
            continue
        save_sent(b["domain"], 0, subject, b["email"], now, msg_id, body)
        log.append({"brand": b["brand"], "list": b["list"], "email": b["email"], "date_sent": now,
                    "replied": "no", "bounced": "no", "unsubscribed": "no", "domain": b["domain"],
                    "subject": subject, "message_id": msg_id, "resend_ids": rid})
        write_log(log)
        print(f"  sent: {b['brand']} <{b['email']}>")
        time.sleep(args.pause)
    if not args.go:
        print("dry run: add --go to send")


def cmd_followup(args):
    log = read_log()
    brands = curated()
    now = today()
    due = []
    for r in log:
        # Auto-replies don't count as replies; only an explicit stop (e.g. an auto-reply asking us not to
        # write again) ends follow-ups to that address.
        if "yes" in (r["replied"], r["bounced"], r["unsubscribed"]) or r.get("stopped") or not r["date_sent"]:
            continue
        sent = dt.date.fromisoformat(r["date_sent"])
        for n, days in enumerate(FOLLOWUP_DAYS, 1):
            field = f"followup{n}_date"
            if not r[field] and (now - sent).days >= days and (n == 1 or r["followup1_date"]):
                due.append((r, n))
                break
    # Rule: never follow up with anyone who hasn't received the first email. Requires the logged send
    # (date, Message-ID, Resend id) AND the saved copy of that email, which is quoted below the follow-up.
    ok = []
    for r, n in due:
        hdr, original = load_sent(r["domain"], 0)
        if not (r["date_sent"] and r["message_id"] and r["resend_ids"] and original
                and hdr.get("To", "").lower() == r["email"].lower()):
            print(f"  SKIP {r['brand']} <{r['email']}>: no record of a first email to this address")
            continue
        ok.append((r, n, original))
    print(f"{len(ok)} follow-ups due")
    for r, n, original in ok:
        b = brands.get(r["domain"]) or {"brand": r["brand"]}
        greeting = original.splitlines()[0] if original.startswith("Hi ") else None
        reply = render_followup(b, n, greeting)
        q_text, q_html = quoted(original, r["date_sent"])
        text = reply + "\n\n" + q_text
        html = to_html(reply).replace("</body></html>", q_html + "</body></html>")
        if not args.go:
            print(f"  would send follow-up {n}: {r['brand']} <{r['email']}>")
            continue
        headers = {"In-Reply-To": r["message_id"], "References": r["message_id"],
                   "Message-ID": f"<{uuid.uuid4()}@outreach.joinmatchly.com>", **unsubscribe_header()}
        try:
            rid = resend_send(r["email"], "Re: " + r["subject"], text, headers, idem=f"intl-{r['domain']}-{n}",
                              html=html)
        except Exception as e:
            print(f"  FAILED {r['brand']}: {e}")
            continue
        save_sent(r["domain"], n, "Re: " + r["subject"], r["email"], now.isoformat(), headers["Message-ID"], text)
        r[f"followup{n}_date"] = now.isoformat()
        r["resend_ids"] = (r["resend_ids"] + " " + rid).strip()
        write_log(log)
        print(f"  sent follow-up {n}: {r['brand']}")
        time.sleep(args.pause)
    if not args.go:
        print("dry run: add --go to send")


def cmd_mark(args):
    log = read_log()
    hit = [r for r in log if r["email"].lower() == args.email.lower() or r["domain"] == args.email.lower()]
    if not hit:
        sys.exit(f"{args.email} not in log.csv")
    for r in hit:
        for f in ("replied", "bounced", "unsubscribed"):
            if getattr(args, f):
                r[f] = "yes"
        if args.auto_reply:  # recorded only; follow-ups continue
            r["auto_reply"] = (r.get("auto_reply", "") + f" {today().isoformat()}: {args.auto_reply}").strip()
        if args.stop:        # e.g. auto-reply asking not to send more messages
            r["stopped"] = f"{today().isoformat()}: {args.stop}"
    write_log(log)
    print(f"updated {len(hit)} row(s)")


def cmd_sync(args):
    """Mark bounces from Resend's email status. Needs a key with read access (RESEND_READ_KEY)."""
    key = os.environ.get("RESEND_READ_KEY") or os.environ.get("RESEND_API_KEY")
    log = read_log()
    changed = 0
    for r in log:
        if r["bounced"] == "yes":
            continue
        for rid in r["resend_ids"].split():
            resp = requests.get(f"https://api.resend.com/emails/{rid}", timeout=30,
                                headers={"Authorization": f"Bearer {key}"})
            if resp.status_code == 401:
                sys.exit("This Resend key can only send. Set RESEND_READ_KEY (full access) to sync bounces, "
                         "or mark them with: mark EMAIL --bounced")
            if resp.ok and resp.json().get("last_event") in ("bounced", "complained"):
                r["bounced"] = "yes"
                changed += 1
    write_log(log)
    print(f"{changed} new bounces marked")


def cmd_status(args):
    log = read_log()
    now = today().isoformat()
    print(f"sent total {len(log)}, today {sum(1 for r in log if r['date_sent'] == now)}, cap today {daily_cap(now)}")
    for f in ("replied", "bounced", "unsubscribed"):
        print(f"{f}: {sum(1 for r in log if r[f] == 'yes')}")


def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("source")
    s.add_argument("--set", help="comma-separated query set names from intl_queries.json")
    s.add_argument("--max-searches", type=int, default=60)
    e = sub.add_parser("enrich")
    e.add_argument("--domains", help="comma-separated domains to (re)enrich, e.g. hand-added brands")
    e.add_argument("--seeds", action="store_true", help="also enrich pipeline/intl_seeds.txt")
    sub.add_parser("triage")
    sub.add_parser("output")
    d = sub.add_parser("draft")
    d.add_argument("--date")
    d.add_argument("--size", type=int)
    d.add_argument("--samples", action="store_true")
    d.add_argument("--force", action="store_true")
    a = sub.add_parser("approve")
    a.add_argument("--date", required=True)
    a.add_argument("--only")
    a.add_argument("--exclude")
    se = sub.add_parser("send")
    se.add_argument("--date", required=True)
    se.add_argument("--go", action="store_true")
    se.add_argument("--pause", type=float, default=45, help="seconds between emails")
    f = sub.add_parser("followup")
    f.add_argument("--go", action="store_true")
    f.add_argument("--pause", type=float, default=30)
    m = sub.add_parser("mark")
    m.add_argument("email", help="email or domain")
    m.add_argument("--replied", action="store_true")
    m.add_argument("--bounced", action="store_true")
    m.add_argument("--unsubscribed", action="store_true")
    m.add_argument("--auto-reply", help="note an auto-reply (does NOT count as a reply)")
    m.add_argument("--stop", help="stop follow-ups to this address, with the reason")
    t = sub.add_parser("test")
    # Tests are the full first email (with its opener). Follow-up tests only when the user asks for one.
    t.add_argument("--kind", required=True, choices=["initial_A", "initial_B", "followup1", "followup2"])
    t.add_argument("--domain", help="brand to render (default: first ready brand)")
    t.add_argument("--to", default=TEST_TO)
    sub.add_parser("sync")
    sub.add_parser("status")
    args = p.parse_args()
    globals()["cmd_" + args.cmd](args)


if __name__ == "__main__":
    main()
