#!/usr/bin/env python3
"""
Remove orphan library entries whose "family" is just a style word.

These are leftovers from uploads where the original filename had been
stripped to a bare weight (e.g. bold.woff2, extralight.woff2) so the
parser had no real family to recover. The compress endpoint now
rejects new uploads of this shape; this script cleans existing ones.

Dry-run by default. Pass --confirm to rewrite the index.
Pass --delete-blobs to also delete the underlying woff2 files.

    python3 scripts/clean-orphans.py
    python3 scripts/clean-orphans.py --confirm
    python3 scripts/clean-orphans.py --confirm --delete-blobs
"""

import argparse
import json
import re
import sys
import time
import urllib.request
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
PROJECT_DIR = SCRIPT_DIR.parent

ENV_FILE = PROJECT_DIR / ".env.local"
BLOB_TOKEN = None
if ENV_FILE.exists():
    for line in ENV_FILE.read_text().splitlines():
        if line.startswith("BLOB_READ_WRITE_TOKEN="):
            BLOB_TOKEN = line.split("=", 1)[1].strip().strip('"')
            break

if not BLOB_TOKEN:
    print("Error: BLOB_READ_WRITE_TOKEN not found in .env.local")
    sys.exit(1)

BLOB_API = "https://blob.vercel-storage.com"

KNOWN_STYLES = [
    "ExtraBoldItalic", "UltraBoldItalic", "SemiBoldItalic", "DemiBoldItalic",
    "ExtraLightItalic", "UltraLightItalic", "BlackItalic", "BoldItalic",
    "ThinItalic", "LightItalic", "MediumItalic", "HeavyItalic",
    "ExtraBold", "UltraBold", "SemiBold", "DemiBold",
    "ExtraLight", "UltraLight",
    "Black", "Heavy", "Bold", "Medium", "Light", "Thin",
    "Italic", "Regular",
]
WEIGHTS = [
    "Thin", "ExtraLight", "UltraLight", "Light", "Regular", "Medium",
    "SemiBold", "DemiBold", "Bold", "ExtraBold", "UltraBold", "Black", "Heavy",
]
STYLE_WORDS = {s.lower() for s in KNOWN_STYLES} | {w.lower() for w in WEIGHTS} | {
    "extra", "ultra", "semi", "demi", "font",
}


def is_bare_style(family):
    tokens = [t for t in re.split(r"[-_\s]+", family.lower()) if t]
    if not tokens:
        return True
    return all(t in STYLE_WORDS for t in tokens)


def blob_get_index():
    req = urllib.request.Request(
        f"{BLOB_API}?prefix=index.json",
        headers={"Authorization": f"Bearer {BLOB_TOKEN}", "x-api-version": "7"},
    )
    resp = urllib.request.urlopen(req)
    blobs = json.loads(resp.read()).get("blobs", [])
    if not blobs:
        return []
    url = blobs[0].get("downloadUrl") or blobs[0]["url"]
    bust = f"{'&' if '?' in url else '?'}t={int(time.time() * 1000)}"
    resp2 = urllib.request.urlopen(urllib.request.Request(url + bust))
    return json.loads(resp2.read())


def blob_put(pathname, data, content_type="application/octet-stream"):
    req = urllib.request.Request(
        f"{BLOB_API}/{pathname}",
        data=data,
        headers={
            "Authorization": f"Bearer {BLOB_TOKEN}",
            "x-api-version": "7",
            "Content-Type": content_type,
            "x-add-random-suffix": "0",
        },
        method="PUT",
    )
    resp = urllib.request.urlopen(req)
    return json.loads(resp.read())


def blob_delete(url):
    req = urllib.request.Request(
        f"{BLOB_API}/delete",
        data=json.dumps({"urls": [url]}).encode(),
        headers={
            "Authorization": f"Bearer {BLOB_TOKEN}",
            "x-api-version": "7",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    urllib.request.urlopen(req)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--confirm", action="store_true", help="actually rewrite index.json")
    parser.add_argument("--delete-blobs", action="store_true", help="also delete orphan woff2 blobs")
    args = parser.parse_args()

    index = blob_get_index()
    print(f"Loaded index: {len(index)} families")

    keep, drop = [], []
    for fam in index:
        if is_bare_style(fam.get("family", "")) or is_bare_style(fam.get("slug", "")):
            drop.append(fam)
        else:
            keep.append(fam)

    print(f"\nOrphans to remove ({len(drop)}):")
    for fam in drop:
        files = ", ".join(v.get("file", "?") for v in fam.get("variants", []))
        print(f"  - {fam['family']:24s} [{fam.get('category','?')}]  {files}")

    print(f"\nKeeping {len(keep)} families.")

    if not args.confirm:
        print("\nDry run. Pass --confirm to write changes.")
        return

    if not drop:
        print("Nothing to do.")
        return

    blob_put("index.json", json.dumps(keep, indent=2).encode(), "application/json")
    print(f"Index rewritten: {len(keep)} families.")

    if args.delete_blobs:
        deleted = 0
        for fam in drop:
            for v in fam.get("variants", []):
                url = v.get("url")
                if url:
                    try:
                        blob_delete(url)
                        deleted += 1
                    except Exception as e:
                        print(f"  ! failed to delete {url}: {e}")
        print(f"Deleted {deleted} orphan blobs.")


if __name__ == "__main__":
    main()
