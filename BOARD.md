# BOARD: live task board for the NEON v1.0 sprint

This file is the one channel for who does what. Claude adds, changes and closes tasks here as progress shows what
comes next, and commits every update. The plan behind it is [SHIP_PLAN.md](SHIP_PLAN.md).

## How it works

- **Delegated apps** (Antigravity, Codex):
  - write only inside `inbox/<ID>/`
  - never run git and never edit other files
  - finish every task with `inbox/<ID>/DONE.md`: files delivered, checks done, open questions
- **You** paste the task prompt into the app shown on the card, then tell Claude "`<ID>` done".
- **Claude** reviews the work, moves what passes into its final folder, updates this board, and makes every commit
  and push. Only Claude touches git and GitHub.
- **Review depth:** public claims (copy, legal) are reviewed in full; the website and research get a spot check; tests
  are checked by running them.

Open the folder `F:\neon-torrent` in the app (never a new project), then paste this prompt (replace `<ID>`):

```
Read AGENTS.md and BOARD.md in F:\neon-torrent. Do task <ID> exactly as its card says, start to finish, without stopping. Do not ask me questions: when something is unclear, pick the safest sensible option and list it under "Assumptions" in DONE.md. Create and edit files only inside F:\neon-torrent\inbox\<ID>\. Do not run terminal commands, install software, run git, edit any other file or write anything on drive C:. If a check needs a command or a tool, skip it and say so in DONE.md. When finished, write F:\neon-torrent\inbox\<ID>\DONE.md.
```

## Apps and models (checked 23 Oct 2026)

| App | Your plan | Model | Fallback |
|---|---|---|---|
| Antigravity | Google AI Pro (Jio offer) | Claude Opus 4.6 (Thinking), for code | Gemini 3.1 Pro (High) |
| Antigravity | same | Gemini 3.1 Pro (High), for web research | Gemini 3.8 Flash (High) |
| Codex app | Free | GPT-6 Luna, reasoning High | none |

- If a model is missing from the dropdown, use the fallback and say so in `DONE.md`.
- The Claude 5.5 models in Antigravity need a non-promotional Pro plan.
- When Antigravity runs out of quota, Claude hands the task to Codex, which resumes from whatever is already in
  `inbox/<ID>/`.
- Google removes the Claude 4.6 models from Antigravity on 2 Nov 2026.
- OpenCode, Cline and TRAE are not used: more apps means more coordination for little gain.

## Status

`todo` · `doing` · `review` · `done` · `blocked`

| ID | Task | Owner | Status |
|---|---|---|---|
| C-01 | MSIX packaging spike: app folder → MSIX → install test in Windows Sandbox | Claude | done: 39 MB package (`tools\make_msix.py`); in Sandbox it signs, installs in 5 s, runs and adds its firewall rules |
| C-02 | Licence keys + Free/Pro gating (Dodo test mode) | Claude | todo |
| C-03 | First-run setup, About + third-party notices, error report | Claude | doing: C-03a About + `THIRD-PARTY-NOTICES.md` (`tools\make_notices.py`, in the MSIX) and C-03b first-run folder dialog done, Sandbox install shows it; error report open |
| C-04 | Icons, Store tiles and screenshots rendered from the app | Claude | todo |
| C-05 | GitHub: private repo [mrsharmaji1301/neon-torrent](https://github.com/mrsharmaji1301/neon-torrent), first push | Claude | done |
| C-06 | Bug: quitting freezes the window for several seconds. Hide it at once, finish shutdown in the background | Claude | done |
| C-07 | Status filter chips with live counts (All, Downloading, Seeding, Completed, Active, Paused, Stopped, Errors) | Claude | done |
| C-08 | Dev tools into `F:\neon-build\tools`: Windows SDK BuildTools 10.0.28000.2705 (makeappx/signtool, nuget.org, 21.3 MB), gitleaks 8.30.1 (secret scan, SHA256-checked, 8.4 MB), ruff (lint, into `.venv`), Token Savior (MCP code navigation, own venv, `optimized` profile, project `.mcp.json`) | Claude | done, hash-checked; Token Savior skipped (not needed to ship) |
| C-09 | Choose files and priorities when adding a torrent, and later in any state (card below) | Claude | done 25 Oct: Add dialog on every add, Details → Files priorities; tests 36/36, audit 18/18. Waiting for the user's real add test |
| D-01 | Website | Antigravity · Gemini 3.8 Flash | replaced by D-01b: it read like a spec sheet, with empty image boxes |
| D-01b | Website rebuild around the real screenshots | Codex · GPT-6 Luna (Antigravity ran out of quota at 03:57) | done: checked at 1280×800 and 375 px, now `site/`. Fixed: invisible nav Download text, placeholder `og.png` (now a 1200×630 crop of screenshot 1), five claims not in the sources ("zero trackers", "own all Pro updates forever", "no data is lost", "never crash", FLASH as "read-only LSD"). `/legal/refund.html` is still a dead link until D-04 |
| D-02 | Launch copy pack | Codex · GPT-6 Luna | done: reviewed, 4 fixes, in `marketing/` |
| D-03 | Outreach list | Codex · GPT-6 Luna (Antigravity ran out of quota before saving anything) | done: 50 rows in `marketing/outreach.md` and `.csv`, each with a source URL and a checked date, no emails. Spot check of 10 URLs: 8 fine, 2 dead links fixed (Softpedia 410, SnapFiles soft 404). Reddit blocks automated reads, so its member counts and YouTube subscriber counts are unverified estimates: refresh before outreach |
| D-05 | Unit tests for `guard.py` and `theme.py` | Codex · GPT-6 Luna | done: 22 tests in `tests/` pass (`python -m unittest discover -s tests`); one wrong expectation fixed |
| D-04a | Privacy policy, terms and abuse page (refund page waits for your decision) | Codex · GPT-6 Luna | done: in `site/legal/` (`.md` in `marketing/legal/`). Privacy rewritten against the code: it now lists .torrent URL fetches, UPnP/NAT-PMP, DHT/LPD/FLASH, X4BNet lists on GitHub, iptoasn.com, VirusTotal hashes, Defender, Cloudflare Pages hosting. New placeholders `{{LICENCE_CHECK_DETAILS}}` (fill in with C-02) and `{{OFFLINE_GRACE_DAYS}}`. Needs a lawyer before launch |
| U-01 | Install GitHub CLI and log in | You | done |
| U-02 | Partner Center individual account (ID + selfie) | You | todo |
| U-03 | Dodo Payments signup + KYC | You | todo |
| U-04 | Buy the domain | You | todo |

**Open questions for you:**
1. Refund window: 14 days or 7 days (needed for D-04 legal drafts).
2. The Store submission on Sun 25 needs your Partner Center account (U-02) first.
3. Confirm the Free/Pro split in SHIP_PLAN ("Free vs Pro in v1.0"). The website shows it now, and C-02 builds it.

## Night shift (24 Oct): Claude works alone while the user sleeps

**24 Oct 05:00, Claude:** C-03a and C-03b done and pushed (About in Preferences, `THIRD-PARTY-NOTICES.md` in the MSIX,
first-run folder screen). Tests 22/22, audit 14/14, and the Sandbox install shows the first-run screen. Still open: D-01b
(no `DONE.md`; Antigravity's last write was at 03:57 and there is no `assets/` folder) and D-03 (no `inbox/D-03/`). Both
look stalled in Antigravity. Please review the LGPL wording in the notices. `APP_VERSION` is now 1.0.0, but the engine's
user agent still says `NeonTorrent/2.0`.

**24 Oct 05:05, Claude:** D-01b and D-03 did not crash. Antigravity ran out of model quota at 03:57 (D-01b started four
page-builder sub-agents at once), and it refreshes at **08:47**. Then type `continue` in both Antigravity
conversations. Do not click "Enable Overages": it bills. D-04a is written up but not sent: at 05:05 a Windows input
overlay (TextInputHost) blocked desktop control. Paste the standard prompt with `D-04a` into Codex (NEON project).

Every session on this shift: read CLAUDE.md and this board first, write in English, never write to drive C:, and make
no purchases, posts, account or settings changes. A scheduled session cannot drive Codex or Antigravity (no desktop
access), so skip anything that needs them. Do the first open item, tick it here, commit and push, then the next.

- [x] Real screenshots from the app (`tools/screenshots.py`); torrent settings no longer overlap
- [x] D-05 reviewed and accepted into `tests/`
- [x] D-03: when `inbox/D-03/DONE.md` exists, open 10 of its URLs, move the files to `marketing/`, mark D-03 done
- [x] D-01b: when `inbox/D-01b/DONE.md` exists, copy `site/assets/*.png` into it, serve it on 127.0.0.1 and check it
  in the built-in browser at 1280×800 and 375 px wide (no empty boxes, no console errors except the Cloudflare
  beacon), fix small issues, then replace `site/` with it and mark D-01b done
- [x] C-03a: `THIRD-PARTY-NOTICES.md` built from the real licence files (Python PSF; PySide6, Qt and shiboken6 LGPLv3
  with the note that users may swap the Qt DLLs; libtorrent BSD-3; OpenSSL Apache-2.0; libffi MIT; bzip2, xz, zlib;
  Microsoft VC++ runtime). `tools/make_msix.py` copies it into the package. An About dialog (version, licence,
  notices) opens from the settings dialog. Run the tests and the security audit, rebuild the MSIX, repeat the
  Sandbox test.
- [x] C-03b: first run asks for the download folder (default `Downloads\NEON`) on one screen that also explains
  File-only mode; nothing else.

**Next up** (cards are written when they start):
- D-04 legal drafts (Codex), after you decide the refund window
- Claude: C-02 licence keys, C-03 error report, C-04 Store images, website checkout wiring, Show HN write-up

## Task cards

### D-01 Website

- **App:** Antigravity · Claude Opus 4.6 (Thinking).
- **Output:** `inbox/D-01/`. It becomes `site/` once accepted.

A static site for Cloudflare Pages with no build step:
- **Tech:** plain HTML, one CSS file, at most 5 KB of vanilla JS. No frameworks, CDNs, external fonts, cookies or
  trackers. The only script from outside is Cloudflare Web Analytics, with `{{CF_ANALYTICS_TOKEN}}`.
- **Pages:**
  - `index.html`: hero, the problem, how the Shield works, features, screenshots, pricing, FAQ, download.
  - `download.html`: Microsoft Store button to `{{STORE_URL}}`; requirements Windows 10/11 x64.
  - `security.html`: a summary of SECURITY.md.
  - `docs.html`: quick start and FAQ from README.md.
  - `404.html`, `sitemap.xml` and `robots.txt` using `{{DOMAIN}}`.
  - Footer links to `/legal/privacy.html`, `/legal/terms.html`, `/legal/refund.html` and `/legal/abuse.html`. These
    pages are written later.
- **Look:** the app's neon theme. Colours come from the Cyberpunk palette in `src/neontorrent/theme.py`: dark
  background, buttons that glow on hover, responsive down to 360 px wide.
- **Facts:** only from README.md and SECURITY.md. Features not shipped yet go in a Roadmap section only: phone remote
  (v1.1), send to phone (v1.2).
- **Pricing:**
  - Free: $0.
  - Pro: $24.99/yr or $2.99/mo; India ₹1,499/yr.
  - Founder lifetime: $39 for the first 500 buyers, then $49.
  - Buttons link to `{{CHECKOUT_FOUNDER}}`, `{{CHECKOUT_PRO_YEARLY}}`, `{{CHECKOUT_PRO_MONTHLY}}` and
    `{{CHECKOUT_PRO_INDIA}}`.
- **Images:** placeholders `assets/screenshot-1.png` and onwards, plus `assets/og.png` (1200×630). Claude supplies
  the real images.
- **Done when:**
  - no console errors
  - Lighthouse (mobile) scores 95 or more in all four categories on `index.html`
  - every link works or is a `{{PLACEHOLDER}}`
  - the site is under 300 KB without images
  - `DONE.md` offers 3 hero headline options

### D-02 Launch copy pack

- **App:** Codex app · GPT-6 Luna, reasoning High.
- **Output:** `inbox/D-02/`. It becomes `marketing/` once accepted.

One Markdown file per channel:
- **`store.md`** (Microsoft Store):
  - short description
  - full description, at most 3,000 characters
  - up to 20 feature bullets, at most 200 characters each
  - 7 search terms
  - "What's new" for 1.0
- **`producthunt.md`:**
  - tagline, at most 60 characters
  - description, at most 260 characters
  - the maker's first comment, about 200 words
  - 3 gallery captions
- **`reddit.md`:** 3 answer templates for "my antivirus blocks my torrent client" threads, each saying "I made
  NEON", plus 1 launch post.
- **`x.md`:** a launch thread of 6–8 posts, plus 5 posts for the week after.
- **`pitch.md`:** pitch emails to TorrentFreak and Neowin, at most 150 words each.
- **`video.md`:** a 60-second demo script with a shot list, showing an Ubuntu ISO download.

**Voice:** confident, technical and honest. No hype words such as "revolutionary", and no piracy references.

**Facts:** every claim must trace to a line in README.md or SECURITY.md. List any claim you could not trace in
`DONE.md`.

### D-03 Outreach list

- **App:** Antigravity · Gemini 3.1 Pro (High).
- **Output:** `inbox/D-03/outreach.md` and `inbox/D-03/outreach.csv`. They move to `marketing/` once accepted.

Use public information only. Give every row its source URL and the date you checked it.
- **15 subreddits** (torrents, Windows software, antivirus, side projects, Indian tech): members, the
  self-promotion rule with a link to the rules, and the best post type.
- **10 Windows software sites and download portals** (for example Softpedia, MajorGeeks, Neowin, AlternativeTo):
  submission page and requirements.
- **10 news sites or writers** covering P2P and privacy: public tip or contact page only.
- **15 YouTube channels** that review Windows utilities, torrent clients or privacy tools: subscribers, one recent
  relevant video, and a public business contact if one is listed.

**Done when:**
- every URL opens
- every email address comes from an official contact page; collect none from anywhere else

### C-09 File selection and priorities (user's decisions, 25 Oct)

- **Every add** (`.torrent` file, HTTP(S) link, magnet, info-hash) opens an Add dialog; there is no setting to skip it.
  Nothing downloads until the user presses DOWNLOAD; CANCEL removes the torrent and leaves no files.
- **Add dialog:** save folder (default `download_dir`, Browse…), free space vs. selected size, then the file list:
  checkbox per file, a Priority column (High / Normal / Low / Don't download = libtorrent 7 / 4 / 1 / 0), select
  all/none, multi-select with right-click → Priority, and the selected total.
- **Magnets:** fetch metadata only. Add with `stop_when_ready` and set every file priority to 0 as soon as metadata
  arrives, then open the dialog. The dialog shows "Fetching the file list…" until then.
- **Guard first:** files Download Guard skips arrive as Don't download, with the reason shown, before the dialog opens.
- **Later, in any state** (downloading, idle, paused, stopped): the right-click → Details → Files tab gets the same
  checkbox, Priority column and right-click menu. Changes apply at once.
- **Survives restarts:** a torrent waiting for its selection keeps a meta flag, stays paused, and reopens the dialog
  after a restart.
- **Rules:** engine changes go through queued signals only. Torrent and magnet parsing is security-critical
  (AGENTS.md), so tests and the security audit must pass. Update README. No builds or MSIX until the user says so.
  Claude adds no torrents: the user tests the real add flow.

### D-01b Website rebuild

- **App:** Antigravity · Claude Opus 4.6 (Thinking); if it is missing, Claude Sonnet 4.6 (Thinking).
- **Output:** every page of the site in `inbox/D-01b/`. It replaces `site/` once accepted.

The first version reads like a spec sheet: feature tables, grids of small cards, empty image boxes. The new one must
sell the product in ten seconds, like the best product sites (Linear, Raycast, Warp): one idea per screen, big real
product images, a lot of space, short copy.
- **Hero:** a headline of at most 8 words, a one-line subhead, two buttons (Download free, See pricing), and
  `assets/screenshot-1.png` large in a floating window frame with the app's neon glow (slow CSS pulse). Nothing else.
- **Proof strip:** "From a 2-minute test download of Ubuntu 26.04 and Debian 13.7: Shield refused 1,080 peers from
  VPN, datacenter and flagged networks, while 495 live peers in 48 countries kept it moving."
- **Three story sections**, image and text alternating sides: Shield connection map (`screenshot-2.png`), torrent
  details (`screenshot-3.png`), per-torrent control (`screenshot-4.png`). Each: a title of 4–6 words, at most two
  sentences, at most three short bullets.
- **Then:** pricing (plans and prices exactly as in the current `site/index.html`), six FAQ questions, a final call to
  action, footer.
- **Remove:** feature tables, the "how the Shield works" tables, the roadmap grid and stacks of small cards. The only
  table left on the site is the audit table on `security.html`.
- **Images:** use `assets/screenshot-1.png` to `assets/screenshot-4.png` and `assets/og.png` by these names. Claude
  copies the real files in; do not create image files.
- **Keep from D-01:** no external fonts, CDNs or trackers except the Cloudflare beacon placeholder; vanilla JS under
  5 KB; every `{{PLACEHOLDER}}`; facts only from README.md, SECURITY.md and `marketing/store.md`; the neon palette
  from `src/neontorrent/theme.py`; responsive down to 360 px; `prefers-reduced-motion` turns animation off.
- **Other pages** (`download.html`, `docs.html`, `security.html`, `404.html`) get the new header, footer and type;
  their content stays.
- **Done when:** no empty boxes, nothing looks like a spreadsheet, and `DONE.md` lists each section of the landing
  page with one line on what it shows.

### D-04a Privacy policy, terms and abuse page

- **App:** Codex app · GPT-6 Luna, reasoning High.
- **Output:** `inbox/D-04a/privacy.html`, `terms.html` and `abuse.html`, plus a `.md` copy of each. They move to
  `site/legal/` once accepted. The refund page waits for the user's decision on the refund window.

Plain English that a Microsoft Store reviewer and a careful user can trust. Facts come only from README.md,
SECURITY.md and SHIP_PLAN.md; anything else becomes a `{{PLACEHOLDER}}` (owner name, postal address, contact and
abuse emails, effective date, `{{REFUND_DAYS}}`).
- **Privacy:** no telemetry and no account. List every network connection the app makes and why: peers and trackers
  of the user's own torrents, the IP-range lists the Shield downloads, optional VirusTotal hash lookups with the
  user's own key, and Store updates. List what stays on the PC (settings, learned blocks, resume data) and how to
  delete it. The website uses Cloudflare Web Analytics without cookies, and Dodo Payments handles payments as
  merchant of record. Say plainly that peers in a swarm see your IP address, because that is how BitTorrent works.
  One short section on rights under GDPR and India's DPDP Act 2023.
- **Terms:** licence to use, the Free and Pro plans and prices from SHIP_PLAN.md, licence keys, refunds within
  `{{REFUND_DAYS}}` days, no warranty, the user is responsible for what they download and must not infringe
  copyright, termination, governing law India.
- **Abuse:** how rights holders and others report misuse to `{{ABUSE_EMAIL}}`; NEON hosts no content and has no
  catalogue or search; what we can and cannot do about a report.
- Link `../style.css` and use simple semantic HTML so the pages take the site's look. At most 1,500 words per page.
- **Done when:** every page shows an effective-date placeholder, no claim lacks a source, and `DONE.md` lists every
  placeholder and says the pages need a lawyer's review before launch.

### D-05 Unit tests for guard.py and theme.py

- **App:** Codex app · GPT-6 Luna, reasoning High.
- **Output:** `inbox/D-05/test_guard.py` and `inbox/D-05/test_theme.py`. They move to `tests/` once accepted.

Use the standard-library `unittest` only (no pytest). Put `src` on `sys.path` relative to the test file, so
`from neontorrent import guard, theme` works from `inbox/D-05/`.
- **guard.py:** every rule in `classify()` and `inspect()`: programs, scripts, shortcuts and macro documents, double
  extensions, hidden direction characters (`TRICK_CHARS`), programs inside media torrents, Strict mode, Windows device
  names (`RESERVED`, with and without an extension) and symlinks. Test `mark_of_the_web()` and `has_mark_of_the_web()`
  on a file in `tempfile.TemporaryDirectory(dir=<the test file's folder>)`.
- **theme.py:** every palette in `THEMES` has the same keys; `set_theme()` with an unknown name falls back to a valid
  theme; `state_color()` returns a valid colour for every state in `STATE_COLORS`.
- Never call Defender, VirusTotal or the network, and do not import `engine.py`.
- **Done when:** Claude runs `.venv\Scripts\python.exe -m unittest discover -s inbox\D-05 -v` and every test passes.
  If you think a behaviour is a bug, list it under "Possible bugs" in `DONE.md`; do not change `guard.py`.
