"""usage: python3 -I legal.py URL [URL...] : print legal-page links and company/registry snippets."""
import requests,re,html,sys,urllib.parse
UA={"User-Agent":"Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120 Safari/537.36"}
def T(h): return html.unescape(re.sub(r'\s+',' ',re.sub('<[^>]+>',' ',re.sub(r'<script.*?</script>|<style.*?</style>','',h,flags=re.S))))
for base in sys.argv[1:]:
    try:
        r=requests.get(base,headers=UA,timeout=25)
    except Exception as e:
        print(base,'ERR',e); continue
    ls=sorted(set(urllib.parse.urljoin(r.url,html.unescape(l)) for l in re.findall(r'href="([^"#]+)"',r.text)))
    legal=[l for l in ls if re.search('aszf|szerz|impr|terms|policies/legal|jogi|rolunk|about',l,re.I)][:6]
    print('==',base,r.status_code,legal)
    for u in [r.url]+legal:
        try: t=T(requests.get(u,headers=UA,timeout=25).text)
        except Exception: continue
        hits=list(re.finditer(r'.{0,120}(Kft\.?|Bt\.|Zrt\.|Korlátolt Felelősségű|Betéti Társaság|cégjegyzékszám|Cg\.|ügyvezető|alapító).{0,160}',t,re.I))[:3]
        for m in hits: print('   ',u,'::',m.group(0))
