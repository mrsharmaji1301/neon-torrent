# X launch copy

## Launch thread

1/7 I made NEON Torrent: a Windows BitTorrent client with peer filtering, file checks, and detailed transfer controls.

2/7 Shield refuses known VPN and datacenter ranges before contact by default. It can also learn from Malwarebytes blocks and filter an IP or tracker on later attempts.

3/7 A new address that Malwarebytes flags can still cause one alert before Shield learns it. The connection map shows live peers, refusal reasons, and learned blocks.

4/7 Download Guard skips several risky file names and types before download, adds Mark-of-the-Web after download, and scans with Defender when Defender is active.

5/7 Optional VirusTotal lookups send a program’s hash, not the file. If a threat is found, NEON stops seeding and alerts you.

6/7 No torrent client can prove an uploader’s file is safe. Keep antivirus and SmartScreen on; use Windows Sandbox for unfamiliar installers.

7/7 NEON also includes per-torrent limits, queue controls, live status filters, disk-full handling, and four themes. Feedback on the workflow and clarity is welcome.

## Posts for the week after launch

### Post 1 — Peer visibility

The NEON connection map shows live peers, their network details, how they were found, and why a peer was refused. Learned blocks can be reviewed and unblocked from the same view.

### Post 2 — File checks

Download Guard checks file names and types before download, adds Mark-of-the-Web after download, and can scan with Microsoft Defender when Defender is active. It can’t make a malicious upload safe.

### Post 3 — Honest limits

Shield learns from Malwarebytes blocks, but a new flagged peer can still cause one alert first. FLASH mode can contact DHT directory nodes that libtorrent’s IP filter cannot cover. Keep antivirus on.

### Post 4 — Transfer controls

NEON has per-torrent speed and connection settings, queue controls, recheck and reannounce actions, and live status filters. The chosen status chip is remembered.

### Post 5 — Disk space

When a drive fills, NEON reports the space needed and the space free, then resumes automatically when there’s room. You can also move a torrent’s data to another drive.
