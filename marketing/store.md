# Microsoft Store listing

## Short description

A Windows torrent client with peer filtering, file checks, and detailed transfer controls.

## Full description

NEON Torrent is a BitTorrent client for Windows. It gives you clear control over transfers and adds two protection layers: one around peer connections and one around downloaded files.

**Shield filters peers.** By default, it refuses known VPN and datacenter ranges before contact, learns from Malwarebytes blocks, and shows connections, learned blocks, and refusal reasons in a map. A new address Malwarebytes flags can still cause one alert before the Shield learns it. FLASH mode, off by default, adds read-only DHT for speed; DHT directory nodes cannot be IP-filtered.

**Download Guard checks files.** Before downloading, it skips disguised programs, shortcuts, hidden Unicode direction characters, programs or scripts inside media torrents, symbolic links, and Windows device names. After download, it adds Mark-of-the-Web and scans with Microsoft Defender when Defender is active. An optional VirusTotal key can look up program hashes; only the hash is sent. If a threat is found, seeding stops and NEON alerts you.

NEON never opens or runs downloaded files. BitTorrent verifies pieces against the torrent’s hashes, but that does not prove the uploader’s files are safe. Keep your antivirus and SmartScreen on, and use Windows Sandbox for unfamiliar installers.

Manage transfers with pause, stop, resume, per-torrent limits, queue controls, file selection, tracker tools, and a live status filter. If a drive fills up, NEON reports the space needed and free, then resumes automatically when room is available.

## Features

- Refuses peers in known VPN and datacenter ranges before contact by default.
- Learns from Malwarebytes blocks and adds blocked IPs or trackers to the filter.
- Displays live peers, network details, refusal reasons, and learned blocks in the connection map.
- Starts with DHT and Local Peer Discovery off; FLASH mode can enable read-only DHT and Local Peer Discovery.
- Skips disguised programs, shortcuts, hidden direction characters, and Windows device names before download.
- Skips programs and scripts inside media torrents; Strict mode also skips all programs and scripts.
- Adds Mark-of-the-Web to downloaded files for Windows checks.
- Scans the active torrent with Microsoft Defender when Defender is the active antivirus.
- Optionally looks up program hashes with a VirusTotal API key; the file itself is not sent.
- Stops seeding and alerts you when a threat is found.
- Adds magnet links, info-hashes, HTTP(S) torrent URLs, and local torrent files.
- Pauses, stops, resumes, removes, or deletes data for one or many selected transfers.
- Sets global speed limits and per-torrent speed, connection, and upload-slot limits.
- Supports sequential download, queue controls, recheck, reannounce, and file selection.
- Reports disk-full conditions and resumes automatically when space is available.
- Provides live speed sparklines, transfer details, status filters, and a system tray.
- Offers Cyberpunk, Synthwave, Dark, and Solarized themes.

## Search terms

torrent, BitTorrent client, torrent downloader, magnet link, secure torrent, peer filtering, file transfer

## What’s new in 1.0

NEON Torrent 1.0 brings together Shield peer filtering, Download Guard file checks, detailed transfer controls, a connection map, live status filters, and four interface themes. It also includes disk-full handling, Mark-of-the-Web, and optional VirusTotal hash lookups.
