# NEON — product scope (v1, 2026-10-23)

Prepared as product research and scoping for turning the Python prototype into a commercial product. Market
figures are cited at the end. Effort figures, prices for NEON itself, and revenue numbers are **proposals and
estimates**, not facts, and are labelled as such.

---

## 1. What the research says

| Finding | Evidence | What it means for NEON |
|---|---|---|
| BitTorrent is shrinking as a share of traffic | 4% of fixed-network upstream in 2024, down from ~10% two years earlier; "file delivery" is now the largest upstream category (29%) [Sandvine 2024] | A pure torrent client is a shrinking market, and it is dominated by free tools. Growth is in *moving files*, not in torrents. |
| The best torrent clients are free | qBittorrent (GPL, no ads), BiglyBT (GPLv2, donationware), Transmission | NEON cannot win by being "qBittorrent with a nicer UI". |
| People pay for **sending big files** | WeTransfer Starter $8/mo, Ultimate $23/mo; Send Anywhere $5.99–$9.99/mo | Sending is a proven paid category. P2P removes the upload wait and the size limits. |
| People pay for **remote / cloud downloading** | Seedr $3.95–$19/mo; put.io from ~$9.99/mo | Users want downloads to happen somewhere else and to control them from anywhere. |
| People pay for **in-client safety** | uTorrent / BitTorrent Pro $19.95/yr, sold on antivirus scanning | NEON's Shield and Guard already go further than this. |
| **No official mobile app** for the leading clients | qBittorrent has no official app; third-party remotes are "very hit and miss" | An official, secure, easy companion app fills a real gap. |
| **Local sharing is huge, but free and crowded** | LocalSend ~95k GitHub stars (Flutter, Apache-2.0); Google Quick Share is free on Windows | LAN sharing alone is no moat. *Interoperating* with LocalSend is cheap reach. |
| Tech is ready for browser peers | libtorrent 2.1 enables WebTorrent (WebRTC) by default | Someone without NEON can receive a NEON "Send" link in their browser. |
| Cross-platform engine exists | `libtorrent_flutter` wraps libtorrent 2.1.1 for Windows, macOS, Linux, Android and iOS; LibreTorrent proves libtorrent on Android | One UI codebase can reach desktop and mobile. |
| Apple rejects torrenting apps | "Apple famously doesn't allow torrenting apps in its App Store" | iOS = remote-control and sharing companion only, with no torrent engine. |
| Content-discovery apps get shut down | Popcorn Time: Canadian injunction (2015) for "enabling, authorizing and inducing" infringement; UK ISP blocks | Never ship built-in torrent search or a media catalog. |
| IP addresses can be personal data | CJEU *Breyer* (C-582/14, 2016); security can be a legitimate interest | Any crowdsourced blocklist needs data minimisation and a privacy policy. |

## 2. Positioning

**From** "a torrent client with a neon UI" **to** **"NEON — the secure P2P platform: download, send and control
files without the cloud and without antivirus drama."**

The torrent engine stays the heart of the product, and the Shield and Guard stay the trust story. What gets added:
1. sending files to anyone (browser included)
2. sharing to nearby devices
3. controlling everything from a phone

Target users:
- **Power downloader:** Linux ISOs, game/patch distribution, datasets, open media. Pain: antivirus alerts, fakes,
  disguised malware, no phone control.
- **Creator / freelancer:** sends 5–500 GB to clients. Pain: WeTransfer caps, upload wait, monthly fees.
- **Multi-device household:** PC ↔ phone ↔ TV/NAS. Pain: cables, cloud limits, hit-and-miss apps.

## 3. Feature pillars and priorities

Legend: **P0** must ship in 1.0 · **P1** 2.x releases · **P2** later · **P3** only if users ask · **Unique** = no mainstream client found
with it · Effort is an estimate for one experienced developer working with AI help.

### A. Secure download (the core: exists in the prototype, gets ported)
| # | Feature | Unique | Priority | Effort | Tier |
|---|---|---|---|---|---|
| A0 | Port of the prototype: Shield (Malwarebytes learning, pre-contact VPN/datacenter filter, network escalation), Guard (pre-download inspection, Mark-of-the-Web, Defender scan), disk-full handling, Stop/Pause, per-torrent settings, connection map, FLASH mode | Yes (as a combination) | P0 | 6–8 wk | Free / Pro |
| A1 | **Universal antivirus learner**: learn from blocked-connection errors (`10013`) and optional WFP audit event `5157`, so most antivirus and firewall products work without per-vendor code. Needs a test per product, because some drop connections silently. | Yes | P0 | 2 wk | Free |
| A2 | **Shield Cloud**: opt-in sharing of *networks* (ASN or /24 ranges, never single addresses or who reported them) that antivirus flagged across NEON users, so most users never see a first alert | Yes (PeerBanHelper has cloud rules, but for anti-leech and after connection) | P1 | 4 wk + server | Pro |
| A3 | **Safe Open**: one click opens a downloaded installer in Windows Sandbox (read-only mapped folder, networking off), plus a visible Authenticode result ("Signed by X / Unsigned") | Yes | P1 | 2 wk | Pro (Sandbox needs Windows Pro/Enterprise/Education) |
| A4 | Archive peek: list zip/7z/rar contents after download and flag programs hidden inside media archives | Rare | P1 | 1–2 wk | Pro |
| A5 | Preview while downloading (libmpv, sequential plus first/last pieces), so fakes are caught before the full download. No catalog, no search. | No (uTorrent Pro has a player) | P2 | 3 wk | Pro |
| A6 | VPN kill switch: bind torrents to a chosen network interface and auto-stop if it drops | No (qBittorrent binds the interface) | P0 | 1 wk | Free |
| A7 | Bandwidth autopilot: throttle during games or calls (fullscreen and latency detection) | Partial | P2 | 2 wk | Free |

### B. Send (new revenue pillar)
| # | Feature | Unique | Priority | Effort | Tier |
|---|---|---|---|---|---|
| B1 | **NEON Send links**: drag a folder to get a link. The files are encrypted first, then shared as a private torrent, with the key kept only in the link's `#fragment`. The receiver gets it with NEON or **in a browser** (WebTorrent through libtorrent 2.1). No size limit, no upload wait. | Yes (for a torrent client) | P1 | 8–10 wk | Free (limited) / Pro (password, expiry, download counts, big links) |
| B2 | **Nearby: LocalSend-compatible** (open LocalSend protocol): send to any phone or PC running LocalSend, instant mobile reach without building a sharing app first | Yes (torrent client + LocalSend interop) | P0 | 3 wk | Free |
| B3 | "Send to my phone" for finished downloads: on the LAN through B2 in 1.0, over the internet through B1 later | Yes | P0 | 1 wk | Free |
| B4 | Relay seed: optional hosted seeder, so links keep working when the sender's PC is off | No | P2 | 4 wk + infra | Paid add-on |

### C. Control
| # | Feature | Unique | Priority | Effort | Tier |
|---|---|---|---|---|---|
| C1 | **NEON Remote** (Android + iOS companion): pair by QR, end-to-end encrypted, works over the internet without port forwarding (WebRTC + STUN, relay for Pro). Add magnets from the share sheet, see progress, push alerts for done, threat or disk full. | Official app = gap | P1 | 8 wk | Free on LAN / Pro over internet |
| C2 | Local web dashboard (HTTPS, paired devices only) | No | P2 | 3 wk | Free |
| C3 | **Home node**: headless NEON core on an always-on PC, NAS or Docker, controlled from anywhere. "Your own put.io" with no storage bill. | Yes (as a packaged experience) | P2 | 4 wk | Pro |
| C4 | CLI + local REST/WebSocket API + webhooks (Home Assistant, Jellyfin library refresh) | No | P2 | 2 wk | Free |
| C5 | Android full client: on-device engine with the pre-contact filter (libtorrent through `libtorrent_flutter`; LibreTorrent already runs libtorrent on Android). Google Play allows torrent apps (µTorrent and Flud are listed there). | No | P2 | 6 wk | Free / Pro |

### D. Sync (later)
| # | Feature | Unique | Priority | Effort | Tier |
|---|---|---|---|---|---|
| D1 | Private P2P folder sync between your own devices | No (Resilio, Syncthing) | P3 | 10+ wk | Pro |

### E. Trust and platform (non-negotiable)
- Microsoft Store (MSIX): Microsoft signs the package for free, so there are no SmartScreen warnings. Also gives
  updates and payments (15% via Store commerce, 0% with our own).
- No telemetry by default; opt-in crash reports. Public privacy policy and security page.
- Security suite in CI: the prototype's 14 attack tests, plus fuzzing of our own protocol code, an SBOM, and
  reproducible release builds.

### Won't do (legal or brand risk)
- built-in torrent search, indexers or media catalogs (Popcorn Time injunctions; Grokster inducement)
- ads, bundleware or miners (AdSense forbids desktop apps; the uTorrent Epic Scale backlash)
- piracy-flavoured marketing

## 4. Production architecture (replacing the Python prototype)

```
                ┌──────────────────────── neon-core (Rust, runs as a service/daemon) ──────────────────────┐
  Flutter UI ──►│ API (WebSocket/JSON-RPC, named pipe locally)                                            │
 (Win/mac/Linux)│  ├─ Torrent engine: libtorrent 2.1 (C++) via thin cxx shim — ip_filter, alerts, WebTorrent│
                │  ├─ Shield: AV learners (MB log, 10013, WFP 5157), VPN/DC feed, ASN DB, Shield Cloud client│
  Flutter app ─►│  ├─ Guard: inspector, MOTW, Defender, Authenticode, Sandbox launcher, archive peek        │
 (Android/iOS)  │  ├─ Send: encrypt-then-torrent, link service, LocalSend protocol server/client           │
  remote only   │  ├─ Remote: pairing (QR + keys), WebRTC data channel, push notifications                 │
   on iOS       │  └─ Storage: settings, resume data, meta (SQLite)                                        │
                └────────────────────────────────────────────────────────────────────────────────────────┘
   Cloud (small): Shield Cloud aggregation · licence server · STUN/TURN relay · push · WebSocket tracker + browser receive page · optional relay seeder
```

Why this stack:
- **Flutter** gives one UI codebase for desktop and mobile. The neon look (glows, shaders) is easier than in Qt
  QSS. LocalSend proves Flutter for exactly this kind of app on all five platforms.
- **Rust core** brings memory safety for the *new* network-facing code (Send, Remote, LocalSend, crypto).
- **libtorrent** stays the engine because it is the most complete: ip_filter, alerts, v2, uTP and WebTorrent are
  everything the Shield relies on.
- The **daemon split** makes Home node (C3), CLI, Docker and Remote nearly free.
- **Alternatives considered:**
  - Qt/QML + C++ (qBittorrent's stack): strong on desktop, but iOS needs static linking, which makes LGPL hard
    and pushes towards a paid Qt licence.
  - Tauri + librqbit: small binaries, but every Shield hook (IP filter, block alerts, WebTorrent) would have to be
    rebuilt and re-validated, while libtorrent already passes the prototype's tests.
- **The Python prototype becomes the reference spec and test oracle.** Its engine tests and the security audit
  are ported first, and the new core must pass them.

## 5. Roadmap (estimates)

| Phase | Weeks | Ships | Exit criteria |
|---|---|---|---|
| 0. Foundations | 4–6 | neon-core skeleton, libtorrent shim, API, Flutter shell with the neon UI, ported test suite | All 14 audit tests and engine tests green on the new core |
| 1. NEON 1.0 (Windows, free) | 14–17 | Feature parity (A0), universal AV learner (A1), kill switch (A6), Nearby/LocalSend (B2/B3), Store MSIX, licence system, Founder presale | Store approval; crash-free sessions ≥ 99.5% in beta; antivirus alerts per hour no higher than the prototype |
| 2. Remote + Pro launch | 15–16 | NEON Remote (Android, then iOS) (C1), Shield Cloud (A2), Safe Open (A3), archive peek (A4); Pro goes on sale | 30% of active users pair a phone (target); first paid conversions |
| 3. Send | 8–10 | NEON Send links with browser receive (B1) and their Pro options | Median link success ≥ 95% |
| 4. Expand | ongoing | Home node (C3), Android full client (C5), macOS/Linux, preview (A5), API (C4), relay seed (B4) | Driven by usage data |

Phases 0–3 add up to roughly 41–49 weeks (about 9–11 months) for one developer. Phases 2 and 3 can swap if the
waitlist (section 9) shows more demand for Send than for Remote.

## 6. Monetisation (proposal)

| Tier | Price (proposal) | Contents |
|---|---|---|
| Free | $0, no ads | Secure torrenting (local Shield + Guard basics), Nearby/LocalSend, Remote on LAN, small Send links |
| **Pro** | **$24.99/yr** or $2.99/mo; India ₹1,499/yr (regional price) | Shield Cloud, Safe Open, archive peek, Remote over the internet, Send links with password/expiry/large size, preview, priority support |
| Founder lifetime | $59 (limited) | Pro forever. Raises early cash; anchored on Resilio's $59.99 lifetime. |
| Relay add-on | $4.99/mo (later) | Hosted relay seeder for Send links, so they work while the PC is off |

Price anchors (real):
- uTorrent/BitTorrent Pro: $19.95/yr
- Send Anywhere: $5.99/mo
- WeTransfer Starter: $8/mo
- Seedr Lite: $3.95/mo

Payments: Microsoft Store commerce (cards worldwide) + BTCPay (BTC/Lightning, self-hosted) + PayPal as fallback.
Dodo Payments is a possible card merchant of record, but subject to review.

## 7. Risks and mitigations

| Risk | Mitigation |
|---|---|
| Inducement liability / store or processor rejection (Grokster, Popcorn Time, Stripe/Paddle policies) | Market only legal uses; no search or catalog; DMCA/abuse contact; clear "share only what you have rights to" text |
| Apple App Store | iOS app is remote + Send receive only, with no torrent engine |
| Our own app flagged by antivirus | Store-signed MSIX, no bundled offers, submit builds to antivirus vendors' false-positive portals before launch |
| Malwarebytes log format changes | The universal learner (A1) is the primary path; per-vendor parsers are optional extras |
| WebRTC widens the attack surface (libtorrent's own warning) | Enable it only for Send/Remote sessions; fuzz our code; keep libtorrent current |
| Shield Cloud privacy (IP = personal data) | Share only network-level aggregates, opt-in, legitimate-interest notice, retention limit |
| Infra cost (relay/TURN) | Free tier is P2P-only; relay is a paid add-on |
| Free competitors (qBittorrent, LocalSend, Quick Share) | Compete on the *combination* plus trust (alerts gone, safe open, phone control), not on any one feature |

## 8. Metrics

- **North star:** safe transfers completed per week (downloads + sends without a security incident).
- **Activation:** first finished download or send within 24 h.
- **Retention:** D7 / D30.
- **Trust:** antivirus alerts per active hour; threats caught.
- **Funnel:** Free → Pro conversion, Remote pairings, Send links created and completed.

## 9. Validate before building everything

1. Landing page and waitlist with the three pillars and the price shown, to measure interest per pillar.
2. Ship the Windows 1.0 (Phases 0–1) to the Store free, and measure activation and antivirus-alert reduction.
3. Build Remote or Send first depending on which waitlist pillar wins.

## Sources

- Sandvine GIPR 2024: <http://www.sandvine.com/hubfs/Sandvine_Redesign_2019/Downloads/2024/GIPR/GIPR%202024.pdf> · TorrentFreak: <https://torrentfreak.com/bittorrent-is-no-longer-the-king-of-upstream-internet-traffic-240315/>
- LocalSend: <https://github.com/localsend/localsend> · Quick Share: <https://en.wikipedia.org/wiki/Quick_Share> · <https://techdows.com/download-quick-share-for-pc-windows-11-10-mac.html>
- WeTransfer pricing: <https://goodsign.io/blog/wetransfer-pricing> · Send Anywhere: <https://send-anywhere.com/pricing> · Resilio: <https://www.gappsy.com/tools/resilio-sync/> · <https://en.wikipedia.org/wiki/Resilio_Sync>
- Seedr: <https://www.seedr.cc/pricing/> · put.io (third-party): <https://www.rapidseedbox.com/blog/10-top-alternatives-to-seedr-cc>
- qBittorrent (no official app): <https://www.cloudwards.net/qbittorrent-review/> · <https://www.techradar.com/reviews/qbittorrent> · qBitController: <https://github.com/Bartuzen/qBitController>
- libtorrent 2.1 WebTorrent: <https://www.libtorrent.org/upgrade_to_2.1-ref.html> · <https://github.com/arvidn/libtorrent/discussions/8570>
- libtorrent_flutter: <https://pub.dev/packages/libtorrent_flutter> · LibreTorrent: <https://f-droid.org/packages/org.proninyaroslav.libretorrent/>
- Popcorn Time: <https://www.cbc.ca/news/business/mpaa-popcorn-time-1.3303428> · <https://en.wikipedia.org/wiki/Popcorn_Time> · Grokster: <https://www.finnegan.com/en/insights/articles/analysis-of-the-u-s-supreme-court-s-grokster-decision.html>
- Breyer (IP = personal data): <https://iapp.org/news/a/in-breyer-decision-today-europes-highest-court-rules-on-definition-of-personal-data> · <https://www.law.kuleuven.be/citip/blog/court-of-justice-rules-on-ip-addresses-and-legitimate-interests-in-breyer-case/>
- Windows Sandbox editions and .wsb: <https://www.itechguides.com/how-to-set-up-windows-sandbox-on-windows-11/> · <https://endpointweekly.com/blog/windows-sandbox-configuration-security.html>
- WFP event 5157: <https://learn.microsoft.com/en-us/previous-versions/windows/it-pro/windows-10/security/threat-protection/auditing/event-5157>
- PeerBanHelper: <https://github.com/PBH-BTN/PeerBanHelper/blob/master/README.EN.md>
- Prices / payments / ads (previous research): BitTorrent Pro <https://www.bittorrent.com/products/win/classic-compare/> · Microsoft Store fees <https://learn.microsoft.com/en-us/windows/apps/publish/publish-your-app/why-distribute-through-store> · AdSense placement policy <https://support.google.com/adsense/answer/1346295?hl=en> · BTCPay <https://docs.btcpayserver.org/BTCPayVsOthers/> · Dodo <https://docs.dodopayments.com/miscellaneous/merchant-acceptance>
