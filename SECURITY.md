# NEON Torrent — security model and audit

Last audited: 2026-10-25 · `tools\security_audit.py`: **18/18 checks passed**.

## What a torrent client can and cannot promise

BitTorrent checks every piece against the torrent's hashes (SHA-1, or SHA-256 for v2 torrents), so a download
is byte-for-byte what the uploader published. Nobody else can inject or alter data. Whether that published file is
safe depends on the uploader. No client can make a malicious installer safe, so "100% malware-proof" is not a
promise any client can honestly make. NEON Torrent works on everything a client *can* control.

## Protection layers

### 1. Network: Shield

- **Pre-contact peer filter.** Peers in known VPN and datacenter ranges (X4BNet lists, refreshed daily, plus
  Cloudflare WARP) are refused before any packet is sent. Big seedbox hosts (Hetzner, OVH, Scaleway) stay
  allowed. Measured on this PC's real alert history: 12 of 13 flagged peers would have been refused before contact.
- **Learning from Malwarebytes.** Every IP or tracker that Malwarebytes blocks for a torrent program goes into
  libtorrent's IP filter or tracker list within 2 s. Its network is blocked too: the /24, or the whole network if it
  is hosting-sized (2 million IPs or fewer; CDNs and big ISPs are never blocked whole).
- **One filter for every peer source.** The IP filter covers peers from trackers, PEX, DHT and incoming
  connections. Web-seed mirrors are resolved and kept reachable.
- **File-only network.** No DHT or LSD by default, so the only hosts contacted are your torrents' trackers and
  peers. FLASH MODE turns on read-only DHT, whose directory nodes cannot be IP-filtered (a libtorrent limitation).
- **Tracker hardening.** Requests to local services are refused (`ssrf_mitigation`), look-alike punycode domains
  are refused (`allow_idna = false`), and HTTPS trackers must present valid certificates.

### 2. Files: Download Guard

- **Add dialog first.** Every new torrent waits, paused and with every file at priority 0, until the user presses
  DOWNLOAD in the Add dialog. A magnet fetches only its file list, in upload-only mode, and is paused with every file
  at 0 the moment the list arrives. CANCEL removes the torrent without deleting anything (files already in the
  folder stay untouched). The engine clamps the dialog's choices to valid file indices and priorities 0–7.
- **Before download.** These are proposed as Don't download in the Add dialog, with the reason, and stay at
  priority 0 before any data is requested; *All* never switches them on:
  - double extensions (`movie.mp4.exe`)
  - shortcuts (`.lnk`, `.url`, `.scf`)
  - hidden Unicode direction or invisible characters (RTLO tricks)
  - trailing dots or spaces
  - programs or scripts inside media torrents
  - symbolic links
  - Windows device names (`CON`, `AUX`…)

  Strict mode also skips every program, script and macro document.
- **After download.** Files get Mark-of-the-Web (`Zone.Identifier`, ZoneId=3), so Windows SmartScreen and Office
  Protected View check them before they can run, as with browser downloads. A file switched on later in Details →
  Files gets the mark and the scan when it finishes too.
- **Scanning.** Microsoft Defender scans the finished torrent when it is the active antivirus. With a VirusTotal
  key, programs are also looked up by SHA-256 (hash only, never the file) against about 70 engines. If a threat is
  found, seeding stops, an alert is shown, and the row is marked ☣.

### 3. The client itself

- Never opens or runs a downloaded file. *Open folder* only selects the item in Explorer, uses an absolute
  `explorer.exe` path, and refuses any name that resolves outside the download folder.
- Torrent-supplied text (names, paths, comments) and network text (tracker messages, peer clients) is shown as
  plain text, never as HTML, in tooltips too.
- The single-instance channel (links, `--pause-all`, `--resume-all`) accepts messages only from the same Windows
  user.
- `.torrent` downloads are capped at 20 MB; malformed or hostile input is rejected without crashing.
- libtorrent sanitises paths (`..`, absolute paths, `:` streams); the Guard covers what it leaves (device names,
  symlinks).
- Runs as its own `runtime\NeonTorrent.exe` (a signed Python interpreter copy) without admin rights, so the
  firewall and antivirus see it separately from other Python programs.

### 4. File Sharing (phone and PC, LAN or internet)

- The server exists only while a sharing session is open (FILE SHARING tab, until STOP or quit). It listens on the
  PC's private LAN IPv4 address only, on a random port, and refuses any source address outside 10/8, 172.16/12,
  192.168/16 and 169.254/16, and any request whose `Host` is not that address (DNS rebinding).
- Pairing: the QR code carries the PC's ephemeral X25519 public key and a 128-bit one-time token in the URL
  `#fragment`, which browsers never send over the network. The phone makes its own ephemeral X25519 key; both sides
  derive two keys (one per direction) with HKDF-SHA256, salt = token. The pairing request is already sealed with
  the derived key, so a phone without the token is refused (403) and the token never travels. A replayed pairing
  request is refused, and the QR code (key and token) is replaced after every Allow or Deny.
- Every message and every 1 MiB file chunk is sealed with ChaCha20-Poly1305 (Python `cryptography`; the phone uses
  `@noble/curves` and `@noble/ciphers`, bundled in the page, no CDN). Nonces are unique per direction, file and
  chunk; the file number, chunk index and chunk count are authenticated, so a tampered, reordered, truncated or
  replayed chunk or message is rejected. Control counters must only grow.
- A new phone has to be allowed on the PC (name, model, IP and MAC shown) before it can list, send or receive
  anything. One phone at a time.
- Received names are reduced to a bare file name: no folders or `..`, no control, bidi or format characters, no
  Windows device names, no trailing dots; an existing name gets ` (1)`. Files are written as hidden `.neonpart`
  files, renamed only when every chunk has passed authentication, and tagged with Mark-of-the-Web like downloads.
  Partial files are deleted on cancel, disconnect or stop. Free space is checked before an upload starts.
- Limit: the phone page itself is served over plain HTTP (browsers need a trusted certificate for HTTPS, which a
  LAN address cannot get). File contents stay confidential against anyone who only watches the Wi-Fi, but an
  attacker who can actively tamper with traffic on your own network while you scan could swap the page's script
  and read the key. Use File Sharing on networks you control, not on public Wi-Fi.
- LAN | INTERNET toggle (next to TO PHONE | FROM PHONE, remembered as `share_net`). **LAN** starts no tunnel at
  all: nothing is reachable from the internet. **INTERNET** (the default) shows the QR code only once the tunnel is
  up, never a LAN code a phone elsewhere could not use, and keeps phones on the tunnel (no LAN hop).
- No port is opened on the router: cloudflared makes an outbound connection to Cloudflare, and only the random
  `*.trycloudflare.com` name reaches the sharing server, over HTTPS.
- Internet mode: while sharing, `cloudflared tunnel --no-autoupdate --url http://<LAN IP>:<port>` runs hidden (no
  account, no config file; its working folder is the app data folder) and is killed on STOP, DISCONNECT (a new
  tunnel URL is made), switching to LAN and quit. It also sits in a Windows job object with kill-on-close, so it
  dies with NEON even when NEON crashes or is killed: no orphaned public tunnel. The tunnel page is HTTPS, so the
  page-integrity limit above shrinks to trusting Cloudflare's edge, which only ever sees ciphertext and never the
  `#fragment`.
- Flood limits: at most 48 concurrent connections (more are dropped unread), 30 s socket timeout, 8 failed pairings
  per IP (4096 IPs remembered), 3 phones waiting for Allow, and an upload's 1 MB body is read only after its session
  and transfer check out.
- A request counts as tunnel traffic only if its `Host` is the current `*.trycloudflare.com` name **and** it comes
  from this PC's own LAN address (where cloudflared connects from) **and** carries `CF-Connecting-IP`; such sessions
  are bound to that public IP and cannot be used from the LAN side. Anyone with the tunnel URL can load the page,
  but pairing still needs the token from the QR fragment and the Allow click on the PC.
- LAN/INTERNET detection: the PC learns its public IPv4/IPv6 once from Cloudflare's trace endpoint
  (`/cdn-cgi/trace`). `/api/where` reveals the LAN address only to a tunnel visitor with the same public IPv4 (or
  IPv6 /64), i.e. someone already behind the same router.

## Audit (re-run any time: `.venv\Scripts\python.exe tools\security_audit.py`)

| # | Attack | Result |
|---|---|---|
| 1 | Torrent with `../../evil.txt`, `C:\Windows\System32\evil.dll`, `sub/../../escape.bat` | All mapped inside the download folder |
| 2 | Alternate-data-stream name `notes.txt:hidden.exe` | Neutralised to `notes.txt_hidden.exe` |
| 3 | Windows device names `CON`, `aux.txt` | Skipped by the Guard (never written) |
| 4 | Symlink to `..\..\..\..\Windows\System32` | libtorrent re-targets it inside the torrent; Guard flags and skips it |
| 5 | Media torrent with `.mp4.exe`, `.lnk`, RTLO `.scr`, codec `.exe` | All four skipped before download; `.mkv`/`.srt` kept |
| 6 | Garbage bencode, invalid info section, `javascript:` and `file:` links | Rejected, no crash |
| 7 | 20 MB+ `.torrent` over HTTP | Refused |
| 8 | Tracker URL aimed at a local admin endpoint (SSRF) | Never requested |
| 9 | HTML in a torrent name (`<img src=file:///…>`) | Escaped in tooltips |
| 10 | Open-folder with traversal and quote injection in the name | Only the download folder opens; nothing is launched |
| 11 | Links sent by another Windows user | Refused (user-only local socket) |
| 12 | Real download completes | Hash-verified, 100% |
| 13 | Finished files | Mark-of-the-Web present |
| 14 | Code review | No `os.system`, `startfile` or `eval`; only Explorer, PowerShell (antivirus status), Defender and cloudflared (File Sharing tunnel) are ever launched |
| 15 | New torrent before the Add dialog is confirmed | Paused, every file at priority 0: nothing is requested |
| 16 | CANCEL in the Add dialog | Torrent removed, no files written |
| 17 | Guard findings in the Add dialog | Skipped files proposed as Don't download, with the reason |
| 18 | HTML in a file name (Add dialog, Details tables) | Escaped in tooltips |
| 19 | File Sharing: pairing without the QR token, replayed pairing request | Refused (403) |
| 20 | File Sharing: listing files before the PC user presses Allow; replayed control message | Refused |
| 21 | File Sharing: tampered chunk; upload named `..\..\..\Windows\evil.exe` | Chunk rejected; saved as `FTP\evil.exe` with Mark-of-the-Web |
| 22 | File Sharing: foreign `Host` header (DNS rebinding); connection from a non-private address | Refused (421 / 403) |
| 23 | File Sharing: request posing as tunnel traffic without Cloudflare's client-IP header | Refused (403) |
| 24 | File Sharing: INTERNET mode and a tunnel visitor behind the same router | LAN address never handed out |
| 25 | File Sharing: old tunnel host name after the tunnel stopped | Refused (421) |
| 26 | File Sharing: upload with a 1 MB body from an unknown session | Refused (401) before the body is read |
| 27 | File Sharing: connection flood | Capped at 48; the server serves again afterwards |

## On this PC (checked 2026-10-23)

- Malwarebytes is the registered antivirus, so **Microsoft Defender is off**. Malwarebytes' AMSI interface does
  not scan application buffers (tested with the EICAR test string: not detected), and its command-line tools are
  locked by self-protection. During the Malwarebytes trial, its real-time protection scans files as they are
  written and run. When the trial ends, Windows turns Defender back on and NEON Torrent starts scanning every
  finished download automatically.
- Add a free VirusTotal API key (Preferences → Safety) for a multi-engine check of programs.

## Your part

1. Get torrents from the uploader's official page, not mirrors or re-uploads.
2. Keep real-time antivirus and Windows SmartScreen ("Check apps and files") on.
3. Run unfamiliar installers in **Windows Sandbox** first (Windows 11 Pro: *Turn Windows features on or off →
   Windows Sandbox*).
4. Treat "☣ THREAT", "⚠ risky files skipped" and SmartScreen warnings as real.
5. Peers can see your IP address: that is how BitTorrent works.
