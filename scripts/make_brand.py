"""Generate the brand images from LuxPower's logo.

LuxPower only publishes the logo as a 1030x186 raster, so this traces each of
its three colours to vector paths and renders those at the sizes Home
Assistant serves from custom_components/luxpower_local/brand/:

- icon: the green X roundel alone, since the wordmark is unreadable at icon size
- logo: the full logo with dark grey lettering, for light themes
- dark_logo: the same with white lettering, as LuxPower uses on dark backgrounds

    uv run --with potracer --with cairosvg --with pillow --with numpy python scripts/make_brand.py
"""

from pathlib import Path

import cairosvg
import numpy as np
import potrace
from PIL import Image, ImageFilter

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "assets" / "luxpower-logo.webp"
BRAND = ROOT / "custom_components" / "luxpower_local" / "brand"
# Sampled from the logo
GREEN = "#64AD83"
GREY = "#485052"
WHITE = "#FFFFFF"
SCALE = 4  # trace an upscaled copy for smoother curves
# Columns of the source holding the roundel; the "LU" ends and "POWER" starts outside them
ROUNDEL_COLUMNS = (175, 362)


def _field(channel: Image.Image, blur: float = 0.6) -> np.ndarray:
    """Upscale a 0-255 channel smoothly and cut it at half way, for clean outlines."""
    big = channel.resize((channel.width * SCALE, channel.height * SCALE), Image.LANCZOS)
    big = big.filter(ImageFilter.GaussianBlur(SCALE * blur))
    return np.asarray(big) > 127


def _disc(shape: np.ndarray, in_roundel: np.ndarray) -> np.ndarray:
    """An exact circle in place of the roundel.

    The published raster clips the circle by a couple of pixels left and right,
    so it is fitted to the roundel's height and centre instead.
    """
    ys, xs = np.nonzero(shape & in_roundel)
    cy, cx = (ys.min() + ys.max()) / 2, (xs.min() + xs.max()) / 2
    radius = (ys.max() - ys.min() + 1) / 2
    yy, xx = np.ogrid[: shape.shape[0], : shape.shape[1]]
    return (yy - cy) ** 2 + (xx - cx) ** 2 <= radius**2


def masks(image: Image.Image) -> dict[str, np.ndarray]:
    """The roundel's disc and X, and the lettering, as upscaled masks."""
    rgba = image.convert("RGBA")
    red, _, _, alpha = rgba.split()
    # The X is white on green: the red channel tells them apart best (240 vs 100)
    cross = Image.fromarray(
        np.clip((np.asarray(red, dtype=int) - 100) * 255 // 140, 0, 255).astype(np.uint8)
    )
    shape = _field(alpha)
    left, right = (c * SCALE for c in ROUNDEL_COLUMNS)
    in_roundel = np.zeros_like(shape)
    in_roundel[:, left:right] = True
    return {
        "disc": _disc(shape, in_roundel),
        "cross": _field(cross, blur=0.9) & shape & in_roundel,
        "lettering": shape & ~in_roundel,
    }


def trace(mask: np.ndarray) -> str:
    """Trace a mask to an SVG path."""
    # potracer traces the False pixels, so hand it the inverse
    path = potrace.Bitmap(~mask).trace(turdsize=50, alphamax=1.0, opticurve=True)
    parts = []
    for curve in path:
        start = curve.start_point
        parts.append(f"M{start.x:.2f},{start.y:.2f}")
        for seg in curve.segments:
            if seg.is_corner:
                parts.append(
                    f"L{seg.c.x:.2f},{seg.c.y:.2f}L{seg.end_point.x:.2f},{seg.end_point.y:.2f}"
                )
            else:
                parts.append(
                    f"C{seg.c1.x:.2f},{seg.c1.y:.2f} {seg.c2.x:.2f},{seg.c2.y:.2f} "
                    f"{seg.end_point.x:.2f},{seg.end_point.y:.2f}"
                )
        parts.append("Z")
    return "".join(parts)


def bbox(*layers: np.ndarray) -> tuple[int, int, int, int]:
    ys, xs = np.nonzero(np.logical_or.reduce(layers))
    return xs.min(), ys.min(), xs.max() + 1, ys.max() + 1


def svg(
    layers: list[tuple[str, str]],
    box: tuple[int, int, int, int],
    width: int,
    height: int,
    margin: float,
) -> str:
    """Fit the traced layers, centred, into width x height with a margin."""
    x0, y0, x1, y1 = box
    scale = min(width * (1 - 2 * margin) / (x1 - x0), height * (1 - 2 * margin) / (y1 - y0))
    dx = (width - (x1 - x0) * scale) / 2 - x0 * scale
    dy = (height - (y1 - y0) * scale) / 2 - y0 * scale
    paths = "".join(f'<path fill="{colour}" fill-rule="evenodd" d="{d}"/>' for colour, d in layers)
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}"><g transform="translate({dx:.2f},{dy:.2f}) '
        f'scale({scale:.5f})">{paths}</g></svg>'
    )


def render(name: str, markup: str) -> None:
    cairosvg.svg2png(bytestring=markup.encode(), write_to=str(BRAND / name))
    print(name, Image.open(BRAND / name).size)


def main() -> None:
    BRAND.mkdir(exist_ok=True)
    parts = masks(Image.open(SOURCE))

    # The roundel: green disc with the white X on top
    roundel = [(GREEN, trace(parts["disc"])), (WHITE, trace(parts["cross"]))]
    box = bbox(parts["disc"])
    (ROOT / "assets" / "icon.svg").write_text(svg(roundel, box, 512, 512, 0.04))
    for name, size in (("icon.png", 256), ("icon@2x.png", 512)):
        render(name, svg(roundel, box, size, size, 0.04))

    lettering = trace(parts["lettering"])
    box = bbox(parts["disc"], parts["lettering"])
    ratio = (box[2] - box[0]) / (box[3] - box[1])
    for prefix, colour in (("", GREY), ("dark_", WHITE)):
        layers = [*roundel, (colour, lettering)]
        (ROOT / "assets" / f"{prefix}logo.svg").write_text(
            svg(layers, box, round(256 * ratio), 256, 0)
        )
        for name, height in ((f"{prefix}logo.png", 128), (f"{prefix}logo@2x.png", 256)):
            render(name, svg(layers, box, round(height * ratio), height, 0))


if __name__ == "__main__":
    main()
