"""
Vercel Python serverless function: font subsetting + WOFF2 compression.
- Compresses uploaded fonts to WOFF2 with Basic Latin subsetting
- Checks Vercel Blob index for duplicates (returns deep link if found)
- Saves new fonts to Vercel Blob and updates the index
"""

import base64
import hashlib
import json
import os
import re
import urllib.request
from io import BytesIO
from http.server import BaseHTTPRequestHandler

from fontTools.ttLib import TTFont
from fontTools.subset import Subsetter, Options

BLOB_TOKEN = os.environ.get("BLOB_READ_WRITE_TOKEN", "")
BLOB_API = "https://blob.vercel-storage.com"
MAX_FILE_SIZE = 4_500_000

# Weight mapping from style names
WEIGHT_MAP = {
    "Thin": 100, "ExtraLight": 200, "UltraLight": 200, "Light": 300,
    "Regular": 400, "Medium": 500, "SemiBold": 600, "DemiBold": 600,
    "Bold": 700, "ExtraBold": 800, "UltraBold": 800, "Black": 900, "Heavy": 900,
}


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


def blob_get_json(url):
    req = urllib.request.Request(url)
    resp = urllib.request.urlopen(req)
    return json.loads(resp.read())


def blob_get_index():
    import time
    try:
        # List blobs to find index.json URL
        req = urllib.request.Request(
            f"{BLOB_API}?prefix=index.json",
            headers={"Authorization": f"Bearer {BLOB_TOKEN}", "x-api-version": "7"},
        )
        resp = urllib.request.urlopen(req)
        data = json.loads(resp.read())
        blobs = data.get("blobs", [])
        if blobs:
            # Add cache-bust to avoid stale reads
            url = blobs[0]["url"]
            bust = f"{'&' if '?' in url else '?'}t={int(time.time() * 1000)}"
            req2 = urllib.request.Request(url + bust)
            resp2 = urllib.request.urlopen(req2)
            return json.loads(resp2.read())
    except Exception:
        pass
    return []


def save_index(index_data):
    blob_put("index.json", json.dumps(index_data, indent=2).encode(), "application/json")


def hash_bytes(data):
    return hashlib.sha256(data).hexdigest()


# Known style suffixes (longest first to match greedily)
KNOWN_STYLES = [
    "ExtraBoldItalic", "UltraBoldItalic", "SemiBoldItalic", "DemiBoldItalic",
    "ExtraLightItalic", "UltraLightItalic", "BlackItalic", "BoldItalic",
    "ThinItalic", "LightItalic", "MediumItalic", "HeavyItalic",
    "ExtraBold", "UltraBold", "SemiBold", "DemiBold",
    "ExtraLight", "UltraLight",
    "Black", "Heavy", "Bold", "Medium", "Light", "Thin",
    "Italic", "Regular",
]


def parse_filename(filename):
    stem = filename.rsplit(".", 1)[0] if "." in filename else filename
    # Strip common prefixes
    if stem.lower().startswith("subset-"):
        stem = stem[7:]

    # Try splitting on last hyphen first: FamilyName-Style
    parts = stem.rsplit("-", 1)
    if len(parts) == 2:
        family, style = parts
        # Validate style is a known weight/style name
        if style in KNOWN_STYLES or style in WEIGHT_MAP:
            return family, style
        # Style part might be part of the family name (e.g. Inter18pt)
        # Fall through to style detection below
        family = stem

    else:
        family = parts[0]

    # No valid split found — try to detect style from the end of the name
    for s in KNOWN_STYLES:
        if family.endswith(s) and len(family) > len(s):
            return family[:-len(s)].rstrip("-"), s

    return family, "Regular"


def human_family_name(family):
    spaced = re.sub(r"([a-z])([A-Z])", r"\1 \2", family)
    spaced = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", spaced)
    # Handle digits: "Inter18pt" -> "Inter 18pt"
    spaced = re.sub(r"([a-zA-Z])(\d)", r"\1 \2", spaced)
    return spaced


def get_weight(style):
    clean = style.replace("Italic", "").strip()
    if not clean:
        clean = "Regular"
    return WEIGHT_MAP.get(clean, 400)


def compress_font(font_bytes):
    font = TTFont(BytesIO(font_bytes))

    # Extract font name
    name_table = font.get("name")
    font_name = "Unknown"
    if name_table:
        for record in name_table.names:
            if record.nameID == 4:
                try:
                    font_name = record.toUnicode()
                    break
                except Exception:
                    pass

    # Subset to Basic Latin
    options = Options()
    options.layout_features = ["*"]
    options.name_IDs = ["*"]
    options.notdef_outline = True
    options.recalc_bounds = True
    options.recalc_timestamp = True
    options.drop_tables = []

    subsetter = Subsetter(options=options)
    subsetter.populate(unicodes=set(range(0x0020, 0x007F)))
    subsetter.subset(font)

    font.flavor = "woff2"
    buf = BytesIO()
    font.save(buf)
    woff2_bytes = buf.getvalue()
    font.close()
    return woff2_bytes, font_name


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
            if content_length > MAX_FILE_SIZE * 1.4:
                return send_json(self, 413, {"error": "File too large. Maximum 4.5MB."})

            body = self.rfile.read(content_length)
            if not body or not body.strip():
                return send_json(self, 400, {"error": "No request body provided."})

            try:
                data = json.loads(body)
            except (json.JSONDecodeError, ValueError):
                return send_json(self, 400, {"error": "Invalid JSON in request body."})

            font_b64 = data.get("font")
            filename = data.get("filename", "font.ttf")

            if not font_b64:
                return send_json(self, 400, {"error": "No font data provided."})

            try:
                font_bytes = base64.b64decode(font_b64)
            except Exception:
                return send_json(self, 400, {"error": "Invalid font data. Expected base64-encoded font file."})
            original_size = len(font_bytes)

            if original_size > MAX_FILE_SIZE:
                return send_json(self, 413, {"error": "File too large. Maximum 4.5MB."})

            # Hash the original font for duplicate detection
            font_hash = hash_bytes(font_bytes)

            # Check index for duplicates
            index = blob_get_index()
            for family in index:
                for variant in family.get("variants", []):
                    if variant.get("hash") == font_hash:
                        # Found a duplicate — return the deep link
                        return send_json(self, 200, {
                            "duplicate": True,
                            "slug": family["slug"],
                            "family": family["family"],
                            "category": family.get("category", "sans-serif"),
                            "style": variant["style"],
                            "url": variant.get("url", ""),
                            "sizeWoff2": variant.get("sizeWoff2", 0),
                        })

            # Check if already WOFF2 (magic bytes: wOF2)
            is_woff2 = font_bytes[:4] == b'wOF2' or filename.lower().endswith('.woff2')

            if is_woff2:
                # Already compressed — use as-is
                woff2_bytes = font_bytes
                # Try to read font name from the WOFF2
                try:
                    tmp_font = TTFont(BytesIO(font_bytes))
                    name_table = tmp_font.get("name")
                    font_name = "Unknown"
                    if name_table:
                        for record in name_table.names:
                            if record.nameID == 4:
                                try:
                                    font_name = record.toUnicode()
                                    break
                                except Exception:
                                    pass
                    tmp_font.close()
                except Exception:
                    font_name = "Unknown"
            else:
                # Compress TTF/OTF/WOFF to WOFF2
                woff2_bytes, font_name = compress_font(font_bytes)

            # Parse metadata from filename
            family_key, style = parse_filename(filename)
            family_name = human_family_name(family_key)
            slug = family_key.lower()
            weight = get_weight(style)
            is_italic = "Italic" in style or "italic" in style

            woff2_filename = filename.rsplit(".", 1)[0] + ".woff2" if "." in filename else filename
            if not woff2_filename.endswith(".woff2"):
                woff2_filename += ".woff2"

            # Upload WOFF2 to blob
            blob_result = blob_put(f"fonts/{woff2_filename}", woff2_bytes, "font/woff2")
            font_url = blob_result["url"]

            # Auto-detect category
            category = "sans-serif"
            try:
                det_font = TTFont(BytesIO(font_bytes))
                os2 = det_font.get("OS/2")
                if os2:
                    fc = os2.sFamilyClass >> 8
                    if fc in (1, 2, 3, 4, 5, 7):
                        category = "serif"
                    elif fc == 10:
                        category = "monospace"
                det_font.close()
            except Exception:
                pass

            # Return font data — index update happens via /api/save batch endpoint
            return send_json(self, 200, {
                "duplicate": False,
                "alreadyCompressed": is_woff2,
                "filename": woff2_filename,
                "fontName": font_name,
                "family": family_name,
                "slug": slug,
                "category": category,
                "style": style,
                "weight": weight,
                "italic": is_italic,
                "originalSize": original_size,
                "compressedSize": len(woff2_bytes),
                "savings": round((1 - len(woff2_bytes) / original_size) * 100),
                "woff2": base64.b64encode(woff2_bytes).decode("ascii"),
                "url": font_url,
                "hash": font_hash,
            })

        except Exception:
            return send_json(self, 500, {"error": "Compression failed. The file may not be a valid font."})

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
