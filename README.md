# NEON Torrent

A Windows desktop BitTorrent client in Python, using PySide6 for the interface and libtorrent 2.x for transfers.

## Start

1. Install 64-bit Python 3.13 if it is not already installed.
2. Run `setup.bat` once. It installs the packages into `.venv` and builds `runtime\NeonTorrent.exe`.
3. Run `run.bat` to start the app. No console window opens; startup errors go to `%APPDATA%\NeonTorrent\error.log`.
   The first start asks where downloads go (default `Downloads\NEON`) and explains File-only mode; change either
   later in Preferences.

You can also pass magnet links, `.torrent` paths, or URLs on the command line:
`run.bat "magnet:?xt=urn:btih:..."`. If the app is already running, the links are sent to that window.
`run.bat --pause-all`, `run.bat --stop-all` and `run.bat --resume-all` control a running instance. The channel accepts only your own
Windows user.

**Disk space:** if a drive fills up, libtorrent stops writing and the torrent goes upload-only. NEON Torrent shows
this as **Disk full** (red), with the space needed and the space free. The Add dialog shows when a new download will
not fit, and the torrent resumes automatically once there is room again. Use *Move data* (row menu or Torrent settings) to move a torrent to
another drive.

`runtime\NeonTorrent.exe` is a renamed copy of the signed Python interpreter with its own `._pth` file
(`tools\make_runtime.py`). Windows, the firewall, and the antivirus therefore see **NeonTorrent.exe** instead of the
shared `python.exe`, so the app can be allowed or blocked without affecting other Python programs. Run `setup.bat`
again after upgrading Python. Windows Firewall asks once for the new exe: allow it on Private networks.

**Windows Installer (MSI).** `.venv\Scripts\python.exe tools\build_msi.py` builds
`neon-build\msi\out\NEON-Torrent-Setup.msi` and `NEON-Torrent-Setup.exe`. The exe is the file to share: a small
native launcher (`tools\setup_stub`, built with Zig) with the NEON icon and version info. It carries the MSI, unpacks
it into a fresh folder under `%TEMP%`, runs `msiexec /i` on it and deletes it afterwards. A bare `.msi` always shows
the generic Windows Installer icon. Nuitka (with the Zig C compiler)
compiles the app to a native `NeonTorrent.exe`; Python, a browser and the VC++ Redistributable are not needed on
the target PC. WiX 3.14 (`neon-build\tools\wix314`) packs it from `packaging\NeonTorrent.wxs`. The installer shows
the user agreement, privacy policy and disclaimer (`packaging\PRIVACY.txt`) and installs for all users, by
default to `F:\Apps\NEON Torrent`. It adds an entry in Programs and Features, a Start menu shortcut, an optional
desktop shortcut and a launch option. The app keeps its data in the `data` folder there, and uninstalling keeps
that data. If NEON Torrent is already installed, Setup shows the installed version next to its own, the update
log (`packaging\CHANGELOG.txt`) and two choices: **Upgrade** (keeps the folder and the data) or **Full uninstall**
(optionally also deletes the `data` folder; downloaded files are never deleted). Full uninstall appears only when
an installed copy is found. `--no-compile` reuses the last Nuitka build. The package contains no certificates or keys: File Transfer
creates fresh keys on the user's device for each session.

**Store package.** `.venv\Scripts\python.exe tools\make_msix.py` builds `NeonTorrent.msix` (about 40 MB): the app with
its own interpreter, the standard library and only the Qt parts it uses. Add `--sandbox` to sign it with a throwaway
certificate, install it and start it in Windows Sandbox; the report goes to `neon-build\msix\results` next to the project folder. The package
adds inbound firewall rules for NeonTorrent.exe on install. Windows keeps the Store version's data under
`%LOCALAPPDATA%\Packages\NeonTorrent_…\LocalCache\Roaming\NeonTorrent` instead of `%APPDATA%\NeonTorrent`.

## Adding a torrent: choose files first

Every add (`.torrent` file, HTTP(S) link, magnet, info-hash) opens the **Add torrent** dialog. Nothing downloads until
you press **DOWNLOAD**.
- **Save to:** defaults to your download folder; *Browse* picks another. The line under it shows the selected size
  against the free space on that drive, in red when it will not fit.
- **Files:** tick the files you want. The Priority column shows **High**, **Normal**, **Low** or **Don't download**.
  Select several rows and right-click → *Priority* to set them together; *All* and *None* tick or clear everything,
  and the total updates as you go. *All* leaves files the Download Guard flagged as dangerous off; tick those one by
  one if you really want them.
- **Download Guard first:** files the Guard skips arrive as *Don't download*, with the reason in the Safety column.
- **Magnets** fetch only the file list first. The dialog shows "Fetching the file list…" until it arrives.
- **CANCEL** (or closing the dialog) removes the torrent. Nothing was downloaded, and files already in the folder are
  never touched.
- A torrent still waiting for its choice shows **Choose files** in the list and stays paused. *Resume* opens its
  dialog again, and so does the next start of the app.

Later, in any state (downloading, idle, paused, stopped), right-click → *Details…* → **Files** has the same checkboxes,
Priority column and right-click menu. Changes apply at once.

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
- Check the client any time: `.venv\Scripts\python.exe tools\security_audit.py` (18 real attack tests, offline).

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

## File Sharing: phone and PC, over Wi-Fi or the internet

The **FILE SHARING** tab at the top of the window (next to **TORRENTS**, or `Ctrl+Tab`) moves files between this PC
and a phone, at home or away. The phone needs only its browser (Android Chrome, iPhone Safari); nothing is installed.

**LAN | INTERNET toggle** (next to **TO PHONE | FROM PHONE**; remembered):
- **INTERNET** (default): the app opens a free Cloudflare quick tunnel (the installed `cloudflared`, no account) and
  the QR code appears only once the tunnel is connected, carrying its `https://….trycloudflare.com` address. A phone
  anywhere, on any network or mobile data, can scan it. If the tunnel fails, the QR area says why; press **NEW QR**
  to try again, or switch to LAN. No port is opened on your router.
- **LAN**: no tunnel at all; the QR code is the direct LAN address, for phones on this Wi-Fi only (fastest).

A **LAN** or **INTERNET** badge next to the status shows the path the phone actually uses, also in the phone's
header. Files are end-to-end encrypted on both paths; Cloudflare relays only ciphertext.

1. Open **FILE SHARING**. A sharing session starts and shows a QR code. **SEND TO PHONE** and **RECEIVE FROM PHONE**
   each have their own code; both open the same page, which has *Send to PC* and *Get from PC* tabs.
2. Scan it with the phone camera. The first time, the phone asks for a name (remembered on the phone). Click the QR
   code to zoom it to 500 × 500 with its hint; the zoom closes with its X, a click anywhere outside it, or as soon as
   a phone connects.
3. The PC asks **Allow “name” (model, IP, MAC)?** Allow it once; the phone stays trusted until you press
   **DISCONNECT**, **STOP**, quit the app, or the phone stays away for 10 minutes. The QR code changes after every
   answer, so a code someone photographed cannot be used again.
4. **PC → phone**: *ADD FILES* (or drop files on the grid). On the phone, *Get from PC* shows them with previews;
   tick what you want and tap *Save to phone*. They go to the phone's Downloads.
   **Phone → PC**: on the phone, *Choose files*, remove any with its X, tap *Send to PC*. Files are saved in
   `<download folder>\FTP\` (names are cleaned; an existing name becomes `name (1).ext`).
   **Text phone → PC**: on the phone, open the *Text* tab, paste (or type) up to 20,000 characters and tap
   *Send text*. *Paste* reads the clipboard in INTERNET mode (HTTPS); on LAN, long-press the box and paste. On the
   PC, **TEXT FROM PHONE** (under the network panel) shows the unread count; click it to pop out the chat panel.
   Each message has a one-click **COPY** at its top right, and any part can be selected with the mouse (Ctrl+C).
   *Clear* empties the panel; messages are never saved to disk.

Both sides show thumbnails (photos and video first frames; a type icon otherwise), an X on every tile (remove before
sending, cancel during a transfer), per-file progress with a ✓ when done, and the overall count (5/12), speed and
time left. The status reads *Ready to connect*, *Waiting for approval*, *Connected*, *Transferring* or
*Disconnected* (no heartbeat for 8 s). The network panel shows this PC's IP, MAC and Wi-Fi name, and the phone's
name, IP and MAC.

Limits:
- The internet path is slower than LAN and depends on Cloudflare's free quick tunnels (no uptime guarantee). The
  tunnel address changes on every START and every DISCONNECT. Guest networks and "client isolation" on some routers
  block the direct LAN path; the phone then stays on INTERNET. The first time, Windows Firewall may ask to allow NeonTorrent on private networks.
- Browsers on plain HTTP do not report the exact phone model: Android Chrome says "Android phone", iPhone says
  "iPhone". Phones also use a random **private MAC** per Wi-Fi network; the panel says so when it sees one.
- Windows hides the Wi-Fi name from apps without Location access; the panel then says so.
- *Save to phone* holds a file in the phone browser's memory before saving it, so very large files (several GB) may
  fail on phones with little memory. Keep the phone screen on during a transfer.

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
| `tools/make_notices.py` | Builds `THIRD-PARTY-NOTICES.md` from the real licence files of Python, Qt, libtorrent and the rest |
| `tools/security_audit.py` | Offline security self-test (malicious torrents, injection, SSRF, Mark-of-the-Web) |

## Features

- Add magnet links, bare info-hashes, HTTP(S) `.torrent` URLs, and local `.torrent` files (multi-select, drag and drop, or Ctrl+V on the list). Each add opens the Add dialog: save folder, free space, files and priorities.
- Pause, stop, resume, remove (keep files), and delete data, on one or many selected torrents. **Pause** is temporary
  (finishes blocks in flight). **Stop** disconnects at once, closes the files, stops seeding, and stays stopped after a
  restart until you resume it.
- Row menu (`⋯` or right-click): details, force recheck, ask trackers for peers, sequential download, open folder, copy magnet link, move data.
- Details window: general info, per-file progress with checkboxes, High / Normal / Low / Don't download priorities
  (right-click several files) and Guard safety notes, connected
  peers, trackers. The Files, Peers, and Trackers tabs sort by any column and have resizable, movable columns with
  horizontal scrolling; the window itself can be resized or maximised.
- Full resume data: progress, paused state, and file choices survive restarts without rechecking.
- Upload cap (default 24 KiB/s), optional download cap, listen port, and connection limit.
- Tracker and IP blocklist (Preferences → Shield), plus everything learned from Malwarebytes.
- Live speed sparklines, connection state, ETA, ratio, seeds/peers tooltips.
- Sorting by any column; filter box matches name and status.
- Three pages above the list, each with a live count: **Downloading** (not finished yet), **Completed** (finished,
  without the progress and download-speed columns) and **All transfers**. Each page has its own status chips (All,
  Active, Paused, Stopped, Errors, and Seeding where it applies; All transfers keeps every chip). The page and chip you
  chose are remembered.
- System tray with pause all/resume all and download-complete notifications. The window's X asks **Minimize to tray** or **Exit**, with *Remember my choice*; change it later in Preferences → General → Close button.
- Quitting hides the window at once. The engine then flushes the disk cache and saves every torrent's state (up to 45 s
  for big sessions) before the process exits. If you start NEON again meanwhile, the new window waits for that save
  instead of disappearing.
- Cyberpunk (default), Synthwave, Dark, and Solarized themes.
- Preferences → About shows the version and the open-source licences (`THIRD-PARTY-NOTICES.md`, shipped in the Store
  package).

## Keyboard

`Ctrl+O` open file · `Ctrl+N` focus link box · `Ctrl+F` filter · `Ctrl+M` Shield map · `Ctrl+Shift+F` FLASH MODE ·
`Ctrl+T` torrent settings · `Ctrl+,` preferences · `Space` pause/resume · `Ctrl+Shift+S` stop · `Del` remove · `Shift+Del` delete data ·
`Enter` details · `Ctrl+1` … `Ctrl+3` pages · `Alt+1` … `Alt+8` status chips · `Ctrl+Tab` TORRENTS / FILE SHARING ·
`Ctrl+Q` quit.

## Data

Stored under `%APPDATA%\NeonTorrent`: `settings.json`, `session\*.fastresume` (torrent state),
`session\meta.json` (ratio limits and per-torrent flags), `shield\learned.json` (learned blocks), and
`shield\ip2asn.cache` (network database).
Magnet links saved by version 1 in `torrents.json` are imported once on first launch.

Your torrent list survives crashes and updates:
- Every save keeps the previous file as `session\<hash>.bak`, and a damaged `.fastresume` is restored from it.
- Once a day at start-up, NEON copies `session\` to `session\backups\<date>` and keeps the newest three.
- A torrent that cannot be restored at all is named in the status line and its files are kept as `.broken`. It is
  never dropped silently.

## Disclaimer

NEON Torrent is a general-purpose file transfer tool, provided as is, without warranty of any kind. To the fullest
extent the law allows, its author accepts no liability for any use of it for illegal, harmful or malicious purposes,
or for any loss or damage that results from such use. Each user alone is responsible and accountable for what they
use NEON for: what they download, share and run, and for following the laws of their country. The same text is shown
on the installer's first page and in Preferences → About.
