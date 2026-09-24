# Hungarian brand outreach pipeline

Build and draft now, but do NOT send anything until I say the ExpandNow setup is confirmed.

1. Source brands (dedupe by domain)
- Meta Ad Library API (ad_reached_countries=HU) with keywords like: webshop, bőrápolás, kozmetikum, étrend-kiegészítő, vitamin, fitnesz, kisállat, lakberendezés, divat, ékszer, baba, játék, sport. Keep advertisers with active ads; record the product in those ads.
- Árukereső.hu and similar Hungarian shop directories for the same categories.
- Accept rows I add by hand.

2. Filter
- Hungarian brands selling their own products (not resellers, not marketplaces).
- Drop household names and very large companies (50+ active ads, national chains, multinationals). Target small and mid-size webshops.
- Borderline ones go to review.xlsx.

3. TikTok Shop check
- Look for TikTok Shop links or shop.tiktok.com URLs on the site and in the brand's TikTok bio.
- Status: "on TikTok Shop" (drop) or "unverified" (keep). Never mark "not on TikTok Shop" without evidence.

4. Enrich
Fetch homepage, /impresszum, /aszf, /kapcsolat, /rolunk. Extract: brand name, company name (Kft/Bt), city, generic company email (info@, hello@, ugyfelszolgalat@ preferred), owner first name only if clearly stated, Instagram and TikTok handles, category, advertised product in Hungarian. Skip brands with no email.

5. Draft
- Fill hu-template.md per brand, wording exactly as written.
- Save each day's batch to drafts/YYYY-MM-DD.md with brand, email, category, TikTok Shop status, and an "approved: no" line.

6. Output
- brands.xlsx columns: Brand, Company, Website, Email, City, Category, Advertised Product, Instagram, TikTok, First Name, TikTok Shop Status, Date Found.
- Short summary per run: found, filtered out (and why), kept.

7. Send (later, only when I say go)
- Approved drafts only, via Resend from viktor@outreach.joinmatchly.com, reply-to info@joinmatchly.com. Start 15/day, add 5/day up to 40/day. Follow-ups day 3 and day 7 in Hungarian. Stop on reply, bounce or "leiratkozom". Log to log.csv.
