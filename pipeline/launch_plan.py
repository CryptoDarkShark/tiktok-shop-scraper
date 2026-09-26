"""Launch plans for brands that replied (see launch_plan_template.md).

    python pipeline/launch_plan.py replied EMAIL   # mark replied (stops follow-ups) + create plans/<domain>.json
    python pipeline/launch_plan.py build DOMAIN    # validate plans/<domain>.json -> .md + one-page .pdf + reply draft

plans/<domain>.json is filled in by hand from the brand's own site: 3 products (10-60 EUR,
with source URL), one "why this brand" sentence and 5 video angles. Creators are matched
automatically from creators.csv by category; nothing is invented, unknown values stay blank.
"""
import argparse
import csv
import datetime as dt
import html
import json
import re
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
import intl_pipeline as ip  # noqa: E402

ROOT = ip.ROOT
PLANS = ROOT / "plans"
TEMPLATE = ROOT / "launch_plan_template.md"
CREATORS = ROOT / "creators.csv"
CHROME = "/opt/pw-browsers/chromium-1194/chrome-linux/chrome"
MAX_CREATORS = 5
SETUP = {"A": "We switch on Hungary in your existing Seller Center.",
         "B": "We set up your TikTok Shop and switch on Hungary."}
# Brand category keywords -> creators.csv categories that fit them.
CATEGORY_MATCH = [
    (r"beauty|skin|makeup|nail|hair|tan|lip|cosmetic", {"beauty", "lifestyle"}),
    (r"fitness|sport|supplement|nutrition|protein", {"fitness"}),
    (r"fashion|jewel|accessor", {"beauty", "lifestyle"}),
    (r"home|kitchen|gift|toy|kids|baby|pet|lifestyle|gadget", {"lifestyle"}),
]


def eur_rates():
    """ECB reference rates: {'HUF': ..., 'GBP': ..., 'PLN': ...} per 1 EUR."""
    xml = requests.get("https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml", timeout=20).text
    rates = {"EUR": 1.0}
    for el in ET.fromstring(xml).iter():
        if el.get("currency"):
            rates[el.get("currency")] = float(el.get("rate"))
    return rates


def to_huf(amount, currency, rates):
    """Approximate Ft price, rounded to the nearest 100."""
    eur = amount / rates[currency]
    return eur, int(round(eur * rates["HUF"], -2))


def creators_for(category):
    rows = list(csv.DictReader(CREATORS.open()))
    want = set()
    for rx, cats in CATEGORY_MATCH:
        if re.search(rx, category, re.I):
            want |= cats
    picked = [r for r in rows if want & set(filter(None, r["category"].split("/")))]
    return picked[:MAX_CREATORS]


def cmd_replied(args):
    log = ip.read_log()
    hit = [r for r in log if r["email"].lower() == args.email.lower()]
    if not hit:
        sys.exit(f"{args.email} is not in log.csv")
    for r in hit:
        r["replied"] = "yes"
    ip.write_log(log)
    domain = hit[0]["domain"]
    b = ip.curated().get(domain)
    if not b:
        sys.exit(f"{domain} not in intl_curation.json")
    PLANS.mkdir(exist_ok=True)
    p = PLANS / f"{domain}.json"
    if not p.exists():
        p.write_text(json.dumps({
            "domain": domain, "brand": b["brand"], "list": b["list"], "email": b["email"],
            "subject": hit[0]["subject"], "contact_name": b.get("first_name") or f"the {b['brand']} team",
            "category": "", "why_this_brand": "",
            "products": [{"name": "", "price": None, "currency": "", "why": "", "source": ""} for _ in range(3)],
            "angles": ["", "", "", "", ""],
            "creators": [dict(r) for r in creators_for(b["category"])],
        }, ensure_ascii=False, indent=1))
    print(f"marked {args.email} as replied (follow-ups stopped); fill in {p} then run: build {domain}")


def validate(plan):
    errs = []
    if not plan["category"]:
        errs.append("category (e.g. 'beauty and skincare')")
    if not plan["why_this_brand"]:
        errs.append("why_this_brand")
    for i, pr in enumerate(plan["products"], 1):
        if not (pr["name"] and pr["price"] and pr["currency"] and pr["why"] and pr["source"]):
            errs.append(f"product {i} incomplete")
    if len([a for a in plan["angles"] if a]) != 5:
        errs.append("5 video angles")
    return errs


def md_table(header, rows):
    return "\n".join([f"| {' | '.join(header)} |", "|" + "---|" * len(header)] +
                     [f"| {' | '.join(r)} |" for r in rows])


def render_md(plan, rates):
    t = TEMPLATE.read_text()
    date = ip.today().strftime("%-d %B %Y")
    vals = {"BRAND": plan["brand"], "CONTACT_NAME": plan["contact_name"], "DATE": date,
            "CATEGORY": plan["category"], "ONE_SENTENCE_WHY_THIS_BRAND": plan["why_this_brand"],
            "SETUP_STEP": SETUP[plan["list"]], "VIDEO_COUNT": str(len(plan["creators"]) * 3)}
    prod_rows, warn = [], []
    for pr in plan["products"]:
        eur, huf = to_huf(float(pr["price"]), pr["currency"], rates)
        if not ip.PRICE_RANGE_EUR[0] * 0.8 <= eur <= ip.PRICE_RANGE_EUR[1] * 1.2:
            warn.append(f"{pr['name']}: ~{eur:.0f} EUR is outside 10-60 EUR")
        prod_rows.append([pr["name"], f"~{huf:,} Ft".replace(",", " "), pr["why"]])
    t = re.sub(r"\| Product \| Price in Hungary \| Why it works on TikTok \|\n(\|.*\n){3}",
               md_table(["Product", "Price in Hungary", "Why it works on TikTok"], prod_rows) + "\n", t)
    fmt = lambda n: f"{int(n):,}".replace(",", " ") if str(n).isdigit() else ""
    cre_rows = [[c["name"], c["tiktok"], fmt(c["followers"]), why_fit(c)] for c in plan["creators"]]
    t = t.replace("| Creator | TikTok | Followers | Why they fit |\n(up to 5 rows from creators.csv)",
                  md_table(["Creator", "TikTok", "Followers", "Why they fit"], cre_rows))
    t = t.replace("1-5: {{ANGLES}}", "\n".join(f"{i}. {a}" for i, a in enumerate(plan["angles"], 1)))
    for k, v in vals.items():
        t = t.replace("{{" + k + "}}", v)
    left = re.findall(r"\{\{\w+\}\}", t)
    if left:
        sys.exit(f"unfilled placeholders: {left}")
    return t, warn


def why_fit(c):
    cat = c["category"].replace("/", " and ")
    return f"{cat.capitalize()} creator, affiliate confirmed" if cat else "Affiliate confirmed (niche not recorded)"


def md_to_html(md, title):
    out, lines, i = [], md.splitlines(), 0
    inline = lambda s: re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", html.escape(s))
    while i < len(lines):
        ln = lines[i]
        if ln.startswith("# "):
            out.append(f"<h1>{inline(ln[2:])}</h1>")
        elif ln.startswith("## "):
            out.append(f"<h2>{inline(ln[3:])}</h2>")
        elif ln.startswith("|"):
            rows = []
            while i < len(lines) and lines[i].startswith("|"):
                if not re.match(r"^\|(-+\|)+$", lines[i]):
                    rows.append([c.strip() for c in lines[i].strip("|").split("|")])
                i += 1
            out.append("<table><tr>" + "".join(f"<th>{inline(c)}</th>" for c in rows[0]) + "</tr>" +
                       "".join("<tr>" + "".join(f"<td>{inline(c)}</td>" for c in r) + "</tr>" for r in rows[1:]) +
                       "</table>")
            continue
        elif re.match(r"^\d+\. ", ln):
            items = []
            while i < len(lines) and re.match(r"^\d+\. ", lines[i]):
                items.append(f"<li>{inline(lines[i].split('. ', 1)[1])}</li>")
                i += 1
            out.append("<ol>" + "".join(items) + "</ol>")
            continue
        elif ln.strip():
            head, sep, rest = ln.partition(": ")
            if sep and len(head) < 30 and not ln.startswith("Prepared"):
                out.append(f"<p><b>{inline(head)}:</b> {inline(rest)}</p>")
            else:
                out.append(f"<p>{inline(ln)}</p>")
        i += 1
    css = """@page{size:A4;margin:11mm 13mm}body{font-family:Helvetica,Arial,sans-serif;font-size:8.6pt;
line-height:1.32;color:#1d1d1f}h1{font-size:15pt;margin:0 0 2px;color:#111}h1+p{color:#666;margin:0 0 6px}
h2{font-size:10pt;margin:8px 0 3px;padding-bottom:2px;border-bottom:1px solid #ddd;color:#111}p{margin:2px 0}
table{border-collapse:collapse;width:100%;margin:3px 0}th,td{border:1px solid #ddd;padding:2px 5px;text-align:left;
vertical-align:top}th{background:#f4f4f5}ol{margin:2px 0 2px 16px;padding:0}li{margin:1px 0}"""
    return f"<!doctype html><html><head><meta charset='utf-8'><title>{html.escape(title)}</title>" \
           f"<style>{css}</style></head><body>{''.join(out)}</body></html>"


def to_pdf(html_text, pdf_path):
    with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False) as f:
        f.write(html_text)
    subprocess.run([CHROME, "--headless", "--no-sandbox", "--disable-gpu", "--no-pdf-header-footer",
                    f"--print-to-pdf={pdf_path}", f"file://{f.name}"], check=True, capture_output=True)
    pages = len(re.findall(rb"/Type\s*/Page[^s]", pdf_path.read_bytes()))
    return pages


def reply_draft(plan):
    name = plan["contact_name"] if not plan["contact_name"].startswith("the ") else f"{plan['brand']} team"
    return f"""Subject: Re: {plan['subject']}

Hi {name},

Thanks for getting back to me. As promised, I've attached the Hungarian TikTok Shop launch plan for {plan['brand']}: the three products I'd start with, the creators I'd match and what the first 30 days look like.

Would a 15-minute call this week work to confirm the products and creators? Then we can start setup within the week.

Viktor

Fazekas Viktor
Founder, Matchly · +36 30 690 0060
"""


def cmd_build(args):
    p = PLANS / f"{args.domain}.json"
    plan = json.loads(p.read_text())
    errs = validate(plan)
    if errs:
        sys.exit("missing: " + "; ".join(errs))
    md, warn = render_md(plan, eur_rates())
    name = f"{plan['brand']} - Hungarian TikTok Shop Launch Plan"
    (PLANS / f"{name}.md").write_text(md)
    pages = to_pdf(md_to_html(md, name), PLANS / f"{name}.pdf")
    (PLANS / f"{args.domain}-reply.txt").write_text(reply_draft(plan))
    print(f"-> plans/{name}.pdf ({pages} page{'s' if pages != 1 else ''})")
    print(f"-> plans/{args.domain}-reply.txt")
    for w in warn + ([f"PDF is {pages} pages, not 1"] if pages != 1 else []):
        print("WARNING:", w)
    missing = [c["name"] for c in plan["creators"] if not c["followers"] or not c["category"]]
    if missing:
        print("creators with blank followers/category:", ", ".join(missing))


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("replied")
    r.add_argument("email")
    b = sub.add_parser("build")
    b.add_argument("domain")
    a = ap.parse_args()
    {"replied": cmd_replied, "build": cmd_build}[a.cmd](a)


if __name__ == "__main__":
    main()
