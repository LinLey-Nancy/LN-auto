"""Generate the LN-auto application icon with Pillow.

Design: a rounded-square purple gradient tile (matching the GUI theme) with a
white cursor arrow and an amber lightning bolt — pointer + automation energy.

Outputs:
  assets/resource/icon.ico  (multi-size, for PyInstaller and Inno Setup)
  assets/resource/icon.png  (256 px, for the runtime window icon)

Usage:  .venv/Scripts/python scripts/generate_icon.py
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "assets" / "resource"

# Draw at 4x and downscale so edges are anti-aliased.
CANVAS = 2048
FINAL = 512
RADIUS = 0.22  # corner radius, fraction of canvas

TOP_COLOR = (124, 58, 237)  # #7C3AED
BOTTOM_COLOR = (49, 46, 129)  # #312E81
CURSOR_COLOR = (248, 250, 252)  # #F8FAFC
CURSOR_SHADOW = (30, 27, 75, 110)  # #1E1B4B at partial alpha
BOLT_COLOR = (245, 158, 11)  # #F59E0B

# Normalized (0..1) polygon coordinates within the canvas.
CURSOR = [
    (0.295, 0.215),
    (0.295, 0.665),
    (0.420, 0.555),
    (0.500, 0.740),
    (0.575, 0.700),
    (0.500, 0.520),
    (0.645, 0.520),
]
BOLT = [
    (0.720, 0.440),
    (0.585, 0.680),
    (0.690, 0.680),
    (0.640, 0.840),
    (0.855, 0.570),
    (0.745, 0.570),
    (0.815, 0.440),
]


def gradient_tile(size: int) -> Image.Image:
    """Rounded-square vertical gradient tile with transparent corners."""
    gradient_mask = Image.linear_gradient("L").resize((size, size))
    top = Image.new("RGBA", (size, size), TOP_COLOR + (255,))
    bottom = Image.new("RGBA", (size, size), BOTTOM_COLOR + (255,))
    tile = Image.composite(bottom, top, gradient_mask)
    mask = Image.new("L", (size, size), 0)
    mask_draw = ImageDraw.Draw(mask)
    mask_draw.rounded_rectangle(
        (0, 0, size - 1, size - 1), radius=int(size * RADIUS), fill=255
    )
    tile.putalpha(mask)
    return tile


def scale_points(points: list[tuple[float, float]], size: int) -> list[tuple[int, int]]:
    return [(int(x * size), int(y * size)) for x, y in points]


def main() -> None:
    image = gradient_tile(CANVAS)
    draw = ImageDraw.Draw(image)

    # Cursor drop shadow, then the cursor itself.
    shadow = scale_points(
        [(x + 0.008, y + 0.012) for x, y in CURSOR], CANVAS
    )
    draw.polygon(shadow, fill=CURSOR_SHADOW)
    draw.polygon(scale_points(CURSOR, CANVAS), fill=CURSOR_COLOR)

    # Lightning bolt overlapping the cursor's lower right.
    bolt_shadow = scale_points(
        [(x + 0.006, y + 0.010) for x, y in BOLT], CANVAS
    )
    draw.polygon(bolt_shadow, fill=CURSOR_SHADOW)
    draw.polygon(scale_points(BOLT, CANVAS), fill=BOLT_COLOR)

    master = image.resize((FINAL, FINAL), Image.LANCZOS)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    png_path = OUTPUT_DIR / "icon.png"
    master.save(png_path)

    ico_path = OUTPUT_DIR / "icon.ico"
    master.save(
        ico_path,
        format="ICO",
        sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
    )
    print(f"Wrote {png_path}")
    print(f"Wrote {ico_path}")


if __name__ == "__main__":
    main()
