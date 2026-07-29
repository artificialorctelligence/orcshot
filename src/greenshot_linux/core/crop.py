"""Crop: canvas-level transforms, not drawn annotations.

Behavioral port of CropContainer's four modes, as pure functions rather
than a Layer-participating shape — see the module docstring in
test_crop.py for why, and for the real behavioral distinction between
"crop to" (Default/AutoCrop) and "crop out" (Vertical/Horizontal).
AutoCrop isn't ported as a separate function: it differs from Default
only in how the editor tool initializes its starting selection rect,
not in the transform itself, so crop_to_rect covers both.

The strip-clamping in both "crop out" functions has one non-obvious
step: after clamping to the image bounds, the end coordinate is pinned
to be >= the start coordinate. A property test caught the case this
guards — an inverted/degenerate band (e.g. from a drag that moved the
selection past its own start) produced *more* rows than the input
image instead of removing nothing, because concatenating image[:top]
with image[bottom:] duplicates content when bottom < top rather than
producing an empty removal.
"""

from __future__ import annotations

import numpy as np

from greenshot_linux.core.geometry import Rect


def _image_bounds(image: np.ndarray) -> Rect:
    return Rect(left=0, top=0, right=image.shape[1], bottom=image.shape[0])


def crop_to_rect(image: np.ndarray, rect: Rect) -> np.ndarray:
    """CropModes.Default / AutoCrop: keep only the pixels inside ``rect``."""
    apply_rect = rect.intersect(_image_bounds(image))
    if apply_rect is None:
        return image[0:0, 0:0].copy()
    return image[apply_rect.top:apply_rect.bottom, apply_rect.left:apply_rect.right].copy()


def crop_out_vertical_strip(image: np.ndarray, rect: Rect) -> np.ndarray:
    """CropModes.Vertical: remove the full-height column band
    [rect.left, rect.right), keeping everything else, spliced back
    together. Only rect's horizontal extent is meaningful — the source
    forces this mode's selection to Top=0/Height=image.Height.
    """
    width = image.shape[1]
    left = max(0, min(rect.left, width))
    right = max(0, min(rect.right, width))
    right = max(right, left)  # an inverted/degenerate band removes nothing
    return np.concatenate([image[:, :left], image[:, right:]], axis=1)


def crop_out_horizontal_strip(image: np.ndarray, rect: Rect) -> np.ndarray:
    """CropModes.Horizontal: remove the full-width row band
    [rect.top, rect.bottom), keeping everything else, spliced back
    together. Only rect's vertical extent is meaningful — the source
    forces this mode's selection to Left=0/Width=image.Width.
    """
    height = image.shape[0]
    top = max(0, min(rect.top, height))
    bottom = max(0, min(rect.bottom, height))
    bottom = max(bottom, top)  # an inverted/degenerate band removes nothing
    return np.concatenate([image[:top, :], image[bottom:, :]], axis=0)


def _corner_colors(image: np.ndarray):
    h, w = image.shape[:2]
    return [tuple(image[0, 0]), tuple(image[0, w - 1]), tuple(image[h - 1, 0]), tuple(image[h - 1, w - 1])]


def _row_or_col_matches(pixels: np.ndarray, color, difference: int) -> bool:
    if difference == 0:
        return bool(np.all(pixels == np.array(color, dtype=pixels.dtype)))
    diff = np.abs(pixels[:, :3].astype(np.int32) - np.array(color[:3], dtype=np.int32))
    return bool(np.all(diff.sum(axis=1) / 3 <= difference))


def _trim_rect_for_color(image: np.ndarray, color, difference: int) -> Rect:
    h, w = image.shape[:2]
    top, bottom, left, right = 0, h, 0, w
    while top < bottom and _row_or_col_matches(image[top, left:right], color, difference):
        top += 1
    while bottom > top and _row_or_col_matches(image[bottom - 1, left:right], color, difference):
        bottom -= 1
    while left < right and _row_or_col_matches(image[top:bottom, left], color, difference):
        left += 1
    while right > left and _row_or_col_matches(image[top:bottom, right - 1], color, difference):
        right -= 1
    return Rect(left, top, right, bottom)


def autocrop_rect(image: np.ndarray, difference: int = 10) -> Rect | None:
    """Where "Shrink canvas" (Ctrl+Shift+-, instant) and crop mode
    AutoCrop's pre-filled selection would trim to - a good-faith,
    deliberately simplified reproduction of
    ImageHelper.FindAutoCropRectangle/FindAutoCropNativeRect
    (ImageHelper.cs:203-301): samples the 4 corner colors and uses the
    most common one (ties broken by which corner was sampled first -
    top-left, top-right, bottom-left, bottom-right) as the single
    background-color hypothesis, then trims every edge
    (top/bottom/left/right, in that order) while it stays within
    ``difference`` of that color (Windows:
    ``(|dR|+|dG|+|dB|)/3 <= difference``, or an exact match if
    ``difference == 0``). None if nothing should be trimmed.

    Windows' own description ("for each corner, grow a region, keep
    the largest") implies evaluating all 4 corners independently and
    picking a winner, which this deliberately doesn't do: since every
    edge scan spans the image's full width or height, a single
    differently-colored corner (the exact scenario multi-corner
    sampling is meant to handle) still poisons its own row *and*
    column scan for every hypothesis tried, and poisons perpendicular
    edges too once one edge fails to trim past it - degenerating to
    unhelpful or inconsistent results in exactly the case it's
    supposed to make more robust. A true flood-fill/region-growing
    implementation might not have this problem, but the exact
    algorithm isn't available to verify against, only Windows'
    high-level description - so this uses one well-defined hypothesis
    (majority corner color) instead of an under-specified 4-way
    scheme that doesn't reliably deliver on its own intent.

    ``difference`` defaults to 10, matching Windows'
    ``AutoCropDifference`` config default (ICoreConfiguration.cs:218-221).
    Apply the result with crop_to_rect.
    """
    h, w = image.shape[:2]
    colors = _corner_colors(image)
    counts = {color: colors.count(color) for color in colors}
    background = max(colors, key=lambda c: counts[c])  # max() keeps the first-seen winner on ties
    rect = _trim_rect_for_color(image, background, difference)
    if rect.width <= 0 or rect.height <= 0:
        return None
    if rect.width == w and rect.height == h:
        return None
    return rect
