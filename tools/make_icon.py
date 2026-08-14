"""Generate the app icon (assets/ti2026.ico) used by the desktop shortcut."""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "assets" / "ti2026.ico"

BG_DARK = (13, 18, 27)
BG_EDGE = (24, 32, 47)
GOLD = (200, 164, 78)
GOLD_SOFT = (227, 194, 115)
INK = (22, 17, 10)


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for name in ("segoeuib.ttf", "arialbd.ttf", "seguisb.ttf", "DejaVuSans-Bold.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def render(size: int) -> Image.Image:
    # supersample, then downscale, so the edges stay smooth at 16x16
    scale = 4
    s = size * scale
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    radius = int(s * 0.22)
    d.rounded_rectangle([0, 0, s - 1, s - 1], radius=radius, fill=BG_DARK, outline=BG_EDGE,
                        width=max(1, int(s * 0.02)))

    # gold aegis-ish shield
    m = s * 0.20
    shield = [
        (s / 2, m * 0.85),
        (s - m, m * 1.9),
        (s - m, s * 0.56),
        (s / 2, s - m * 0.75),
        (m, s * 0.56),
        (m, m * 1.9),
    ]
    d.polygon(shield, fill=GOLD)
    inner = [(x + (s / 2 - x) * 0.17, y + (s * 0.52 - y) * 0.17) for x, y in shield]
    d.polygon(inner, fill=GOLD_SOFT)

    label = "TI"
    f = _font(int(s * 0.34))
    box = d.textbbox((0, 0), label, font=f)
    d.text(((s - (box[2] - box[0])) / 2 - box[0], s * 0.40 - box[1] - (box[3] - box[1]) / 2),
           label, font=f, fill=INK)

    return img.resize((size, size), Image.LANCZOS)


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    sizes = [16, 24, 32, 48, 64, 128, 256]
    frames = [render(n) for n in sizes]
    frames[-1].save(OUT, format="ICO", sizes=[(n, n) for n in sizes])
    print(f"wrote {OUT} ({OUT.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
