"""One-off: generate assets/app_icon.png + .ico (FIX-12a).

Forest rounded square (palette #0c3b2e) with a cream (#f7f5ef) "FV"
monogram; .ico carries 16/32/48/256. Regenerate with:

    python tools/make_icon.py
"""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

FOREST = "#0c3b2e"
CREAM = "#f7f5ef"
AMBER = "#ffba00"
ASSETS = Path(__file__).resolve().parent.parent / "assets"


def _font(px: int) -> ImageFont.FreeTypeFont:
    """A bold face from the palette FONT_STACK, wherever one lives."""
    candidates = [
        "C:/Windows/Fonts/segoeuib.ttf",                      # Segoe UI Bold
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ]
    try:  # matplotlib always ships DejaVu — the palette's second choice
        import matplotlib
        candidates.append(str(Path(matplotlib.get_data_path())
                              / "fonts" / "ttf" / "DejaVuSans-Bold.ttf"))
    except Exception:
        pass
    for c in candidates:
        try:
            return ImageFont.truetype(c, px)
        except Exception:
            continue
    return ImageFont.load_default()


def draw(size: int) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    r = max(2, size // 6)
    d.rounded_rectangle([0, 0, size - 1, size - 1], radius=r, fill=FOREST)
    if size >= 32:  # amber base accent, the brand mockup's rule
        d.rectangle([r // 2, size - max(2, size // 16), size - r // 2,
                     size - 1], fill=AMBER)
    font = _font(int(size * 0.52))
    bbox = d.textbbox((0, 0), "FV", font=font)
    w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
    d.text(((size - w) / 2 - bbox[0], (size - h) / 2 - bbox[1] - size * 0.03),
           "FV", font=font, fill=CREAM)
    return img


def main() -> None:
    ASSETS.mkdir(exist_ok=True)
    png = draw(256)
    png.save(ASSETS / "app_icon.png")
    png.save(ASSETS / "app_icon.ico",
             sizes=[(16, 16), (32, 32), (48, 48), (256, 256)])
    print(f"wrote {ASSETS / 'app_icon.png'} and .ico")


if __name__ == "__main__":
    main()
