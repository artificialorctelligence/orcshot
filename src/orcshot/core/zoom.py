"""Editor canvas zoom - faithful port of ImageEditorForm/Surface's
zoom feature (Greenshot.Editor/Forms/ImageEditorForm.cs,
Greenshot.Editor/Drawing/Surface.cs). Confirmed via research this is
a real, well-developed Windows feature (added in PR #201, Ctrl+wheel
in PR #282 - see docs/changelogs/CHANGELOG-1.3.md:192-193 in the
Windows source), not something to design from scratch.

Fixed discrete levels rather than continuous zoom - ImageEditorForm.cs:101-104's
ZOOM_VALUES = [1/4, 1/2, 2/3, 3/4, 1/1, 2/1, 3/1, 4/1, 6/1]. Uses
fractions.Fraction rather than float for the same reason Windows uses
its own Fraction struct there: 2/3 (66%) has no exact float
representation, and repeated float zoom steps would drift.
"""

from __future__ import annotations

from fractions import Fraction

ZOOM_LEVELS: tuple[Fraction, ...] = (
    Fraction(1, 4), Fraction(1, 2), Fraction(2, 3), Fraction(3, 4), Fraction(1, 1),
    Fraction(2, 1), Fraction(3, 1), Fraction(4, 1), Fraction(6, 1),
)
ACTUAL_SIZE_ZOOM = Fraction(1, 1)


def zoom_in(current: Fraction) -> Fraction:
    """The next level above ``current``, or the top level if already there."""
    for level in ZOOM_LEVELS:
        if level > current:
            return level
    return ZOOM_LEVELS[-1]


def zoom_out(current: Fraction) -> Fraction:
    """The next level below ``current``, or the bottom level if already there."""
    for level in reversed(ZOOM_LEVELS):
        if level < current:
            return level
    return ZOOM_LEVELS[0]


def best_fit_zoom(content_width: int, content_height: int, available_width: int, available_height: int) -> Fraction:
    """The largest fixed level at which the content still fits entirely
    within the available space, faithfully porting
    ZoomBestFitMenuItemClick's "pick the largest ZOOM_VALUES entry
    that still fits" (ImageEditorForm.cs:2080-2098). Falls back to the
    smallest level if even that doesn't fit - matches Windows: it
    never gives up and shows nothing, it just accepts overflow at the
    smallest available level.
    """
    fitting = [
        level for level in ZOOM_LEVELS
        if content_width * level <= available_width and content_height * level <= available_height
    ]
    return max(fitting) if fitting else min(ZOOM_LEVELS)


def zoom_percent_label(zoom: Fraction) -> str:
    return f"{round(zoom * 100)}%"


def optimal_window_size(
    chrome_width: int, chrome_height: int, canvas_width: int, canvas_height: int,
    min_width: int, min_height: int, max_width: int, max_height: int,
) -> tuple[int, int]:
    """The editor window's total size for a given zoomed canvas size -
    faithful port of ImageEditorForm.GetOptimalWindowSize
    (ImageEditorForm.cs:2012-2052): everything that isn't the
    scrollable canvas ("chrome" - menu bar, toolbars, style panel,
    tool palette) plus the zoomed canvas itself, clamped to a minimum
    window size and to the available screen work area. ``chrome_*``
    is measured dynamically by the caller from the current layout
    (Windows: ``Size - panel1.ClientSize``), not hardcoded, since it
    doesn't vary with zoom but does vary with which panels are shown.
    """
    total_width = min(max(chrome_width + canvas_width, min_width), max_width)
    total_height = min(max(chrome_height + canvas_height, min_height), max_height)
    return total_width, total_height
