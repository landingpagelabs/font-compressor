"""
Vercel Python serverless function: serves the font library index from Vercel Blob.
GET /api/library -> returns the full index.json
"""

import json
import os
import urllib.request
from http.server import BaseHTTPRequestHandler

BLOB_TOKEN = os.environ.get("BLOB_READ_WRITE_TOKEN", "")
BLOB_API = "https://blob.vercel-storage.com"


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            # Find index.json in blob
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

            # Fetch the index
            index_url = blobs[0]["url"]
            req2 = urllib.request.Request(index_url)
            resp2 = urllib.request.urlopen(req2)
            index_data = resp2.read()

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Cache-Control", "public, max-age=60")
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
