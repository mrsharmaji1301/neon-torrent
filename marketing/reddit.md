# Reddit launch copy

Use these as replies only when they fit the thread. Keep the disclosure, answer the person’s question first, and follow each subreddit’s rules.

## Reply template 1 — Malwarebytes alert

I made NEON, a Windows torrent client, so I’ve run into this kind of alert too. Malwarebytes may block a peer or tracker based on its IP reputation; public swarms can include flagged addresses. NEON’s Shield learns from Malwarebytes blocks and filters that IP or tracker on later attempts, but a new block can still trigger one alert first. Keep real-time protection on, and don’t treat a clean scan as proof that an uploader’s file is safe.

## Reply template 2 — Defender or file warning

I made NEON, and its Download Guard is built around the limit that a torrent client can’t verify whether the uploader’s file is safe. It skips several risky names and file types before download, adds Mark-of-the-Web, and scans with Microsoft Defender when Defender is the active antivirus. If Defender is off or your security app still warns, take that warning seriously. NEON doesn’t open or run downloaded files. For an unfamiliar installer, use Windows Sandbox and get torrents from the uploader’s official page.

## Reply template 3 — Want fewer peer alerts

I made NEON. Its Shield refuses known VPN and datacenter ranges before contact by default, and its connection map shows live peers, refusal reasons, and learned blocks. It learns from Malwarebytes blocks, so a peer it has not seen flagged before may still cause one alert. FLASH mode can broaden discovery with read-only DHT and Local Peer Discovery; DHT directory nodes are outside libtorrent’s IP filter, so an alert is possible while FLASH is on. If you try it, keep antivirus protection enabled and turn FLASH off when you don’t need it.

## Launch post

**I made NEON, a Windows torrent client with peer filtering and file checks.**

Shield filters known VPN and datacenter ranges before contact by default, learns from Malwarebytes blocks, and gives you a connection map with refusal reasons. Download Guard skips risky file names and types before download, adds Mark-of-the-Web, and can scan with Microsoft Defender when it is active.

It also has per-torrent settings, status filters, queue controls, and disk-full handling. It’s not a promise that every download is safe: the uploader decides what the torrent contains, and a new antivirus block can still cause an alert before Shield learns it.

I’d appreciate feedback on the UI and on which parts of the connection map or Guard results need clearer explanations. Please check the subreddit rules before sharing or discussing a product link.
