"""Builds the exe icon and the in-app logo from the source PNG."""
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).parent
SOURCE = ROOT / "logoQ-przezroczyste.png"
ICON_SIZES = (256, 128, 64, 48, 32, 24, 16)


def square(image):
    side = max(image.size)
    canvas = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    canvas.paste(image, ((side - image.width) // 2, (side - image.height) // 2))
    return canvas


def resized(image, size):
    # Premultiplied alpha: the source keeps a checkerboard in the RGB of fully transparent
    # pixels, and a plain resize would bleed it into the edges as a grey halo.
    return image.convert("RGBa").resize((size, size), Image.LANCZOS).convert("RGBA")


def main():
    logo = square(Image.open(SOURCE).convert("RGBA"))
    (ROOT / "assets").mkdir(exist_ok=True)
    resized(logo, 192).save(ROOT / "ui" / "logo.png", optimize=True)
    frames = [resized(logo, size) for size in ICON_SIZES]
    frames[0].save(ROOT / "assets" / "icon.ico", format="ICO", append_images=frames[1:],
                   sizes=[(s, s) for s in ICON_SIZES])


if __name__ == "__main__":
    main()
