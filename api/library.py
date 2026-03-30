"""
Vercel Python serverless function: serves the font library index from Vercel Blob.
GET /api/library -> returns the full index.json (always fresh, no caching)
"""

import json
import os
import time
import urllib.request
from http.server import BaseHTTPRequestHandler

BLOB_TOKEN = os.environ.get("BLOB_READ_WRITE_TOKEN", "")
BLOB_API = "https://blob.vercel-storage.com"


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            # List blobs to find index.json
            req = urllib.request.Request(
                f"{BLOB_API}?prefix=index.json",
                headers={"Authorization": f"Bearer {BLOB_TOKEN}", "x-api-version": "7"},
            )
            resp = urllib.request.urlopen(req)
            data = json.loads(resp.read())
            blobs = data.get("blobs", [])

            if not blobs:
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(b"[]")
                return

            # Use downloadUrl (bypasses CDN) with cache-bust
            index_url = blobs[0].get("downloadUrl") or blobs[0]["url"]
            bust = f"{'&' if '?' in index_url else '?'}t={int(time.time() * 1000)}"
            req2 = urllib.request.Request(index_url + bust)
            resp2 = urllib.request.urlopen(req2)
            index_data = resp2.read()

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
            self.end_headers()
            self.wfile.write(index_data)

        except Exception as e:
            self.send_response(500)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"error": str(e)}).encode())

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
