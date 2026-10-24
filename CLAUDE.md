@AGENTS.md

## For Claude: working with this user

- Start every session by reading [BOARD.md](BOARD.md): live tasks, statuses and open questions.
- Reply in short, serious, conversational English, even when the user writes or dictates in Hindi or Hinglish.
  Do the work yourself instead of explaining how. Ask only for
  vision, money, accounts or consent decisions, and never assume those.
- Check the PC before claiming anything about it (installed tools, paths, drives). The user's terminal is PowerShell.
- Market or business claims need real data with source links; label your own estimates.
- Show progress during long tests. Ship the controls users expect from similar apps without being asked.
- Never write to drive C:. Project `F:\neon-torrent`; builds, temp and caches `F:\neon-build`; app data
  `F:\neon-data\NeonTorrent` (junction at `%APPDATA%\NeonTorrent`).
- Start the app detached, so it survives session restarts: `explorer.exe "F:\neon-torrent\run.bat"`.
- Only Claude commits and pushes (private repo `mrsharmaji1301/neon-torrent`).
- Claude Pro plan: the weekly limit is the bottleneck, so keep the context small.
- Never clear, reset or restart the chat on your own, even to save tokens. Ask first: the user reads the history.
- Never buy anything: no credits, overages, upgrades, subscriptions or "buy" buttons in any app. The user makes every
  purchase personally.

## Token discipline

- Grep first, then Read only the line ranges you need. Do not re-read a file you already have unless it changed.
- Change files with Edit; never rewrite a whole file to change part of it.
- Batch independent tool calls in one message.
- No recaps and no restated plans. Stop when the task is done.
