# Product Hunt

## Tagline

A torrent client with peer filtering and file checks

## Description

NEON Torrent adds Shield peer filtering and Download Guard file checks to a Windows BitTorrent client. See peer connections, control transfers in detail, and get clear alerts when files need attention.

## Maker’s first comment

Hi Product Hunt — we made NEON Torrent for people who want more visibility and control in a desktop torrent client.

The Shield filters known VPN and datacenter ranges before contact by default, and it can learn from Malwarebytes blocks. The connection map shows live peers, their network details, refusal reasons, and learned blocks. Download Guard checks file names and types before download, adds Mark-of-the-Web after download, and can scan with Microsoft Defender when it is active. VirusTotal hash lookups are optional; NEON sends the program hash, not the file.

We’ve tried to be precise about what these protections can do. A new address that an antivirus flags can still cause an alert before NEON learns it. FLASH mode can also contact DHT directory nodes that the IP filter cannot cover. And no torrent client can prove that an uploader’s file is safe. Keep your antivirus and SmartScreen on.

NEON also includes per-torrent settings, transfer queues, status filters, a connection map, and four themes. We’d value feedback on which parts of the transfer and safety workflow are clearest, and where the interface needs work.

— NEON team

## Gallery captions

1. **Shield connection map** — See live peers, refusal reasons, and learned blocks.
2. **Download Guard** — Review skipped files, scan results, and safety alerts.
3. **Transfer controls** — Filter statuses and tune settings for each torrent.
