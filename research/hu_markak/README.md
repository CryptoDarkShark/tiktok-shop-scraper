# Magyar TikTok Shop-jelölt márkák – kutatás

Futtatás dátuma: 2026-10-22. Ebben a körben: **1. Skincare** és **7. Kiegészítők** (a többi csoport külön futás).

| Fájl | Tartalom |
|---|---|
| `1_skincare.csv` | 20 ellenőrzött + 3 „nem igazolt” márka |
| `7_kiegeszitok.csv` | 16 ellenőrzött márka (a cél 20 volt, lásd lent) |
| `kihagyott.csv` | minden megvizsgált, de kiszűrt jelölt az okkal együtt |
| `data/` | nyers ellenőrzési eredmények (`res*.json`) és kézi javítások (`extra.json`) |
| `tools/` | a szkriptek |

## Módszer

1. **Jelöltek**: a repó `brands.xlsx` magyar márkái, sajtó- és toplista-cikkek (welovebudapest, kremmania, helloskin, origo, telex), és célzott domainpróbák.
2. **Cég**: a márka saját weboldalának impresszuma, ÁSZF-je vagy adatkezelési tájékoztatója (forrás oszlop, 1. URL). A tárhely-, futár- és fizetési szolgáltatókat kiszűrtem.
3. **Méret és döntéshozó**: a nemzeticegtar.hu (Opten) nyilvános cégoldala: 2025-ös nettó árbevétel, létszám, cégjegyzésre jogosultak. A lakcímeket kihagytam.
   - Szűrő: árbevétel 100 M–2 Mrd Ft **vagy** 5–50 fő. A 2 Mrd Ft felettiek („túl nagy”) és a mindkét feltétel alattiak („túl kicsi”) a `kihagyott.csv`-be kerültek.
   - Kft./Bt./Zrt. kell; az egyéni vállalkozók kiestek.
4. **TikTok**: a weboldalon linkelt TikTok-profil nyilvános oldala (`ttSeller` jelölés). Ha nincs linkelt profil, vagy a profil nem olvasható: „nem ellenőrizve”.
5. **LinkedIn**: csak nyilvános cégoldal, bejelentkezés nélkül. Csak akkor töltöttem ki, ha az oldal a márka saját domainjére hivatkozik.
6. **Alapító / marketingvezető**: csak akkor szerepel, ha a márka „rólunk” / „csapat” oldala megnevezi (a forrás ott van mellette).

Státusz:
- **ellenőrzött**: a cég, a méret és a döntéshozó mind forrással igazolt.
- **részleges**: a cég megvan, de valami hiányzik.
- **nem igazolt**: ismert márka, de a cégadat nem olvasható (JS-oldal, 403, szkennelt PDF).

## Blokkolt vagy nem elérhető források (nem kerültem meg őket)

- **Meta Ad Library**: a nyilvános felület 403-at adott. A link minden sorban ott van, de nem ellenőriztem.
- **e-cegjegyzek.hu**: innen nem volt elérhető (timeout). Helyette a nemzeticegtar.hu-t használtam.
- **DuckDuckGo**: captchát adott, nem használtam tovább.
- **TikTok Shop publikus kereső**: JS/bot-szűrés miatt nem olvasható. Csak a linkelt profilok `ttSeller` jelölését néztem.
- **Márkaoldalak**: több oldal 403-at adott (Maskaolin, Artidia, egyeditok.hu, taskaweb.hu, ekszerbirodalom.hu), nem volt elérhető (TEO Sunglasses, Kócos, Gábor Kiss), lejárt a TLS-tanúsítványa (CoolVision), vagy bontotta a kapcsolatot (Tisza). A részletek a `kihagyott.csv`-ben vannak.

## Ismert hiányok

- **Kiegészítők: 16/20.** A magyar tervezői táska- és ékszermárkák nagy része egyéni vállalkozó vagy 100 M Ft alatti. A középméretű telefontok-, kábel- és fülhallgató-cégek vagy túl nagyok (Cellect, Mobilfox), vagy nem magyar márkák. Több ellenőrzött sor viszonteladó webáruház, nem saját márka (Telefontok.hu, Tok-shop, Webszemüveg.hu, Óraszalon, Órabirodalom, Szputnyik shop).
- **Marketingvezető**: csak a Thinwoodnál találtam név szerint (Bakos Kata), de a Thinwood a méretszűrőn kiesett (54 M Ft, 2 fő). Máshol üres. A nyilvános oldalak ritkán neveznek meg ilyen szerepet, nevet pedig nem találtam ki.
- **TikTok Shop**: a 36 ellenőrzött márka egyikénél sem láttam TikTok Shop-eladó jelölést. Ahol olvasható profil van, ott „nem” szerepel, a többinél „nem ellenőrizve”.
- **Közös cég**: a PHINICHE és az Almost 1.618 ugyanaz a cég (TINATI Natural Kft.). A Steeel és az EkszerWebshop.hu szintén közös (Camelot Consulting Kft.); az utóbbi ezért a kihagyottak között van.
