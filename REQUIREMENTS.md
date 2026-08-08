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

**Magnifier loupe + selection size label — done** (`src/greenshot_linux/core/magnifier.py` for the
pure positioning/sizing math, unit tested; `src/greenshot_linux/ui/magnifier.py` for the Cairo
drawing, headlessly tested like `ui/render.py`). Ported from the Windows source's `CaptureForm.cs`
(`DrawZoom`/`VerifyZoomAnimation`): a circular, nearest-neighbor-zoomed preview of the 25x25px
region around the cursor (diameter = `min(screen_w, screen_h) // 5`, rounded down to a multiple of
4), with a white ring border and a black-on-white precision crosshair marking the exact cursor
pixel (a small gap right at that pixel, not a continuous cross, so it stays visible). Positioned
20px from the cursor, trying Windows' own priority order (bottom-right, bottom-left, top-right,
top-left of the cursor) for whichever quadrant both stays on screen and avoids the in-progress
selection rectangle, falling back to allowing that overlap only if no quadrant can avoid it.
Deliberately skips Windows' fade/slide-in animation for the loupe's appearance - polish, not core
behavior. Also draws a "W x H" label near the cursor once a drag is in progress, matching the
source's `sizeText`. Verified with `FakeCaptureBackend` (a synthetic coordinate-pattern image, no
real X11 grab) and by calling `_on_draw` directly against an offscreen Cairo surface - consistent
with this project's standing caution around not rendering live desktop content for inspection.

**Full-screen aiming crosshair + coordinate tooltip — done**, added per explicit request after
"you replaced my cursor with crosshairs" turned out to be a real Windows feature this port had
missed. Faithful port of `CaptureForm.cs:1154-1182`: before a drag starts (once one's in progress
this is replaced by the selection rect + "W x H" label above, matching the source's own
`if (_mouseDown || ...) {...} else {<crosshair>}` branch), a dotted `LightSeaGreen` (`#20B2AA`)
line spans the full screen width and height through the cursor, plus a small `SeaGreen` (`#2E8B57`)
-bordered "X x Y" coordinate tooltip on a light-mint background just past the cursor. Coordinates
shown are absolute screen position, matching WinForms' `Cursor.Position` being screen-space rather
than form-relative. Deliberately *not* added to `window_picker.py`: `CaptureForm.cs` is nominally
one shared class across capture modes, but this exact branch's own gating condition
(`!(_mouseDown || _captureMode == CaptureMode.Window || IsAnimating(_windowAnimator))`) explicitly
excludes `CaptureMode.Window` - real Windows never shows this crosshair during window-picker-style
capture either, so giving it to `window_picker.py` too would have been a deviation, not the
"share it like Windows does" the user actually asked for. Verified with `FakeCaptureBackend`
(synthetic image) and `_on_draw` called directly against an offscreen surface: no crash before any
mouse movement (`_cursor_pos` still `None`); both crosshair lines and the coordinate tooltip render
once the cursor moves; the crosshair correctly disappears the moment a drag starts.

**Initially missed one piece: the real OS cursor icon itself, since fixed.** User feedback from
actually using real Windows Greenshot the same day caught this - the drawn guide lines above aren't
the whole picture. `CaptureForm.Designer.cs:61` (the designer-generated half, not the hand-written
`.cs` logic already checked) sets `this.Cursor = Cursors.Cross` for the whole capture form: the real
mouse pointer itself becomes a crosshair icon for the entire selection gesture, on top of (not
instead of) the drawn lines. Fixed in `start_region_capture` (`ui/region_select.py`) by setting the
`RegionSelectWindow`'s `GdkWindow` cursor to `Gdk.CursorType.CROSSHAIR` right after `show_all()` -
the same underlying X cursor-font glyph (`XC_crosshair`, index 34) `Cursors.Cross` maps to on
Windows. Verified live against a synthetic-content window (`FakeCaptureBackend`, no real desktop
capture): `window.get_window().get_cursor().get_cursor_type() == Gdk.CursorType.CROSSHAIR`, raw
value `34`, confirming the real glyph was actually applied, not just that the call didn't raise.

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

**Cursor auto-capture — done, faithfully replicating Windows including its tray-menu-vs-hotkey
asymmetry.** Windows samples the mouse cursor via Win32 `GetCursorInfo`/`GetIconInfo`
(`WindowCapture.CaptureCursor`, `Greenshot.Base/Core/WindowCapture.cs:81-101`); this port uses the
X11 XFixes extension's `GetCursorImage` request instead (`capture/x11_cursor.py`, via `python-xlib`
— already a project dependency), the direct protocol equivalent. Confirmed live against this
machine's own real mouse pointer icon (never desktop content — just the small cursor bitmap, same
precedent as the earlier Flatpak-detection live queries): pixel format is 32-bit premultiplied
ARGB with alpha in the top byte, matching Cairo's own layout exactly — an opaque black cursor pixel
round-tripped as `0xff000000` exactly as expected. Un-premultiplied on the way into this codebase's
numpy RGBA arrays, since every other image source here synthesizes full opacity and this is the
first one with genuinely partial-alpha (anti-aliased) pixels — see `ui/cairo_convert.py`'s
documented premultiplication limitation, which this inherits rather than separately breaks.

- **Setting**: "Capture mouse cursor" checkbox in the editor's Preferences dialog
  (`editor_window.py`'s `_do_show_settings`), persisted via `settings.py`'s
  `get_capture_mouse_cursor`/`set_capture_mouse_cursor` (default `True`) — faithful port of
  `ICoreConfiguration.cs:79-81`'s `CaptureMousepointer` (also default `True`).
- **Placement math** (`core/cursor_capture.py`, pure/tested): `cursor_bounds_in_capture` is a
  direct port of `WindowCapture.cs:81-97`'s formula (cursor's absolute hotspot position, minus the
  cursor bitmap's own hotspot offset, minus the capture region's screen origin).
  `cursor_shape_for_capture` adds the intersection check ported from `Surface.cs:552-565` — a
  cursor over a different monitor than the captured region is dropped, not clamped or shown
  anyway.
- **Not baked into the base image — a movable/deletable/auto-selected layer element for Edit,
  composited only for the other four destinations.** Windows adds the cursor as a real
  `CursorContainer` element on the `Surface` (`CaptureHelper.cs:736`'s comment: "elements can be
  added automatically (like the mouse cursor)"), auto-selected, and every destination (Save/Copy/
  Print included) exports that same rendered Surface. This port's Copy/Save/Save As/Print
  destinations previously operated on a flat numpy array with no Layer at all
  (`ui/destination_picker.py`) — extended to composite the cursor in via a one-shape `Layer` +
  `ui/composite.py`'s existing `composite_to_numpy` (the exact same rendering pipeline the live
  editor uses) for those four, while Edit instead adds the same `CursorShape` as a real, auto-
  selected `Layer` element with undo support (`editor_window.py`'s `_do_insert_image` tail pattern)
  — so cursor is present everywhere Windows shows it, movable/deletable only where Windows'
  architecture would actually let you do that too (in the editor).
- **Tray-menu-vs-hotkey asymmetry replicated exactly, per explicit decision** (not simplified away):
  Windows hides the cursor unconditionally when a capture is triggered from `MainForm.cs`'s tray
  icon/context menu (`_captureMouseCursor=false` at every one of those call sites — e.g. region:
  `MainForm.cs:821/1269`, full screen: `845/1272`, window-interactive: `861/1275`), but respects the
  Preferences setting for hotkey-triggered captures (`HotkeyHelper.cs` passes `true` at every
  binding) — because by the time you've clicked the tray icon or a menu item, your mouse is over
  the icon/menu, not your content. This port's tray items and hotkeys previously called the exact
  same `GreenshotApplication.start_*_capture` methods with no way to distinguish source
  (`app.py:151-177`) — now every one of those methods takes a `capture_mouse_cursor: bool = True`
  parameter (mirroring `CaptureHelper.cs`'s own `_captureMouseCursor` constructor parameter, see
  `PluginHelper.cs:141`'s doc comment), threaded down through `ui/capture_modes.py`,
  `region_select.py`, and `window_picker.py`; the tray icon's default click and every tray menu item
  now explicitly pass `capture_mouse_cursor=False`, while the CLI-option path used by the hotkey
  daemon (`do_command_line`) uses the default `True`.
- **Interactive modes (region select, window picker) sample the cursor once, at overlay
  construction — not at drag-release, not tracking the live mouse.** Matches Windows' own timing:
  `CaptureHelper.cs` samples the cursor before the interactive `CaptureForm` is even shown
  (`CaptureHelper.cs:315-329`), so the cursor baked into the final result is wherever the mouse was
  when the capture was *triggered*, not wherever the selection ends up. A live preview of the
  sampled cursor is drawn on the frozen backdrop throughout the drag/hover (reusing
  `ui/render.py`'s real `render_cursor`, so it can't visually drift from the final render), and an
  "M" key toggle flips visibility live during selection — faithful port of
  `CaptureForm.cs:307-311` — with the toggle's state at completion deciding whether the cursor
  makes it into the final result. Live preview is a bounded scope decision: it shows the cursor's
  one sampled position/appearance exactly once, not a moving/re-sampled preview — Windows' own
  `CaptureForm` doesn't re-sample either.
- **Full-screen/active-window/last-region modes** (`ui/capture_modes.py`) apply cursor capture
  the same way, non-interactively — grab region, grab cursor, compute placement against that same
  region, done in one pass.
- Verified live end-to-end at every layer: the real XFixes mechanism against this machine's real
  cursor icon (contract-tested, `tests/unit/capture/test_cursor_backend_contract.py`, parametrized
  over both the fake and the real X11 backend); the Preferences checkbox round-tripping through a
  sandboxed `XDG_CONFIG_HOME` (never the real config file); the full pipeline with
  `FakeCaptureBackend`/`FakeCursorBackend` end to end for all five capture modes, confirming correct
  placement, the intersection-drop case, the M-key toggle, and that Copy/Edit route the cursor
  through their respective (composite vs. movable-element) paths correctly; the tray-vs-hotkey
  `capture_mouse_cursor` threading through every `GreenshotApplication` method; and an offscreen
  Cairo render of both interactive overlays' `_on_draw` (cursor preview + magnifier together) to
  exercise the actual drawing path, not just the placement math. No real desktop content was ever
  captured or viewed for any of this — only the small cursor icon (never a privacy concern) and
  synthetic fake image data.
- **Real X11 cursor hotspot isn't trusted unconditionally — clamped at the boundary.** The live
  contract test (`test_cursor_backend_contract.py::test_snapshot_hotspot_is_within_the_image_bounds
  [x11]`) failed twice against this machine's real cursor: `XFixesGetCursorImage` reported a
  genuinely-invisible cursor as a 1x1 fully-transparent pixel with hotspot `(1, 1)` - out of bounds
  for a 1-pixel image, whose only valid coordinate is `(0, 0)`. Diagnosed rather than dismissed as
  flaky: something producing a blank/hidden cursor via a degenerate pixmap apparently doesn't bother
  clamping its hotspot either, since nothing renders regardless of where it points - a legitimate,
  if unusual, real-world X11 reply, not a bug in this port's own parsing. Checked whether it could
  actually break anything: `cursor_bounds_in_capture` (`core/cursor_capture.py`) only ever uses the
  hotspot arithmetically, never as an array index, so this specific case was never a crash risk -
  but an unclamped hotspot could still visibly mis-place a real, *visible* cursor for some other
  malformed reply. Fixed with `x11_cursor.py`'s `_clamp_hotspot`, applied in `cursor_snapshot()`
  before constructing the `CursorSnapshot`, so the boundary validates the X server's reply instead
  of trusting it unconditionally - the live contract test's invariant now holds by construction
  (confirmed with 5 consecutive clean runs) rather than by hoping live X11 state cooperates. Added a
  deterministic unit test reproducing the exact observed case (`_clamp_hotspot(1, 1, width=1,
  height=1) == (0, 0)`) plus the general boundary cases, so this doesn't depend on live hardware
  state recurring to stay covered.

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

**Pixelize's noise pattern is now stable across redraws of the same shape — fix, not a port
deviation in spirit.** `filters.py`'s `pixelize` draws fresh CSPRNG randomness by default
(`_default_rng`, deliberately — the noise exists to defeat depixelation attacks, so it must not be
predictable) and previously nothing pinned that per shape, so every redraw (which fires on *any*
canvas activity, since moving one shape repaints the whole layer) reshuffled the block-jitter
pattern - reported as the pixelization looking like it randomly "changed when other items moved."
Checked against the real Windows source before changing anything: `PixelizationFilter.cs:56`
creates a fresh `CryptoRandomBuffer` inside `Apply()` too, with nothing cached at the container
level, and `DrawableContainer.cs:443/456` calls `Apply()` on every repaint - so the reshuffling was
a faithfully-ported quirk, not a bug introduced here. Fixed anyway, since it's jarring in practice:
`ObfuscateShape` grew a `seed: int` field (`compare=False` - two shapes with the same
bounds/mode/amount are still equal regardless of which random seed happens to back their
pixelization), drawn once from `secrets.randbits(128)` at shape creation. `render_obfuscate` now
derives Pixelize's `rng` from `shape.seed` when no explicit override is given (tests can still pass
one, e.g. `ZeroRng`, for determinism) instead of falling through to a fresh draw every call. Each
shape still gets its own independent, never-reused random seed - genuinely unpredictable between
shapes and sessions, same as before, just now *stable* for one shape's own repeated redraws. Also
consistent with `composite.py`'s own stated WYSIWYG guarantee (exported output pixel-identical to
the live editor) - a export-time-only re-randomization would have violated that.

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

**Editor layout restructured to match Windows, plus two more interactive tools — done.** Windows'
editor uses a vertical left-side tool palette plus a separate File/Edit/Object/Help menu bar, not
one horizontal toolbar; requested explicitly, with only the menu items applicable to this port's
actual feature set (no Office/OneDrive/cloud destinations - already cut, see "Explicitly cut"
below).
- Layout: `_build_menu_bar()` (File/Edit/Object/Help) → `_build_action_toolbar()` (Undo/Redo/Copy/
  Save/Print/Save-location, horizontal, unchanged from before) → `_build_style_panel()` (unchanged)
  → a horizontal row of `_build_tool_palette()` (the drawing tools, now vertical) beside the drawing
  area. `_content_offset()`'s centering math (see above) is layout-agnostic by construction - it
  only compares the drawing area's actual allocation to the image's actual size, not which side the
  toolbar is on - so it needed no changes for this.
- **The tool palette is plain `Gtk.RadioButton`s in a `Gtk.Box`, not `Gtk.RadioToolButton`s in a
  `Gtk.Toolbar(orientation=VERTICAL)`** - the more common pattern for a vertical icon palette anyway
  (same idea as GIMP/Inkscape's toolbox). This *wasn't* chasing a confirmed bug: a first pass with
  `Gtk.Toolbar` looked like the last of 10 buttons was clipped below the window edge in a
  screenshot, but the actual fix turned out to be `border_width` (zero padding at the bottom made it
  flush with the window edge and easy to miss, not actually clipped - confirmed via per-button
  `get_allocation()`/`get_mapped()` checks, all correct). The widget swap happened before that was
  isolated and turned out harmless, so it stayed.
- **Verification methodology note, worth keeping**: mid-investigation, X11 screen-capture-based
  screenshots of the live window repeatedly showed an inexplicable artifact (a plain rounded-
  rectangle shape) at the exact position of the Step Label icon, even after the padding fix. Direct,
  non-screenshot checks (the widget's own `get_image().get_pixbuf()`, saved and inspected) confirmed
  the *actual* icon data was always correct. Rather than keep capturing more of the live X11 desktop
  to chase what might have been a window-manager decoration artifact or, worse, a capture-region
  overshoot picking up unrelated desktop content, switched to `Gtk.OffscreenWindow` - renders a
  widget subtree straight to a pixbuf with no real display/desktop involved at all - which
  immediately confirmed all 10 tools render correctly. Prefer `Gtk.OffscreenWindow` over X11 window-
  bounds screenshots for future editor-window UI verification: same visual fidelity, zero desktop-
  capture risk.
- Two new interactive tools, both already had full rendering support from earlier in this project
  (`ui/render.py`) and only needed UI wiring: **Speech Bubble** (drag to create; the tail's `target`
  defaults to a fixed point below the bubble, since `SpeechBubbleShape` has no dedicated handle to
  reposition just the tail after creation - moving the whole shape keeps target and bubble in sync,
  but there's no way to adjust their relative offset post-creation, so creation has to pick a
  sensible default) and **Step Label** (click-to-place - `core/tools.py`'s `create_shape_from_drag`
  ignores the drag's end point for this tool, always using a fixed-radius circle at the start point,
  matching the source's click-to-place rather than drag-to-size interaction; auto-increments via
  `EditorWindow._next_step_number()`, counting existing `StepLabelShape`s already in the layer).
  Speech Bubble also generalizes the existing Text-tool editing machinery (immediate edit-mode after
  creation, double-click to re-edit) from a `TextShape`-only `isinstance` check to
  `(TextShape, SpeechBubbleShape)` - both already used the same generic `dataclass_replace(shape,
  text=...)` pattern keyed off a `.text` field, so no other changes were needed for text entry to
  work on bubbles too.
- **Object menu** (new): Delete (also bound to the Delete key), Bring to Front, Send to Back -
  thin wiring over already-tested pure `Layer` methods (`bring_to_front`/`send_to_back`) and the
  existing `DeleteElementMemento`. Bring to Front/Send to Back are **deliberately not undoable
  yet** - `core/history.py` has no z-order memento type (only Add/Delete/ElementChange), and
  reordering is rare/easy enough to reverse manually that this is a documented simplification, not
  something worth a new memento type for right now.
- **Help → About** (new): a `Gtk.AboutDialog` using the real logo (`resources/greenshot-linux.png`,
  see the icon-surfaces work above).
- **Still outstanding from the original ask** (not yet done, needs product decisions before
  building - see the task list): Icon/stamp, Cursor overlay, embedded Image, and embedded SVG as
  interactive tools. All four already render correctly too, but unlike Speech Bubble/Step Label they
  need either a stock asset picker (Icon), a file chooser (Image/SVG - `Gtk.FileChooserDialog`,
  already used elsewhere in this file), or capture-time integration rather than after-the-fact
  placement (Cursor - Windows embeds the actually-captured mouse cursor bitmap, which isn't
  something a toolbar tool naturally "adds" after the fact the way the others do).

**Selection tool, Emoji tool, and style-panel label fixes — done**, from live review of a real
Windows screenshot cross-checked against `ImageEditorForm.Designer.cs`.
- **Select** (`Tool.SELECT`, first in the palette, default active tool - matches the source's
  `btnCursor.Checked = true`): Windows' "Cursor" tool - clicking empty space does nothing, only
  select/move/resize of existing shapes works. Changes the out-of-the-box behavior: a fresh capture
  used to default to Rectangle (draw immediately), now defaults to Select like Windows does (pick a
  tool first). No dedicated keyboard shortcut yet - there's no clear Windows precedent to port, and
  every unclaimed letter would be an undocumented convention rather than a faithful port, so it's
  toolbar-only pending explicit direction.
- **Emoji** (`Tool.EMOJI`, key `M` - confirmed from the source's `btnEmoji.Text = "Emoji (M)"`): no
  dedicated shape type - reuses `TextShape` pre-filled with a default glyph (🙂) instead of empty
  text, through the exact same immediate-edit/double-click-to-re-edit machinery Text/Speech Bubble
  already have (retype to pick a different emoji). The icon is a hand-drawn monochrome smiley, not
  an actual emoji-font glyph - Cairo's toy text API has no reliable color-emoji-font support, and a
  hand-drawn glyph stays visually consistent with the other single-color, theme-following tool icons
  instead of looking like a mismatched color sticker among them.
- Palette now has a separator between Select and the rest, matching the source's real grouping
  (`toolsToolStrip.Items`: Cursor | sep | Rectangle...Emoji | sep | Highlight/Obfuscate/Effects | sep
  | Crop/Rotate/Resize) - Highlight/Effects and Crop/Rotate/Resize are still empty for now since
  they're not built yet (task #36/#42); Obfuscate itself is now built (see below).
- Style panel: `Thickness:` renamed to `Line Thickness:`; the single generic `Obfuscate Amount:`
  spinner's label now swaps to `Blur Radius:` or `Pixel Size:` depending on which tool is active,
  matching the source's own two separate, mode-specific labeled controls (`blurRadiusLabel`/
  `pixelSizeLabel`) rather than one generically-named field doing double duty. Still one shared
  spinner underneath (not two separate controls like the source) - a smaller, cosmetic-only
  simplification versus the label fix itself. **Since revised** (see "Obfuscate toolbar control"
  below): the fallback text is now the shorter `Amount:`, the label follows the *selected shape's*
  mode when one's selected rather than just the active tool, and a vertical separator now sits
  between the Shadow checkbox and this label/spinner pair.

**Obfuscate toolbar control now matches Windows' actual layout, not two separate buttons — done.**
Originally built as two independent toolbar buttons, Pixelize and Blur. Reading the real source
closer (`DrawingModes.cs`, `ImageEditorForm.Designer.cs`, `ObfuscateContainer.cs:34` - *"a
FilterContainer for the obfuscator filters like blur and pixelate"*) showed Windows has exactly one
`Obfuscate` drawing mode and one toolbar button (`btnObfuscate`) for it, plus a separate small
dropdown (`obfuscateModeButton`, items `pixelizeToolStripMenuItem`/`blurToolStripMenuItem`) that
picks which filter (`PreparedFilter.BLUR`/`PIXELIZE`) it currently applies — Blur/Pixelize are
sub-modes of one tool, not two tools. Rebuilt to match: a single "Obfuscate" radio button in the
palette (icon reflects whichever mode is currently prepared, defaulting to Pixelize per
`ObfuscateContainer.InitializeFields`) plus a small attached `Gtk.MenuButton` dropdown to switch
modes. `core/tools.py` is untouched - `Tool.PIXELIZE`/`Tool.BLUR` still exist and still drive
`create_shape_from_drag` exactly as before; only the palette's *presentation* changed, both tool
values now map to the same shared button widget in `self._tool_buttons`. Keyboard shortcuts 6
(Pixelize)/7 (Blur) still work, now routed through `_select_and_activate_obfuscate_mode` so they
behave correctly even when Obfuscate is already the active tool (GTK's own `"toggled"` signal
doesn't refire when a radio button's active state doesn't change, so that path updates
`self.tool`/the icon/the label directly rather than relying solely on the signal).

**Revised again to decouple the dropdown from tool activation, after checking the real binding
Windows uses.** The first cut had picking a mode from the dropdown *also* activate the tool - close,
but not what Windows actually does. `ImageEditorForm.cs:1366` binds `obfuscateModeButton`'s
`SelectedTag` bidirectionally *only* to the `PREPARED_FILTER_OBFUSCATE` field
(`BidirectionalBinding`), and `BindableToolStripDropDownButton.OnDropDownItemClicked`
(`Controls/BindableToolStripDropDownButton.cs`) just swaps the button's own tag/icon - neither ever
touches `DrawingMode`. Only `BtnObfuscateClick` (the *main* button) sets
`_surface.DrawingMode = DrawingModes.Obfuscate`. So in real Windows the dropdown is a pure
preference: picking Blur while Rectangle is the active tool just changes what Obfuscate will use
*next time*, without switching you into drawing mode. Split accordingly:
`_set_obfuscate_mode` (dropdown menu items - changes the prepared mode only, though it does update
the amount label/icon live if Obfuscate already happens to be active, matching Windows' field
aggregator reflecting the newly prepared filter's fields immediately even though nothing about
*whether* it's active changed) vs. `_activate_obfuscate_tool` (the main button - starts drawing with
whichever mode is prepared, mirrors `BtnObfuscateClick` exactly). The 6/7 keyboard shortcuts are the
one intentional exception - they call both in sequence (`_select_and_activate_obfuscate_mode`) since
a keyboard shortcut is expected to do something immediately, and Windows has no per-sub-mode
shortcut to be unfaithful to there in the first place (only one `Obfuscate` drawing mode exists).
Verified live (synthetic image, no real desktop capture): picking a mode from the dropdown while
Rectangle is the active tool leaves the active tool as Rectangle and only updates
`self._default_obfuscate_mode`; clicking the main button afterward correctly picks up that newly
prepared mode; picking a different mode while Obfuscate *is* already active updates the label live
without needing a separate activation step; selecting an existing Pixelize `ObfuscateShape` while a
different tool (Rectangle) is active correctly shows `Pixel Size:` without switching the active tool
out from under the user.

**Moved again, to the correct toolbar entirely.** The dropdown had been attached directly to
`btnObfuscate` in the tool palette this whole time - closer to a plausible guess than something
actually checked against the source. It doesn't live there in Windows: `toolsToolStrip.Items`
(`ImageEditorForm.Designer.cs:334-353`) has `btnObfuscate` alone, no attached dropdown, in the same
row as every other draw tool; `obfuscateModeButton` is in a *different* toolbar entirely,
`propertiesToolStrip.Items` (`:1076`), the same row as `btnFillColor`/`btnLineColor`/
`lineThicknessLabel`/`blurRadiusLabel` - Windows' equivalent of this port's style panel, not the tool
palette. And it follows the exact same visibility rule as those: `obfuscateModeButton.Visible =
props.HasFieldValue(FieldType.PREPARED_FILTER_OBFUSCATE)` sits right next to the
`BLUR_RADIUS`/`PIXEL_SIZE` checks in `RefreshFieldControls`. Moved to match: `STYLE_FIELD_OBFUSCATE_MODE`
added to `core/tools.py`'s `_OBFUSCATE_STYLE_FIELDS` (so it shows/hides together with `obfuscate_amount`
- both driven by the same "is Obfuscate relevant" condition, matching Windows grouping them under the
same field-aggregator check), and the dropdown itself moved into `_build_style_panel` as an ordinary
conditionally-visible cell, right before the Amount cell. `_build_obfuscate_control` (the palette
entry) goes back to a plain button like every other tool, no attached widget. Icon-swapping moved
with it: Windows' `btnObfuscate.Image` is a single static icon, never reassigned anywhere in the
source - only `obfuscateModeButton.Image` swaps
(`BindableToolStripDropDownButton.OnDropDownItemClicked`, `Image = clickedItem.Image`) - so the
palette button's icon is now fixed (at the Pixelize glyph, the default mode; this port has no
separate generic "Obfuscate" icon asset, matching Windows not having a dynamic one there either), and
the moved dropdown shows the live mode instead - as button *text* ("Pixelize"/"Blur"), not a swapped
icon, since every other style-panel control is text already and this port has no per-mode icon
that'd look right at that small size next to text labels. Verified live (synthetic image): the
palette button has no dropdown attached and no `MenuButton` anywhere near it; the mode cell lives in
`self._style_field_widgets`, hidden by default (Select tool, nothing selected), shown alongside
Amount only once Obfuscate is relevant; picking a mode while Rectangle is the active tool still
leaves Rectangle active (the decoupling above still holds from its new location) while correctly
updating the prepared mode for later.

**Missed on the first pass: a selected ObfuscateShape's own mode wasn't retroactively updated by
the dropdown - fixed.** Every other style-panel control already restyles the current selection when
changed (`_apply_style_change` for line/fill/thickness/shadow; `_on_obfuscate_amount_changed` for
Amount) - the mode dropdown didn't, an oversight from when it was first split into its own method,
not a deliberate choice. Real usage caught it: select an existing Blur box, switch the dropdown to
Pixelize, and the selected shape stayed Blur. `_set_obfuscate_mode` now checks `self.selected_shape`
first - if it's an `ObfuscateShape`, retroactively replaces its `mode` field (`dataclass_replace` +
`ElementChangeMemento`, same pattern as the amount handler, undoable), preserving `amount`/`bounds`
and leaving the active tool untouched (doesn't jump into drawing mode just because a shape got
retagged) - only falling through to the "update `self.tool` live" branch when *nothing's* selected
but Obfuscate is already the active tool. Verified live: selected an existing Blur shape, switched
the dropdown to Pixelize - the shape's mode updated in place (amount and bounds preserved), the
active tool stayed Select, the label swapped to "Pixel Size:", and undo correctly restored the Blur
version.

**Style panel now shows/hides each control per tool/selection, not always every control — done,**
fixing a real complaint: the obfuscate-amount spinner ("Amount:") stayed visible and functionally
inert on every non-Obfuscate tool, since nothing but Pixelize/Blur ever read
`self._default_obfuscate_amount`. Checked the real source rather than just hiding that one control:
`ImageEditorForm.cs:1375`'s `RefreshFieldControls` shows/hides *every* style-panel control
individually, driven by `FieldAggregator.HasFieldValue` against whichever's actually selected or
active - `blurRadiusLabel`/`pixelSizeLabel` are only two of many (`btnFillColor`, `btnLineColor`,
`lineThicknessLabel`, `shadowButton`, etc. all get the same treatment) - and with nothing selected
and no drawing mode active, *everything* is hidden (`HideToolstripItems()`), not shown. This port's
panel was built once and left permanently visible regardless of context, a simplification that
predates this session and wasn't specific to the obfuscate-amount complaint - implementing it
properly meant per-field visibility for the whole panel, not a special case.

Added `core/tools.py`'s `visible_style_fields(tool, selected_shape=None)`: a selected shape's own
fields take priority over the active tool's (matching Windows' aggregator reflecting the
*selection's* fields when there is one), falling back to the active tool's fields, with
`Tool.SELECT` + nothing selected showing nothing. Field sets per tool/shape are an explicit table
(`_TOOL_STYLE_FIELDS`/`_shape_style_fields`) cross-checked against the real per-container
`AddField` calls (`RectangleContainer.cs`/`EllipseContainer.cs`/`LineContainer.cs`/
`ArrowContainer.cs`/`FreehandContainer.cs`/`TextContainer.cs`/`StepLabelContainer.cs`/
`ImageContainer.cs`) *and* against what this port's own `ui/render.py` renderers actually use per
shape, since some of this port's rendering already diverges from the source in ways that matter
here - e.g. `render_arrow` fills the arrowhead with `line_color`, not a separate `fill_color`, so
Arrow gets Line's field set (no Fill control) even though `ArrowContainer.cs` does have a
`FILL_COLOR` field in the real source; `render_freehand` never draws a shadow or fill, matching
`FreehandContainer.cs` having neither field either. Deliberately an explicit table rather than
derived indirectly from shape construction, so it stays one easy-to-audit place to revisit next time
someone compares this against a newer Windows source. `ui/editor_window.py`'s `_build_style_panel`
groups each field's label+control into its own `Gtk.Box` "cell" (`self._style_field_widgets`, keyed
by field name) so a whole field can be shown/hidden in one `set_visible()` call;
`_refresh_style_panel` (replacing the older `_refresh_obfuscate_amount_label`, called from the same
places: the `selected_shape` property setter and every tool-switch path) drives both the amount
label's text and every cell's visibility together, since they depend on the same (tool, selected
shape) pair. The vertical separator (see the style-panel bullet above) only shows while Amount is
visible, since style fields and `obfuscate_amount` are never visible at the same time - it would
otherwise dangle before an empty, fully-hidden style-fields cluster. Full unit test coverage in
`core/tools.py` (pure, no GTK) plus live verification of the GTK wiring: Select-with-nothing-selected
hides the whole panel; Rectangle shows Line/Fill/Thickness/Shadow with Amount hidden; Line hides Fill
only; Obfuscate shows only Amount; selecting an existing Line while Rectangle is the active tool
shows Line's fields (selection overriding tool); selecting an `IconShape` (no style fields at all)
hides everything; deselecting falls back to the active tool's fields again.

**Action toolbar reordered to match Windows, plus per-shape Cut/Copy/Paste, Settings, Help, and an
external-editor button — done.** Real order confirmed from `ImageEditorForm.Designer.cs`'s
`destinationsToolStrip.Items`: `Save, Copy(image), Print | Delete | Cut, Copy(shape), Paste, Undo,
Redo | Settings | Help`.
- **Per-shape Cut/Copy/Paste** (new): a single-shape clipboard (`EditorWindow._shape_clipboard`,
  in-editor state, not the real system clipboard) - distinct from the existing whole-image "Copy"
  button, which still copies the composited image to the real system clipboard unchanged. Paste
  offsets the pasted copy by (20, 20) so repeated pastes don't stack exactly on top of the original.
  Deliberately doesn't read an image *from* the system clipboard (Windows' Paste can also do that) -
  `ClipboardBackend` here is write-only (`set_image`, no read-back), so that half is out of scope
  until the port gains clipboard-read support.
- **Delete** as a toolbar button too now (logic already existed via task #40's Object menu + Del
  key, just needed a button).
- **Settings** (new, gear icon): a small `Preferences` dialog - matches Windows' real Settings
  button, but there isn't much to configure yet, so it's mostly a home for the existing Screenshot
  Save Location control (moved here from being its own standalone toolbar button, which wasn't a
  Windows button to begin with) rather than a Windows-parity settings surface.
- **Help** (new, info icon): a small dialog listing keyboard shortcuts. Windows' own Help opens
  online docs this port doesn't have, so this is a reasonable placeholder, not a port.
- **Open in External Editor** (new, paint-palette icon) — **not a Windows feature**, Windows has no
  such destination; built per explicit request, not a port. Checks for Krita first (specifically
  requested), then GIMP, checking *both* a PATH executable and a Flatpak install for each - Flatpak
  is a common install method on Mint (confirmed live: this dev machine's Krita is Flatpak-only, not
  on PATH at all - a plain `shutil.which` check alone would have missed it entirely). Flatpak
  detection uses a live `flatpak list --app` query rather than `locate`: `locate` depends on the
  optional `mlocate`/`plocate` package being installed at all, and its index can be stale until the
  next `updatedb` run, so a just-installed app might not show up yet; `flatpak list` is authoritative
  and always current. Saves the composited image to a temp PNG and launches the editor
  non-blockingly (`subprocess.Popen`), via `flatpak run <app-id>` when that's how it was found.
  - **Fixed a real bug: the temp PNG went to system `/tmp`, which a Flatpak-sandboxed editor can't
    see even with broad `filesystems=host` permission.** Reported as Krita saying *"The file
    /tmp/greenshot-linux-....png does not exist"* immediately after clicking the button. Checked
    Krita's actual granted permissions first rather than guessing (`flatpak info
    --show-permissions org.kde.krita` → `filesystems=host;xdg-run/gvfs;`) - `host` looked like it
    should cover `/tmp`, but doesn't: bubblewrap always gives a Flatpak sandbox its own private,
    empty `/tmp` tmpfs regardless of `host` access (a well-known Flatpak/bubblewrap-specific
    carve-out). Confirmed empirically both ways rather than assumed: `flatpak run --command=ls
    org.kde.krita /tmp` came back empty (the sandbox's own private `/tmp`, not the host's, which
    has real files) while `flatpak run --command=ls org.kde.krita ~` showed the real host home
    directory. Fixed by writing the temp PNG to `$XDG_CACHE_HOME/greenshot-linux/` instead (matching
    `settings.py`'s existing `$XDG_CONFIG_HOME` convention) - confirmed genuinely visible inside the
    sandbox the same way (`flatpak run --command=cat org.kde.krita
    ~/.cache/greenshot-linux/<file>` read it back correctly). The previous export's file is deleted
    right before a new one is written (unique filenames still, so a second export mid-edit can't
    clobber a file a still-open first editor session already loaded into memory), since
    `~/.cache/greenshot-linux` isn't OS-managed transient storage the way `/tmp` is and would
    otherwise accumulate one PNG per click for the life of the session.
  - **Which editor is preferred is now configurable, not just hardcoded Krita-then-GIMP.** A new
    `settings.py` key (`get_external_editor_preference`/`set_external_editor_preference`, default
    `EXTERNAL_EDITOR_AUTO`) picked from a `Gtk.ComboBoxText` in the Preferences dialog
    ("Auto (Krita, then GIMP)" / "Krita" / "GIMP"). `_find_external_editor_command` tries the
    preferred candidate first, then always falls through to the normal auto-detect order regardless
    of *why* the preferred one didn't match (set to "auto", names a candidate that's since been
    uninstalled, or names something no longer in `_EXTERNAL_EDITOR_CANDIDATES`) - a stale preference
    can never leave the button silently broken. Verified live (mocked `subprocess.Popen` and
    `config_file_path`, no real editor launched): preference round-trips through the combo box
    including the stale-ID fallback case (`Gtk.ComboBoxText.set_active_id` returns `False` for an ID
    that isn't in the list, confirmed rather than assumed, falling back to Auto in the UI); against
    this dev machine's real installed state (Krita via Flatpak, GIMP not installed at all),
    preferring "GIMP" or an unknown name both correctly fall back to finding Krita rather than
    returning nothing.

**Insert Image / Insert SVG — done, folds in what would otherwise be Icon/Cursor support.**
Windows has no dedicated "insert image" *toolbar tool* — `DrawingModes.Bitmap` is defined in the
enum but never assigned anywhere in the source. Image/SVG are instead handled by Windows' generic
file-import system (`IFileFormatHandler` implementations alongside PNG/JPG/ICO/`SvgFileFormatHandler.cs`),
so this port matches that shape: `File > Insert Image...` / `File > Insert SVG...`, not tool-palette
buttons. Since there's no drag gesture to size the shape from (a file picker, not a click-and-drag
tool), the inserted shape starts at `core/tools.py`'s new `default_insert_bounds(content_w,
content_h, canvas_w, canvas_h)` - centered on the canvas at natural size, scaled down (preserving
aspect ratio) only if larger than 80% of the canvas in either dimension, never scaled up - and is
then movable/resizable like any other shape via the Select tool (`ImageShape`/`SvgShape` were
already in `_BOUNDS_RESIZABLE`, so no extra work needed there). Confirmed live: PNG insert into a
500x300 canvas centers a 60x40 image at `Rect(220,130,280,170)`; SVG insert centers an 80x40 SVG at
`Rect(210,130,290,170)` - both match the expected centered math exactly.
- **Icon/stamp folded in, not built separately**: GdkPixbuf's own supported-format list includes
  `.ico`/`.cur` natively (confirmed live via `GdkPixbuf.Pixbuf.get_formats()`), so Insert Image
  already covers icon files with zero extra code. This isn't a shortcut - Windows' own
  `IconContainer` (the closest equivalent) turned out to be dead code during research: it's defined
  but has no UI path that ever constructs one (confirmed via `Surface.cs`/`CaptureHelper.cs`
  citations), so there was nothing real to port in the first place. Cursor is unrelated - it's a
  capture-time *setting* (draw the mouse cursor into the screenshot), not a tool at all; tracked
  separately as its own task since it belongs in the capture backend, not the editor.
- **Debugging note worth keeping**: verifying this live (driving the real `Gtk.FileChooserDialog`
  via `GLib.timeout_add` + `dialog.set_filename()` + `dialog.response()`, the same pattern used
  successfully for every other dialog in this port) initially hung indefinitely and looked like a
  serious bug in the new code. Root cause was a *test-harness-only* race: calling
  `dialog.response(OK)` immediately after `set_filename()`, with no gap for the file chooser's own
  async directory-navigation to settle, deadlocks `dialog.run()` - reproduced in a minimal script
  with no app code involved at all, and confirmed fixed by giving the main loop a short gap (a
  second `GLib.timeout_add` a few hundred ms later) between the two calls. A real user clicking
  through the dialog never hits this, since mouse interaction doesn't race the chooser's internal
  state the way scripted `set_filename()` + immediate `response()` does. Cancel-only dialog tests
  (used everywhere else so far) never exercised this path, which is why it hadn't shown up before.

### Editor zoom (faithful port of `ImageEditorForm`/`Surface`'s zoom)
**Status: done.** Initially flagged as "not yet checked against the Windows source" in this file's
backlog - research confirmed it's a real, well-developed Windows feature (PR #201, Ctrl+wheel in PR
#282 - `docs/changelogs/CHANGELOG-1.3.md:192-193`), not something to design from scratch.

- **Fixed discrete levels** (`core/zoom.py`, pure/tested): 25/50/66/75/100/200/300/400/600%,
  faithful port of `ImageEditorForm.cs:101-104`'s `ZOOM_VALUES`. Uses `fractions.Fraction` rather
  than float, for the same reason Windows uses its own `Fraction` struct there - 66% (2/3) has no
  exact float representation, and repeated zoom steps would drift.
- **Canvas-only scaling, mouse coordinates un-scaled for hit-testing** - faithful port of `Surface`'s
  single paint-time `ScaleTransform` (`Surface.cs:1865-1899`) plus `InverseZoomMouseCoordinates`
  (`Surface.cs:1469-1470`): `_on_draw` applies one `ctx.scale(zoom, zoom)` before painting the base
  image and every shape (all still rendered in image-space coordinates, so they can never visually
  drift from what a click actually hits), and every mouse handler divides event coordinates by zoom
  before hit-testing/dragging/creating shapes - drawing and clicking stay pixel-accurate at any zoom
  level, not just 100%.
- **Window resizes to fit zoomed content, like Windows - a deliberate choice, not the initial
  instinct.** Before implementing, this was flagged as a real UX fork: Windows resizes
  `ImageEditorForm` itself to fit the zoomed canvas (`GetOptimalWindowSize`/
  `AlignCanvasPositionAfterResize`, `ImageEditorForm.cs:2012-2052,1971-2006`), clamped between a
  650x530 minimum and the screen's available work area, only scrolling if even that doesn't fit -
  versus the more typical Linux/GTK pattern of a fixed-size window with an always-scrollable canvas.
  Asked directly; chose the faithful Windows behavior. `_set_zoom` (every zoom action funnels
  through this one method, matching `ZoomSetValue`) measures "chrome" size (everything that isn't
  the canvas - menu bar, toolbars, style panel, tool palette) dynamically from the current layout
  rather than hardcoding it, resizes the drawing area to the new zoomed size, then resizes the
  window via `core/zoom.py`'s pure `optimal_window_size` clamp helper. The canvas is still wrapped
  in a `Gtk.ScrolledWindow` (`_canvas_scroller`) for the overflow case - matches Windows' own
  `panel1`/`NonJumpingPanel`, which is always scrollable even though `ZoomSetValue` normally resizes
  the window instead of relying on it.
- **Zoom control lives in a status-bar dropdown, not a menu-bar entry** - Windows has no top-level
  zoom menu either; only `zoomStatusDropDownBtn` (a status-bar button opening `zoomMenuStrip`,
  `ImageEditorForm.Designer.cs:224,271-277`) plus keyboard shortcuts and Ctrl+wheel. Matched that
  structure rather than inventing a "View" menu Windows doesn't have. The status bar
  (`_build_status_bar`) also shows image pixel dimensions, matching Windows' `dimensionsLabel`.
- **Keyboard shortcuts**: Ctrl+=/Ctrl+Numpad+ (zoom in), Ctrl+-/Ctrl+Numpad- (zoom out), Ctrl+0/
  Ctrl+Numpad0 (Actual Size), Ctrl+9/Ctrl+Numpad9 (Best Fit) - matches
  `ImageEditorForm.cs:1142-1157`'s exact bindings. Incidental fix made while wiring these in: the
  existing (Linux-only, no Windows precedent) bare-number-key tool-switch shortcuts (`_TOOL_KEYS`,
  e.g. bare `0`→Step Label, bare `9`→Speech Bubble) were checked *before* the Ctrl-held branch, so
  Ctrl+0/Ctrl+9 would have been swallowed as tool switches instead of ever reaching the new zoom
  shortcuts (GDK reports the same base keyval regardless of whether Ctrl is held). Fixed by checking
  `ctrl_held` first and gating the tool-switch lookup on `not ctrl_held` - since none of those
  digit-key tool shortcuts have Windows precedent to begin with, treating Ctrl+digit as a reserved
  namespace (like virtually every other app) is a safe, minor consistency fix alongside the real
  collision fix, not a faithfulness regression.
- **Ctrl+wheel zoom, 100ms-throttled** - faithful port of `PanelMouseWheel`
  (`ImageEditorForm.cs:1181-1200`) and its `_zoomStartTime` throttle (`ImageEditorForm.cs:96,1185-1187`):
  a physical scroll wheel can send many events per detent, so without throttling one wheel click
  could jump several zoom levels at once.
- **Verification note**: live-testing `Gtk.Window.resize()` initially looked broken - calling it in
  a rapid, unfocused headless test script had zero visible effect even after many `Gtk.main_iteration()`
  pumps. Root-caused to a test-harness gap, not an app bug: confirmed via an isolated bare
  `Gtk.Window` that `resize()` needs the window to actually have focus (`win.present()`) and needs
  *real* wall-clock time for the X11 ConfigureRequest/ConfigureNotify round-trip with the window
  manager to complete - a tight pump-loop with no real delay never gives the WM a chance to respond.
  Re-verified with `present()` + real waits and the full zoom flow (in/out/actual-size/best-fit,
  all four keyboard shortcuts, Ctrl+wheel with throttle, bare-digit tool-switch keys still working)
  all confirmed correct.

### Color picker (faithful port of `Greenshot.Editor.Forms.ColorDialog`)
**Status: done.** Replaces the line-color/fill-color style-panel buttons' original implementation
(plain `Gtk.ColorButton`, opening GTK's generic system color chooser). Research first corrected an
assumption in this feature's own task description ("a dropdown palette of preset/recent colors plus
a 'more colors...' option") — the real Windows control (`ToolStripColorButton`) opens one custom
`ColorDialog` directly, no two-stage dropdown-then-dialog flow; the "palette" lives entirely inside
that one dialog alongside RGB/hex fields, a Transparent button, and an eyedropper. Both line-color
and fill-color buttons share the exact same dialog and behavior in Windows — no field-specific
logic anywhere, confirmed by reading the source — so this port's version does too.

- **Palette grid** (`core/color_palette.py`, pure/tested): 13 columns x 11 rows, faithful port of
  `CreateColorPalette`/`CreateColorButtonColumn` (`ColorDialog.cs:68-109`) — 12 hue columns (red,
  orange, yellow, chartreuse, green, spring green, cyan, azure, blue, violet, magenta, rose) each
  shaded black→pure-hue→white, plus a greyscale column. Got the exact formula (including Windows'
  *truncating* integer division, not rounded) directly from the source rather than approximating —
  the visual grid is directly observable/checkable, so getting the literal algorithm right mattered
  more here than for e.g. drop-shadow's blur, which isn't independently verifiable without a
  reference render. A test hand-traces the entire red column's 11 exact RGB values end to end.
- **Recent colors** (`core/color_palette.py`'s `add_recent_color` + `settings.py`'s
  `get_recent_colors`/`set_recent_colors`): classic MRU (remove-if-present, insert at front, cap at
  12), faithful port of `AddToRecentColors` (`ColorDialog.cs:182-192`) and
  `IEditorConfiguration.RecentColors` (`IEditorConfiguration.cs:36-42`, ini-backed — this port's
  equivalent is the same JSON settings file everything else in `settings.py` uses). Persists across
  app restarts, matching Windows. One simplification: Windows pre-allocates 12 disabled/transparent
  placeholder swatches and enables them as history accumulates; this port just shows however many
  colors actually exist (0 to 12), avoiding a "disabled swatch" visual state for no real benefit.
- **The dialog itself** (`ui/color_dialog.py`): a `Gtk.Dialog` with the palette grid, recent-colors
  row, a live preview swatch, RGB/Alpha spinbuttons + a hex entry (two-way synced, guarded against
  update loops the same way the Resize effect dialog's aspect-lock is), a Transparent quick-pick,
  and an Eyedropper button, plus Cancel/Apply. Single-clicking a swatch previews it (updates the
  preview + fields without closing); double-clicking applies and closes in one action — faithful
  port of `ColorButtonDoubleClick` (`ColorDialog.cs:133-137`).
- **Eyedropper** (`ui/eyedropper.py`) — press-and-hold on the eyedropper button, drag anywhere on
  screen (not confined to the dialog's own window), a magnified preview follows the cursor, release
  commits the color under the cursor, Escape cancels: faithful port of
  `Greenshot.Editor.Controls.Pipette`/`MovableShowColorForm`. Built almost entirely from *existing*
  infrastructure rather than a new subsystem: the screen-wide drag uses a fullscreen invisible
  `Gtk.WindowType.POPUP` overlay (the same technique `region_select.py`/`window_picker.py` already
  use for exact multi-monitor geometry) plus `Gdk.Seat.grab()` (confirmed live, in isolation before
  writing any dialog code, that a grab initiated from one widget's button-press correctly redirects
  the in-progress drag's motion/release events to a *different* window — exactly the "press started
  on the small eyedropper button, drag continues anywhere on screen" case this needs); pixel reading
  reuses `CaptureBackend.grab()` (the same real X11 mechanism every capture mode already uses, just
  a tiny clamped patch instead of a full region); the magnified preview reuses `ui/magnifier.py`'s
  existing `draw_magnifier` (the same one region-select's own magnifier loupe uses) unchanged.
- Verified live end-to-end: cancel returns nothing changed; hex-entry and RGB-spinbutton edits
  correctly two-way sync and commit; the Transparent button; the palette grid's exact widget count
  (143 = 13×11); double-click-applies-and-closes on a real swatch; recent-colors persistence
  (sandboxed to a temp `XDG_CONFIG_HOME`) correctly accumulating in MRU order; the editor's
  line-color button correctly opening the dialog and propagating a picked color into
  `_default_style`; and the eyedropper's pixel-sampling + edge-clamping logic (never crashes near
  screen edges, always returns a full-size patch) against `FakeCaptureBackend` synthetic content —
  never real desktop pixels, consistent with this project's standing privacy rule. The
  `Gdk.Seat.grab()` mechanism itself was confirmed against the real X11 session (a grab succeeding
  reveals no content, unlike a screen capture, so this was safe to verify for real) but the full
  pixel-sampling logic was verified only against fake content.

### Whole-image effects (faithful port of `Greenshot.Base/Effects`)
**Status: done.** Operations on the *entire* captured image, distinct from drawn annotation shapes
(`core/tools.py`) — grouped in a dedicated "Image" menu (`_build_menu_bar`) rather than Windows'
toolbar split-button, matching how this port already puts other toolbar-button actions (Insert
Image, Print) in the menu bar instead. Research (before implementing) inventoried every effect
Windows actually wires into its editor UI, citing `Greenshot.Base/Effects/*.cs` and
`Greenshot.Base/Core/ImageHelper.cs` for each — `AdjustEffect`/`MonochromeEffect`/
`ReduceColorsEffect` were found defined but with no UI call site anywhere in `ImageEditorForm.cs`,
so they're correctly out of scope, not missing.

- **Pure numpy pixel effects** (`core/effects.py`, tested): `rotate_90_image` (90° only, matching
  `RotateEffect.cs:32-68` — arbitrary angles throw `NotSupportedException` there too),
  `grayscale_image` (NTSC luma weights R=.3/G=.59/B=.11, `ImageHelper.cs:1133-1161`),
  `invert_image` (`out = 255 - in` per RGB channel, `ImageHelper.cs:900-928`),
  `add_border_image` (fixed 2px black default, no dialog — matches Windows' own left-click-only
  behavior, `ImageHelper.cs:1024-1060`), `enlarge_canvas_image` (fixed 25px pad, transparent fill,
  `ImageHelper.cs:1399-1410`), `remove_transparency_image`, `clear_image`, `box_blur` (two-pass
  horizontal+vertical, applied twice — 4 passes total, a Gaussian approximation faithfully porting
  `ImageHelper.ApplyBoxBlur`'s fallback path, `ImageHelper.cs:493-527`), and `drop_shadow_image`
  (darkness 0.6 / size 7 / offset (-1,-1) defaults, matching `DropShadowEffect.cs:48-53`) — the last
  one explicitly documented as a *good-faith reproduction* of the described algorithm (silhouette +
  blur + composite), not a pixel-identical port of GDI+'s exact blur/compositing internals, which
  aren't independently verifiable without a reference render to diff against.
- **Autocrop / "Shrink Canvas"** (`core/crop.py`'s `autocrop_rect`, tested) — deliberately
  *simplified* from Windows' own description ("for each corner, grow a region, keep the largest"):
  attempting a literal 4-corner "grow and pick best" implementation revealed a real structural
  problem caught by testing, not assumed — since every edge scan spans the image's full width/height,
  a single differently-colored corner (exactly the scenario multi-corner sampling is meant to handle)
  poisons its own row *and* column scan for every hypothesis tried, degenerating to unhelpful results
  in precisely the case it's supposed to make more robust. Simplified to one well-defined hypothesis
  (the most common of the 4 sampled corner colors) instead of an under-specified 4-way scheme that
  didn't reliably deliver on its own intent — documented as a known, inherent limitation (a stray
  pixel exactly at a corner can still block trimming its two adjacent edges), not silently dropped.
  `crop_to_rect` (already existed, built for the still-unbuilt interactive Crop tool) is reused
  directly to apply the result — no new crop-application logic needed.
- **Resize (resample)** (`ui/effects.py`'s `resize_image`, live-verified) — dialog with width/height
  in pixels and an aspect-ratio lock (auto-syncing the other field live); Windows also offers percent-
  based entry, deliberately not ported — a scope reduction to keep the dialog simple, since pixel
  entry alone covers the effect's actual behavior faithfully. Uses `GdkPixbuf.InterpType.HYPER`
  (GdkPixbuf's own highest-quality/anti-aliased filter) as the closest available equivalent to
  Windows' `InterpolationMode.HighQualityBicubic` — GdkPixbuf has no bicubic filter, and this isn't a
  pixel-identical port of GDI+'s exact resampling kernel.
- **Torn Edge** (`ui/effects.py`'s `torn_edge_image`, live-verified) — the most speculative effect:
  a jagged Cairo path (each edge divided into tooth-range-wide regions, each boundary randomly
  displaced inward by `[1, tooth_height)`, matching Windows' own *unseeded* `Random.Next` per
  application — every application looks organically different, by design, same as Windows, not
  nondeterminism to fix) filled with the source image, optionally piped through `drop_shadow_image`
  when `generate_shadow` is set (Windows: `TornEdgeEffect` extends `DropShadowEffect`,
  `GenerateShadow` defaults true) — confirmed live this compounds the padding (tear's own
  `shadow_size` pad, plus another full `shadow_size` pad from the chained shadow call, so a 100×200
  image becomes 128×228 with defaults, not 114×214 — traced and confirmed correct, not a bug, the
  first time it came up during verification).
- **Remove Transparency, Resize, Drop Shadow, Torn Edge all have settings dialogs** — Remove
  Transparency's is a plain `Gtk.ColorChooserDialog` (matching Windows' own bare `ColorDialog`, no
  custom UI beyond the fill color); Drop Shadow/Torn Edge follow Windows' real left-click-instant
  vs. right-click-opens-settings split (`_do_drop_shadow`/`_do_torn_edge` instant-apply the last-used
  settings; `_do_drop_shadow_settings`/`_do_torn_edge_settings` open a dialog, then apply) — except
  triggered from separate menu items here (`Drop Shadow` / `Drop Shadow Settings...`) rather than a
  left/right-click distinction on one toolbar button, since this port uses menus, not that toolbar
  widget, for these actions. **Settings are session-only** (an instance dict, `self._drop_shadow_settings`/
  `self._torn_edge_settings` in `EditorWindow.__init__`), not persisted across app restarts the way
  Windows' `EditorConfiguration.DropShadowEffectSettings`/`TornEdgeEffectSettings` are — a deliberate
  scope reduction, not silently dropped.
- **Enlarge Canvas / Shrink Canvas have no menu entry at all** — faithfully matching Windows, which
  has no menu/toolbar button for either, only `Ctrl+Shift++`/`Ctrl+Shift+-`
  (`ImageEditorForm.cs:1164-1171`). A real disambiguation problem surfaced implementing this: GDK
  reports the *already-shifted* keyval for a character like `+` (unlike Windows' separate
  KeyCode/Modifiers model), so "Ctrl++" (zoom in) and "Ctrl+Shift++" (enlarge canvas) can report the
  identical keyval on keyboards where typing `+` itself requires Shift — resolved by checking Shift
  state explicitly to route between the two pairs, not by keyval alone. `Ctrl+Delete` (Clear,
  matching `ClearToolStripMenuItem`'s shortcut) vs. plain `Delete` (removes the selected shape,
  pre-existing) needed the same kind of explicit modifier-based disambiguation — previously `Delete`
  fired unconditionally regardless of Ctrl.
- **Undo/redo — a new memento type, now genuinely in scope.** `core/history.py`'s own module
  docstring previously said `SurfaceBackgroundChangeMemento` (undoing a whole-image effect) was "out
  of scope... needs a 'Surface' document concept (base image + Layer) that doesn't exist yet" —
  revisited now that `EditorWindow` provides exactly that. `BackgroundChangeMemento` restores both
  the base image *and* every annotation element the effect repositioned (via `core/tools.py`'s new
  `scale_shape`/`rotate_shape_90`, added alongside the pre-existing `translate_shape`, all three
  following the identical per-shape-type dispatch pattern) — never merges, matching the source
  (`Merge()` always `false`; every effect application is its own separate undo step). A genuine bug
  caught by the round-trip test before this ever reached the UI: the first implementation swapped
  `before_image`/`after_image` in the memento `restore()` returns, so redo silently re-applied the
  *undo* instead of the original effect — `TestBackgroundChangeMemento::test_full_undo_redo_round_trip_via_the_stack`
  failed immediately, exactly the kind of bug this session's TDD-first discipline exists to catch
  before live verification, not during it.
- **`EditorWindow.base_image` is now a property**, not a plain attribute — its setter rebuilds the
  cached Cairo surface, resizes the canvas/window to the new image's dimensions (reusing zoom's own
  `_resize_canvas_and_window`, factored out of `_set_zoom` for this), and updates the status bar's
  dimensions label, all in one place — so `BackgroundChangeMemento.restore()` on undo/redo gets
  correct resizing "for free" just by assigning `target.base_image = ...`, with no separate
  undo/redo-specific resize logic needed anywhere.
- Verified live end-to-end for every effect: pixel correctness (grayscale/invert exact values),
  canvas growth/shrinkage amounts, element repositioning (translate for border/enlarge/shrink/shadow/
  torn-edge, scale for resize, rotate for rotate-90 — including a full 4-rotations-returns-to-original
  property test), full undo/redo round trips restoring image + elements + canvas/window size +
  dimensions label together, every keyboard shortcut (including the Ctrl+Z-vs-bare-Z and
  Ctrl+Delete-vs-Delete and Ctrl++-vs-Ctrl+Shift++ disambiguations), the aspect-ratio-lock live
  auto-sync in the Resize dialog, and that every "Image" menu item actually invokes its handler —
  all with synthetic image data, never real desktop content.

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

### Advanced print options (faithful port of `PrintOptionsDialog`/`PrintHelper`)
**Status: done.** Research first corrected a speculative earlier backlog note (this file's own prior
guess at scope) against the actual source, catching several wrong assumptions before implementing
anything — e.g. the note assumed "grayscale/monochrome/invert" were one uniform effects set; the
real source shows grayscale is a printer-driver flag with **no pixel processing at all** in Windows
(`PrintHelper.cs:111-114`, `DefaultPageSettings.Color = false`), while monochrome and invert are
real per-pixel effects. This port implements grayscale as a real pixel effect anyway (a deliberate,
documented deviation) — there's no printer driver to delegate to for the
`Gtk.PrintOperationAction.EXPORT` path this project verifies against, and it keeps grayscale
consistent with how the editor's own Effects menu treats it.

- **`core/print_layout.py`** (pure, tested): `compute_print_layout` faithfully ports
  `PrintHelper.DrawImageForPrint`'s rotate/scale/center math (`PrintHelper.cs:183-264`) —
  `should_rotate_for_orientation` checks a real page-vs-image orientation *mismatch*
  (`PrintHelper.cs:222-225`), not a simple width>height comparison; shrink and enlarge are
  independently gated booleans sharing one aspect-preserving fit computation
  (`ScaleHelper.GetScaledSize`, min of width/height scale factors — aspect ratio is always
  preserved); not centering aligns top-left, except Windows flips that to top-right after a
  rotation to keep the result visually sane (`PrintHelper.cs:228-231`) — all faithfully ported.
- **Color mode** (`core/effects.py`): reuses the *same* `grayscale_image`/`invert_image` the
  editor's Effects menu uses (task #36), plus a new `monochrome_image` (threshold-based
  black/white, default threshold 127 matching `OutputPrintMonochromeThreshold`,
  `ICoreConfiguration.cs:198-201`) — confirmed via source it's a **flat, unweighted** RGB average
  (`(R+G+B)/3 > threshold`), deliberately *not* the same luma-weighted formula grayscale uses; a
  test exercises an input (pure green) where the two formulas actually disagree, to prove the
  distinction is real and not accidentally identical. Monochrome and grayscale are mutually
  exclusive radios (matching Windows), invert is an independent checkbox layered on top of either.
- **Print options dialog** (`ui/printing.py`'s `_show_print_options_dialog`) — a standalone
  `Gtk.Dialog` (matching every other options dialog in this project), shown before
  `Gtk.PrintOperation.run()` unless `prompt_options` is off, with a "Page layout settings" group
  (shrink/enlarge/rotate/center/footer, all matching Windows' real defaults: shrink **on**, enlarge
  **off**, rotate **off**, center **on**, footer **on**) and a "Color settings" group (full color /
  grayscale / monochrome radios + an independent invert checkbox), plus "Save options as default and
  do not ask again" (checking it flips `prompt_options` off for future prints, matching
  `PrintOptionsDialog.cs:46`). **Deliberately does not use `Gtk.PrintOperation`'s
  `create-custom-widget` signal** (which would embed these controls as a tab inside the native print
  dialog) — Windows itself shows its own separate dialog *after* the OS print dialog
  (`PrintHelper.cs:105,139`), not merged into it, and a standalone dialog makes "don't ask again"
  skip the dialog entirely on future prints, which `create-custom-widget` can't do (it always
  renders whenever the native dialog is shown).
- **Settings persistence** (`settings.py`'s `PrintOptions` dataclass + `get_print_options`/
  `set_print_options`): bundled as one dataclass rather than 9 separate flat get/set function pairs,
  since Windows always edits and applies all of them together too — stored as one nested JSON object
  rather than 9 top-level keys.
- **Footer text**: real, drawn via `context.create_pango_layout()` (not the editor's own
  `ui/render.py` Pango helper, which is built for screen-DPI rendering) so it's sized correctly
  against the print context's actual DPI, not screen DPI — confirmed this distinction matters via
  research before implementing. Page height is reserved for the footer *before* the fit/center math
  runs, matching `PrintHelper.cs:217`. **Simplified from Windows' own footer pattern** (a
  configurable `${capturetime:d"D"} ${capturetime:d"T"} - ${title}` string,
  `ICoreConfiguration.cs:207-209`) to a plain print-time timestamp with no `-${title}` suffix and no
  configurable pattern — this port doesn't track a per-capture title/window-name metadata through to
  printing the way Windows' `CaptureDetails` does. A deliberate, documented scope reduction.
- **Rotation implementation**: physically rotates the numpy pixel array first (reusing task #36's
  `rotate_90_image`, matching Windows' own `image.RotateFlip` approach of rotating the bitmap rather
  than transforming the draw call), then does a plain scale+paint — avoided a much trickier live
  Cairo rotation-transform derivation by reusing already-tested code instead of writing new,
  unverified transform math.
- **No custom printer-enumeration/selection UI** — confirmed live via introspection that
  `Gtk.PrintUnixDialog`/`Gtk.Printer`/`Gtk.PrintJob` aren't exposed via GObject-Introspection at all
  in this GTK3 build (`AttributeError` on each), a known limitation of `gtk_enumerate_printers()`'s
  callback signature not being introspectable. `Gtk.PrintOperation.run()` already shows a complete
  native dialog with its own printer picker, covering the same practical need. Windows' "one
  destination menu item per installed printer" (`PrinterDestination.cs`) would need a new dependency
  (`pycups`, confirmed available on this machine but not currently a project dependency) or shelling
  out to `lpstat` just to replicate something the native dialog already provides — not implemented,
  a deliberate scope reduction.
- **A real GTK API bug caught during live verification, not assumed from docs**: initially called
  `context.create_pango_layout(text)`, matching a plausible-looking pattern — failed immediately with
  `TypeError: create_pango_layout() takes exactly 1 argument (2 given)`. The correct call is
  `context.create_pango_layout()` (no arguments) followed by a separate `layout.set_text(text, -1)`
  call - fixed and re-verified.
- Verified live end-to-end: the print options dialog's real widgets (checkbox/radio defaults exactly
  matching Windows, correct capture of changed values and the "don't ask again" flip); settings
  persistence causing `print_image` to skip the dialog entirely on a subsequent call (sandboxed to a
  temp `XDG_CONFIG_HOME`, never the real config file); color-mode pixel math; and the actual
  Cairo/Pango drawing path via `Gtk.PrintOperationAction.EXPORT` to a real PDF, rendered back with
  `pdftoppm` and checked **numerically** (never viewed as an image) — confirmed centered placement,
  correct aspect-preserving scale, footer text presence, and a real 90-degree rotation (a landscape
  100x40 source image correctly rendered as a tall 40x100 shape on a portrait page) - all with
  synthetic solid-color test images, never real desktop content.

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
- `src/greenshot_linux/resources.py` + `resources/greenshot-linux.png` (new): the app's real logo
  asset (a dotted-ring "G" mark, user-supplied), bundled and used for every icon surface -
  `Gtk.Window.set_default_icon_from_file` in `do_startup` for the window/taskbar icon (previously
  unset, i.e. a generic default), `Gtk.StatusIcon.set_from_file` for the tray icon (previously
  `applets-screenshooter`, a generic theme icon), and the autostart `.desktop` entry's `Icon=` field.
  One shared real asset rather than a separate hand-drawn recreation per surface (an earlier Cairo-
  drawn dotted-G prototype for the tray icon specifically was built and looked reasonable, but was
  dropped in favor of the actual source image once available, per explicit request - "this is
  supposed to be a port").
- **Bug fixed after initial ship, reported live**: triggering a capture hotkey while `EditorWindow`
  was already open produced a confusing silent no-op - no capture overlay, no destination picker, no
  new editor - though the app didn't hang. Root cause wasn't pinned down with certainty (Cinnamon/
  Muffin focus-stealing prevention likely keeps a newly-created override-redirect overlay from
  actually receiving input while the editor already holds focus - confirmed empirically that a
  separate suspect, `EditorWindow`'s `self.connect("destroy", Gtk.main_quit)`, was *not* the cause:
  it turned out to be a harmless no-op against the real `Gtk.Application`-driven app - `Gtk.main_quit`
  has nothing to quit when `Gtk.Application.run()`, not `gtk_main()`, is what's driving the loop -
  confirmed by reproducing it in isolation, though it was still a leftover from early standalone-
  script testing that printed a spurious `Gtk-CRITICAL` on every editor close). Fixed at the product
  level instead of chasing the exact WM interaction: `GreenshotApplication` now tracks open
  `EditorWindow` instances (`register_editor_window`/`unregister_editor_window`, called from the
  window's `__init__`/`destroy` via `Gio.Application.get_default()`) and every capture-trigger method
  (`start_region_capture` and its four siblings) declines to start a new capture while one's open,
  presenting the existing editor instead - both avoids the whole class of overlapping-capture bugs
  and matches the reasonable expectation that starting a new capture mid-annotation isn't something
  you'd want anyway. Verified live end-to-end (open an editor, confirm a capture call is blocked and
  the existing editor is presented; close it, confirm capture calls go through again; confirmed the
  `Gtk-CRITICAL` warning is gone on close too).
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

**Fixed a real crash on non-Cinnamon desktops: hotkey auto-configuration now checks schema
availability first, instead of hard-aborting the whole app.** Found by actually installing the
rebuilt `.deb` on Ubuntu 26.04/GNOME in a VirtualBox VM (first real cross-distro test since this
project targeted Mint specifically) — the app died on launch, before the first-run dialog even had
a chance to appear:
```
GLib-GIO-ERROR **: Settings schema 'org.cinnamon.desktop.keybindings.media-keys' is not installed
Aborted (core dumped)
```
`GLib-GIO-ERROR` (as opposed to `-CRITICAL`/`-WARNING`) means GLib called `g_error()` internally,
which unconditionally calls `abort()` afterward — a hard C-level process termination, not a Python
exception, so nothing in this codebase's own `try`/`except` could ever have caught it regardless of
where it was placed. `hotkey_setup.py`'s `check_all_conflicts` (called from `first_run_setup.py`
before the dialog is built) reaches `GioSettingsBackend` for `MEDIA_KEYS_SCHEMA`
(`org.cinnamon.desktop.keybindings.media-keys`), which doesn't exist outside Cinnamon at all. Fixed
with `hotkey_setup.cinnamon_keybindings_available()` - a read-only `Gio.SettingsSchemaSource.get_
default().lookup(CUSTOM_LIST_SCHEMA, True)` check (confirmed live: returns a real schema object for
`org.cinnamon.desktop.keybindings` on this Mint machine, `None` for a made-up nonexistent schema) -
checked in `_run_dialog` *before* `check_all_conflicts` or `GioSettingsBackend` are ever reached.
When unavailable, hotkey checkboxes are replaced with an explanatory message and manual-binding
instructions (the exact `executable --capture-*` command for each of the four `DEFAULT_HOTKEYS`) -
autostart is still offered either way, since `install_autostart_entry` is a plain XDG `.desktop`
file with no Cinnamon dependency. Verified with the real fix: rebuilt the `.deb`, reinstalled it in
the same VM, confirmed the app now launches and shows the fallback dialog correctly instead of
crashing. A separate, non-fatal `Gtk-CRITICAL **: gtk_widget_get_scale_factor: assertion
'GTK_IS_WIDGET (widget)' failed` still appears on that same GNOME desktop even with this fix in
place - not called anywhere in this codebase (only `Gdk.Monitor.get_scale_factor()` exists, in
`capture/x11.py`, a different function entirely), likely internal-GTK/theme-engine, not reproducible
on the Mint dev machine, tracked separately rather than guessed at.

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

### Wayland (task #49)

First actual test against a Wayland session (Ubuntu 26.04 desktop in a VirtualBox VM, confirmed via
`$XDG_SESSION_TYPE=wayland`), installing the real `.deb` and running `greenshot-linux
--capture-region` for real. Scoped precisely what does and doesn't work, rather than assuming
"Wayland = broken":

- **Works fine via XWayland compatibility**: the overlay window itself, the OS crosshair cursor,
  the full-screen guide-line crosshair + coordinate tooltip, the magnifier loupe chrome, drag-to-
  select tracking and the live "W x H" size label, releasing into the destination picker, opening
  the editor. All genuine GTK/X11-protocol interaction, handled transparently.
- **Cursor auto-capture (XFixes) still works** even under Wayland - the auto-captured cursor glyph
  showed up correctly composited into the (otherwise black) captured image. `XFixesGetCursorImage`
  apparently isn't blocked the way core screen-content reading is.
- **Actual screen pixel capture returns black/empty.** `capture/x11.py`'s `X11CaptureBackend.grab`
  uses the classic `XGetImage`-style X11 API to read screen content - Wayland's compositor
  deliberately blocks that for any client (X11 or native) as a core security/anti-spying feature,
  by design, not a bug to patch in the existing path. This is the actual, now-confirmed reason
  Wayland support needs a fundamentally different capture mechanism.
- **A second, related limitation**: `Gdk-Message: Window 0x... is a temporary window without
  parent, application will not be able to position it on screen` - client-side absolute window
  positioning (`region_select.py`'s `RegionSelectWindow.move()`, needed for the POPUP overlay's
  exact multi-monitor geometry) is also restricted by the Wayland compositor, separate from the
  capture issue. Not yet addressed - out of scope for the capture backend itself.

Net: the interactive/UI layer of this app is largely Wayland-ready already, almost by accident (GTK3
+ XWayland compatibility carries most of it); pixel capture was the real blocker.

**Capture mechanism: `org.freedesktop.portal.Screenshot`, not `ScreenCast`+PipeWire.** Initial
assumption was ScreenCast (video-stream-oriented), corrected after checking the actual portal
interface spec: `Screenshot` (v3) is the purpose-built one-shot capture API - no new dependency
beyond `Gio`, already used elsewhere in this project (`hotkey_setup.py`'s GSettings calls). The
D-Bus mechanism (call `Screenshot`, get a `Request` object path back, wait for its `Response`
signal, bridged to a synchronous call via a nested `GLib.MainLoop` - the same category of trick
`Gtk.Dialog.run()` already relies on) was validated with a standalone script against the real
portal backend (Mutter, Ubuntu 26.04) before writing any production code: it returned
`response_code=0` and a real, valid PNG uri (`file:///home/.../Pictures/Screenshot.png`, 1366x768
RGBA), confirmed independently by inspecting the file on disk. No permission dialog appeared during
that test - open question whether that's specific to this unsandboxed/non-Flatpak deployment mode,
a policy the portal backend remembered, or something else; not yet explained.

**Implemented**: `capture/wayland_portal.py` (`request_screenshot()` - the D-Bus mechanics, cleaned
up from the validated prototype) and `capture/wayland.py` (`WaylandCaptureBackend`, implementing the
same `CaptureBackend` protocol as `X11CaptureBackend`: `screen_layout()` delegates to the
now-shared `capture/gdk_screen_layout.py` - extracted from `x11.py` since monitor enumeration is
pure GDK, not X11-specific, so both backends need the identical logic; `grab(rect)` requests a full
screenshot from the portal, loads the returned PNG, and crops to `rect` client-side, since the
portal has no notion of "just this rect"). `capture/backend_select.py` centralizes backend choice
(checks `XDG_SESSION_TYPE` once, used by all four of this app's capture call sites) rather than each
call site (`capture_modes.py`, `eyedropper.py`, `window_picker.py`, `region_select.py`) picking
X11 individually - this can't be "try X11, fall back on failure": a Wayland root-window read
doesn't raise, it silently returns black, so there's nothing to catch.

The crop math assumes the portal's returned image starts at the virtual screen's own origin
(`bounds.left`, `bounds.top`) - true for the VM's single monitor (`bounds.left == 0`), **not yet
verified against a real multi-monitor Wayland session**, where a monitor left of the primary gives
`bounds.left < 0`.

**Live-verified end to end** (Ubuntu 26.04 VM, real portal backend): `WaylandCaptureBackend`
imported and exercised directly (not just the raw D-Bus prototype) - `screen_layout()` reported one
1366x768 monitor; `grab(virtual_bounds)` returned a `(768, 1366, 4)` uint8 array; `grab()` on a
100x80 sub-region returned the correct shape, and its pixels matched the corresponding slice of the
full-screen grab exactly (0.0000 fraction differing) - confirming the crop-offset math is correct
against a real captured screenshot, not just the synthetic unit-test data. Verification script only
ever printed shape/dtype/numeric summaries, never rendered or saved the captured content.

**Minor open finding from that same run**: the VM's single monitor reported `is_primary=False` from
GDK (`display.get_primary_monitor()` returned None, and the monitor's own `is_primary()` was also
False) - `ScreenLayout.primary` already falls back to the first monitor when none is marked primary,
so this didn't break anything for a single-monitor session, but it suggests GDK's primary-monitor
concept may not be reliably reported under Wayland. Only matters once there's a real multi-monitor
Wayland setup to test full-screen-capture's primary-monitor logic against - not investigated further
since it's outside what task #67 needed to prove.

**Still unresolved as of 2026-08-04**: the overlay absolute-positioning warning noted above (task
#68 - needs a per-monitor multi-window rebuild of the region-select/window-picker/eyedropper
overlays, since Wayland forbids clients from setting absolute screen position at all, the same
category of restriction as direct capture); the multi-monitor crop-offset assumption, still
unverified against a real multi-monitor Wayland session. Window enumeration (below) is resolved for
GNOME specifically.

#### Task #68 progress (2026-08-05): region-select and window-picker done, eyedropper in progress

Built the multi-window architecture this was scoped to need: `ui/monitor_window.py`'s
`MonitorWindow` - one `Gtk.WindowType.TOPLEVEL` per monitor, each `fullscreen_on_monitor()`'d onto
its own output instead of the single `POPUP`+absolute-`move()` trick X11 uses. No cross-window
pointer grab needed for region-select/window-picker: whichever window is physically under the
cursor naturally receives its own events (guaranteed compositor behavior), each window translating
its own local coordinates to/from the shared global (virtual-screen) coordinate space at the
boundary. `ui/region_select_wayland.py` and `ui/window_picker_wayland.py` are the two working
implementations; `ui/eyedropper_wayland.py` is still being debugged (see below). X11's existing
single-window implementations are completely untouched.

Real findings along the way, not assumptions:

- **No keyboard grab needed, unlike X11.** X11's overlays need an explicit `Gdk.Seat` keyboard grab
  because `POPUP` (override-redirect) windows never get real window-manager focus at all. These are
  plain `TOPLEVEL` windows, which Mutter focuses normally on mapping (confirmed live, same session
  that found GNOME auto-focuses newly-shown windows regardless of hints - see the window-picker
  section above). Grabbing anyway also triggers Wayland's keyboard-shortcuts-inhibit permission
  dialog (a real, easy-to-miss async consent prompt: "Allow inhibiting shortcuts") for no benefit.
- **Wayland popup menus need a real, still-alive anchor window, not the root window.** The
  destination picker's `Gtk.Menu.popup_at_rect()` call already anchored to
  `Gdk.Screen.get_default().get_root_window()` for X11 (its own earlier fix, see that module's
  docstring) - under Wayland this fails outright (`Gdk-WARNING: Couldn't map as window ... as popup
  because it doesn't have a parent`), landing the menu at some fallback position instead of where
  requested. Fix: `destination_picker.py` gained an `anchor_window`/`anchor_local_pos` pair; the
  Wayland overlays keep whichever one of their `MonitorWindow`s covers the release point alive
  (destroying the rest immediately) specifically to serve as that anchor, then destroy it once the
  menu's `deactivate` signal fires.
- **Calling the portal from inside an already-active event handler hangs indefinitely - confirmed a
  genuine reentrancy problem, not latency.** Window-picker's `Activate()`+fresh-grab (task #69) run
  directly inside `button-press-event` hung for several minutes with no response, including its own
  120s internal timeout never firing - meaning the nested `GLib.MainLoop` the portal call spins up
  wasn't processing *any* of its own sources, not just waiting on the compositor. Fix pattern:
  `GLib.idle_add()` the actual portal work so it runs on a fresh top-level main-loop iteration,
  *after* the triggering event has fully finished dispatching - but see the eyedropper notes below
  for where this pattern alone isn't sufficient.
- **Wayland's popup grab must be requested synchronously within the triggering input event -
  deferring it breaks it ("no trigger event for menu popup").** This directly conflicts with the
  reentrancy fix above for anything that needs to *both* show a popup *and* call the portal in
  response to the same click. Resolution for window-picker: show the destination picker immediately
  (synchronously, using the frozen-backdrop crop as a placeholder image), and only resolve the real
  `Activate()`+fresh-grab pixels once the user actually picks a menu item - itself a fresh,
  non-nested dispatch by the time it fires, not subject to either constraint.
  `destination_picker.py`'s new `refresh_image` parameter (a zero-arg callable, called lazily) is
  the general mechanism for this.
- **Fullscreen surfaces are forced opaque by Mutter - deliberately, not a bug.** The eyedropper is
  the one overlay that actually needs live transparency (it shows the real desktop through a mostly
  invisible window, with just a magnifier loupe drawn on top). Confirmed live: even with an explicit
  RGBA visual *and* an explicit empty opaque-region hint *and* clearing to `rgba(0,0,0,0)` via
  `OPERATOR_SOURCE`, a `fullscreen_on_monitor()`'d window still renders solid black everywhere except
  what's explicitly painted. This is Mutter's own documented policy, not a client-fixable bug -
  confirmed against Mutter's own GitLab tracker ("Transparent fullscreen windows render black
  background", #2520) and matching Ubuntu/Fedora bug reports, with the maintainers' own stated
  reasoning: avoiding a performance hit for fullscreen games that accidentally used RGBA instead of
  RGBX. The protocol that would give real transparency instead (`wlr-layer-shell`, what
  `gtk-layer-shell`-based tools use on every other major compositor) is explicitly not implemented by
  Mutter (GNOME's own tracking issue, #973, is still an open feature request). Resolution: the
  Wayland eyedropper paints a frozen backdrop instead, exactly like region-select/window-picker
  already do - not a compromise unique to this project, the same tradeoff other real tools
  (Flameshot) make on GNOME specifically by delegating to the portal's native picker instead.
  Concrete user-facing consequence, documented for whoever revisits this: the picked colour reflects
  screen content at the moment the eyedropper drag *started*, not the moment of release (a hover-
  state colour change under the cursor wouldn't be reflected) - a live per-motion portal re-grab
  would be far too slow for a smooth drag anyway.

Two genuinely pre-existing, cross-platform bugs were found and fixed along the way - neither is
Wayland-specific, both would affect X11/Cinnamon too, just hadn't been exercised/noticed before:

- **`editor_window.py`'s tool-palette buttons never cleared `selected_shape`.** `visible_style_fields`
  (task #57) always prioritizes a selected shape's own fields over the active tool's - correct for
  clicking an *existing* shape on the canvas, but `_on_tool_button_toggled` was also hitting this
  path, meaning any residual selection (including the auto-inserted cursor shape every editor opens
  with) shadowed whatever tool was actually just clicked, hiding the whole style panel for every real
  drawing tool. Fixed: picking a tool now also clears `selected_shape`.
- **`draw_magnifier`'s single `cursor` parameter conflated two different coordinate spaces.** It's
  used both as the crop-center within `frozen_image` and as the on-canvas draw position - these only
  coincide when `frozen_image` and the drawing context share a coordinate space, true for
  region_select.py's usage (the whole virtual-screen backdrop) but not eyedropper.py's (an
  already-small, pre-cropped patch). Confirmed live: the eyedropper's loupe always rendered pinned
  near the drawing context's own origin, never actually following the cursor. Fixed with a new
  optional `dest_pos` parameter, defaulting to `cursor` (preserving region-select's behavior
  unchanged) but explicitly overridden by both eyedropper.py and eyedropper_wayland.py.

**Eyedropper: done (2026-08-07), after three distinct real bugs found and fixed via live
debugging.** Backdrop loading, colour sampling, and loupe positioning were confirmed working early
on; getting an actual pick to complete without corrupting state took three separate fixes:

1. **Widget-lifecycle race.** `_load_backdrop`'s `GLib.idle_add` callback isn't scoped to whichever
   main loop was active when it was scheduled - it can still be pending when a fast click-release
   tears the overlay down, then fires later against already-destroyed `MonitorWindow`s on the very
   next idle slot (however that got triggered - confirmed live it could be a completely unrelated
   later click). Symptom: a cascade of `Gtk-CRITICAL **: assertion 'GTK_IS_WIDGET' failed` errors.
   Fixed with a `self._alive` flag, set `False` at the start of both teardown paths
   (`_on_button_release`/`_on_key_press`) and checked at the top of `_load_backdrop` before it
   touches anything.
2. **`Gdk.Seat.grab()` doesn't redirect an in-progress gesture to a `TOPLEVEL` window under
   Wayland.** The original design mirrored X11's single continuous press-hold-drag-release (matching
   Windows' `Pipette.cs:111-136`, which uses `SetCapture` for the same effect) via
   `Gdk.Seat.grab(..., Gdk.SeatCapabilities.ALL, ..., press_event, ...)`. Confirmed live: motion and
   release events kept going to the original Eyedropper button, never reaching the overlay - no
   loupe ever appeared, "hangs until Escape." **Redesigned the interaction on both platforms**
   (deliberate divergence from Windows, not just a Wayland workaround - matches how most other
   eyedropper implementations behave anyway): clicking "Eyedropper" now just opens the picking
   overlay; the actual sample happens via a *fresh* press-drag-release that starts within the
   overlay itself, needing no cross-window pointer grab on either platform. X11's overlay now only
   grabs keyboard (still required - `POPUP` windows never get real X keyboard focus on their own);
   Wayland's overlay needs no grab at all, matching region-select/window-picker's existing pattern.
3. **`Gtk.Dialog.run()` holds a GTK-level modal grab (`gtk_grab_add`) for its whole duration,
   independent of window-manager/compositor focus.** Even after fix #2, clicking/dragging on the
   Wayland overlay still did nothing, and Escape still closed the whole dialog directly. Diagnosed by
   querying GNOME Shell's own window list via the bundled window-calls extension
   (`org.gnome.Shell.Extensions.Windows.List`, see task #69 below) while the overlay was up: it
   reported `focus: true` for the overlay window, proving compositor-level focus was NOT the problem
   - the redirect was happening client-side, inside GTK's own event dispatch, independent of what the
   window manager thought had focus. `start_eyedropper()` now suspends whatever `Gtk.grab_get_current()`
   returns before showing either platform's overlay (`widget.grab_remove()` - note: exposed as an
   instance method in PyGObject, not `Gtk.grab_remove(widget)`) and restores it (`widget.grab_add()`)
   once the eyedropper finishes, on both platforms - this is a GTK concept, not X11/Wayland-specific,
   and X11's old explicit pointer grab most likely only masked the same underlying issue rather than
   needing a genuinely different mechanism.

All `[TRACE]` print statements added during this debugging have been removed from
`ui/eyedropper_wayland.py` and `ui/monitor_window.py`.

**Known follow-up, not a blocker (task #71):** dragging quickly in the Wayland eyedropper shows the
loupe's top rows not rendering/flickering when moving up, and right-side rows when moving right -
directionally correlated with drag speed. Confirmed live NOT present in the X11 eyedropper on the
real Mint machine, narrowing this to something specific to Wayland's frozen-backdrop-slice approach.
No bug found on inspection of `ui/magnifier.py`/`ui/cairo_convert.py` (crop/clamp math and the
Cairo/numpy conversion both look correct regardless of movement direction). Leading, unconfirmed
hypothesis: `_on_draw` repaints the *entire* large cached backdrop surface on every single motion
event before drawing the small loupe on top, unlike X11's genuinely-transparent overlay which never
repaints a large surface per frame - under this VM's likely software-rendered Wayland compositor,
that could produce visible incomplete-frame artifacts during rapid redraws. Worth checking whether
restricting the repaint to just the loupe's own region fixes it.

**Also flagged, not yet done (task #72):** checked the real Windows source
(`ColorDialog.Designer.cs:223-232`, `Pipette.cs`) for whether the Transparent/Eyedropper buttons
should have icons. `btnTransparent` is plain text in Windows too (matches this port already), but
the real Eyedropper is not a text button at all - it's the `Pipette` control (a `Label` subclass)
with `pipette.Image` set to a small bitmap, no text. This port's plain `Gtk.Button(label="Eyedropper")`
is a real, not-yet-fixed deviation.

### Tray icon under Wayland (tasks #66 and #70, 2026-08-07)

`Gtk.StatusIcon` relies on XEmbed, which has no Wayland equivalent - confirmed live it never actually
embeds (`is_embedded() == False`), and its internal icon-scaling code throws a Gtk-CRITICAL
(`gtk_widget_get_scale_factor: assertion 'GTK_IS_WIDGET' failed`) trying to render an icon with no
real widget backing it. Isolated the exact trigger: `icon.set_from_file()` alone reproduces it. This
turned out to be the same root cause as task #66's warning, not a separate bug - both closed together.
`Gtk.StatusIcon` is also flatly deprecated in GTK3 regardless of platform.

**Fix**: `AyatanaAppIndicator3` (the actively-maintained fork; the original `AppIndicator3` is largely
superseded on modern Ubuntu) for Wayland, keeping `Gtk.StatusIcon` for X11 rather than unifying onto
one mechanism for both. This isn't just code-sharing caution - confirmed live (a standalone test
indicator, both mouse buttons) that AppIndicator has no distinct left-click ("activate") action once a
menu is attached: the real desktop indicator host shows the same menu regardless of which button was
clicked (a long-documented AppIndicator design limitation - see
https://bugs.launchpad.net/bugs/1910521 - not something fixable from this codebase). Unifying would
have meant losing the left-click-for-instant-capture shortcut that already works correctly on X11
(matching Windows Greenshot's own tray default, `start_capture`'s docstring), for no benefit since
nothing was broken there. `app.py`'s `_build_tray_icon()` branches on `XDG_SESSION_TYPE`; menu
construction is shared via `_build_tray_menu()`. Icon loading uses `set_icon_theme_path()` pointed at
the bundled PNG's own directory (this app ships one asset rather than installing into the system icon
theme, same rationale as `resources.py`'s existing docstring). New `.deb` runtime dependency:
`gir1.2-ayatanaappindicator3-0.1` (not a build dependency - imported lazily, only inside the Wayland
branch, so the test suite/build doesn't need it).

**A real regression this surfaced, not caused**: "Repeat Last Region"'s sensitivity was refreshed via
`menu.connect("show", ...)`, which worked fine for `Gtk.StatusIcon` (a real local GTK popup) but never
fires a second time for an AppIndicator-hosted menu - confirmed live via tracing: the "show" signal
only fired once, at `menu.show_all()` during construction, never again on subsequent real opens through
the shell. AppIndicator exports the menu structure to the shell once via dbusmenu; the shell renders
its own copy from then on, so GTK's own "show" signal on the local `Gtk.Menu` object isn't a reliable
signal for "the user is looking at this now" under that mechanism. Fixed by updating
`self._repeat_item`'s sensitivity eagerly in `_remember_region()`, the moment `last_region` actually
changes, rather than lazily at show-time - simpler, and correct on both platforms uniformly.

**Confirmed working end-to-end, live, via the real tray icon** (not a test script - this was the first
time in this whole Wayland effort that a capture flow was exercised through the actual tray-menu round
trip rather than direct script invocation): tray icon renders, menu opens with both mouse buttons,
Capture Region drags/selects/positions the destination picker correctly, Edit opens the editor with
the correct captured image, Repeat Last Region now enables correctly.

**New problems this uncovered, not yet fixed** (real gaps, only found because a real trigger path was
exercised for the first time - not regressions from this change):

- **Clipboard didn't work at all under Wayland (task #74, fixed same day)** - see its own section below.
- **An audible camera-shutter sound plays on destination-picker clicks (task #73)**: confirmed nothing
  in this codebase plays any sound (grepped for sound/beep/shutter/play_sound - nothing found). Leading
  hypothesis, not yet confirmed: `xdg-desktop-portal-gnome` provides this as built-in feedback whenever
  `org.freedesktop.portal.Screenshot`'s `Screenshot()` method is invoked by any app - a GNOME desktop
  feature, not app code - which would also explain why X11/Windows never exhibit it (neither goes
  through that portal). The exact trigger timing hasn't been confirmed live yet.
- **Intermittent destination-picker mispositioning (task #75)**: sometimes still shows centered with
  the same "no trigger event for menu popup"/"doesn't have a parent" warnings as the original
  Wayland-popup bug this project already fixed once (see task #69's `anchor_window` mechanism). Fully
  instrumented `region_select_wayland.py` and `destination_picker.py` with timestamps and state dumps
  across several repro attempts (both fast <1s and slow ~7.5s drags) - every traced attempt showed
  fully valid state (real anchor, real `BUTTON_RELEASE` event, anchor mapped) with no warning, so the
  failure didn't reproduce under tracing. Not yet root-caused; needs either catching it live with
  tracing still active, or a different diagnostic angle.

### Clipboard under Wayland (task #74, fixed 2026-08-07)

`destination_picker.py`'s clipboard-backend selection and `editor_window.py`'s own separate "Copy"
action both unconditionally used `X11ClipboardBackend`, with no Wayland branch at all - unlike every
other backend in this codebase. Centralized both call sites onto a new
`backend_select.default_clipboard_backend()`, matching the existing `default_capture_backend()`
pattern, rather than leaving the platform check duplicated across two files.

**First real fix attempt (omitting `.store()`) did not work** - confirmed via a genuine cross-process
test: a completely separate probe process saw zero clipboard targets and no image, moments after the
app's own "Copy to Clipboard" ran with no errors or warnings at all. Not a downstream MIME-type/format
issue - the clipboard claim itself never reached the Wayland protocol layer.

**Root cause, confirmed via research** (Wayland's own protocol documentation plus `wl-clipboard`'s own
docs), not assumed: a `wl_data_offer` is only valid while the *claiming client has real keyboard
focus*, and `wl_data_device.set_selection()` needs a recent, valid serial tied to that focus.
`Gtk.Menu`'s popup is a Wayland **popup-role** surface - it gets pointer/keyboard *events* forwarded
via its parent's grab, but never receives genuine `wl_keyboard` focus the way a real `TOPLEVEL` window
does. The destination picker's "Copy to Clipboard" menu item was therefore trying to claim the
clipboard from a context that never had valid focus to claim it with, on any compositor without the
`wlr-data-control` protocol extension - which GNOME/Mutter doesn't implement (same story as
`wlr-layer-shell`, see `eyedropper_wayland.py`).

**A wrong intermediate attempt, worth recording so it isn't retried**: explicitly calling
`anchor_window.focus(Gdk.CURRENT_TIME)` (the real, still-mapped `MonitorWindow` kept alive as the
picker's popup anchor) right before the clipboard claim, hoping to give GDK a definitely-focused
surface to work with. This produced a new, real protocol error (`Gdk-Message: Error 22 (Invalid
argument) dispatching to Wayland display`) and did not fix the underlying problem -
`Gdk.Window.focus()` is not a safe call under Wayland (an X11-oriented API with no clean Wayland
mapping). Reverted.

**Real fix**: the same technique `wl-clipboard` itself documents using for compositors without
`wlr-data-control` - `wayland_clipboard.py`'s `WaylandClipboardBackend.set_image()` now briefly shows
an invisible, undecorated 1x1 `TOPLEVEL` window purely to receive genuine compositor-granted focus
(the same natural "TOPLEVEL windows get real focus on mapping" behavior already relied on all through
task #68), and only claims the clipboard once a real `focus-in-event` arrives - not assumed to be
instant. A 1-second `GLib.timeout_add` fallback attempts the claim anyway and cleans up if focus never
arrives, rather than hanging indefinitely the way `wl-clipboard` itself can. Confirmed live: copy then
paste into a separate paint app now works correctly. One confirmed, expected, and accepted minor
cosmetic side effect - the same one `wl-clipboard`'s own documentation warns about - a brief taskbar/
window-list reflow is visible right when the invisible window briefly maps, live-confirmed by the
user.

Not guaranteed on every compositor (confirmed via `wl-clipboard`'s own documented caveat, not just
this project's own testing): compositor focus-granting policy for a newly-mapped window isn't
standardized by the Wayland protocol itself, so this technique's reliability could differ on a
non-GNOME Wayland compositor. The timeout fallback exists specifically so a compositor that never
grants focus degrades to "clipboard silently doesn't work" (the pre-fix behavior) rather than hanging.

This makes `ClipboardBackend.set_image()` fire off asynchronous work under Wayland rather than
claiming the clipboard before returning - acceptable since the Protocol's contract was always
fire-and-forget (no caller ever waited for or checked a result).

### Shell-side rewrite of the Wayland overlays (task #77, planned 2026-08-07, complete 2026-08-08)

**What this is for.** Tasks #75/#76 both trace back to the same root cause: region-select/window-
picker/eyedropper's Wayland overlays (task #68) are real, separate `Gtk.WindowType.TOPLEVEL` client
windows - Mutter treats a real application window being mapped/unmapped as a normal window-lifecycle
event, and other Shell UI (the dock, possibly other extensions) reacts to that, producing the
window-list/dock reflow task #76 describes. Confirmed by elimination, not assumed: ruled out the
clipboard mechanism (identical reflow with both the GNOME-extension and invisible-window clipboard
techniques, and on non-clipboard actions like Save/Edit too), ruled out `dash-to-dock`'s own
`intellihide` setting (`dock-fixed=true` had no effect), and ruled out desktop notifications (a live
`dbus-monitor` session watching `org.freedesktop.Notifications` showed nothing fired during a
reproduction). Confirmed by comparison, not assumed either: read Gradia Capture's actual source
(`gradia-companion`, GPL-3.0) and found its selection UI hooks directly into GNOME Shell's own native
screenshot UI (`Main.screenshotUI`) via Clutter/St actors added to Shell's own UI group - genuinely no
separate window at all, which is *why* it doesn't hit this. Checked Mark-Shot too: no companion Shell
extension, a standalone Qt app using `wlr-layer-shell` (which Mutter doesn't implement) for its own
overlay - architecturally in the same position as us, just a different toolkit.

**The decision, made explicitly, not the default choice**: rather than use GNOME's own native
screenshot UI directly (which would mean giving up this project's own magnifier loupe, crosshair, and
faithful-to-Windows-Greenshot look), reimplement this project's *own* overlay UI as GNOME Shell
extension code - Clutter/St actors drawn on Shell's own stage, the same category Gradia's approach
belongs to, just built from scratch rather than piggybacking on Shell's existing screenshot UI.
Deliberately scoped to GNOME specifically (not a generic Wayland solution) - consistent with this
project's already-GNOME-specific window-calls and greenshot-linux-clipboard extensions. Accepted
tradeoff, explicit: Mint/Cinnamon's own eventual Wayland session will need this revisited separately
once Cinnamon ships one (a different shell/extension system entirely, no path to reusing this code -
same scope boundary already documented for window-calls in the Window-picker section below). Accepted
as reasonable because Mint, Ubuntu, and Debian's GNOME spin between them cover the realistic majority
of "Windows user trying Linux" landings this project targets.

**Architecture change.** Currently: the Python app creates and owns the interactive overlay directly
(`ui/monitor_window.py`'s `MonitorWindow`, one real `TOPLEVEL` window per monitor, `fullscreen_on_
monitor()`'d, drawing via Cairo and handling all input via GTK signals, all in Python). After this
rewrite: the bundled Shell extension gains a new D-Bus-exposed "start an interactive selection"
capability; when called, the *extension itself* builds and drives the entire interactive UI using
Shell-internal APIs only (Clutter actors on `global.stage`/`Main.uiGroup`, `St.DrawingArea` or
equivalent for backdrop/magnifier/crosshair rendering, Clutter's own event handling for press/motion/
release/key) - no window is ever created by either side. Once the user completes or cancels, the
extension reports the result back to the Python app (selected rect / window id / picked color), which
then proceeds exactly as it does today from that point on - destination picker, clipboard, editor,
etc. are all unaffected by this rewrite and need no changes.

**Concrete pieces to move into the extension (GJS/Clutter/St), per overlay:**
- **Region-select**: frozen-backdrop rendering, drag-to-select rectangle + dim-outside-selection,
  the magnifier loupe + aiming crosshair + size label (`core/magnifier.py`'s positioning math needs a
  careful, deliberate port to JS - simple enough arithmetic that this is a reasonable risk, not a
  rewrite-from-scratch), Escape/M-key handling, cursor-shape auto-capture sampling.
- **Window-picker**: hover-highlight rendering over real window geometry, click-to-select + activate.
  Worth checking during implementation whether this can use `Meta.Window` directly (Shell already has
  this data natively) rather than round-tripping through the bundled window-calls extension's own
  D-Bus interface, now that the caller is Shell-side too.
- **Eyedropper**: frozen-backdrop rendering (shared with region-select), the two-step click-then-drag
  gesture (interaction model unchanged, just Shell-side now), magnifier loupe rendering, color
  sampling from the backdrop pixel data.

**Real simplification worth checking during implementation, not assumed yet**: since GNOME Shell's
own native screenshot UI already captures the compositor's content directly (privileged, Shell-side
access, no portal round trip), the extension may be able to capture its own backdrop the same way -
potentially eliminating `wayland_portal.py`'s async D-Bus dance entirely for this specific flow. Needs
confirming what capture APIs are actually reachable from extension code before relying on it.

**D-Bus interface shape, to be finalized during implementation, not fully decided yet**: these
interactions are inherently long-running/interactive (a real user gesture in the middle, not a quick
call), so the Python side must use `Gio`'s *async* D-Bus call machinery (`call`, not `call_sync`) to
avoid blocking its own main loop while waiting - critical given this project's own established
reentrancy lesson (see [[feedback-wayland-portal-reentrancy]] in memory): a nested/blocking wait here
would risk the exact same hang class chased all through task #68's original debugging.

**Migration and testing strategy:**
- Build one overlay at a time, region-select first (most-used, most representative) - verify task
  #76's reflow is genuinely gone (not just reduced) before moving on to window-picker and eyedropper.
- Keep the existing `MonitorWindow`-based Python implementation as the fallback when the extension
  isn't installed/enabled - the same "prefer the extension, fall back gracefully" pattern already
  used for window-calls and the clipboard extension, not a hard replacement.
- No unit tests possible for the new GJS/Clutter code, matching this project's existing "UI glue not
  unit tested" convention - live-verification only, same rigor as everything else, not a lower bar.
- Cross-monitor behavior (already an open, unverified gap from task #68 - see that section) stays
  unverified either way until real multi-monitor hardware is available; this rewrite doesn't change
  that gap's status.
- License: GPL-3.0-or-later, wholly original code, same as `greenshot-linux-clipboard` - not derived
  from Gradia's or GNOME Shell's own source, just built using the same public Clutter/St/Main APIs any
  extension has access to (see that extension's own docstring for the fuller reasoning on this point).

**Open questions to resolve during implementation, not yet answered:**
- Exact modern Clutter/St drawing API surface (GNOME Shell versions have shifted this over time;
  needs checking against the actual shell-version range this project targets, not assumed from an
  older recollection).
- Whether Shell extensions can reach compositor content directly for backdrop capture (see the
  simplification note above) - needs confirming, not assumed.
- Keyboard/pointer input handling from within a Shell extension - Shell already owns global input in
  a way client apps don't, so this is plausibly simpler than every client-side grab problem chased
  this session, but that's an expectation to verify live, not a guarantee.

#### Region-select implementation (2026-08-08): working end-to-end, task #76's reflow fully eliminated

Built and live-verified on the VM (GNOME Shell 50.1/Mutter 18). `StartRegionSelect()`, a new async
D-Bus method on the same bundled `greenshot-linux-clipboard` extension (kept as one extension rather
than adding a third, per the plan above), builds a full-stage `St.Widget` (`RegionSelectOverlay`)
added to `Main.uiGroup`, bound to `global.stage`'s geometry via `Clutter.BindConstraint`, using
`GrabHelper` for input/Escape and `Clutter.PanGesture` for the drag gesture (mirroring GNOME Shell's
own internal `SelectArea` class in `js/ui/screenshot.js` almost exactly, since that turned out to be
the cleanest reference once found). Backdrop capture uses `Shell.Screenshot.screenshot_stage_to_
content()` (no portal round-trip at all - the "real simplification worth checking" above panned out);
the final crop+PNG-encode uses `Shell.Screenshot.composite_to_stream()`, the same privileged API
GNOME Shell's own screenshot UI uses to save files, called with the selected rect directly against the
already-captured texture - one capture, cropped Shell-side, PNG bytes returned straight over D-Bus
(`ay`) alongside the absolute rect, rather than a second client-side capture-and-crop round trip.

**Two of the "open questions" above resolved with real, sometimes-surprising answers, not the assumed
ones:**
- **`Clutter.Canvas` does not exist in this Shell's bundled Clutter fork at all** - confirmed by
  introspecting the live `Clutter-18.typelib` directly (`Object.keys(Clutter)` has no `Canvas`, only
  `Content`/`TextureContent`). GNOME Shell's own `SelectArea` reference (evidently written against an
  older Clutter) uses it; this project's extension does not exist on that source's timeline, so it hit
  this immediately as a live `TypeError: ... Canvas is not a constructor`. **`St.DrawingArea`**
  (`get_context()`/`get_surface_size()`/`queue_repaint()`, a parameterless `'repaint'` signal) is the
  real, current equivalent - confirmed the same way, via `GObject.signal_query()` against the live St
  typelib from inside a real `gjs` process with Mutter's typelib path set
  (`GI_TYPELIB_PATH=/usr/lib/x86_64-linux-gnu/mutter-18:/usr/lib/gnome-shell`), not assumed from an
  older recollection or from reading Shell's own (evidently stale, for this purpose) source.
- **A single `<node>` XML document with two `<interface>` elements does not work with
  `Gio.DBusExportedObject.wrapJSObject()`** - confirmed against GJS's own source
  (`modules/core/overrides/Gio.js`): it parses via `Gio.DBusInterfaceInfo.new_for_xml()`, singular,
  which only picks up one interface. A second single-interface `wrapJSObject()` call exported at the
  *same* object path is also silently a no-op (confirmed live: `gdbus call` against the second
  interface came back "No such interface", with `enable()` itself reporting no error either way, in
  either wrong attempt). The working shape: two separate `Gio.DBusExportedObject`s, two separate
  object paths (`.../GreenshotClipboard` and `.../GreenshotCapture`), one extension, one `enable()`.

**A packaging/deployment gotcha, not a code bug, worth recording so it isn't re-debugged from
scratch:** `gnome-extensions disable`/`enable` does not reliably force GNOME Shell to re-`import()` an
extension's `.js` file after the *first* time it's loaded in a given Shell process - confirmed live,
repeatedly, across several edit-redeploy-reload cycles that kept running stale cached code (visible as
the same, already-fixed error recurring after a fix was deployed and reloaded). A full logout/login
(fresh Shell process) reliably picks up on-disk changes; disable/enable alone was not trustworthy
during this session's iteration. Not yet root-caused further (module caching keyed by file path,
some other extension-manager state - unclear); noting the workaround (full session restart between
meaningful extension.js changes) rather than the cause, which wasn't chased down further given time
already spent.

**Live-verified end to end**: drag-to-select renders correctly (dim-outside-selection, blue border,
matching `region_select.py`'s own constants), Escape/click-outside cancel via `GrabHelper`'s own
built-in handling (no custom code needed, as expected), a completed selection returns a pixel-correct
cropped PNG (confirmed by opening it in the editor and visually comparing to the dragged region), and
- as of the redesign below - the destination picker appears immediately with no window flash, no dock
disappearing, and no black backdrop behind it, repeatably across many captures in a row. Magnifier
loupe, aiming crosshair, and size label are **not yet ported** - this first pass deliberately covers
only the core drag-to-select round trip, matching the migration strategy's "verify the reflow question
before investing in the rest" ordering; see task #79 for a related sizing question to resolve before/
during that port (the loupe already looks a different size between the X11 and `WaylandRegionSelect`
paths, worth fixing in one place rather than porting the discrepancy a third time).

**The destination-picker redesign (2026-08-08): three real bugs, one shared root cause, fully fixed.**
The first client-anchored-picker design (a `MonitorWindow` fullscreened at the release point purely to
give `ui/destination_picker.py`'s `Gtk.Menu` a valid Wayland popup parent) surfaced three distinct,
live-reported symptoms once real multi-capture testing started: the app's own icon flashing briefly in
the dock, the dock itself blinking, and (once the anchor was changed to a small non-fullscreen window
to try to fix the first two) the picker silently failing to appear at all past the very first capture
of a session, with the selection overlay's own dim/black backdrop still visible while it tried. Traced
each in turn rather than accepting any of them as an unavoidable cosmetic cost (a real, repeatable
"other screenshot tools don't do this" pushback from live testing, not a hunch):
- **Fullscreen-transition churn was a red herring, not the cause** - tried removing `fullscreen_on_
  monitor()` from the anchor entirely (a small, compositor-placed `Gtk.Window`, matching wayland_
  clipboard.py's own invisible-window construction) on the theory that Ubuntu's default "hide the dock
  on fullscreen" behavior was reacting badly to rapid fullscreen window churn. The dock-icon-flash and
  dock-blink symptoms trace to *any* new client toplevel window being created at all (however small),
  not specifically to fullscreening one - removing fullscreen alone didn't fix the underlying picker-
  visibility bug, which is the real finding here.
- **The real cause, confirmed by direct instrumentation, not inferred**: a Wayland `xdg_popup` can only
  be created in response to a real, recent client-side input-event serial - a deliberate protocol-level
  anti-spoofing rule (clients can't legitimately conjure a popup grab without genuine, fresh user
  interaction), not a GTK quirk or something patchable with another window/timing trick. Confirmed live
  via added instrumentation (both in extension.js, temporarily, writing to a home-dir log file since
  `journalctl`/`Eval` were both unreliable channels for reaching this process's own output during this
  session - see the deployment-gotcha note above for why - and in the Python client): the Shell-side
  extension's own log showed *every single* capture attempt completing successfully (drag recognized,
  ended, grab released, correct result returned) even on attempts where the picker never appeared -
  proving the bug was 100% client-side. On the client side, `menu.popup_at_rect()` reported
  `menu.get_visible() == True` on *every* attempt, but only the very first call ever actually took real
  compositor focus (`anchor_window.has_toplevel_focus()` correctly went `False` right after, matching a
  real popup grab taking over); on every later attempt the anchor kept keyboard focus the whole time,
  meaning the "visible" menu was never actually mapped by the compositor at all - GTK's own client-side
  bookkeeping and the compositor's real state had silently diverged. `popup_at_rect(..., None)`'s `None`
  trigger-event argument is exactly the gap: with no separate client window ever receiving *any* real
  input event during the new Shell-side selection flow (all of it happens compositor-side now), there
  is fundamentally nothing on the Python side to legitimately trigger a popup with, ever, after
  whatever residual/lucky serial the process's own startup provided for the very first call.
- **The fix**: move the destination picker into the *same* continuous Shell-side interaction as the
  drag-select itself, using `PopupMenu.PopupMenu`/`PopupMenu.PopupMenuManager` (`resource:///org/gnome/
  shell/ui/popupMenu.js` - the exact class Shell's own top-bar menus use, confirmed via its real source
  rather than assumed: constructor needs a real `sourceActor` to anchor to, not arbitrary coordinates,
  hence a tiny invisible `St.Widget` at the release point used purely as that anchor; `addAction(label,
  callback)` for each of the five destinations; `open-state-changed` fires exactly once per open/close
  cycle regardless of *how* the menu closed - item chosen, Escape, or click-outside - giving one single
  resolution point with no custom dismiss-handling needed, the same "let the platform's own mechanism
  own it" pattern `GrabHelper` already provided for the selection grab). `StartRegionSelect()` now
  chains straight from a completed drag into showing this menu and awaiting the user's choice *before*
  ever returning to Python at all - cropping/encoding the PNG happens once, right after the drag, and
  the D-Bus reply (now `(b ok, s destination, ay pngBytes, i x, i y, i width, i height)`) only goes out
  once a concrete destination has been chosen (or `ok=false` if cancelled at any point, drag or picker).
  `ui/destination_picker.py` gained a `dispatch_destination(id, image, cursor_shape, clipboard_backend)`
  function - the actual Copy/Save/Save As/Edit/Print logic, shared between its own (still-used-by-X11-
  and-`WaylandRegionSelect`) `Gtk.Menu` and this new Shell-native path, so neither duplicates it.
  `ui/region_select_gnome_shell.py` shrank enormously as a direct result: no anchor window, no focus-
  wait dance, no monitor lookup - it just decodes the PNG and calls `dispatch_destination` once the
  Shell side hands back a chosen destination id. All three original symptoms are gone as a direct
  consequence of the fix's actual shape (zero client windows created anywhere in the whole flow now,
  drag through destination choice), not worked around individually - confirmed live, repeatably, across
  many captures in a row with no dock icon, no dock blink, and no black backdrop.

**A real architectural fork seriously considered and explicitly rejected mid-session, worth recording**:
whether to abandon this project's own custom selection UI entirely and adopt GNOME's *stock* built-in
screenshot tool for Wayland instead (literally what Gradia Capture does - `Main.screenshotUI.open()`,
no custom UI of its own at all, which is *why* it never hit any of these problems in the first place).
Rejected because it would mean losing the magnifier loupe, aiming crosshair, and the Windows-style
Copy/Save/Save As/Edit/Print picker for Wayland specifically (GNOME's stock tool just saves to
`~/Pictures/Screenshots` and copies to clipboard, no picker at all) - considered and explicitly turned
down in favor of finishing the harder-but-complete version once the destination-picker failure's real
cause (a bounded, well-understood Wayland protocol restriction) was found rather than an open-ended
unknown.

**Not yet done**: eyedropper (still using the pre-existing `MonitorWindow`-based Wayland
implementation) - per the migration strategy, next up now that region-select and window-picker (see
below) are both done.

#### Window-picker implementation (2026-08-08): working end-to-end, reuses region-select's architecture

Built immediately after region-select using the exact same building blocks (`GrabHelper`,
`Main.layoutManager.emit('system-modal-opened')`, `St.DrawingArea` for dim+highlight rendering,
`Shell.Screenshot.screenshot_stage_to_content()`/`composite_to_stream()`, and - critically -
`pickDestinationAsync` reused directly, not reimplemented) - a new `WindowPickerOverlay` class and
`StartWindowPicker()` D-Bus method, same reply shape as `StartRegionSelect()`. Real window geometry and
content now come straight from Shell's own native API - `global.get_window_actors()`/`Meta.Window`
(`get_frame_rect()`, `is_override_redirect()`, `located_on_workspace()`, `minimized`, `activate()`) -
rather than round-tripping through the bundled window-calls extension's own D-Bus interface at all, a
"worth checking during implementation" question from the original task #77 plan that panned out
exactly as hoped, now that the caller is Shell-side too. `global.get_window_actors()` returns actors in
bottom-to-top stacking order (confirmed both by reading GNOME Shell's own `UIWindowSelector.capture()`,
which enumerates the same way, and by it matching the existing "last match wins" hover contract
`ui/window_picker.py`'s own docstring already documents test coverage for) - no separate
enumeration-order concern to worry about, unlike the real X11 bug that contract was originally written
to prevent (`_NET_CLIENT_LIST` vs `_NET_CLIENT_LIST_STACKING`, see that module's docstring).

**One real bug caught and fixed via live testing with actual overlapping windows (Krita partially
behind Firefox), not assumed correct from the design alone**: capturing a partially-occluded window
returned a mix of that window's own pixels and whatever had been drawn on top of it in the region where
they overlapped. Root cause: `metaWindow.activate()` (raising the clicked window to the front) does
not take visual effect *instantly* - the same restacking-latency Windows-parity detail
`ui/window_picker_wayland.py`'s own docstring already documented for the X11/portal-based
implementation ("the raise genuinely happens, just too fast to perceive... 0.15s"), which this port
initially missed carrying over, having assumed Shell-side synchronous execution would sidestep timing
concerns generally (true for the *reentrancy* hazards that motivated a lot of this session's other
work, but not true for actual compositor-repaint latency, a different class of problem). Fixed by
reusing that same empirically-verified 150ms wait (via a `GLib.timeout_add`-backed `Promise`) between
`activate()` and the fresh post-raise `screenshot_stage_to_content()` call - confirmed live afterward
with the same overlapping-windows setup that the captured content is now fully correct.

No `refresh_image`/deferred-capture dance needed at all here, unlike `ui/window_picker_wayland.py`'s
own X11-portal-based implementation - that dance existed specifically to route around the reentrancy
hazard of doing the activate-then-regrab round trip *from inside* the very Wayland popup-menu-trigger
event that needed to stay synchronous (see `destination_picker.py`'s `refresh_image` docstring for the
full story). Since the destination picker here is Shell-native now (not a client `Gtk.Menu` needing a
live trigger-event serial at all), that whole constraint doesn't exist in this path - raise, wait,
re-screenshot, and crop all happen inline, in order, before the destination picker is ever shown.

#### Eyedropper implementation (2026-08-08): task #77 complete - all three overlays now Shell-side

The last of the three overlays, and the one with no destination picker at all - the eyedropper's only
job is handing a single sampled colour back to its caller (the colour dialog, itself opened from
`EditorWindow`'s style panel), so `StartEyedropper()` (new `EyedropperOverlay`, same
`GrabHelper`/`Clutter.PanGesture`/`St.DrawingArea` building blocks as the other two) returns
`(ok, r, g, b, a)` directly with no `pickDestinationAsync` chained on at all. The grab-suspend/restore
and `toplevel.present()` dance `ui/eyedropper.py`'s `start_eyedropper()` already does around
`Gtk.Dialog.run()`'s own GTK-level modal grab (see that function's own docstring) applies unchanged to
this new path too - a GTK concept, independent of which Wayland implementation is underneath.

**The magnifier loupe needed a real, verified-live rendering technique of its own** - the single
hardest piece of this task #77 sub-effort, given the loupe itself is not optional for this tool (unlike
region-select's own loupe, deliberately deferred - see this section's own earlier entry) and needed
live, per-motion-event pixel sampling, not just a one-time crop. Two more GJS Cairo API gaps found live,
same discipline as the rest of task #77 (checked before relying on them, not assumed):
`Cairo.ImageSurface.createForData()` does not exist in this binding at all (unlike pycairo's own API,
which `ui/cairo_convert.py`'s `numpy_to_cairo_surface` relies on for the exact same purpose Python-side),
and `Cairo.ImageSurface.createFromPNG()` only accepts a filename (a real string path), not a stream or
bytes (confirmed live: "Couldn't convert to filename" against a `Gio.MemoryInputStream`). The real path
that worked: `Shell.Screenshot.composite_to_stream()` already hands back a fully-decoded
`GdkPixbuf.Pixbuf` directly (not just the PNG bytes written to its own stream argument - see the
region-select section above for where this was first confirmed reading GNOME Shell's own
screenshot.js), and `GdkPixbuf.Pixbuf.get_pixels()` returns a real, correctly-indexable `Uint8Array`
(confirmed live against a hand-filled test pixbuf) - so the magnified preview is drawn one source pixel
at a time, each its own filled Cairo rectangle scaled up to the destination size (manual nearest-
neighbour scaling), rather than via a Cairo surface pattern the way `ui/magnifier.py`'s
`draw_magnifier` does it in Python. `composite_to_stream()` is called fresh on every `pan-update` (not
once, unlike the frozen-backdrop-based Python fallback) against a small (25x25, matching
`ui/eyedropper.py`'s own `_PATCH_SIZE`) crop of the already-captured stage texture - genuinely live
sampling, not a one-time-frozen approximation, which the previous `MonitorWindow`-based Wayland
fallback's own docstring explicitly called out as a known limitation it couldn't avoid.

**One real, still-not-fully-explained flake during live verification, recorded honestly rather than
glossed over**: on the very first live test after implementation, the colour sample itself worked
correctly (confirmed by the colour dialog receiving the right value), but the loupe never became
visible at all during the drag. Added detailed instrumentation (temporary, since removed) logging every
step of the pipeline - `_sample()`'s `composite_to_stream()` calls, the decoded pixbuf's own dimensions/
rowstride/channels, the computed colour, `_onRepaint` firing, and (once that showed nothing wrong
either) the exact geometry `_drawLoupe` computes (`destX`/`destY`/`centerX`/`centerY`/`scaleX`/`scaleY`,
the drawing area's own size/visibility/opacity, and the first sampled pixel's raw value) - every single
value logged out correct and in-bounds, and zero exceptions were ever recorded across roughly 90 repaint
calls in one drag. The very next test, with no code change besides the added logging itself, rendered
correctly, and stayed reliable across several more repeat tests after that. Left unresolved rather than
declared root-caused: given every checked value was correct both times, the most likely explanation is
some kind of one-off Clutter/compositor timing glitch during the very first repaint cycle after the
overlay was shown, not a logic bug in this code - but that's an inference from elimination, not a
confirmed mechanism, so it's recorded as an open flake rather than a closed bug. Revisit if it recurs.

**A real tooling lesson from this same debugging arc, worth remembering independent of the bug itself**:
a screen-lock/re-authenticate cycle on the test VM is not the same as a logout, and does not restart the
`gnome-shell` process or clear its extension-module cache the way an actual Log Out does - confirmed
live via `ps aux | grep gnome-shell`'s PID staying identical across several "logged back in" reports
that turned out to be lock-timeout re-authentications, not real logouts. See
[[feedback-extension-reload-caching]] in memory for the fuller writeup - always verify a genuinely new
Shell PID before trusting that a reload actually happened, rather than taking "I logged back in" at
face value.

**Task #77 is now complete**: region-select, window-picker, and eyedropper are all Shell-side, task #76
(the dock/taskbar reflow) is fully eliminated across all three, and the destination picker (used by
region-select and window-picker) is a native Shell popup menu with no client-side trigger-event
restriction to fight. Not yet ported: the magnifier loupe/aiming crosshair/size label for region-select
specifically (deliberately deferred, see that section) - the *only* remaining piece of the original
task #77 scope, tracked as a natural follow-up rather than blocking this task's completion.

### Window-picker under Wayland (task #69)

Wayland has no portable window-enumeration API - confirmed via research before building anything:
`wlr-foreign-toplevel-management` is wlroots-only and not implemented by Mutter (GNOME's compositor);
`org.gnome.Shell.Eval` is access-restricted; AT-SPI (the accessibility bus) *does* report real window
positions live-tested on both X11 and the Ubuntu 26.04 VM (toolkit-level, not compositor-level, so it
isn't blocked by Wayland's security model the way direct enumeration is), but its `grab_focus()`
comprehensively failed live on Wayland - every single accessible object in a real test window's whole
tree (the frame, every button, panel, label) raised an identical `atspi_error`, and its `layer`/`zorder`
fields don't carry real cross-application stacking order either. Ruled out after live testing, not
assumed from documentation.

**What works, live-verified on the Ubuntu 26.04 VM**: the third-party GNOME Shell extension
[window-calls](https://github.com/ickyicky/window-calls) (GPL-2.0-or-later; bundled in this repo, see
THIRD_PARTY_NOTICES.md) exposes `List()` (real per-window `id`/`wm_class`/`x`/`y`/`width`/`height`),
`Details()`, and - the key one - `Activate(winid)`, which genuinely raises and focuses an arbitrary
*background* window. Found and fixed three real bugs in the published extension along the way (a
`ReferenceError` that broke `Details`/`Activate`/etc. entirely, `List()` requesting geometry via
methods that don't exist on `Meta.Window`, and `Activate()` granting keyboard focus without a
stacking-order raise - Mutter treats those as separate concepts, confirmed live: the target window
kept focus but visually stayed behind another window until an explicit `win.raise()` was added). All
three fixes are documented in a comment block at the top of the bundled `extension.js` itself, per
GPL's own requirement to mark changed files.

**Design**: `capture/window.py` gained a `WindowActivator` Protocol (`activate(window_id)`) alongside
the existing `WindowEnumerator` - X11's window-picker never needs one, since it already gets correct
content for free by cropping a single frozen full-screen grab taken when the overlay opened (whatever
was actually on top at that moment is already baked into the pixels). Wayland has no equivalent
guarantee, so instead of trusting hover-highlight accuracy, `WindowPickerWindow._on_button_press`
activates the clicked window, waits briefly, and does a **fresh** grab of just that window's rect
(`capture/gnome_window_calls.py`'s `GnomeWindowCallsBackend`, implementing both protocols) - correct
regardless of what was visible or guessed during hover. `capture/backend_select.py`'s
`default_window_enumerator_and_activator()` centralizes the X11-vs-GNOME-Wayland choice (probing
`is_available()` empirically rather than assuming from session/desktop name - a GNOME Wayland session
with the extension not installed or not enabled looks identical from the outside otherwise), reused by
both `window_picker.py` and `capture_modes.py`'s active-window capture (which had the same latent gap,
silently finding nothing rather than crashing).

**Packaging and consent**: the `.deb` installs the extension's files to
`/usr/share/gnome-shell/extensions/window-calls@domandoman.xyz/` unconditionally (`debian/greenshot-
linux.install`) - that alone is not a settings change, just files on disk. Enabling it is a real write
to the user's `org.gnome.shell` `enabled-extensions` gsettings key (`gnome_extension_setup.py`), which
this project's standing rule (see feedback memory on real system-settings writes) says must only ever
happen from the user's own confirmation click - so it's offered as an opt-in checkbox in the existing
first-run setup dialog, shown only when the session is actually GNOME Wayland
(`gnome_shell_present()`), checked by default, with an explicit "requires logging out and back in to
take effect" note rather than implying it works immediately. Confirmed live that this is a real
requirement, not overcaution: GNOME Shell caches the extension's imported JS module in memory and
won't pick up a freshly-installed extension's code even after a `disable()`/`enable()` toggle - only a
full logout/login forces a fresh read from disk. If declined (or on any Wayland session where the
extension isn't available - a non-GNOME compositor, GNOME without the extension enabled, etc.), the
tray menu's "Capture Window..." item is shown greyed out with an explanatory tooltip
(`backend_select.window_picker_supported()`) rather than silently doing nothing or capturing wrong
content - matching this project's "if it can't work correctly, don't ship it looking like it works"
bar rather than a half-working feature.

**Cinnamon/Mint scope note, for whenever this becomes relevant**: this entire mechanism is GNOME
Shell-specific - it talks to `org.gnome.Shell` on the session bus and uses GNOME Shell's own
extension-loading system. Cinnamon is a long-diverged fork with a completely separate shell process
and an incompatible extension ecosystem ("Cinnamon Spices," not GNOME Shell extensions) - confirmed
via research, not assumed. Cinnamon's own Wayland session is still unreleased as of this writing
(landing in Cinnamon 6.8 / Linux Mint 23, and even then X11 remains the default), so this has been
deliberately left out of scope rather than researched further. The *capture* mechanism (task #67,
`WaylandCaptureBackend` via the XDG portal) is desktop-environment-agnostic and will work on Cinnamon
Wayland automatically, with zero changes, the moment `XDG_SESSION_TYPE=wayland` is set in that
session - `capture/backend_select.py` already checks that fresh on every capture call, not once at
startup. Window-picker specifically will not, and will need its own, separate Cinnamon-specific
mechanism investigated whenever that becomes real - do not assume the window-calls extension approach
transfers.

## Packaging

**Decision: `.deb`.** Avoids Flatpak's sandbox tendency to force portal-mediated capture even
under X11, which would fight the direct-X11-access priority.

**Status: done for Mint/Cinnamon — a real `.deb` builds, lints clean, and installs/runs correctly.**
Research first compared `debhelper`+`dh-python` (pybuild) against `dh-virtualenv` and a
PyInstaller-bundled binary — the latter two were rejected as the wrong tool shape for this app
specifically: PyGObject/GTK bindings load system `.typelib`/`.so` files at runtime via
`gi.require_version()`, so a bundled venv either needs the system `gir1.2-*` packages present
anyway (no benefit to bundling) or tries to vendor GTK itself (nobody does this, and it throws away
Debian's own security updates for the GTK stack). Confirmed against two real Debian-archive
packages with near-identical dependency shapes to this project (`mat2` for Rsvg/GdkPixbuf,
`solaar` for GTK/cairo/X11) that plain `debhelper`+`dh-python` is how real apps like this are
packaged.

- **License decided**: GPLv3 (matching the original Windows Greenshot's own license, per this
  file's own long-standing recommendation, now confirmed with the user rather than left open). A
  `LICENSE` file was fetched verbatim from `gnu.org` via `curl` — deliberately not through a
  web-fetch tool that summarizes/rewrites content through a model, since a legal document needs to
  be byte-exact, not paraphrased.
- **Two real prerequisites found and fixed before packaging could even start**, both confirmed by
  research and both real bugs, not just packaging nice-to-haves:
  - No `[project.scripts]` entry point existed — the app only ever ran via `python3 -m
    greenshot_linux.app`. Added `greenshot-linux = "greenshot_linux.app:main"` to
    `pyproject.toml`, giving a real `/usr/bin/greenshot-linux` once installed.
  - `first_run_setup.py`'s `_default_executable()` hardcoded the `python3 -m` invocation into every
    hotkey binding and the autostart entry it writes — meaning a `.deb` install would have kept
    wiring hotkeys to a dev-only command that wouldn't exist on a machine without this project's
    venv on `PATH`. Fixed to prefer the installed `greenshot-linux` binary (`shutil.which`,
    injectable for tests) and fall back to the dev-mode form only when not installed - confirmed
    live post-install that it now correctly resolves to `/usr/bin/greenshot-linux`.
  - Also added an explicit `GLib.set_prgname("greenshot-linux")` in `app.py`'s `main()` — without
    it, `WM_CLASS` is inferred from `argv[0]`'s basename, which can vary by invocation method
    (bare command, absolute path, a symlink); setting it explicitly keeps it matching the packaged
    `.desktop` launcher's `StartupWMClass` unconditionally, a known gotcha for interpreted-language
    GTK apps confirmed by research before writing any packaging files.
- **`debian/` contents**: `control` (Build-Depends deliberately includes the full runtime dependency
  list too, plus `python3-pytest`/`python3-hypothesis`/`python3-scipy` — the test suite runs for
  real as part of the package build via `dh_auto_test`, not skipped; a deliberate choice consistent
  with this project's own TDD emphasis, catching real build-environment problems rather than hiding
  them), `rules` (`dh $@ --buildsystem=pybuild`), `changelog`, `copyright` (DEP-5, GPL-3.0-or-later),
  `source/format` (`3.0 (native)` — this project *is* the upstream, no separate orig tarball),
  `greenshot-linux.desktop` (the menu launcher — `Icon=greenshot-linux` as a theme name, not the
  absolute path the app's own runtime tray/window icon code uses, since those are two different
  lookup mechanisms; `StartupNotify=false` since no window is shown on a plain launch;
  `StartupWMClass=greenshot-linux`; a single `Categories=Graphics;` — an earlier `Graphics;Utility;`
  tripped a real `desktop-file-validate` hint about apps with two main categories potentially
  appearing twice in the menu, fixed after being caught), and `greenshot-linux.install` (installs
  the launcher + a copy of the bundled icon into `/usr/share/icons/hicolor/128x128/apps/` for
  icon-theme lookup — the bundled PNG is actually 155x126, not a standard icon size, so this is the
  closest bucket, not a pixel-perfect fit; a `lintian` `icon-size-and-directory-name-mismatch`
  warning documents this, not silently ignored).
- **No `postinst`/`postrm` script was written** - confirmed in the built `.deb` that `dh_python3`
  auto-generates one anyway (routine bytecode compilation on install/removal, nothing this project
  authored), so no hotkey/autostart writes happen at install time - consistent with this project's
  standing policy that only a human clicking through the in-app first-run dialog may ever write
  those for real.
- **Full local build/lint/install verified live**: `dpkg-buildpackage -us -uc -b` (all 656 tests ran
  for real during the build via `dh_auto_test`/pybuild, not just the dev venv's own suite) produced
  `greenshot-linux_0.1.0-1_all.deb`; `lintian` on it found zero errors, three harmless warnings (the
  icon-size mismatch above, `initial-upload-closes-no-bugs` - only relevant for real Debian-archive
  uploads, and `no-manual-page` - a nice-to-have not yet written); `dpkg -c`/`dpkg -I` confirmed
  every expected file landed in the right place with the right `Depends:` line; a real
  `sudo apt install <path-to-deb>` (run by the user, not automated - installing packages is a real
  system change) succeeded, the desktop-file/icon-theme/menu-cache triggers all fired correctly, and
  the installed `/usr/bin/greenshot-linux` binary launched cleanly. The real first-run-setup flag
  was checked (read-only) *before* any launch to confirm it was already `true` from earlier genuine
  user interaction, specifically to avoid ever triggering an unsupervised real first-run dialog -
  consistent with the standing rule that only a human may click through that dialog for real.
- **Two full `sudo apt-get install` cycles were needed** to get from "files written" to "package
  actually builds": the build-tooling itself (`debhelper`, `dh-python`, `pybuild-plugin-pyproject`,
  `python3-hatchling`, `devscripts`, `lintian`, plus the runtime dep `python3-shapely`), then
  separately `python3-all` (a `Build-Depends` entry initially missed) and `python3-pytest`/
  `python3-hypothesis` (needed only once the decision was made to actually run the real test suite
  during the build rather than skip it). Every `apt install`/`dpkg -i` step was run by the user
  directly, never automated - installing packages and modifying the system are exactly the kind of
  actions this project's standing safety rules require checking first for, and `sudo` in this
  environment genuinely requires an interactive password this agent cannot supply anyway.

## Open questions (not yet decided)

- Exact CI setup — to be established once there's a build worth gating.

## Security considerations

Not vulnerabilities in this app's own code (no injection surface found - every `subprocess` call
uses list-form argv, never `shell=True` or string-built commands; no privilege escalation; no
network exposure; settings are non-sensitive), but two real caveats about what the tool does and
doesn't protect against, surfaced from a general "does this have security issues" question rather
than a targeted audit:

- **Blur/Pixelize are not cryptographically secure redaction.** Both deliberately preserve some
  correlated information about the underlying content - that's what distinguishes them from an
  opaque blackout - and block-average pixelization in particular is well-documented as reversible
  (tools like [Depix](https://github.com/beurtschipper/Depix) recover redacted text, including
  passwords, from pixelized screenshots by correlating block patterns). Real Windows Greenshot is
  aware of this: `PixelizationFilter.cs` adds cryptographically-random per-block/per-pixel noise
  specifically "to defeat depixelation attacks" (confirmed reading the source), and this port
  faithfully replicates that (`filters.py`'s `_default_rng`, `core/shapes.py`'s `ObfuscateShape.seed`
  docstring). Noise raises the bar against casual depixelation; it does not make either transform
  irreversible against a determined attacker. See task tracker for the follow-up: investigate a
  genuinely irreversible solid-fill "Redact" mode as a third `ObfuscateMode`, since true
  irreversibility isn't really compatible with "blur/pixelize" as a concept.
- **X11 has no per-app screen-capture isolation.** Any X11 client can, in principle, capture any
  window or the whole screen (there's no Wayland-style compositor-mediated permission model) - true
  of every X11 screenshot tool, including real Windows Greenshot's own Linux-adjacent equivalents,
  not something specific to a bug in this codebase. Relevant context for task #49 (Wayland support),
  which would change this story via portal-mediated capture once Mint ships it.

A manual review of this whole session's diff (the packaged `/security-review` skill couldn't run in
this repo - its preamble hardcodes a comparison against an `origin/HEAD` remote-tracking ref, and
this repo has no remote configured at all) found one real, low-severity issue, since fixed:
**`_external_editor_cache_dir` (`ui/editor_window.py`) created `~/.cache/greenshot-linux/` with
umask-controlled permissions instead of an explicit restrictive mode.** The exported screenshot
*files* were always correctly protected (`tempfile.mkstemp` forces `0600` on each one regardless of
umask), but the directory itself would inherit whatever the umask allowed (typically `0755` -
world-listable) - on a system with looser-than-default home-directory permissions, another local
user could enumerate filenames/mtimes in there, though never read contents. Fixed with an explicit
`mode=0o700` on creation (only takes effect on first creation, confirmed via a real
`XDG_CACHE_HOME`-redirected creation - `oct(dir.stat().st_mode & 0o777) == '0o700'`). Everything else
in the diff checked out clean: every `subprocess.Popen` call uses list-form argv built from fixed,
hardcoded candidates (the external-editor preference only *selects* among them, never injects a
string); the new settings key is non-sensitive plain JSON; the X11 keyboard grabs added for the
Escape-cancel fix are released on every exit path found, and X11 releases any grab automatically on
client disconnect regardless (crash-safe).

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

**Status: decided — GPLv3.** Greenshot (Windows) is GPLv3; this is a derivative work — same name,
same feature set, same design lineage — even though no source code is shared. Confirmed with the
user (not just this file's own recommendation) when a real `LICENSE` file became a genuine blocker
for `debian/copyright` during packaging. `LICENSE` at the repo root is the verbatim text from
`gnu.org`, fetched via `curl` rather than a web-fetch tool that summarizes content through a model —
a legal document needs to be byte-exact, not paraphrased.
