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
| 14 | Code review | No `os.system`, `startfile` or `eval`; only Explorer, PowerShell (antivirus status) and Defender are ever launched |
| 15 | New torrent before the Add dialog is confirmed | Paused, every file at priority 0: nothing is requested |
| 16 | CANCEL in the Add dialog | Torrent removed, no files written |
| 17 | Guard findings in the Add dialog | Skipped files proposed as Don't download, with the reason |
| 18 | HTML in a file name (Add dialog, Details tables) | Escaped in tooltips |

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
