"""Pure layout math for printing - faithful port of
PrintHelper.DrawImageForPrint's rotate/scale/center computation
(Greenshot/Helpers/PrintHelper.cs:183-264), kept separate from
ui/printing.py's Cairo/GTK glue so it's unit-testable headless. The
footer text itself isn't computed here - it needs live font metrics
(ui/printing.py reserves page height for it before calling
compute_print_layout, matching Windows reserving pageRect.Height
*before* this math runs, PrintHelper.cs:217).
"""

from __future__ import annotations

from dataclasses import dataclass


def should_rotate_for_orientation(page_width: float, page_height: float, image_width: float, image_height: float) -> bool:
    """Faithful port of PrintHelper.cs:222-225's condition: rotate
    only if the page and image *orientations* actively disagree (page
    landscape + image portrait, or vice versa) - not a plain
    width-vs-height comparison, and a match (both landscape, both
    portrait, or either being square) never rotates.
    """
    page_landscape = page_width > page_height
    page_portrait = page_width < page_height
    image_landscape = image_width > image_height
    image_portrait = image_width < image_height
    return (page_landscape and image_portrait) or (page_portrait and image_landscape)


@dataclass(frozen=True)
class PrintLayout:
    x: float
    y: float
    width: float
    height: float
    rotate: bool


def compute_print_layout(
    image_width: float,
    image_height: float,
    page_width: float,
    page_height: float,
    allow_shrink: bool,
    allow_enlarge: bool,
    center: bool,
    allow_rotate: bool = True,
) -> PrintLayout:
    """Faithful port of PrintHelper.cs:183-264's rotate+scale+center
    math. ``allow_rotate`` gates whether an orientation mismatch is
    corrected at all (PrintHelper.cs:222's own
    ``if (CoreConfig.OutputPrintAllowRotate)`` check happens *before*
    the mismatch test, not just before applying it) - when False,
    ``should_rotate_for_orientation`` is never even consulted, so
    ``rotate`` is always False regardless of the actual mismatch.
    Shrink and enlarge are independently gated booleans sharing one
    aspect-preserving "fit within the page" scale computation
    (PrintHelper.cs:236-244, ScaleHelper.GetScaledSize) - shrink only
    applies if the fit is smaller than the original, enlarge only if
    it's bigger; if neither applies, the image prints at its natural
    (rotated-if-needed) size. Not centering aligns top-left, except
    Windows flips that to top-right after a rotate to keep the result
    visually sane (PrintHelper.cs:228-231).
    """
    rotate = allow_rotate and should_rotate_for_orientation(page_width, page_height, image_width, image_height)
    content_w, content_h = (image_height, image_width) if rotate else (image_width, image_height)

    width, height = content_w, content_h
    if content_w and content_h:
        scale = min(page_width / content_w, page_height / content_h)
        scaled_w, scaled_h = content_w * scale, content_h * scale
        if allow_shrink and scaled_w < width:
            width, height = scaled_w, scaled_h
        if allow_enlarge and scaled_w > width:
            width, height = scaled_w, scaled_h

    if center:
        x, y = (page_width - width) / 2, (page_height - height) / 2
    elif rotate:
        x, y = page_width - width, 0.0
    else:
        x, y = 0.0, 0.0

    return PrintLayout(x=x, y=y, width=width, height=height, rotate=rotate)
