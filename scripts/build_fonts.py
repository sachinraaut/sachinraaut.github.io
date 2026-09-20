#!/usr/bin/env python
"""Subset the Noto Sans Devanagari TTFs in assets/fonts/ into small WOFF2 files in static/fonts/.

Run once (or after changing the ranges) and commit the result:

    .venv/bin/python scripts/build_fonts.py

Self-hosting removes a render-blocking third-party stylesheet and two extra connections on every page load,
and keeps the site from telling Google what our readers are reading.
"""
from __future__ import annotations

import sys
from pathlib import Path

from fontTools import subset

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "assets" / "fonts"
OUT = ROOT / "static" / "fonts"
FACES = {400: "NotoSansDevanagari-Regular.ttf", 700: "NotoSansDevanagari-Bold.ttf"}
# Devanagari + its extended block, Latin (the posts mix in UPI, SIP, AI...), punctuation, digits, rupee.
UNICODES = "U+0020-007E,U+00A0-00FF,U+0900-097F,U+A8E0-A8FF,U+200C-200D,U+2010-2027,U+20B9,U+2212,U+FEFF"


def build() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    total = 0
    for weight, name in FACES.items():
        src = SRC / name
        if not src.exists():
            print(f"missing {src}", file=sys.stderr)
            return 1
        dst = OUT / f"noto-sans-devanagari-{weight}.woff2"
        args = [str(src), f"--unicodes={UNICODES}", "--layout-features=*", "--flavor=woff2",
                f"--output-file={dst}", "--desubroutinize", "--no-hinting"]
        subset.main(args)
        kb = dst.stat().st_size / 1024
        total += dst.stat().st_size
        print(f"{dst.relative_to(ROOT)}  {kb:.0f} KB  (from {src.stat().st_size / 1024:.0f} KB)")
    print(f"total {total / 1024:.0f} KB")
    return 0


if __name__ == "__main__":
    raise SystemExit(build())
