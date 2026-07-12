"""One-off local generator for Shantry Bills' PWA icon set.

Not a runtime dependency -- Pillow isn't in requirements.txt on purpose.
Run once (`pip install Pillow && python3 scripts/gen_icons.py`), commit the
output. Re-run and re-commit only if the design changes.

Font path is Windows-specific (developed/run on Windows) -- update
FONT_PATH if running elsewhere.
"""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

BG = "#101214"
ACCENT = "#4caf7d"
GLYPH = "$"
FONT_PATH = r"C:\Windows\Fonts\arialbd.ttf"
OUT_DIR = Path(__file__).resolve().parent.parent / "static" / "icons"


def render_icon(size: int, padding_frac: float = 0.0) -> Image.Image:
    """Render GLYPH centered on a BG square, ACCENT-colored, sized to fill
    (size - 2*padding) px. padding_frac is a fraction of `size` reserved on
    each edge (used for the maskable variant's safe zone)."""
    img = Image.new("RGB", (size, size), BG)
    draw = ImageDraw.Draw(img)

    padding = int(size * padding_frac)
    target = size - 2 * padding

    # Binary-search a font size whose glyph bbox fits within `target`.
    lo, hi = 1, size
    best_font = ImageFont.truetype(FONT_PATH, 1)
    while lo <= hi:
        mid = (lo + hi) // 2
        font = ImageFont.truetype(FONT_PATH, mid)
        bbox = draw.textbbox((0, 0), GLYPH, font=font)
        w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
        if w <= target and h <= target:
            best_font = font
            lo = mid + 1
        else:
            hi = mid - 1

    bbox = draw.textbbox((0, 0), GLYPH, font=best_font)
    w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
    x = (size - w) / 2 - bbox[0]
    y = (size - h) / 2 - bbox[1]
    draw.text((x, y), GLYPH, font=best_font, fill=ACCENT)
    return img


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    render_icon(180).save(OUT_DIR / "apple-touch-icon.png")
    render_icon(192).save(OUT_DIR / "icon-192.png")
    render_icon(512).save(OUT_DIR / "icon-512.png")
    # ~10% padding per edge = glyph stays inside the ~80%-diameter safe
    # zone adaptive-icon masks require.
    render_icon(512, padding_frac=0.10).save(OUT_DIR / "icon-512-maskable.png")

    favicon_sizes = [16, 32, 48]
    favicon_imgs = [render_icon(s) for s in favicon_sizes]
    favicon_imgs[0].save(
        OUT_DIR / "favicon.ico",
        format="ICO",
        sizes=[(s, s) for s in favicon_sizes],
        append_images=favicon_imgs[1:],
    )

    print(f"Wrote icons to {OUT_DIR}")


if __name__ == "__main__":
    main()
