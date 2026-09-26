"""Collect every email a brand publishes on its own pages (home, contact, about, press,
affiliate/partnership, legal) with surrounding text, and rank them by the contact priority.

    python pipeline/email_scan.py DOMAIN [DOMAIN ...]      # prints ranked addresses
    python pipeline/email_scan.py --batch 2026-09-28 [--apply]  # whole batch; --apply updates intl_curation.json
"""
import argparse
import json
import re
import sys
from pathlib import Path
from urllib.parse import urljoin

from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).resolve().parent))
import intl_pipeline as ip  # noqa: E402

LINK_WORDS = ["contact", "kontakt", "about", "o-nas", "press", "media", "affiliate", "partner", "collab",
              "influenc", "ambassador", "creator", "wholesale", "b2b", "stockist", "terms", "privacy", "legal",
              "regulamin", "mentions", "impressum", "polityka", "careers", "faq", "help"]
EXTRA = ["pages/contact", "pages/contact-us", "pages/about-us", "pages/affiliates", "pages/affiliate",
         "pages/partnerships", "pages/press", "policies/contact-information", "policies/terms-of-service"]


def scan(domain, website):
    found = {}
    final, html = ip.fetch(website)
    if not html:
        return found
    home = BeautifulSoup(html, "html.parser")
    urls = [final] + ip.find_links(home, final, LINK_WORDS, limit=14) + [urljoin(final, e) for e in EXTRA]
    seen = set()
    for u in urls:
        u = u.split("#")[0]
        if u in seen or len(seen) >= 20:
            continue
        seen.add(u)
        f, h = (final, html) if u == final else ip.fetch(u)
        if not h:
            continue
        text = re.sub(r"\s+", " ", BeautifulSoup(h, "html.parser").get_text(" "))
        text = re.sub(r"\s*(?:\[at\]|\(at\)|\[@\]|\(@\))\s*", "@", text)
        emails = set(ip.EMAIL_RE.findall(text)) | set(ip.cf_emails(h)) | \
            {m.split("?")[0] for m in re.findall(r'mailto:([^"\'>\s]+)', h)}
        for e in emails:
            m = ip.EMAIL_RE.search(e)
            if not m:
                continue
            e = m.group(0).lower().strip(".")
            i = text.lower().find(e)
            ctx = text[max(0, i - 120): i + 40] if i >= 0 else ""
            found.setdefault(e, {"page": f, "context": ctx})
    return found


def ranked(domain, found):
    ctx = {e: v["context"] for e, v in found.items()}
    own = [e for e in ip.pick_emails(found, domain, ctx)]
    return [(e, ip.email_tier(e, ctx.get(e, "")), found[e]["page"]) for e in own]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("domains", nargs="*")
    ap.add_argument("--batch")
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    brands = ip.curated()
    doms = a.domains or [it["domain"] for it in json.loads((ip.DRAFTS / f"batch-{a.batch}.json").read_text())["items"]]
    cur = json.loads(ip.CURATION.read_text())
    changes = []
    for d in doms:
        b = brands[d]
        site_root = ip.domain_of(b["website"]).split(".")[-2]
        found = scan(d, b["website"])
        r = [x for x in ranked(ip.domain_of(b["website"]), found)
             if site_root in x[0].split("@")[1] or d.split(".")[-2] in x[0].split("@")[1]]
        best = r[0] if r else None
        print(f"== {b['brand']} (current {b['email']})")
        for e, t, pg in r[:6]:
            print(f"   tier {t}  {e}  ({pg})")
        cur_t = ip.email_tier(b["email"], found.get(b["email"], {}).get("context", ""))
        if best and best[0] != b["email"] and best[1] < cur_t:
            changes.append((d, b["brand"], b["email"], best[0], best[1], best[2]))
    print("\nCHANGES:")
    for d, brand, old, new, t, pg in changes:
        print(f"  {brand}: {old} -> {new} (tier {t}, found on {pg})")
        if a.apply:
            cur["brands"][d]["email"] = new
            cur["brands"][d]["email_source"] = pg
    if a.apply:
        ip.CURATION.write_text(json.dumps(cur, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
