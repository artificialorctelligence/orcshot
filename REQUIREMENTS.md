# Greenshot Linux — Requirements

A Linux Mint (Cinnamon) port of [Greenshot](https://getgreenshot.org/), rebuilt from scratch as a
faithful behavioral port — not a literal code port. The original Windows source
(`/home/greenshotlinux/projects/Greenshot/greenshot`, C#/.NET/WinForms) is the reference for feature
behavior and defaults, but no code is shared; everything here is a new Python implementation.

## Platform priority

1. **X11 — primary target.** Everything is built and tested against X11 first.
2. **Wayland — secondary.** Deferred until X11 is solid. Capture and hotkeys work fundamentally
   differently under Wayland (portal/DBus-mediated, no direct capture, no standard global-hotkey
   API), so this is treated as a distinct phase of work, not a variant of the X11 implementation.

## Technology stack

- **Python + GTK (PyGObject).** Chosen over .NET+Avalonia and C++/Qt for ecosystem maturity on
  both X11 and Wayland (see decision log below) and over literal C# reuse because the reusable
  slice of the Windows source (filter math, undo model) was judged too small to justify a
  cross-language interop boundary, especially under a strict-TDD requirement.
- **GTK3**, not GTK4. Decision, open to revisiting: Cinnamon's own shell is still GTK3-based, so a
  GTK3 app integrates natively into Mint's look and feel without libadwaita-style theming
  mismatches. GTK3's PyGObject tooling/examples are also more mature for the kind of thing this
  app needs most (transparent full-screen selection overlays).
- **Test framework: pytest** (decision, not yet discussed with user in depth — flag if you want
  something else, e.g. `unittest`).

## Architecture

**Strict TDD is a hard requirement.** Every feature is written test-first. This drives an
important architectural consequence: platform-specific operations (screen capture, clipboard,
global hotkeys, tray icon) must sit behind narrow interfaces with fake/in-memory implementations
usable in tests, so the bulk of the app (drawing model, filters, undo/redo, annotation logic) can
be unit tested headless with no X server required.

- Decision: **ports-and-adapters from day one**, not "hardcode X11 now, refactor later." Define
  `CaptureBackend`, `ClipboardBackend`, `HotkeyManager` interfaces immediately; ship the X11
  adapter first; leave Wayland as a stub/future adapter. Keeps the TDD loop clean and avoids a
  rewrite when Wayland work starts.
- The app runs as a persistent background process with a tray icon (like the Windows version),
  not a launch-per-capture CLI tool.

## Feature scope

### Capture modes
- Region select
- Full screen
- Active window
- Window picker
- Last region (repeat)

**Status: Region select is done** (`src/greenshot_linux/ui/region_select.py`,
`RegionSelectWindow`/`start_region_capture`) — the actual click-and-drag trigger for a real capture
flow, launching `EditorWindow` on whatever gets selected. A fullscreen, borderless overlay shows a
frozen copy of the desktop (grabbed once up front, so the backdrop can't drift from what's actually
captured mid-drag, and cropped from that same frozen copy rather than re-grabbing); dragging shows a
live selection rectangle with everything outside it dimmed (even-odd fill rule "hole", not clip-
region combination); releasing crops and opens the editor; Escape cancels.

**Full screen and Active window are also done.** `src/greenshot_linux/capture/modes.py` holds the
pure "which Rect to grab" logic (`full_screen_region`, `active_window_region`), unit tested against
`FakeCaptureBackend`/`FakeWindowEnumerator` — `active_window_region` clamps the focused window's
reported bounds to the virtual screen (a window can extend slightly past it, e.g. after being
dragged partway off-screen) and returns `None` if there's no focused window or it's entirely
off-screen. `src/greenshot_linux/ui/capture_modes.py` is the thin grab-then-launch-`EditorWindow`
glue on top, wired into `app.py`'s `--capture-full-screen`/`--capture-active-window` CLI options and
tray menu. Verified live: routed both through the real single-instance app (a second process
correctly reached the running instance's handler, same as `--capture-region`), and ran both for
real, checking only `image.shape` against the expected dimensions — deliberately never rendering the
captured content for inspection, since a full-screen/active-window grab necessarily contains
whatever's really on screen right now.

**Window picker is also done** (`src/greenshot_linux/ui/window_picker.py`, `WindowPickerWindow`/
`start_window_picker`) — same frozen-backdrop overlay technique as Region select, but highlighting
whichever window is under the cursor (dimming everything else) instead of a free-form drag
rectangle, and capturing that window on click. Wired into `app.py`'s `--capture-window-picker` CLI
option and tray menu ("Capture Window...").

**Found and fixed a real Z-order bug building this**, caught by a mix of live testing and the
user directly watching their own screen during a manual test: on a desktop with several maximized
windows sharing one monitor (Brave, GitKraken, Proton Mail, Spotify all at the same bounds below
Brave's tab bar), hovering the *shared/occluded* region picked whichever window happened to be
last in `X11WindowEnumerator.list_windows()`'s order — which was reading `_NET_CLIENT_LIST`, an
EWMH property with **no stacking-order guarantee** (commonly just initial-mapping order) — not
whichever window was actually visible on top. The visible symptom: hovering Brave's page content
highlighted a box that stopped short at the tab bar (matching an occluded window's smaller bounds,
since only Brave's own bounds extend up to y=0), then jumped to a full-window box the moment the
cursor crossed into the tab-bar strip where only Brave's bounds applied at all. Root-caused by
cross-checking against `xprop -root _NET_CLIENT_LIST_STACKING` (which *does* return true
bottom-to-top order) and confirming the active window landed second in the old property's order,
not last. Fixed in `capture/x11_window.py` by reading `_NET_CLIENT_LIST_STACKING` (falling back to
`_NET_CLIENT_LIST` if a WM doesn't advertise it); the picker's own "last matching window wins"
logic didn't need to change, since it was already correct *given* a properly bottom-to-top-ordered
list. Regression-guarded by `test_window_enumerator_contract.py`'s
`test_active_window_is_last_in_list_windows_stacking_order`, run against both the fake and the real
X11 adapter — confirmed red against the old property, green after the fix. Re-verified live
afterward: hovering both the tab-bar strip and the content area of Brave now consistently resolve
to Brave, no more box-jumping.

**Last region (repeat) is also done.** `GreenshotApplication.last_region` (`app.py`) tracks the
absolute `Rect` from whichever capture mode ran most recently — every `start_*_capture` wires its
launch function's new `on_captured(absolute_rect)` callback (threaded through `region_select.py`,
`window_picker.py`, `capture_modes.py`) to `_remember_region`. `ui/capture_modes.py`'s
`start_last_region_capture(last_region, capture_backend=None)` re-grabs that region *fresh* — not
cached pixels, matching the Windows source's Shift+PrintScreen semantics of repeating the same
spatial region and picking up whatever's there now — clamping to the current screen layout in case
it no longer fully fits (e.g. a monitor was disconnected since). Wired into `app.py`'s
`--capture-last-region` CLI option and a "Repeat Last Region" tray item that's disabled until
something's actually been captured. Verified live: confirmed `last_region` updates after a capture
and the tray item's sensitivity flips accordingly, a real end-to-end grab-the-same-region-twice
check, and the CLI option routing through the single-instance app the same way as the other modes.

All five capture modes from the original requirements list are now done.

**Multi-monitor lesson learned building this:** a normal `Gtk.WindowType.TOPLEVEL` window's
requested size gets clamped by the window manager to a single monitor's work area — confirmed
empirically here, where a 4480×1440 (two-monitor) request came back 4480×1040 under
Cinnamon/Muffin, silently cutting off the bottom of the taller monitor. `Gtk.WindowType.POPUP`
(X11 override-redirect) bypasses window-manager placement/sizing entirely and was used instead,
giving exact geometry across the whole virtual screen — the standard technique other screenshot
tools use for this kind of overlay, not something to rediscover per-adapter later.

### Annotation tools (faithful port of `Greenshot.Editor/Drawing`)
Rectangle, Ellipse, Line, Arrow, Freehand, Text, Speech bubble, Step-number labels, Highlight,
Icon/stamp, Crop, Cursor overlay, embedded Image, embedded SVG, Blur filter, Pixelize filter.

**Status: all ported at the pure-data-model level** (`src/greenshot_linux/core/shapes.py`,
`drawing.py`, `filters.py`, `crop.py`), TDD throughout. See individual module docstrings for
scoped-out rendering details (GDI+ Bezier smoothing, exact stroked-path geometry, font
measurement) — each is a rendering-layer concern, not a data-model gap.

**Cairo rendering (`src/greenshot_linux/ui/render.py`): done for every shape type** — Rectangle,
Ellipse, Line, Arrow, Freehand, Text, Speech bubble, Step-number labels, Icon/stamp, Cursor
overlay, embedded Image, embedded SVG, and Obfuscate (Blur/Pixelize) — including the ported
`DrawShadow` algorithm (5-step diagonal drop shadow). Headless tests draw to an in-memory
`cairo.ImageSurface` and assert on pixels — no X server needed. `render_shape`'s
`NotImplementedError` branch now exists only as a fallback for a genuinely unrecognized shape type,
not a marker for missing work. Notable deliberate simplifications, each documented in `render.py`
itself:
- Arrow only draws a single end-point arrowhead (`ArrowShape` has no field for the other head
  combinations, matching `ArrowContainer`'s default), with a simplified triangle shape standing in
  for GDI+'s `AdjustableArrowCap` geometry.
- Text/StepLabel/SpeechBubble are laid out via Pango/PangoCairo (Cairo's own toy text API has no
  word-wrap or font-family/style resolution); StepLabel's auto-scaled font size skips the source's
  measured-text aspect-ratio correction (font_size = 0.7 × min(width, height) flat).
- SpeechBubble's tail border skips GDI+'s clip-region trick (tail drawn first, bubble drawn on top
  instead) and uses the same 0-4px shadow-offset convention as every other shape rather than the
  source's own 1-5px cumulative-transform quirk.
- `ImageShape`'s shadow tints its own RGB to black (keeping its alpha as the silhouette) rather
  than reproducing the source's separate `_shadowBitmap` generation.
- Svg rendering uses librsvg's `render_document(ctx, viewport)` directly, no intermediate cached
  bitmap the way `VectorGraphicsContainer` keeps one.

`ObfuscateShape` (`core/shapes.py`) is architecturally different from every other shape: it has no
visual content of its own, so rendering it means re-running `filters.py`'s `box_blur`/`pixelize`
against the region of the *original captured image* under its bounds, every frame — not caching a
filtered patch and dragging that around. `render_shape`/`render_layer` take an optional
`base_image` parameter for this (unused by every other shape; raises a clear `ValueError` if an
`ObfuscateShape` is rendered without one). Verified live: moving a pixelize/blur box reveals a
freshly-filtered version of whatever's now underneath it, matching the source's per-frame
`Apply()` semantics rather than a static drag.

**Live editor window (`src/greenshot_linux/ui/editor_window.py`): create + select/move + resize +
toolbar + text entry, for Rectangle/Ellipse/Line/Arrow/Freehand/Pixelize/Blur/Text.** `EditorWindow`
shows a captured image, renders the `Layer` on top every frame, and wires:
- A `Gtk.Toolbar` of radio buttons for tool selection, plus Undo/Redo/Copy/Save/Print buttons —
  kept in sync with number keys 1-8, which still work as accelerators for the same tools. Icon-only
  (`Gtk.ToolbarStyle.ICONS`) with tooltips, paint/Photoshop-style rather than text labels — see
  **Toolbar icons** below
- Mouse drag on empty space to create a shape in the current tool (`AddElementMemento`), which also
  selects the new shape — except Text, see below
- Clicking an existing shape (via `Layer.topmost_at`, so hollow shapes are only grabbable near
  their outline, filled ones anywhere inside — faithful to the ported `ClickableAt` semantics)
  selects it (persists across clicks, drawing small square handles at its corners/edges, or its two
  endpoints for Line/Arrow) and starts dragging it (`ElementChangeMemento`)
- Dragging one of those handles instead resizes/reshapes the shape (also `ElementChangeMemento`);
  corner handles move both adjacent edges, edge-midpoint handles move just one. Only shapes with a
  plain `bounds` field (Rectangle/Ellipse/Obfuscate/Text) or a start/end pair (Line/Arrow) have
  handles — `core/tools.py`'s `shape_handles` returns `{}` for the rest, so they're just not
  resizable yet.
- Ctrl+Z/Ctrl+Y (and the toolbar buttons) for undo/redo across all of the above; both clear the
  current selection afterward, since a memento can change any shape in the layer, not necessarily
  the selected one — keeping a stale selection would show handles that don't match what's drawn
- The Text tool drags out a box, then enters a type-directly-onto-the-canvas editing mode (no
  GtkEntry overlay — the shape just re-renders live through the normal Cairo pipeline on every
  keystroke). Enter commits; Escape or committing with empty text discards the shape instead. Every
  other key handler (tool switching, undo/redo, copy/save/print) is suppressed while editing, and
  clicking elsewhere or using a toolbar button commits first. There's still no visible text
  cursor/caret (the live-updating text is the only feedback).
- **Double-clicking an existing `TextShape` re-enters editing mode on it too.** GTK fires a normal
  single-click press before a double-click's second press, so the first press already runs the
  ordinary select-and-start-moving branch — the double-click branch explicitly cancels that
  in-progress move first. `self._editing_original_shape` (`None` for a brand-new shape, the pre-edit
  instance for a re-edit) drives which memento a commit/cancel produces: a brand-new shape's
  cancel/empty-commit just discards it (nothing was ever added to undo history); a re-edit's cancel
  reverts the text with nothing to undo either, but committing pushes `ElementChangeMemento`
  (non-empty) or `DeleteElementMemento` (emptied out) instead of `AddElementMemento`, since the
  shape already existed in committed history. A related fix found while tracing through this: a
  click that ends without any drag (dx=dy=0 — e.g. plain single-click selection, or the first press
  of what becomes a double-click) no longer pushes a no-op move `ElementChangeMemento` cluttering
  undo history. Verified live: created "Hello", double-clicked it, appended " World", committed,
  confirmed one shape (not a duplicate) reading "Hello World"; undid back to "Hello"
  (`ElementChangeMemento` working); re-edited again, cleared all the text, committed, confirmed the
  shape was deleted; undid that deletion and confirmed "Hello" came back (`DeleteElementMemento`
  working).

The shape-selection/move/resize logic (`create_shape_from_drag`, `create_freehand_shape`,
`translate_shape`, `shape_handles`, `handle_at`, `resize_shape`) lives in
`src/greenshot_linux/core/tools.py`, kept pure and unit tested (including a Hypothesis property
test that translation composes additively) even though the window itself isn't. Verified against a
real on-screen window and X11 screenshots at each interaction stage: create each shape type
(including pixelize/blur on a high-contrast test pattern, and Text/SpeechBubble/StepLabel/
Icon/Cursor/Image/Svg rendered directly into a Layer), select-and-move, drag a resize handle, click
the toolbar's Undo button, undo a move back to its original position, type into a new Text shape
and commit it, cancel one with Escape, confirm an empty-text commit discards the shape rather than
leaving a blank box in the layer, and change the style panel's line/fill color and thickness
controls then confirmed the *next* shape drawn picked up the new style. A second toolbar row
(`Gtk.ColorButton` ×2 with alpha enabled, a thickness `Gtk.SpinButton`, a shadow `Gtk.CheckButton`)
updates `self._default_style` via `dataclasses.replace` on each change.

**Restyling an already-placed shape is also done**: if a shape is selected when a style-panel
control changes, it's restyled too (one `ElementChangeMemento` per control change,
`hasattr(shape, "style")`-gated so Obfuscate/Icon/Cursor/Image/Svg — none of which have line/fill
styling — are silently skipped rather than erroring). The panel doesn't sync the other direction
though: selecting a shape doesn't update the controls to reflect *its* current style, only editing
them pushes a change out. Verified live: drew a rectangle, changed its line color via the panel,
confirmed it restyled in place (not duplicated) with the panel's own swatch updating, then undid the
change and confirmed the shape reverted to its original color.

**Obfuscation-amount (blur radius / pixel size) control is also done.** A separate spinner
("Obfuscate Amount") tracks `self._default_obfuscate_amount` (`ShapeStyle` has no field for this —
`ObfuscateShape.amount` is a different concept entirely) and works the same way as the style
controls: affects shapes created afterward, and retroactively updates a selected `ObfuscateShape`.
`core/tools.py`'s `create_shape_from_drag` grew an `amount: int = 5` parameter (matching
`ObfuscateShape`'s own default) that every tool accepts and ignores except Pixelize/Blur, so
`EditorWindow` can pass it unconditionally on every call rather than branching on the current tool
first. Verified live on a high-contrast checkerboard test pattern: drew a Pixelize shape at
amount=5 (fine grain), retroactively changed the same selected shape to amount=30 and confirmed it
visibly went coarse in place, then drew a second shape and confirmed it picked up the new default
(both now equally coarse).

**Resize now covers every shape type with a renderer** — the remaining gap (Freehand/SpeechBubble/
StepLabel/Icon/Cursor/Image/Svg) is closed. `core/tools.py`'s `_BOUNDS_RESIZABLE` tuple grew to
include StepLabel/Icon/Cursor/Image/Svg (each has a genuine, settable `bounds` field, so the
existing generic branch just worked). Two shape types needed their own logic because their
`.bounds` (the `Drawable`-protocol property `Layer` uses for z-order aggregation) isn't a plain
field:
- `SpeechBubbleShape`: `.bounds` unions `bubble_bounds` with the tail's own extent — a *wider* rect
  than what the resize handles should track. Handles/resize now target `bubble_bounds` directly;
  `translate_shape` (move) shifts `target` by the same delta so the tail keeps pointing the same
  *relative* direction, while `resize_shape` leaves `target` untouched so the tail's *aim point*
  stays fixed and just gets re-angled/re-lengthed to reach it — verified live: dragged a bubble's
  corner handle, confirmed `bubble_bounds` changed and `target` didn't move.
- `FreehandShape`: no bounds field at all (`.bounds` is a computed tight bounding box of its point
  tuple). Resizing scales every point proportionally from the old tight bbox into the new one
  (`_scale_points`) — the natural generalization of "resize" for a point cloud, verified both by a
  hand-traced unit test (dragging one corner while the opposite one stays anchored) and live: drew
  a zigzag stroke, dragged its corner handle, confirmed the shape scaled up while staying
  recognizably the same zigzag.

**Toolbar icons — done** (`src/greenshot_linux/ui/icons.py`, requested explicitly to make the
toolbar look more like a real paint/Photoshop-style tool palette instead of text buttons, matching
what Windows Greenshot's own toolbar already looks like — not a requirement to skin the *whole app*
like Windows, which was explicitly discussed and ruled out in favor of native GTK theming). Two
different sources, since no icon theme has standardized names for annotation tools:
- The eight drawing-tool icons are small Cairo-drawn icons, and where a tool already has a real
  renderer (Rectangle/Ellipse/Line/Arrow/Freehand — see `ui/render.py`), its icon reuses that exact
  `render_*` function on a miniature shape, so the icon can never visually drift from what the tool
  actually draws. Pixelize/Blur have no small-scale renderer to reuse (obfuscation needs a base
  image to filter against), so those are hand-drawn directly as a small checkerboard and a few
  soft-alpha circles respectively — deliberately colorful, since they stand for image content, not
  themed line art (see the color bug below). Text has no small-scale Pango layout worth reusing for
  a single glyph, so it's hand-drawn as a bold "A" too, but *is* themed like the other line art.
  Headless-tested (every tool has a builder, every icon draws something non-transparent, no two
  tools' icons are pixel-identical — a cheap guard against a copy-paste bug).
- The five generic action buttons (Undo/Redo/Copy/Save/Print) use standard freedesktop theme icon
  names (`edit-undo-symbolic` etc.) instead — confirmed present via `Gtk.IconTheme.has_icon` on this
  machine before relying on them. Being theme icons rather than anything hardcoded, they (like
  everything else in this app - see the dark/light theme discussion above) automatically follow
  whatever icon theme and light/dark mode the user has set, with no extra work.

Toolbar switched from `Gtk.ToolbarStyle.TEXT` to `ICONS` with tooltips holding the labels instead.
Verified live: full toolbar screenshot showing all 13 icons rendering distinctly and legibly.

**Bug fixed after initial ship, reported live via screenshot**: the six line-art icons
(Rectangle/Ellipse/Line/Arrow/Freehand/Text) hardcoded a fixed dark-gray line color, so they were
nearly invisible against Cinnamon's dark "Mint-Y-Dark-Blue" toolbar theme, while the five
freedesktop-icon action buttons correctly auto-followed the theme — an inconsistency the user
caught immediately ("these should all be white... in the light theme these should be black"). This
contradicted an earlier claim in this doc that the app "automatically follows the system theme" —
true for standard GTK widgets and theme icon names, but not for raw Cairo-drawn content, which
needs to explicitly query and apply the theme color itself. Fixed by giving `tool_icon_surface`/
`tool_icon_image` a `color` parameter (default a plain dark gray, for any caller that doesn't care)
threaded through the six line-art builders; Pixelize/Blur ignore it, since forcing their content to
a single theme color would defeat their purpose. `editor_window.py`'s `_build_toolbar()` queries
`self.get_style_context().get_color(Gtk.StateFlags.NORMAL)` — confirmed empirically to resolve the
correct theme foreground color even before `show_all()`/realization — converts it to the app's
`(r,g,b,a)` tuple via the existing `_rgba_to_color` helper, and passes it through. While fixing
this, also found and fixed a related but distinct issue in the "A" icon specifically: Cairo's toy
text API (`show_text`) was inheriting the system's subpixel/LCD glyph antialiasing, leaving a faint
RGB fringe around the glyph at 24px — invisible at 1x but visible zoomed. Glyph antialiasing is
controlled by `cairo_font_options_t`, not `ctx.set_antialias()`, so the fix sets
`ANTIALIAS_GRAY` via `ctx.get_font_options()`/`set_font_options()`. (The real Text tool, which uses
PangoCairo rather than Cairo's toy API, was never affected.) Verified live: an editor window populated with synthetic image content (not a grab of the real
desktop), captured to just the window's own on-screen bounds, with raw pixel sampling confirming
the six line-art icons now render at the exact theme foreground color with no stray fringe pixels.

**Bug fixed after initial ship, reported live**: for a capture smaller than the toolbar's natural
width, the drawing area (packed with `fill=True`, so `Gtk.Box` stretches it to match the toolbar's
width) ended up wider than the image, and the image was drawn pinned to its top-left corner instead
of centered - leaving a lopsided gap on the right (and below, for a short capture). Fixed by adding
`EditorWindow._content_offset()` (half the leftover width/height, floored at 0) and applying it as a
Cairo translate in `_on_draw` plus subtracting it from raw event coordinates in
`_on_button_press`/`_on_motion`/`_on_button_release` - both the drawing and all hit-testing/shape-
creation now agree on where the image actually is, not just the drawing. Verified live (visual
centering) and via a simulated click/drag confirming the resulting shape's bounds land at the
correct image-local coordinates despite the widget-local click coordinates being offset.

### Undo/redo
**Status: done at the pure-data-model level** (`src/greenshot_linux/core/history.py`) — a generic
`UndoRedoStack` engine plus mementos over `Layer` (add/delete/change an element, batched as one
step via `CompositeMemento`). Faithful port of Greenshot's `IMemento`/`Surface.Undo/Redo`, with one
deliberate architectural simplification: three Windows memento types (bounds-change, field-change,
text-change) collapse into one `ElementChangeMemento`, since all three reduce to "swap the
immutable shape instance" once shapes are frozen dataclasses. **Now wired into `EditorWindow`** for
adding shapes (Ctrl+Z/Ctrl+Y) — see the Cairo rendering / live editor window notes above.
`ElementChangeMemento` now has three callers in `EditorWindow` — move, resize, and restyle (see the
Cairo rendering / live editor window notes above). `CompositeMemento` (batched ops) has no caller
yet — nothing in the UI performs a multi-shape action as a single undo step.

### Export
- Copy to clipboard
- Save to file
- **Basic print** (send bitmap to a printer via the OS print dialog — easy on GTK via
  `Gtk.PrintOperation`/CUPS, in scope for initial build)

**Status: all three — copy to clipboard, save to file, and basic print — are done and wired into
`EditorWindow`.**
- `src/greenshot_linux/ui/composite.py`: `composite_to_numpy(base_image, layer)` flattens the base
  image + annotation `Layer` into one final image by reusing the exact same rendering pipeline the
  live editor uses (`numpy_to_cairo_surface` + `render_layer` + `cairo_surface_to_numpy`) — what
  gets exported is pixel-identical to what was on screen, not a second, potentially-diverging path.
- `src/greenshot_linux/ui/gdk_convert.py`: numpy <-> `GdkPixbuf` conversion (headless-testable;
  unlike Cairo's ARGB32, GdkPixbuf's RGB colorspace needs no byte-order swap).
- `src/greenshot_linux/capture/clipboard.py` + `x11_clipboard.py`: ports-and-adapters again, same
  shape as `CaptureBackend` — a `ClipboardBackend` Protocol, a `FakeClipboardBackend`, and a real
  `X11ClipboardBackend` (`Gtk.Clipboard.set_image`, which advertises the standard GDK/GTK image
  targets — the X11 equivalent of the Windows source's `ClipboardFormat.PNG/DIB/BITMAP/DIBV5`;
  DIB/BITMAP/DIBV5 are Windows GDI-specific formats with no X11 analogue, so they aren't
  reproduced). Verified with a **real** in-process X11 clipboard round-trip test (`@pytest.mark.x11`,
  skipped when `DISPLAY` is unset) — not just a fake.
- `src/greenshot_linux/ui/file_export.py`: `save_image_to_file(image, path)`, format inferred from
  the extension via `GdkPixbuf`'s own save types, defaulting to PNG.
- `EditorWindow` wiring: toolbar Copy/Save/Print buttons plus Ctrl+C/Ctrl+S/Ctrl+P. Save uses a real
  `Gtk.FileChooserDialog`; Print uses `src/greenshot_linux/ui/printing.py`'s `print_image()` (a real
  `Gtk.PrintOperation` — scales the image to fit the page, centered — no page setup/multi-page/DPI
  options, "basic print" per the requirement), extracted out of `EditorWindow` so the destination
  picker (see Global activation below) can print a raw, not-yet-annotated capture too, not just
  `EditorWindow`'s own composited image. Verified live: drew a shape, copied it, confirmed the real
  X11 clipboard held the exact expected composited image; saved it through the actual dialog
  (auto-responded via a scheduled `GLib.timeout_add` firing inside the dialog's nested main loop, not
  skipped), confirmed the file on disk matched too; exported print output via
  `Gtk.PrintOperationAction.EXPORT` (the same `draw-page` code path real printing uses, without
  needing a physical printer) to a PDF, rendered that PDF back to an image with `pdftoppm`, and
  visually confirmed the composited content landed centered and correctly scaled on the page.
- **Destination picker** (`src/greenshot_linux/ui/destination_picker.py`, new): every capture now
  shows a `Gtk.Menu` context menu at the pointer instead of unconditionally opening the editor.
  Reading the actual Windows source (`Greenshot.Base/Core/ICoreConfiguration.cs`,
  `Greenshot/Destinations/PickerDestination.cs`) before building this found that Windows' own
  default `OutputDestinations` is `"Picker"` — a destination-choice popup — not "always open the
  editor," which is what this port originally, incorrectly, always did. Item order matches Windows'
  own priority-sorted default (File priority 0, Editor priority 1, Clipboard/Printer priority 2)
  with one deliberate change per explicit user request: Copy to Clipboard is pulled to the very top.
  Final order: Copy to Clipboard, Save, Save As..., Edit, Print. Save/Save As mirror Windows' own
  two-tier save (`FileNoDialog`/`FileDialog`): Save writes silently to the configured output
  directory (see `settings.py` below) with a generated timestamp filename
  (`settings.quick_save_filename`, matching Windows' own `yyyy-MM-dd HH_mm_ss` pattern but dropping
  its `-${title}` suffix — not every capture mode here has a single associated window title);
  Save As opens a file chooser. `region_select.py`, `window_picker.py`, and `capture_modes.py`'s
  three non-interactive triggers all show this picker now instead of constructing `EditorWindow`
  directly. Verified live and via a headless structural check (menu item labels/order, activating
  the Clipboard item against a fake backend) plus an end-to-end sandboxed quick-save write.
  **Bug fixed after initial ship, reported live**: the picker never actually appeared after a real
  capture (region-select worked, then nothing) — root-caused to `Gtk.Menu.popup_at_pointer(None)`,
  which needs to resolve a GDK-known window under the current pointer position to anchor against.
  Right after the full-screen capture overlay closes, the pointer is back over whatever real window
  was underneath it — almost never one this app owns — so that resolution silently fails
  (reproduced directly: `Gtk-CRITICAL "assertion 'GDK_IS_WINDOW (rect_window)' failed"`, menu never
  becomes visible/mapped). Fixed by anchoring to the screen's root window instead (always
  resolvable) via `popup_at_rect` at the raw pointer coordinates from `Gdk.Seat.get_pointer()`,
  confirmed live to actually show now.
- **Configurable save location** (`src/greenshot_linux/settings.py`, new): a plain JSON file at
  `~/.config/greenshot-linux/config.json` (XDG Base Directory spec, same testing approach as
  `autostart.py`'s `.desktop` entry — real file I/O, exercised for real in tests against a temp
  path) holding the output directory the destination picker's silent Save writes to (default
  `~/Pictures/Screenshots`, falling back to `~/Screenshots` if there's no Pictures folder) and the
  first-run-setup-already-ran flag (see Global activation below). `EditorWindow` gained a toolbar
  button (folder icon, end of the toolbar) opening a folder-chooser dialog to view/change it — the
  user explicitly asked for this to be adjustable "in the editor," not just a config file. The
  editor's own pre-existing Save dialog also now starts from this folder.

### Global activation (new requirement, not in original Windows feature parity list but matched
to Windows defaults for familiarity)
Default hotkeys, taken from the Windows source
(`Greenshot.Base/Core/ICoreConfiguration.cs`):

| Hotkey | Action |
|---|---|
| `PrintScreen` | Region capture |
| `Alt+PrintScreen` | Window capture |
| `Ctrl+PrintScreen` | Full-screen capture |
| `Shift+PrintScreen` | Repeat last region |

Plus tray-icon single-click/double-click configurable actions, matching Windows behavior.

**Implementation approach:** rather than the app holding a raw X11 global key grab (which fights
Cinnamon's own default PrtScn binding to its built-in screenshot tool), bind these via Cinnamon's
own keybinding system (`org.cinnamon.desktop.keybindings` in gsettings/dconf), configured
automatically on first run with a one-time user confirmation. This avoids the "arcane
configuration" experience of other Linux screenshot tools while still requiring no manual trip
into Settings.

Autostart on login (`.desktop` autostart entry) so the tray icon is always present, matching
Windows "run at startup" behavior.

**Status: done, including the first-run confirmation flow — all four hotkeys, autostart, and
collision detection are wired up and trigger for real the first time the app is actually run.**
- `src/greenshot_linux/app.py` (`GreenshotApplication`): a `Gtk.Application` with a fixed
  `application_id`, using GIO's built-in single-instance-via-D-Bus behavior — re-running the entry
  point (as a hotkey binding would) gets routed to the already-running instance's
  `do_command_line`/`start_capture()` rather than spawning a duplicate process, verified empirically
  (a probe app run twice from separate OS processes showed both invocations landing in the first
  process's PID) before relying on it. `Gtk.StatusIcon` for the tray icon (Cinnamon still supports
  the legacy XEmbed tray protocol its panel inherited from GNOME2/MATE, unlike pure GNOME Shell) —
  click or the menu's "Capture Region" both call the same `start_capture()` the CLI flag does.
  `do_startup` also calls `ui.first_run_setup.maybe_run_first_run_setup()` (see below). Verified
  live: started the app, confirmed the tray icon builds without error, launched a second process
  with `--capture-region`, and confirmed (via a subclass overriding `start_capture` to log instead
  of opening a real overlay, to avoid needless live desktop interaction) that it landed in the first
  process, not a new one.
- `src/greenshot_linux/autostart.py`: `install_autostart_entry(exec_command, autostart_dir=None)`
  writes a `.desktop` autostart entry (XDG Desktop Entry/Autostart specs), creating
  `$XDG_CONFIG_HOME/autostart/` (default `~/.config/autostart/`) if needed. Unlike
  `hotkey_setup.py`'s gsettings/dconf writes (global session state with no safe way to test without
  touching the live system), a `.desktop` entry is just a plain file, so the actual write is
  exercised for real in tests — against a temp directory, never the real default path.
- `src/greenshot_linux/hotkey_setup.py`: generalized from a single hardcoded PrintScreen binding to
  all four (`DEFAULT_HOTKEYS`, a tuple of `HotkeyBinding(name, binding, cli_flag)` matching the
  table above). `configure_hotkey(backend, name, binding, command)` idempotently adds a Cinnamon
  custom keybinding (`org.cinnamon.desktop.keybindings.custom-keybinding`, the relocatable schema
  backing `/org/cinnamon/desktop/keybindings/custom-keybindings/customN/`); `configure_all_hotkeys`
  does all four at once, with a `skip` set for anything the caller decided not to touch.
  **Collision detection, added because the user asked to be warned before anything gets
  overwritten**: `find_conflicts(backend, binding, ignore_names=...)` scans
  `org.cinnamon.desktop.keybindings.media-keys`'s screenshot-related keys (`area-screenshot`,
  `area-screenshot-clip`, `screenshot`, `screenshot-clip`, `window-screenshot`,
  `window-screenshot-clip` — Cinnamon's own built-in PrtScn-family actions) plus existing custom
  keybindings for anything already bound to a given key combo; `check_all_conflicts` runs that
  across all four defaults at once; `clear_conflict` frees a specific conflicting binding (clearing
  just that one field — a custom keybinding's name/command are left intact, just unbound) without
  deleting whatever it belonged to. This is a deliberate scope boundary, not exhaustive: it only
  checks the schemas realistically likely to hold a PrintScreen-family binding, not every gsettings
  schema on the system. Schema/path layout and the built-in media-keys key names were confirmed by
  reading (not writing) this machine's real Cinnamon settings first — which turned up real, not
  hypothetical, collisions for *all four* target bindings: `Print` was already claimed by a custom
  "Area Screenshot" → `shutter -s` binding, `<Alt>Print` by Cinnamon's own built-in
  `window-screenshot` action, `<Control>Print` by Cinnamon's built-in `screenshot-clip` action, and
  `<Shift>Print` by a custom "Full Screenshot" → `shutter -f` binding.
  **Deliberately still never invoked against the real system by anything in this codebase or its
  tests** — all of the above is fully unit tested against an injectable fake `SettingsBackend`. The
  real `GioSettingsBackend` adapter is written and its schema verified by reading the live system,
  but the only thing in this codebase that ever calls it for real is `ui/first_run_setup.py`, and
  only because a human clicked a real confirmation button in their own running app — never as a
  side effect of building or testing the feature.
- `src/greenshot_linux/ui/first_run_setup.py` (new): the actual first-run confirmation dialog.
  `maybe_run_first_run_setup()` checks `settings.is_first_run_setup_done()` (so it only ever asks
  once — whatever the user chooses, the flag is set either way, matching "one-time") and, if not yet
  run, shows a `Gtk.Dialog` offering to enable autostart and each of the four hotkeys. Each
  conflict-free hotkey defaults to checked; each conflicting one defaults to *unchecked* with the
  conflict named in its own label ("... — overwrite existing custom shortcut 'Area Screenshot'?") —
  checking it is how the user opts into overwriting, matching the explicit request to "ask if we
  want that overwritten." `resolve_hotkey_choices` (pure, in `hotkey_setup.py`) turns the checkbox
  state into a skip-set and a list of conflicts to actually clear; the dialog itself is just thin
  GTK glue calling that plus `configure_all_hotkeys`/`clear_conflict`/`install_autostart_entry`.
  Wired into `app.py`'s `do_startup`, so it fires for real the first time the packaged app actually
  runs — for this dev machine or anyone else who installs it. Verified live end-to-end, fully
  sandboxed (temp `XDG_CONFIG_HOME` + a fake settings backend seeded with the two real conflicts
  above, auto-clicking through both the default-safe path and the opt-in-overwrite path via
  `dialog.response()`), then re-confirmed against this machine's *real* gsettings and
  `~/.config/greenshot-linux/` that nothing real was touched by any of that verification.

### Explicitly cut (not ported)
- Email destination
- Windows 10 OCR / Share integrations
- Cloud plugin destinations (Imgur, Box, Confluence, Dropbox, Jira, Office)
- Metafile (EMF/WMF) container support

### Backlog (deferred, not forgotten)
- OCR-driven "search text and auto-redact" obfuscation feature (would need a Tesseract-based OCR
  substitute for the Windows-only OCR API the original feature depends on)
- Advanced print options: auto-rotate-to-fit, shrink/enlarge-to-fit, center alignment,
  grayscale/monochrome/invert print effects, footer timestamp, "prompt for print options" dialog
- Zoom in the editor - not yet checked against the Windows source for whether/how it behaved there;
  needs that check before implementing, to decide faithful behavior vs. a from-scratch design.

## Packaging

**Decision: `.deb`.** Avoids Flatpak's sandbox tendency to force portal-mediated capture even
under X11, which would fight the direct-X11-access priority. Packaging mechanics (debhelper vs
`dh-virtualenv` vs a PyInstaller-built binary bundled into the `.deb`) not yet worked out — revisit
once the app has enough surface area to package.

## Open questions (not yet decided)

- Exact CI setup — to be established once there's a build worth gating.

## Unverified assumptions

Implemented, believed correct (spec, docs, or code-reading), but not directly observed working
on real hardware. Each entry names a concrete way to close the gap — don't remove an entry until
that's actually been done.

- **HiDPI scale factor in X11 capture** (`capture/x11.py`, `X11CaptureBackend.screen_layout`).
  Multiplies GDK's logical monitor geometry by `scale_factor` to get device pixels, per GDK
  monitor API semantics. This dev machine runs at scale factor 1, so the multiplication is dead
  code in every test run so far. **To verify:** run the test suite (specifically
  `test_backend_contract.py`'s `x11` parametrization) on a HiDPI display, or temporarily force a
  non-1 scale factor via Cinnamon's display settings and re-run `verify_x11.py`-style manual
  capture, confirming captured pixel dimensions match physical framebuffer size, not logical size.

- **Minimized-window detection** (`capture/x11_window.py`, `_NET_WM_STATE_HIDDEN`). Correct per
  the EWMH spec and used by every compliant taskbar, but not observed live: attempting to
  force-trigger it via `wmctrl -b add,hidden` on this desktop's WM (Cinnamon/Muffin) didn't
  actually set the state (minimize isn't a client-settable EWMH toggle the way maximize is — it
  likely needs the ICCCM `WM_CHANGE_STATE` request instead, a different protocol). **To verify:**
  minimize a real window via the Cinnamon UI itself (not a script) and confirm
  `X11WindowEnumerator.active_window()`/`list_windows()` reports `is_minimized=True` for it.

## Licensing

Greenshot (Windows) is GPLv3. This is a derivative work — same name, same feature set, same
design lineage — even though no source code is shared. Recommendation (not yet confirmed with
user): license this repo GPLv3 as well and credit the upstream Greenshot project in the README.
Flag if a different license or a distinct product name is intended instead.
