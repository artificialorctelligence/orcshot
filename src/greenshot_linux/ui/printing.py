"""Printing a captured image via GTK's print dialog - factored out of
EditorWindow so the destination picker (ui/destination_picker.py) can
print a raw, not-yet-annotated capture too, not just EditorWindow's own
composited image. EditorWindow's own Print button is now a thin
wrapper calling this with its composited image.

Advanced print options - a faithful port of PrintOptionsDialog
(Greenshot/Forms/PrintOptionsDialog.cs) and PrintHelper.DrawImageForPrint
(Greenshot/Helpers/PrintHelper.cs:183-282). Deliberately does *not* use
Gtk.PrintOperation's "create-custom-widget" signal (which would embed
this dialog's controls as a tab inside the native print dialog) -
Windows itself shows its own separate PrintOptionsDialog *after* the
native/OS print dialog (PrintHelper.cs:105,139 - PrintWithDialog shows
the OS dialog first, then this port's equivalent), not merged into it,
and a standalone Gtk.Dialog (matching every other options dialog in
this project) also makes the "don't ask again" skip-the-dialog-entirely
behavior trivial, which create-custom-widget doesn't support (it always
renders whenever the native dialog is shown).

No custom printer-enumeration/selection UI - confirmed live that
Gtk.PrintUnixDialog/Gtk.Printer aren't exposed via GObject-Introspection
at all in this GTK3 build, and Gtk.PrintOperation.run() already shows a
full native printer picker, covering the same practical need without a
new dependency (pycups) just to replicate Windows' "one destination
menu item per installed printer".

Not unit tested for the same reason editor_window.py isn't: GTK print-
dialog glue with no meaningful headless test. The actual layout/rotate/
scale/center math is pure and tested separately (core/print_layout.py).
Verified live (via Gtk.PrintOperationAction.EXPORT to a PDF, rendered
back with pdftoppm) for the base flow when this logic first shipped;
the advanced-options additions verified the same way plus direct
dialog-widget inspection (see REQUIREMENTS.md's "Advanced print
options" section).
"""

from __future__ import annotations

from datetime import datetime

import numpy as np
import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Pango", "1.0")
gi.require_version("PangoCairo", "1.0")
from gi.repository import Gtk, Pango, PangoCairo

from greenshot_linux.core.effects import grayscale_image, invert_image, monochrome_image, rotate_90_image
from greenshot_linux.core.print_layout import compute_print_layout
from greenshot_linux.settings import PrintOptions, get_print_options, set_print_options
from greenshot_linux.ui.cairo_convert import numpy_to_cairo_surface

_FOOTER_FONT_FAMILY = "sans-serif"
_FOOTER_FONT_SIZE_PT = 10  # PrintHelper.cs:202's fixed Font(FontFamily.GenericSansSerif, 10, Regular)


def _apply_color_mode(image: np.ndarray, options: PrintOptions) -> np.ndarray:
    """Pre-processing pixel effects on a temporary print-time copy,
    never the saved/copied image - faithful port of
    PrintHelper.ApplyEffects (PrintHelper.cs:266-282). Monochrome and
    invert are real per-pixel effects there; "grayscale" is actually a
    printer-driver flag in Windows (DefaultPageSettings.Color = false,
    no pixel processing at all) - deliberately ported as a pixel
    effect instead (reusing core/effects.py's grayscale_image, the
    same one this port's editor Effects menu uses) for consistency,
    and because there's no driver to delegate to for the
    Gtk.PrintOperationAction.EXPORT path this project verifies against.
    """
    if options.monochrome:
        image = monochrome_image(image, threshold=options.monochrome_threshold)
    elif options.grayscale:
        image = grayscale_image(image)
    if options.inverted:
        image = invert_image(image)
    return image


def _footer_text(when: datetime) -> str:
    """A simplified equivalent of Windows' footer pattern
    (``${capturetime:d"D"} ${capturetime:d"T"} - ${title}``,
    ICoreConfiguration.cs:207-209) - just the print-time timestamp, no
    "- title" suffix: this port doesn't track a per-capture title/
    window-name through to printing the way Windows' CaptureDetails
    does. A deliberate scope reduction, not silently dropped.
    """
    return when.strftime("%B %d, %Y %I:%M %p")


def _footer_layout(context, text: str):
    # context.create_pango_layout (not PangoCairo.create_layout) ties
    # the layout to the print context's own DPI - a plain screen-DPI
    # layout (like ui/render.py's _pango_layout, built for the on-screen
    # canvas) would size the footer text wrong against a real printer's
    # resolution.
    layout = context.create_pango_layout()
    layout.set_text(text, -1)
    font_desc = Pango.FontDescription()
    font_desc.set_family(_FOOTER_FONT_FAMILY)
    font_desc.set_size(_FOOTER_FONT_SIZE_PT * Pango.SCALE)
    layout.set_font_description(font_desc)
    return layout


def _draw_print_page(image: np.ndarray, options: PrintOptions, operation, context, page_nr) -> None:
    processed = _apply_color_mode(image, options)
    page_w, page_h = context.get_width(), context.get_height()
    ctx = context.get_cairo_context()

    footer_text = footer_layout = None
    footer_height = 0.0
    if options.footer:
        footer_text = _footer_text(datetime.now())
        footer_layout = _footer_layout(context, footer_text)
        _, extents = footer_layout.get_pixel_extents()
        footer_height = extents.height
        page_h -= footer_height  # reserved *before* the fit/center math, matching PrintHelper.cs:217

    img_h, img_w = processed.shape[:2]
    layout = compute_print_layout(
        img_w, img_h, page_w, page_h,
        options.allow_shrink, options.allow_enlarge, options.center,
        allow_rotate=options.allow_rotate,
    )
    if layout.rotate:
        processed = rotate_90_image(processed, clockwise=True)

    proc_h, proc_w = processed.shape[:2]
    ctx.save()
    ctx.translate(layout.x, layout.y)
    if proc_w and proc_h:
        ctx.scale(layout.width / proc_w, layout.height / proc_h)
    ctx.set_source_surface(numpy_to_cairo_surface(processed), 0, 0)
    ctx.paint()
    ctx.restore()

    if footer_layout is not None:
        _, extents = footer_layout.get_pixel_extents()
        ctx.save()
        ctx.translate((context.get_width() - extents.width) / 2, page_h)
        ctx.set_source_rgb(0, 0, 0)
        PangoCairo.show_layout(ctx, footer_layout)
        ctx.restore()


def _show_print_options_dialog(parent: Gtk.Window, options: PrintOptions) -> PrintOptions | None:
    """None if the user cancelled. Mirrors PrintOptionsDialog's real
    layout (Designer.cs:222-261): a "Page layout settings" group
    (shrink/enlarge/rotate/center/footer) and a "Color settings" group
    (full color / grayscale / monochrome radios + an independent
    invert checkbox), plus "don't ask again".
    """
    dialog = Gtk.Dialog(title="Greenshot print options", transient_for=parent)
    dialog.add_buttons(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL, Gtk.STOCK_OK, Gtk.ResponseType.OK)
    content = dialog.get_content_area()
    content.set_border_width(12)
    content.set_spacing(10)

    layout_frame = Gtk.Frame(label="Page layout settings")
    layout_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
    layout_box.set_border_width(8)
    shrink_check = Gtk.CheckButton(label="Shrink printout to fit paper size")
    shrink_check.set_active(options.allow_shrink)
    enlarge_check = Gtk.CheckButton(label="Enlarge printout to fit paper size")
    enlarge_check.set_active(options.allow_enlarge)
    rotate_check = Gtk.CheckButton(label="Rotate printout to page orientation")
    rotate_check.set_active(options.allow_rotate)
    center_check = Gtk.CheckButton(label="Center printout on page")
    center_check.set_active(options.center)
    footer_check = Gtk.CheckButton(label="Print date / time at bottom of page")
    footer_check.set_active(options.footer)
    for widget in (shrink_check, enlarge_check, rotate_check, center_check, footer_check):
        layout_box.pack_start(widget, False, False, 0)
    layout_frame.add(layout_box)
    content.pack_start(layout_frame, False, False, 0)

    color_frame = Gtk.Frame(label="Color settings")
    color_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
    color_box.set_border_width(8)
    color_radio = Gtk.RadioButton.new_with_label(None, "Full color print")
    grayscale_radio = Gtk.RadioButton.new_with_label_from_widget(color_radio, "Force grayscale printing")
    monochrome_radio = Gtk.RadioButton.new_with_label_from_widget(color_radio, "Force black/white printing")
    if options.monochrome:
        monochrome_radio.set_active(True)
    elif options.grayscale:
        grayscale_radio.set_active(True)
    else:
        color_radio.set_active(True)
    invert_check = Gtk.CheckButton(label="Print with inverted colors")
    invert_check.set_active(options.inverted)
    for widget in (color_radio, grayscale_radio, monochrome_radio, invert_check):
        color_box.pack_start(widget, False, False, 0)
    color_frame.add(color_box)
    content.pack_start(color_frame, False, False, 0)

    dont_ask_check = Gtk.CheckButton(label="Save options as default and do not ask again")
    dont_ask_check.set_active(False)
    content.pack_start(dont_ask_check, False, False, 0)

    dialog.show_all()
    try:
        if dialog.run() != Gtk.ResponseType.OK:
            return None
        return PrintOptions(
            prompt_options=not dont_ask_check.get_active(),
            allow_shrink=shrink_check.get_active(),
            allow_enlarge=enlarge_check.get_active(),
            allow_rotate=rotate_check.get_active(),
            center=center_check.get_active(),
            footer=footer_check.get_active(),
            grayscale=grayscale_radio.get_active(),
            monochrome=monochrome_radio.get_active(),
            monochrome_threshold=options.monochrome_threshold,
            inverted=invert_check.get_active(),
        )
    finally:
        dialog.destroy()


def print_image(image: np.ndarray, parent: Gtk.Window = None) -> None:
    options = get_print_options()
    if options.prompt_options:
        chosen = _show_print_options_dialog(parent, options)
        if chosen is None:
            return
        options = chosen
        set_print_options(options)

    operation = Gtk.PrintOperation()
    operation.set_n_pages(1)
    operation.connect("draw-page", lambda op, ctx, page_nr: _draw_print_page(image, options, op, ctx, page_nr))
    operation.run(Gtk.PrintOperationAction.PRINT_DIALOG, parent)
