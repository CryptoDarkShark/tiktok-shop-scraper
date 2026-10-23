# Magyar TikTok Shop-jelölt márkák – kutatás

Futtatás: 2026-10-22 (skincare, kiegészítők) és 2026-10-23 (a többi csoport, kiegészítők folytatása).

## Összefoglaló

A 20-as célba csak a **saját márkák** számítanak (`márkatípus` = „saját márka”). A viszonteladó webshopok is benne vannak a CSV-kben, de külön jelölve, és nem számolom őket a 20-ba.

| Csoport | Fájl | Saját márka (ellenőrzött + részleges) | Viszonteladó | Nem igazolt | Hiány a 20-hoz |
|---|---|---|---|---|---|
| 1. Skincare | `1_skincare.csv` | **20** | 0 | 3 | 0 |
| 2. Supplement | `2_supplement.csv` | **16** | 2 | 0 | 4 |
| 3. Smink | `3_smink.csv` | **3** (1 részleges) | 0 | 0 | 17 |
| 4. Ruházat | `4_ruhazat.csv` | **11** (1 részleges) | 2 | 0 | 9 |
| 5. Sportkiegészítő | `5_sportkiegeszito.csv` | **3** (a Vivamax saját márka + viszonteladó) | 4 | 0 | 17 |
| 6. Hajápolás | `6_hajapolas.csv` | **2** | 6 | 0 | 18 |
| 7. Kiegészítők | `7_kiegeszitok.csv` | **10** | 8 | 0 | 10 |

`kihagyott.csv`: 242 megvizsgált, de kiszűrt jelölt, mindegyik mellett az ok.

## Miért nincs meg mindenhol a 20

- **Smink**: kevés a magyar sminkmárka.
  - A Helia-D körüli márkák vagy túl nagyok, vagy nem találtam meg a cégüket. A Nora Beauty üzemeltetője, a HELIA-D & NÓRA Kft. nincs benne a nemzeticegtar keresőjében, ezért „részleges”.
  - A KAP 36 M Ft-tal túl kicsi.
  - A „PomPom” és a „Gloss Twins” domainje nem a márkáé.
  - A többi találat külföldi márka.
- **Hajápolás**: a magyar hajápolási piacot nagy cégek uralják: Kallos (8,9 Mrd Ft), Luxoya/CosmoPro (10,6 Mrd Ft), Hair-Line (2,8 Mrd Ft). A középméretű szereplők szinte mind fodrászkellék-viszonteladók. Saját márkát csak a Wipe Hairnél és az NVNT Haircare-nél (Bódi Ákos) találtam. Hajszárítót gyártó magyar márkát nem találtam.
- **Sportkiegészítő**:
  - A magyar edzőruha-márkák nagy része egyéni vállalkozó vagy 100 M Ft alatti (Beyond by ST, CCK, Toti), illetve felszámolás alatt áll (Dark Fitness).
  - A középméretű cégek szinte mind viszonteladók.
  - A Dorko, a Gymbeam, a Fitshop és a G&T cipő oldala blokkolt (403).
- **Ruházat**: sok tervezői márka egyéni vállalkozó vagy 100 M Ft alatti (Valid, Zhoja, Király Beáta, Matyodesign, Cabala, OAT AVA, Viktoriabolla). Több oldal blokkolt: Retro Jeans, Dorko, Pizsi, Süel, Aeron (403/406), NON+ (429).
- **Kiegészítők**:
  - A táska- és ékszertervezők többnyire egyéni vállalkozók vagy túl kicsik.
  - A telefontok-, kábel- és fülhallgató-cégek vagy túl nagyok (Cellect, Mobilfox), vagy viszonteladók.
- **Supplement**:
  - Túl nagy: YiYa (2,4 Mrd Ft), Interherb (2,2 Mrd Ft), GAL, Natur Tanya, BioTechUSA, Bioextra, Cerbona.
  - Több webshopnál nem olvasható a cégadat (JavaScripttel töltődik): Nutriversum, Flavin7, Pure Gold, Jutavit, Mannavita, Myshape, Damona.

## Módszer (minden csoportnál ugyanaz)

1. **Jelöltek**: sajtó- és toplista-cikkek (welovebudapest, kremmania, szinte.hu, mrsale, yourstyleguide, zoldgardrob, origo, telex), a repó `brands.xlsx` fájlja és célzott domainpróbák.
2. **Cég**: a márka saját impresszuma, ÁSZF-je vagy adatkezelési tájékoztatója (forrás oszlop, 1. URL). A tárhely-, futár-, bank- és fizetési szolgáltatókat kiszűrtem. A téves találatokat kézzel javítottam (`data/extra.json`).
3. **Méret és döntéshozó**: a nemzeticegtar.hu (Opten) nyilvános cégoldala: 2025-ös nettó árbevétel, létszám, cégjegyzésre jogosultak. A lakcímeket kihagytam.
   - Szűrő: árbevétel 100 M–2 Mrd Ft **vagy** 5–50 fő.
   - Kft./Bt./Zrt. kell; az egyéni vállalkozók, valamint a felszámolás és végelszámolás alatt álló cégek kiestek.
4. **Márkatípus**: ha a kínálat főleg más gyártók termékeiből áll, „viszonteladó webshop”. Ilyen például a Gyémántsziget (Tommy Hilfiger, Guess) és a Lachmann (Olymp, Pierre Cardin).
5. **TikTok**: a weboldalon linkelt TikTok-profil nyilvános oldala (`ttSeller` jelölés). Ha nincs linkelt profil, vagy nem olvasható: „nem ellenőrizve”.
6. **LinkedIn**: csak nyilvános cégoldal, bejelentkezés nélkül. Csak akkor töltöttem ki, ha az oldal a márka domainjére hivatkozik. A 2026-10-23-i futás közben a LinkedIn 999-es választ (bot-limit) adott. Itt leállítottam, ezért a supplement-lista egy részénél és az utána következő csoportoknál a LinkedIn-oszlop nincs végigellenőrizve.
7. **Alapító / marketingvezető**: csak ha a márka saját oldala vagy egy cikk megnevezi (a forrás ott van mellette).

Státusz:
- **ellenőrzött**: a cég, a méret és a döntéshozó mind forrással igazolt.
- **részleges**: a cég megvan, de az adat hiányos vagy bizonytalan (pl. AXAMO: valószínű névváltozás).
- **nem igazolt**: ismert márka, de a cégadat nem olvasható.

## Blokkolt vagy nem elérhető források (nem kerültem meg őket)

- **Meta Ad Library**: 403. A link minden sorban ott van, de nem ellenőriztem.
- **e-cegjegyzek.hu**: nem volt elérhető. Helyette a nemzeticegtar.hu-t használtam.
- **DuckDuckGo**: captchát adott.
- **TikTok Shop publikus kereső**: bot-szűrés miatt nem olvasható.
- **Márkaoldalak**: a 403-as, 406-os, 429-es, 502-es hibát adó, illetve lejárt tanúsítványú oldalak a `kihagyott.csv`-ben vannak.

## Megjegyzések

- **Marketingvezető**: név szerint szinte sehol nem szerepel nyilvánosan, ezért a legtöbb sorban üres. Nevet nem találtam ki.
- **TikTok Shop**: egyik márkánál sem láttam TikTok Shop-eladó jelölést.
- **Közös cégek**: a PHINICHE és az Almost 1.618 közös cég (TINATI Natural Kft.). A Steeel és az EkszerWebshop.hu szintén közös (Camelot Consulting Kft.).
- **Csoportbesorolás**: egy márka csak egy csoportban szerepel. A Magister Products (sok hajápoló termékkel) és a Vintage Beauty a skincare-ben maradt.
