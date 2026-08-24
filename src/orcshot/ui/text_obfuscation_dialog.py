"""Find & Redact Text (task #100) - faithful port of
ImageEditorForm.ObfuscateTextToolStripMenuItemClick
(ImageEditorForm.cs:1724-1768) and TextObfuscationForm
(TextObfuscationForm.cs): runs OCR on the editor's base image, then
lets the user search the recognized text (by word or by line, plain
substring or regex) and apply an obfuscation/highlight effect to every
match, with a live preview before committing.

Displayed as "Find & Redact Text..." in this port's Effects dropdown,
not Windows' own "Obfuscate Text" - direflail flagged live-testing
that the original name collides with the separate manual "Obfuscate"
drawing tool (task #54/#59), and that "Obfuscate" specifically implies
only ObfuscateShape results when this feature's effect choices also
include HighlightShape ones (Text Highlight/Magnification). "Redact"
names the outcome instead of a specific shape type, so it stays
accurate regardless of which effect is picked.

Deliberately not ported from TextObfuscationForm:
- The collapsible "Advanced settings" group - everything is shown at
  once here instead. A UX-chrome simplification only; every underlying
  setting (padding, offset, regex, case-sensitivity) is still present.
- AREA_HIGHLIGHT/GRAYSCALE as effect choices - Windows' own dropdown
  excludes them too ("Exclude AREA_HIGHLIGHT and GRAYSCALE as
  requested", TextObfuscationForm.cs:83). SCRAMBLE (task #60, no
  Windows precedent either) is left out for the same reason.
- Settings persistence across app restarts (EditorConfiguration.
  TextObfuscationSearchPattern/UseRegex/etc.) - session-only here
  (EditorWindow._text_obfuscation_settings), the same deliberate scope
  reduction already made for Drop Shadow/Torn Edge Settings.

Deliberately added beyond TextObfuscationForm's own 4-item effect list
(Pixelize/Blur/Text Highlight/Magnification): Solid Fill (task #60/#86,
no Windows precedent). Live-testing this feature against a real
capture surfaced exactly the scenario Solid Fill exists for - Pixelize
and Blur are reversible via public depixelation tools (see
core/filters.py's own docstrings and REQUIREMENTS.md's task #60
writeup), which matters more here than in the manual Obfuscate tool
since this feature's entire purpose is finding and redacting sensitive
text, not general-purpose stylistic obfuscation. Left out of Windows'
own dropdown only because Windows never built Solid Fill as a mode at
all - not a deliberate Windows design choice to exclude it, so adding
it here isn't a faithfulness break.

Not unit tested - GTK dialog glue with live OCR/preview state, same as
destination_picker.py/first_run_setup.py (see their own docstrings).
The pure logic it calls into (core/ocr.py's find_matches/apply_padding/
parse_tesseract_tsv) is fully tested there instead. Verified live:
ran this against a real capture containing text, searched a known
word, confirmed the preview box tracked it exactly, applied it, and
confirmed the resulting shape is undoable like any other add.
"""

from __future__ import annotations

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, GLib, Gtk

from orcshot.core.geometry import Rect
from orcshot.core.history import AddElementMemento, CompositeMemento
from orcshot.core.ocr import SCOPE_LINES, SCOPE_WORDS, OcrResult, find_matches
from orcshot.core.shapes import HighlightMode, HighlightShape, ObfuscateMode, ObfuscateShape
from orcshot.i18n import _, ngettext
from orcshot.ui.ocr import run_tesseract_ocr, tesseract_available

_DEBOUNCE_MS = 300
_DIALOG_TITLE = _("Find & Redact Text")

# (label, mode-key) - mode-key is either an ObfuscateMode or a
# HighlightMode; _make_shape below dispatches on which one it is. Order
# is security-tier-first (Solid Fill, then Pixelize/Blur), not
# InitializeEffectDropdown's original Pixelize-first order
# (TextObfuscationForm.cs:79-87) - direflail's live testing of this
# exact dialog is what drove Solid Fill's addition in the first place
# (see module docstring), so leading with it plus labeling Pixelize/
# Blur's real weakness inline reuses the identical security-tier
# convention the main Obfuscate tool's own dropdown already established
# (_OBFUSCATE_MODE_SECURITY_SUFFIX/_OBFUSCATE_MODE_ORDER,
# editor_window.py) - duplicated as literal strings here rather than
# imported, to avoid a circular import (editor_window.py already
# imports from this module).
_EFFECT_CHOICES = (
    ("Solid Fill (most secure)", ObfuscateMode.SOLID_FILL),
    ("Pixelize (not secure)", ObfuscateMode.PIXELIZE),
    ("Blur (not secure)", ObfuscateMode.BLUR),
    ("Text Highlight", HighlightMode.TEXT_HIGHLIGHT),
    ("Magnification", HighlightMode.MAGNIFICATION),
)

# Matches TextObfuscationForm.Designer.cs's own control defaults
# (pixelSizeUpDown=5, blurRadiusUpDown=5, magnificationUpDown=2,
# paddingHorizontalUpDown=10, paddingVerticalUpDown=20,
# offsetHorizontalUpDown=0, highlightColorButton=Color.Yellow,
# searchScopeComboBox index 0 = Words) - except effect_index 0, which
# is Solid Fill here rather than Windows' own Pixelize default
# (effectComboBox index 0, TextObfuscationForm.cs:79-87) - an explicit,
# requested deviation, not a silently-opinionated one: direflail asked
# for Solid Fill first in the list, and defaulting a fresh search to
# the front-of-list (and now safest) choice is the expected behavior
# for a dropdown, not something to special-case around; solid_fill_color
# defaults to ObfuscateShape's own SOLID_FILL default (opaque black).
#
# offset_vertical is a deliberate deviation from Windows' own default
# (-5, TextObfuscationForm.Designer.cs) - confirmed live against a real
# screenshot that apply_padding's offset *shifts* the whole box rather
# than expanding it, so for a typical short OCR word ("Stewart", raw
# bounds only 13px tall) a fixed 5px upward shift left ~4px of the
# actual glyphs exposed below the box while padding a few extra pixels
# of empty space above instead - visibly incomplete redaction, not a
# subtle rounding difference. Taller text (e.g. a bold headline) barely
# notices the same fixed shift, which is why this only showed up on
# some words and not others. -5 was presumably tuned against Windows'
# own OCR engine's bounds, which may already be looser than Tesseract's
# tighter ones - it doesn't generalize here, so the default is 0
# (still user-adjustable via the spinner, just not clipping by
# default). Imported by editor_window.py to seed EditorWindow.
# _text_obfuscation_settings - always copy it
# (``dict(DEFAULT_TEXT_OBFUSCATION_SETTINGS)``), never assign directly,
# since every EditorWindow instance would otherwise share one mutable
# dict.
DEFAULT_TEXT_OBFUSCATION_SETTINGS = {
    "search_text": "", "use_regex": False, "case_sensitive": False, "scope": SCOPE_WORDS,
    "effect_index": 0, "pixel_size": 5, "blur_radius": 5, "solid_fill_color": (0, 0, 0, 255),
    "highlight_color": (255, 255, 0, 255), "magnification_factor": 2, "padding_horizontal": 10,
    "padding_vertical": 20, "offset_horizontal": 0, "offset_vertical": 0,
}


def _info_dialog(parent, text: str, secondary: str = None, message_type=Gtk.MessageType.INFO) -> None:
    dialog = Gtk.MessageDialog(
        transient_for=parent, message_type=message_type, buttons=Gtk.ButtonsType.OK, text=text,
    )
    if secondary:
        dialog.format_secondary_text(secondary)
    dialog.run()
    dialog.destroy()


def _make_shape(bounds: Rect, mode, settings: dict):
    if mode == ObfuscateMode.SOLID_FILL:
        return ObfuscateShape(bounds=bounds, mode=mode, fill_color=settings["solid_fill_color"])
    if isinstance(mode, ObfuscateMode):
        amount = settings["pixel_size"] if mode == ObfuscateMode.PIXELIZE else settings["blur_radius"]
        return ObfuscateShape(bounds=bounds, mode=mode, amount=amount)
    if mode == HighlightMode.TEXT_HIGHLIGHT:
        return HighlightShape(bounds=bounds, mode=mode, fill_color=settings["highlight_color"])
    return HighlightShape(bounds=bounds, mode=mode, magnification_factor=settings["magnification_factor"])


def do_obfuscate_text(editor) -> None:
    """Entry point wired to the Effects dropdown's "Find & Redact
    Text..." item (see module docstring for the naming rationale) -
    runs OCR (once per editor, cached on editor._ocr_result;
    invalidated by base_image's setter, see its own docstring) then
    opens the search dialog. Faithful to
    ObfuscateTextToolStripMenuItemClick's own message-box gates
    (no OCR provider / no text found), swapped for this port's
    tesseract_available() and OcrResult.has_content.
    """
    if not tesseract_available():
        _info_dialog(
            editor, _DIALOG_TITLE,
            _("Tesseract OCR is not installed. Install the tesseract-ocr package to use this feature."),
            message_type=Gtk.MessageType.WARNING,
        )
        return

    if editor._ocr_result is None:
        window = editor.get_window()
        if window is not None:
            window.set_cursor(Gdk.Cursor.new_from_name(Gdk.Display.get_default(), "wait"))
        while Gtk.events_pending():
            Gtk.main_iteration()
        try:
            editor._ocr_result = run_tesseract_ocr(editor.base_image)
        except Exception as exc:
            _info_dialog(editor, _DIALOG_TITLE, _("OCR failed: {}").format(exc), message_type=Gtk.MessageType.ERROR)
            return
        finally:
            if window is not None:
                window.set_cursor(None)

    if not editor._ocr_result.has_content:
        _info_dialog(editor, _DIALOG_TITLE, _("No text found in this image."))
        return

    _TextObfuscationDialog(editor, editor._ocr_result).run()


class _TextObfuscationDialog:
    def __init__(self, editor, ocr_result: OcrResult):
        self._editor = editor
        self._ocr = ocr_result
        self._settings = editor._text_obfuscation_settings
        self._preview_shapes: list = []
        self._debounce_id = None

        dialog = Gtk.Dialog(title=_DIALOG_TITLE, transient_for=editor)
        dialog.add_buttons(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL, "Apply", Gtk.ResponseType.OK)
        dialog.set_default_size(420, -1)
        self._dialog = dialog

        content = dialog.get_content_area()
        content.set_border_width(12)
        content.set_spacing(8)

        search_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self._search_entry = Gtk.Entry()
        # Deliberately never pre-filled from self._settings["search_text"]
        # (unlike every other field here) - confirmed live this reads as
        # a real bug, not a convenience: reopening the dialog silently
        # re-ran the previous search and repainted its preview boxes,
        # which looked exactly like an undone edit somehow coming back.
        # A fresh search each time avoids that; every other setting
        # (regex/case/scope/effect/colors/padding/offset) still persists,
        # since those read as preferences rather than leftover state.
        self._search_entry.set_placeholder_text(_("Search text (min. 3 characters)..."))
        search_row.pack_start(self._search_entry, True, True, 0)
        content.pack_start(search_row, False, False, 0)

        options_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        self._regex_check = Gtk.CheckButton(label=_("Regex"))
        self._regex_check.set_active(self._settings["use_regex"])
        options_row.pack_start(self._regex_check, False, False, 0)
        self._case_check = Gtk.CheckButton(label=_("Case sensitive"))
        self._case_check.set_active(self._settings["case_sensitive"])
        options_row.pack_start(self._case_check, False, False, 0)
        content.pack_start(options_row, False, False, 0)

        grid = Gtk.Grid(row_spacing=6, column_spacing=6)
        content.pack_start(grid, False, False, 0)
        row = 0

        grid.attach(Gtk.Label(label=_("Search in:"), xalign=0), 0, row, 1, 1)
        self._scope_combo = Gtk.ComboBoxText()
        self._scope_combo.append_text("Words")
        self._scope_combo.append_text("Lines")
        self._scope_combo.set_active(0 if self._settings["scope"] == SCOPE_WORDS else 1)
        grid.attach(self._scope_combo, 1, row, 1, 1)
        row += 1

        grid.attach(Gtk.Label(label=_("Effect:"), xalign=0), 0, row, 1, 1)
        self._effect_combo = Gtk.ComboBoxText()
        for label, _mode in _EFFECT_CHOICES:
            self._effect_combo.append_text(label)
        self._effect_combo.set_active(self._settings["effect_index"])
        grid.attach(self._effect_combo, 1, row, 1, 1)
        row += 1

        self._pixel_size_label = Gtk.Label(label=_("Pixel size:"), xalign=0)
        grid.attach(self._pixel_size_label, 0, row, 1, 1)
        self._pixel_size_spin = Gtk.SpinButton.new_with_range(2, 100, 1)
        self._pixel_size_spin.set_value(self._settings["pixel_size"])
        grid.attach(self._pixel_size_spin, 1, row, 1, 1)
        row += 1

        self._blur_radius_label = Gtk.Label(label=_("Blur radius:"), xalign=0)
        grid.attach(self._blur_radius_label, 0, row, 1, 1)
        self._blur_radius_spin = Gtk.SpinButton.new_with_range(1, 30, 1)
        self._blur_radius_spin.set_value(self._settings["blur_radius"])
        grid.attach(self._blur_radius_spin, 1, row, 1, 1)
        row += 1

        self._solid_fill_color_label = Gtk.Label(label=_("Fill color:"), xalign=0)
        grid.attach(self._solid_fill_color_label, 0, row, 1, 1)
        self._solid_fill_color_button = Gtk.ColorButton()
        self._solid_fill_color_button.set_rgba(_color_to_rgba(self._settings["solid_fill_color"]))
        grid.attach(self._solid_fill_color_button, 1, row, 1, 1)
        row += 1

        self._highlight_color_label = Gtk.Label(label=_("Highlight color:"), xalign=0)
        grid.attach(self._highlight_color_label, 0, row, 1, 1)
        self._highlight_color_button = Gtk.ColorButton()
        self._highlight_color_button.set_rgba(_color_to_rgba(self._settings["highlight_color"]))
        grid.attach(self._highlight_color_button, 1, row, 1, 1)
        row += 1

        self._magnification_label = Gtk.Label(label=_("Magnification:"), xalign=0)
        grid.attach(self._magnification_label, 0, row, 1, 1)
        self._magnification_spin = Gtk.SpinButton.new_with_range(2, 8, 1)
        self._magnification_spin.set_value(self._settings["magnification_factor"])
        grid.attach(self._magnification_spin, 1, row, 1, 1)
        row += 1

        grid.attach(Gtk.Label(label=_("Padding horizontal %:"), xalign=0), 0, row, 1, 1)
        self._padding_h_spin = Gtk.SpinButton.new_with_range(0, 200, 1)
        self._padding_h_spin.set_value(self._settings["padding_horizontal"])
        grid.attach(self._padding_h_spin, 1, row, 1, 1)
        row += 1

        grid.attach(Gtk.Label(label=_("Padding vertical %:"), xalign=0), 0, row, 1, 1)
        self._padding_v_spin = Gtk.SpinButton.new_with_range(0, 200, 1)
        self._padding_v_spin.set_value(self._settings["padding_vertical"])
        grid.attach(self._padding_v_spin, 1, row, 1, 1)
        row += 1

        grid.attach(Gtk.Label(label=_("Offset horizontal:"), xalign=0), 0, row, 1, 1)
        self._offset_h_spin = Gtk.SpinButton.new_with_range(-100, 100, 1)
        self._offset_h_spin.set_value(self._settings["offset_horizontal"])
        grid.attach(self._offset_h_spin, 1, row, 1, 1)
        row += 1

        grid.attach(Gtk.Label(label=_("Offset vertical:"), xalign=0), 0, row, 1, 1)
        self._offset_v_spin = Gtk.SpinButton.new_with_range(-100, 100, 1)
        self._offset_v_spin.set_value(self._settings["offset_vertical"])
        grid.attach(self._offset_v_spin, 1, row, 1, 1)
        row += 1

        self._match_count_label = Gtk.Label(label=_("0 matches"), xalign=0)
        content.pack_start(self._match_count_label, False, False, 0)

        for widget, signal in (
            (self._search_entry, "changed"), (self._regex_check, "toggled"), (self._case_check, "toggled"),
            (self._scope_combo, "changed"), (self._pixel_size_spin, "value-changed"),
            (self._blur_radius_spin, "value-changed"), (self._solid_fill_color_button, "color-set"),
            (self._highlight_color_button, "color-set"),
            (self._magnification_spin, "value-changed"), (self._padding_h_spin, "value-changed"),
            (self._padding_v_spin, "value-changed"), (self._offset_h_spin, "value-changed"),
            (self._offset_v_spin, "value-changed"),
        ):
            widget.connect(signal, lambda *_a: self._schedule_preview())
        self._effect_combo.connect("changed", self._on_effect_changed)

        self._on_effect_changed(self._effect_combo)
        dialog.show_all()
        self._update_effect_field_visibility()
        self._update_preview()

    def _current_effect_mode(self):
        return _EFFECT_CHOICES[self._effect_combo.get_active()][1]

    def _on_effect_changed(self, _combo) -> None:
        self._update_effect_field_visibility()
        self._schedule_preview()

    def _update_effect_field_visibility(self) -> None:
        mode = self._current_effect_mode()
        self._pixel_size_label.set_visible(mode == ObfuscateMode.PIXELIZE)
        self._pixel_size_spin.set_visible(mode == ObfuscateMode.PIXELIZE)
        self._blur_radius_label.set_visible(mode == ObfuscateMode.BLUR)
        self._blur_radius_spin.set_visible(mode == ObfuscateMode.BLUR)
        self._solid_fill_color_label.set_visible(mode == ObfuscateMode.SOLID_FILL)
        self._solid_fill_color_button.set_visible(mode == ObfuscateMode.SOLID_FILL)
        self._highlight_color_label.set_visible(mode == HighlightMode.TEXT_HIGHLIGHT)
        self._highlight_color_button.set_visible(mode == HighlightMode.TEXT_HIGHLIGHT)
        self._magnification_label.set_visible(mode == HighlightMode.MAGNIFICATION)
        self._magnification_spin.set_visible(mode == HighlightMode.MAGNIFICATION)

    def _schedule_preview(self) -> None:
        if self._debounce_id is not None:
            GLib.source_remove(self._debounce_id)
        self._debounce_id = GLib.timeout_add(_DEBOUNCE_MS, self._debounced_update_preview)

    def _debounced_update_preview(self) -> bool:
        self._debounce_id = None
        self._update_preview()
        return False

    def _read_settings(self) -> dict:
        return {
            "search_text": self._search_entry.get_text(), "use_regex": self._regex_check.get_active(),
            "case_sensitive": self._case_check.get_active(),
            "scope": SCOPE_WORDS if self._scope_combo.get_active() == 0 else SCOPE_LINES,
            "effect_index": self._effect_combo.get_active(), "pixel_size": int(self._pixel_size_spin.get_value()),
            "blur_radius": int(self._blur_radius_spin.get_value()),
            "solid_fill_color": _rgba_to_color(self._solid_fill_color_button.get_rgba()),
            "highlight_color": _rgba_to_color(self._highlight_color_button.get_rgba()),
            "magnification_factor": int(self._magnification_spin.get_value()),
            "padding_horizontal": int(self._padding_h_spin.get_value()),
            "padding_vertical": int(self._padding_v_spin.get_value()),
            "offset_horizontal": int(self._offset_h_spin.get_value()),
            "offset_vertical": int(self._offset_v_spin.get_value()),
        }

    def _clear_preview(self) -> None:
        for shape in self._preview_shapes:
            self._editor.layer.remove(shape)
        self._preview_shapes = []

    def _update_preview(self) -> None:
        self._clear_preview()
        settings = self._read_settings()
        matches = find_matches(
            self._ocr, settings["search_text"], use_regex=settings["use_regex"],
            case_sensitive=settings["case_sensitive"], scope=settings["scope"],
            padding_horizontal=settings["padding_horizontal"], padding_vertical=settings["padding_vertical"],
            offset_horizontal=settings["offset_horizontal"], offset_vertical=settings["offset_vertical"],
        )
        mode = self._current_effect_mode()
        for bounds in matches:
            shape = _make_shape(bounds, mode, settings)
            self._editor.layer.add(shape)
            self._preview_shapes.append(shape)
        match_count = len(matches)
        self._match_count_label.set_text(ngettext("{} match", "{} matches", match_count).format(match_count))
        self._editor._drawing_area.queue_draw()

    def run(self) -> None:
        try:
            response = self._dialog.run()
        finally:
            if self._debounce_id is not None:
                GLib.source_remove(self._debounce_id)

        if response == Gtk.ResponseType.OK and self._preview_shapes:
            # Already in the layer from the last preview update -
            # committing just means making that addition undoable,
            # matching TextObfuscationForm.ApplyButton_Click's own
            # "clear the preview containers, then re-add the same
            # matches for real" (TextObfuscationForm.cs:344-368),
            # collapsed here since our preview shapes already *are*
            # the real ones.
            self._settings.update(self._read_settings())
            self._editor.undo_redo.push(
                CompositeMemento([AddElementMemento(self._editor.layer, s) for s in self._preview_shapes])
            )
        else:
            self._clear_preview()
        self._editor._drawing_area.queue_draw()
        self._dialog.destroy()


def _rgba_to_color(rgba: Gdk.RGBA):
    return (round(rgba.red * 255), round(rgba.green * 255), round(rgba.blue * 255), round(rgba.alpha * 255))


def _color_to_rgba(color) -> Gdk.RGBA:
    r, g, b, a = color
    rgba = Gdk.RGBA()
    rgba.red, rgba.green, rgba.blue, rgba.alpha = r / 255, g / 255, b / 255, a / 255
    return rgba
