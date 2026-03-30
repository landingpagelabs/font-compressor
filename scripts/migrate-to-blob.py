#!/usr/bin/env python3
"""
Migrate existing WOFF2 fonts and data.json to Vercel Blob storage.
Reads BLOB_READ_WRITE_TOKEN from .env.local.
Usage: python3.14 scripts/migrate-to-blob.py
"""

import hashlib
import json
import os
import sys
import urllib.request
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
PROJECT_DIR = SCRIPT_DIR.parent
FONTS_DIR = PROJECT_DIR / "fonts"
SOURCE_TTF_DIR = PROJECT_DIR.parent / "skills" / "design" / "references" / "canvas-design" / "canvas-fonts"

# Load token from .env.local
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


def blob_put(pathname, data, content_type="application/octet-stream"):
    """Upload a file to Vercel Blob. Returns the response with URL."""
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


def hash_file(path):
    """SHA-256 hash of a file."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def migrate():
    # Load existing data.json
    data_path = FONTS_DIR / "data.json"
    if not data_path.exists():
        print(f"Error: {data_path} not found. Run build-library.py first.")
        sys.exit(1)

    with open(data_path) as f:
        families = json.load(f)

    print(f"Migrating {len(families)} families to Vercel Blob...\n")

    for family in families:
        print(f"  {family['family']}:")
        for variant in family["variants"]:
            woff2_path = FONTS_DIR / variant["file"]
            if not woff2_path.exists():
                print(f"    SKIP {variant['file']} (not found)")
                continue

            woff2_data = woff2_path.read_bytes()

            # Compute hash of original TTF for duplicate detection
            ttf_name = variant["file"].replace(".woff2", ".ttf")
            ttf_path = SOURCE_TTF_DIR / ttf_name
            if ttf_path.exists():
                variant["hash"] = hash_file(ttf_path)
            else:
                # Hash the WOFF2 itself as fallback
                variant["hash"] = hashlib.sha256(woff2_data).hexdigest()

            # Upload WOFF2 to blob
            blob_pathname = f"fonts/{variant['file']}"
            result = blob_put(blob_pathname, woff2_data, "font/woff2")
            variant["url"] = result["url"]
            print(f"    {variant['file']} -> {result['url'][:60]}...")

    # Upload index.json to blob
    index_data = json.dumps(families, indent=2).encode()
    result = blob_put("index.json", index_data, "application/json")
    print(f"\n  index.json -> {result['url']}")

    # Save a local copy of the updated data with URLs and hashes
    with open(FONTS_DIR / "data-blob.json", "w") as f:
        json.dump(families, f, indent=2)

    print(f"\nDone! {sum(len(f['variants']) for f in families)} fonts uploaded to Vercel Blob.")
    print(f"Index URL: {result['url']}")


if __name__ == "__main__":
    migrate()
