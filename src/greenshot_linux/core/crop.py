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
