# Matchly – márkakeresési preferenciák (Viktor)

## Márka-kritériumok
1. Niche: ruha, kiegészítő, táplálékkiegészítő, smink, skincare.
2. Magyar márka vagy magyar szálú (magyar leányvállalat / forgalmazó / vezető).
3. Minél ismertebb, annál jobb – az ismert márka a legjobb.

## Kizárva
- A matchly_kizart_markak.csv márkái (már megvannak).
- Out of Mood és SideQuest: SOHA ne kapjanak automatikus üzenetet vagy e-mailt.

## Döntéshozó
- Tulajdonos / alapító / CEO / ügyvezető / head of marketing; nemzetközi márkánál a magyar country manager vagy marketing manager.
- LinkedIn az elsődleges. Csak pontos profil-URL, ahol a keresési találat címében a név és a cég együtt látszik. URL-t soha ne gyárts, a LinkedInt ne scrape-eld.
- E-mail csak akkor, ha biztos, hogy nincs LinkedIn-profil.
- Kitalált vagy bizonytalan adatot ne írj be.

## Kimenet
CSV: niche, márka, weboldal, magyar szál, név, pozíció, linkedin_url, megjegyzés – nichenként, elöl a legismertebbek.
