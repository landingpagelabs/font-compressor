#!/usr/bin/env python3
"""
Build script: converts canvas-fonts TTFs to WOFF2 and generates data.json metadata.
Usage: python3.14 scripts/build-library.py
"""

import json
import os
import re
import sys
from io import BytesIO
from pathlib import Path

from fontTools.ttLib import TTFont
from fontTools.subset import Subsetter, Options

# Paths
SCRIPT_DIR = Path(__file__).parent
PROJECT_DIR = SCRIPT_DIR.parent
SOURCE_DIR = PROJECT_DIR.parent / "skills" / "design" / "references" / "canvas-design" / "canvas-fonts"
OUTPUT_DIR = PROJECT_DIR / "fonts"

# Manual category overrides (fonts that can't be auto-detected reliably)
CATEGORY_OVERRIDES = {
    "ArsenalSC": "sans-serif",
    "BigShoulders": "display",
    "Boldonse": "display",
    "BricolageGrotesque": "sans-serif",
    "CrimsonPro": "serif",
    "DMMono": "monospace",
    "EricaOne": "display",
    "GeistMono": "monospace",
    "Gloock": "serif",
    "IBMPlexMono": "monospace",
    "IBMPlexSerif": "serif",
    "InstrumentSans": "sans-serif",
    "InstrumentSerif": "serif",
    "Italiana": "serif",
    "JetBrainsMono": "monospace",
    "Jura": "sans-serif",
    "LibreBaskerville": "serif",
    "Lora": "serif",
    "NationalPark": "display",
    "NothingYouCouldDo": "handwriting",
    "Outfit": "sans-serif",
    "PixelifySans": "display",
    "PoiretOne": "display",
    "RedHatMono": "monospace",
    "Silkscreen": "display",
    "SmoochSans": "sans-serif",
    "Tektur": "sans-serif",
    "WorkSans": "sans-serif",
    "YoungSerif": "serif",
}

# Weight mapping from style names
WEIGHT_MAP = {
    "Thin": 100,
    "ExtraLight": 200,
    "UltraLight": 200,
    "Light": 300,
    "Regular": 400,
    "Medium": 500,
    "SemiBold": 600,
    "DemiBold": 600,
    "Bold": 700,
    "ExtraBold": 800,
    "UltraBold": 800,
    "Black": 900,
    "Heavy": 900,
}


def parse_filename(filename):
    """Parse 'FamilyName-Style.ttf' into family and style parts."""
    stem = Path(filename).stem
    parts = stem.rsplit("-", 1)
    if len(parts) == 2:
        family, style = parts
    else:
        family = parts[0]
        style = "Regular"
    return family, style


def get_weight(style):
    """Extract numeric weight from style name."""
    # Check for combined styles like BoldItalic
    clean = style.replace("Italic", "").strip()
    if not clean:
        clean = "Regular"
    return WEIGHT_MAP.get(clean, 400)


def is_italic(style):
    """Check if style includes italic."""
    return "Italic" in style or "italic" in style


def human_family_name(family):
    """Convert CamelCase family name to human-readable: IBMPlexSerif -> IBM Plex Serif."""
    # Insert space before uppercase letters that follow lowercase
    spaced = re.sub(r"([a-z])([A-Z])", r"\1 \2", family)
    # Insert space between consecutive uppercase and following mixed: IBM -> IBM
    spaced = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", spaced)
    return spaced


def compress_font(ttf_path, woff2_path):
    """Load a TTF, subset to Basic Latin, and save as WOFF2. Returns (original_size, compressed_size)."""
    original_size = ttf_path.stat().st_size

    font = TTFont(str(ttf_path))

    # Subset to Basic Latin (U+0020-007E) — matches what Transfonter does by default
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

    woff2_path.write_bytes(woff2_bytes)
    compressed_size = len(woff2_bytes)

    font.close()
    return original_size, compressed_size


def build():
    """Main build: compress all TTFs and generate data.json."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    ttf_files = sorted(SOURCE_DIR.glob("*.ttf"))
    if not ttf_files:
        print(f"No TTF files found in {SOURCE_DIR}")
        sys.exit(1)

    print(f"Found {len(ttf_files)} TTF files in {SOURCE_DIR}")

    # Group fonts by family
    families = {}

    for ttf_path in ttf_files:
        family, style = parse_filename(ttf_path.name)
        woff2_name = ttf_path.stem + ".woff2"
        woff2_path = OUTPUT_DIR / woff2_name

        print(f"  Compressing {ttf_path.name}...", end=" ", flush=True)
        original_size, compressed_size = compress_font(ttf_path, woff2_path)
        savings = round((1 - compressed_size / original_size) * 100)
        print(f"{original_size:,} -> {compressed_size:,} bytes ({savings}% smaller)")

        if family not in families:
            families[family] = {
                "family": human_family_name(family),
                "slug": family.lower(),
                "category": CATEGORY_OVERRIDES.get(family, "sans-serif"),
                "variants": [],
            }

        families[family]["variants"].append({
            "style": style,
            "weight": get_weight(style),
            "italic": is_italic(style),
            "file": woff2_name,
            "sizeOriginal": original_size,
            "sizeWoff2": compressed_size,
        })

    # Sort variants by weight then italic
    for fam in families.values():
        fam["variants"].sort(key=lambda v: (v["weight"], v["italic"]))

    # Build final data array sorted alphabetically
    data = sorted(families.values(), key=lambda f: f["family"].lower())

    # Write data.json
    data_path = OUTPUT_DIR / "data.json"
    with open(data_path, "w") as f:
        json.dump(data, f, indent=2)

    total_original = sum(v["sizeOriginal"] for fam in data for v in fam["variants"])
    total_compressed = sum(v["sizeWoff2"] for fam in data for v in fam["variants"])
    total_savings = round((1 - total_compressed / total_original) * 100)

    print(f"\nDone! {len(data)} font families, {len(ttf_files)} variants")
    print(f"Total: {total_original:,} -> {total_compressed:,} bytes ({total_savings}% smaller)")
    print(f"Output: {OUTPUT_DIR}")


if __name__ == "__main__":
    build()
