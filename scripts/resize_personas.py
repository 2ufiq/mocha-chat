"""
Resize + recompress persona card images so they ship at display size.

Cards render at ~300×375 CSS px (4:5 aspect). Retina/2x devices want
600×750 max. Anything above that is wasted bandwidth + extra CPU work
decoding on the user's phone.

Usage:
    uvx --with pillow python scripts/resize_personas.py

(uvx pulls Pillow into a one-off venv — we keep it OUT of the project
deps because this is maintenance-only.)

Behavior:
- Reads each *.webp in static/persona/
- If larger than 700px in either dimension, downscales to fit 600×750
  with Lanczos, re-encodes as webp at quality 82.
- Writes BACK over the original (so the URL doesn't change). Skips files
  that are already small enough.
"""

import sys
from pathlib import Path

try:
    from PIL import Image
except ImportError:
    print("Pillow not found. Run with: uvx --with pillow python scripts/resize_personas.py")
    sys.exit(1)

PERSONA_DIR = Path(__file__).resolve().parent.parent / "static" / "persona"
MAX_W, MAX_H = 600, 750     # 2x retina at 300×375 CSS card
QUALITY = 82                # webp lossy quality; 80-85 is sweet spot
SKIP_THRESHOLD = 800        # if shortest side already < this, skip


def resize_one(path: Path) -> None:
    img = Image.open(path)
    w, h = img.size
    if max(w, h) <= SKIP_THRESHOLD:
        print(f"  skip   {path.name:20s} ({w}×{h}, already small)")
        return
    # Compute target preserving aspect ratio.
    img.thumbnail((MAX_W, MAX_H), Image.LANCZOS)
    new_w, new_h = img.size
    before = path.stat().st_size
    img.save(path, "webp", quality=QUALITY, method=6)
    after = path.stat().st_size
    print(
        f"  resize {path.name:20s} {w}×{h} → {new_w}×{new_h}  "
        f"{before//1024}KB → {after//1024}KB"
    )


def main():
    files = sorted(PERSONA_DIR.glob("*.webp"))
    if not files:
        print(f"no webp files in {PERSONA_DIR}")
        return
    print(f"processing {len(files)} files in {PERSONA_DIR}\n")
    total_before = sum(f.stat().st_size for f in files)
    for f in files:
        resize_one(f)
    total_after = sum(f.stat().st_size for f in PERSONA_DIR.glob("*.webp"))
    print(
        f"\ntotal: {total_before//1024}KB → {total_after//1024}KB "
        f"({(1 - total_after/total_before)*100:.0f}% smaller)"
    )


if __name__ == "__main__":
    main()
