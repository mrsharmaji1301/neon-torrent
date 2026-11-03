# Final steps (user-approved, 3 Nov 2026). Reply to the user in Hinglish.

0. FIRST, before the build: in the torrent list, show downloaded / total under the progress bar
   (e.g. "12.0 GB / 28.0 GB"). Show the user a preview screenshot (no torrents added: render the row from a fake
   in-memory row on a throwaway profile) and get their OK, then continue with step 1.
   Also fix: in the FILE SHARING tab the hint lines under the QR code overlap the QR (src\neontorrent\share_ui.py,
   QrView / self.hint in the left panel). Include it in the same preview.

1. Wait until the "C-11: QR file sharing" session has finished internet mode (Cloudflare quick tunnel + LAN/INTERNET auto-detect).
2. Final audit: `.venv\Scripts\python.exe -m unittest discover -s tests`, `tools\security_audit.py`,
   `F:\neon-build\tools\gitleaks\gitleaks.exe dir src --no-banner`, ruff (no new warnings). Regenerate THIRD-PARTY-NOTICES.md
   for cryptography, cffi, pycparser, segno and the bundled @noble libs.
3. Build: `.venv\Scripts\python.exe tools\build_installer.py` (TEMP/TMP = F:\neon-build\tmp) -> `F:\neon-build\installer\out\NEON-Torrent-Setup.exe`.
4. Install: `NEON-Torrent-Setup.exe /VERYSILENT /TASKS=desktopicon /DIR="F:\Apps\NEON Torrent"`. Then copy `F:\neon-build\keep\shield\*`
   to `F:\Apps\NEON Torrent\data\shield\` and write `data\settings.json` from `F:\neon-build\keep\blocked_hosts.json` (only blocked_hosts).
   Start the app from its desktop shortcut and check `data\error.log` shows "restored 0 of 0".
5. Commit everything (git add -A; no torrent names anywhere) and push to the private repo `mrsharmaji1301/neon-torrent` only.
   Create a private GitHub release v1.0.0 with NEON-Torrent-Setup.exe attached (`gh release create`).
6. Copy the setup to `F:\NEON-Torrent-Setup.exe`. Delete `F:\neon-data`, the junction `%APPDATA%\NeonTorrent`, `F:\neon-build`
   and finally `F:\neon-torrent` (future work: clone from GitHub). Keep `F:\Apps\NEON Torrent` and `D:\Torrents`.
