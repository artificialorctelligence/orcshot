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

from orcshot.core.tools import Tool
from orcshot.ui.cairo_convert import cairo_surface_to_numpy
from orcshot.ui.gdk_convert import pixbuf_to_numpy
from orcshot.ui.icons import (
    ICON_SIZE, _DEFAULT_COLOR, _crop_icon, _drawn_icon_image, _effects_icon, _highlight_icon, _obfuscate_icon,
    _resize_icon, _rotate_icon, destination_icon_image, tool_icon_surface,
)


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


def test_destination_icon_image_uses_the_mapped_geometry_for_known_ids():
    clipboard = pixbuf_to_numpy(destination_icon_image("clipboard").get_pixbuf())
    save = pixbuf_to_numpy(destination_icon_image("save").get_pixbuf())
    assert not np.array_equal(clipboard, save), "clipboard and save should use different icons"


def test_destination_icon_image_falls_back_to_the_shared_geometry_icon_for_unmapped_ids():
    # "office" and any "external:<name>" ExternalCommand id have no
    # fixed action to depict (task #110/#95). Task #113 needs the
    # Wayland Shell picker to draw this same fallback too, which means
    # it now has to be geometry.json-backed like every other icon
    # (extension.js can't run this module's own Cairo code) rather
    # than the one-off hand-drawn _external_command_icon it used to
    # be - so this specifically pins the fallback to the new
    # "external-command-symbolic" geometry key, not just "renders
    # something", to guard the actual mechanism this task depends on.
    office = pixbuf_to_numpy(destination_icon_image("office").get_pixbuf())
    external = pixbuf_to_numpy(destination_icon_image("external:My Tool").get_pixbuf())
    expected = pixbuf_to_numpy(_drawn_icon_image("external-command-symbolic", _DEFAULT_COLOR, ICON_SIZE).get_pixbuf())
    assert np.array_equal(office, expected)
    assert np.array_equal(external, expected)
    assert expected[:, :, 3].max() > 0, "fallback icon is fully transparent"


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


def test_rotate_icons_draw_something_visible():
    for clockwise in (True, False):
        surface = _rotate_icon((60, 60, 60, 255), clockwise=clockwise)
        assert surface.get_width() == ICON_SIZE
        assert surface.get_height() == ICON_SIZE
        image = cairo_surface_to_numpy(surface)
        assert image[:, :, 3].max() > 0


def test_rotate_icons_use_the_given_color():
    red = (255, 0, 0, 255)
    for clockwise in (True, False):
        image = cairo_surface_to_numpy(_rotate_icon(red, clockwise=clockwise))
        mask = (image[:, :, 0] > 200) & (image[:, :, 1] < 50) & (image[:, :, 2] < 50) & (image[:, :, 3] > 0)
        assert mask.any()


def test_rotate_cw_and_ccw_icons_are_not_identical():
    # CCW is drawn by mirroring CW's own commands (see _rotate_icon's
    # docstring) - not asserting exact pixel mirror symmetry here,
    # since Cairo's antialiasing under a flip transform isn't
    # guaranteed bit-identical to the unflipped raster at the
    # sub-pixel level, even for geometrically identical paths.
    cw = cairo_surface_to_numpy(_rotate_icon((60, 60, 60, 255), clockwise=True))
    ccw = cairo_surface_to_numpy(_rotate_icon((60, 60, 60, 255), clockwise=False))
    assert not np.array_equal(cw, ccw)


def test_resize_icon_draws_something_visible():
    surface = _resize_icon((60, 60, 60, 255))
    assert surface.get_width() == ICON_SIZE
    assert surface.get_height() == ICON_SIZE
    image = cairo_surface_to_numpy(surface)
    assert image[:, :, 3].max() > 0


def test_resize_icon_uses_the_given_color():
    red = (255, 0, 0, 255)
    image = cairo_surface_to_numpy(_resize_icon(red))
    mask = (image[:, :, 0] > 200) & (image[:, :, 1] < 50) & (image[:, :, 2] < 50) & (image[:, :, 3] > 0)
    assert mask.any()


def test_resize_icon_changes_visibly_between_colors():
    white_image = cairo_surface_to_numpy(_resize_icon((255, 255, 255, 255)))
    black_image = cairo_surface_to_numpy(_resize_icon((0, 0, 0, 255)))
    assert not np.array_equal(white_image, black_image)


def test_crop_icon_draws_something_visible():
    surface = _crop_icon((60, 60, 60, 255))
    assert surface.get_width() == ICON_SIZE
    assert surface.get_height() == ICON_SIZE
    image = cairo_surface_to_numpy(surface)
    assert image[:, :, 3].max() > 0


def test_crop_icon_uses_the_given_color():
    red = (255, 0, 0, 255)
    image = cairo_surface_to_numpy(_crop_icon(red))
    mask = (image[:, :, 0] > 200) & (image[:, :, 1] < 50) & (image[:, :, 2] < 50) & (image[:, :, 3] > 0)
    assert mask.any()


def test_crop_icon_changes_visibly_between_colors():
    white_image = cairo_surface_to_numpy(_crop_icon((255, 255, 255, 255)))
    black_image = cairo_surface_to_numpy(_crop_icon((0, 0, 0, 255)))
    assert not np.array_equal(white_image, black_image)
