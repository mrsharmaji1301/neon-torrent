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
- Google removes the Claude 4.6 models from Antigravity on 2 Nov 2026.
- OpenCode, Cline and TRAE are not used: more apps means more coordination for little gain.

## Status

`todo` · `doing` · `review` · `done` · `blocked`

| ID | Task | Owner | Status |
|---|---|---|---|
| C-01 | MSIX packaging spike: app folder → MSIX → install test in Windows Sandbox | Claude | done: 39 MB package (`tools\make_msix.py`); in Sandbox it signs, installs in 5 s, runs and adds its firewall rules |
| C-02 | Licence keys + Free/Pro gating (Dodo test mode) | Claude | todo |
| C-03 | First-run setup, About + third-party notices, error report | Claude | todo |
| C-04 | Icons, Store tiles and screenshots rendered from the app | Claude | todo |
| C-05 | GitHub: private repo [mrsharmaji1301/neon-torrent](https://github.com/mrsharmaji1301/neon-torrent), first push | Claude | done |
| C-06 | Bug: quitting freezes the window for several seconds. Hide it at once, finish shutdown in the background | Claude | done |
| C-07 | Status filter chips with live counts (All, Downloading, Seeding, Completed, Active, Paused, Stopped, Errors) | Claude | done |
| C-08 | Dev tools into `F:\neon-build\tools`: Windows SDK BuildTools 10.0.28000.2705 (makeappx/signtool, nuget.org, 21.3 MB), gitleaks 8.30.1 (secret scan, SHA256-checked, 8.4 MB), ruff (lint, into `.venv`), Token Savior (MCP code navigation, own venv, `optimized` profile, project `.mcp.json`) | Claude | done, hash-checked; Token Savior skipped (not needed to ship) |
| D-01 | Website | Antigravity · Claude Opus 4.6 | doing |
| D-02 | Launch copy pack | Codex · GPT-6 Luna | done: reviewed, 4 fixes, in `marketing/` |
| D-03 | Outreach list | Antigravity · Gemini 3.1 Pro | todo |
| D-05 | Unit tests for `guard.py` and `theme.py` | Codex · GPT-6 Luna | todo |
| U-01 | Install GitHub CLI and log in | You | done |
| U-02 | Partner Center individual account (ID + selfie) | You | todo |
| U-03 | Dodo Payments signup + KYC | You | todo |
| U-04 | Buy the domain | You | todo |

**Open questions for you:**
1. Refund window: 14 days or 7 days (needed for D-04 legal drafts).
2. The Store submission on Sun 25 needs your Partner Center account (U-02) first.

**Next up** (cards are written when they start):
- D-04 legal drafts (Codex), after you decide the refund window
- Claude: C-02 licence keys, C-03 first-run and About, C-04 Store images, website checkout wiring, Show HN write-up

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
