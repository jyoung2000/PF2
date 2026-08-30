#!/usr/bin/env python3
"""Capture a login session for a browser-based scraper site (5.2).

Runs a HEADED Chromium on your desktop, lets you log in manually, then exports
the Playwright storage_state JSON that the PromptForge container consumes.

Usage (on a desktop with a display, NOT inside the container):
    pip install playwright && playwright install chromium
    python scripts/capture_login.py midjourney
    python scripts/capture_login.py tensorart --out ./data/sessions

Then copy the exported file to your server:
    <appdata>/promptforge/sessions/<site>.json
(mapped to /data/sessions/<site>.json inside the container — the scrapers
dashboard shows the session as valid once the file is in place.)
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

SITES = {
    "x": "https://x.com/login",
    "midjourney": "https://www.midjourney.com/explore",
    "tensorart": "https://tensor.art/",
    "seaart": "https://www.seaart.ai/",
    "pixai": "https://pixai.art/",
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("site", choices=sorted(SITES),
                        help="which site to capture a login for")
    parser.add_argument("--out", default="./data/sessions",
                        help="output directory (default ./data/sessions)")
    args = parser.parse_args()

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("playwright isn't installed. Run:\n"
              "  pip install playwright && playwright install chromium",
              file=sys.stderr)
        return 1

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / f"{args.site}.json"

    print(f"Opening {SITES[args.site]} …")
    print("Log in in the browser window. When you're fully logged in,")
    print("come back here and press <Enter> to export the session.")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()
        page.goto(SITES[args.site])
        try:
            input("\n>>> Press Enter once you're logged in… ")
        except (KeyboardInterrupt, EOFError):
            print("\nCancelled — nothing exported.")
            browser.close()
            return 1
        context.storage_state(path=str(out_file))
        browser.close()

    print(f"\n✓ Session exported to {out_file}")
    print("Copy it to your PromptForge data volume as "
          f"sessions/{args.site}.json and the scraper goes live.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
