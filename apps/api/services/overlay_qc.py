"""Overlay quality-control helpers.

detect_checkerboard_background — fast local pixel analysis to catch
"transparency preview grid" backgrounds baked into generated overlay PNGs.
"""

import logging

import numpy as np
from PIL import Image

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Checkerboard detection
# ---------------------------------------------------------------------------

_THUMB_SIZE = 128
_TILE_SIZES = (4, 8, 16)
# Minimum fraction of the image area covered by the alternating pattern
_PATTERN_THRESHOLD = 0.35
# Maximum color distance between two "constant" tile colors
_COLOR_TOLERANCE = 30
# Both dominant colors must be in the grayscale band
_GRAY_MAX_DEVIATION = 25  # max abs(r-g), abs(r-b), abs(g-b)


def detect_checkerboard_background(img_path: str) -> bool:
    """Return True if *img_path* has a baked checkerboard alpha-grid background.

    The heuristic downsamples to 128x128, then checks for periodic
    alternation of two near-constant grayscale colors at 8x8 or 16x16
    tile boundaries.  Designed to be fast and catch obvious
    transparency-preview grids without false-positiving on real content.
    """
    try:
        img = Image.open(img_path).convert("RGB")
        img = img.resize((_THUMB_SIZE, _THUMB_SIZE), Image.NEAREST)
        pixels = np.array(img, dtype=np.int16)  # (128, 128, 3)
    except Exception:
        return False

    for tile in _TILE_SIZES:
        if _check_tile_pattern(pixels, tile):
            return True
    return False


def _is_grayscale(color: np.ndarray) -> bool:
    """Check if an RGB color is approximately grayscale."""
    r, g, b = int(color[0]), int(color[1]), int(color[2])
    return (abs(r - g) <= _GRAY_MAX_DEVIATION
            and abs(r - b) <= _GRAY_MAX_DEVIATION
            and abs(g - b) <= _GRAY_MAX_DEVIATION)


def _check_tile_pattern(pixels: np.ndarray, tile: int) -> bool:
    """Check if pixels exhibit a checkerboard pattern at the given tile size."""
    h, w = pixels.shape[:2]
    tiles_y = h // tile
    tiles_x = w // tile
    if tiles_y < 4 or tiles_x < 4:
        return False

    # Compute average color per tile
    tile_colors = np.zeros((tiles_y, tiles_x, 3), dtype=np.float64)
    for ty in range(tiles_y):
        for tx in range(tiles_x):
            block = pixels[ty * tile:(ty + 1) * tile, tx * tile:(tx + 1) * tile]
            tile_colors[ty, tx] = block.mean(axis=(0, 1))

    # Collect colors from even (ty+tx even) and odd (ty+tx odd) positions
    even_colors = []
    odd_colors = []
    for ty in range(tiles_y):
        for tx in range(tiles_x):
            if (ty + tx) % 2 == 0:
                even_colors.append(tile_colors[ty, tx])
            else:
                odd_colors.append(tile_colors[ty, tx])

    if not even_colors or not odd_colors:
        return False

    even_mean = np.mean(even_colors, axis=0)
    odd_mean = np.mean(odd_colors, axis=0)

    # Both dominant colors must be roughly grayscale
    if not (_is_grayscale(even_mean) and _is_grayscale(odd_mean)):
        return False

    # The two colors must be distinct
    color_dist = np.linalg.norm(even_mean - odd_mean)
    if color_dist < 15:
        return False

    # Check that individual tiles are consistent with their group mean
    alternating_count = 0
    total = 0
    for ty in range(tiles_y):
        for tx in range(tiles_x):
            c = tile_colors[ty, tx]
            expected = even_mean if (ty + tx) % 2 == 0 else odd_mean
            if np.linalg.norm(c - expected) < _COLOR_TOLERANCE:
                alternating_count += 1
            total += 1

    ratio = alternating_count / total if total > 0 else 0
    return ratio >= _PATTERN_THRESHOLD
