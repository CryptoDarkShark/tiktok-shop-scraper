# Email rules (Matchly)

Applies to every email sent by any session or tool, to brands, creators or anyone else, including follow-ups.

## The rule (paste this at the start of any session that sends email)

> Send every email as HTML with each paragraph in its own `<p>` tag, plus a plain-text version with a blank line between paragraphs. The greeting goes on its own line, and each signature line on its own line. Never send an email as one block of text. Write like a person: plain text, no bold, no bullet points, no emojis, simple everyday words. Before any new type of email goes out, send one test to info@joinmatchly.com first.

Sending: Resend (RESEND_API_KEY), from viktor@outreach.joinmatchly.com, reply-to info@joinmatchly.com. Never Zoho.

## Brand outreach (this repo)
`pipeline/intl_pipeline.py` builds both versions from one source (`render()` -> `to_html()`), and `send` / `followup`
refuse to run until `test --kind <type>` has sent the current wording to info@joinmatchly.com (recorded in
`pipeline/email_tests.json`; editing a template requires a new test).

## Creator email (Hungarian) — correct layout

Plain text:

```
Szia [Név]!

Viktor vagyok a Matchlytól. TikTok Shop kampányok indítására készülünk nemzetközi márkákkal Magyarországon, ahol minden eladás után jutalékot kapnál.

Két gyors kérdés:

1. Mi a TikTok felhasználóneved?

2. Megnéznéd a TikTok appban (Profil → Alkotói eszközök), hogy látod-e a „TikTok Shop" vagy az „Affiliate" lehetőséget? Egy screenshot elég.

Köszi!

Viktor
```

HTML:

```html
<p>Szia [Név]!</p>
<p>Viktor vagyok a Matchlytól. TikTok Shop kampányok indítására készülünk nemzetközi márkákkal Magyarországon, ahol minden eladás után jutalékot kapnál.</p>
<p>Két gyors kérdés:</p>
<p>1. Mi a TikTok felhasználóneved?</p>
<p>2. Megnéznéd a TikTok appban (Profil → Alkotói eszközök), hogy látod-e a „TikTok Shop" vagy az „Affiliate" lehetőséget? Egy screenshot elég.</p>
<p>Köszi!</p>
<p>Viktor</p>
```

The 40 creators who already received the one-block version are not re-sent.
