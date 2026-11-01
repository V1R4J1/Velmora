"""Regenerate responsive assets using Pillow, a development-only dependency."""
from pathlib import Path
import sys

from PIL import Image, ImageOps


ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "static"
WIDTHS = (320, 640, 960)


def main():
    sources = [STATIC / path for path in sys.argv[1:]] if len(sys.argv) > 1 else list((STATIC / "productImages").glob("*/*"))
    if len(sys.argv) == 1:
        sources.extend((STATIC / "campaign").glob("*.jpg"))
    for source in sources:
        with Image.open(source) as original:
            for width in WIDTHS:
                destination = STATIC / "responsive" / source.relative_to(STATIC)
                destination = Path(f"{destination}.{width}.webp")
                destination.parent.mkdir(parents=True, exist_ok=True)
                image = ImageOps.exif_transpose(original)
                image.thumbnail((width, 10000), Image.Resampling.LANCZOS)
                image.save(
                    destination, "WEBP", quality=88, method=6,
                    icc_profile=original.info.get("icc_profile", b""),
                )


if __name__ == "__main__":
    main()
