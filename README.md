# NEON Torrent

A Windows desktop BitTorrent client in Python, using PySide6 for the interface and libtorrent 2.x for transfers.

## Start

1. Install 64-bit Python 3.13 if it is not already installed.
2. Run `setup.bat` once. It installs the packages into `.venv` and builds `runtime\NeonTorrent.exe`.
3. Run `run.bat` to start the app. No console window opens; startup errors go to `%APPDATA%\NeonTorrent\error.log`.

You can also pass magnet links, `.torrent` paths, or URLs on the command line:
`run.bat "magnet:?xt=urn:btih:..."`. If the app is already running, the links are sent to that window.
`run.bat --pause-all`, `run.bat --stop-all` and `run.bat --resume-all` control a running instance. The channel accepts only your own
Windows user.

**Disk space:** if a drive fills up, libtorrent stops writing and the torrent goes upload-only. NEON Torrent shows
this as **Disk full** (red), with the space needed and the space free. It warns when a new download will not fit, and
resumes automatically once there is room again. Use *Move data* (row menu or Torrent settings) to move a torrent to
another drive.

`runtime\NeonTorrent.exe` is a renamed copy of the signed Python interpreter with its own `._pth` file
(`tools\make_runtime.py`). Windows, the firewall, and the antivirus therefore see **NeonTorrent.exe** instead of the
shared `python.exe`, so the app can be allowed or blocked without affecting other Python programs. Run `setup.bat`
again after upgrading Python. Windows Firewall asks once for the new exe: allow it on Private networks.

## Shield: peer filtering and antivirus alerts

Every peer connection is bound to one torrent by its info-hash, and every piece is hash-checked before it is
written, so a peer can only ever deliver that torrent's data. Antivirus web protection (Malwarebytes here) does not
look at that data. It blocks connections by IP reputation from a private list, and public swarms always contain some
flagged addresses, mostly VPN or datacenter exits. The Shield works in two steps:

- **Refuses VPN and datacenter peers before contact (default).** Uses the X4BNet VPN and datacenter range lists
  (refreshed daily) plus Cloudflare WARP. Seedbox hosts Hetzner, OVH and Scaleway stay allowed, and web-seed mirrors
  are resolved and kept reachable. On this PC's real alert history, 12 of 13 flagged peers would have been refused
  before any contact.
- **Learns from Malwarebytes.** Reads `C:\ProgramData\Malwarebytes\MBAMService\MwacDetections` every 2 s. Each IP or
  tracker it blocked for a torrent program (this app, uTorrent, qBittorrent, and others) goes into libtorrent's IP
  filter and tracker list, so it is never contacted again. Past detections are imported on first run.
- **Whole network on first flag (default).** A flagged IP's /24 neighbours are blocked too. Its whole network is
  blocked if it is hosting-sized (2 million IPv4 addresses or fewer). Large ISPs such as Jio, Airtel, or BSNL and CDN
  backbones such as Cloudflare or Akamai are never blocked whole. *Balanced* and *Exact IP only* are in
  Preferences → Shield.
- **File-only network (default).** Turns off DHT and Local Peer Discovery, so the only remote hosts contacted are
  your torrents' trackers and peers. Incoming peers (UPnP / NAT-PMP port mapping, IPv4 and IPv6) are allowed by
  default: they must present one of your torrents' info-hashes and pass the same IP filter. Turn them off in
  Preferences → Shield if you want outgoing connections only. DHT can be turned back on (read-only) for magnets
  that have no trackers.
- **Connection map** (shield button or `Ctrl+M`). Shows every live peer with its torrent, network (ASN), country,
  client, how it was found (tracker, PEX, or DHT), direction, and speed. Also lists refused peers with the reason,
  and all learned blocks with an unblock option. Click a header to sort; drag a divider to widen a column, or
  double-click it to fit; drag the corner or use the maximise button to enlarge the window. Network data comes from
  the public iptoasn.com dataset and is refreshed weekly.

What it can and cannot do: a peer that Malwarebytes flags but has not flagged before can still cause one alert,
because its list is private. After that the address, and usually its network, is never dialled again. To stop the
alerts for this app completely, add the exe to Malwarebytes yourself: **Settings → Allow List → Add → Allow an
application to connect to the internet → `runtime\NeonTorrent.exe`**. Malwarebytes still scans every downloaded file
on disk.

## Download Guard: file safety

No torrent client can make a malicious file safe: pieces are verified against the torrent, so you get exactly
what the uploader published. The Guard covers what a client can control. Details and the attack-test results are in
[SECURITY.md](SECURITY.md).

- **Before download:** these are never downloaded:
  - disguised programs (`movie.mp4.exe`)
  - shortcuts (`.lnk`, `.url`)
  - names with hidden Unicode direction characters
  - programs or scripts inside media torrents
  - symbolic links
  - Windows device names

  *Strict* mode also skips every program and script.
- **After download:** files get Mark-of-the-Web, so SmartScreen checks programs before they run. Microsoft Defender
  scans the torrent when it is active, and an optional VirusTotal key adds a hash lookup for programs (only the
  hash is sent). If a threat is found, seeding stops and you are alerted.
- The status column shows the result: ⚠ risky files skipped · ✓ scanned clean · ✓ marked · ☣ THREAT.
- Check the client any time: `.venv\Scripts\python.exe tools\security_audit.py` (14 real attack tests, offline).

## Speed

These apply in every mode and do not widen what the client talks to:

- Announces to **every tracker in every tier**. libtorrent's default stops at the first working tier, which leaves a
  torrent with 50 trackers using only one of them.
- The upload cap counts **payload only**. TCP/IP overhead from downloading (ACKs) is no longer charged to it, so a
  small cap such as 24 KiB/s no longer starves your own piece requests.
- Faster peer ramp-up (connection rate, connect boost, shorter connect timeout) and more hashing threads for checks.
- Peers reward clients that upload back. If a download is still slow, raising the upload cap is the quickest fix.

**FLASH MODE** (the ⚡ FLASH button next to Shield and Settings, or `Ctrl+Shift+F`) is a manual boost for big
torrents. It adds every file source at once: read-only DHT (asks only about your own torrents and serves nobody
else's lookups), Local Peer Discovery, a few long-lived public booster trackers, and up to 1500 connections. Peers
found this way are still Shield-filtered. DHT directory nodes are not, because libtorrent's IP filter does not cover
the DHT, so an antivirus alert is possible while Flash is on. Turning Flash off removes the booster trackers again.
Flash mode resets to off when the app restarts.

## Speed limits and per-torrent settings

- **Speed limits**: click the DOWNLOAD or UPLOAD card, or the gear on UPLOAD LIMIT. Global caps apply instantly, with
  presets.
- **Torrent settings**: click a torrent's name (or `Ctrl+T`, or *Torrent settings…* in the row menu). Everything
  applies instantly:
  - download and upload caps, connection and upload-slot limits
  - sequential download, first and last pieces first, super seeding, force start
  - stop seeding at a share ratio
  - queue up, down, top, and bottom
  - force recheck, skip hash check, reannounce
  - open folder, move data, copy magnet
  - add trackers
- **Skip hash check** marks data on disk as complete without hashing it first. libtorrent still verifies each piece
  the first time it is uploaded, and if the files are missing it falls back to a normal download.

## Layout

| File | Purpose |
| --- | --- |
| `src/neon_torrent.py` | Main window, frameless title bar, tray, single-instance, shortcuts |
| `src/neontorrent/engine.py` | libtorrent session in its own thread: alerts, resume data, all torrent actions |
| `src/neontorrent/shield.py` | VPN/datacenter pre-filter, Malwarebytes learning, network database, block rules |
| `src/neontorrent/guard.py` | Download Guard: file inspection, Mark-of-the-Web, Defender / VirusTotal scans |
| `src/neontorrent/transfers.py` | Transfers table model, filter/sort proxy, neon row painter |
| `src/neontorrent/widgets.py` | Glow panels, glow buttons, stat cards with sparklines, status line |
| `src/neontorrent/dialogs.py` | Preferences, torrent details/settings, speed limits, Shield connection map |
| `src/neontorrent/icons.py` | Vector icons, logo and file-type badges painted in code |
| `src/neontorrent/theme.py` | Palettes, fonts, formatting, settings storage |
| `tools/make_runtime.py` | Builds `runtime\NeonTorrent.exe` |
| `tools/security_audit.py` | Offline security self-test (malicious torrents, injection, SSRF, Mark-of-the-Web) |

## Features

- Add magnet links, bare info-hashes, HTTP(S) `.torrent` URLs, and local `.torrent` files (multi-select, drag and drop, or Ctrl+V on the list).
- Pause, stop, resume, remove (keep files), and delete data, on one or many selected torrents. **Pause** is temporary
  (finishes blocks in flight). **Stop** disconnects at once, closes the files, stops seeding, and stays stopped after a
  restart until you resume it.
- Row menu (`⋯` or right-click): details, force recheck, ask trackers for peers, sequential download, open folder, copy magnet link, move data.
- Details window: general info, per-file progress with skip/download toggles and Guard safety notes, connected
  peers, trackers. The Files, Peers, and Trackers tabs sort by any column and have resizable, movable columns with
  horizontal scrolling; the window itself can be resized or maximised.
- Full resume data: progress, paused state, and file choices survive restarts without rechecking.
- Upload cap (default 24 KiB/s), optional download cap, listen port, and connection limit.
- Tracker and IP blocklist (Preferences → Shield), plus everything learned from Malwarebytes.
- Live speed sparklines, connection state, ETA, ratio, seeds/peers tooltips.
- Sorting by any column; filter box matches name and status.
- Status chips above the list: All, Downloading, Seeding, Completed, Active, Paused, Stopped and Errors, each with a
  live count. The chosen chip is remembered.
- System tray with pause all/resume all, optional close-to-tray, and download-complete notifications.
- Quitting hides the window at once; state is saved in the background and the app exits within seconds.
- Cyberpunk (default), Synthwave, Dark, and Solarized themes.

## Keyboard

`Ctrl+O` open file · `Ctrl+N` focus link box · `Ctrl+F` filter · `Ctrl+M` Shield map · `Ctrl+Shift+F` FLASH MODE ·
`Ctrl+T` torrent settings · `Ctrl+,` preferences · `Space` pause/resume · `Ctrl+Shift+S` stop · `Del` remove · `Shift+Del` delete data ·
`Enter` details · `Alt+1` … `Alt+8` status chips · `Ctrl+Q` quit.

## Data

Stored under `%APPDATA%\NeonTorrent`: `settings.json`, `session\*.fastresume` (torrent state),
`session\meta.json` (ratio limits and per-torrent flags), `shield\learned.json` (learned blocks), and
`shield\ip2asn.cache` (network database).
Magnet links saved by version 1 in `torrents.json` are imported once on first launch.
