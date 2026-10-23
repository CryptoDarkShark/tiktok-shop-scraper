"""usage: python3 -I deep.py URL... : find operator company names on legal pages (raw text, incl. scripts)."""
import requests,re,html,sys,urllib.parse,concurrent.futures
UA={"User-Agent":"Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120 Safari/537.36"}
STOP=re.compile(r"Barion|OTP|GLS|Posta|Packeta|Foxpost|Sprinter|DPD|Express|Billingo|Számlázz|KBOSS|Shopify|UNAS|Shoprenter|Árukereső|Google|Meta|Facebook|MPL|Webshippy|Raiffeisen|CIB|Erste|K&H|MBH|Unicredit|Gránit|Simple|Magyar Telekom|Tárhely|Rackhost|Dotroll|Wix|Compaya|JUTASA|Fogyasztó Barát|Pénzügyi Békéltető|Netpincér|Sanoma|Webmark|Innocode|Revolut|Wise|Mailchimp|Klaviyo|Webgalamb|SalesAutopilot",re.I)
NAME=re.compile(r"([A-ZÁÉÍÓÖŐÚÜŰ][\w&.\-’' ÁÉÍÓÖŐÚÜŰáéíóöőúüű]{1,50}?\s(?:Korlátolt Felelősségű Társaság|Betéti Társaság|Zártkörűen Működő Részvénytársaság|Kft\.?|Bt\.?|Zrt\.?))(?!\w)")
def run(base):
    try: r=requests.get(base,headers=UA,timeout=20)
    except Exception as e: return base,["ERR "+e.__class__.__name__]
    links=[urllib.parse.urljoin(r.url,html.unescape(l)) for l in re.findall(r'href="([^"#]+)"',r.text)]
    links=[l for l in dict.fromkeys(links) if urllib.parse.urlparse(l).netloc==urllib.parse.urlparse(r.url).netloc and re.search(r"aszf|szerz|impressz|impressum|kapcsolat|rolunk|about|terms|policies|jogi|adatkezel|elerhet",urllib.parse.unquote(l),re.I)][:10]
    found={}
    for u in [r.url]+links:
        try: t=requests.get(u,headers=UA,timeout=20).text
        except Exception: continue
        t=html.unescape(re.sub(r"\\u00([0-9a-f]{2})",lambda m:chr(int(m.group(1),16)),t))
        t=re.sub(r"\s+"," ",re.sub(r"<[^>]+>"," ",t))
        for m in NAME.finditer(t):
            n=m.group(1).strip(); ctx=t[max(0,m.start()-60):m.start()]
            if STOP.search(n) or re.search(r"tárhely|futár|adatfeldolgoz|bank|fizet",ctx,re.I): continue
            n=re.sub(r"^(?:.*?(?:neve|Cégnév|Üzemeltető|Szolgáltató|Eladó|Név)\s*:?\s*)","",n)
            found.setdefault(n,u)
    return base,[f"{k}  <- {v}" for k,v in list(found.items())[:5]]
with concurrent.futures.ThreadPoolExecutor(6) as ex:
    for b,f in ex.map(run,sys.argv[1:]): print("==",b); [print("   ",x) for x in f]
