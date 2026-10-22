"""usage: python3 -I team.py res.json [res2.json...] : find marketing/founder names on about/team pages."""
import html
import json
import re
import sys
import urllib.parse

import requests

UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120 Safari/537.36"}
WORDS = re.compile(r"rolunk|rólunk|csapat|about|tortenet|történet|team|alapito|alapító|kapcsolat|contact|sajto|sajtó|press", re.I)
ROLE = re.compile(r"marketing|PR\b|sajtó|kommunikáció|social media|brand manager|alapító|founder|tulajdonos|ügyvezető|CEO", re.I)


def T(h):
    h = re.sub(r"<script.*?</script>|<style.*?</style>", "", h, flags=re.S)
    return re.sub(r"(\|\s*)+", "| ", html.unescape(re.sub(r"\s+", " ", re.sub("<[^>]+>", " | ", h))))


for p in sys.argv[1:]:
    for r in json.load(open(p)):
        try:
            home = requests.get(r["website"], headers=UA, timeout=20)
        except Exception:
            continue
        links = []
        for l in re.findall(r'href="([^"#]+)"', home.text):
            u = urllib.parse.urljoin(home.url, html.unescape(l))
            if urllib.parse.urlparse(u).netloc == urllib.parse.urlparse(home.url).netloc and WORDS.search(
                    urllib.parse.unquote(u)) and u not in links:
                links.append(u)
        hits = []
        for u in links[:6]:
            try:
                t = T(requests.get(u, headers=UA, timeout=20).text)
            except Exception:
                continue
            for m in ROLE.finditer(t):
                ctx = t[max(0, m.start() - 90):m.end() + 60]
                if re.search(r"[A-ZÁÉÍÓÖŐÚÜŰ][a-záéíóöőúüű]+ [A-ZÁÉÍÓÖŐÚÜŰ][a-záéíóöőúüű]+", ctx) and not re.search(
                        r"cookie|süti|hozzájárul|adatkezel", ctx, re.I):
                    hits.append((u, ctx))
        seen = set()
        print("==", r["brand"], r["website"])
        for u, ctx in hits:
            if ctx not in seen and len(seen) < 6:
                seen.add(ctx)
                print("   ", u, "::", ctx)
