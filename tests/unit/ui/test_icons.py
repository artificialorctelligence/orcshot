"""Toolbar icons for the drawing tools.

Small Cairo-drawn icons, not a downloaded/bundled icon pack - no icon
theme has standardized names for "rectangle annotation tool" etc. (the
generic actions - Undo/Redo/Copy/Save/Print - use standard freedesktop
theme icon names instead, confirmed present via Gtk.IconTheme.has_icon
before relying on them; that part isn't unit tested, it's just a
Gtk.Image.new_from_icon_name call in editor_window.py).

Where a tool already has a real renderer (Rectangle/Ellipse/Line/Arrow/
Freehand/StepLabel's own outline circle), its icon reuses that exact
render_* function on a miniature shape, so the icon can never visually
drift from what the tool actually draws. Pixelize/Blur/Text have no
small-scale renderer to reuse (obfuscation needs a base image to
filter, and a single glyph doesn't need Pango's layout machinery), so
those are hand-drawn - as is the single Obfuscate toolbar button's own
icon (_obfuscate_icon, not keyed by Tool - see its own docstring),
representing the whole feature rather than any one selectable mode.

Headless-testable like the rest of ui/ - Cairo needs no X11 connection.
"""

import numpy as np

from greenshot_linux.core.tools import Tool
from greenshot_linux.ui.cairo_convert import cairo_surface_to_numpy
from greenshot_linux.ui.icons import ICON_SIZE, _effects_icon, _highlight_icon, _obfuscate_icon, tool_icon_surface


def test_every_tool_has_an_icon_builder():
    for tool in Tool:
        surface = tool_icon_surface(tool)
        assert surface.get_width() == ICON_SIZE
        assert surface.get_height() == ICON_SIZE


def test_every_tool_icon_draws_something_visible():
    for tool in Tool:
        surface = tool_icon_surface(tool)
        image = cairo_surface_to_numpy(surface)
        assert image[:, :, 3].max() > 0, f"{tool} icon is fully transparent"


def test_icons_for_different_tools_are_not_identical():
    # a cheap sanity check against a copy-paste bug where every builder
    # accidentally draws the same thing
    surfaces = {tool: cairo_surface_to_numpy(tool_icon_surface(tool)) for tool in Tool}
    tools = list(surfaces)
    for i, tool_a in enumerate(tools):
        for tool_b in tools[i + 1:]:
            assert not np.array_equal(surfaces[tool_a], surfaces[tool_b]), f"{tool_a} and {tool_b} look identical"


_LINE_ART_TOOLS = [
    Tool.SELECT, Tool.RECTANGLE, Tool.ELLIPSE, Tool.LINE, Tool.ARROW, Tool.FREEHAND, Tool.TEXT,
    Tool.SPEECH_BUBBLE, Tool.EMOJI, Tool.STEP_LABEL,
]


def test_line_art_icons_use_the_given_color():
    # Rectangle/Ellipse/Line/Arrow/Freehand/Text must be theme-aware
    # (a real bug: they used to hardcode a fixed dark gray, which was
    # nearly invisible against a dark toolbar theme - reported live,
    # confirmed by screenshot, root-caused to this hardcoding).
    red = (255, 0, 0, 255)
    for tool in _LINE_ART_TOOLS:
        image = cairo_surface_to_numpy(tool_icon_surface(tool, color=red))
        mask = (image[:, :, 0] > 200) & (image[:, :, 1] < 50) & (image[:, :, 2] < 50) & (image[:, :, 3] > 0)
        assert mask.any(), f"{tool} icon doesn't use the given color"


def test_line_art_icons_change_visibly_between_colors():
    white = (255, 255, 255, 255)
    black = (0, 0, 0, 255)
    for tool in _LINE_ART_TOOLS:
        white_image = cairo_surface_to_numpy(tool_icon_surface(tool, color=white))
        black_image = cairo_surface_to_numpy(tool_icon_surface(tool, color=black))
        assert not np.array_equal(white_image, black_image), f"{tool} icon looks the same in white and black"


def test_pixelize_and_blur_icons_ignore_the_color_param():
    # these represent colorful image content, not theme-colored line
    # art - the requested color intentionally doesn't apply to them.
    for tool in (Tool.PIXELIZE, Tool.BLUR):
        white_image = cairo_surface_to_numpy(tool_icon_surface(tool, color=(255, 255, 255, 255)))
        black_image = cairo_surface_to_numpy(tool_icon_surface(tool, color=(0, 0, 0, 255)))
        assert np.array_equal(white_image, black_image), f"{tool} icon changed with the color param"


def test_obfuscate_icon_draws_something_visible():
    surface = _obfuscate_icon((60, 60, 60, 255))
    assert surface.get_width() == ICON_SIZE
    assert surface.get_height() == ICON_SIZE
    image = cairo_surface_to_numpy(surface)
    assert image[:, :, 3].max() > 0


def test_obfuscate_icon_uses_the_given_color():
    red = (255, 0, 0, 255)
    image = cairo_surface_to_numpy(_obfuscate_icon(red))
    mask = (image[:, :, 0] > 200) & (image[:, :, 1] < 50) & (image[:, :, 2] < 50) & (image[:, :, 3] > 0)
    assert mask.any()


def test_obfuscate_icon_changes_visibly_between_colors():
    white_image = cairo_surface_to_numpy(_obfuscate_icon((255, 255, 255, 255)))
    black_image = cairo_surface_to_numpy(_obfuscate_icon((0, 0, 0, 255)))
    assert not np.array_equal(white_image, black_image)


def test_effects_icon_draws_something_visible():
    surface = _effects_icon((60, 60, 60, 255))
    assert surface.get_width() == ICON_SIZE
    assert surface.get_height() == ICON_SIZE
    image = cairo_surface_to_numpy(surface)
    assert image[:, :, 3].max() > 0


def test_effects_icon_uses_the_given_color():
    red = (255, 0, 0, 255)
    image = cairo_surface_to_numpy(_effects_icon(red))
    mask = (image[:, :, 0] > 200) & (image[:, :, 1] < 50) & (image[:, :, 2] < 50) & (image[:, :, 3] > 0)
    assert mask.any()


def test_effects_icon_changes_visibly_between_colors():
    white_image = cairo_surface_to_numpy(_effects_icon((255, 255, 255, 255)))
    black_image = cairo_surface_to_numpy(_effects_icon((0, 0, 0, 255)))
    assert not np.array_equal(white_image, black_image)


def test_highlight_icon_draws_something_visible():
    surface = _highlight_icon((60, 60, 60, 255))
    assert surface.get_width() == ICON_SIZE
    assert surface.get_height() == ICON_SIZE
    image = cairo_surface_to_numpy(surface)
    assert image[:, :, 3].max() > 0


def test_highlight_icon_uses_the_given_color():
    red = (255, 0, 0, 255)
    image = cairo_surface_to_numpy(_highlight_icon(red))
    mask = (image[:, :, 0] > 200) & (image[:, :, 1] < 50) & (image[:, :, 2] < 50) & (image[:, :, 3] > 0)
    assert mask.any()


def test_highlight_icon_changes_visibly_between_colors():
    white_image = cairo_surface_to_numpy(_highlight_icon((255, 255, 255, 255)))
    black_image = cairo_surface_to_numpy(_highlight_icon((0, 0, 0, 255)))
    assert not np.array_equal(white_image, black_image)
