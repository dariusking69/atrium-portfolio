#!/usr/bin/env python3
"""
Generate static/ brand assets from Atrium's OFFICIAL logo files.

Run this only when the logo files themselves change. The output is committed, so
a normal build (and the GitHub Action) just copies static/ and never needs Pillow.

Why it works this way
---------------------
The brand spec is explicit: use the real logo files, never recreate the
letterforms, never software-invert the standard logo. So nothing here draws a
letter - it takes the official artwork and only ever resizes it or places it on
a solid backing. The one thing it does change is the wordmark's fill, and only
between the two sanctioned colourways (standard black / reversed white).

Sources (outside this repo, under Downloads/Work):
    Claude/atrium_owner_portal/static/atrium-wordmark.svg  - vector ATRIUM wordmark
    Marketing/logos/White/A logo White.png                 - reversed A lettermark

    usage:  python3 tools/make_assets.py
"""
from pathlib import Path

from PIL import Image, ImageDraw

HERE = Path(__file__).resolve().parent.parent
SRC = Path.home() / "Downloads/Work"
OUT = HERE / "static"

WORDMARK = SRC / "Claude/atrium_owner_portal/static/atrium-wordmark.svg"
A_MARK_WHITE = SRC / "Marketing/logos/White/A logo White.png"

ATRIUM_BLACK = "#121212"


def wordmarks():
    """Standard (black, for light backgrounds) + reversed (white, for dark)."""
    svg = WORDMARK.read_text()
    if "fill:#fff" not in svg:
        raise SystemExit(f"unexpected wordmark source - no white fill found in {WORDMARK}")
    (OUT / "atrium-wordmark.svg").write_text(svg.replace("fill:#fff", f"fill:{ATRIUM_BLACK}"))
    (OUT / "atrium-wordmark-neg.svg").write_text(svg)
    print("  atrium-wordmark.svg      (standard, for light backgrounds)")
    print("  atrium-wordmark-neg.svg  (reversed, for dark backgrounds)")


def tile(mark, size, radius_ratio=0.16, mark_ratio=0.60):
    """The A lettermark, reversed, centred on an Atrium Black rounded tile."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    ImageDraw.Draw(img).rounded_rectangle(
        [0, 0, size - 1, size - 1], radius=int(size * radius_ratio), fill=(18, 18, 18, 255))
    target = int(size * mark_ratio)
    w, h = mark.size
    scale = min(target / w, target / h)          # never distort - uniform scale only
    small = mark.resize((max(1, int(w * scale)), max(1, int(h * scale))), Image.LANCZOS)
    img.alpha_composite(small, ((size - small.width) // 2, (size - small.height) // 2))
    return img


def icons():
    mark = Image.open(A_MARK_WHITE).convert("RGBA")
    tile(mark, 64).save(OUT / "favicon.png")
    tile(mark, 180, radius_ratio=0.22).save(OUT / "apple-touch-icon.png")
    print("  favicon.png              (64px, browser tab)")
    print("  apple-touch-icon.png     (180px, iOS home screen)")


if __name__ == "__main__":
    for p in (WORDMARK, A_MARK_WHITE):
        if not p.exists():
            raise SystemExit(f"missing source logo file: {p}")
    OUT.mkdir(parents=True, exist_ok=True)
    print(f"writing to {OUT}/")
    wordmarks()
    icons()
    print("done - commit static/ so the build and the Action need no image tooling")
