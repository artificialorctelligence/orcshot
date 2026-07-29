"""Whole-image effects: operations on the entire captured image, as
opposed to individual drawn annotation shapes (core/tools.py). Ported
from Greenshot.Base/Effects/*.cs and Greenshot.Base/Core/ImageHelper.cs
- see each function's docstring for its specific citation.

Pure numpy - everything here works on plain (H, W, 4) uint8 RGBA
arrays with no GTK/Cairo dependency, so it's unit-testable headless
like the rest of core/. Resize (needs GdkPixbuf for quality resampling)
and Torn Edge (needs Cairo for path-fill masking) don't fit that
constraint and live in ui/effects.py instead.
"""

from __future__ import annotations

import numpy as np

from greenshot_linux.core.filters import box_blur as _region_box_blur
from greenshot_linux.core.geometry import Rect


def rotate_90_image(image: np.ndarray, clockwise: bool) -> np.ndarray:
    """Faithful port of RotateEffect (Greenshot.Base/Effects/
    RotateEffect.cs:32-68) - only 90-degree rotation is supported
    there (arbitrary angles throw NotSupportedException), same here.
    """
    return np.rot90(image, k=-1 if clockwise else 1).copy()


def grayscale_image(image: np.ndarray) -> np.ndarray:
    """Faithful port of ImageHelper.CreateGrayscale
    (ImageHelper.cs:1133-1161): the classic NTSC luma weights
    R=.3, G=.59, B=.11, alpha untouched.
    """
    rgb = image[:, :, :3].astype(np.float64)
    luma = rgb[:, :, 0] * 0.3 + rgb[:, :, 1] * 0.59 + rgb[:, :, 2] * 0.11
    luma = np.clip(np.round(luma), 0, 255).astype(np.uint8)
    result = image.copy()
    result[:, :, 0] = luma
    result[:, :, 1] = luma
    result[:, :, 2] = luma
    return result


def invert_image(image: np.ndarray) -> np.ndarray:
    """Faithful port of ImageHelper.CreateNegative (ImageHelper.cs:900-928):
    ``out = 255 - in`` per RGB channel, alpha untouched.
    """
    result = image.copy()
    result[:, :, :3] = 255 - image[:, :, :3]
    return result


def monochrome_image(image: np.ndarray, threshold: int = 127) -> np.ndarray:
    """Faithful port of ImageHelper.CreateMonochrome (ImageHelper.cs:998-1013):
    a flat (unweighted) per-pixel average of R/G/B, hard-binarized
    against ``threshold`` - ``(R+G+B)/3 > threshold ? white : black``,
    alpha untouched. Deliberately *not* the same as grayscale_image's
    luma weighting - Windows uses this plain average here specifically,
    confirmed by reading the source rather than assumed. Only used for
    print's "force black/white" option in this port (ui/printing.py) -
    Windows itself never wires this into the editor's Effects menu
    either, only print.
    """
    average = image[:, :, :3].astype(np.float64).mean(axis=2)
    value = np.where(average > threshold, 255, 0).astype(np.uint8)
    result = image.copy()
    result[:, :, 0] = value
    result[:, :, 1] = value
    result[:, :, 2] = value
    return result


def remove_transparency_image(image: np.ndarray, fill_color=(255, 255, 255, 255)) -> np.ndarray:
    """Flattens alpha onto a solid background color - faithful port of
    RemoveTransparencyEffect (only applies if there's alpha to remove
    in the source; this function is unconditional, callers check).
    """
    alpha = image[:, :, 3:4].astype(np.float64) / 255
    rgb = image[:, :, :3].astype(np.float64)
    bg = np.array(fill_color[:3], dtype=np.float64)
    blended = rgb * alpha + bg * (1 - alpha)
    result = np.empty_like(image)
    result[:, :, :3] = np.clip(np.round(blended), 0, 255).astype(np.uint8)
    result[:, :, 3] = 255
    return result


def clear_image(width: int, height: int) -> np.ndarray:
    """A fully transparent image of the given size - faithful port of
    Surface.Clear (Surface.cs:1078-1087): replaces the whole image,
    but (per the caller in ui/editor_window.py) doesn't remove
    annotation elements, only the base pixels.
    """
    return np.zeros((height, width, 4), dtype=np.uint8)


def _alpha_composite(dst: np.ndarray, src: np.ndarray, left: int, top: int) -> None:
    """Paints ``src`` onto ``dst`` in place at (left, top), "src over
    dst" alpha compositing, clipped to dst's bounds. Shared by every
    effect below that pastes one image onto a differently-sized canvas
    (add_border_image, drop_shadow_image) - Windows does the
    equivalent via GDI+'s own alpha-aware Graphics.DrawImage.
    """
    src_h, src_w = src.shape[:2]
    dst_h, dst_w = dst.shape[:2]
    dst_left, dst_top = max(0, left), max(0, top)
    dst_right, dst_bottom = min(dst_w, left + src_w), min(dst_h, top + src_h)
    if dst_left >= dst_right or dst_top >= dst_bottom:
        return
    src_left, src_top = dst_left - left, dst_top - top
    src_right, src_bottom = dst_right - left, dst_bottom - top
    region = dst[dst_top:dst_bottom, dst_left:dst_right]
    piece = src[src_top:src_bottom, src_left:src_right]
    alpha = piece[:, :, 3:4].astype(np.float64) / 255
    blended_rgb = piece[:, :, :3].astype(np.float64) * alpha + region[:, :, :3].astype(np.float64) * (1 - alpha)
    blended_alpha = piece[:, :, 3].astype(np.float64) + region[:, :, 3].astype(np.float64) * (1 - alpha[:, :, 0])
    region[:, :, :3] = np.clip(np.round(blended_rgb), 0, 255).astype(np.uint8)
    region[:, :, 3] = np.clip(np.round(blended_alpha), 0, 255).astype(np.uint8)


def add_border_image(image: np.ndarray, width: int = 2, color=(0, 0, 0, 255)) -> np.ndarray:
    """Faithful port of ImageHelper.CreateBorder (ImageHelper.cs:1024-1060):
    grows the canvas by ``width`` on every side, filled with ``color``,
    with the original image composited on top. Windows' own default
    (left-click, no dialog) is 2px solid black - same default here.
    """
    h, w = image.shape[:2]
    result = np.empty((h + 2 * width, w + 2 * width, 4), dtype=np.uint8)
    result[:, :] = color
    _alpha_composite(result, image, width, width)
    return result


def enlarge_canvas_image(image: np.ndarray, left: int, right: int, top: int, bottom: int, fill_color=(0, 0, 0, 0)) -> np.ndarray:
    """Faithful port of ImageHelper.ResizeCanvas (ImageHelper.cs:1399-1410):
    pads the canvas with ``fill_color`` (transparent by default - room
    to draw more annotations, not a colored bar) and pastes the
    original unscaled at the new offset. Used by "Enlarge canvas"
    (Ctrl+Shift++, ImageEditorForm.cs:1817-1821), fixed 25px on every
    side there.
    """
    h, w = image.shape[:2]
    result = np.empty((h + top + bottom, w + left + right, 4), dtype=np.uint8)
    result[:, :] = fill_color
    result[top:top + h, left:left + w] = image
    return result


def _paste_clipped(dst_channel: np.ndarray, src_channel: np.ndarray, left: int, top: int) -> None:
    """Like _alpha_composite but for a single plain channel (no alpha
    blending) - a direct, bounds-clipped overwrite. Used to place the
    drop-shadow silhouette, whose offset can in principle push it
    partially outside the padded canvas.
    """
    src_h, src_w = src_channel.shape[:2]
    dst_h, dst_w = dst_channel.shape[:2]
    dst_left, dst_top = max(0, left), max(0, top)
    dst_right, dst_bottom = min(dst_w, left + src_w), min(dst_h, top + src_h)
    if dst_left >= dst_right or dst_top >= dst_bottom:
        return
    src_left, src_top = dst_left - left, dst_top - top
    src_right, src_bottom = dst_right - left, dst_bottom - top
    dst_channel[dst_top:dst_bottom, dst_left:dst_right] = src_channel[src_top:src_bottom, src_left:src_right]


def drop_shadow_image(image: np.ndarray, darkness: float = 0.6, size: int = 7, offset=(-1, -1)) -> np.ndarray:
    """Whole-image drop shadow - a good-faith reproduction of the
    *documented* algorithm behind ImageHelper.CreateShadow
    (ImageHelper.cs:830-893) - build a solid black silhouette of the
    image's own alpha shape at ``darkness`` opacity, blur it (reusing
    core/filters.py's box_blur - the same already-Windows-verified
    two-pass blur the Blur obfuscation tool uses, over the whole
    canvas rather than a sub-rect, rather than a second, independently
    written blur implementation), offset it, then paint the original
    image back on top - using the same default parameters (darkness
    0.6, size 7, offset (-1,-1)), rather than a pixel-identical port
    of GDI+'s exact compositing internals, which aren't independently
    verifiable without a reference render to diff against. ``size`` is
    forced odd, matching the source.
    """
    if size % 2 == 0:
        size += 1
    h, w = image.shape[:2]
    pad = size
    silhouette = np.zeros((h + pad * 2, w + pad * 2, 4), dtype=np.uint8)

    silhouette_alpha = np.clip(image[:, :, 3].astype(np.float64) * darkness, 0, 255).round().astype(np.uint8)
    _paste_clipped(silhouette[:, :, 3], silhouette_alpha, pad + offset[0], pad + offset[1])

    canvas_h, canvas_w = silhouette.shape[:2]
    blurred = _region_box_blur(silhouette, Rect(0, 0, canvas_w, canvas_h), size)
    _alpha_composite(blurred, image, pad, pad)
    return blurred
