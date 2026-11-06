"""Build the File Sharing phone page into src/neontorrent/share_web (index.html, app.js, app.css).

    .venv\\Scripts\\python.exe tools\\build_share_web.py

Needs Node.js (E:\\node). npm packages, caches and temp files live under F:\\neon-build\\share-web, never on C:.
The built files are committed, so the app itself needs no Node.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "tools" / "share_web"
OUT = ROOT / "src" / "neontorrent" / "share_web"
BUILD = Path(os.environ.get("NEON_SHARE_BUILD", str(ROOT.parent / "neon-build" / "share-web")))
NODE_DIR = Path(os.environ.get("NEON_NODE", r"E:\node"))
PACKAGES = ["@noble/curves@2.4.0", "@noble/ciphers@2.4.0", "@noble/hashes@2.4.0", "esbuild@0.28.2",
            "tailwindcss@3.4.19"]


def run(args: list[str], env: dict) -> None:
    print(">", " ".join(args))
    subprocess.run(args, check=True, env=env, cwd=BUILD)


def main() -> int:
    BUILD.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, PATH=f"{NODE_DIR};{os.environ.get('PATH', '')}", NODE_PATH=str(BUILD / "node_modules"),
               npm_config_cache=str(BUILD.parent / "npm-cache"), TEMP=str(BUILD.parent / "tmp"),
               TMP=str(BUILD.parent / "tmp"))
    node = str(NODE_DIR / "node.exe")
    if not (BUILD / "node_modules" / "esbuild").is_dir():
        if not (BUILD / "package.json").exists():
            (BUILD / "package.json").write_text('{"private": true}\n', encoding="utf-8")
        run([str(NODE_DIR / "npm.cmd"), "install", "--save-exact", *PACKAGES], env)
    OUT.mkdir(parents=True, exist_ok=True)
    esbuild = BUILD / "node_modules" / "esbuild" / "bin" / "esbuild"
    run([node, str(esbuild), str(SOURCE / "app.js"), "--bundle", "--minify", "--format=iife", "--target=es2020",
         "--legal-comments=eof", f"--outfile={OUT / 'app.js'}"], env)
    tailwind = BUILD / "node_modules" / "tailwindcss" / "lib" / "cli.js"
    run([node, str(tailwind), "-c", str(SOURCE / "tailwind.config.js"), "-i", str(SOURCE / "input.css"),
         "-o", str(OUT / "app.css"), "--minify"], env)
    shutil.copyfile(SOURCE / "index.html", OUT / "index.html")
    for name in ("index.html", "app.js", "app.css"):
        print(f"{name}: {(OUT / name).stat().st_size:,} bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
