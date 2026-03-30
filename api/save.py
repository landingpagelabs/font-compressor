"""
Vercel Python serverless function: batch update the library index.
Receives an array of new font entries and merges them into the index in one write.
"""

import json
import os
import time
import urllib.request
from http.server import BaseHTTPRequestHandler

BLOB_TOKEN = os.environ.get("BLOB_READ_WRITE_TOKEN", "")
BLOB_API = "https://blob.vercel-storage.com"


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


def blob_get_index():
    try:
        req = urllib.request.Request(
            f"{BLOB_API}?prefix=index.json",
            headers={"Authorization": f"Bearer {BLOB_TOKEN}", "x-api-version": "7"},
        )
        resp = urllib.request.urlopen(req)
        data = json.loads(resp.read())
        blobs = data.get("blobs", [])
        if blobs:
            url = blobs[0]["url"]
            bust = f"{'&' if '?' in url else '?'}t={int(time.time() * 1000)}"
            req2 = urllib.request.Request(url + bust)
            resp2 = urllib.request.urlopen(req2)
            return json.loads(resp2.read())
    except Exception:
        pass
    return []


def send_json(handler, status, data):
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Access-Control-Allow-Origin", "*")
    handler.end_headers()
    handler.wfile.write(json.dumps(data).encode())


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        try:
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length)

            if not body or not body.strip():
                return send_json(self, 400, {"error": "No request body provided."})

            try:
                entries = json.loads(body)
            except (json.JSONDecodeError, ValueError):
                return send_json(self, 400, {"error": "Invalid JSON."})

            if not isinstance(entries, list) or len(entries) == 0:
                return send_json(self, 400, {"error": "Expected a non-empty array of font entries."})

            # Read current index
            index = blob_get_index()

            # Build a set of existing hashes for fast lookup
            existing_hashes = set()
            for fam in index:
                for v in fam.get("variants", []):
                    if v.get("hash"):
                        existing_hashes.add(v["hash"])

            added = 0
            for entry in entries:
                font_hash = entry.get("hash", "")
                if font_hash in existing_hashes:
                    continue  # Skip duplicates

                slug = entry.get("slug", "")
                new_variant = {
                    "style": entry.get("style", "Regular"),
                    "weight": entry.get("weight", 400),
                    "italic": entry.get("italic", False),
                    "file": entry.get("filename", ""),
                    "url": entry.get("url", ""),
                    "sizeOriginal": entry.get("originalSize", 0),
                    "sizeWoff2": entry.get("compressedSize", 0),
                    "hash": font_hash,
                }

                # Find or create family
                family_entry = None
                for fam in index:
                    if fam["slug"] == slug:
                        family_entry = fam
                        break

                if family_entry:
                    family_entry["variants"].append(new_variant)
                    family_entry["variants"].sort(key=lambda v: (v["weight"], v.get("italic", False)))
                else:
                    family_entry = {
                        "family": entry.get("family", slug),
                        "slug": slug,
                        "category": entry.get("category", "sans-serif"),
                        "variants": [new_variant],
                    }
                    index.append(family_entry)

                existing_hashes.add(font_hash)
                added += 1

            # Sort families alphabetically
            index.sort(key=lambda f: f["family"].lower())

            # Single write
            blob_put("index.json", json.dumps(index, indent=2).encode(), "application/json")

            return send_json(self, 200, {"saved": added, "total": len(index)})

        except Exception as e:
            return send_json(self, 500, {"error": f"Save failed: {str(e)}"})

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
