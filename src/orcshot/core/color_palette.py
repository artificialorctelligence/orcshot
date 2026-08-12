"""The editor's color-picker palette and recent-colors list - faithful
port of Greenshot.Editor.Forms.ColorDialog (ColorDialog.cs), which
Windows' line-color/fill-color toolbar buttons (ToolStripColorButton)
open directly - not a small dropdown-then-dialog flow, one dialog with
everything in it (see REQUIREMENTS.md's "Color picker" section for the
full research trail).

Pure logic only - the actual dialog widgets live in ui/color_dialog.py.
"""

from __future__ import annotations

from typing import List, Tuple

Color = Tuple[int, int, int, int]  # RGBA, matching this codebase's convention elsewhere

# The 12 base hue colors CreateColorPalette iterates through, in this
# exact order - faithful port of ColorDialog.cs:68-94's literal call
# sequence (component halves use // 2, matching C#'s integer division
# via "255 / 2" on int operands).
_HUE_COLUMNS: Tuple[Tuple[int, int, int], ...] = (
    (255, 0, 0),  # red
    (255, 255 // 2, 0),  # orange
    (255, 255, 0),  # yellow
    (255 // 2, 255, 0),  # chartreuse
    (0, 255, 0),  # green
    (0, 255, 255 // 2),  # spring green
    (0, 255, 255),  # cyan
    (0, 255 // 2, 255),  # azure
    (0, 0, 255),  # blue
    (255 // 2, 0, 255),  # violet
    (255, 0, 255),  # magenta
    (255, 0, 255 // 2),  # rose
)
_GREY_COLUMN: Tuple[int, int, int] = (255 // 2, 255 // 2, 255 // 2)

SHADES_PER_COLUMN = 11
RECENT_COLORS_MAX = 12


def _shaded_column(red: int, green: int, blue: int) -> List[Color]:
    """The 11 shades for one hue column, top-to-bottom: black, 4
    intermediate dark shades, the pure hue (row 5), 4 intermediate
    light shades, white - faithful port of CreateColorButtonColumn
    (ColorDialog.cs:99-109), including its *truncating* integer
    division (not rounded).
    """
    shaded_colors_num = (SHADES_PER_COLUMN - 1) // 2  # 5
    dark = []
    light = []
    for i in range(shaded_colors_num + 1):
        dark.append((
            red * i // shaded_colors_num, green * i // shaded_colors_num, blue * i // shaded_colors_num, 255,
        ))
        if i > 0:
            light.append((
                red + (255 - red) * i // shaded_colors_num,
                green + (255 - green) * i // shaded_colors_num,
                blue + (255 - blue) * i // shaded_colors_num,
                255,
            ))
    return dark + light


def color_palette_grid() -> List[List[Color]]:
    """13 columns x 11 rows - faithful port of CreateColorPalette
    (ColorDialog.cs:68-97): 12 hue columns (red, orange, yellow,
    chartreuse, green, spring green, cyan, azure, blue, violet,
    magenta, rose), each shaded black-to-hue-to-white, plus a
    greyscale column. Each returned column is top-to-bottom row order.
    """
    columns = [_shaded_column(*hue) for hue in _HUE_COLUMNS]
    columns.append(_shaded_column(*_GREY_COLUMN))
    return columns


def add_recent_color(recent_colors: List[Color], color: Color, max_count: int = RECENT_COLORS_MAX) -> List[Color]:
    """Faithful port of AddToRecentColors (ColorDialog.cs:182-192):
    remove any existing occurrence of ``color``, insert it at the
    front, truncate to ``max_count`` (12, matching Windows) - classic
    MRU behavior.
    """
    updated = [c for c in recent_colors if c != color]
    updated.insert(0, color)
    return updated[:max_count]
