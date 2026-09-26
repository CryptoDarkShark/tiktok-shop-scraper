# Email rules (Matchly)

Applies to every email sent by any session or tool, to brands, creators or anyone else, including follow-ups.

## The rule (paste this at the start of any session that sends email)

> Send every email as HTML with each paragraph in its own `<p>` tag, plus a plain-text version with a blank line between paragraphs. The greeting goes on its own line, and each signature line on its own line. Never send an email as one block of text. Write like a person: plain text, no bold, no bullet points, no emojis, simple everyday words. Before any new type of email goes out, send one test to info@joinmatchly.com first.

Sending: Resend (RESEND_API_KEY), from viktor@outreach.joinmatchly.com, reply-to info@joinmatchly.com. Never Zoho.

## Follow-ups
Never send a follow-up to anyone who hasn't received the first email. A follow-up is a reply in the same thread
(`Re:` subject, `In-Reply-To`/`References` = the first email's Message-ID) with the original email quoted below it,
exactly as it was sent, so the recipient sees the full message.

## Test emails
Every test is the full first email (with its personalized opening line), sent to info@joinmatchly.com in the
paragraph format above. Test a follow-up only when the user specifically asks for it.

## Brand outreach (this repo)
`pipeline/intl_pipeline.py` builds both versions from one source (`render()` -> `to_html()`), and `send` refuses to run
until `test --kind initial_A|initial_B` has sent the current first-email wording to info@joinmatchly.com (recorded in
`pipeline/email_tests.json`; editing a template requires a new test). Every email sent to a brand is saved verbatim
in `sent/<domain>-<n>.txt`; `followup` only runs for addresses with a logged first send AND that saved copy, and
quotes it below the reply.

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
