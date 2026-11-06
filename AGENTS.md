# AGENTS.md: rules for every coding agent on NEON Torrent

Read [SHIP_PLAN.md](SHIP_PLAN.md) first. It is the current plan: v1.0 ships on 30 Oct 2026.
- Product direction: [PRODUCT_SCOPE.md](PRODUCT_SCOPE.md).
- User-facing behaviour: [README.md](README.md).
- Security behaviour: [SECURITY.md](SECURITY.md).

## Stack

- Windows 11, Python 3.13 (64-bit), PySide6-Essentials 6.12, libtorrent 2.1.1 (`requirements.txt`).
- `setup.bat` creates `.venv` and builds `runtime\NeonTorrent.exe` (`tools/make_runtime.py`). `run.bat` starts the
  app.
- The libtorrent session runs in its own QThread (`src/neontorrent/engine.py`). The UI talks to it only through
  queued Qt signals and slots. Never call engine methods directly from the UI thread.

## Layout

| Path | Purpose |
|---|---|
| `src/neon_torrent.py` | Main window, title bar, tray, single instance, shortcuts |
| `src/neontorrent/engine.py` | libtorrent session, alerts, resume data, all torrent actions |
| `src/neontorrent/shield.py` | Peer filtering, antivirus learning, network database |
| `src/neontorrent/guard.py` | Download Guard: file inspection, Mark-of-the-Web, scans |
| `src/neontorrent/dialogs.py`, `transfers.py`, `widgets.py`, `icons.py`, `theme.py` | UI |
| `tools/security_audit.py` | Offline attack tests; every test must pass |

## Rules

1. Tasks come from [BOARD.md](BOARD.md). Delegated apps write only inside `inbox/<ID>/`, never run git and never
   edit other files. Claude reviews, moves accepted work into place and makes every commit.
2. Changes to security-critical code need Claude's review. That code is:
   - `shield.py` and `guard.py`
   - the IP filter and alert handling in `engine.py`
   - licence code and the IPC server
   - anything that parses torrents, magnets, URLs or network input
3. Before asking for review, run `.venv\Scripts\python.exe tools\security_audit.py`. All tests must pass.
4. No pirated content anywhere: code, tests, fixtures, screenshots, docs or posts. Use Ubuntu/Debian ISOs and open
   movies (Blender) as examples.
5. No telemetry, ads, bundled offers or crypto miners. Never commit secrets (`.env`, `*.pfx`, API keys, licence
   signing keys).
6. Edit files with an editor tool, not shell heredocs: Git Bash mangles `\n` and `\\` inside strings.
7. Match the surrounding code: type hints, existing naming, comment density, and the neon theme in `theme.py`.
8. Update README.md for user-facing changes and SECURITY.md for security behaviour in the same change.
9. Nothing goes on drive C: (it is full). The project lives at `E:\PROJECTS\NEON\neon-torrent`. Put build output,
   temp files and caches under `E:\PROJECTS\NEON\neon-build` (the tools default to the `neon-build` folder next to
   the repo): set `TEMP`, `TMP` and `PIP_CACHE_DIR` there before building or installing.
