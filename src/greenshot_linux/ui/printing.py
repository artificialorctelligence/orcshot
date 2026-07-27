"""Printing a captured image via GTK's print dialog - factored out of
EditorWindow so the destination picker (ui/destination_picker.py) can
print a raw, not-yet-annotated capture too, not just EditorWindow's own
composited image. EditorWindow's own Print button is now a thin
wrapper calling this with its composited image.

Not unit tested for the same reason editor_window.py isn't: GTK print-
dialog glue with no meaningful headless test. Verified live (via
Gtk.PrintOperationAction.EXPORT to a PDF, rendered back with pdftoppm,
and visually confirmed centered/scaled) when this logic first shipped
inside EditorWindow - behavior is unchanged by this extraction.
"""

from __future__ import annotations

import numpy as np
import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk

from greenshot_linux.ui.cairo_convert import numpy_to_cairo_surface


def _draw_print_page(image: np.ndarray, operation, context, page_nr) -> None:
    img_h, img_w = image.shape[:2]
    page_w, page_h = context.get_width(), context.get_height()
    scale = min(page_w / img_w, page_h / img_h)

    ctx = context.get_cairo_context()
    ctx.translate((page_w - img_w * scale) / 2, (page_h - img_h * scale) / 2)
    ctx.scale(scale, scale)
    ctx.set_source_surface(numpy_to_cairo_surface(image), 0, 0)
    ctx.paint()


def print_image(image: np.ndarray, parent: Gtk.Window = None) -> None:
    operation = Gtk.PrintOperation()
    operation.set_n_pages(1)
    operation.connect("draw-page", lambda op, ctx, page_nr: _draw_print_page(image, op, ctx, page_nr))
    operation.run(Gtk.PrintOperationAction.PRINT_DIALOG, parent)
