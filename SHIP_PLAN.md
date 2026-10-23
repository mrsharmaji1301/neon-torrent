# NEON v1.0: ship in 8 days, $1,000 in 30 days (23 Oct – 22 Nov 2026)

Goals:
- By **Fri 30 Oct 2026**, NEON Torrent v1.0 for Windows is live in the Microsoft Store, with a website, payments, a
  public repo and launch posts.
- **$1,000 gross revenue by Sun 22 Nov 2026.**

Mobile, Send and the Flutter/Rust rewrite come after launch (see [PRODUCT_SCOPE.md](PRODUCT_SCOPE.md)).

## Scope

**In v1.0:** the current engine (Python + Qt + libtorrent), packaged as a real Windows app.
- Everything the prototype does today: Shield, Download Guard, FLASH, Stop/Pause, per-torrent settings, details
  tables, disk-full handling.
- MSIX package (Microsoft signs it during Store certification), own icon and Start menu entry, firewall rule in the
  manifest. Users never see Python.
- Licence keys (Dodo Payments) with Free/Pro gating and an offline grace period.
- First-run setup, an About page with third-party notices (Qt LGPL, libtorrent BSD, X4BNet MIT, iptoasn), and an
  error-report button.

**Free vs Pro in v1.0 (proposal):**
- Free keeps all alert protection.
- Pro adds FLASH mode, Guard scans (Defender / VirusTotal), themes and priority support. Every later Pro feature
  (Remote, Send, Shield Cloud) is included at no extra cost.

**Prices:**
- Pro: $24.99/yr or $2.99/mo. India: ₹1,499/yr.
- Founder lifetime: $39 for the first 500 buyers, then $49. Founder pre-orders open as soon as the website is live
  (Day 3).

**After launch (weekly releases):**
- v1.1 (week 2): phone remote in the browser (QR pairing, LAN) and BTC payments (BTCPay).
- v1.2 (week 3): send to phone (LocalSend-compatible).
- Later: Send links, Android app, Shield Cloud. Flutter/Rust v2 once revenue allows.

## Day by day

| Day | Date | Claude builds | You do |
|---|---|---|---|
| 0 | Fri 23 Oct (window from 19:50 IST) | git + AGENTS.md; packaging spike: app folder → MSIX → install test in Windows Sandbox | Partner Center account (ID + selfie), Dodo signup + KYC, buy the domain |
| 1 | Sat 24 | Licence + Free/Pro gating (Dodo test mode), first-run setup, About + notices, error report | Reserve the "NEON Torrent" name in Partner Center |
| 2 | Sun 25 | Full test pass: 14 audit tests, live download, clean install in Sandbox, Malwarebytes/Defender/VirusTotal on our package. Store listing, screenshots (legal content only), privacy policy | **Submit to the Store** |
| 3 | Mon 26 (weekly limit resets 00:30 IST) | Website on Cloudflare Pages: landing, pricing, download, docs, privacy, terms, refund, security, abuse contact. Dodo checkout; Founder pre-orders open | Point the domain at Cloudflare |
| 4 | Tue 27 | Public GitHub repo (README, releases, issue templates, SECURITY.md). Launch kit: Show HN write-up on the Shield, posts for Reddit, X, Product Hunt, LinkedIn; pitches to TorrentFreak and Neowin; demo video script | Start 5–10 beta testers |
| 5 | Wed 28 | Fixes from beta and Store feedback; portable ZIP fallback if the Store is late | Record the demo video |
| 6 | Thu 29 | Release candidate, payments live, website final; submit to Softpedia, MajorGeeks, AlternativeTo | Check Store status |
| 7 | Fri 30 | Launch-day support | **Launch**: Product Hunt goes live 12:31 IST, then Show HN and the posts |
| 8 | Sat 31 | Hotfixes, replies, v1.1 announcement | Replies |

## Revenue target: $1,000 gross by Sun 22 Nov

**Commitment:**
- Claude commits to the build and launch dates above, a daily growth routine after launch, a weekly feature release
  and an honest numbers report every day.
- Nobody can commit to how many people buy. Estimate: about a 1-in-3 chance of $1,000 in 30 days. That chance rises
  sharply if one channel breaks out.

**Funnel (estimates from published benchmarks):**

| Step | Needed |
|---|---|
| Sales | ~26 at $39, or a mix of Founder and yearly Pro |
| Active users | ~900–1,300 (2–3% paid in the first weeks; typical freemium is 2–5% over 3–6 months) |
| Downloads | ~1,300–2,000 |
| Site visitors | ~5,000–10,000 targeted visitors in about 3.5 weeks |

**Channels, in order of expected reach:**
1. **Show HN** with a technical write-up of the Shield (how NEON learns from antivirus blocks). A front-page post
   brings 5,000–30,000 visitors, but only ~2.3% of submissions reach the front page.
2. **TorrentFreak and Windows software sites** (Neowin, Softpedia, MajorGeeks, AlternativeTo): pitches and listings
   in launch week.
3. **Reddit threads** where people ask why their antivirus blocks their torrent client. Give helpful answers, follow
   each subreddit's rules and do not spam.
4. **Product Hunt** on launch day: 1,000–5,000 visitors if featured, but the audience is not mainly torrent users.
5. **A 60-second demo video** for YouTube Shorts and X.
6. **Re-launch posts** for v1.1 (week 2) and v1.2 (week 3).

**Checkpoints:**

| Date | On track if | If not |
|---|---|---|
| Sat 31 Oct | Store and payments live | Portable ZIP + Gumroad/PayPal |
| Fri 6 Nov | ≥ 2,000 visitors and ≥ 5 sales | Move effort to the channel that worked best; pitch YouTubers |
| Fri 13 Nov | ≥ 15 sales | 72-hour Founder offer, launched together with v1.2 |
| Sun 22 Nov | $1,000 gross | Honest post-mortem, then decide month 2 |

## Budget

Claude Pro on Opus 5.5 at max effort:
- About 3 five-hour windows (~8 h) are left until the weekly reset on Mon 26 Oct, 00:30 IST.
- Each new week brings about 8 windows (~22 h).
- The build needs about 20 h, and growth work about 10–15 h a week after launch. Other Claude projects pause until
  22 Nov.

Start each day from this file, in a fresh session or after `/compact`, so the context stays small.

## Risks and fallbacks

| Risk | Fallback |
|---|---|
| Store certification takes up to 3 business days, possibly longer for a brand-new account | Submit by Sun 25 Oct. If the listing is not live by Thu 29, launch with the portable ZIP from the website and switch the button once the Store listing is live. |
| Dodo verification (24–72 working hours) or product approval fails | Gumroad (merchant of record, licence keys, 10% + $0.50 plus processing; check India payouts first) or PayPal |
| Antivirus flags our own package | Scan with Malwarebytes, Defender and VirusTotal on Day 2, and report false positives to the vendors at once |
| Piracy association (Store, payments, press) | No game, repack or movie torrents in any screenshot, post or demo. Use Ubuntu/Debian ISOs and open movies (Blender). Put terms and an abuse contact on the site. |
| No channel breaks out | Weekly re-launch posts, YouTuber outreach, a 72-hour Founder offer |
| Weekly Claude limit runs out | Pause other projects. Delegate website copy, posts and tests to the free tools; Claude reviews their work. |
