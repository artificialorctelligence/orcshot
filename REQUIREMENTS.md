# Orcshot — Requirements

Orcshot is a Linux port of [Greenshot](https://getgreenshot.org/), rebuilt from scratch as a
faithful behavioral port — not a literal code port, and not affiliated with or endorsed by the
Greenshot project. The original Windows source
(a local read-only checkout of [Greenshot](https://github.com/greenshot/greenshot),
C#/.NET/WinForms) is the reference for feature behavior and defaults, but no code is shared;
everything here is a new Python implementation.

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

**Status: Region select is done** (`src/orcshot/ui/region_select.py`,
`RegionSelectWindow`/`start_region_capture`) — the actual click-and-drag trigger for a real capture
flow, launching `EditorWindow` on whatever gets selected. A fullscreen, borderless overlay shows a
frozen copy of the desktop (grabbed once up front, so the backdrop can't drift from what's actually
captured mid-drag, and cropped from that same frozen copy rather than re-grabbing); dragging shows a
live selection rectangle with everything outside it dimmed (even-odd fill rule "hole", not clip-
region combination); releasing crops and opens the editor; Escape cancels.

**Magnifier loupe + selection size label — done** (`src/orcshot/core/magnifier.py` for the
pure positioning/sizing math, unit tested; `src/orcshot/ui/magnifier.py` for the Cairo
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

**Full screen and Active window are also done.** `src/orcshot/capture/modes.py` holds the
pure "which Rect to grab" logic (`full_screen_region`, `active_window_region`), unit tested against
`FakeCaptureBackend`/`FakeWindowEnumerator` — `active_window_region` clamps the focused window's
reported bounds to the virtual screen (a window can extend slightly past it, e.g. after being
dragged partway off-screen) and returns `None` if there's no focused window or it's entirely
off-screen. `src/orcshot/ui/capture_modes.py` is the thin grab-then-launch-`EditorWindow`
glue on top, wired into `app.py`'s `--capture-full-screen`/`--capture-active-window` CLI options and
tray menu. Verified live: routed both through the real single-instance app (a second process
correctly reached the running instance's handler, same as `--capture-region`), and ran both for
real, checking only `image.shape` against the expected dimensions — deliberately never rendering the
captured content for inspection, since a full-screen/active-window grab necessarily contains
whatever's really on screen right now.

**Window picker is also done** (`src/orcshot/ui/window_picker.py`, `WindowPickerWindow`/
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

**Status: all ported at the pure-data-model level** (`src/orcshot/core/shapes.py`,
`drawing.py`, `filters.py`, `crop.py`), TDD throughout. See individual module docstrings for
scoped-out rendering details (GDI+ Bezier smoothing, exact stroked-path geometry, font
measurement) — each is a rendering-layer concern, not a data-model gap.

**Cairo rendering (`src/orcshot/ui/render.py`): done for every shape type** — Rectangle,
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

**Live editor window (`src/orcshot/ui/editor_window.py`): create + select/move + resize +
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
`src/orcshot/core/tools.py`, kept pure and unit tested (including a Hypothesis property
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

**Toolbar icons — done** (`src/orcshot/ui/icons.py`, requested explicitly to make the
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
- **Help → About** (new): a `Gtk.AboutDialog` using the real logo (`resources/orcshot.png`,
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
    /tmp/orcshot-....png does not exist"* immediately after clicking the button. Checked
    Krita's actual granted permissions first rather than guessing (`flatpak info
    --show-permissions org.kde.krita` → `filesystems=host;xdg-run/gvfs;`) - `host` looked like it
    should cover `/tmp`, but doesn't: bubblewrap always gives a Flatpak sandbox its own private,
    empty `/tmp` tmpfs regardless of `host` access (a well-known Flatpak/bubblewrap-specific
    carve-out). Confirmed empirically both ways rather than assumed: `flatpak run --command=ls
    org.kde.krita /tmp` came back empty (the sandbox's own private `/tmp`, not the host's, which
    has real files) while `flatpak run --command=ls org.kde.krita ~` showed the real host home
    directory. Fixed by writing the temp PNG to `$XDG_CACHE_HOME/orcshot/` instead (matching
    `settings.py`'s existing `$XDG_CONFIG_HOME` convention) - confirmed genuinely visible inside the
    sandbox the same way (`flatpak run --command=cat org.kde.krita
    ~/.cache/orcshot/<file>` read it back correctly). The previous export's file is deleted
    right before a new one is written (unique filenames still, so a second export mid-edit can't
    clobber a file a still-open first editor session already loaded into memory), since
    `~/.cache/orcshot` isn't OS-managed transient storage the way `/tmp` is and would
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

**Insert Window (task #99) — done.** Windows' `Insert_window_toolstripmenuitem`
(`ImageEditorForm.Designer.cs`, last item in the Edit menu after a separator) shows a hover submenu
of every open window's title (built by `MainForm.AddCaptureWindowMenuItems`,
`ImageEditorForm.cs:1717-1802`); clicking one captures it and drops it in via
`Surface.AddImageContainer(bitmap, 100, 100)` (`Surface.cs:843-854`) - a fixed position at the
image's natural size, then re-activates the editor. This port doesn't build that hover submenu -
it reuses the same click-to-select overlay `ui/window_picker.py` already built for the "Capture
Window" tray/hotkey action, rather than a second window-enumeration UI. `start_window_picker`
gained two parameters for this: `on_window_captured(image, cursor_shape)`, which bypasses the
usual destination-picker popup entirely and hands the captured image straight back to the caller,
and `force_plain_overlay=True`, which skips the GNOME-Shell-native fast path under Wayland (that
path's own overlay shows Shell-side destination *choices* itself, with no hook to hand an image
back to a specific already-open editor - see `GnomeShellWindowPicker`'s docstring) so Insert Window
behaves the same on every platform, not just wherever the bundled Shell extension happens to be
missing. `EditorWindow._do_insert_window` wires this to the same `default_insert_bounds` +
`ImageShape` + `AddElementMemento` pattern as Insert Image, so the inserted window is centered/
scaled-to-fit and immediately movable/resizable like anything else - a deliberate deviation from
Windows' fixed-position, natural-size placement, chosen for consistency with every other insert
path in this port rather than matching the original pixel-for-pixel. `capture_mouse_cursor=False`
matches the tray's own "Capture Window..." menu item.
- **Known gap, not silently dropped**: `force_plain_overlay=True` means Insert Window never uses
  the GNOME-Shell-native picker's nicer overlay under Wayland, even when the bundled extension is
  present - it always falls back to the plain click-to-select overlay instead. Acceptable since the
  plain overlay is already Wayland's own fallback path for everything else when the extension isn't
  available; revisit only if `GnomeShellWindowPicker` grows a hand-back-the-image hook.
- Verified live (X11/Mint) with `FakeCaptureBackend`/`FakeWindowEnumerator` injected via
  `backend_select.default_capture_backend`/`default_window_enumerator_and_activator` - never a real
  desktop grab, per this project's standing screenshot-privacy rule. Triggered
  `_do_insert_window()`, simulated a click on a fake window through the real
  `WindowPickerWindow._on_button_press` handler, and confirmed a new `ImageShape` lands in
  `editor.layer`, is undoable (`undo_redo.can_undo`), and renders selected/centered on the canvas.

#### Text-editing rewrite: Gtk.TextView overlay (task #78, complete 2026-08-08)
**Status: done, verified live (X11/Mint - Wayland unaffected, this is in-process widget
composition, not a separate compositor surface).** Root cause of "text tool draws a rectangle
instead of text": not a logic bug (typing always worked) - the old mechanism (key-press
interception directly mutating the shape's `text` field, redrawn via Cairo every keystroke) had
no visible caret/cursor at all on a fresh empty box, so it looked broken even though it wasn't.
User explicitly asked whether a native control was possible before settling for a hand-drawn
caret; confirmed `Gtk.TextView` composes correctly with both X11 and Wayland (unrelated to the
session's earlier Wayland popup-serial fights, since this is in-process, not a separate surface)
and chose the more faithful fix: a real `Gtk.TextView` overlaid on the canvas, matching
`TextContainer.cs`'s own architecture (a native `System.Windows.Forms.TextBox`
`ShowTextBox()`/`HideTextBox()`'d over the shape), replacing the old custom mechanism entirely.

**Architecture**: `self._canvas_overlay = Gtk.Overlay()` now sits between `self._canvas_scroller`
and `self._drawing_area` (`self._canvas_overlay.add(self._drawing_area);
self._canvas_overlay.add_overlay(self._text_editor)`), with `self._text_editor`'s position/size
driven by the overlay's `get-child-position` signal (`_on_canvas_overlay_get_child_position`),
computed from the shape's bounds + zoom + the same `ceil(line_thickness/2)` inset
`render.py._draw_text_block` uses (`_text_editor_screen_rect`). `_show_text_editor`/
`_hide_text_editor` mirror `ShowTextBox`/`HideTextBox`; `_apply_text_editor_style` mirrors
`UpdateTextBoxFont`/`UpdateTextBoxFormat`. Plain Enter commits, Shift+Enter inserts a newline
(native `Gtk.TextView` behavior, no longer hand-rolled), Escape cancels, losing focus commits
(`TextBox_LostFocus`) - `_on_key_press`'s old window-level swallow-every-key-while-editing branch
is gone; it now just returns `False` while editing so GTK's normal focus-widget dispatch hands
keys straight to the focused `Gtk.TextView`, which also means keys the TextView doesn't consume
(Ctrl+S etc.) correctly do nothing while editing, rather than the old mechanism's actual latent
bug of inserting the literal character (`Gdk.keyval_to_unicode` doesn't distinguish Ctrl-held).

**Bugs found and fixed live, none guessed**:
- **`Gtk.Widget.override_color()`/`override_background_color()` don't reliably win against this
  GTK3 theme's own CSS for a `Gtk.TextView`'s actual text/caret drawing.** Confirmed live: an
  `override_background_color` white background rendered correctly, but `override_color`'d text
  and the caret itself never appeared at all - typing worked (buffer content updated, driving the
  live Cairo-rendered shape underneath, which is why it *looked* like nothing was different from
  before at first), but the native `Gtk.TextView` itself showed nothing. Root cause not chased
  further than "the deprecated override APIs lose to theme CSS specificity here" - fixed by
  switching to a per-widget `Gtk.CssProvider` at `Gtk.STYLE_PROVIDER_PRIORITY_USER`, targeting the
  `textview text` CSS subnode (the documented GTK3 node for a TextView's actual editable area) with
  explicit `color`/`caret-color`/`background-color`, which reliably wins.
- **Rounded "text" CSS subnode still painted its full rectangular background outside the rounded
  corners as solid black** (theme default) once `border-radius` was added for Speech Bubble
  (below) - fixed by also setting `textview { background-color: transparent; }` on the outer node,
  so the canvas underneath shows through in the corners instead.

**Deliberate deviations from Windows, by explicit request** (this port's own polish, not treated
as citation errors):
- **No `EnsureTextBoxContrast`-style synthesized background.** Windows always shows an opaque
  white/dark-gray background while editing regardless of the shape's own fill, for readability
  against a busy screenshot. This port instead shows the shape's *own real* `fill_color` while
  editing (transparent for the Text tool's own default, so no fill at all - matching exactly what
  committing it produces) - WYSIWYG was preferred over the readability crutch.
- **Rounded corners while editing a `SpeechBubbleShape`** (`bubble_corner_radius`, now public in
  `render.py`, reused for the CSS `border-radius`) - no Windows citation, WinForms' `TextBox` is a
  plain rectangle there too; purely to stop the overlay's own rectangular background from visibly
  poking out past the bubble's rounded outline while typing.
- **Approximate vertical centering while editing** (`_update_text_editor_vertical_offset`, using
  `vertical_text_offset` - now public in `render.py` - and a real `Pango.Layout` built the same way
  `_pango_layout`/`_draw_text_block` build theirs, measured in screen space since the TextView
  lives there rather than the unscaled image space `_draw_text_block` draws in) - recomputed on
  every keystroke via `top_margin`, so text starts near where the final centered/bottom-aligned
  render will land instead of always top-aligned like a native `Gtk.TextView` defaults to, and
  keeps tracking as the text grows/shrinks. Not pixel-identical (GtkTextView's own line-height
  metrics still differ slightly from raw Pango's) - a small residual jump on commit remains with
  multi-line text, accepted as good enough after live comparison.

#### Adjacent fixes found and fixed in the same pass (not originally part of task #78)
Live-testing the new TextView overlay surfaced two more real, unrelated bugs in the same area,
fixed at the user's explicit request rather than filed separately:

**Per-tool "last used" style memory, not one style shared by every tool.** `create_shape_from_drag`
was passing one editor-wide `self._default_style` into every new shape regardless of type, so
e.g. changing the Text tool's color also changed what a freshly drawn Speech Bubble looked like -
first noticed as "a new speech bubble doesn't look like a speech bubble" (no fill, wrong color,
since it inherited whatever the Text tool had last used). Windows' own `EditorConfigurationHelper.
CreateField`/`UpdateLastFieldValue` (`EditorConfigurationHelper.cs:48-98`) keys its "last used
value" cache by `requestingTypeName + "." + fieldType.Name` - independent memory per container
type, seeded from that type's own `InitializeFields()` default. Ported faithfully:
`core/tools.py`'s new `default_style_for_tool(tool)` (per-type defaults, cross-checked against
`RectangleContainer.cs`/`EllipseContainer.cs`/`LineContainer.cs`/`ArrowContainer.cs`/
`FreehandContainer.cs`/`TextContainer.cs`/`SpeechbubbleContainer.cs`/`StepLabelContainer.cs`'s own
`InitializeFields()` calls - all identical to `ShapeStyle()`'s own plain default except Freehand's
thicker line and Speech Bubble/Step Label's own distinct looks) and `style_key_for_shape(shape)`
(the inverse mapping, so restyling an existing *selected* shape - typically done with Select
active, not that shape's own drawing tool - updates the right type's memory rather than
`Select`'s, which has none). `EditorWindow.tool` is now a property (mirroring the existing
`selected_shape` property's own centralizing pattern) whose setter refreshes the style panel's
displayed values too, not just field visibility as before - `_active_style()` resolves to the
selected shape's own live style if one exists, else the active tool's remembered one, with a
`self._syncing_style_panel` reentrancy guard so `_refresh_style_panel`'s own programmatic
`.set_value()`/`.set_active()` calls don't get mistaken for a user edit and push a redundant
undo-history memento. Also completed `StepLabelShape`'s own creation, which had the same bug in a
smaller way - `create_shape_from_drag`'s `STEP_LABEL` branch wasn't passing `style` through at all,
relying entirely on the shape's own hardcoded dataclass default (which happened to already be
correct, since nothing ever overrode it) rather than genuinely participating in the per-type memory
system the way Windows' own `StepLabelContainer.InitializeFields` does.

**Speech bubble border had no seam where the tail attaches - `SpeechbubbleContainer.Draw`'s real
clip-region trick wasn't actually being reproduced.** `SpeechbubbleContainer.Draw`
(`SpeechbubbleContainer.cs:236-333`) draws the tail's border *clipped to exclude the bubble's own
area* (`SetClip(bubbleRegion, CombineMode.Exclude)`), then the bubble's border *clipped to exclude
the tail's area* - so the tail's two edges and the bubble's rounded outline meet as one continuous
seam, with a genuine gap in the bubble's own border exactly where the tail's base crosses it. This
port's previous `render_speech_bubble` didn't reproduce that: it drew the tail first (full,
unclipped) then the bubble on top, relying on the bubble's *opaque fill* to visually paper over
the overlap - which happened to look fine with a visible fill (the common case, so this wasn't
caught earlier), but left the bubble's full uninterrupted border running straight across the
tail's throat with nothing to hide the seam once the user actually looked closely, and would have
been visibly wrong with a transparent fill too (nothing to paper over the seam with at all). Cairo
has no `CombineMode.Exclude` equivalent - reproduced via the same even-odd-fill-rule "hole" trick
`region_select.py`'s own dim overlay already uses (`render.py`'s new `_clip_excluding` helper:
an outer rectangle plus the shape-to-exclude, even-odd filled, then `ctx.clip()`). One faithful-
but-odd source detail *not* reproduced: the tail's own border draw in the source has no
`lineVisible` guard at all (`SpeechbubbleContainer.cs:284-291`, unlike the bubble's own border draw
just below it at `:307-321`) - almost certainly a source oversight (a zero-width GDI+ Pen still
draws a hairline) rather than a deliberate effect; replicating a thickness-0-yet-still-drawn tail
border would be a stranger, more surprising deviation from this shape's own `line_visible` gating
(and every other shape's) than just not reproducing it, so both border draws here are symmetrically
gated on `line_visible`. Regression test: `test_bubble_border_has_no_seam_across_the_tail_base`
(`tests/unit/ui/test_render_speech_bubble.py`) - a straight-down tail with a transparent fill (so
there's nothing to visually paper over a regression) asserts the dead-center pixel of the bubble's
bottom edge, which is also dead-center of the tail's own base, is fully transparent (alpha 0) -
confirmed this genuinely fails against the old implementation (which painted it opaque blue there,
from the bubble's own then-unclipped border).

**Speech Bubble's default line color changed from Blue to Black**, by direct user request -
`SpeechbubbleContainer.cs:80`'s own default is Blue; both `core/tools.py`'s
`_TOOL_STYLE_DEFAULTS[Tool.SPEECH_BUBBLE]` and `SpeechBubbleShape`'s own dataclass default
(`core/shapes.py`) were changed together to stay consistent, with comments at both citing this as
a deliberate deviation, not a citation error.

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

**Default/initial editor window size (task #97) — fixed, was a real gap.** Windows applies
`GetOptimalWindowSize` not just on zoom changes but immediately on load, via `SurfaceSizeChanged`
firing as soon as the captured image is set on the surface, gated by `EditorConfiguration.
MatchSizeToCapture` (`IEditorConfiguration.cs:49-51`, `[DefaultValue(true)]` - on by default, no
opt-in needed). This port's `_set_zoom` path already replicated the clamp math correctly
(`optimal_window_size`, above), but the *initial* open never called it - `EditorWindow.__init__`
can't (`base_image`'s setter docstring: no real `GdkWindow`/allocation exists pre-realize), and
nothing filled the gap afterward, so `_canvas_scroller` (a `Gtk.ScrolledWindow`, which doesn't
propagate its child's size request the way Windows' `panel1` does) left the initial window size
determined entirely by the toolbar/menu/palette rows' own natural size - **confirmed live: a
3000x2000 and a 40x40 synthetic capture produced the byte-identical initial window size**, i.e. the
window never actually reflected the captured image's dimensions at all on open, only on a
subsequent zoom action.
- **Fix**: `show_all()` (already overridden for the style-panel-visibility fix from tasks #57/#58 -
  the one call site every real open goes through, `ui/destination_picker.py`'s `_open_editor`) now
  also does `GLib.idle_add(self._resize_canvas_and_window)`. Deferred via `idle_add` rather than
  called inline, since GTK's own pending resize/allocation queue (`GTK_PRIORITY_RESIZE`) runs at
  higher priority than a default-priority idle callback - by the time it fires, the window has a
  real post-realize allocation for `_resize_canvas_and_window` to measure chrome size from, instead
  of stale pre-realize zeros.
- **Verified live** (synthetic images only, no real desktop capture): before the fix, huge and tiny
  captures both opened at the same fixed size; after, the initial window size responds to the
  captured image's dimensions and stays within `optimal_window_size`'s existing 650x530-minimum/
  screen-work-area-maximum clamp in both cases - matching `SurfaceSizeChanged`'s effect on a real
  Windows install with the (default-on) `MatchSizeToCapture` setting. No preferences-dialog toggle
  was added for `MatchSizeToCapture` itself, since this port has no "always open at a fixed size"
  alternative behavior to toggle to yet - tracked as a possible follow-up, not silently dropped.

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
(`core/tools.py`). Border/Drop Shadow/Torn Edge/Grayscale/Invert/Remove Transparency are grouped
under the toolbar's Effects dropdown (task #89, `_build_effects_control`/`_build_effects_menu`),
matching Windows' real `toolStripSplitButton1` (`ImageEditorForm.Designer.cs`,
`LanguageKey="editor_effects"`, `DropDownItems`: Add Border, Add Drop Shadow, Torn Edges,
Grayscale, Invert, Remove Transparency, Obfuscate Text — the last excluded here, tracked
separately as task #100's OCR feature) — despite its "SplitButton" class name it's actually a
`GreenshotToolStripDropDownButton`, not a true split button with separate click-vs-arrow regions,
so a plain `Gtk.MenuButton` matches it exactly. Drop Shadow and Torn Edge each get *two* dropdown
entries (instant-apply plus "...Settings") rather than Windows' single item with a
left-click-vs-right-click(`MouseUp`) distinction, since a GTK menu item has the same
no-right-click-affordance limitation this port's previous Image-menu placement already had to work
around. Rotate CW/CCW and Resize (task #90) moved out into their own plain toolbar buttons too
(`_build_action_button`, new hand-drawn rotate-arrow/resize-frame icons in `ui/icons.py`) —
separate `rotateCwToolstripButton`/`rotateCcwToolstripButton`/`btnResize` toolbar buttons in
Windows, not part of the Effects split-button, so a plain click-to-run `Gtk.Button` per action
matches that structure rather than reusing the dropdown pattern. The "Image" menu now holds only
"Clear" as a result — an expected side effect of moving everything else into the toolbar across
tasks #89/#90, not something patched here; the menu bar's own structure is task #95's scope.
Research (before
implementing) inventoried every effect Windows actually wires into its editor UI, citing
`Greenshot.Base/Effects/*.cs` and `Greenshot.Base/Core/ImageHelper.cs` for each —
`AdjustEffect`/`MonochromeEffect`/`ReduceColorsEffect` were found defined but with no UI call site
anywhere in `ImageEditorForm.cs`, so they're correctly out of scope, not missing.

- **Effects dropdown item-count discrepancy, resolved (task #101)** — flagged as "7 in source vs 5
  in the real app": the Designer declares 7 `DropDownItems`, but a typical real run only ever shows
  5. Not a bug on either side, just two runtime `Visible` gates neither obvious from the Designer nor
  previously replicated here: `obfuscateTextToolStripMenuItem.Visible = CoreConfiguration.
  IsBetaTester` (`ImageEditorForm.cs:308`, off by default — no "beta tester" concept exists in this
  port, so Obfuscate Text stays excluded, tracked as task #100 regardless of any such flag) and
  `removeTransparencyToolStripMenuItem.Visible = Image.IsAlphaPixelFormat(_surface.Image.
  PixelFormat)` (`ImageEditorForm.cs:1473-1477`, re-evaluated on every selection/undo/image change
  via `RefreshEditorControls`) — Remove Transparency is hidden for the common case of an opaque
  screen capture, which is most of them. This port's images are always physically RGBA regardless of
  origin, so a format-level check would always be true and gate nothing; the faithful equivalent
  ported is content-based instead (`EditorWindow._refresh_remove_transparency_visibility`: any pixel
  actually below full opacity), called from the `base_image` setter — this port's existing single
  "image changed" choke point (undo/redo restores, every other whole-image effect) — plus once at
  menu-build time for the image the editor opens with. `remove_transparency_image`
  (`core/effects.py`) had documented this exact gap in its own docstring since task #36 ("only
  applies if there's alpha to remove in the source; this function is unconditional, callers check")
  without any caller ever doing so until now. Verified live: an opaque synthetic image hides the
  item, one with an actual transparent patch shows it, and swapping an opaque editor's image to a
  transparent one via `base_image` picks the change up immediately.
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
  triggered from two separate dropdown entries here (`Add Drop Shadow` / `Drop Shadow Settings...`,
  in the toolbar's Effects dropdown as of task #89) rather than a left/right-click distinction on
  one button, since a GTK menu item has no right-click affordance to bind the settings variant to.
  **Settings are session-only** (an instance dict, `self._drop_shadow_settings`/
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

### Obfuscate Text / OCR (task #100, faithful port of `ObfuscateTextToolStripMenuItemClick`/`TextObfuscationForm`)
**Status: done, fully live-verified including a real Tesseract process.** Windows' 7th Effects
dropdown item (`ImageEditorForm.cs:1724-1768`): runs OCR on the capture, then opens
`TextObfuscationForm` (`TextObfuscationForm.cs`) to search the recognized text and apply an
obfuscation/highlight effect to every match, with a live preview before committing.

- **OCR engine**: real Greenshot uses `Windows.Media.Ocr` via `Win10OcrProvider`
  (`Greenshot/Native/Win10OcrProvider.cs`) - an OS-level API with no Linux equivalent. This port uses
  **Tesseract** (`tesseract-ocr`) instead, invoked as a plain subprocess (`tesseract <file> stdout
  tsv`, parsed with stdlib `csv` - `ui/ocr.py`/`core/ocr.py`) rather than adding `pytesseract`/Pillow
  as new Python dependencies: the CLI's own `--tsv` output already gives word-level text, bounding
  boxes, and a `(block_num, par_num, line_num)` grouping key, which is everything
  `Win10OcrProvider.CreateOcrInformation` (`Win10OcrProvider.cs:157-183`) gets ready-made from the
  Windows OCR engine's own `OcrResult.Lines`. Declared as a `Recommends` in `debian/control`, not a
  hard `Depends`, unlike every other dependency this package has — missing it degrades gracefully (a
  warning dialog explaining what to install) rather than breaking the app, matching
  `ObfuscateTextToolStripMenuItemClick`'s own `IOcrProvider == null` message-box gate
  (`ImageEditorForm.cs:1734-1739`).
- **Data model** (`core/ocr.py`, pure, tested): `Word`/`Line`/`OcrResult` faithfully port
  `Greenshot.Base/Interfaces/Ocr/Word.cs`/`Line.cs`/`OcrInformation.cs` - `Line.bounds` computes the
  union of its words' bounds the same way `Line.CalculatedBounds` does (`Line.cs:59-77`), just as a
  property instead of a mutation-invalidated cache, since this port's `Word` tuples are immutable.
  `parse_tesseract_tsv` does the line-grouping Windows' OCR engine does for free.
- **Search/match logic** (`core/ocr.py`, pure, tested): `find_matches`/`apply_padding`/`is_valid_regex`
  faithfully port `TextObfuscationForm.SearchWords`/`SearchLines`/`ApplyPadding`/`IsMatch`/
  `IsValidRegex` (`TextObfuscationForm.cs:180-297`) - word-or-line scope, plain-substring or regex,
  case-sensitive toggle, percentage padding split evenly on both sides plus a flat pixel offset, and
  the same "fewer than 3 characters matches nothing" gate `UpdatePreview` applies before searching at
  all.
- **Effects offered**: Pixelize, Blur, Text Highlight, Magnification - matches
  `InitializeEffectDropdown`'s exact 4-item list (`TextObfuscationForm.cs:79-87`, which itself
  excludes `AREA_HIGHLIGHT`/`GRAYSCALE` "as requested"). Reuses this port's existing
  `ObfuscateShape`/`HighlightShape` (tasks #54/#88) directly - no new shape types needed. This port's
  own `SOLID_FILL`/`SCRAMBLE` obfuscate modes (task #60, no Windows precedent) aren't offered here
  either, for the same reason Windows' own dropdown doesn't offer them.
- **Dialog** (`ui/text_obfuscation_dialog.py`, not unit tested - GTK glue, same as
  `destination_picker.py`): search entry (min 3 chars, 300ms debounce via `GLib.timeout_add`
  cancel-and-reschedule, matching `SetupDebouncedSearch`'s own `Throttle(300ms)`), regex/case-
  sensitive checkboxes, word/line scope, effect dropdown with effect-specific fields shown/hidden
  (pixel size/blur radius/highlight color/magnification factor), padding/offset spinners (exact
  ranges from `TextObfuscationForm.Designer.cs`: padding 0-200% default 10/20, offset ±100 default
  0/-5), and a live match-count label. Every match is rendered as a real preview shape added directly
  to the layer (not a separate overlay), matching `ShowPreview`'s own approach
  (`TextObfuscationForm.cs:271-286`); Apply just makes that same set of shapes undoable in one step
  via `CompositeMemento` rather than clearing and re-adding them, since the preview shapes already
  *are* the final ones. Cancel/close removes them with no undo entry, matching `ClearPreview`.
  **Deliberately not ported**: the collapsible "Advanced settings" group (a UX-chrome simplification
  only - every underlying setting is still present) and settings persistence across app restarts
  (`EditorConfiguration.TextObfuscationSearchPattern`/etc.) - session-only here
  (`EditorWindow._text_obfuscation_settings`), the same deliberate scope reduction already made for
  Drop Shadow/Torn Edge Settings.
- **OCR result caching**: `EditorWindow._ocr_result` mirrors `_surface.CaptureDetails.OcrInformation`'s
  own cache-until-explicitly-cleared behavior (`ImageEditorForm.cs:1732` only runs OCR `if ==
  null`) so reopening the dialog doesn't re-run OCR - but unlike Windows, this port also invalidates
  it from the `base_image` setter (the existing single "image changed" choke point) whenever the
  image itself changes via undo/redo or any whole-image effect. Windows doesn't appear to do this;
  without it, a resize/rotate/crop after the first OCR run would leave every match's bounds silently
  misaligned with the (differently-shaped) current image - a deliberate, documented improvement over
  a narrow reading of the source, not a faithfulness gap.
- **Live-verified against a real Tesseract process** (after the user installed `tesseract-ocr`):
  rendered a synthetic PNG with real Pango/Cairo text ("Confidential Report" / "SSN 123-45-6789",
  never real desktop content), ran `run_tesseract_ocr` directly against it - correct word text, exact
  bounding boxes, and correct 2-line grouping, confirming `parse_tesseract_tsv`'s column/key
  assumptions match Tesseract's real `--tsv` output, not just the hand-written fixture in
  `test_ocr.py`. Then ran the full pipeline through a real `EditorWindow` and the actual
  `do_obfuscate_text` entry point (not a synthetic `OcrResult` injected directly): searched
  "Confidential", got one real preview match, applied it, confirmed a real `ObfuscateShape` landed in
  the layer and is undoable, and confirmed `EditorWindow._ocr_result` cached the real OCR run for
  reuse.

#### Follow-up from real-world testing (2026-08-12): confidence filtering, Solid Fill, rename
direflail tested this against a real captured screenshot (a game-result list mixing avatar photos,
icons, and text at varying sizes/styles) and found three real gaps, each confirmed via a synthetic
reproduction of the same layout pattern (never the original screenshot itself, per this project's
screenshot-privacy rule):

- **`parse_tesseract_tsv` needed a real confidence threshold, not just Tesseract's `-1` sentinel.**
  Searching a username that appeared twice (once as a bold link, once in smaller gray "personal
  note" text) only found one occurrence in **Words** scope, and switching to **Lines** scope made
  things *worse* - it grabbed a whole adjacent avatar photo along with the text. Root-caused with a
  synthetic reproduction (a noisy random-pixel "avatar" blob next to real rendered text, run through
  the real `tesseract` binary): Tesseract emitted a genuine word-level TSV row over the noise blob -
  `text="Ne"`, `conf=7.6` - which the old filter (`conf < 0`, only Tesseract's exact "not text at
  all" placeholder value) let straight through. That garbage word's bounds then polluted whichever
  line it got grouped into. Fixed by raising the bar to `DEFAULT_MIN_CONFIDENCE = 30` (`core/ocr.py`)
  - a conventional "trust this" cutoff for Tesseract's 0-100 confidence scale, not tuned against a
  specific corpus. Re-verified against the same synthetic reproduction: the `"Ne"` row is gone from
  the parsed result entirely.
  - **Lines scope itself is left as a known, real limitation**, not something this fix resolves -
    Tesseract's own paragraph/line layout analysis is unreliable on dense mixed icon+text UI
    screenshots (it merged unrelated visual elements into one logical "line" in the failing case).
    The practical workaround, confirmed live: stay in **Words** scope and use **Regex** mode with an
    alternation covering every way the identifier might have been tokenized (e.g. `Sensitive|Ad-4-U`)
    - each fragment matches independently regardless of how Tesseract split the original string, and
    adjacent fragments read as one continuous redaction since they sit next to each other in the
    image. Verified live on the same synthetic reproduction: 2 clean matches, no icon exposure, with
    the confidence fix in place.
- **Solid Fill added as a 5th effect choice** (`ObfuscateMode.SOLID_FILL`, task #60/#86 - no Windows
  precedent), alongside Pixelize/Blur/Text Highlight/Magnification. direflail's live testing was a
  direct demonstration of why: this feature's whole purpose is finding and redacting sensitive text,
  and Pixelize/Blur are both documented-reversible via public depixelation tools (same caveat as the
  manual Obfuscate tool, since it's the identical `ObfuscateShape`/`filters.py` rendering path -
  task #60's anti-depixelation hardening already applies here automatically, no extra work needed).
  Windows never built a Solid Fill mode at all, so adding it here isn't excluding something Windows
  deliberately chose not to show (unlike AREA_HIGHLIGHT/GRAYSCALE, which Windows explicitly excludes
  by name in `TextObfuscationForm.cs:83`) - there was nothing to be unfaithful to.
  - **Follow-up, explicitly requested**: reordered the dropdown to Solid Fill first (was Pixelize/
    Blur/Solid Fill/Text Highlight/Magnification, `InitializeEffectDropdown`'s original order),
    making Solid Fill the new default (`effect_index: 0`) rather than Windows' own Pixelize default -
    an explicit, requested deviation this time, not a silent one. Also labeled Pixelize/Blur inline
    as `"Pixelize (not secure)"`/`"Blur (not secure)"` and Solid Fill as `"Solid Fill (most secure)"`,
    reusing the identical security-tier convention the main Obfuscate tool's own dropdown already
    established (`_OBFUSCATE_MODE_SECURITY_SUFFIX`/`_OBFUSCATE_MODE_ORDER`, `editor_window.py`) -
    duplicated as literal strings rather than imported, to avoid a circular import
    (`editor_window.py` already imports from `text_obfuscation_dialog.py`).
- **Renamed "Obfuscate Text..." to "Find & Redact Text..."** in this port's Effects dropdown only
  (Windows' own `obfuscateTextToolStripMenuItem` name is unchanged in every citation). direflail
  flagged, also from live testing, that the original name collides with the separate manual
  "Obfuscate" tool (task #54/#59) and that "Obfuscate" specifically undersells the feature now that
  its effect choices include Highlight-based ones (Text Highlight/Magnification) alongside
  Obfuscate-based ones - "Redact" describes the outcome rather than one specific shape type, so it
  stays accurate regardless of which effect is picked.

#### A real, severe parsing bug found via direct testing on a real file (2026-08-12)
After the fixes above, direflail reported single-word searches ("years", "Peacock", "robot", "banks",
"legally") still missing on a real screenshot even though the words were big and clearly legible -
the two synthetic reproductions built to investigate (a dense multi-column card grid, and small
10pt UI text) both worked perfectly, ruling out layout/segmentation and font size as causes. direflail
then explicitly authorized testing against the specific real file directly (`~/Pictures/Screenshots/
ocr.png` - a page of ads and social-media cards), which the standing screenshot-privacy rule would
otherwise rule out; only program output (text/confidence/bounds), never the rendered image itself,
was used.

Root cause, found by diffing `tesseract <file> stdout tsv` run directly (which direflail ran and
pasted output from) against this port's own `run_tesseract_ocr`/`parse_tesseract_tsv`: Tesseract's
TSV output is a naive tab-split dump with **no quoting or escaping of any kind** - a literal `"`
character in recognized text (here, a low-confidence misread of some punctuation, `conf=22`, its own
standalone "word") is just a `"` in the file. `csv.DictReader`, however, applies CSV-style quote
handling *by default even when the delimiter is `\t`* - it saw that stray `"` as an open quote and
silently treated every row after it as one enormous mangled field, until another `"` happened to
appear 170 lines later (`"The golden age". FML`, from an unrelated comment). Every real, high-
confidence row in between - including all 5 occurrences of "years" and both of "Peacock" (91-97%
confidence) - was swallowed with **no error, no exception, nothing** - `has_content` was still `True`
and everything else on the page still worked, which is exactly why this was reported as
inconsistent/spotty rather than as an obvious crash. Word count for this file went from 127 (silently
truncated) to 231 (correct) after the fix.

Fixed with one keyword: `csv.DictReader(..., quoting=csv.QUOTE_NONE)`. Verified three ways: (1) the
real file's word count and target-word matches, both before/after; (2) a regression test
(`test_stray_unescaped_quote_does_not_swallow_later_rows`, `test_ocr.py`) reproducing the exact
mechanism with a synthetic 3-row TSV fixture; (3) the full pipeline end-to-end
(`run_tesseract_ocr` → `find_matches`) against the real file, confirming all 6 previously-missing
words now resolve to the correct match counts. This bug predates every other fix in this section -
it was silently truncating OCR results on *any* image where recognized text happened to contain an
unbalanced quote character, which is not a rare occurrence in real screenshots (quoted text, smart
quotes, apostrophes misread as `"`, stray punctuation).

#### Two more real-world findings (2026-08-12): search box persistence, offset_vertical default
- **Search text no longer pre-fills on reopen.** direflail reported reopening the dialog looked like
  a previously-undone redaction was somehow coming back - it was actually the persisted search text
  (`EditorWindow._text_obfuscation_settings["search_text"]`) silently re-running the last search and
  repainting its live preview the instant the dialog opened. Every other setting still persists
  (regex/case/scope/effect/colors/padding/offset - those read as preferences); only the search box
  itself now always starts empty.
- **`offset_vertical` default changed from Windows' own `-5` to `0`.** direflail found "Stewart" only
  half-redacted while "FOOTAGE" (bold, larger) redacted cleanly, on the same image with the same
  settings. Traced with real bounds from the actual file: `apply_padding`'s offset *shifts* the whole
  box rather than expanding it, and "Stewart"'s raw OCR bounds are only 13px tall - a fixed 5px
  upward shift is nearly 40% of that height, so the box's bottom edge ends up 4px above the real
  glyphs while a few pixels of empty space above get redacted instead of them. Tall text barely
  notices the same fixed shift, which is exactly why this looked word-dependent rather than
  systematic. Windows' own `-5` default was presumably tuned against its own OCR engine's bounds,
  which may already run looser than Tesseract's tighter ones - it doesn't generalize here. `0` never
  clips by construction; still user-adjustable via the spinner for anyone who wants to nudge it.

### Undo/redo
**Status: done at the pure-data-model level** (`src/orcshot/core/history.py`) — a generic
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
- `src/orcshot/ui/composite.py`: `composite_to_numpy(base_image, layer)` flattens the base
  image + annotation `Layer` into one final image by reusing the exact same rendering pipeline the
  live editor uses (`numpy_to_cairo_surface` + `render_layer` + `cairo_surface_to_numpy`) — what
  gets exported is pixel-identical to what was on screen, not a second, potentially-diverging path.
- `src/orcshot/ui/gdk_convert.py`: numpy <-> `GdkPixbuf` conversion (headless-testable;
  unlike Cairo's ARGB32, GdkPixbuf's RGB colorspace needs no byte-order swap).
- `src/orcshot/capture/clipboard.py` + `x11_clipboard.py`: ports-and-adapters again, same
  shape as `CaptureBackend` — a `ClipboardBackend` Protocol, a `FakeClipboardBackend`, and a real
  `X11ClipboardBackend` (`Gtk.Clipboard.set_image`, which advertises the standard GDK/GTK image
  targets — the X11 equivalent of the Windows source's `ClipboardFormat.PNG/DIB/BITMAP/DIBV5`;
  DIB/BITMAP/DIBV5 are Windows GDI-specific formats with no X11 analogue, so they aren't
  reproduced). Verified with a **real** in-process X11 clipboard round-trip test (`@pytest.mark.x11`,
  skipped when `DISPLAY` is unset) — not just a fake.
- `src/orcshot/ui/file_export.py`: `save_image_to_file(image, path)`, format inferred from
  the extension via `GdkPixbuf`'s own save types, defaulting to PNG.
- `EditorWindow` wiring: toolbar Copy/Save/Print buttons plus Ctrl+C/Ctrl+S/Ctrl+P. Save uses a real
  `Gtk.FileChooserDialog`; Print uses `src/orcshot/ui/printing.py`'s `print_image()` (a real
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
- **Destination picker** (`src/orcshot/ui/destination_picker.py`, new): every capture now
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
- **Configurable save location** (`src/orcshot/settings.py`, new): a plain JSON file at
  `~/.config/orcshot/config.json` (XDG Base Directory spec, same testing approach as
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
- `src/orcshot/app.py` (`GreenshotApplication`): a `Gtk.Application` with a fixed
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
- `src/orcshot/resources.py` + `resources/orcshot.png` (new): the app's real logo
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
- `src/orcshot/autostart.py`: `install_autostart_entry(exec_command, autostart_dir=None)`
  writes a `.desktop` autostart entry (XDG Desktop Entry/Autostart specs), creating
  `$XDG_CONFIG_HOME/autostart/` (default `~/.config/autostart/`) if needed. Unlike
  `hotkey_setup.py`'s gsettings/dconf writes (global session state with no safe way to test without
  touching the live system), a `.desktop` entry is just a plain file, so the actual write is
  exercised for real in tests — against a temp directory, never the real default path.
- `src/orcshot/hotkey_setup.py`: generalized from a single hardcoded PrintScreen binding to
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
- `src/orcshot/ui/first_run_setup.py` (new): the actual first-run confirmation dialog.
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
  `~/.config/orcshot/` that nothing real was touched by any of that verification.

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
`$XDG_SESSION_TYPE=wayland`), installing the real `.deb` and running `orcshot
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
project's already-GNOME-specific window-calls and orcshot-clipboard extensions. Accepted
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
- License: GPL-3.0-or-later, wholly original code, same as `orcshot-clipboard` - not derived
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
D-Bus method on the same bundled `orcshot-clipboard` extension (kept as one extension rather
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
before investing in the rest" ordering; tracked as its own task, #82. Task #79's
X11-vs-`WaylandRegionSelect` loupe-size discrepancy (see this file's task #79 writeup below) was fixed
first, so #82's eventual port has one fewer bug to carry forward a third time.

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
task #77 scope, tracked as its own follow-up task (#82) rather than blocking this task's completion.

#### Task #82 (port the magnifier loupe/crosshair/size-label to RegionSelectOverlay) - complete 2026-08-09

Ported `RegionSelectOverlay`'s missing loupe/aiming-crosshair/size-label using
`EyedropperOverlay`'s already-proven live-sampling technique (`Shell.Screenshot.composite_to_stream()`
against the frozen `this._texture` captured once in `selectAsync()`, per motion/pan event) as the
starting point, but with the loupe's *sizing and positioning* ported from `core/magnifier.py`'s real
algorithm (`_magnifierDiameter`/`_magnifierOffset`, both new module-level functions in `extension.js`)
rather than reusing `EyedropperOverlay`'s fixed 80px/fixed-offset approach - see task #79's own writeup
above for why starting from the real per-monitor-sized algorithm mattered here specifically. Sizing
itself needed `global.display.get_current_monitor()`/`get_monitor_geometry()` (Shell's own equivalent of
`ScreenLayout.monitor_at()`) - confirmed live via GI typelib introspection against this system's real
`Mutter-18`/`Mtk-18` typelibs (`get_monitor_geometry(index)` returns an `Mtk.Rectangle` with `x`/`y`/
`width`/`height` fields, not the `Meta.Rectangle` an older Mutter version would have used) before
writing any code that depended on it, rather than assumed from general GNOME Shell extension knowledge.

**The pixel-blit/ring/crosshair drawing itself was extracted into a shared `_drawMagnifierLoupe()`
function**, used by both `RegionSelectOverlay` and (refactored in place, no behavior change)
`EyedropperOverlay` - mirroring `ui/magnifier.py`'s own `draw_magnifier()`, which already serves both
Python-side equivalents for exactly the same reason. The two classes' actual *sampling* methods
(`_sampleLoupe`/`_sample`) were deliberately left un-shared, matching this file's existing precedent of
not sharing state-touching methods between the overlay classes (`_onRepaint`'s dim/fill logic is
likewise duplicated between `RegionSelectOverlay` and `WindowPickerOverlay` already).

**Two real bugs found and fixed during live verification, not assumed away:**

- **A destroyed-actor race, confirmed live as a real crash, not theoretical.** `_sampleLoupe()`'s
  `composite_to_stream()` call is async, and unlike `EyedropperOverlay` (which calls `this.destroy()`
  immediately once its grab resolves), `RegionSelectOverlay.selectAsync()` still awaits its own final
  crop *and* `pickDestinationAsync()`'s open-ended wait on the user before destroying - a much longer
  window for a `_sampleLoupe()` call left in flight from the last motion/pan-update before release to
  resolve *after* `destroy()` had already run. First live test hit this exactly: `journalctl` showed
  `clutter_actor_set_allocation_internal`'s `isnan` assertion failing with an invalid `StDrawingArea`
  allocation (`-2147483648 x -2147483648`, the classic NaN-cast-to-int32 signature), followed seconds
  later by a `PopupMenuItem` "already disposed" access on the destination picker - real compositor-state
  corruption from touching a destroyed actor, the same general class of failure this project hit before
  from unsafe extension-reload timing (see [[feedback-extension-reload-caching]]), just from a different
  cause here. Fixed with the standard pattern: a `this._destroyed` flag flipped by `Clutter.Actor`'s own
  `'destroy'` signal, checked before `_sampleLoupe()` touches `this._drawing`/`this._loupePixbuf` after
  its `await`. Retested live after the fix: the crash and the disposed-object error were both gone,
  confirmed across a full capture (drag, destination picker, completed normally).
- **Crosshair jitter, reported live by real testing, root-caused before assuming it was just the
  technique's inherent latency.** The loupe's inner precision crosshair visibly jumped around during a
  drag - traced to `_drawRegionLoupe()` computing the crosshair's position-within-patch from the *live*
  `this._cursorX/Y` (updated synchronously on every motion event) against the *stale* `this._loupeOrigin`
  (only updated whenever the current in-flight `composite_to_stream()` call happened to resolve - and
  concurrent in-flight calls from fast successive events aren't sequenced, so a later one can resolve
  before an earlier one). Fixed by pairing each resolved patch with the exact cursor position it was
  sampled at (`this._loupeSampleCursor`, set alongside `this._loupePixbuf`/`this._loupeOrigin` in
  `_sampleLoupe`) and using that paired value - not the live cursor - for the crosshair math specifically,
  while the loupe's own on-screen *position* (`_magnifierOffset`'s placement) still uses the live cursor
  so the widget itself keeps tracking smoothly. Retested live: crosshair confirmed steady.
  **`EyedropperOverlay`'s own `_sample()`/`_drawLoupe()` likely has the identical race** (its `_cursorX`/
  `_cursorY` are set synchronously at sample-start rather than paired with the patch that call eventually
  produces) - very plausibly the real root cause of task #71's already-tracked "loupe flicker/shearing on
  fast drag," not just generic async latency. Flagged as a follow-up rather than fixed here, to keep this
  task's diff scoped to `RegionSelectOverlay`.

Verified live end to end on the project's GNOME/Wayland test VM across three separate full logout/login
cycles (one per fix, per [[feedback-extension-reload-caching]]'s established reload discipline - a
`gnome-shell` PID change confirmed before each retest): the aiming crosshair + coordinate tooltip appear
before a drag starts, the loupe (correctly sized/positioned, steady crosshair) and "W x H" size label
appear during one, and a real capture completes normally afterward. Syntax-checked before each deploy via
`gjs -m` against the real file (SpiderMonkey parses the whole module before failing on the expected
unresolvable `resource:///` import outside a real Shell process - confirms no syntax error without
needing a full Shell runtime). Not unit tested, matching every other piece of this extension - GJS/Shell
glue with no meaningful headless test, same precedent as the rest of `extension.js`.

#### Task #71 (Wayland eyedropper loupe flicker/shearing) - Shell-native path fixed, portal-fallback split off, 2026-08-09

Important scoping note first: task #71's original entry (this file's Wayland-eyedropper section, "Known
follow-up, not a blocker") is about `ui/eyedropper_wayland.py`'s `_WaylandEyedropperOverlay` - the
Python/GTK **portal-fallback** path, only used when the bundled `orcshot-clipboard` extension
isn't available. All of this session's work was instead on `extension.js`'s **Shell-native**
`EyedropperOverlay` (task #77's rewrite) - the path actually active whenever the extension is available,
which is the default/common case. The portal-fallback's own flicker was never touched here and remains
open, split into its own task (**#84**) so it isn't lost now that #71 itself is closed.

Three real bugs found and fixed in `EyedropperOverlay`, each confirmed live before moving to the next:

- **Crosshair jitter within the loupe**, same root cause and same fix pattern already used for
  `RegionSelectOverlay` (task #82's own writeup above): `_sample()`'s `this._cursorX/Y` were set
  synchronously at call-start, so a newer, faster-arriving `_sample()` call could overwrite them before
  an older, still-in-flight call resolved and overwrote `this._patchPixbuf`/`_patchOrigin` with its own
  (now mismatched) data. Fixed by pairing each resolved patch with the exact cursor position it was
  sampled at (`this._patchSampleCursor`), used for the crosshair-within-patch math specifically while
  the loupe's own on-screen position keeps using the live cursor. Also added the same `this._destroyed`
  guard `RegionSelectOverlay` needed (a narrower window here, since `selectAsync()` destroys immediately
  after its grab resolves rather than also awaiting a destination picker, but not a zero one).
- **The color-value read itself was needlessly slow**, not just the visual loupe. Reported live: "the
  loupe was always the problem, not the color" - `_sample()` extracted the picked colour from the same
  slow `composite_to_stream()` patch (a full server-side PNG encode + decode round trip, confirmed via
  reading GNOME Shell's own `src/shell-screenshot.c`) used for the visual magnifier, even though a much
  cheaper, purpose-built API exists on the same `Shell.Screenshot` class: `pick_color(x, y)` does a
  direct compositor buffer read (`do_grab_screenshot` → `clutter_stage_paint_to_buffer`) with no
  encode/decode at all - added specifically to back the XDG portal's own `PickColor` method (GNOME Shell
  MR !171, 2018), confirmed live via typelib introspection to exist on this Shell's own `Shell-18`
  typelib before relying on it. Wired as an independent, separately-coalesced fast path
  (`_requestColorPick`/`_pickColor`) so the actual released colour no longer waits on the slow visual
  patch at all. One real GJS API-shape surprise, confirmed live rather than assumed (temporary debug
  logging, since removed): `pick_color_finish`'s `(gboolean, out CoglColor*)` signature resolves via
  `Gio._promisify` to a **one-element array**, not the bare `Cogl.Color` directly - different from
  `composite_to_stream_finish`'s no-leading-boolean, resolves-bare shape already used elsewhere in this
  file. `Cogl.Color`'s fields are plain 0-255 bytes, also confirmed live, matching what the existing
  hex-formatting code already expected.
- **The loupe's own on-screen position only redrew whenever a slow async call happened to resolve, not
  on every actual mouse movement** - the real cause of "the whole loupe doesn't move with the cursor
  exactly, it catches up," reported live after the two fixes above didn't resolve it. Unlike
  `RegionSelectOverlay`'s `_updateCursor` (which calls `queue_repaint()` synchronously, decoupled from
  its own async sample), `_requestSample()`'s coalescing wrapper updated `this._cursorX/Y` immediately
  but never actually queued a repaint until `_sample()`/`_pickColor()` resolved - so `_drawLoupe`'s
  `destX`/`destY` (which only depend on the live cursor, no async data needed) only got a chance to run
  as often as those slow round trips completed. Fixed by adding the missing `queue_repaint()` call
  directly in `_requestSample`, matching what `RegionSelectOverlay` already does correctly.

**Residual "offset isn't always exactly 18px during fast movement" - not a further app-logic bug,
folded into task #83.** After all three fixes above, a small remaining symptom persisted: the loupe's
fixed diagonal offset from the cursor doesn't stay perfectly constant during fast movement, collapsing
back to exactly right once movement slows, while the magnified content inside stays accurate throughout.
Confirmed the position math itself is already correct (`destX`/`destY` read the live cursor directly,
not stale data) - the likely remaining cause is generic Clutter/compositor frame-presentation latency:
the real OS pointer is a separate, near-instantly-composited hardware overlay, while the loupe is
app-drawn `St.DrawingArea` content bounded by however long Clutter actually takes to rasterize and
present a new frame, plausibly worse under VirtualBox's virtualized GPU specifically. This is the same
underlying explanation already suspected for task #82's own aiming-crosshair lag (`RegionSelectOverlay`'s
`_updateCursor` is *also* already synchronous, yet the full-screen dim+crosshair redraw still lags on
fast movement) - concluded live to be one issue, not two, and merged into task #83 rather than kept as
two separate open questions with the same likely cause. No further JS-logic fix is expected to help;
deprioritized by explicit user direction rather than chased further.

Verified live across the same repeated full logout/login cycles as task #82 (PID-change-confirmed each
time, per [[feedback-extension-reload-caching]]). Not unit tested, same precedent as the rest of
`extension.js`.

#### Task #84 (portal-fallback Wayland eyedropper flicker) - status: **open**, real progress made, same root cause as #83 (2026-08-13)

**Status: not closed.** Real, measured improvement across four attempts on `ui/eyedropper_wayland.py`/
`ui/monitor_window.py`, but the underlying directional tearing (reported live: "the outside edges of
the loupe momentarily disappear... you can still see part of them toward the center", worse moving
right/down, absent moving up/left, and *never present on X11 at all*) was never fully eliminated.
Concluded to be the same root cause already established for task #83 - generic compositor frame-
presentation latency under this project's only Wayland test hardware's likely software-rendered GPU -
not a specific app-logic bug still waiting to be found. Recording the full trail here rather than
re-litigating it from scratch next time this comes up.

Each of the four changes below was deployed to the real "Ubuntu 26.04" VM and tested live by direflail
against the real Wayland compositor after every single one - critically, **not** via this session's own
local X11 pixel-diff scripts, which were repeatedly (mistakenly) offered as if they were relevant
confirmation. They aren't: X11 never reproduces this bug at all (per direflail, confirmed live), so a
"renders correctly" result there only ever proves the underlying geometry/math has no logic error - it
says nothing about the actual Wayland compositor-timing artifact. Worth stating plainly since it wasted
real back-and-forth before being caught.

1. **`_redraw_loupe`: `queue_draw_area` for just the loupe+swatch's own rect, not `queue_draw()` for the
   whole window.** Every motion event previously invalidated (and forced a full backdrop re-blit +
   loupe redraw for) the entire fullscreen surface. Measured live against the real compositor with a
   synthetic backdrop and a real 60-step drag: **68x less invalidated area per frame** (15,376px² vs.
   1,049,088px² for the VM's real 1366x768 screen), consistently, never falling back to full-screen size.
   `_LOUPE_REGION_MARGIN`/`_LOUPE_REGION_SIZE` (2px margin, 124px box) sized from real
   `ctx.text_extents()` measurements on the VM's own font config, not guessed - confirmed generous
   enough via a real pixel-capture comparison (see below) before ever suspecting box size as a cause.
   direflail's first live report after this shipped: right/down movement still showed clipping "at the
   edges of the loupe itself... nothing to do with the contents", up/left fine.
   - Ruled out via direct evidence, not assumption: is this a genuine screen-edge clamping artifact
     (`_clamped_patch_rect`/`_clamped_crop`, unavoidable when the cursor is literally at the edge of the
     virtual screen)? direflail confirmed live it happens "anywhere on the screen", not just near edges -
     ruled out. Is the invalidation box too small for the real drawn content? Measured real
     `ctx.text_extents("#FFFFFF")` on the VM (width=50, height=9, smaller than the box assumed) - box
     confirmed generously oversized in every direction, ruled out. Is it a settled-frame geometry bug at
     all? A direct pixel-capture comparison (identical fast-right-and-down drag, once through the
     optimized `queue_draw_area` path and once through the old full-window `queue_draw()` path, both
     landing at the same final position) produced byte-identical, fully-formed rings in both - proved
     the bug is a *transient* artifact during active movement, not a settled-frame clipping bug, and
     that this fix's own geometry isn't the cause.
2. **`_redraw_loupe`: one unioned `queue_draw_area` call per window (`_union_rect`) instead of two
   separate ones (erase-old, draw-new).** Under fast movement those two rects usually don't overlap, so
   each frame was being composited from two distinct damage regions instead of one - removed as a
   variable. direflail's report after this shipped: **"it happens less now, particularly in the down
   direction. it's still happening though."** Real, measured improvement, not full elimination.
3. **`_build_loupe_surface`: pre-composite the magnified circle, ring, crosshair, and color swatch onto
   a small off-screen `cairo.ImageSurface` in one self-contained pass, then a single blit in `_on_draw`**
   - instead of five-plus separate Cairo operations (arc-clip+paint, `ctx.restore()`, ring `ctx.stroke()`,
     two crosshair `move_to`/`line_to` pairs, swatch rectangle+text) landing directly on the window's own
     backing surface, any one of which could be the boundary where a partial/torn frame gets presented.
   direflail's report: **"still happening but less pronounced. you may be on the right track."** Further
   real, measured improvement.
4. **`_on_draw`: slice the exact invalidated region straight out of the raw frozen numpy pixels
   (`ctx.clip_extents()` read back from the draw event itself) instead of painting from one big cached
   per-monitor `cairo.ImageSurface` covering the whole window** (relying on Cairo's own clip to skip the
   unneeded work). Removed `self._surfaces`/`self._window_index` entirely (no longer needed).
   direflail's report: **"no change in wayland"** - this one didn't help. Most likely explanation:
   Cairo's clip-based work-skipping for a large-source/small-destination paint was already efficient, so
   this was addressing something that was never actually a bottleneck. Left in (not reverted) since it's
   not worse and is arguably simpler in one sense (no per-monitor surface cache to keep in sync) even
   though it adds `ctx.clip_extents()` handling - a judgment call, not a strong one either way.
   - Also tried, independently, no effect: removing `MonitorWindow`'s `set_visual(rgba_visual)` request
     (`monitor_window.py`) - originally added for the eyedropper's now-abandoned real-transparency
     attempt (see this file's eyedropper-under-Wayland section above), confirmed dead code for its
     original purpose since transparency never survives `fullscreen_on_monitor()` under this Mutter
     session regardless. Removing it was well-justified on its own merits (real, if small, compositor
     cost for zero benefit) even though it didn't move the needle on this specific symptom - left removed.
   - Also tried, inconclusive: watched GNOME Shell's own `journalctl` live during a real reproduction.
     No warnings about slow paint, dropped frames, or damage-region handling - not a smoking gun either
     way, just no additional signal from this angle.

**Why this is concluded to be task #83's root cause, not a distinct bug**: the two changes that helped
(items 2 and 3) both reduced the *amount of rendering work* done per frame against the live window: one
fewer damage region, five-plus operations collapsed to one blit. Both produced *partial*, not complete,
improvement - never a clean fix, never a regression either. That is exactly the signature of a genuine
compositor/GPU throughput ceiling (less work per frame narrows the window in which a slow frame gets
caught mid-render, without eliminating the possibility that some frame is still slow enough), not a
specific logic bug waiting to be found - especially once combined with: this VM's likely software-
rendered Wayland compositor is the *only* environment either symptom (#83's lag, #84's tearing) has ever
been observed in; X11 has no per-frame backdrop-blit architecture at all for this overlay (genuine
transparency), so there is nothing for a slow compositor to ever catch mid-render there, which is
exactly why it's never reproduced on X11 specifically, not because the code paths differ in some other
way that would matter.

**Deliberately not pursued further, and why**: a genuinely different rendering architecture (GPU-
accelerated Clutter/GL instead of software Cairo blits against a GTK3 `Gtk.Window`) is the only lever
left untried that could plausibly eliminate this outright rather than reduce it - judged too large an
undertaking for what this task warrants, not attempted. Also considered and rejected: capturing a
screenshot of the real VM mid-drag to inspect the actual torn frame directly - reasoned through before
attempting, since a screenshot call is itself a point-in-time query most likely to just show whatever
frame has already settled by the time it executes, the same fundamental limitation as the "capture after
the drag" tests in item 1 above, which is why this wasn't tried as a fifth iteration.

Left **open** for a time per direflail's explicit direction, with root cause recorded as identical to
task #83 - revisit both together if a genuinely different rendering approach is ever undertaken, rather
than continuing to chase incremental app-side mitigations on this one alone.

**Update, 2026-08-21 - closed.** direflail: "close this one, if it comes up again ill reopen." No new
work done; the analysis and four attempts above still stand as the record if this needs revisiting.

#### Extending Shell-native capture to Full Screen/Active Window/Last Region Repeat (task #73, complete 2026-08-09)

Reported as "an audible camera-shutter sound plays on the destination-picker click after a Wayland
capture" - confirmed live (`journalctl` watched while reproducing) that this is `xdg-desktop-portal-
gnome`'s own built-in UI feedback, played whenever `org.freedesktop.portal.Screenshot`'s `Screenshot()`
method is invoked, regardless of caller. Region-select and window-picker were already silent - task #77
moved them off the portal entirely - but Full Screen/Active Window/Last Region Repeat (`ui/
capture_modes.py`) never needed an interactive overlay, so #77 never touched them; they still went
through `WaylandCaptureBackend.grab()` → the portal. Confirmed the fix scope precisely before writing
any code: `capture.modes.full_screen_region`/`active_window_region` (the *which Rect to grab* logic)
never needed the portal at all - `WaylandCaptureBackend.screen_layout()` uses plain GDK monitor
enumeration, and active-window's own focused-window lookup already goes through the portal-free
`GnomeWindowCallsBackend` - only the actual pixel *grab* (`WaylandCaptureBackend.grab()`) touches the
portal, so that's the only piece that needed to move.

**Extended #77's own architecture rather than just muting the sound**, by explicit choice (the simpler
"Preferences toggle to mute it" alternative was also on the table). Added a new, non-interactive
`CaptureRect(x, y, width, height)` D-Bus method to the bundled extension's `GreenshotCapture` interface
(`extension.js`) - reuses the exact `screenshot_stage_to_content`/`composite_to_stream` primitive
`RegionSelectOverlay`/`WindowPickerOverlay` already use for their own final crop, with no gesture/overlay
actor of its own. New `capture/gnome_capture_rect.py` client (`start_capture_rect`) and a
`ui/capture_modes.py._capture_and_pick()` helper, used by all three non-interactive capture functions in
place of their old direct `capture_backend.grab(region)` + `show_destination_picker()` calls - prefers
the Shell-native round trip whenever the bundled extension is available on Wayland, falls back to the
classic portal/`Gtk.Menu` path otherwise (X11, or the extension not installed/enabled).

**A second, real, separate artifact was found live-testing just the pixel-grab fix**, before it was
considered done: even with the portal (and its sound) eliminated, the *old* `ui/destination_picker.py`
`Gtk.Menu` - a real client-side popup window - still caused a brief dock/taskbar icon flash for these
three modes, the exact same symptom class task #76/#77 already eliminated for region-select/window-
picker by moving *their* destination picker Shell-side too. Extended `CaptureRect` to chain into the
same `pickDestinationAsync()` region-select/window-picker use (anchored at the current pointer position
via `global.get_pointer()`, since there's no drag-release/click point to anchor at instead here) rather
than stopping at "no more sound" - `CaptureRect` now returns `(ok, destination, pngBytes)`, matching
`StartRegionSelect`/`StartWindowPicker`'s own reply shape. This changed `gnome_capture_rect.py`'s own
call from a bounded, synchronous `call_sync()` (correct for a plain pixel-grab-only round trip) to a
genuinely async, infinite-timeout `Gio.DBusConnection.call()` (`start_capture_rect`, callback-based,
mirroring `gnome_region_select.start_region_select` exactly) - once a destination choice is folded in,
the round trip is open-ended and user-timed, the same reentrancy reasoning that already governed the
interactive overlays' own D-Bus calls. `ui/capture_modes.py`'s three `start_*` functions no longer
return anything meaningful on the Shell-native path (fire-and-forget, same as the interactive overlays'
own callers) - confirmed no caller anywhere relied on their previous return value before making this
change.

**A real regression-shaped scare during this work turned out to be self-inflicted, not a real bug** -
worth recording so it isn't re-chased. After the first extension.js deploy (`CaptureRect`, pixel-grab-
only version), window-picker - untouched by any of this session's changes - started crashing instead of
showing its destination picker, with `gnome-shell` logging a `cogl_sub_texture_new: assertion 'sub_y +
sub_height <= next_height' failed` chain (and cascading `COGL_IS_TEXTURE`/`G_IS_OBJECT`/`GDK_IS_PIXBUF`
assertion failures right after) reliably, on more than one window. `gdbus introspect` against
`GreenshotCapture` confirmed the new method's XML was well-formed and didn't corrupt the interface
(ruling out the first, most obvious guess). Root cause: mid-session `gnome-extensions disable`/`enable`
cycling (tried once, to avoid yet another full logout, while adding temporary debug logging) left the
*compositor's own* actor/texture bookkeeping in a genuinely corrupted state - not just stale JS code the
way [[feedback-extension-reload-caching]] already documented, but active runtime corruption serious
enough to crash an entirely unrelated, unmodified code path. A subsequent full logout/login (the
already-established reliable reload method) fully cleared it - window-picker was retested repeatedly
afterward with zero failures. Strengthens the existing lesson from task #77's own debugging: never use
`gnome-extensions disable`/`enable` mid-session as a shortcut around a full logout when iterating on this
extension, even just once "to save time" - the failure mode isn't limited to "your change didn't load,"
it can actively break other, already-working parts of the same running Shell session.

**Verified live end-to-end, all three modes, after the full fix**: no shutter sound, no dock/taskbar
flash, `journalctl` clean of errors/warnings during capture, and at least one full destination dispatch
(Edit) confirmed to open the editor with the correct captured image. Full local test suite (759 passed,
3 skipped) unaffected - `capture_modes.py`/`gnome_capture_rect.py` remain untested for the same reason
`gnome_region_select.py`/`gnome_window_picker.py`/`gnome_eyedropper.py` are: D-Bus glue needing a real
GNOME/Wayland session, only verified live.

**Task #75 (intermittent destination-picker mispositioning) closed as a side effect, confirmed live,
not just assumed**: its original bug was specific to the old client-side `anchor_window`/`Gtk.Menu`
picker mechanism (`ui/region_select_wayland.py`/`ui/destination_picker.py`), which region-select/
window-picker stopped using in task #77 and full-screen/active-window/last-region-repeat stopped using
in this same task #73 - that code path is now only reachable as a last-resort fallback (extension
unavailable). Retested live: repeated region-select captures, a mix of fast and slow drags, positioned
correctly every time; `journalctl` clean of the original "no trigger event for menu popup"/"doesn't
have a parent" warnings throughout.

#### Task #49 ("Add Wayland support") status: core scope complete, audited 2026-08-09

Re-audited the whole Wayland story end to end before closing the umbrella task, rather than trusting
individual subtask checkmarks alone - every piece task #49's own original scope named (capture
mechanism, overlay positioning) is done and live-verified, and every Wayland-specific bug/regression
surfaced *while building it* (tray icon, clipboard, window enumeration, dock/taskbar reflow, shutter
sound, destination-picker mispositioning) is also done and live-verified:

- **Capture**: all six modes (full screen, active window, region select, window picker, eyedropper,
  last region repeat) work, portal-free wherever the bundled Shell extension is available (tasks #67,
  #77, #73), with the original XDG-portal path as a correctness-preserving fallback when it isn't.
- **Clipboard** (#74), **window enumeration** (#69), **tray icon** (#70), **overlay positioning**
  (#68/#77), **destination-picker positioning** (#75, just reconfirmed above), **dock/taskbar reflow**
  (#76/#77/#73), and **the shutter sound** (#73) are all fixed and live-verified.
- **Cursor auto-capture** (XFixes) and **the editor itself** work via XWayland compatibility, confirmed
  in this section's own earliest entries and unaffected by everything built since.

**Known, deliberately non-blocking gaps, tracked separately rather than folded into #49's own
completion** (matching how task #77 itself shipped with its own magnifier-loupe follow-up still open):
- Multi-monitor Wayland capture is still genuinely unverified (this project's only Wayland test rig is
  a single-monitor VM) - the crop-offset math's assumption that the captured image starts at the
  virtual screen's own origin has never been checked against a monitor with negative `bounds.left`.
  Nothing points to it being wrong, but it's untested, not confirmed correct.
- Global hotkeys were Cinnamon-only at the time #49 closed (`hotkey_setup.py` originally targeted
  `org.cinnamon.desktop.keybindings` only) - scoped from the very start ("Platform priority" above:
  "Capture and hotkeys work fundamentally differently under Wayland... no standard global-hotkey API"),
  not a gap #49 introduced, and every capture mode remained fully reachable via the tray menu regardless.
  **Since closed by task #81**: `hotkey_setup.py` now also detects and auto-configures GNOME's own
  `org.gnome.settings-daemon.plugins.media-keys` schema (full-path list entries, string not array
  `binding` field - verified live against a real GNOME/Wayland session, differs from Cinnamon's schema
  in both respects), via a `DesktopKeybindingProfile`/`detect_profile()` abstraction so the same
  conflict-detection logic serves both desktops. Still X11/Cinnamon-and-GNOME only, not XFCE/KDE/MATE -
  those, and any third-party screenshot tool's own bindings, fall back to the existing manual
  cut-and-pasteable CLI-flag list in the first-run dialog by deliberate choice (detecting/resetting
  arbitrary other tools' bindings was ruled out as infeasible).
- Three smaller polish items remain open as their own tracked tasks, none blocking core functionality:
  eyedropper loupe flicker/shearing on fast drags (#71), the Shell-extension `RegionSelectOverlay`'s
  magnifier loupe/crosshair/size-label still needing its own port (#82 - see #79's writeup below for why
  that's a distinct gap from the size bug #79 fixed), and the benign "no trigger event for menu popup"
  warning documented and closed below (#80).

**Verdict: task #49's own scope is done.** Task #50 (package for Ubuntu 26.04 LTS), the only task
blocked on #49, is now unblocked.

#### Task #79 (magnifier loupe size differs between X11 and Wayland) - fixed 2026-08-09

Root-caused before touching anything: `region_select.py` (X11) and `region_select_wayland.py`
(`WaylandRegionSelect`, the portal-fallback path) both call the identical `magnifier_diameter()`/
`draw_magnifier()` (`core/magnifier.py`, `ui/magnifier.py`) with the same `source_size=25` crop - not a
DPI/scale-factor bug, not different constants. The only divergence was *which* `Rect`'s width/height fed
`magnifier_diameter()`: X11's `region_select.py:188` used `self._bounds`, the **virtual-desktop union of
every monitor**; Wayland's `region_select_wayland.py:190` used `window.monitor_bounds`, the **single
monitor** that overlay window belongs to (Wayland already gets this "for free" since it uses one overlay
window per monitor, not one spanning all of them). On the project's single-monitor Wayland test VM these
happen to coincide, which is why the discrepancy wasn't caught until multi-monitor use surfaced it.

Checked which behavior is actually faithful to Windows before picking a side: `CaptureForm.cs:814-819`
sizes the real Greenshot zoom widget from `DisplayInfo.GetBounds(MousePosition)` - the single display
under the cursor, exactly Wayland's existing behavior. **X11 was the deviation, not Wayland.**

Fixed in `region_select.py`: `RegionSelectWindow` now keeps the full `ScreenLayout` from
`capture_backend.screen_layout()` (not just its `virtual_bounds`), and `_on_draw` looks up
`monitor_at(cursor_x, cursor_y)` each frame to size the loupe from the monitor currently under the
cursor, falling back to the full virtual bounds only if the cursor is over dead space between
differently-sized/offset monitors (a real possibility per `ScreenLayout`'s own docstring). Placement
(`magnifier_offset`, keeping the loupe from covering the current selection) still uses the full window's
`screen_rect` unchanged - only the *size* calculation moved to per-monitor.

Verified offscreen (no real desktop capture, matching this module's own established verification
approach) with a synthetic two-monitor `FakeCaptureBackend` layout (1920x1080 primary, 2560x1440
secondary): cursor over the primary now correctly sizes the loupe to 216px (`magnifier_diameter(1920,
1080)`) instead of the old, monitor-blind 288px it was getting from the virtual-bounds union
(`magnifier_diameter(4480, 1440)`) - the exact discrepancy #79 described, gone. No unit-test coverage
added (`region_select.py`'s own docstring: GTK glue with no meaningful headless test, verified via
FakeCaptureBackend + a direct offscreen Cairo surface instead, same precedent as the rest of this file).

Separately, not part of #79's own fix: the Shell-extension Wayland path (`extension.js`'s
`RegionSelectOverlay`, the one actually used once the bundled orcshot-clipboard extension is
available - see task #77) still has no magnifier loupe at all yet. That's a distinct, already-known
"not yet ported" gap from task #77 (see that section above), not a sizing bug - tracked as its own task,
#82, rather than reopening #79.

#### Task #80 (benign "no trigger event for menu popup" warning on Wayland Edit) - investigated 2026-08-09

This exact warning text was previously seen and fixed for a *different* code path: the old
client-anchored `Gtk.Menu` destination picker (task #75, closed above) hit it because Wayland's
`xdg_popup` grab has to be requested synchronously within the triggering input event, and that picker's
original design deferred it. That instance is confirmed gone (re-verified live during #75's own closure,
clean `journalctl` across repeated captures).

The still-open instance task #80 asks about is a different site entirely: `ui/editor_window.py`'s two
`Gtk.MenuButton` dropdowns (the Obfuscate-mode button, `editor_window.py:1034-1035`, and the zoom button,
`editor_window.py:1917,1920`) wired purely via `.set_popup(menu)`, with no app code ever calling
`.popup()`/`.popup_at_widget()`/`.popup_at_pointer()` on them directly - confirmed by grep, no
`idle_add` or deferred-callback pattern anywhere near either widget, ruling out the reentrancy mechanism
behind the #75/portal-window-picker instances of this same warning text
(`gnome_window_picker.py`/`destination_picker.py`'s own documented "must stay synchronous" fix above).
The actual `Gtk.Menu.popup_at_widget()` call responsible lives entirely inside GTK3's own
`GtkMenuButton` C implementation (this system: `libgtk-3-0t64` 3.24.41), which doesn't reliably thread
the originating `GdkEvent`/input serial through to the popup call the way a hand-written
`button-press-event` handler would - harmless under X11 (X's popup model doesn't need an
event-derived serial), logged under Wayland because `xdg_popup` positioning wants one, but GDK's Wayland
backend falls back to the seat's last-known serial regardless and the menu still opens and positions
correctly every time.

**Confirmed benign, not fixed - no app-level fix available.** The only real "fixes" would be replacing
`Gtk.MenuButton` with a hand-rolled button + manual `button-press-event` handler purely to thread a real
event through two dropdown menus with no other observed problem, or suppressing the GLib log domain
(masking a real GTK signal rather than addressing it) - neither justified for a cosmetic log line with
no functional or visual impact. Closed as documented rather than carried forward as an open question.

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
    orcshot.app`. Added `orcshot = "orcshot.app:main"` to
    `pyproject.toml`, giving a real `/usr/bin/orcshot` once installed.
  - `first_run_setup.py`'s `_default_executable()` hardcoded the `python3 -m` invocation into every
    hotkey binding and the autostart entry it writes — meaning a `.deb` install would have kept
    wiring hotkeys to a dev-only command that wouldn't exist on a machine without this project's
    venv on `PATH`. Fixed to prefer the installed `orcshot` binary (`shutil.which`,
    injectable for tests) and fall back to the dev-mode form only when not installed - confirmed
    live post-install that it now correctly resolves to `/usr/bin/orcshot`.
  - Also added an explicit `GLib.set_prgname("orcshot")` in `app.py`'s `main()` — without
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
  `orcshot.desktop` (the menu launcher — `Icon=orcshot` as a theme name, not the
  absolute path the app's own runtime tray/window icon code uses, since those are two different
  lookup mechanisms; `StartupNotify=false` since no window is shown on a plain launch;
  `StartupWMClass=orcshot`; a single `Categories=Graphics;` — an earlier `Graphics;Utility;`
  tripped a real `desktop-file-validate` hint about apps with two main categories potentially
  appearing twice in the menu, fixed after being caught), and `orcshot.install` (installs
  the launcher + a copy of the bundled icon into `/usr/share/icons/hicolor/128x128/apps/` for
  icon-theme lookup — the bundled PNG is actually 155x126, not a standard icon size, so this is the
  closest bucket, not a pixel-perfect fit; a `lintian` `icon-size-and-directory-name-mismatch`
  warning documents this, not silently ignored).
- **No `postinst`/`postrm` script was written** - confirmed in the built `.deb` that `dh_python3`
  auto-generates one anyway (routine bytecode compilation on install/removal, nothing this project
  authored), so no hotkey/autostart writes happen at install time - consistent with this project's
  standing policy that only a human clicking through the in-app first-run dialog may ever write
  those for real. (Superseded by task #141's later systemd `--user` service migration - `debian/
  orcshot.postinst` is now a real, project-authored script; see the two new `lintian` warnings
  below.)
- **Two more `lintian` warnings, both understood, both harmless (0.1.1)**: `maintainer-script-
  calls-systemctl` - expected, task #141's own `debian/orcshot.postinst` genuinely needs to
  `systemctl --user enable --now orcshot.service` for the "enable autostart" debconf answer to take
  effect at install time, the whole point of that migration. `malformed-question-in-templates
  orcshot/enable-autostart` - traced into `lintian`'s own source
  (`Lintian::Check::Debian::Debconf`, the `$short !~ /\?/` check on a `boolean`-type template) rather
  than dismissed: the short description ("Start Orcshot automatically at login?") plainly does
  contain a `?`, confirmed byte-for-byte in both `debian/orcshot.templates` and the same file
  re-extracted from the actual built `.deb` - a `lintian` parsing edge case with this specific
  template shape, not a real formatting defect. The debconf question itself was already confirmed
  working correctly in earlier testing.
- **Full local build/lint/install verified live**: `dpkg-buildpackage -us -uc -b` (all 656 tests ran
  for real during the build via `dh_auto_test`/pybuild, not just the dev venv's own suite) produced
  `orcshot_0.1.0-1_all.deb`; `lintian` on it found zero errors, three harmless warnings (the
  icon-size mismatch above, `initial-upload-closes-no-bugs` - only relevant for real Debian-archive
  uploads, and `no-manual-page` - a nice-to-have not yet written); `dpkg -c`/`dpkg -I` confirmed
  every expected file landed in the right place with the right `Depends:` line; a real
  `sudo apt install <path-to-deb>` (run by the user, not automated - installing packages is a real
  system change) succeeded, the desktop-file/icon-theme/menu-cache triggers all fired correctly, and
  the installed `/usr/bin/orcshot` binary launched cleanly. The real first-run-setup flag
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

### Ubuntu 26.04 LTS (task #50, complete 2026-08-14)

**Status: done.** The same `.deb` built above (no rebuild needed for a different target -
`Architecture: all`, no compiled code) was verified on the project's own "Ubuntu 26.04" VM (GNOME/
Wayland - see the VM-testing reference notes), which had previously only ever run this app from
source via `PYTHONPATH`, never through a real install. `apt-get --simulate install` confirmed every
declared `Depends:` (including `gir1.2-ayatanaappindicator3-0.1`, the specific naming-drift risk
flagged while scoping this - older Ubuntu/Mint releases shipped Canonical's original
`gir1.2-appindicator3-0.1` instead) resolves cleanly against that release's own repos. The actual
`sudo apt install` was run by the user directly inside the VM, same standing rule as the Mint install
above.

**A real packaging bug was caught and fixed by this verification, not just confirmed working**:
`debian/orcshot.install`'s MIME-registration line (`src/orcshot/resources/orcshot-mime.xml
usr/share/mime/packages/orcshot.xml`, task #129) tried to rename the file on install by putting a
different filename in the destination column - but `dh_install`'s `.install` format always treats
that column as a destination *directory*, never a rename target. The actual result: a directory
literally named `orcshot.xml` got created with the real XML file nested inside it
(`usr/share/mime/packages/orcshot.xml/orcshot-mime.xml`), which the `shared-mime-info` trigger then
failed to parse (`I/O error: Is a directory`) the moment the package was actually installed - this
had gone unnoticed until now because nothing since task #129 had exercised a real `.deb` install,
only unit tests and live GTK checks of the app itself. Fixed by renaming the source resource file
itself to `orcshot.xml` (`git mv`) and changing the `.install` line to a plain directory destination,
matching every other line in that file. Rebuilt, re-verified with `dpkg-deb -c` that the path is now
a real file, and confirmed live on the VM: dependency resolution, install, and the triggers
(`desktop-file-utils`, `hicolor-icon-theme`, `gnome-menus`, `shared-mime-info`) all completed with no
errors, `dpkg -l orcshot` shows `ii` (properly installed, not stuck in a broken state), and
`/usr/share/mime/packages/orcshot.xml` is a real, correctly-parsed XML file containing the
`application/x-orcshot` type.

**Installed binary verified live, not just the package metadata**: after clearing a leftover
dev-source `orcshot.app` process from earlier Wayland testing in the same VM (it had been squatting
on the `org.orcshot.Orcshot` D-Bus name, silently absorbing the first launch attempt via GIO's own
single-instance forwarding rather than actually testing anything), `/usr/bin/orcshot` (the real
`[project.scripts]` entry point, not `python3 -m orcshot.app`) was launched via `VBoxManage
guestcontrol` and confirmed to stay running and register `org.orcshot.Orcshot` on the session D-Bus.

**Three findings along the way turned out to be artifacts of `guestcontrol`'s incomplete environment,
not real bugs** - `guestcontrol` doesn't inherit the graphical session's environment at all (only the
three vars this project's own VM-testing notes already call out), and this exercise found the list was
still incomplete for a GUI app that needs XWayland:
- The tray icon didn't render at first because `XDG_SESSION_TYPE` wasn't set (`_build_tray_icon`,
  `app.py`, branches on it to choose `AyatanaAppIndicator3` vs `Gtk.StatusIcon`) - without it the
  process silently took the X11 branch under Wayland, producing exactly the `gtk_widget_get_scale_factor`
  failure task #66/#70 already documented for *that* branch specifically (not the harmless one it was
  first mistaken for here). Fixed by adding `--putenv=XDG_SESSION_TYPE=wayland`.
- A real capture (`PrtScrn`, forwarded via GIO's single-instance mechanism into this already-running
  process) crashed with `Xlib.error.DisplayNameError` - `region_select_gnome_shell.py`'s cursor
  backend needs XWayland's X11 protocol for cursor-position queries even on Wayland, and `$DISPLAY`
  was never set. Fixed by adding `--putenv=DISPLAY=:0` (confirmed via the running `Xwayland :0` process).
- Same capture then crashed with `Xlib.error.DisplayConnectionError: ...Authorization required...` -
  `$XAUTHORITY` was missing too. Fixed by pointing it at XWayland's own auth cookie
  (`--putenv=XAUTHORITY=/run/user/1000/.mutter-Xwaylandauth.<random>`, read off the running
  `Xwayland` process's own `-auth` argument). With all of `XDG_SESSION_TYPE`/`DISPLAY`/`XAUTHORITY`
  set, a real `PrtScrn` → region-select → destination-picker round trip completed with no crash.

**A real, separate bug was found this way, not an artifact**: the destination-picker popup that
successful capture opened showed no icons at all (not wrong-colored - absent). Confirmed via isolated
testing that this is deeper than the task #127/#128 icon-color fix (calling `destination_icon_image`
directly with the same resolved color produces a correct, visible pixbuf saved to PNG) - the defect is
specifically in how that pixbuf composites inside a live `menu.popup_at_rect()` Wayland popup. Filed as
task #133 rather than chased further here, since diagnosing on-screen compositing issues has no good
tooling through `guestcontrol` round-trips - needs direct visual access.

### Ubuntu 24.04 LTS (task #38, complete 2026-08-15)

GNOME Shell 46 (mutter-14) is not just an older version of the GNOME Shell 50 (mutter-18) this port's
bundled `orcshot-clipboard` extension was originally built and verified against (task #77/#82) - several
Clutter APIs the extension relies on differ in ways that are not simple "old vs new" substitutions.
Confirmed live on the Ubuntu 24.04 VM, not assumed from a version number, using the same
`GI_TYPELIB_PATH`/`GObject.signal_query()` introspection technique this project already established for
St vs. Clutter/Meta's differing typelib paths (see the Wayland section above).

**Fixed - `Clutter.PanGesture` absence** (`extension.js`'s `_attachPanGesture`, shared by
`RegionSelectOverlay` and `EyedropperOverlay`): GNOME 50 has the new unified `Clutter.PanGesture`
API; GNOME 46 only has the older `Clutter.PanAction`/`GestureAction`, and neither Shell version has
both. A hard requirement on `PanGesture` crashed both overlays' constructors outright on 24.04
("`Clutter.PanGesture` is not a constructor"), surfacing only as a silent `StartRegionSelect` promise
rejection with no client-visible error at all (PrtScrn and the tray's Capture Region did nothing).
Fixed with a feature-detected `_attachPanGesture` helper that normalizes both APIs' differing signal
names (`recognize`/`pan-update`/`end`/`cancel` vs. `gesture-begin`/`gesture-progress`/`gesture-end`/
`gesture-cancel`) to the same `onBegin(x,y)`/`onUpdate(x,y)`/`onEnd()` shape.

**Fixed - `Clutter.CursorType` absence** (`extension.js`'s `_setCrosshairCursor`): the same
two-way-incompatible pattern going the other direction - `actor.set_cursor_type(Clutter.CursorType.
CROSSHAIR)` works on GNOME 50 but doesn't exist at all on GNOME 46; `Meta.Display.prototype.
set_cursor(Meta.Cursor.CROSSHAIR)` is that version's real replacement, but doesn't exist on GNOME 50
in turn. This error (`TypeError: (intermediate value).CursorType is undefined`) was only discoverable
after wrapping `StartRegionSelect`/`StartWindowPicker`/`StartEyedropper` in try/catch + `logError`
(matching `CaptureRect`'s existing pattern) - GJS's own D-Bus dispatch (`modules/core/overrides/
Gio.js`) silently drops the real exception message from "Unhandled promise rejection" log entries
otherwise. Fixed with a feature-detected `_setCrosshairCursor` helper, with an explicit cursor reset
on the actor's `destroy` signal for the `Meta.Display` path (that API's own override doesn't revert
itself automatically the way the per-actor one does).

**Fixed - drag always anchored at the stage origin instead of the real press point**
(`_attachPanGesture`'s `PanAction` branch): once the two crashes above were fixed, the overlay
appeared correctly but every drag started from `(0, 0)` regardless of where the mouse was actually
pressed, with the far corner tracking the real drag correctly - "set select area to top left by
default and let me move where the rest of the box would drag" was the live report. Confirmed via a
temporary diagnostic that `action.get_motion_coords(0)` returns `(0, 0)` inside the `gesture-begin`
handler specifically (motion tracking for the point hasn't been populated yet at that exact instant),
while `action.get_press_coords(0)` correctly holds the real press position from the moment of press.
`get_motion_coords` is correct from `gesture-progress` onward, once real motion has occurred. Fixed by
switching `gesture-begin`'s handler to `get_press_coords(0)`.

A closely related bug fixed alongside the above, same root cause class: `GestureAction::gesture-begin`
and `::gesture-progress` are `gboolean`-returning signals (confirmed live via `GObject.signal_query()`
against the real mutter-14 typelib) - the handler's return value is GestureAction's own vote on
whether to accept the gesture. The original handlers had no explicit `return`, so GJS marshaled the
implicit `undefined` to `false` ("reject"), which made GestureAction cancel its own gesture ~7ms after
every `gesture-begin`, before any drag could happen at all - confirmed live via a temporary diagnostic
logging each signal: `gesture-begin` immediately followed by `gesture-cancel`, no `gesture-progress` in
between, every single time. This was the actual cause of the overlay disappearing the instant the
mouse button was pressed (reported as "it dies when i try to click and drag"). Fixed by adding
`return true;` to both handlers.

**Fixed - "Edit" (and every other) destination never opening/completing after the picker closes**
Root cause was not in the drag/select logic or `pickDestinationAsync` at all (both traced and
confirmed working correctly via live diagnostics logging each step of `pickDestinationAsync`'s
`activate`/`open-state-changed`/`resolve` chain and `RegionSelectOverlay.selectAsync()`'s own
post-picker steps - every one fired exactly as expected, ending in `StartRegionSelect` genuinely
returning a valid `[true, 'edit', pngBytes, x, y, width, height]` array). The real defect was one
level up, in GJS's own D-Bus dispatch: `Gio.DBusExportedObject`'s `_handleMethodCall`
(`modules/core/overrides/Gio.js`) only recognizes a method as async via the `MethodNameAsync`
naming convention (`this[`${methodName}Async`]`, taking `(parameters, invocation, fdList)` and
calling `invocation.return_value(...)` itself) - a bare `async StartRegionSelect()` is invoked
*synchronously*, so `retval` ends up being the returned Promise object itself, which then fails to
pack into a `GLib.Variant` and gets silently converted into a DBus error reply, with **no local
logging at all** (that specific catch block has no `logError` call - confirmed by pulling GJS's own
`overrides/Gio.js` straight off the running Shell via `Gio.resources_lookup_data()` and reading
`_handleMethodCall` directly, not assumed). This exactly explains the original symptom set: no
exception anywhere, `on_reply`'s own try/except never even reached its first line (since
`connection.call_finish()` raises `GLib.Error` for the DBus error reply, caught by the existing
`except GLib.Error:` branch, which is a silent no-op since `on_cancelled` is never supplied for this
call site), and the D-Bus reply genuinely never containing a value Python could use.

GJS 1.80.2 (bundled with Ubuntu 24.04/GNOME Shell 46/mutter-14) has no Promise-detection branch in
`_handleMethodCall` at all - confirmed live via the same source pull. This file's own prior comment
citing that branch's existence was accurate for whatever newer GJS ships with GNOME Shell 50/Ubuntu
26.04/mutter-18 (where `StartRegionSelect` was already confirmed working as a bare async method) -
just not this one, the same "neither version is a superset of the other" pattern as every other
GNOME-46-vs-50 gap found this session. Since the D-Bus reply is the *only* thing every destination
depends on (drag/select itself needs no D-Bus round trip - pure Shell-side Clutter signals, which is
why capture looked fully functional right up to the destination-picker click), this silently broke
**every** destination on GNOME 46, not just the one that happened to get tested first.

Fixed by renaming `StartRegionSelect`/`StartWindowPicker`/`StartEyedropper`/`CaptureRect` to
`StartRegionSelectAsync`/etc. with the `(parameters, invocation)` signature GJS's dispatch actually
supports, each now marshaling its own `GLib.Variant` (matching `CAPTURE_IFACE`'s declared out-arg
types exactly) and calling `invocation.return_value(...)` directly instead of `return`ing a value.

All temporary diagnostics (Python print statements, the `extension.js` `captured-event`/gesture-signal
loggers, the `pickDestinationAsync`/`selectAsync` step loggers, the `GrabHelper`/`grabHelper.js` and
`overrides/Gio.js` source dumps) were removed once each fix was confirmed - only the real fixes above
remain in the committed code.

**Not a real bug - crosshair cursor briefly appeared stuck during diagnostic iteration, but resets
correctly on a real install.** First observed while testing the async-dispatch fix above against a
diagnostic-patched dev instance running from source via `PYTHONPATH` override on the original (pre-
crash) Ubuntu 24.04 VM. After that VM crashed and was rebuilt from scratch and a real `.deb` built
from this same commit was installed fresh (`sudo apt install ./orcshot_0.1.0-1_all.deb`, no source-
tree overrides involved), a full capture round trip - drag-select, Edit, editor opens with the
captured image, cursor back to a normal arrow immediately after - worked correctly with no special
handling needed. The original observation was most likely an artifact of the rapid extension-reload/
diagnostic-patching cycle on the earlier VM (a stale actor reference, or a `destroy` signal that
hadn't fully propagated between edits) rather than a defect in `_setCrosshairCursor`'s reset logic
itself.

**Real, separate bug found during the .deb reinstall on the rebuilt VM: the first-run setup dialog's
extension-enable checkboxes don't actually persist.** `ui/first_run_setup.py`'s "Enable reliable
'Copy to Clipboard' support" checkbox was checked and the dialog confirmed with OK, yet
`gsettings get org.gnome.shell enabled-extensions` came back `@as []` afterward - confirmed from the
user's own terminal on the VM, not just this session's own `guestcontrol` queries, ruling out a
stale-session-bus explanation. `gnome_extension_setup.enable_extension`'s logic (read `enabled-
extensions` via `GioSettingsBackend`, add the UUID if missing, write back) and its call site in
`first_run_setup.py` both read correctly by inspection - the actual defect hasn't been root-caused
yet. Worked around for this session by having the user run the equivalent
`gsettings set org.gnome.shell enabled-extensions "['orcshot-clipboard@orcshot.org']"` directly in
their own terminal (which stuck correctly), then logging out/in - the extension then showed
`enabled: true, state: 1` (ENABLED) via `org.gnome.Shell.Extensions.ListExtensions`, and capture
worked normally after that. Filed as a new task rather than chased further here - worth a fresh
`systematic-debugging` pass of its own (reproduce with a print/log added directly to `enable_extension`
itself, confirm whether it's even reached, before guessing further).

**Verification summary**: with the async-dispatch fix installed via a real `.deb` on a fresh Ubuntu
24.04 install (not a source-tree/`PYTHONPATH` dev override), a full capture round trip was confirmed
working end-to-end for: region-select → Edit (editor opens with the captured image, cursor resets
correctly), region-select → Copy to Clipboard, and Window Picker capture → Open in External Editor.
Two new, separate bugs surfaced during that last check - a destination-picker-menu artifact bleeding
into window-picker captures, and the captured window's title bar being excluded - filed as tasks #134
and #135 rather than folded into this one, since task #38's own actual scope (the GNOME-46
compatibility blockers) is now fully resolved.

**Both #134/#135 turned out to be one real bug plus one false alarm, not two GNOME-46-specific
issues** - see the section below.

## Tray menu doesn't close before the next capture mode starts (task #134, complete 2026-08-15)

Not a bug in `extension.js` at all, despite the initial diagnosis (see task #38's own section above,
which originally suspected the post-capture destination picker) - the real defect was in `app.py`'s
tray menu, and it predates today's GNOME 46 work entirely. Every tray menu item's `"activate"` handler
called its capture-mode-starting method directly and synchronously
(`region_item.connect("activate", lambda _item: self.start_region_capture(...))`, same shape for every
item) - a classic "closed a menu and started new UI work in the same callback" race: the menu's own
popdown/hide is itself just a request queued during that same signal emission, not something guaranteed
to have reached the display server yet, so a capture that starts synchronously can grab a screenshot
(or, for Window Picker, a specific window's frame rect) before that request has actually been
processed - a fragment of the still-technically-visible menu ends up baked into the resulting image.

Confirmed live by direflail across platforms: reproducible on Mint (X11) and Ubuntu 24.04/GNOME 46,
not reproducible on Ubuntu 26.04/GNOME 50 - almost certainly a relative-speed difference between
display stacks rather than a different code path, since the exact same synchronous call pattern is
used identically everywhere. Fixed with a small `_defer()` helper (`GLib.idle_add()`, run once and
returns `GLib.SOURCE_REMOVE`) wrapping all five tray-menu-item capture calls (region, full screen,
active window, window picker, repeat last region) - yields one main-loop iteration so GTK's own
popdown handling (and, on X11, the display flush) completes before the next capture starts. Verified
live: no more menu fragment in the captured pixels, on a confirmed Wayland session with both bundled
extensions enabled.

**Task #135 (captured window excluding its title bar) turned out not to be a real, separate bug** -
re-tested under the same confirmed-Wayland conditions and the title bar was correctly included via
`WindowPickerOverlay`'s existing `metaWindow.get_frame_rect()`. The original observation was made
while the VM's session had silently become X11 (see below) with the `window-calls` extension not yet
enabled, so "Capture Window" was actually running through the entirely separate X11-native code path
that day, not `extension.js` at all.

### A real process lesson: X11 vs Wayland is not something you can assume stays constant

The Ubuntu 24.04 VM crashed mid-session and was rebuilt from the same installer (direflail just bumped
RAM/resolution) - the rebuilt VM silently came up in an X11 session instead of Wayland, and stayed
that way through several further logout/login cycles before anyone noticed. GDM remembers the last-
picked session type from its own login-screen gear icon; something about the rebuild changed what it
defaulted to. Every "it works!" check made in the meantime (several of task #38's own "confirmed live"
claims, task #134/#135's original diagnoses) was actually exercising the *X11-native* capture path, not
the GNOME Shell extension path the day's actual bug fixes targeted - real time was spent chasing a
"destination-picker menu" theory for #134 that never had anything to do with `extension.js` at all,
purely because the environment wasn't what it was assumed to be.

Two things came out of this, beyond just re-verifying everything under a confirmed Wayland session
(`loginctl show-session <id> -p Type`, not assumed):

- `_log_session_info()` (`app.py`'s `do_startup`) now logs the detected session type, desktop, and
  (on Wayland) GNOME Shell extension availability once at every real startup - `[orcshot]
  session_type=... desktop=... -> ...`. Purely diagnostic, changes no behavior - the existing per-
  capture `XDG_SESSION_TYPE` checks in `region_select.py`/`window_picker.py`/`_build_tray_icon` were
  already correct (read fresh at each decision point, not cached at import time), so there was nothing
  to fix architecturally - what was missing was just visibility into which path a given run actually
  took, for exactly this kind of situation.
- The bundled `window-calls` extension (separate from `orcshot-clipboard`, both offered by the same
  first-run-setup dialog) needs to be enabled independently for Window Picker/Active Window capture to
  work at all on Wayland (`capture/backend_select.py`'s `window_picker_supported()`) - easy to forget
  when manually re-enabling extensions via `gsettings` after a first-run-dialog issue, since only the
  clipboard one was fixed that way earlier this same session.

**Final verification, confirmed Wayland session, real install**: with both bundled extensions enabled
and the session type directly confirmed via `loginctl` (not assumed), the built `.deb` was reinstalled
fresh (`sudo apt install ./orcshot_0.1.0-1_all.deb` over the already-installed version) and every
capture flow re-tested against that real, freshly-launched process - no dev-source/`PYTHONPATH`
override involved this time: region-select → Edit, region-select → Copy to Clipboard, Window Picker,
and Active Window capture all confirmed working correctly by direflail, with no tray-menu artifact and
the title bar correctly included. Also confirmed as expected, unrelated-to-this-work behavior: keybindings
and the first-run-setup-done marker both survived the reinstall untouched, since `dpkg`/`apt` only ever
touch a package's own files under `/usr/` - user-level `dconf`/`gsettings` state and Orcshot's own
settings live entirely in the user's home directory, independent of any specific package install.

## Launchpad PPA test-environment fragility (task #102, fixed 2026-08-15)

First real PPA upload (`ppa:artificialorctelligence/orcshot`, `0.1.0-1`) failed to build -
`TestRenderStepLabel::test_draws_the_circle_like_an_ellipse` failed on Launchpad's build farm chroot
even though the full suite was green locally immediately beforehand. The assertion sampled a single
pixel expected to be pure DarkRed fill `(139, 0, 0)` and got `(139, 3, 38)` instead - the red channel
matched exactly, but green/blue picked up a small amount of colored fringing. That specific pattern
(one channel exact, the other two off by different amounts) is the signature of subpixel-antialiased
glyph-edge rendering, not a uniform alpha blend - the StepLabelShape's white "1" digit glyph rendered
with different Cairo/fontconfig antialiasing defaults in Launchpad's minimal build chroot than on this
dev machine, and its anti-aliased edge reached this "away from dead center" sample pixel differently.
Not a real rendering bug in the app - `test_draws_the_number_in_a_contrasting_color`, right below the
fixed test, already handles this same class of environment sensitivity via `_colored_pixel_bounds`'s
own `tolerance` parameter. Fixed by making the failing test tolerant the same way (max per-channel
diff ≤ 40, comfortably covering the observed diff of 38 while still catching a genuinely wrong fill).

Practical consequence for future PPA uploads: **once a source version is accepted by Launchpad, it
can't be re-uploaded even if the build itself failed** - a failed build still consumes that version
number. Re-uploads need a bumped `debian/changelog` version (`0.1.0-1` → `0.1.0-2` here) even for a
test-only fix with no user-facing behavior change.

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
**`_external_editor_cache_dir` (`ui/editor_window.py`) created `~/.cache/orcshot/` with
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

## Obfuscation hardening: Solid Fill and Color Scramble (task #60, complete 2026-08-09)

**The research question that started this**: are Blur/Pixelize actually secure redaction, or just
visual obfuscation? Checked rather than assumed. Found real, documented prior art:
[Greenshot issue #387 "Add noise to obfuscate-tool"](https://github.com/greenshot/greenshot/issues/387)
(Feb 2022, citing BishopFox's `unredacter`) is where this Linux port's own noised-Pixelize design
(`core/filters.py`'s `pixelize()`, `secrets`-CSPRNG-seeded jittered blocks) actually traces back to -
confirmed by reading the real Windows `PixelizationFilter.cs`, which does use
`System.Security.Cryptography.RandomNumberGenerator` internally, unlike `BlurFilter.cs` (no such
import at all - a genuinely deterministic, easily-invertible box blur with zero hardening). The
GitHub issue thread itself is a cautionary tale worth recording: two community members proposed a
**static, shared noise layer "distributed with the Greenshot binary"** as an alternative to genuine
per-render randomness (to solve a real WYSIWYG problem the maintainer raised - noise that changes on
every repaint doesn't match what gets saved) - which would have been a real security regression, since
a public, shared noise pattern is trivially subtractable by anyone with the same open-source binary.
This port already avoids that trap: `ObfuscateShape.seed` (task #51) is drawn fresh from the OS CSPRNG
**per shape**, then pinned to that instance - solving the same WYSIWYG problem without ever using a
shared/predictable pattern.

Even so, broader security research (Depix, `unredacter`, multiple academic papers, and a Bleeping
Computer writeup on reversing pixelated redactions) is close to unanimous: pixelization/blur - noised
or not - are block-averaging/low-pass operations, and the block statistics themselves leak real
information regardless of noise sprinkled on top. The universal recommendation for anything genuinely
sensitive is solid, opaque redaction - "there is nothing to reverse" - not a better blur.

**What shipped**: two new `ObfuscateMode` values alongside the existing Blur/Pixelize, each with a
different, honestly-labeled security property:

- **Solid Fill** (`core/filters.py`'s `solid_fill()`) - unconditionally overwrites the covered region
  with a single caller-chosen color (default opaque black, the standard redaction convention). The
  only mode with a provable zero-information guarantee: the output depends only on the chosen color,
  never on any pixel of the original image. **Now the default obfuscate mode** (was Pixelize) - the
  one deliberate deviation from the real Windows source's own default in this whole port, made
  explicitly because Pixelize/Blur are both documented-reversible via public tools and Solid Fill is
  the only mode that actually is what a "redaction" tool implies.
- **Color Scramble** (`core/filters.py`'s `scramble()`) - extracts only the covered region's coarse
  per-channel color statistics (mean, std-dev with a noise floor for flat regions), then synthesizes
  entirely fresh random pixels from that distribution, lightly smoothed for a less static-y look. No
  actual pixel value from the original ever survives into the output at any position - the property
  Depix/`unredacter`-style attacks depend on (matching a candidate against a *specific* block
  position), and what distinguishes this from Pixelize, which keeps exact block-position averages
  even with noise on top. Deliberately still leaks the region's dominant hue/lightness (e.g., flesh
  tones would still suggest a photo of a person) - an accepted, explicitly-labeled tradeoff for a
  more attractive default than a flat box, not a claim of full security.

**UI**: the style panel's mode dropdown now rates all four on a 3-tier scale - "Solid Fill (most
secure)", "Color Scramble (moderately secure)", "Pixelize (not secure)", "Blur (not secure)" - each
with a tooltip explaining why (Pixelize/Blur's cite Depix/`unredacter` by name). The always-visible
mode button itself stays short (just the mode name); the rating/reasoning only shows in the dropdown,
where someone's actually comparing options. Solid Fill gets its own color-picker field
(`STYLE_FIELD_OBFUSCATE_FILL_COLOR`, deliberately separate from the generic `STYLE_FIELD_FILL_COLOR`
other shapes use, since `ObfuscateShape` has no `ShapeStyle`); Color Scramble needs no extra field at
all - fully automatic, derived from the region itself.

**A real, pre-existing bug found and fixed along the way, unrelated to this feature but blocking its
own verification**: live-testing the new per-mode field visibility turned up `EditorWindow`'s style
panel showing *every* control at once regardless of active tool/selection - completely undermining
tasks #57/#58's whole point, for every tool, not just the two new obfuscate modes. Root cause:
`Gtk.Widget.show_all()` unconditionally re-shows every descendant, including the cells
`_refresh_style_panel()` had already correctly hidden during `__init__` (nothing is selected and
Select is the active tool at construction time) - and the real app
(`ui/destination_picker.py`'s `_open_editor`) calls `editor.show_all()` to actually display the
window, silently undoing the hide every single time an editor opens. Fixed by overriding
`EditorWindow.show_all()` to call `_refresh_style_panel()` again immediately after the real
`show_all()` - confirmed live (screenshot before/after) that the panel now correctly shows only the
fields relevant to whatever's active.

Verified live: unit tests for both new filter functions (`solid_fill`/`scramble`, including that a
uniform input region is *not* a no-op for Scramble - the accepted floor-noise tradeoff, unlike
Pixelize/Blur which correctly treat a flat region as one) and the tool-dispatch/style-field-visibility
logic, plus a real GTK session (window-scoped screenshots only, synthetic gradient test image, never a
real desktop capture) stepping through all four modes' style panel and rendering actual Solid
Fill/Color Scramble shapes to confirm the pixel output matches what each mode's own security claim
promises - a fully opaque flat box for Solid Fill, a grainy color-matched texture (not the smooth
original, not a flat block) for Color Scramble.

## Solid Fill preset redaction text (task #60 follow-up, complete 2026-08-09)

Solid Fill boxes can now carry an optional label drawn centered on top of the fill -
`ObfuscateShape.fill_text`/`text_color` (model-level default `""`/white - a neutral, opinion-free
default for bare construction, since there's no Windows source to be faithful to here), a fixed
preset list (None, REDACTED, CENSORED, CLASSIFIED, CONFIDENTIAL, SECRET, dropdown order unchanged)
via a new Text: dropdown next to Fill: in the style panel, plus its own Text Color: swatch. The
*editor's* own policy default (`EditorWindow._default_obfuscate_fill_text`, what a freshly-drawn
Solid Fill shape actually gets) is "REDACTED" - the most common real-world case - the same kind of
deliberate model/editor default split already established for `_default_obfuscate_mode` vs
`ObfuscateMode.PIXELIZE` above. Deliberately no free-text entry - anyone wanting a custom label
already has the separate Text tool; this isn't trying to become a second text-editing UI. Rendered by
`ui/render.py`'s `_draw_fitted_centered_text()`: measures at a generous starting font size with
wrapping effectively disabled, shrinks proportionally in one pass if it doesn't fit the box (not an
iterative search - Pango metrics scale close enough to linearly with font size for this), then centers
by hand via the computed `move_to` offset.

**Two real rendering bugs found and fixed while verifying this, both specific to this dev environment's
Cairo/Pango build (`cairo` 1.25.1 / PangoCairo 1.52.1), not this port's own logic**:

1. `PangoCairo.show_layout()` silently painted nothing at all in this environment when combined with
   `Pango.Alignment.CENTER` and a large nominal layout width - reproduced in total isolation (a bare
   `cairo.ImageSurface` plus 6 lines of raw PangoCairo calls, no code from this project at all).
   Root cause: Pango's own CENTER alignment centers within the layout's *set width*, not the visible
   canvas - `_draw_fitted_centered_text` sets a deliberately huge nominal width (10,000px) specifically
   to disable wrapping (see its own docstring), so combined with CENTER alignment the glyphs landed
   around x&asymp;5000, off any real canvas. Fixed by using `"near"` (left) alignment for the internal
   Pango layout instead - centering is already done entirely by hand afterward via the `move_to` offset
   computed from the actually-measured text width, so Pango's own alignment was redundant *and* actively
   harmful here.
2. The unit test asserting the drawn text's color appears "somewhere in the box" originally required an
   exact `(255, 255, 255, 255)` pixel match. At the test's own deliberately tiny stress-test font size
   (a ~40px box forces the fitted font down to ~5px), every glyph pixel is anti-aliased against the
   black fill rather than solidly covered, so no pixel ever hits pure white in all four channels even
   though the text clearly renders (confirmed by inspecting the actual pixel values - up to 251/245/248,
   never simultaneously 255/255/255). Relaxed the assertion to a "clearly light-colored pixel exists"
   threshold instead of exact equality - a test-fidelity fix, not a rendering change.

Verified live: unit tests for the new shape fields, tool dispatch, style-field visibility, and render
output (including the two bugs above); a real GTK session confirming the Text:/Text Color: cells only
show for Solid Fill (hidden for Blur/Pixelize/Color Scramble, matching `visible_style_fields`),
selecting a preset actually threads through to a newly-drawn shape's `fill_text`, changing the preset
retroactively updates the currently-selected shape (matching every other style-panel control's own
behavior), and the rendered box shows the chosen word correctly centered and fully legible.

Also fixed in passing, found while wiring the new Text Color: swatch: `_obfuscate_fill_swatch` (Solid
Fill's own Fill: color swatch, added in task #60 above) was never `queue_draw()`n by
`_refresh_style_panel`, unlike every other color swatch in the panel - a latent staleness bug (the
swatch could show a stale color right after switching selection, until some unrelated repaint happened
to refresh it) that the new Text Color: swatch would otherwise have shipped with too. Both are now
refreshed together.

## Obfuscate and Step Label toolbar icons (complete 2026-08-09)

Both icons were the two hardcoded exceptions to `ui/icons.py`'s own stated design (every tool icon is
hand-drawn Cairo primitives, theme-colored via a `color` param the way real desktop icon themes are) -
found while reviewing the panel built for task #86 above.

- **Step Label** used to reuse `render_step_label` directly on a real `StepLabelShape`, which draws in
  that shape's own fixed dark-red/white on-canvas style (`core/shapes.py`'s own default) - correct for
  the actual drawn element, but the one tool icon in the whole toolbar that silently ignored the given
  `color` and never changed with the theme. Replaced with a hand-drawn version matching the Ellipse
  tool's own icon technique: an unfilled stroked circle (`render_ellipse` with a transparent fill, the
  exact same call `_ellipse_icon` already makes) with a "1" centered inside, both in the passed color -
  same silhouette as before, now outline instead of filled and theme-aware like every other icon.
- **Obfuscate**'s single unified toolbar button (task #54) hardcoded `tool_icon_image(Tool.PIXELIZE,
  ...)` regardless of which mode was actually active - a real, colorful 3x3 grid standing in for the
  whole redaction feature, which read as decorative noise (reported live as "looks like a Rubik's
  cube") rather than communicating "conceal/redact." None of the four individual mode icons
  (Pixelize/Blur/SolidFill/Scramble) are otherwise ever shown anywhere - the mode dropdown itself is
  text-only (see task #60's own UI section above) - so there was no mode-specific icon actually being
  lost by replacing it. New `_obfuscate_icon`/`obfuscate_icon_image` (not keyed by `Tool`, called
  directly by `_build_obfuscate_control` in place of the old hardcoded `Tool.PIXELIZE` reference): a
  hand-drawn fedora-and-sunglasses "incognito" glyph (wide brim, narrower crown, two lenses joined by a
  bridge - the familiar Chrome-incognito/Font-Awesome-"user-secret" silhouette, used only as a loose
  proportions reference, not traced or embedded as an asset), monochrome and theme-colored like every
  other tool icon rather than the fixed-color mode icons it replaces.

Deliberately not a bundled/downloaded icon asset for either - this file's whole existing design
(explained in its own module docstring) is "no icon theme has standardized names for these tools," and
that reasoning holds just as well for "incognito redaction icon" as it does for "rectangle annotation
tool": no freedesktop icon-naming-spec category covers either, unlike the generic Undo/Redo/Copy/Save/
Print actions elsewhere in the editor, which do use real system theme icon names. Bundling a specific
third-party SVG would also need its own license attribution (this project already went through real
effort keeping packaging/licensing clean for the anonymous GPL3 release) and its own re-coloring
mechanism (`currentColor` substitution or mask-based re-tinting) just to stay theme-aware like the rest
of the toolbar - more moving parts than drawing the shape directly in the color already wanted.

Verified live: unit tests (`_obfuscate_icon` draws something visible, uses the given color, and changes
between colors, mirroring the existing per-tool color tests; Step Label moved from the "ignores color"
test into `_LINE_ART_TOOLS`, now covered by the same use-the-given-color/changes-between-colors checks
every other line-art icon already has) plus a real GTK toolbar screenshot (synthetic dark test image,
never real desktop content) confirming both icons render in the same theme gray as every other tool,
with the fedora/sunglasses silhouette and the outlined "1" circle both legible at actual 24px size.

**Two follow-up fixes from live review, same day:**

- The "1" looked slightly right-of-center. Root cause, confirmed by rendering the glyph and inspecting
  its ink column-by-column: `text_extents("1")`'s ink bounding box is itself asymmetric (a thin top-left
  flag against a full-height stem), so centering on ink bbox width - correct for the "A" glyph
  `_text_icon` uses, and what `_step_label_icon` originally copied - puts the *visually dominant* stem
  right of true center, since the eye weights the stem more than the thin flag. Fixed by centering "1"
  horizontally on its `x_advance` (the font's own full logical width, including its side bearings)
  instead of pure ink width - the font's built-in side bearings already balance this asymmetry for
  normal text flow, and reusing them here reads as properly centered. Vertical centering is unaffected
  (stays ink-bbox based - "1" isn't asymmetric top-to-bottom).
- Separately (not an icon bug): switching to/from the Select tool visibly yanked the whole
  toolbar-and-canvas up or down by ~30px, because the style panel row (`_build_style_panel`) has zero
  visible cells when Select is active with nothing selected (`visible_style_fields` correctly hides
  everything), collapsing the row's natural height to ~1px versus ~34px for any populated row -
  reported live as "it made me think something was broken." Fixed with a height floor
  (`_STYLE_PANEL_MIN_HEIGHT`, `box.set_size_request(-1, 42)` on the panel's outer box) sized from a live
  measurement of a populated row's actual allocation (34px) plus the 8px `set_border_width(4)` pads on
  top of whatever height is requested (confirmed empirically, not purely reasoned from GTK's box-model
  docs - asking for exactly 34 only allocated 26). `set_size_request` sets a floor, not a fixed height,
  so populated rows are unaffected; only the collapsed-to-1px case is floored to match. Verified live by
  measuring the style panel's actual allocated height across Select/Rectangle/Solid Fill/Select-again -
  all four now allocate identically to 34px, and a before/after screenshot pair confirms the canvas's
  on-screen position no longer shifts when switching to or from Select.

## Editor keyboard shortcuts and Help dialog rework (complete 2026-08-09)

By request: give every tool a key (Select had none before), and turn the Help dialog's plain
hand-padded text block into a real two-column table. New `_TOOL_KEYS` mapping (`ui/editor_window.py`) -
this port's own convenience layer, not a Windows port (`ImageEditorForm` has no cursor-tool shortcut at
all, and Windows has only one Obfuscate drawing mode, not four, so there's no per-mode shortcut to be
faithful to either):

| Key | Tool | | Key | Tool |
|---|---|---|---|---|
| \` | Select | | 6 | Obfuscate (whichever mode was last prepared) |
| 1 | Rectangle | | 7 | Text |
| 2 | Ellipse | | 8 | Speech Bubble |
| 3 | Line | | 9 | Step Label |
| 4 | Arrow | | 0 | Emoji |
| 5 | Freehand | | | |

Solid Fill, Color Scramble, Pixelize, and Blur have no keys of their own - only reachable through
Obfuscate's own Mode dropdown (task #54), same as before this port added any obfuscate-related keys at
all. **6 is deliberately not in `_TOOL_KEYS` itself** - unlike every other key, it isn't a 1:1 `Tool`
mapping (Obfuscate is one toolbar button standing in for four modes), so it's a dedicated check in
`_on_key_press` that calls the existing `_activate_obfuscate_tool()` helper directly - the same method
`BtnObfuscateClick`'s real Windows equivalent already documents itself as mirroring: activates whichever
mode is *currently prepared*, the same as a real click on the toolbar button, and never changes which
mode that is. Pressing 6 again while already in Obfuscate (any mode) is a correct no-op, matching every
other tool key already being a no-op when pressed again while that tool's active.

**This went through two earlier, wrong shapes before landing here, each corrected from live feedback**:
first, Solid Fill and Scramble got their own dedicated keys (6 and 7 respectively) in place of the
Pixelize/Blur keys they replaced - which meant pressing 7 while already drawing with Solid Fill would
force-switch to Scramble every time, reported live as "it should do nothing in this case." That was
tightened to a no-op-while-already-in-Obfuscate rule for 6/7 specifically - but that still didn't match
the actual ask, which was for Obfuscate to behave like a single tool with one key, exactly like every
other tool, resuming whatever mode/fill-color/text/text-color was last configured rather than forcing a
mode via which digit got pressed. The version documented above is that final shape - confirmed against
the real Windows source before implementing, not just reasoned out: `PreparedFilter` in the real
`ObfuscateContainer`/`FieldAggregator` is a `Field` on the same persistent, editor-session-lifetime
object that holds line color, fill color, thickness, and shadow - `BtnObfuscateClick` never touches it,
only the dropdown's own binding does. Tool-switching never implicitly changes a field in real Windows;
this port's per-tool style memory (`self._tool_styles`) already follows the identical principle for
color/thickness/shadow, and Obfuscate's own `_default_obfuscate_mode`/`_default_obfuscate_fill_color`/
`_default_obfuscate_fill_text`/`_default_obfuscate_text_color` (plain instance state nothing resets
except its own explicit setter) already worked this way too, once "6" stopped forcing a mode as a side
effect of merely re-entering the tool.

**Help dialog** (`_do_show_help`): rebuilt from a single `Gtk.Label` holding a hand-space-padded string
onto a real `Gtk.Grid` - two columns (key, function), one row per shortcut, a bold header row spanning
both columns above each group ("Tools", "Editing", "Actions", "Tray Icon"). The header sits flush left -
each key cell gets a small `set_margin_start` so it reads as slightly indented beneath its own section
header, matching the previous plain-text layout's visual relationship - by request, specifically kept
rather than redesigned. Real columns also fix a latent alignment problem the old hand-counted-spaces
version had: "Ctrl+Z / Ctrl+Y" is wider than every other Actions key, so the old manual padding was only
approximately aligned even before this change.

Added while restructuring, not previously documented anywhere in the app: the zoom/canvas shortcuts
(Ctrl +/-, Ctrl+Shift +/- , Ctrl+0, Ctrl+9 - all real, already wired in `_on_key_press`, just never
listed) and a new **Tray Icon** section - genuinely different behavior per platform, not just a wording
choice, so it's generated at runtime (same `XDG_SESSION_TYPE` check `app.py`'s own `_build_tray_icon`
already uses to pick which tray implementation to build) rather than describing both unconditionally:

- **X11** (`Gtk.StatusIcon`): left-click starts a region capture immediately; right-click opens the menu.
- **Wayland** (`AyatanaAppIndicator3.Indicator`): every click opens the same menu - no distinct
  left-click action exists, a real upstream AppIndicator limitation once a menu is attached
  ([launchpad.net/bugs/1910521](https://bugs.launchpad.net/bugs/1910521)), not a bug in this app or
  something fixable from here - see `app.py`'s own `_build_tray_icon` docstring for the full citation.

Verified live: unit tests still pass (no existing coverage of `_TOOL_KEYS`/`_on_key_press` to update -
this file has no dedicated test module at all, consistent with how the rest of its interactive behavior
in this project has always been verified - live GTK sessions, not headless pytest), plus a driven GTK
script confirming every tool key lands on the right `win.tool`, and specifically: configuring Solid Fill
with a black fill, white text color, and "REDACTED" text, switching to Ellipse, then returning via
*both* the "6" key and a real click on the toolbar button - both correctly resume the exact prior
configuration (mode, fill color, text color, and text all intact), and pressing 6 again while already in
Obfuscate changes nothing. Also a real screenshot of the rebuilt Help dialog confirming the table layout,
header/key indentation relationship, and (running under X11 in this dev environment) the X11-specific
Tray Icon wording.

## Editor keyboard shortcuts replaced with the real Windows letter-mnemonic scheme (task #92, complete 2026-08-10)

The backtick+1-0 layout documented in the section above was this port's own invented scheme, adopted
before the real one had been found - `ImageEditorForm.Designer.cs`'s `ShortcutKeys` properties are all
empty, which an earlier pass in this project mistook for "no shortcut exists." The real shortcuts live
in the actual `KeyDown` handler instead (`ImageEditorFormKeyDown`, `ImageEditorForm.cs:1055-1107`),
confirmed directly from source, not guessed:

| Key | Tool | | Key | Tool |
|---|---|---|---|---|
| Escape | Select | | H | Highlight (whichever mode was last prepared) |
| R | Rectangle | | O | Obfuscate (whichever mode was last prepared) |
| E | Ellipse | | C | Crop (whichever mode was last prepared) |
| L | Line | | M | Emoji |
| F | Freehand | | Z | Resize (a whole-image effect, not a `Tool`) |
| A | Arrow | | | |
| T | Text | | | |
| S | Speech Bubble | | | |
| I | Step Label | | | |

Every letter is real Windows, not invented - including **Escape for Select**, which directly corrects
the previous section's own claim that Select "has no clear Windows precedent": that was true of the
Designer.cs properties, false of the real `KeyDown` handler (`case Keys.Escape: BtnCursorClick(...)`).
H/O/C aren't `Tool` mappings in `_TOOL_KEYS` any more than the old "6" was - Highlight/Obfuscate/Crop
are each one toolbar button standing in for several modes, so they're their own dedicated branches in
`_on_key_press` calling `_activate_highlight_tool`/`_activate_obfuscate_tool`/`_activate_crop_tool`
(same reasoning the old "6" already established, just extended to the two tools built since). Z's
own bare-key handling (already correct, predates this task) is untouched - Ctrl+Z still means Undo,
disambiguated by `ctrl_held`, matching Windows' own identical Z-means-two-different-things-by-modifier
design.

Both GDK keyval cases are bound per letter (`Gdk.KEY_r`/`Gdk.KEY_R`, etc.) - GDK reports a distinct
keyval per case for letters (unlike the numeric row, where Ctrl++/Ctrl+Shift++ needed Shift-state
disambiguation instead - see the section above). Not a literal replica of Windows' own
`Modifiers.Equals(Keys.None)` check, which excludes Shift+letter entirely and would mean Shift+R does
nothing special in real Windows - a deliberate consistency choice with how this file already treats
every Ctrl-combo shortcut (both cases bound there too, e.g. `Gdk.KEY_z`/`Gdk.KEY_Z` for undo), not a
second, stricter convention invented just for these.

None of the existing Ctrl-modified shortcuts changed - they already matched Windows before this task
(confirmed again against the same `ImageEditorFormKeyDown` listing while verifying: Ctrl+Z/Y, Ctrl+Q/B/T/
G/I, Ctrl+Delete, Ctrl+,/. , Ctrl+/-, Ctrl+Shift+/-, Ctrl+0/9). The old collision-avoidance code for
"plain 0/9 switch tools, but Ctrl+0/Ctrl+9 are zoom" was deleted outright rather than kept dormant - it
only existed because the old scheme's Step Label(9)/Emoji(0) keys shared a base keyval with the zoom
shortcuts; with those tools moved to I/M, the collision it guarded against no longer exists.

The old special-cased "Escape cancels an in-progress crop selection" branch (added with task #91, before
this task existed) was removed too, not kept alongside the new general Escape→Select mapping - it's now
subsumed by it: switching tools away from Crop already discards an unconfirmed selection (the `tool`
property setter's own logic, task #91), so Escape→Select produces the identical effect as a special case
of the general rule, matching real Windows' own unconditional Escape=Cursor behavior rather than this
port's previous crop-only-scoped approximation of it.

Help dialog's "Tools" section rewritten to match; "Actions" gained rows for Ctrl+B/Q/T/G/I/Delete/,/. -
already-implemented shortcuts that were simply never listed before, discovered while rewriting the
section next to them, not a new task #92 behavior.

Verified live: a driven GTK script exercising every new letter (bare, not Ctrl) and confirming it lands
on the correct `win.tool`, including Escape→Select, and the H/O/C special dispatch landing on each
tool's currently-prepared mode (`Tool.HIGHLIGHT_TEXT`/`Tool.SOLID_FILL`/`Tool.CROP_DEFAULT` by default);
bare Z confirmed to call `_do_resize()` without changing `self.tool`, and Ctrl+Z confirmed to leave the
active tool alone too (undo path); every pre-existing Ctrl-combo shortcut (Border/Torn Edge/Drop Shadow/
Grayscale/Invert/Copy/Save/Print/Undo/Redo/Rotate CCW/Rotate CW) confirmed to still fire correctly and
uncollided with the new bare-letter dispatch; a real screenshot of the rebuilt Help dialog confirming
every row's wording and layout.

### Toolbar tooltip shortcut suffixes (task #92 follow-up, complete 2026-08-10)

By request: every icon tooltip that has a real keyboard shortcut now shows it in parentheses -
`"Select (Esc)"`, `"Rectangle (R)"`, `"Highlight (H)"`, `"Rotate Clockwise (Ctrl+.)"`, `"Save
(Ctrl+S)"`, and so on - covering the tool palette (`_TOOL_TOOLTIP_SHORTCUTS`, a small dict keyed by
the exact label already used in `_TOOL_LABELS`, plus `_with_shortcut`), the Highlight/Obfuscate/Crop/
Rotate/Resize buttons (hardcoded directly, one-off), the action toolbar (Save/Copy/Print/Delete/Undo/
Redo), and Crop's own Cancel button (`"Cancel (Esc)"` - accurate even though it's not a *dedicated*
key for Cancel specifically, just the observable effect of the general Escape→Select mapping
discarding an unconfirmed selection, per the section above). Tools/actions with no real shortcut
(Effects, Confirm, Preferences, Cut/Copy Shape/Paste Shape, Help, External Editor) were deliberately
left with a plain label rather than inventing one.

Verified each suffix via `get_tooltip_text()` on the actual constructed widget for every case except
the action toolbar's `Gtk.ToolButton`s, where that getter returns `None` even immediately after
`set_tooltip_text()` - confirmed to be a pre-existing quirk of this GTK/PyGObject environment
specifically for `Gtk.ToolItem` subclasses (a plain `Gtk.Button`/`Gtk.RadioButton` round-trips
correctly; a bare `Gtk.ToolButton` does not, even with `set_has_tooltip(True)` forced explicitly),
not something this change caused - it affects buttons this task never touched (Preferences/Help)
identically. A tooltip *popup* itself renders in its own separate top-level window a main-window
screenshot can't capture regardless, so that avenue couldn't close the loop either; treated as
sufficiently verified given every other tooltip category round-trips correctly and this one is a
same-call-site text edit to an already-shipped, already-working `set_tooltip_text()` invocation from
an earlier task, not new mechanism.

## Editor title bar text (complete 2026-08-09)

`EditorWindow`'s title changed from "Greenshot Linux" to "Greenshot for Linux image editor", by
request. Only the editor window itself - the tray icon's own tooltip and the About dialog's program
name (both still "Greenshot Linux") weren't part of this request and were left alone.

## Speech Bubble tail anchor point (complete 2026-08-09)

Real bug, reported live with a screenshot: the tail visibly moved to a different side of the bubble
depending on which direction you dragged from the same start point, rather than staying put. Root
cause: `create_shape_from_drag`'s old formula derived the tail's target from the *final* bounding box's
bottom-left corner (`bubble_bounds.left`, `bubble_bounds.bottom + 30`) - but `Rect.from_points` always
normalizes `start`/`end` into a proper left<=right/top<=bottom rect regardless of which way you actually
dragged, so "the bottom-left corner" can correspond to any of the four *actual* dragged corners
depending on direction, making the tail seem to jump around unpredictably.

Fixed as a faithful port of the real Windows source (`Greenshot.Editor/Drawing/SpeechbubbleContainer.
cs`), not guessed - its own `HandleMouseDown`/`HandleMouseMove` carry a comment citing a real prior
Windows bug ("BUG-1682") this exact mechanism was built to fix: the tail is anchored to
`_initialGripperPoint`, the drag's own fixed start point (mouse-down location, never moves for the rest
of the drag), offset by a constant 20px in each axis - the offset's *sign* flips based on
`leftAligned`/`topAligned` (whether the box is still growing in its original direction or has been
dragged back past the start point), so the tail always points away from wherever the bubble is
currently growing, never into it. Ported directly: `core/tools.py`'s `_SPEECH_BUBBLE_TAIL_DROP` (a
single 30px drop below the bottom-left corner) replaced with `_SPEECH_BUBBLE_TAIL_OFFSET = 20` and the
same `end[0] >= start[0]` / `end[1] >= start[1]` direction check Windows' own `Right - Left >= 0` /
`Bottom - Top >= 0` comparison amounts to once you account for Windows' own `Rectangle` not
auto-normalizing negative width/height the way this port's `Rect.from_points` does.

Verified: new unit tests asserting the tail always sits exactly 20px outside the start point in both
axes regardless of drag direction (4 directions tested), that it points the correct diagonal direction
for two opposite drags, and that reversing a drag past its own start point flips the offset rather than
leaving the tail stranded mid-drag. Also live in a real GTK session - two bubbles dragged in opposite
diagonal directions both show the tail correctly pointing away from the bubble, anchored near the drag's
own start point in both cases.

## Highlight tool (task #88, complete 2026-08-09)

Faithful port of `Greenshot.Editor/Drawing/HighlightContainer.cs` and its four filters, cited directly
rather than guessed (per this project's own port-verification rule): the real toolbar exposes a single
`btnHighlight` button (`ImageEditorForm.Designer.cs`, `LanguageKey="editor_drawhighlighter"`) plus a
`highlightModeButton` dropdown with four `Tag`s drawn from `FilterContainer.PreparedFilter`:
`TEXT_HIGHTLIGHT` (sic - the real enum member has this exact typo, corrected in this port's own
`HighlightMode.TEXT_HIGHLIGHT` since it's purely an internal identifier with no user-visible spelling to
preserve), `AREA_HIGHLIGHT`, `GRAYSCALE`, `MAGNIFICATION`. `HighlightContainer.ConfigurePreparedFilters`
swaps in a different filter (or filter pair) per mode:

- **Text Highlight** -> `HighlightFilter` (`Filters/HighlightFilter.cs`): per-pixel
  `Color.FromArgb(color.A, Min(highlight.R, color.R), Min(highlight.G, color.G), Min(highlight.B,
  color.B))` against the default `FILL_COLOR = Color.Yellow` - since yellow's blue channel is 0, this
  clamps every pixel's blue channel to 0 inside the shape's own bounds, tinting it yellow without ever
  brightening anything. Non-invert (paints inside its own bounds only).
- **Area Highlight** -> `BrightnessFilter{Invert=true}` (default `BRIGHTNESS=0.9`) chained with
  `BlurFilter{Invert=true}` (default `BLUR_RADIUS=3`) - both inverted, so together they darken+blur
  everything *outside* the shape's bounds, leaving the shape's own interior untouched: a "spotlight"
  effect, not a highlight-the-inside effect.
- **Grayscale** -> `GrayscaleFilter{Invert=true}` - same spotlight semantic, desaturating everything
  outside the shape's bounds.
- **Magnification** -> `MagnifierFilter` (`Filters/MagnifierFilter.cs`, default `MAGNIFICATION_FACTOR=2`,
  non-invert) - crops a `rect.Width/factor` x `rect.Height/factor` region centered on the shape's own
  center, then `DrawImage`s that crop stretched to fill the full shape bounds using
  `InterpolationMode.NearestNeighbor` (a hard-edged zoom, not smoothed).

Ported to `core/shapes.py`'s `HighlightShape`/`HighlightMode` and `core/filters.py`'s `highlight_filter`/
`brightness_filter`/`grayscale_filter`/`magnify_filter` (the first three already existed in this
codebase, written but never wired up or tested until now; `magnify_filter` is new, replicating
`MagnifierFilter.Apply`'s exact `halfWidth`/`halfHeight`/`newWidth`/`newHeight`/`source` arithmetic).
`ui/render.py`'s `render_highlight` reproduces the real `GraphicsState.SetClip(applyRect);
ExcludeClip(rect)` invert mechanism using Cairo's even-odd fill rule (a full-canvas rect XOR'd with the
shape's own bounds, clipped, then the filtered full-canvas surface painted through that clip) - critically,
because it clips rather than painting-then-erasing, an *earlier* shape sitting inside a *later*
invert-mode Highlight's own bounds survives untouched, matching Windows' own clip-based (not
paint-order-based) exclusion. Toolbar/style-panel wiring in `ui/editor_window.py` mirrors the existing
Obfuscate mode-dropdown architecture exactly (`_HIGHLIGHT_GROUP` sentinel, `_build_highlight_control`,
`_set_highlight_mode`/`_activate_highlight_tool` split matching Windows' own `BindableToolStripDropDownButton`
vs `BtnHighlightClick` separation), positioned in the toolbar immediately before Obfuscate, matching the
real `toolsToolStrip.Items` order confirmed directly from the Designer file.

**Bug found and fixed along the way, affecting already-shipped Obfuscate code too**: `_set_obfuscate_mode`
and (the new) `_set_highlight_mode` had an `if isinstance(shape, ...): ... elif self.tool in
_MODE_ORDER: self.tool = mode` structure, treating "a shape is selected" and "the tool itself should
track this mode" as mutually exclusive. Since drawing a shape leaves it selected, changing that shape's
mode via the dropdown updated only the *shape*, never `self.tool` - so the next shape drawn without first
re-clicking the tool button silently used the stale old mode. Reproduced live for both Highlight
(`HIGHLIGHT_TEXT` -> `HIGHLIGHT_AREA`) and Obfuscate (`SOLID_FILL` -> `SCRAMBLE`) before the fix, confirmed
gone after. Fixed by making the two updates independent (`elif` -> `if`) rather than removing the
selected-shape branch, since both need to happen together, not as alternatives.

Verified: 9 new `render.py` unit tests (`TestRenderHighlight`, covering all 4 modes' pixel output against
the filters module directly, that non-invert modes paint nothing outside their bounds and invert modes
paint nothing inside, and specifically that a shape drawn earlier *inside* a later invert-mode Highlight's
bounds survives), `filters.py` unit tests for the 3 previously-untested filter functions plus the new
`magnify_filter` (`TestHighlightFilter`, `TestBrightnessFilter`, `TestGrayscaleFilter`,
`TestMagnifyFilter`), and `tools.py` unit tests mirroring the existing Obfuscate
`TestCreateShapeFromDrag`/`TestVisibleStyleFields` coverage for all 4 Highlight tools/modes. Also live in a
real GTK session: Text Highlight and Area Highlight (strong test brightness, since the real default 0.9 is
a deliberately subtle ~10% darkening) both visually confirmed painting only where expected; Grayscale
visually confirmed preserving its own interior's original color while desaturating everything else;
Magnification confirmed via direct pixel-level inspection of the shape object the live UI actually created
(not just the isolated filter function), since a smooth test gradient made the zoom effect hard to judge
by eye alone.

## Crop tool (task #91, complete 2026-08-09)

Faithful port of `CropContainer.cs` plus its supporting `Surface.cs` methods, cited directly rather
than guessed. Architecturally the first tool in this port that doesn't produce a persistent
annotation shape — `CropContainer.IsUndoable => false` / `HasContextMenu => false` in the real
source, and functionally it's a one-time "transform the whole canvas on confirm" operation
(`Surface.ConfirmCrop`), not something composited into the image like every other drawing tool.
`core/crop.py`'s pure functions (`crop_to_rect`, `crop_out_vertical_strip`,
`crop_out_horizontal_strip`, `autocrop_rect`) already existed — built ahead of time during an
earlier task in anticipation of this one, already tested — so this task was entirely the
interactive UI layer on top of them: `editor_window.py` tracks the in-progress selection as a plain
`Rect` (`self._crop_selection`), never a `Layer` entry, confirmed or cancelled via the style
panel's own Confirm/Cancel buttons.

- **Three modes, one toolbar button** — `Tool.CROP_DEFAULT`/`CROP_VERTICAL`/`CROP_HORIZONTAL`
  mirror Highlight/Obfuscate's own four/three-Tool-values-one-button architecture, but *without*
  the Tool↔shape-mode translation dance those two need (`_TOOL_TO_HIGHLIGHT_MODE` etc.) — since no
  Shape ever exists for Crop, the Tool values directly *are* the modes `core/crop.py` dispatches on.
  Real dropdown order confirmed from `cropModeButton.DropDownItems`
  (`ImageEditorForm.Designer.cs:1143-1145`): Default, Vertical, Horizontal, then Auto — the last is
  a plain one-shot trigger item, not a fourth persistent mode (matching `InitCropMode`,
  `ImageEditorForm.cs:1674-1696`: `AutoCrop()` seeds a rect and leaves the UI in *Default* mode
  going forward, never tracking "AutoCrop" as ongoing state anywhere).
- **Default crops *to* the selection** (`crop_to_rect`, keep-this-discard-rest); **Vertical/
  Horizontal crop it *out*** (`crop_out_vertical_strip`/`crop_out_horizontal_strip` — remove the
  selected full-height/full-width band and splice the remaining pieces back together, closing the
  gap). Confirmed directly from the source's own enum doc comments on `CropContainer.CropModes`,
  not inferred from the draw/resize code.
- **Drag-to-create respects each mode's own axis constraint** — `CropContainer.HandleMouseDown`'s
  override forces the initial corner to `(0, y)` for Horizontal / `(x, 0)` for Vertical, and
  `HandleMouseMove` forces the perpendicular axis to the full image extent every frame
  (`Left=0,Width=image.Width` / `Top=0,Height=image.Height`) — ported as
  `_crop_selection_from_drag`, which anchors the relevant axis at the drag's own origin and lets
  `Rect.from_points` normalize the rest, reproducing "a full-height/full-width band whose anchored
  edge stays put while the other follows the mouse" exactly.
- **Resize handles match the real adorner sets** — 4 corners for Default
  (`CreateDefaultAdorners`), 2 edge handles for Vertical/Horizontal
  (`CreateLeftRightAdorners`/`CreateTopBottomAdorners`) — only the axis that mode's own drag
  actually varies gets a handle. `_crop_handle_at`/`_resize_crop_rect` are small dedicated
  duplicates of `core/tools.py`'s own `handle_at`/`_resized_rect` idea rather than exporting a
  private cross-module helper for one caller — Crop's selection is a bare `Rect`, not a `Shape`,
  so the existing shape-oriented functions don't apply directly anyway.
- **Confirm reuses the existing whole-image-effect machinery** (`_apply_background_effect`, the
  same helper Rotate/Border/Resize/Shrink Canvas already use) rather than new undo-plumbing —
  faithful port of `Surface.ConfirmCrop(true)`/`ApplyCrop`/`ApplyVerticalCrop`/
  `ApplyHorizontalCrop`. The element-repositioning offset for Vertical/Horizontal deliberately
  matches Windows' own single *global* `matrix.Translate` (a uniform shift applied to every
  element regardless of whether it sat left/right of the removed band) rather than a "smarter"
  per-element conditional — confirmed from the source this isn't a simplification on this port's
  part, Windows itself doesn't do the smarter thing either.
- **Confirm/Cancel buttons, not a keyboard shortcut** — real Windows shows `btnConfirm`/`btnCancel`
  in `propertiesToolStrip` for *any* `CONFIRMABLE`-flagged selection (`ImageEditorForm.cs:1399`),
  not a Tool-driven `STYLE_FIELD` the way every other style-panel cell is — so this cell's
  visibility is set directly from `self._crop_selection is not None` in `_refresh_style_panel`
  rather than through the generic `visible_style_fields` loop. Escape also cancels an in-progress
  selection, scoped narrowly to "a crop selection exists" rather than a global Escape-switches-to-
  Select remap (real Windows' own plain-Escape-to-Cursor mapping isn't ported yet — task #92).
  Icon buttons (`emblem-ok-symbolic`/`action-unavailable-symbolic`, the standard freedesktop
  checkmark and "no entry" circle-with-a-slash), not text labels — matching real Windows'
  `btnConfirm`/`btnCancel` appearance, confirmed by the user comparing side-by-side with the real
  app; same icon-name convention `_build_action_toolbar` already uses for Save/Copy/Print, not
  hand-drawn Cairo icons, since these are generic actions rather than tools.
- **Dropdown label stays "Auto", matching Windows** — a "Follow Border" rename was tried and then
  reverted at the user's own call: it didn't reduce the confusion enough to be worth diverging
  from the real Windows label (their words: the underlying feature — silently doing nothing when
  it finds no border, no radio indicator since it's a one-shot trigger, not a mode — "is already
  weird" regardless of what it's called). Purely a label question either way — `_do_auto_crop`'s
  own behavior, and Windows' underlying `CropModes.AutoCrop` semantics it ports, were never in
  question.
- **Switching tools discards an unconfirmed selection** — enforced once, in the `tool` property
  setter itself (the single choke point every tool switch passes through: palette clicks, keyboard
  shortcuts, Crop's own mode-dropdown), matching `InitCropMode`'s own
  `Surface.RemoveCropContainer()` call on every mode/tool change.
- New hand-drawn crop-bracket toolbar icon (`_crop_icon` in `ui/icons.py`) — a first version with
  overlapping brackets read as two nested squares rather than a frame with a gap, caught by
  rendering and zooming in, not guessed; widened the corner spacing to fix.

Verified: `tools.py` unit tests mirroring the existing Highlight/Obfuscate `TestVisibleStyleFields`
coverage for all 3 Crop tools; icon tests (draws-something-visible/uses-given-color/changes-
between-colors, matching every sibling icon). Also live in a real GTK session end-to-end: drag-to-
create and resize-handle-drag for all 3 modes: the overlay's outside-vs-inside tint confirmed via
direct pixel inspection (not just eyeballing a screenshot, since a smooth test gradient's own
natural desaturation toward its center looked deceptively similar to a tint at first glance);
Confirm applying the correct pixel transform and producing the correct new canvas size for all 3
modes, with working undo/redo; Cancel discarding the selection without touching the image; Auto
correctly seeding from `autocrop_rect`'s real border detection; element repositioning verified to
translate an existing shape by the exact expected offset on confirm; switching to a different tool
mid-selection confirmed to clear both the selection and the Confirm/Cancel buttons' visibility.

## Highlight tool mode renames + restricted fill-color picker (task #106, complete 2026-08-10)

Port-local wording/UX decisions, not Windows behavior changes - `core/filters.py`/`core/shapes.py`'s
actual filter logic is byte-for-byte unchanged from task #88, and the underlying `HighlightMode`/
`Tool` enum members keep their original internal names (`TEXT_HIGHLIGHT`, `HIGHLIGHT_TEXT`, etc.) -
only `_HIGHLIGHT_MODE_LABELS`'s *displayed* strings and the fill-color picker's own widget changed:

- **"Text Highlight" → "Highlight"** - dropped "Text" since the filter is a per-channel min-clamp
  against the fill color (`highlight_filter`) with no text-detection involved at all; the old name
  implied a capability that doesn't exist, confirmed while investigating what looked like a bug
  report but turned out to be exactly this naming confusion (task #107, resolved not-a-bug).
- **"Area Highlight" → "Spotlight Focus"; "Grayscale" → "Spotlight Colorize"** - working names for
  the two invert-mode filters (darken/desaturate everywhere *outside* the shape's own bounds,
  leaving the inside untouched - see task #88's own writeup for the mechanism), explicitly flagged
  by the user as not fully satisfying ("not sure that captures what it does... not sure how to put
  that in two words") - kept as the best available two-word names for now, open to revision.
- **Magnification's own field label → "Amount"** - the spinner underneath the Magnification mode
  used to say "Magnification:", redundant with the mode name sitting right above it; renamed to
  match Obfuscate's own Pixelize/Blur amount field, which is already just "Amount".
- **Text Highlight/"Highlight" mode's Fill swatch is now a restricted 5-color picker**
  (`_HIGHLIGHT_FILL_COLORS`, `_build_highlight_fill_button`) instead of the arbitrary Greenshot-
  style palette dialog every other color field in the style panel opens (`_build_color_button`) -
  user's own words: "not looking for weird color tricks. this isn't photoshop." Reported live: a
  dark/low-brightness fill collapses `highlight_filter`'s effect into a flat translucent box instead
  of a highlight (task #107's resolved mechanism) - every offered color (Yellow, Green, Pink,
  Orange, Blue) deliberately keeps at least one RGB channel at full 255, so the filter always
  leaves *something* visibly unclamped underneath, avoiding that failure mode by construction
  rather than by picking "nice-looking" colors and hoping. A small `Gtk.MenuButton` + swatch-and-
  label menu items, not a dialog - no arbitrary-color escape hatch, matching the "not photoshop"
  framing precisely.

Verified live: mode dropdown shows the three renamed labels plus unchanged "Magnification" in the
real Windows declaration order; the Amount field's label confirmed via the actual constructed
widget after switching to Magnification mode; the Fill button's popup confirmed to offer exactly
the 5 named colors and correctly apply Green on click (`self._default_highlight_fill_color`
updated); a real screenshot of the style panel showing "Mode: Highlight" and the yellow Fill
swatch together.

## Preferences dialog: Expert tab audit + close-time save prompt (task #93, complete 2026-08-10)

An audit of the real Settings dialog (`Greenshot/Forms/SettingsForm.cs`/`.Designer.cs`, 7 tabs, traced
via `.Controls.Add()` parent-child relationships) against this port's much smaller Preferences dialog
(`EditorWindow._do_show_settings`). Most tabs (Capture/Output/Destinations/Printer/Plugins) are out of
this round's scope or already covered elsewhere (Printer's settings live in `ui/printing.py`'s own
dialog, task #39); this pass covered the **Language** and **Icon size** items from the General tab, the
**Plugins** tab, and every item in the **Expert** tab (`groupbox_expert`).

**Language** - the real app ships 39 translations (`Greenshot/Languages/language-*.xml`: ar-SY, ca-CA,
cs-CZ, da-DK, de-DE, de-x-franconia, el-GR, en-US, es-ES, et-EE, fa-IR, fi-FI, fr-FR, fr-QC, he-IL,
hu-HU, id-ID, it-IT, ja-JP, kab-DZ, ko-KR, lt-LT, lv-LV, nl-NL, nn-NO, pl-PL, pt-BR, pt-PT, ro-RO,
ru-RU, sk-SK, sl-SI, sr-RS, sv-SE, tr-TR, uk-UA, vi-VN, zh-CN, zh-TW), each a `LanguageKey`-driven
resource file (~304 `<resource>` entries in `language-en-US.xml` alone). This port has zero i18n
infrastructure - every user-facing string is a hardcoded English literal in the Python source, not a
lookup against any resource table. Adding real translation support isn't a Preferences-dialog checkbox;
it's a foundational rework (extract ~300+ literals into a resource/gettext layer, wire every widget
construction site to look them up, then translate and maintain N language files) that touches nearly
every file under `ui/`. Not attempted this round - noted here as a scoping decision, not silently
dropped, in case it's picked up as its own dedicated effort later.

**Icon size** (`DpiCalculator.ScaleWithDpi`, destination-picker listview icons) - a Windows-specific
manual DPI-scaling workaround; GTK scales its own icons natively. No Linux equivalent needed, left out.

**Plugins tab** (`checkbox_pluginenabled` listview, populated dynamically at runtime by
`PluginHelper.Instance.FillListView` from whichever plugin DLLs are actually loaded - not a fixed list).
The real bundled set is six, not four as first assumed: `Greenshot.Plugin.Jira`,
`Greenshot.Plugin.Confluence`, `Greenshot.Plugin.Box`, `Greenshot.Plugin.Dropbox`,
`Greenshot.Plugin.Imgur`, `Greenshot.Plugin.Office`, plus `Greenshot.Plugin.ExternalCommand` (tracked
separately, task #110, since it's generic rather than cloud/Office-specific - see below). Effort/library
research per plugin, not attempted this round, all confirmed via the real plugin source plus a check of
the current Python/Linux library landscape:

- **Box, Dropbox** (`BoxUtils.cs`/`DropboxUtils.cs`) - real OAuth2 (`Greenshot.Base.Core.OAuth`,
  authorization-code flow with a browser popup + redirect capture + token exchange/refresh). Both
  services have official, actively-maintained Python SDKs with OAuth2 built in -
  [`boxsdk`](https://box-python-sdk.readthedocs.io/) and the official
  [`dropbox`](https://github.com/dropbox/dropbox-sdk-python) package - so the SDK/API-call side is a
  solved problem; the actual work is per-service developer-app registration (see below) plus the
  redirect-capture UI. Neither plugin ships working credentials even on Windows - each has only a
  `Greenshot.Plugin.{Box,Dropbox}.Credentials.template` placeholder file in the real repo
  (`ClientId`/`ClientSecret` left as `${...}` tokens) - meaning **every Greenshot build, including the
  official one, requires whoever's building it to register their own OAuth app** with Box/Dropbox first.
  That's a real prerequisite, not an integration-code problem.
- **Imgur** (`ImgurUtils.cs`) - simpler than Box/Dropbox: a plain HTTP POST with a `Client-ID` header,
  not a full OAuth dance (anonymous uploads only need a registered Client ID, no user login). Same
  credentials-template situation - needs a registered Imgur app. The official Python client
  ([`imgurpython`](https://github.com/Imgur/imgurpython)) is deprecated and archived as of 2023; given
  how simple the API actually is, a plain `requests` POST is arguably simpler than pulling in one of the
  unofficial community replacements anyway.
- **Jira, Confluence** (`JiraConnector.cs:118`, `Confluence.cs:96`, `SetBasicAuthentication`) - HTTP
  Basic auth against a self-hosted or cloud instance, no app registration or OAuth needed. Less auth
  friction than Box/Dropbox/Imgur, but more API-surface work: the real plugins pull in typed REST
  clients for each service's own object model (issues/filters for Jira, pages/spaces for Confluence) -
  there's no single drop-in Python library for either that matches Greenshot's specific usage, so this
  would mean hand-rolling a small REST client against each API directly (`requests` + each service's
  documented REST endpoints), not just wiring up an existing SDK.
- **Office** (`OfficeInterop`, Word/Excel/PowerPoint destinations) - genuinely Windows-only as first
  assessed: this is COM automation of installed Office applications, with no Linux equivalent. However,
  LibreOffice/OpenOffice do have their own analogous automation surface - the
  [UNO API](https://mobiarch.wordpress.com/2023/03/05/using-the-libreoffice-python-api/) (Universal
  Network Objects), reachable from Python either in-process (LibreOffice's bundled Python) or by
  connecting to a headless `soffice` instance over a socket
  (`--accept=socket,host=localhost,port=...;urp;StarOffice.ServiceManager`). Inserting an image into a
  Writer document is a documented, working pattern
  (`com.sun.star.drawing.GraphicObjectShape`, `GraphicURL` set via `uno.systemPathToFileUrl()`) - so a
  "send to LibreOffice Writer" destination is technically buildable, but it's not a port of
  `OfficeInterop` (different API entirely, would need to be designed from scratch against UNO) and
  depends on LibreOffice being installed, running headless or launched fresh, and the `python3-uno`
  bridge being available - a real but separate feature, not attempted this round.

None of the six are small - each is its own multi-day feature, and three (Box/Dropbox/Imgur) need
developer-account credentials registered before there's anything to test against.

**Decided against, not just deferred** (2026-08-10): traced how the real Windows binary actually gets
working Box/Dropbox/Imgur credentials - `Directory.Build.targets`' `ProcessTemplates` target token-
replaces each `*.Credentials.template` file at build time, and `.github/workflows/release.yml` supplies
those tokens from GitHub Actions secrets (`secrets.Box13_ClientId` etc.) - meaning the *project*
registered one production OAuth app per service and bakes those shared credentials into every copy of
the official binary it distributes; every installed copy of Greenshot authenticates as the same app.
Explicitly rejected as a direction for this port: distributing a single shared OAuth Client
Secret inside an open-source binary that anyone can decompile/extract is a real credential-exposure
concern, not a hypothetical one - was going to require *this port's* maintainer to register and then be
responsible for apps with three external services just to ship it. Task (formerly #112) deleted rather
than left open; the six-plugin effort research above stays as a record of what was actually looked into
and why it isn't happening, in case the question comes up again.

**Expert tab** (`groupbox_expert`, gated behind `checkbox_enableexpert` - see below) - covered item by
item:

- **Reuse Editor** (`IEditorConfiguration.ReuseEditor`, `EditorDestination.cs:96`) - when a new capture
  is about to open an editor, if enabled *and* an already-open editor exists *and* that editor has no
  unsaved changes, the capture reuses that editor's surface (replaces its image/shapes) instead of
  opening a second editor window. Concretely: capture a region, annotate it, then capture *again*
  without closing the first editor - with Reuse Editor on, the second capture replaces the content of
  the window you already have open instead of spawning a new one, so repeated quick captures don't pile
  up a stack of editor windows. Confirmed portable (nothing Windows-specific in the logic), but not
  built this round - left as an open decision, not yet implemented, pending confirmation it's wanted.
- **Minimize memory footprint** (`checkbox_minimizememoryfootprint`) - grep-confirmed no
  `ICoreConfiguration` property and no code path anywhere in the real Windows app reads a setting by
  this name outside the Settings form's own enable/disable UI logic. Genuinely decorative in real
  Greenshot itself, not a gap in this port. Left out.
- **Check for unstable updates** (`ICoreConfiguration.cs:287-289`, `CheckForUnstable`, default `False`)
  - a stub: `settings.get_check_unstable_updates`/`set_check_unstable_updates`, a checkbox in the new
  Expert section, but no update-checking system exists in this port at all yet (task #103), so the flag
  currently has nowhere to plug in. Ported now, documented as a no-op via the checkbox's own tooltip,
  so #103's eventual update checker only needs to read an existing setting rather than also inventing
  where it lives.
- **Suppress the save dialog when closing the editor**
  (`IEditorConfiguration.SuppressSaveDialogAtClose`, `IEditorConfiguration.cs:83-85`, default `False`) -
  implemented for real, both the setting (`settings.get_suppress_save_dialog_at_close`/
  `set_suppress_save_dialog_at_close`) and the behavior it gates. See "Close-time save prompt" below.
- **Counter** (`OutputFileIncrementingNumber`, `ICoreConfiguration.cs:163-165`, default `1`, "increased
  automatically after each save") - implemented as `settings.get_filename_counter`/
  `set_filename_counter` (peek) and `consume_filename_counter` (peek-then-increment-and-persist).
  Windows' own version is an opt-in `${NUM}` token in an arbitrary, user-editable filename pattern
  (`OutputFileFilenamePattern`); this port has no such pattern engine (`settings.quick_save_filename`
  is a fixed timestamp format, by design - see its own docstring), so the counter is always appended
  here as a zero-padded `(NNN)` suffix rather than an opt-in placeholder:
  `"2026-08-10 14_23_05 (007).png"`. Wired into both of `ui/destination_picker.py`'s save paths - the
  silent "Save" destination consumes (and advances) the counter for the file it actually writes; "Save
  As..." only *peeks* the counter for its suggested default filename, and only consumes/advances it if
  the user actually completes the save (so a cancelled Save As doesn't burn a counter value).
- **Printer footer pattern** (`OutputPrintFooterPattern`, `ICoreConfiguration.cs:206-209`, default
  `${capturetime:d"D"} ${capturetime:d"T"} - ${title}`) - implemented as `settings.get_footer_pattern`/
  `set_footer_pattern`. Windows resolves its own `${token}` template engine against a `${title}` this
  port has no equivalent for (region/full-screen captures have no single associated window title - see
  `quick_save_filename`'s own docstring for the same limitation); the setting here is a plain Python
  `strftime` format string instead, editable via a new Expert-section text field. Wired into
  `ui/printing.py`'s `_footer_text`, replacing what used to be a hardcoded `"%B %d, %Y %I:%M %p"` -
  the setting's own default is that exact same string, so a fresh install's printed footer is
  unchanged from before this setting existed.
- **Auto reduce colors** (`OutputFileAutoReduceColors`, `ICoreConfiguration.cs:139-141`, default
  `False`) - traced the real save-path logic (`ImageIO.cs:205-243`, not just the config declaration):
  on save, for opaque images only (anything with alpha is skipped outright), it counts the image's
  actual distinct colors via a quantizer and, only if that count is already under 256, re-encodes as an
  indexed/palette image instead of full RGB - a free file-size win with no visible quality loss, never a
  forced reduction. Genuinely buildable (Pillow's `Image.quantize()` could drive it, since GdkPixbuf has
  no quantizer of its own), but left out by explicit decision - a dedicated paint/image tool is a better
  place for deliberate color reduction than a silent screenshot-save side effect.
- **Thumbnail preview** (`checkbox_thumbnailpreview`, tray-icon-hover thumbnail) - tray-specific, and a
  stretch given this port's already-documented Wayland tray limitations (see "Tray icon under Wayland"
  above). Left out.
- **Optimize for RDP** (`AnimatingForm.cs:50`, `IsTerminalServerSession`) - confirmed genuinely
  RDP-session-specific via source; this port has no UI animations that would need it either way. Left
  out.
- **Clipboard formats** (`ClipboardHelper.cs:963-1122`, `ICoreConfiguration.ClipboardFormats`) -
  controls which Win32 clipboard formats get written *simultaneously* on copy, tied to Windows' own
  multi-format-at-once `SetClipboardData` model; doesn't map onto X11/Wayland's on-demand target
  negotiation, which this port's clipboard backend already handles correctly for GTK's own model. Left
  out (confirmed, not newly revisited this round).

**"I know what I am doing!" master toggle** (`checkbox_enableexpert`) - ported as a plain
`Gtk.CheckButton` gating every Expert-section widget's `set_sensitive` (`_build_expert_settings_frame`,
`EditorWindow._do_show_settings`), matching `ExpertSettingsEnableState`/`Checkbox_enableexpert_
CheckedChanged` (`SettingsForm.cs:844-869`) exactly. Confirmed via the real source that this checkbox
has no `PropertyName` binding of its own in `SettingsForm.Designer.cs` at all - it's session-only UI
state even on the real form, unchecked again every time the dialog reopens, not a persisted setting -
so it isn't written to `settings.py` here either.

### Close-time save prompt (`_on_delete_event`)

Faithful port of `ImageEditorFormFormClosing` (`ImageEditorForm.cs:1004-1033`): closing an editor
(window-manager close button or File → Close, both arrive as the same GTK `delete-event` - `Gtk.Window.
close()` synthesizes one) with unsaved changes and "Suppress the save dialog when closing the editor"
off shows a Yes/No/Cancel prompt before allowing the close.

- **Dirty tracking** (`EditorWindow.is_modified`) - a port of `Surface.Modified` (`ISurface.cs:193`).
  Real Greenshot sets `Modified` true on *any* drawable-list change, including via undo/redo restoring
  a previous state (`DrawableContainerList.cs:176` etc. fire regardless of whether the caller is a
  fresh edit or a memento's `Restore()`) - it's an activity flag, not a true state diff, so undoing back
  to the original content still reads as modified. Ported the same way: `core/history.py`'s
  `UndoRedoStack` gained a monotonic `generation` counter bumped by every `push`/`undo`/`redo` (merged
  pushes included, since `DrawableContainerList.cs` doesn't distinguish those either);
  `EditorWindow.is_modified` compares the current generation against `self._saved_generation`, updated
  only by a completed save. Chosen over hand-setting a dirty flag at each of `_do_save`'s ~20 existing
  `undo_redo.push(...)` call sites, all of which stay untouched.
- **The prompt** - `Gtk.MessageDialog(message_type=QUESTION, text="Do you want to save the screenshot?")`
  with `set_title("Save image?")`, Yes/No/Cancel buttons - `QUESTION` message type renders GTK's own
  question-mark icon to the left, matching the requested layout without a custom icon. Exact strings
  from `LangKey.editor_close_on_save`/`editor_close_on_save_title`
  (`language-en-US.xml`: "Do you want to save the screenshot?" / "Save image?"). "Yes" calls the
  existing `_do_save` (now returns whether a save actually completed, mirroring
  `ImageEditorForm.cs:1024-1028`'s own `if (_surface.Modified)` re-check after `BtnSaveClick`) and
  blocks the close if the save dialog itself was cancelled; "No" allows the close unsaved; "Cancel" (or
  closing the prompt itself) blocks the close. Windows drops the Cancel option specifically when the
  *application* is shutting down (`CloseReason.ApplicationExitCall`/`WindowsShutDown`/
  `TaskManagerClosing`) - this port has no equivalent distinction (every close of this window arrives
  as the same `delete-event`), so Cancel is always offered, matching how Windows itself handles every
  other single-window close.

Verified live: a scripted `EditorWindow` exercising `is_modified` through change → save → change →
undo cycles (undo confirmed to re-dirty a saved editor, matching `Surface.Modified`'s own behavior);
`_on_delete_event`'s six branches (not modified, suppressed, No, Cancel, Yes-with-cancelled-save,
Yes-with-successful-save) driven directly with `Gtk.MessageDialog.run` monkeypatched to avoid blocking
the verification script on a real modal loop; the Expert section's gating (checkbox unchecked → every
other Expert widget insensitive → checked → all sensitive → unchecked again → insensitive again) and
the Counter/Footer pattern fields' round-trip into `settings.py`, all driven directly against the
actual constructed widgets; a real screenshot of the open Preferences dialog with Expert Settings
expanded, confirming the full layout renders as intended.

## ExternalCommand-style destinations (task #110, complete 2026-08-10)

Named, persistently-stored shell commands, each becoming its own destination-picker entry that runs
against the just-captured screenshot's exported file path - the one Plugins-tab item from task #93's
audit that isn't cloud/Office-specific (see the Plugins tab research above, and task #112 for the rest).

Faithful port of the real plugin's structure, confirmed via source (`Greenshot.Plugin.ExternalCommand`):
`ExternalCommandPlugin.cs:69-75`'s `Destinations()` yields one `ExternalCommandDestination` per
configured name, `IExternalCommandConfiguration.cs:35-67` confirms `Commands` is a genuine
`List<string>` with parallel `Commandline`/`Argument`/`RunInbackground` maps (multiple independently-
stored commands, never a one-shot single command), and `SettingsForm.cs`/`SettingsFormDetail.cs`
confirm the real management UI is exactly a list dialog (Add/Edit/Delete) plus a detail editor
(Name/Commandline+Browse/Arguments/OutputFormat) - reachable via the Plugins tab's "Configure" button
(`ExternalCommandPlugin.cs:225-229`).

**Ported (`settings.py`'s `ExternalCommand` dataclass, `ui/external_commands.py`)**:
- `name`, `commandline`, `argument` (a `str.format` template, default `"{0}"`), `run_in_background`
  (default `True`, matching `ExternalCommandConfigurationImpl`'s own fallback for a misconfigured
  entry) - one dataclass per command in a JSON list, rather than four parallel dicts keyed by name
  (Python has no ini-section auto-binding to preserve).
- `build_command_argv` - the actual execution mechanism, and the one place this port deliberately
  diverges from the *mechanism* Windows uses while preserving the *safety property* it's for. Windows'
  own `ExternalCommandDestination.FormatArguments` (`ExternalCommandDestination.cs:288-311`)
  substitutes the file path into a single argument *string*, then denies a list of shell metacharacters
  (`&|;$\`()<>\n\r"'`) - necessary there because `Process.Start`'s `Arguments` property is itself
  re-tokenized by a shell-like parser even with `UseShellExecute=false`. `subprocess.Popen`'s
  list-of-args form has no such parser - each argv item goes straight to `execve()`, never
  reinterpreted - so `build_command_argv` splits the argument template into tokens *before*
  substitution and formats each token independently: the exported file path can never be read back out
  as shell syntax, no matter what characters it contains, with no denylist needed at all. Verified via
  a dedicated test asserting a path containing shell metacharacters (`` $(rm -rf ~); echo pwned.png ``)
  stays a single, inert argv item.
- `run_external_command` - exports the screenshot to a temp file (`ui/file_export.py`'s
  `orcshot_cache_dir`, a shared home extracted from what was previously
  `EditorWindow._external_editor_cache_dir`'s own private logic - same Flatpak-`/tmp`-isolation
  reasoning applies to any external process, not just the "Open in External Editor" button), builds the
  argv, then runs it - on a background thread when `run_in_background` (so the app doesn't freeze), or
  blocking the caller when not (the same UX tradeoff Windows itself has - `WaitForExit()` freezes its
  own UI thread in that mode too, not a regression introduced here). A 5-minute timeout guards against a
  hung process leaking a background thread forever - Windows has no such cap (`WaitForExit()` waits
  indefinitely), a small, deliberate hardening addition rather than a strict mechanical port.
- The management UI (`show_manage_external_commands_dialog` + `_show_command_detail_dialog`) - a list
  dialog with Add/Edit/Delete plus a detail editor (Name/Command+Browse/Arguments/Run in background),
  reached from a new "External Commands: Manage..." row in `EditorWindow._do_show_settings` (this port
  has no separate Plugins tab for Windows' own "Configure" button to live behind). Validation mirrors
  `SettingsFormDetail.OkButtonState` (`SettingsFormDetail.cs:134-201`): name required and unique,
  command required and resolvable (`shutil.which` or an existing file), arguments template parseable.
- Destination-picker wiring (`ui/destination_picker.py`'s `_all_destinations`): the five built-in
  destinations plus one entry per configured `ExternalCommand`, computed fresh on every call (not
  cached at import time) so an added/edited/removed command shows up immediately, matching Windows' own
  `Destinations()` re-enumerating `ExternalCommandConfig.Commands` each time. Appended after the
  built-ins rather than interleaved into Windows' own priority ordering - these are user-added, so they
  read naturally as extras tacked onto the end.

**Deliberately not ported**:
- Per-command `OutputFormat` - this port's save path is PNG-only (`ui/file_export.py`), so there's no
  per-command format to choose.
- URI-detection-in-stdout-then-clipboard (`ExternalCommandDestination.cs:149-164`,
  `OutputToClipboard`/`UriToClipboard`) - a genuinely separate sub-feature (useful for a command that
  uploads somewhere and prints a URL), not core to "run a command with the screenshot's path". Left for
  later if wanted.
- The Windows "runas" elevation retry (`CallExternalCommand`'s `Win32Exception` fallback) - a
  UAC-specific concept with no Linux equivalent.
- **The Wayland Shell-native destination picker does not show external commands.** Under X11 (and the
  Wayland region-select fallback), `show_destination_picker`'s `Gtk.Menu` is built fresh from
  `_all_destinations()` every time, so configured commands appear immediately. Under GNOME Shell-native
  Wayland capture, the picker is rendered by the bundled Shell extension's own JavaScript
  (`resources/gnome-shell-extensions/orcshot-clipboard@orcshot.org/extension.js:206-211`,
  a hardcoded `DESTINATIONS` array), which has no access to this port's Python-side JSON settings and
  so can't dynamically list configured commands - `dispatch_destination` *would* run one correctly if
  asked, but the Shell-native menu never offers it as a choice in the first place. A real gap, not
  silently dropped: fixing it means either the extension reading the same config file directly via
  GJS's file APIs, or a D-Bus bridge - out of scope for tonight, tracked as its own follow-up.

Verified live: `run_external_command` exercised end-to-end (not mocked) against a real shell script that
records the argv it received to a marker file, for both `run_in_background=True` and `False` - confirmed
the recorded path is a real, freshly-exported PNG; `_all_destinations()`/`dispatch_destination` confirmed
to include and correctly run a configured command, and to no-op on an unrecognized id; both dialogs
(list and detail) screenshotted live, confirming layout, validation-driven OK-button sensitivity, and
the "Name is required" error text.

## Task backlog from a side-by-side comparison with the real Windows editor (2026-08-09)

A large batch of gaps/fixes (tasks #87-101) came from the user directly comparing this port's editor
against a real running Windows Greenshot instance, rather than this port's own read-through-the-source
approach used for everything before this. Surfaced several real, previously-unknown-to-this-port
issues no amount of source-reading alone had caught, and one real correction to something this project's
own REQUIREMENTS.md previously claimed:

- **The real Windows keyboard shortcut scheme uses letter mnemonics, not numbers** (`ImageEditorFormKeyDown`,
  `ImageEditorForm.cs`) - Escape=Select, R/E/L/F/A/T/S/I/H/O/C/M/Z for
  Rectangle/Ellipse/Line/Freehand/Arrow/Text/SpeechBubble/StepLabel/Highlight/Obfuscate/Crop/Emoji/Resize,
  plus Ctrl+./Ctrl+, for rotate and Ctrl+Q/B/T/I/G for the individual Effects. This directly corrects an
  earlier claim in this same file (see the now-superseded "Editor keyboard shortcuts" section above) that
  Select "has no clear Windows precedent" for a shortcut - that was based on checking only the Designer.cs
  `ShortcutKeys` properties (all empty), not the real `KeyDown` handler where Windows actually implements
  this. Task #92 tracks replacing this port's own invented `` ` ``+1-9+0 scheme with the real one.
- **Effects is a toolbar dropdown in Windows, not a popup dialog** - confirmed from the real
  `toolStripSplitButton1.DropDownItems` list, contradicting this port's current modal-dialog
  implementation (task #89).
- **Crop and Highlight tools were never built** (tasks #91, #88).
- **Rotate CW/CCW and Resize belong in the toolbar, not the Image menu** (task #90).
- An unresolved discrepancy surfaced mid-conversation: the real Windows *source* lists 7 Effects dropdown
  items, but a real screenshot of the actual running Windows app the user provided shows only 5 - missing
  Remove Transparency and the OCR-based "Obfuscate Text" item. Not yet explained (version mismatch?
  conditionally hidden at runtime?) - tracked as its own task (#101) rather than guessed at, since it
  affects the real scope of both #89 and #100.
- Windows 10's own OCR integration (auto-obfuscate detected text, confusingly labeled "Obfuscate Text"
  inside the Effects dropdown) and Share integration (native DataTransferManager share-sheet, no Linux
  equivalent) were investigated and split into two tasks with very different shapes: OCR is confirmed to
  build (task #100, needs a Linux-side OCR engine like Tesseract swapped in for `IOcrProvider`), Share is
  deliberately kept as a discussion-only task (task #94) since there's no universal Linux desktop
  share-sheet standard to port to.

Full task list and citations live in the task tracker (tasks #87-101); this section is a pointer to how
they were found, not a duplicate of each one's own description.

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

## Branding: Orcshot rebrand (task #105, complete 2026-08-11)

Task #105 (rebrand away from the "Greenshot" name/logo - GPLv3 covers the code, not the trademark)
picked a name - **Orcshot** - and a new logo, then renamed the codebase to match: the Python package
(`src/greenshot_linux` → `src/orcshot`, every internal import), the distributed package/executable
name (`greenshot-linux` → `orcshot` in `pyproject.toml`, Debian `control`/`.desktop`/`.install`/
`.postinst`), the config/cache directories (`~/.config/greenshot-linux` → `~/.config/orcshot`,
`~/.cache/greenshot-linux` → `~/.cache/orcshot` - a fresh-start, not a migrated one; no attempt was
made to carry old settings forward), the bundled GNOME Shell extension (directory, D-Bus interface/
object-path names, UUID domain `@greenshotlinux.org` → `@orcshot.org`), the `Gio.Application` ID
(`org.greenshotlinux.GreenshotLinux` → `org.orcshot.Orcshot`), the internal `GreenshotApplication`
class → `OrcshotApplication`, and every user-visible string (window titles, About dialog, tray
tooltip, first-run setup, autostart `.desktop` entry, the four hotkey binding display names, README/
`REQUIREMENTS.md` titles). "Linux Mint" branding was dropped throughout too (per explicit request -
the project already targets Ubuntu/GNOME broadly, not just Mint/Cinnamon; see tasks #37/#38/#50/#102),
and every rewritten description now explicitly states this port is "not affiliated with or endorsed
by the Greenshot project" - a deliberate disambiguation, not just a name swap.

**Explicitly not done, by deliberate choice, not oversight:**
- **git history** - discussed directly with the user, who agreed after hearing the tradeoff: rewriting
  70+ published commits on a shared GitHub remote is destructive (force-push breaks every existing
  clone/fork) and doesn't reduce the actual legal exposure, which comes from current live branding, not
  historical commit messages accurately describing "this started as a port of Greenshot" (nominative
  fair use). Left alone.
- **GitHub org/repo rename** (`github.com/greenshotlinux/greenshotlinux`) - a real external-service
  action distinct from local file edits, not bundled into this pass. Tracked separately.
- Citations of the real upstream Windows Greenshot project (`Greenshot.Editor/Drawing/CropContainer.cs`
  -style file paths, "matching Windows Greenshot's own tray default," etc.) were deliberately left
  alone throughout - those are accurate references to the software being ported, not this port's own
  branding, and renaming them would have broken the faithful-port citation trail this whole file
  depends on.

Verified live: full test suite (905 passed) after the rename; the app launched fresh via the new
`orcshot` command (not the old `greenshot-linux` one, which was removed from the venv) with no import
errors; `EditorWindow`'s real title read back as "Orcshot image editor" and `resources.LOGO_PATH`
resolved to the new `orcshot.png`, both checked programmatically, not just eyeballed.

The logo itself:

**The idea**: reuse the real Greenshot logo's own dot-matrix rendering *technique* (a grid of green
circles on a flat grey square) but light a different picture into it - an orc face - rather than the
"G". Style/technique isn't the protectable part of a trademark; the specific mark is, so redrawing an
unrelated image with the same rendering technique is a meaningfully different, safer position than
reusing the G shape itself.

**Reverse-engineering the real grid** - the logo isn't freehand-placed dots; it's a genuine rotated
square lattice. Confirmed by blob-detecting all green circles in the real
`orcshot.png` (155×126px) and clustering the pairwise nearest-neighbor vectors between their
centers: two perpendicular basis vectors, each ~17.2px long, at ~20.9° off horizontal (the user's own
eyeball guess of "maybe 30°, rotated right" was correct in kind, off by about 9° in practice) -
confirmed by reconstructing the real G from this model and confirming it visually matches the source
file. Every dot in both the reconstruction and the final logo is a 7px-radius circle (matching the
real logo's own dot size measured the same way), placed at
`anchor + col * 17.2075 * (cos21°, sin21°) + row * 17.2075 * (-sin21°, cos21°)`.

**The final design** - direflail hand-specified the exact result as a 9-column × 7-row ASCII grid
(`B`=blank, `G`=green, `R`=red, `W`=white):

```
BBBGGGBBB
GBGGGGGBG
BGGRGRGGB
BGGGGGGGB
BGWGGGWGB
BGGWGWGGB
BBGGGGGBB
```

Green = the same rendering as the original G. Red = two eyes. White = four tusk dots (an orc's lower
jaw/tusks), positioned in the two rows below the eyes. The grid is anchored flush against the canvas's
top-left corner (`anchor = (36.77, 0)`) per direflail's explicit instruction ("top and left should
align with the greenshot logo") - since the grid's own rotated bounding box (~165×145px) is larger
than the 155×126 canvas, the overflow is pushed entirely to the right/bottom edges, where several real
dots are genuinely clipped by the canvas boundary - the same thing the original G's own dots already
do (confirmed during the earlier grid-reconstruction work: a few real G dots are partially cut off at
the image edge too), not a new technique introduced for Orcshot.

**A finding worth keeping**: the two dots at row 2 (grid columns 0 and 8 - the "ears," each 4 columns
out from the row-1 cluster's center) were flagged by direflail as visually not lining up with the rest
of the pattern. Verified with a debug render overlaying row/column lattice lines through every dot
center - both ear dots sit exactly on the same lattice as everything else, confirmed by direflail's
own independent measurement too. The mismatch is perceptual, not geometric: a *rotated* square lattice doesn't preserve left-right
visual symmetry for shapes that are symmetric in row/column-index terms (moving N columns in the
`+col` direction and N columns in the `-col` direction cover different net pixel distances once
combined with the same row offset, since the basis vectors aren't axis-aligned), and an isolated dot
with no adjacent neighbor to visually connect it to the main cluster reads as "floating" even when
it's mathematically exactly on-grid. Decided to leave both ear dots exactly where the grid places
them.

**Process artifacts** (grid measurement, reconstruction validation, and every rejected design - a
full orc *face* attempt across six iterations, none of which read as recognizable at this dot
density/grid resolution, before landing on the O-then-blob-then-final-grid approach) live in
session scratch files, not the repo - not reproduced here since they were superseded, but the lesson
that mattered is: **a sparse ring or face outline doesn't carry enough visual information at this
dot count/spacing to read as representational art** - a dense, filled cluster with 2-3 colors does.

## Menu bar rebuild: File/Edit/Object/Zoom/Help (task #95, part 1 - complete 2026-08-13)

Grounded in the real menu structure (`ImageEditorForm.Designer.cs:589-595`'s `menuStrip1.Items`), not the
initial assumption the task was filed under. Real Windows has **File/Edit/Object/Plugin[hidden unless
plugins load]/Zoom/Help** — no top-level "Image" menu exists there at all (this port's own "Image" menu
was down to one item, "Clear", after tasks #89/#90 already moved effects/rotate/resize to the toolbar),
and **Zoom genuinely is a top-level menu** — `zoomMainMenuItem` sits directly in `menuStrip1.Items`
alongside File/Edit/Object/Help (line 594), sharing the exact same `zoomMenuStrip` the status-bar
`zoomStatusDropDownBtn` also opens (lines 1735, 1891) — two real entry points to one menu, not one. This
port's own prior comment claiming "Windows has no top-level zoom menu either" (removed) was simply wrong.

**Menu bar icons added throughout**, reusing the toolbar's existing symbolic icon names
(`document-save-symbolic`, `edit-cut-symbolic`, etc. - `_build_action_toolbar` already established these)
plus the hand-drawn tool icons (`tool_icon_image`) for Object's shape items - matching real Windows, where
menu and toolbar share one bitmap per action (e.g. `copyToolStripMenuItem.Image` is literally the same
resource as its toolbar button's).

**File**: Save (new - see below), Save As... (renamed from the old "Save...", same dialog-driven
behavior), Copy to Clipboard, Print..., Insert Image/SVG... (this port's own additions, no Windows
File-menu equivalent - kept anyway, File remains the most sensible home), Screenshot Save Location...
(also our own addition, kept in File per direflail's call), Close.

**Save vs. Save As... split (new)**: real Windows distinguishes a silent "Save" (writes immediately to a
preferred location/filename, no dialog) from "Save As..." (always dialog-driven). This port's existing
"Save..." was actually always dialog-driven - closer to Save As. `_do_quick_save` is the new silent Save,
reusing the exact mechanism `ui/destination_picker.py`'s own "Save" destination already used
(`quick_save_filename`/`get_output_directory`/`consume_filename_counter`) rather than a second
implementation. Still writes a fixed `.png` with the existing hardcoded timestamp pattern - real
configurable "preferred file settings" (filename pattern, primary format) are Output-tab work, part 2 of
this task, not done yet.

**Edit**: Undo, Redo, Cut/Copy/Paste (a real fix along the way - this menu's old "Copy" wrongly called the
whole-image `_do_copy`; real Windows' `cutToolStripMenuItem`/`copyToolStripMenuItem`/`pasteToolStripMenuItem`
are grouped with Undo/Redo and act on the *selected shape*, matching `_do_cut_shape`/`_do_copy_shape`/
`_do_paste_shape` instead - the whole-image copy stays in File as "Copy to Clipboard", always-available
regardless of selection, matching Windows' own split), Duplicate (new - `_do_duplicate`, same offset-copy-
and-select pattern as Paste, sourced from the current selection instead of the shape clipboard),
Preferences... (menu-ifies the existing toolbar-only `_do_show_settings`), Set Up Hotkeys & Autostart...
(temporary placement next to Preferences - belongs inside a rebuilt Preferences>General per real Windows'
`groupbox_hotkeys`, not done yet, part 2), Insert Window... (ours, kept over Windows' per direflail - "I
like our insert window better than theirs"), Clear All (moved here from the now-removed Image menu).

**Object**: the 8 add-shape items (Rectangle/Ellipse/Line/Arrow/Freehand/Text/Speech Bubble/Counter)
mirroring the tool palette - each wired via `self._tool_buttons[tool].set_active(True)` (not
`self.tool = ...` directly) so the palette's own radio-button pressed state stays in sync, the same
pattern `_on_key_press`'s letter shortcuts already use. Delete. Arrange submenu (Bring to Top/Up One
Level/Down One Level/Send to Bottom) - the "one level" pair is new UI (`_do_bring_forward`/
`_do_send_backward`), but `Layer.bring_forward`/`send_backward` already existed fully unit-tested in
`core/drawing.py` (`test_drawing.py`), just never wired to anything - real Windows'
`upOneLevelToolStripMenuItem`/`downOneLevelToolStripMenuItem` confirmed this was a real gap, not a
deliberate cut.

**Not yet in Object**: Select All (needs real multi-select - this port's selection model is strictly
single-shape throughout `editor_window.py`, confirmed via grep, no rubber-band/marquee select exists
despite Tool.SELECT already being real from task #43; split into its own task, #125, rather than treated
as a menu-wiring afterthought) and Save/Load Objects (needs the `.orcshot` file format, task #123, which
doesn't exist yet).

**Zoom**: new top-level menu, `_populate_zoom_menu` shared with the status bar's dropdown so the two can't
drift apart (mirrors real Windows' own `zoomMainMenuItem`/`zoomStatusDropDownBtn` split). Icons only on
Zoom In/Out, matching Windows - the percentage/Best Fit/Actual Size entries have no `.Image` set there
either.

**Help**: Online Help (new - opens `github.com/artificialorctelligence/orcshot` in a browser for now; real help-page
content, probably a GitHub wiki page, is content-writing not code, tracked as a follow-up rather than
blocking this) and About Orcshot.

**Deliberately deferred to task #95 part 2** (Preferences dialog rebuild - 7 tabs matching
`SettingsForm.Designer.cs`'s General/Capture/Output/Destinations/Printer/Plugins[dropped]/Expert, icon-
size live resize, hotkey config relocation) and to their own split-off tasks (#123 `.orcshot` format, #124
`.greenshot` NRBF export - confirmed via reading `GreenshotFileFormatHandler.cs`/`Surface.cs`/
`BinaryFormatterHelper.cs` that real Windows' `.greenshot` format is PNG + a raw .NET BinaryFormatter/NRBF
blob gated by an explicit type whitelist, genuinely buildable but scoped separately from `.orcshot` itself;
#125 real multi-select). Live-verified (structural menu-tree walk + functional checks for tool-button
sync/Duplicate/Arrange/quick-Save, synthetic solid-color test image, no real desktop content per this
project's own verification discipline) and full suite green (926 passed, 3 skipped) before committing.

## Preferences dialog rebuild, part 1 - General tab (task #95 part 2, complete 2026-08-13)

Real Windows' Preferences dialog is **General/Capture/Output/Destinations/Printer/Plugins/Expert** - 7
tabs, confirmed via the exact `tabcontrol.Controls.Add`/`tab_x.Controls.Add` calls in
`SettingsForm.Designer.cs` (not guessed from control declaration order, which doesn't match tab
membership). Plugins is dropped by direflail's own call - real Windows' tab lists loaded plugin DLLs with
Configure buttons; this port has exactly one "plugin"-shaped thing (ExternalCommand, task #110), better
served by Destinations tab's own Configure-button equivalent than a whole tab for one item. Rebuilt as a
`Gtk.Notebook` (was a single flat `Gtk.Dialog` with stacked rows), one tab per real Windows group, built
incrementally with a check-in after each rather than all at once.

**General tab (fully new/real this pass)**: Network and Updates (Use system default proxy - see
`get_use_default_proxy`'s docstring for what "default proxy" means on Linux vs. Windows' WinINet; Check
for updates every N days - inert, task #103 doesn't exist yet, same documented-placeholder treatment as
`get_check_unstable_updates` already established), Hotkeys (a "Configure Hotkeys..." button reusing the
existing `ui/first_run_setup.py` dialog rather than rebuilding Windows' own live-capture `HotkeyControl`
widgets inline - real Windows embeds them directly in `groupbox_hotkeys`, this is a faithful-in-spirit
stand-in), Application Settings (Language - disabled placeholder, only "English" exists until task #109;
Icon size - real, a 16-256-step-16 spinner matching `numericUpdownIconSize`, see below; Launch Orcshot on
startup - real, a direct toggle distinct from the Hotkeys button's wizard-style flow, needed two new
`autostart.py` functions since that module was previously write-only; External Image Editor - kept here,
not a Windows setting at all so no real tab to match against).

**Icon size, made real** (`settings.get_icon_size`/`set_icon_size`, default 24 not Windows' 16 - matches
`ui/icons.py`'s own pre-existing `ICON_SIZE` constant, an unrelated prior sizing choice this setting makes
configurable rather than changes for a fresh install). Applied by bitmap-scaling the rendered pixbuf
(`tool_icon_image`'s new `size` param, `GdkPixbuf.Pixbuf.scale_simple` with `BILINEAR` - smooth vector line
art, unlike `orcshot.png`'s deliberately blocky dot-matrix logo which needed `NEAREST`) rather than
threading a size parameter through every one of `icons.py`'s dozens of hardcoded-coordinate drawing
functions - also how Windows' own `IconSize` actually works (it scales bitmap resources, doesn't redraw
vector art at a new resolution). Applied everywhere `tool_icon_image` is called: the tool palette and the
Object menu's shape items - the latter matches real Windows exactly, whose `menuStrip1.ImageScalingSize`
is literally set to the same `coreConfiguration.IconSize` its toolbar uses
(`ImageEditorForm.Designer.cs:586`), not a separate menu-specific size. The generic theme-icon buttons
(toolbar action buttons, effects/crop/highlight dropdowns) don't respect this setting yet - `icons.py`'s
own module docstring already documents those as a deliberately separate code path from the hand-drawn
icons this setting touches; left as a known, honest gap rather than claimed as done.

**Autostart made read/write** (`autostart.py` gained `is_autostart_enabled`/`remove_autostart_entry` -
previously write-only, only ever called once from the first-run wizard with no way to check current state
or turn it back off). Real file-based, same pattern as `install_autostart_entry` - existence of the
`.desktop` file is the only signal, no separate enabled/disabled flag within it.

**Existing controls moved to their real Windows-matching tabs, unchanged otherwise** (pure reorganization,
confirmed nothing was dropped via a structural live-verify walk of every tab's contents): Capture mouse
cursor → Capture tab (matches `groupbox_capture`'s own `checkbox_capture_mousepointer`). Screenshot Save
Location → Output tab (matches `groupbox_preferredfilesettings`'s storage-location field). External
Commands "Manage..." → Destinations tab (task #110's own faithful-in-spirit stand-in for that tab's
Configure button). The Expert settings frame (`_build_expert_settings_frame`, unchanged) → Expert tab.

**Not yet real, explicit placeholders, not silent gaps**: Printer tab (a labeled placeholder - real printer
*defaults* don't exist, only the existing per-print-job dialog, `ui/printing.py`, backed by the same
`settings.PrintOptions` this tab would eventually default from). Capture tab's Notifications/Play Sound
checkboxes (split into task #126 - no underlying notify/sound feature exists in this port at all to attach
them to; confirmed via grep, and task #73 already established the one sound anyone noticed during Wayland
capture was `xdg-desktop-portal-gnome`'s own incidental feedback, not this app). Output tab's filename
pattern/primary format/quality settings, Destinations tab's full checklist, real printer defaults - all
later passes of this same task.

Edit menu's "Set Up Hotkeys & Autostart..." (added in part 1 as an explicitly-temporary placement) removed
now that General tab's "Configure Hotkeys..." button is its real, permanent home - avoids two menu paths
to the same dialog.

10 new unit tests (`test_settings.py`'s `TestIconSize`/`TestUseDefaultProxy`/
`TestUpdateCheckIntervalDays`, `test_autostart.py`'s `TestIsAutostartEnabled`/`TestRemoveAutostartEntry`).
Live-verified: structural tab-order/content walk (all 6 tabs, confirmed every migrated control still
present) plus functional checks (autostart checkbox really installs/removes the `.desktop` entry, icon
size spinner really persists) against a synthetic solid-color test image and a scratch `XDG_CONFIG_HOME`,
never the real one. Full suite green (936 passed, 3 skipped) before committing.

## Preferences dialog rebuild, part 2 - Output tab (task #95 part 2, complete 2026-08-14)

Real Windows' Output tab is two groupboxes (`groupbox_preferredfilesettings` + `groupbox_qualitysettings`,
`ICoreConfiguration.cs:126-160`) - filename pattern, primary format, copy-path-to-clipboard, storage
location, reduce colors, always-show-quality-dialog, JPEG quality. All real now, backed by one new
`settings.OutputSettings` dataclass (defaults confirmed against the real source: `OutputFileCopyPathToClipboard`
is `true` by default, not the `false` I'd assumed before actually checking; `OutputFileJpegQuality` `80`;
everything else `false`).

**New `core/filename_pattern.py`** - a faithful-in-spirit subset of `FilenameHelper.cs`'s `${TOKEN}`
substitution (`FillPattern`, lines 344-441): `${YYYY}` (4-digit-padded), `${MM}`/`${DD}`/`${hh}`/`${mm}`/`${ss}`
(2-digit-padded), `${NUM}` (6-digit-padded, the existing save counter), `${title}` (filename-safety-
sanitized, defaults to empty - matches `quick_save_filename`'s own long-standing rationale for dropping
`-${title}` from the default pattern: not every capture mode has one). Deliberately excludes Windows'
`${domain}`/`${user}`/`${hostname}`/environment-folder tokens (low value, storage location is already its
own setting) and `${now}`/`${capturetime}` (redundant with the individual date tokens here). 14 unit
tests, pure function, no I/O.

**Save vs. Save As, now both genuinely respect these settings** (part 1 left `_do_quick_save` still
hardcoding `.png`/a fixed pattern - a documented, not-yet-fixed gap at the time):
- `_do_quick_save` (silent Save) now resolves the real filename pattern + primary format, applies
  `jpeg_quality` on save, and copies the saved path to the clipboard when `copy_path_to_clipboard` is on
  (direct `Gtk.Clipboard.set_text`, not routed through `ClipboardBackend` - that Protocol only has
  `set_image`, and plain text doesn't need the X11/Wayland-specific handling image clipboard support
  required, confirmed via `ui/capture/clipboard.py` - no backend change needed).
- `_do_save` (Save As...) gained a real "Save as type" selector (`Gtk.ComboBoxText` as the
  `FileChooserDialog`'s `set_extra_widget`, matching `SaveImageFileDialog.cs`) - png/jpg/bmp/tiff/gif,
  deliberately excluding jxr (WMPhoto, Windows-only), ico (technically save-able via `file_export.py` but a
  poor fit for a screenshot tool's Save As list), and `.orcshot`/`.greenshot` (task #123, doesn't exist
  yet). Picking a format live-updates the suggested filename's extension; the combo's choice wins over
  whatever extension ends up typed, matching how Windows' own type dropdown overrides the visible name.

**Quality dialog added** (`_maybe_show_quality_dialog`, faithful port of `QualityDialog.cs`) - a JPEG
quality slider, shown before *either* save path completes when `always_show_quality_dialog` is on. Off by
default, so most users never see it. Confirmed via source this is genuinely how real Windows behaves too,
even on its own quick-save-style destination (`FileDestination.cs:80-84` gates on the identical
`CoreConfig.OutputFilePromptQuality` flag, format-independent, same as the Save-As path in `ImageIO.cs:422-426`)
- not a design shortcut invented for this port. Adjusting the slider persists the new default `jpeg_quality`
too, matching Windows having exactly one persisted value for it, not a separate "this dialog" vs. "default" pair.

**`file_export.save_image_to_file` gained an optional `jpeg_quality` param** - passed through to
GdkPixbuf's own `savev` quality option, silently ignored for non-JPEG formats (matching GdkPixbuf's own
behavior for an option a format doesn't recognize, not a special case this port added).

**`reduce_colors` is persisted but explicitly not applied to a save** - no palette-quantization step
exists in this port at all; documented the same way `get_check_unstable_updates` already was (real
setting, real gap, not a fake control) rather than either skip the field or fake an implementation.

19 new tests (`test_filename_pattern.py`'s 14, `test_settings.py`'s `TestOutputSettings` (4),
`test_file_export.py`'s JPEG-quality pair). Live-verified: quick-save actually respects a changed
`primary_format` and writes a correctly-patterned filename, clipboard actually receives the saved path as
text, Save As's format combo actually overrides a mismatched typed extension and live-updates the
suggested filename - all against a synthetic solid-color image and a scratch `XDG_CONFIG_HOME`/output
directory, using the `GLib.timeout_add`-driven dialog-interaction pattern for the two nested `dialog.run()`
calls involved (Save As's FileChooserDialog, and the General tab's Preferences dialog). Full suite green
(956 passed, 3 skipped) before committing.

## Preferences dialog rebuild, part 3 - Destinations tab (task #95 part 2, complete 2026-08-14)

Real Windows' Destinations tab is `groupbox_destination`: `checkbox_picker` + `listview_destinations` (a
checked list of every available destination, plugin-provided ones included). `listview_destinations` is
real now: `ui/destination_picker.py`'s `_all_destinations()` (the exact list `show_destination_picker`
already builds its menu from) drives a real `Gtk.TreeView` checklist, toggled against a new
`settings.get_excluded_destinations()`/`set_excluded_destinations()` pair. Faithful to the real field this
ports, `ExcludeDestinations` (`ICoreConfiguration.cs:230-231`, "Comma separated list of destinations which
should be disabled") - an *exclude* list, not an include list, so a destination added later (a future
built-in, or a freshly-created ExternalCommand) is enabled by default rather than silently hidden until
opted in. `checkbox_picker` itself ("always show the picker rather than jumping straight to one preferred
destination") has no equivalent here - every hotkey/tray action already opens the picker unconditionally,
there's no "skip it" mode to toggle in the first place.

**Real bug caught while building this, fixed before it shipped**: `_all_destinations()` already filters out
excluded ids for its normal callers (the actual picker menu, correctly). Populating the checklist itself
from that same filtered call would have made an unchecked/excluded destination vanish from its own settings
UI entirely - no row to re-check, no way back in. Fixed with an `include_excluded=True` parameter on
`_all_destinations()` for exactly this one caller, rather than a second, drifting copy of the destination-
enumeration logic.

**Office destination, added** (direflail's own request - "adding openoffice/libreoffice... would be good").
Real Windows' actual Office destination inserts the image straight into a document via COM automation, a
Windows-only mechanism with no Linux equivalent, so this isn't a port - it's a new addition scoped to the
closest faithful-in-spirit outcome: detect `soffice`/`ooffice`/`openoffice.org` on `PATH` (`shutil.which`,
same detection idiom `_find_external_editor_command` already established) and, if found, offer "LibreOffice
Draw"/"OpenOffice Draw" as a destination that exports to a temp file (`orcshot_cache_dir()`) and launches
`<binary> --draw <path>`. Live-verified against this actual dev machine, which really does have LibreOffice
installed - "LibreOffice Draw" showed up in the real destination list, not just a mocked/assumed path.

**Also fixed, found while reviewing the two save destinations for this pass**: `ui/destination_picker.py`'s
own `_quick_save`/`_save_as` (the hotkey/tray-menu entry points to Save/Save As, as opposed to
`EditorWindow`'s menu-bar versions) had drifted out of sync with part 2's Output-tab work - still hardcoding
`.png` and the old fixed timestamp pattern, since only the editor's own copies were updated at the time.
Both are the same conceptual Windows destination (`FileDestination.cs`) reached from a second entry point,
so this was a real, if narrow, regression risk left dangling rather than new scope - fixed here to use
`settings.OutputSettings` identically to the editor's versions (filename pattern, primary format, JPEG
quality, copy-path-to-clipboard).

5 new unit tests (`test_settings.py`'s `TestExcludedDestinations`). `destination_picker.py` stays
untested at the unit level per its own established convention (live GTK popup-menu glue, no meaningful
headless test) - live-verified instead: the checklist reflects real `_all_destinations()` content including
the live-detected Office entry, unchecking a row immediately removes it from the real picker's own list
while it remains visible (unchecked) in the checklist itself, and the excluded set round-trips through
`settings.json` correctly. Full suite green (959 passed, 3 skipped) before committing.

## Preferences dialog rebuild, part 4 - Printer tab (task #95 part 2, complete 2026-08-14)

Real Windows' Printer tab (`groupBoxColors` + `groupBoxPrintLayout` + `checkbox_alwaysshowprintoptionsdialog`,
`SettingsForm.Designer.cs:815-978`) maps directly onto a dataclass this port already had -
`settings.PrintOptions`, previously only ever read/written by `ui/printing.py`'s per-print-job dialog. This
tab is genuinely the smallest of the four built so far: no new settings, no new core logic, just a second
UI surface over the same persisted state, mirroring the per-job dialog's own field layout
(`_show_print_options_dialog`) but persisting each control immediately on change (matching Output tab's own
live-persist pattern) rather than through an OK/Cancel round trip - these are *defaults*, not a one-shot
decision the way the per-job dialog's fields are.

Confirmed via reading `ui/printing.py`'s own `print_image` that this genuinely takes effect on the next
real print with zero changes needed there: it already seeds from `get_print_options()` and already gates
the per-job dialog on `options.prompt_options` - exactly the field this tab's own "Show print options
dialog every time an image is printed" checkbox controls. No wiring gap to close.

No new tests (reuses `PrintOptions`' existing settings.py round-trip coverage; this tab is pure UI over
already-tested state). Live-verified: toggling Enlarge/grayscale-radio/prompt_options in the tab really
updates `settings.get_print_options()`, radio mutual-exclusivity confirmed (choosing grayscale correctly
clears monochrome). Full suite green (959 passed, 3 skipped, unchanged count as expected) before committing.

## Preferences dialog rebuild, part 5 - Capture tab (task #95 part 2 COMPLETE, 2026-08-14)

Final tab of the rebuild. Real Windows' Capture tab is three groupboxes: `groupbox_editor` (match-capture-
size), `groupbox_windowscapture` (capture-technique selector), `groupbox_capture` (zoomer/notifications/
sound/mouse-cursor/wait-time). Each got a real, deliberate decision rather than uniform treatment:

- **Capture mouse cursor** - already real (moved here in part 1).
- **Show magnifier while selecting a region, new this pass** - faithful port of the "zoomer" setting
  (`ZoomerEnabled`, `ICoreConfiguration.cs:318-320`, default `true`). Wired into both `ui/region_select.py`
  (X11) and `ui/region_select_wayland.py` (the Wayland portal-fallback path) - each reads
  `settings.get_show_magnifier_while_selecting()` once at construction (matching how `capture_mouse_cursor`
  is already resolved once, not per-frame) and gates only the magnifier-drawing lines, leaving the aiming
  crosshair and the selection-size label unconditional. Live-verified with a spy on `draw_magnifier` against
  a real `RegionSelectWindow` (synthetic `FakeCaptureBackend` content, never real desktop pixels) - confirmed
  it's actually called when the setting is on and genuinely skipped when off, not just that the flag gets
  set. **Real, documented platform gap**: the Wayland Shell-native path (task #82's own GJS port of this
  same magnifier, `RegionSelectOverlay` in the bundled extension) doesn't read this setting at all - it's
  separate JS code with no channel to `settings.json` short of adding one to the D-Bus call that starts it,
  out of scope for this pass. The Capture tab's own checkbox tooltip says so directly.
- **Window Capture group, deliberately excluded** - Windows' Screen/GDI/Aero/AeroTransparent/Auto capture-
  technique selector is entirely about which Windows graphics API grabs a window's pixels (GDI vs. DWM/Aero
  compositing bypass tricks) - no Linux equivalent exists or would mean anything; this port's X11/Wayland
  backends already pick the correct mechanism automatically per platform, there's no user-facing choice to
  surface. Same treatment interactive-capture-mode and the capture background color got, both parts of the
  same Windows-graphics-API-specific group.
- **Match capture size, deliberately not independently toggleable** - this port's editor always resizes to
  match the capture (task #97, `_resize_canvas_and_window`, a deliberate, already-verified, unconditional
  design choice folded into the same code path that also handles ongoing zoom-driven resizing). Making it a
  real off/on toggle would need a genuine "remembered/default editor size" fallback this port doesn't have
  at all - not a checkbox-wiring task, a real new feature nobody's asked for.
- **Wait time before capture, deliberately not built** - `numericUpDownWaitTime` implies a real capture-delay
  timer (useful for grabbing hover states/tooltips/context menus that vanish the instant a hotkey fires) -
  this port has no such timer anywhere in its capture pipeline. New functionality, not settings-wiring;
  not filed as its own task since nobody's requested it, unlike the notifications/sound gap.
- **Notifications/Play Sound, excluded per task #126** (already split off during the Output-tab pass - no
  capture-complete notify/sound feature exists in this port to attach them to).

2 new unit tests (`test_settings.py`'s `TestShowMagnifierWhileSelecting`). Live-verified: the checkbox
reflects/persists the real setting, and (separately, more importantly) the setting genuinely changes
`RegionSelectWindow`'s actual draw behavior, not just a stored flag nothing reads. Full suite green (961
passed, 3 skipped) before committing.

**Task #95 is now fully complete**: both halves (menu bar rebuild, part 1; the full 6-tab Preferences
rebuild, part 2's five sub-passes above) are done, live-verified, and documented. Split off along the way
into their own tracked tasks rather than bundled in: #123 (`.orcshot` file format), #124 (`.greenshot` NRBF
export, blocked on #123), #125 (real multi-select + Object menu's Select All), #126 (capture-complete
notifications + sound).

## Preferences dialog follow-up: Expert tab removed, filename-pattern modes, layout fixes (2026-08-14)

Direct follow-up requests from direflail after the tab-by-tab rebuild above landed, all same day.

**General tab reordered**: Application Settings, Hotkeys, Network and Updates (was Network and Updates,
Hotkeys, Application Settings, matching Windows' own `tab_general.Controls` declaration order) - direflail's
own call, no functional change.

**Expert tab removed entirely.** Every field it held moved to its real home: Suppress-save-dialog →
General > Application Settings; Counter (`${NUM}`) → Output > Preferred File Settings, directly under the
filename pattern field it feeds; Printer footer pattern → Printer tab, under the "Print date/time" checkbox
it belongs to. The "I know what I am doing!" gate that used to lock all of these went with it, by explicit
request - they're normal, always-editable settings now, matching every other tab. "Check for unstable
updates" (`get_check_unstable_updates`/`set_check_unstable_updates`, its settings key, and its tests) was
deleted outright rather than relocated - direflail's own call, since this port has no update-checking system
at all to attach it to (task #103).

**Filename pattern: two mutually exclusive modes, not composed.** direflail's own request - "in addition to
keeping the way greenshot does it" - to also support standard Linux/strftime-style codes (`%Y`, `%m`, ...)
alongside Greenshot's own `${YYYY}`/`${MM}` tokens. The first implementation attempt tried composing both in
one pattern (strftime pass, then `${...}` pass) and was caught live, by direflail, as a real bug before it
shipped: Python's `strftime()` delegates straight to the platform's C library, which recognizes a much
larger, platform-dependent code set than anyone expects - confirmed live that
`when.strftime("a%screenshot.png")` returns `"a1772723222creenshot.png"` (glibc's `%s` = Unix epoch seconds,
silently eating the "s"), and `%USERPROFILE%` (an ordinary pasted Windows envvar string) becomes
`"09SERPROFILE%"` (`%U` = ISO week number). A follow-up attempt narrowed this to a curated "safe" whitelist
of standard C89 codes only - also caught live as still broken: `%d` (day-of-month, a perfectly standard,
whitelisted code) ate the "d" out of the ordinary word "done" in `"100%done"`. The root cause isn't fixable
by curating the letter set smaller - a bare `%` immediately followed by a single ordinary letter is
*inherently* ambiguous in free text, since nearly every common code letter also starts ordinary English
words.

**Real fix, direflail's own call**: a real dropdown (`OutputSettings.filename_pattern_mode`,
`core.filename_pattern.MODE_GREENSHOT`/`MODE_STRFTIME`) - the two syntaxes are never both active on the same
pattern. In Greenshot mode, `%` is never parsed at all (pure literal text, matching real Windows' own
behavior exactly - it only ever understands `${...}`). In strftime mode, `${...}` is never parsed at all,
and this mode now uses the *real, full* `datetime.strftime()` (not a whitelist) - safe to do since it's an
explicit opt-in and the standard `%%`-escapes-a-literal-percent convention is expected, documented behavior
for anyone who deliberately chose this mode, not a silent footgun sitting in front of anyone who happens to
have used `%` in a pattern for an unrelated reason. `_build_output_settings_tab` gained a "Pattern style:"
combo box above the filename pattern field; the `?` help button's content is mode-aware, showing only the
relevant token/code list for whichever mode is currently selected.

11 new/rewritten unit tests in `test_filename_pattern.py` (`TestGreenshotMode`/`TestStrftimeMode`, replacing
the old single mixed-mode test class), including regression tests reproducing the exact `%s`/`%d` corruption
cases above to lock the fix in. Live-verified: the mode dropdown persists correctly, a quick-save in
strftime mode produces a correctly-formatted filename end-to-end (`20260814_072209.png` from
`%Y%m%d_%H%M%S`), and the General/Output/Printer tab restructuring (frame order, relocated fields, Expert
tab gone) was walked structurally against the live dialog. Full suite green (966 passed, 3 skipped) before
committing.

## .orcshot file format + Object > Save/Load Objects (task #123, complete 2026-08-14)

Real Windows Greenshot has two distinct ways to persist a shape layer, both grounded in
`Greenshot.Editor/Drawing/Surface.cs` and `Greenshot.Editor/Forms/ImageEditorForm.cs`:

- **A full `.greenshot` file** (`GreenshotFileFormatHandler.cs:49-133`): the captured image as PNG bytes,
  followed by the shape layer serialized with .NET's `BinaryFormatter` (NRBF), followed by a length and an
  ASCII version marker - PNG readers ignore the trailing bytes after `IEND`, so the file opens fine as a
  plain screenshot anywhere that doesn't know about the trailer.
- **Object > "Save objects to file" / "Load objects from file"** (`editor_save_objects`/`editor_load_objects`,
  `language-en-US.xml:170,131`) - a *separate*, image-less feature: `Surface.SaveElementsToStream`/
  `LoadElementsFromStream` (`Surface.cs:729-764`) serialize only the shape list (again via `BinaryFormatter`)
  to a "Greenshot templates (`*.gst`)" file, wired to the Object menu directly after the Arrange submenu
  (`ImageEditorForm.Designer.cs:734-736`, no separator between them) via `SaveFileDialog`/`OpenFileDialog`
  (`ImageEditorForm.cs:1598-1628`). `LoadElementsFromStream` *adds* the loaded elements onto whatever's
  already on the surface (`DeselectAllElements()` then `AddElements(loadedElements)`), it doesn't replace it.

This port builds both shapes, **not byte-compatible with either** - `BinaryFormatter`/NRBF is impractical to
hand-encode from Python (confirmed during task #124's own prior research, which is why #124 - a real NRBF
writer for actual `.greenshot`/`.gst` interop - is tracked as a separate, harder, still-blocked task). Instead:

- `core/orcshot_format.py` (pure Python + numpy, no GTK import at all - deliberately kept headless, mirroring
  how `core/` stays GTK-free everywhere else): `serialize_shape`/`deserialize_shape` dispatch on `type(shape)`
  exactly rather than `isinstance`, so `ArrowShape` (a `LineShape` subclass with no new fields, just a
  different hit-test margin) round-trips as an Arrow, not a Line. Per-shape embedded images (Icon/Cursor/
  Image shapes) are base64-encoded raw numpy bytes, not PNG - keeps this module free of any image-codec
  dependency. `ObfuscateShape.seed` (`compare=False` on the dataclass, so it doesn't affect `==`) is still
  explicitly serialized and restored, since it drives deterministic per-shape noise rendering - a lost/
  regenerated seed wouldn't be caught by an equality check alone, only by comparing `.seed` directly.
- `ui/orcshot_file.py` (GdkPixbuf-based, headless-testable like `ui/file_export.py`'s own precedent - no X11
  connection needed despite living in `ui/`): `save_orcshot_file`/`load_orcshot_file` write the full
  PNG-bytes + JSON-blob + 8-byte little-endian length + `b"ORCSHOT1"` marker container (same "PNG readers
  ignore the trailer" trick as real `.greenshot`, confirmed live - a saved `.orcshot` file opens fine via
  plain `GdkPixbuf.Pixbuf.new_from_file`). `save_objects_file`/`load_objects_file` are the separate,
  image-less pair mirroring `SaveElementsToStream`/`LoadElementsFromStream` - plain JSON, no PNG/trailer
  framing at all (there's no image portion for a PNG reader to fall back to, so pretending otherwise would be
  misleading). `load_objects_file` transparently accepts *either* a Save-Objects file or a full `.orcshot`
  file (image discarded) by checking for the trailer marker - reasonable either way, since pulling a shape
  layer back out of a full file is a sensible thing to want.

**UI wiring** in `ui/editor_window.py`: Save As... gained `"orcshot"` as a format choice
(`"Orcshot (with shapes, task #123)"`), appended directly to the Save-As dialog's own format combo rather
than to the shared `_SAVE_AS_FORMATS` list (which also backs the Output tab's "Primary format" dropdown) -
real Windows' own `OutputFileFormat` setting explicitly excludes "greenshot" as a valid default/quick-save
format too (`ICoreConfiguration.cs:130-132` lists only "bmp, gif, jpg, png, tiff"), so `.orcshot`/`.greenshot`
is Save-As-only on both platforms, never a primary format. Choosing it saves `self._base_image` (the raw
capture) + `self.layer` directly rather than the flattened `_composited_image()` - the whole point is keeping
shapes separately editable. The Object menu gained "Save Objects..."/"Load Objects..." directly after Arrange
(matching real Windows' own placement, no separator, per the Designer.cs citation above), using a plain
`*.json` extension rather than claiming to write a real `.gst` file. Load Objects pushes one
`AddElementMemento` per loaded shape (the only add-memento this port has - no bulk-load memento type exists,
so undoing a multi-shape load takes multiple undos) and selects the last-loaded shape, standing in for real
Windows' multi-element `SelectElements(loadedElements)` (this port only tracks one selected shape today -
task #125). An invalid/corrupt file shows a `Gtk.MessageDialog` (`InvalidOrcshotFileError`'s message) rather
than crashing.

Deliberately out of scope for this pass: a general File > Open / MIME-type / double-click-to-open flow for
`.orcshot` files - the task's own literal scope is "wire into Save As... and Object menu's Save/Load
Objects," and `load_objects_file`'s own "accepts a full `.orcshot` file too" behavior already covers pulling
shapes back out of a saved file without a dedicated Open flow. Flagged here as a real, known gap rather than
silently built or silently dropped - not yet tracked as its own task.

30 new unit tests (`test_orcshot_format.py`: one round-trip per shape type + the Arrow/Line and Obfuscate-seed
cases above, 18 tests; `test_orcshot_file.py`: round-trip, PNG-backward-compat, invalid-file, and
Save/Load-Objects cases, 12 tests). Live-verified end-to-end with a synthetic (non-desktop) test image and
two synthetic shapes: Save As → `.orcshot` (image and shapes both round-trip, file still opens as a plain
PNG), Object > Save Objects (writes a file), Object > Load Objects into a fresh window (populates the layer,
sets a selection, is undoable - undoing both loads empties the layer again), and Object > Load Objects on a
corrupt file (shows the error dialog, leaves the layer untouched, no crash). Full suite green (996 passed, 3
skipped) before committing.

## .greenshot NRBF export proof-of-concept: RectangleContainer (task #124, PARKED, 2026-08-14)

Real Windows `.greenshot`/`.gst` files embed the shape layer via raw .NET `BinaryFormatter` (MS-NRBF wire
format) - `GreenshotFileFormatHandler.cs:49-133`, `Surface.cs:729-764`. Earlier research (recorded in the
task #95 writeup) assumed this was "genuinely buildable but scoped separately"; a closer look this session
(direflail: "dig deeper before concluding infeasible" applies here too) confirmed it's not just buildable
but was mostly *already built*, elsewhere.

**Approach, narrowed twice by direflail's own direct pushback**, each time landing on a smaller, more
tractable design than the one before:

1. First framing (rejected): a generic Python object-graph serializer covering all ~14 shape types plus
   arbitrary System.Drawing/Field types - estimated 15-25 hours.
2. direflail: *"is this still a serializer for EVERYTHING? why are we not just making a serializer that
   does only what the .orcshot format will give it?"* - correct: real `RectangleContainer`'s 9 serialized
   members are either a direct 1:1 mapping from this port's own `Rect`/`ShapeStyle` data, or fixed constants
   for every freshly-placed shape (undrawn-state enum, empty `Children`, `accountForShadowChange=False`) -
   nothing needs a general graph walker.
3. direflail: *"can't you just translate the serializer they already have into python"* - led to finding
   `agix/NetBinaryFormatterParser` (MIT, github.com/agix/NetBinaryFormatterParser), an existing Python 2
   NRBF reader **and writer** (`JSON2dotnetBinaryFormatter.py`) implementing exactly the record types real
   Greenshot's own output uses. Ported to Python 3 (`core/nrbf.py`), fixing two real bugs found while
   porting: `Single`/`Double` were packed with `'<I'`/`'<Q'` (raw-bit reinterpretation) instead of `'<f'`/
   `'<d'` (real IEEE 754). See `THIRD_PARTY_NOTICES.md` and `debian/copyright` for the MIT attribution.

**Ground truth came from the real object, not guesswork.** Using the windows11 VM (`VBoxManage
guestcontrol`, full-email-no-domain credential per its own reference doc), `Assembly.LoadFrom` on the real
installed `Greenshot.Editor.dll`/`Greenshot.Base.dll`, `FormatterServices.GetUninitializedObject` to build a
bare `RectangleContainer` without needing a real `Surface`, then the real `BinaryFormatter.Serialize` -
captured actual bytes real Greenshot itself produced (`tests/fixtures/rectangle_container.nrbf`). Hand-
decoding those bytes against the MS-NRBF spec caught a real bug in the *first* hand-rolled reader: member
type info is written as *all* `BinaryTypeEnumeration` bytes first, then *all* `AdditionalInfo` values -
not interleaved per-member as first assumed. Fixed, then verified: a from-scratch Python encoder
constructed to match reproduced the real bytes **exactly**, byte-for-byte, for a bare (empty
`Children`/`fields`) `RectangleContainer`.

Also explained, via `dotnet/runtime`'s own open-source `FormatterServices.cs`
(`InternalGetSerializableMembers`), a real .NET quirk this session's decode surfaced: `_defaultEditMode`
(a `protected` field) is serialized *twice* - once unqualified (picked up by a plain `GetFields()` call on
the concrete type, which returns non-private inherited fields) and once as `"DrawableContainer+..."`
(picked up again by a separate per-ancestor-level walk for private fields, which doesn't check for fields
the first pass already found). Not a bug in this port's reading of the format - genuine real Windows
behavior, reproduced deliberately rather than "fixed away."

**Populating real style data (`fields`)**: reading `RectangleContainer.cs`'s own `InitializeFields()`
(`LINE_THICKNESS`/`LINE_COLOR`/`FILL_COLOR`/`SHADOW`) confirmed a clean 1:1 match with this port's own
`ShapeStyle` dataclass. VM-reflected the real `Field`/`FieldType`/`System.Drawing.Color` classes'
serializable layout (`Field`: `_myValue`/`<FieldType>k__BackingField`/`<Scope>k__BackingField`; `FieldType`:
`<Name>k__BackingField`; `Color`: `name`/`value`/`knownColor`/`state`, confirmed live that an ARGB-explicit
color - `Color.FromArgb(...)`, what this port's own RGBA-tuple `ShapeStyle` will always produce - encodes
as `state=2` with `value` holding the packed ARGB as an *unsigned* 32-bit pattern zero-extended into the
Int64 field, not sign-extended; real Greenshot's own "known color" shortcuts like `Color.Red` use a
different, irrelevant encoding this port doesn't need). Constructed a full `RectangleContainer` with 4 real
`Field` entries via the VM and round-tripped it through real Greenshot's own
`BinaryFormatterHelper` (its actual security whitelist binder, the same code path `Object > Load Objects`/
opening a real `.greenshot` file uses) - deserialized successfully back into a genuine `RectangleContainer`
with every field intact.

**`core/greenshot_export.py`** (`rectangle_shape_to_greenshot_nrbf`) uses this port's own simple, sequential
object-id scheme rather than replicating real `BinaryFormatter`'s breadth-first discovery-order ids (an
implementation optimization detail, not an MS-NRBF requirement) - proven by sending *this port's own*
independently-encoded bytes (different id numbers than the VM capture, never seen by real Greenshot before)
back to the VM and round-tripping them through the same real `BinaryFormatterHelper` binder. Caught one real
bug this way: `System.Drawing.Color`'s library id was referenced without ever emitting the `BinaryLibrary`
record declaring it - real Greenshot's own deserializer rejected it with `"No assembly ID for object type
'4 System.Drawing.Color'"`. Fixed; re-verified live: `SUCCESS: deserialized as
Greenshot.Editor.Drawing.RectangleContainer`, `left=10 top=20 width=100 height=50`,
`LINE_THICKNESS=3, LINE_COLOR=(255,200,30,30), FILL_COLOR=(0,0,0,0), SHADOW=True` - exactly the shape passed
in.

**Scope, explicitly confirmed with direflail**: this is the `RectangleContainer` proof-of-concept only, not
the other ~13 shape types (a separate, much larger follow-up - revised estimate ~4-6 hours using this same
now-proven template-per-type approach, down from an initial ~15-25 hour generic-serializer estimate). Also
not yet done: wiring `rectangle_shape_to_greenshot_nrbf`'s output into an actual `.greenshot`/`.gst` file
container (PNG + NRBF blob + trailer, matching `GreenshotFileFormatHandler.cs`) or any editor UI - this
section covers the object-graph bytes only. **Flagged, not yet solved**: Orcshot has (or will have) data
with no real-Greenshot equivalent to translate to (task #123's `.orcshot`-only features, e.g. its two
filename-pattern modes, OCR-based auto-obfuscate, or future Orcshot-only shape types) - the strategy for
what happens when a `.greenshot` export hits data the real format can't represent (drop, approximate, warn,
refuse) is an open design question for whoever picks up full 14-shape coverage.

12 new unit tests (`test_nrbf.py`: low-level record-writing correctness, including a regression test for
the Single/Double packing bug; `test_greenshot_export.py`: a regression test for the missing-BinaryLibrary
bug, header/MessageEnd framing, and exact bounds/style byte-pattern checks using the same values verified
live against the VM). `tests/fixtures/rectangle_container.nrbf` is the real VM-captured reference file.
Full suite green (1008 passed, 3 skipped).

**Decision: parked as a maybe-add.** Before stopping, the obvious next step - calling real Greenshot's own
compiled DLLs directly via `pythonnet`+Mono instead of maintaining a hand-ported encoder - was actually
tested, not just discussed. Installed `mono-complete`, pulled `Greenshot.Editor.dll`/`Greenshot.Base.dll` +
all 33 `Dapplo.*` dependencies off the `windows11` VM (`VBoxManage guestcontrol copyfrom --recursive`), and
proved live: the real DLLs load under Mono on Linux, a full `RectangleContainer` with real
`Field`/`FieldType`/`System.Drawing.Color` objects constructs correctly (`Color.FromArgb` needs no
`libgdiplus`/GDI+ P/Invoke), `BinaryFormatter.Serialize` works, and deserializing back through the real
`BinaryFormatterHelper` whitelist binder succeeds with exactly correct values. The assumption that
`Dapplo.Windows.*` (Windows-only P/Invoke wrappers) would block this was wrong - .NET's assembly loading is
lazy, so a DLL is only resolved once a type from it is actually touched (one real exception:
`FormatterServices.GetUninitializedObject` needs every field's *type* resolvable up front for the full
object layout, which is why `log4net.dll` and `Dapplo.Windows.Common.dll` specifically were still required
even for construction-only). Measured real sizes: a minimal Mono *runtime* (not `mono-complete`'s
compiler/dev/doc tooling) is ~13.4MB core engine + ~6.7MB of System.* CIL libraries actually touched, plus
~5.4MB for the full bundled Greenshot DLL set - **~25-30MB of permanent runtime dependency for every
install**, for a feature most users won't use. Legally uncomplicated (GPLv3-to-GPLv3 reuse with
attribution), but direflail weighed the size cost against wanting Orcshot to stay small and chose small:
*"let's just save our own files in .orcshot format. leave saving .greenshot with mono the way we described
as a maybe-add."* Task #124 is parked, not abandoned - the pure-Python proof-of-concept above stays
committed and working; picking this up again (either finishing the pure-Python path for the other ~13 shape
types, or revisiting the Mono path, e.g. if `.greenshot` *reading* - which the Mono path gets nearly for
free - becomes a priority) should start by reading this section, not re-deriving either approach.

## Real multi-select: shift-click + rubber-band, Object > Select All (task #125, complete 2026-08-14)

**Real Windows source read first, faithfully:** `Surface.cs`'s `SurfaceMouseDown`/`SurfaceMouseMove`/
`SurfaceMouseUp` (~1477-1732), `SelectAllElements`/`SelectElements`/`SelectElement`/`DeselectElement`
(~2485-2530), and `RemoveSelectedElements`/`CutSelectedElements`/`CopySelectedElements`/
`DuplicateSelectedElements` (~2118-2420); `ImageEditorForm.cs`'s `SelectAllToolStripMenuItemClick`
(line 1699); `ImageEditorForm.Designer.cs`'s exact Object menu ordering (`selectAllToolStripMenuItem`
directly above `removeObjectToolStripMenuItem`, no separator between them). Real Windows commits
shift-toggle membership on **mouse-up**, not mouse-down; a plain click on something not already
selected replaces the whole selection; a plain click on something already part of a multi-selection
leaves the selection untouched (so dragging any member moves the whole group). **Real Windows has no
rubber-band/marquee-select at all** — confirmed by reading the complete `SurfaceMouseDown`/
`SurfaceMouseMove` bodies and finding no branch for "drag over empty space to draw a selection
rectangle."

**Deliberate deviations:**
- This port's selection commits on **mouse-down**, not mouse-up (a pre-existing architecture choice
  from before this task, kept rather than switched, to limit the size of this change). Shift-toggle and
  the "already-selected click preserves the group" behavior are both still faithfully reproduced, just
  evaluated at press time instead of release time.
- **Rubber-band/marquee select is an Orcshot-only addition beyond the real port** — direflail's own
  explicit choice (`"Shift-click + rubber-band (bigger, Orcshot-only addition)"`) when asked to scope
  this task, given real Windows has none. Dragging from empty space with the Select tool draws a
  dashed selection rectangle; releasing selects every shape whose bounds are **fully** contained in it
  (`Rect.contains_rect`, `core/geometry.py`) — partial overlap doesn't select, matching the common
  "fully enclosed" convention most editors use for marquee-select. Shift-held rubber-band is additive
  (unions with the existing selection) rather than replacing it.

**Implementation:**
- `EditorWindow._selected_shapes` (list, was a single `_selected_shape`) is the source of truth;
  `selected_shape` (singular, returns the last/"primary" entry) stays as the existing property other
  code already reads, `selected_shapes` (plural) is new. `_set_selected_shapes()` is the single funnel
  point every selection change goes through.
- Move state (`_move_shapes`/`_move_origin`/`_move_previews`) and clipboard (`_shape_clipboard`) were
  pluralized the same way. `_do_delete`/`_do_cut_shape`/`_do_copy_shape`/`_do_paste_shape`/
  `_do_duplicate` all now operate on the whole selection, pushing one `CompositeMemento` for a
  multi-shape delete/move — `CompositeMemento` (`core/history.py`) already existed as a faithful port
  of `AddElementsMemento`/`DeleteElementsMemento` but had never been wired to anything before this task.
- Shapes are `@dataclass(frozen=True)` with structural equality, so two coincidentally-identical shape
  instances would collide as the same value; every membership check and lookup in the new code
  deliberately uses identity (`is`) or parallel lists, never a shape-keyed dict or `in`/`==`.
- `Object > Select All` (`_do_select_all`) wired directly above `Delete` in the Object menu, matching
  the real Designer.cs ordering exactly (no separator between them).
- Non-primary selected shapes get a dashed outline (`_draw_selection_outline`) so a multi-selection is
  visually distinguishable from a single one; the primary (last-selected) shape keeps the existing
  resize-handle rendering.

**Verified live** (`Gtk.Window`-based `EditorWindow`, synthetic `Gdk`-shaped press/motion/release
events against the real handlers — not mocks): plain click, shift-click add/remove, click on an
already-selected member preserving the group, dragging a multi-selection as one undo step (and
undoing it as one step), full-selection Select All, rubber-band select (full-enclosure only, verified
a partially-overlapping shape is correctly excluded), shift+rubber-band as additive, click-on-empty-
space clearing the selection, and multi-shape Delete/Duplicate/Cut/Paste each producing the right
layer/undo-stack/selection state. `_on_draw` also exercised directly with an active multi-selection
and a live rubber-band rect to confirm the new drawing paths don't raise. Full suite green (1011
passed, 3 skipped) both before and after.

## File > Open for .orcshot files + MIME/double-click (task #129, complete 2026-08-14)

**No real Windows equivalent, confirmed by source read.** `ImageEditorForm.Designer.cs`'s File menu
has no "Open" item at all — the closest analogue is `LoadElementsToolStripMenuItemClick`
(`ImageEditorForm.cs:1613-1628`, this port's own Object > Load Objects), which loads a shape-only
`.gst` template onto the *current* surface rather than opening a saved capture as a new document.
Real Greenshot has no general "reopen a saved capture" concept at all — screenshots are captured, not
opened as files. This whole task is therefore an Orcshot-only addition, same as task #123's own
`.orcshot` format it builds on.

**Implementation:**
- `EditorWindow._do_open` (File > Open..., placed first in the File menu, ahead of Save) and
  `open_orcshot_file_in_new_window` (module-level, `ui/editor_window.py`) — the latter shared with the
  app-level file-manager open path below. Opening always creates a **brand-new** `EditorWindow` rather
  than replacing the current one's document, consistent with every capture already becoming its own
  window (task #111's "Reuse Editor" setting doesn't exist yet). The loaded shapes become the new
  window's initial content, not undoable edits — no mementos are pushed, so the fresh undo stack starts
  empty and nothing is pre-selected, matching how opening a file leaves nothing to "undo" back out of.
  An invalid/non-.orcshot file shows the same `Gtk.MessageDialog` error pattern already used by Object
  > Load Objects, rather than raising.
- **MIME/double-click**: `debian/orcshot.desktop` now sets `Exec=orcshot %u` and
  `MimeType=application/x-orcshot;`; `src/orcshot/resources/orcshot.xml` (installed to
  `/usr/share/mime/packages/orcshot.xml`) registers `application/x-orcshot` with a `*.orcshot` glob and
  `sub-class-of image/png` — deliberate, not decorative: a `.orcshot` file really is a valid PNG with a
  trailing shape-layer blob (`ui/orcshot_file.py`'s own module docstring), so this keeps a plain image
  viewer able to open one even where Orcshot itself isn't installed. No manual `update-mime-database`/
  `update-desktop-database` calls added to `debian/orcshot.postinst` — both `/usr/share/mime/packages`
  and `/usr/share/applications` already have dpkg triggers (via `shared-mime-info` and
  `desktop-file-utils` respectively) that fire automatically on install, the same reason the existing
  `.desktop`/icon files never needed one either.
- `app.py`'s `do_command_line` gained an `else` branch: positional (non-option) command-line arguments
  are treated as files to open via the new `OrcshotApplication.open_file` (resolves a plain path or a
  `file://` URI via `Gio.File.new_for_commandline_arg`, since a file manager's `%u` substitution sends a
  URI, not necessarily a bare path). This reuses the exact single-instance `do_command_line` forwarding
  every capture CLI option already relies on, so double-clicking a `.orcshot` file while Orcshot is
  already running opens it in the already-running instance rather than spawning a second process - no
  new IPC mechanism needed. `HANDLES_OPEN`/`do_open` (GApplication's dedicated file-open vtable) was
  considered and deliberately not used - it only takes over from `do_command_line` when the desktop
  entry sets `DBusActivatable=true`, which this one doesn't, so a plain `HANDLES_COMMAND_LINE`
  positional-argument check is the simpler, already-consistent mechanism here.

**Verified live**: `save_orcshot_file` → `open_orcshot_file_in_new_window` round trip (base image and
shape layer both come back correctly, undo stack starts empty, nothing pre-selected); the error-dialog
path for a file with no `.orcshot` trailer, driven via this project's own established
`GLib.timeout_add` + `Gtk.Window.list_toplevels()` + `.response()` pattern for a nested `dialog.run()`
loop (confirmed it returns `None` rather than raising); `OrcshotApplication.open_file` resolving both a
plain path and a `file://` URI to the same path. A real bug was caught this way before it shipped:
`load_orcshot_file` was used in the new code but never actually imported (only
`load_objects_file`/`save_orcshot_file`/etc. were) - `open_orcshot_file_in_new_window` would have raised
`NameError` on its very first real use. Fixed by adding it to the existing import. Full suite green
(1011 passed, 3 skipped).

## Preferences reachable from the tray icon (task #119, complete 2026-08-14)

Real Windows has this too - `contextmenu_settings` on the tray's own context menu
(`MainForm.Designer.cs`), labeled "Preferences..." (`language-en-US.xml:62`, matching this port's own
Edit menu wording already), positioned after the capture items and before Exit. Before this task,
Orcshot's Preferences dialog (`_do_show_settings`) only existed as an `EditorWindow` method, reachable
from the editor's own Edit menu or toolbar button - there was no way to reach it at all with no editor
open, which is exactly what the tray menu needs to cover (the tray icon and its capture items are
usable with zero editors open).

**Refactor, not just a new menu item.** `_do_show_settings` and its five tab-builder methods
(`_build_general_settings_tab`, `_build_capture_settings_tab`, `_build_output_settings_tab`,
`_build_destinations_settings_tab`, `_build_printer_settings_tab`) turned out to use `self` for nothing
but (a) `transient_for` on the dialogs they open and (b) two plain constant tuples
(`_SAVE_AS_FORMATS`, `_EXTERNAL_EDITOR_CANDIDATES`) - no editor state (image, layer, selection) at all.
So rather than duplicating ~580 lines of dialog-building code for a parent-less tray variant, all six
were converted to module-level functions in `ui/editor_window.py` taking an explicit
`parent: Gtk.Window = None`, with the two constants promoted to module level alongside them.
`EditorWindow._do_show_settings` is now a two-line wrapper calling the new
`show_preferences_dialog(self)`. `_do_choose_save_location` (used by both the Output tab and the File
menu's own "Screenshot Save Location..." item) got the same treatment, extracted to a module-level
`_choose_save_location(parent)`. `OrcshotApplication.show_preferences` (`app.py`) is the tray menu's own
callback - it passes the topmost open editor as `parent` when one exists (nicer window stacking,
matching what opening it from that editor's own menu would do) and `None` otherwise, which is the
actual fix: `show_preferences_dialog(None)` now works, where calling an `EditorWindow` method never
could.

One small, deliberate behavior change from this refactor: sub-dialogs opened from within a settings tab
(the hotkeys configure dialog, the filename-pattern help popup) are now `transient_for` the Preferences
dialog itself rather than the original `EditorWindow` - a more correct GTK window-stacking parent (the
Preferences dialog is the actual on-screen ancestor at that point), not a regression.

**Verified live**: `show_preferences_dialog(None)` (the tray's own no-editor-open path) opens and closes
without raising, exercising construction of all five tabs in one call; `EditorWindow._do_show_settings()`
still works unchanged after the refactor (regression check); `OrcshotApplication.show_preferences()`
verified both with no open editor and with one open, driven live via this project's own established
`GLib.timeout_add` + `Gtk.Window.list_toplevels()` + `.response()` pattern for a nested `dialog.run()`
loop. Tray menu item order also verified directly (`Preferences...` sits between a separator after the
capture items and the separator before Quit, matching real Windows' own relative position). Full suite
green (1011 passed, 3 skipped).

## Check for Updates (task #103, complete 2026-08-14)

**Faithful basis**: `UpdateService.cs` in full - a background timer, not a manual trigger (confirmed by
reading the whole file plus `MainForm.cs`'s own `updateService.Startup()` call site and every
`SettingsForm.Designer.cs` control; no "check now" button exists anywhere in real Windows). Starts 20
seconds after startup (`BackgroundTask`'s own "Initial delay, to make sure this doesn't happen at the
startup"), gated by `UpdateCheckInterval` days (0 = disabled - already ported as
`settings.get_update_check_interval_days`, default 14, previously a documented no-op waiting on this
task). On finding a newer version, shows a toast whose click action opens a generic Downloads page
(`Process.Start(Downloads.AbsoluteUri)`, `ShowUpdate`) - it never names or picks a specific installer,
which is exactly the precedent this task's own GitHub-Releases adaptation leans on.

**Deliberate adaptations** (all discussed and confirmed with direflail before implementation):

- **GitHub Releases instead of a self-hosted feed.** Real Windows polls `getgreenshot.org/update-feed.json`
  (a file that project hosts itself); Orcshot has no equivalent website, so `core/update_check.py` +
  `ui/update_check.py` poll `GET api.github.com/repos/artificialorctelligence/orcshot/releases/latest` instead. That
  endpoint already excludes prereleases/drafts on its own, which is why there's no beta-channel
  distinction to port (`IsBetaUpdateAvailable` has no Orcshot equivalent) - consistent with the real
  Expert-tab "Check for unstable updates" checkbox already having been dropped outright (task #93
  follow-up) rather than relocated.
- **Link to the release page, not a specific installer asset.** Directly answers a hypothetical
  direflail raised while scoping this: what if a future release needs more than one installer format
  (`.deb`, Flatpak, AppImage, ...)? Real Windows' own answer is "don't try to know" - it always links to
  a generic page and lets a human pick. A GitHub Release tag can carry multiple assets under one
  version; since the update-checker only ever needs the release's own `html_url`, adding a second
  installer format later is a packaging-only change - this code never has to learn about installer
  types at all.
- **No separate `LastUpdateShown` 24-hour reshow guard.** Real Windows has two timestamps - one gating
  the check itself (`LastUpdateCheck`), a separate one gating how often the *same* found update gets
  re-shown even if checks happen more frequently. Given `update_check_interval_days` defaults to 14 (and
  is expected to normally be days, not hours), the check itself already can't repeat inside a day in any
  realistic configuration, making the second guard redundant here - one `settings.last_update_check`
  field (`get_last_update_check`/`set_last_update_check`, `settings.py`) covers both roles.
- **New Orcshot-only manual trigger**: Help > "Check for Updates..." (`EditorWindow._do_check_for_updates`,
  next to "About Orcshot"), since real Windows has nothing to match here at all - the task's own title
  asked for "menu support" specifically. Unlike the silent background check, a manual click always
  reports back (an "up to date" info dialog, or an error dialog if GitHub couldn't be reached) rather
  than only speaking up when there's something to say - staying silent after a deliberate click would
  read as broken.

**Architecture**: `core/update_check.py` (pure, unit-tested) holds `parse_version`/`is_newer_version`
(mirrors `ProcessFeed`'s own `Regex.Replace(tag, "[a-zA-Z\-]*", "")` cleanup before comparing) and
`should_check_now` (mirrors `BackgroundTask`'s `checkIsDisabled`/`nextCheckIsInTheFuture` gating).
`ui/update_check.py`'s `fetch_latest_release()` does the actual network call - stdlib `urllib.request`
only, no new dependency for one lightweight GET a week; returns `None` on *any* failure (no release
published yet, network down, malformed response), matching `UpdateCheck`'s own
`if (updateFeed == null) return;`. `app.py` wires it all together: `do_startup` registers an
`app.open-uri` `Gio.SimpleAction` (the only way a `Gio.Notification`'s click action can open a URL - it
targets a registered action, not a plain callback) and a `GLib.timeout_add_seconds` chain (one-shot 20s
delay, then a recurring hourly poll that re-checks `should_check_now` rather than reproducing Windows'
own dynamic `TimeSpan` rescheduling). The network fetch runs on a background `threading.Thread` -
`urlopen()` would otherwise block the GTK main loop - with `GLib.idle_add` marshaling the result back to
the main thread, since every subsequent step (dialogs, notifications) has to run there.

**Shared with task #126** (capture-complete notifications, still pending): `OrcshotApplication._notify`
is a small `Gio.Notification` wrapper - the app already being a registered `Gio.Application` makes this
~15 lines. Orcshot had no notification mechanism at all before this task; building it as a small shared
piece now (title/body/click-action only, no sound) avoids a second one-off when #126 needs the same
primitive.

**Verified live** (`OrcshotApplication`, `.register()`'d but never `.run()` - avoids publishing a real
D-Bus name for a throwaway test instance, or crashing outright: calling `do_startup()`/`add_action()`
without registering first segfaults at the GLib level, confirmed by hitting it directly before fixing
the verification script): `do_startup()` runs clean and registers `app.open-uri`; a manual check with a
mocked "update available" response runs without raising; a manual check when already up to date opens
and closes a real info dialog (driven via this project's own established `GLib.timeout_add` +
`list_toplevels()` + `.response()` pattern); a manual check when the fetch fails opens and closes a real
error dialog the same way; a periodic tick correctly skips the network call entirely when
`should_check_now` says a check isn't due yet. `EditorWindow._do_check_for_updates` verified to build
into the Help menu and no-op safely with no running `Gio.Application` (a bare `EditorWindow` instantiated
outside `OrcshotApplication`, as several other live-verification scripts in this project already do).
`_notify`'s actual notification delivery couldn't be exercised end-to-end in this pass specifically - a
real Orcshot instance was already running on this dev machine during verification (`ps aux`, PID
confirmed), so this script's own `OrcshotApplication` correctly registered as *remote* rather than
primary, and `Gio.Application.send_notification` is a primary-only call (a harmless `GLib-GIO-CRITICAL`,
not a bug - proof the single-instance mechanism itself is working correctly, not a gap in this feature).
16 new unit tests (`test_update_check.py`) plus 2 for the new `settings.last_update_check` field
(`test_settings.py`). Full suite green (1029 passed, 3 skipped).

## Destination-picker icons missing in the Wayland/Shell-native picker (task #133, complete 2026-08-14)

**Wrong initial diagnosis, corrected before fixing anything - worth recording so it doesn't get
re-chased.** When this was first filed (from task #50's live verification), the working theory was a
rendering bug in `ui/destination_picker.py`'s `Gtk.Menu` - a pixbuf-based icon failing to composite
inside a real `menu.popup_at_rect()` Wayland popup specifically, since an isolated test of
`destination_icon_image()` rendered correctly. That isolated test was real but answered the wrong
question: it only proved the pixbuf *data* was correct, and a follow-up reproduction (a real
`Gtk.Menu` with pixbuf icons, actually shown via `popup_at_rect` against a live anchor window,
inspected by reading the popup's own `GdkWindow` pixels directly - not a desktop screenshot) rendered
correctly too. The Python code was never the problem.

**Real root cause**: `capture/gnome_region_select.py`'s own module docstring says it outright - "the
*entire* interaction (frozen backdrop, drag-to-select, ..., and the post-capture destination picker)
runs inside the Shell/Mutter compositor process" for the GNOME-Shell-native Wayland flow (task #77).
The popup the user actually sees is built by
`resources/gnome-shell-extensions/orcshot-clipboard@orcshot.org/extension.js`'s own
`pickDestinationAsync()`, using GNOME Shell's native `PopupMenu.PopupMenu` - a completely different
render path from `destination_picker.py`'s `Gtk.Menu`, which `region_select.py`'s own comment already
noted "is no longer used for the Wayland/Shell-native flow at all" (`ui/region_select.py:369-374`).
Confirmed with `grep -i icon extension.js`: zero matches. Task #96 gave the Python picker hand-drawn
icons; task #77's later Shell-side rewrite of the *popup itself* for this flow never carried them
over - `menu.addAction(label, callback)` (the API used) only ever takes a plain label, no icon
parameter exists on it at all. A missing feature, not a broken one.

**Fix**: `DESTINATIONS` gained a third element per entry - a themed icon name matching
`ui/editor_window.py`'s own File/Edit menu items for the exact same actions exactly
(`edit-copy-symbolic`, `document-save-symbolic`, `document-save-as-symbolic`,
`applications-graphics-symbolic` - the same one `_do_open_in_external_editor`'s own toolbar button
uses, `document-print-symbolic`). The `menu.addAction()` calls became manually constructed
`PopupMenu.PopupImageMenuItem(label, iconName)` instances (GNOME Shell's own built-in icon+label menu
item class, from the same already-imported `PopupMenu` module) with `activate` connected by hand,
added via `menu.addMenuItem()`. Themed icon names rather than porting the hand-drawn cairo glyphs to
GJS/Clutter - simpler, and St.Icon's own icon-theme lookup already resolves these names correctly
with no drawing code needed.

**Verified live, twice, for real reasons each time**: `node --input-type=module --check` confirmed JS
syntax before ever touching the VM. Per this project's own established finding
([[feedback-extension-reload-caching]]), a GNOME Shell extension's `.js` doesn't reload on
`gnome-extensions disable`/`enable` - only a full logout/login does - so the fix was pushed to the
VM's user-local extension override path (`~/.local/share/gnome-shell/extensions/...`, which takes
precedence over the system copy the `.deb` installed) and confirmed `State: ACTIVE` from that path
only *after* a real logout/login. A genuine end-to-end capture (region-select through the destination
picker) then confirmed icons render correctly - direflail's own words: "works."

## Tray icon capture-mode menu had no icons at all (task #137, complete 2026-08-15)

**Reported by direflail via screenshot**: the tray icon's own right-click menu (Capture Region/Full
Screen/Active Window/Window.../Repeat Last Region/Preferences/Quit) had never had icons, on any
platform - confirmed live on Ubuntu 24.04, 26.04, and X11/Mint alike. Real Windows Greenshot has an
icon on every one of these (`MainForm.Designer.cs`: `contextmenu_capturearea.Image`,
`contextmenu_capturewindow.Image`, `contextmenu_settings.Image`, `contextmenu_exit.Image`, etc.).

**Fix, part 1 - icons**: five new hand-drawn cairo icons added to `ui/icons.py`
(`capture_mode_icon_image()` / `_CAPTURE_MODE_ICON_BUILDERS`) - a dashed rectangle for Capture Region
(the "marching ants" region-select metaphor), a monitor+stand for Full Screen, a solid window frame
for Active Window, the same frame dashed for Window Picker (dashed = interactive pick, solid =
concrete/current, kept consistent across the pair), and a rectangle plus a small refresh arrow for
Repeat Last Region. Preferences/Quit reuse standard theme icon names
(`preferences-system-symbolic`/`application-exit-symbolic`), matching `editor_window.py`'s own
`menu_item` helper. Each icon was rendered to a standalone PNG and visually checked before being wired
in - the same discipline used for the earlier toolbar icons.

**Fix, part 2 - Wayland showed no icons even after part 1**: `_build_tray_menu`'s `menu_item` helper
originally built each row as a `Gtk.MenuItem` wrapping a hand-composed `Gtk.Box(image, label)`, the
same pattern `editor_window.py`/`destination_picker.py` use for their own (purely local) menus. That
rendered correctly on X11 but showed no icons at all on Wayland/Ubuntu 26.04. Root cause: unlike those
other menus, this one is exported over the DBusMenu D-Bus protocol by
`AyatanaAppIndicator3.Indicator.set_menu()` under Wayland (see `_build_tray_icon`'s own comment for why
X11 stays on `Gtk.StatusIcon` instead of unifying onto AppIndicator) and rendered by a *remote*
process - `ubuntu-appindicators@ubuntu.com`, the Shell extension that hosts AppIndicator menus - using
its own JS/Clutter/St widgets, not this process's GTK widget tree at all. Its exporter only reads
recognized GTK properties (`Gtk.ImageMenuItem.image`), not an arbitrary child widget composition.
Switching every row to `Gtk.ImageMenuItem` (deprecated since GTK 3.10 but still functional - the
deprecation is exactly why the other, local-only menus moved away from it, not evidence it's broken)
plus `set_always_show_image(True)` fixed Wayland without regressing X11.

**Fix, part 3 - icon side inconsistent between platforms**: once icons were visible everywhere, X11
showed them on the left and Wayland on the right - inconsistent with each other and with the
destination picker (left on both platforms). First attempt: force `Gtk.TextDirection.RTL` on every
item to make X11 match Wayland's right side instead. This was wrong and confirmed live to be wrong -
it broke icon display entirely on Wayland. RTL evidently reorders `GtkImageMenuItem`'s internal
image+label children, not just their visual rendering, and the DBusMenu exporter's own icon-extraction
logic is order-dependent, so flipping direction on the exported menu broke serialization. Reverted
immediately.

direflail's actual ask, once the platforms were correctly compared side by side (not the initial
mixed-up screenshot pairing): both platforms *left*, matching the destination picker. Wayland's right
side is `ubuntu-appindicators@ubuntu.com`'s own `dbusMenu.js` hard-coding `xAlign:
Clutter.ActorAlign.END` for every menu item's icon (confirmed by reading its source) - no DBusMenu
property exists for a client to override this, so it's not fixable from Orcshot's code, full stop.

X11's side turned out to be fixable, but not obviously so. Nothing in this codebase was setting
`GtkImageMenuItem`'s text direction, yet isolated reproductions of the exact same widget code (a bare
`Gtk.StatusIcon` + `Gtk.ImageMenuItem` + `menu.popup()`, run standalone, run from the app's own venv,
run with `GTK3_MODULES=xapp-gtk3-module` set to match the live session) all rendered icons on the
*left* - contradicting the real running app, which direflail confirmed by photo was showing icons on
the *right* on X11/Mint. Dead ends checked and ruled out: the active theme
(`Mint-Y-Dark-Blue`)'s CSS has no `ImageMenuItem`- or direction-specific rules; `xapp-gtk3-module`
(present in the real session's `GTK3_MODULES`, absent from the isolated tests) only forces window
*icons* (`gtk_window_set_icon`), confirmed by reading its exported symbols - nothing menu-related;
attaching a debugger to the live process to read its actual resolved direction was blocked by
`ptrace_scope` (would need root, not pursued). The exact mechanism behind the live divergence was never
positively identified. What *is* true regardless: `GtkImageMenuItem`'s icon side is governed by
`gtk_widget_get_direction()` (confirmed in GTK's own source), X11's tray menu is a genuine local
`Gtk.Menu` never exported anywhere (unlike Wayland's), so explicitly forcing `Gtk.TextDirection.LTR`
on it is safe regardless of *why* the live default was resolving differently - it's the opposite change
from the one that broke Wayland, and it's scoped to the `XDG_SESSION_TYPE != "wayland"` branch only, so
it cannot touch the DBusMenu-exported path at all. Verified live: icons moved to the left on X11/Mint,
confirmed by direflail.

**Final state at the time**: icons on every tray-menu item, left-aligned on X11 (matching the
destination picker). Wayland kept its right-aligned icons, believed to be a permanent platform
difference not worth chasing further - **superseded the same day**, see the next section: the
Wayland tray menu was rearchitected entirely rather than left as a known limitation.

## Tray menu rearchitected as a Shell-native panel button (task #137 follow-up, complete 2026-08-15)

direflail pushed back on accepting Wayland's right-aligned icons as permanent (see the previous
section's "not a bug to keep chasing" - direflail: "is the extension really the best way for
wayland?" then, once scoped, "build it right. we don't know who's going to run this or what theme
they'll use"). What follows is a real architectural change, not a bigger version of the same fix.

**Why AppIndicator3 couldn't be fixed in place**: the Wayland tray icon (`AyatanaAppIndicator3.
Indicator.set_menu()`) hands the whole menu over to `ubuntu-appindicators@ubuntu.com`, a *different*,
third-party Shell extension, which reconstructs it with its own JS/Clutter widgets and hard-codes
right-aligned icons in its own `dbusMenu.js` (`xAlign: Clutter.ActorAlign.END`, confirmed by reading
its source) - no DBusMenu property exists for a client to override that. Nothing on Orcshot's side of
that protocol can change it.

**The fix**: move the tray icon itself into `orcshot-clipboard@orcshot.org` (this project's own,
already-installed Shell extension, used since task #77/#133 for the Wayland capture flow) as a real
`PanelMenu.Button` with GNOME Shell's own `PopupMenu`/`PopupBaseMenuItem` widgets - the same class of
fix task #133 already used for the destination picker, applied to the tray icon too. `app.py` still
owns every capture-mode action; the Shell-side button reaches them via `Gio.DBusActionGroup`, which
works with zero new D-Bus interface code on the Python side - `GApplication` already auto-exports its
registered actions at `/org/orcshot/Orcshot` (`APPLICATION_ID` with `.` → `/`) over the standard
`org.gtk.Actions` interface, since this app is already a registered `Gio.Application` with a fixed
`application_id`. `app.py` gained `_tray_action_handlers()`/`_register_tray_actions()` (one shared
dict of the five capture-mode closures, reused by both the local `Gtk.Menu` and the new GActions -
not duplicated) and `_check_shell_extension_health()` (below).

**AppIndicator3 stays as a fallback, deliberately** - `_build_tray_icon()` only skips it when
`gnome_region_select.shell_tray_button_active()` (a real `HasTrayButton` D-Bus probe, not just
`is_available()`'s `Ping()`) confirms the Shell's own button actually exists. Extension-not-installed,
not-yet-enabled (first boot before a relogin), Shell-version skew, and the user disabling extensions
are all real, ordinary states, not edge cases to shrug off - keeping a working fallback for them cost
nothing since the code already existed.

**Staleness and failure surfacing (`_check_shell_extension_health`, called from `do_startup`)** - a
real gap direflail flagged before this was scoped: GNOME Shell caches an extension's loaded JS module
for the entire login session (see `gnome_extension_setup.py`'s own docstring) - a package upgrade that
changes `extension.js` leaves an already-running Shell serving the *old* module, `Ping()` included,
until the user logs out and back in. First-run setup already told a *new* user this ("Both require
logging out and back in to take effect.") but nothing told an *upgrading* one. `extension.js` gained a
fourth D-Bus interface, `OrcshotVersion.GetApiVersion()`, returning a constant (`API_VERSION`, bump
alongside any future D-Bus contract change) that `gnome_clipboard.get_live_api_version()` compares
against `EXPECTED_API_VERSION`; a live version below expected triggers a real desktop notification
("...needs a restart..."), reusing the `_notify()` helper task #103's update-check already
established rather than a new mechanism. Separately, `OrcshotTray.HasTrayButton()`/
`GetTrayButtonError()` let Python tell "extension not running" apart from "running, but its own panel-
button construction threw" (caught in `enable()` specifically so a bug there can't take the whole
extension - and the real capture flow it also backs - down with it) - the latter surfaces the actual
JS error/stack in a second notification, not a silently missing tray icon.

**Icon alignment, actually fixed this time**: `PopupMenu.PopupImageMenuItem` adds its `St.Icon` as the
*first* child, before the label (confirmed by reading GNOME Shell's own `js/ui/popupMenu.js`, gnome-
shell 50 branch) - a structurally different construction from `ubuntu-appindicators`' bespoke
reimplementation, which appends its icon *after* an `x_expand`'d label. Left-aligned by construction,
no direction hack needed this time.

**Icon color - the real saga, worth recording in full so it isn't re-chased**: direflail's screenshots
went through, in order - icons invisible against a light-themed menu background (assumed dark, from
older destination-picker screenshots); a `-st-icon-style: regular` CSS override that made it *worse*
(disabled the theme-adaptive recoloring symbolic icon *names* like `preferences-system-symbolic` get
automatically); icons visible only on hover (the row highlight gave a white icon just enough contrast
to read - the clue that finally pinned down "the icon loads fine, the color is just wrong for this
theme"); a `-st-icon-style: symbolic` override with *zero* effect, even though a `background-color:
red` test on the same CSS class rendered correctly (proving the stylesheet loads and the class
applies - `-st-icon-style` itself just doesn't do anything for a file-based `Gio.FileIcon`, evidently
governing icon-*theme-name* lookup variant selection, not arbitrary pixel recoloring); a pragmatic
hardcoded-dark-color PNG (works only for light themes, direflail explicitly rejected this: "we don't
know who's going to run this or what theme they'll use"). Along the way, a real, separate bug surfaced
and got fixed regardless of the color question: `PopupImageMenuItem`'s constructor routes its icon
through `setIcon()`, which branches on `GObject.type_is_a(icon, Gio.Icon)` - `Gio.Icon` is an
interface, and this check doesn't recognize a `Gio.FileIcon` as satisfying it in this GJS/Shell
version, so icons went through the *wrong* branch (`icon_name = <a GObject>`) and rendered nothing at
all until `item._icon.gicon = ...` was set directly, bypassing `setIcon()` entirely (the panel
button's own top-bar logo, built the same direct way, had worked correctly the whole time - the
comparison that caught this).

**Final fix**: draw the five icons live with Cairo inside an `St.DrawingArea`'s own `'repaint'` signal
handler, reading `area.get_theme_node().get_foreground_color()` *at paint time* - the exact color the
row's own label text uses, so it's correct under any theme, not a light/dark guess. `St.DrawingArea`
was already a proven pattern in this same file (the region-select magnifier loupe/crosshair use it);
the geometry is a hand-ported copy of `icons.py`'s own `_capture_region_icon`/
`_capture_full_screen_icon`/`_window_frame_icon`/`_capture_repeat_icon` (same coordinates, GJS's
Cairo binding uses camelCase method names - `setLineWidth`/`moveTo` - where PyGObject's uses
snake_case, a real binding difference, not a typo) - kept in sync by hand, same reasoning as
[[feedback-shape-serialization-sync]]. `PopupImageMenuItem` can't host an arbitrary actor, so these
five items are built manually from `PopupMenu.PopupBaseMenuItem` instead (`add_child()` the
`St.DrawingArea` and an `St.Label`, set `label_actor` - the exact pattern `PopupMenuItem` itself uses,
confirmed by reading it). One more real bug here too: `St.DrawingArea` rendered *nothing at all*,
even on hover, with zero errors - `icon-size` (the CSS property sizing `St.Icon`) turned out to be
`St.Icon`-specific and does nothing for a generic `St.DrawingArea`, leaving it at zero allocated size;
fixed with an explicit `width`/`height` in pixels instead of relying on that CSS property.
`SetRepeatAvailable` calls `queue_repaint()` after `setSensitive()` so the disabled/enabled color
change (`get_foreground_color()` already returns the dimmer `:insensitive` shade automatically) is
actually redrawn, not just set.

**Verified live** (Ubuntu 26.04/GNOME Shell 50.1): icons render correctly colored, correctly shaped,
left-aligned, both capture and window-picker capture confirmed working end-to-end through the new
GAction path, "Repeat Last Region" correctly dims/undims and its icon redraws to match. direflail's
own words once it finally worked: "finally."

## Multiple editor windows allowed at once (task #138, complete 2026-08-15)

Reported live by direflail: `File > Open` on a saved `.orcshot` file while a capture's editor was
already open just opened a second, independent editor window - surprising, since starting a *new
capture* while an editor was open did the opposite (`app.py`'s `_block_if_editor_open`, added earlier
for task #14/#15's original hotkey flow, silently refused and focused the existing editor instead).

**Checked against the real Windows source before picking a direction** (this project's own standing
rule - see [[feedback-faithful-port-verification]]): there is no "one editor at a time" limit in
Windows Greenshot at all. Both a fresh capture and opening a saved `.greenshot` file route through the
same method, `EditorDestination.ExportCapture` (`EditorDestination.cs:89-152`), which by default
(`ReuseEditor` defaults to `false`, `IEditorConfiguration.cs:73-75`) always constructs a fresh,
independent `ImageEditorForm` (`EditorDestination.cs:112`) - multiple editor windows are meant to
coexist freely; a static `EditorList`/`Editors` collection (`ImageEditorForm.cs:78`) just tracks them
for cross-editor operations, with no cap. The only reuse behavior is the opt-in "Reuse already open
editor" setting (off by default), which injects into the first *unmodified* open editor rather than
enforcing a limit. So `File > Open`'s behavior was actually the faithful one; the capture-side block
was the divergence.

**Why the block existed**: added as a workaround for a real report - triggering a hotkey while an
editor was open produced a confusing, silent no-op (the capture overlay/destination-picker flow never
appeared, though the app didn't hang). The suspected cause, per the block's own docstring, was never
actually confirmed: "Cinnamon/Muffin focus-stealing prevention likely keeps the newly-created
override-redirect overlay from actually receiving input while the editor already has focus" - a guess,
not a diagnosis. Root-caused today by looking at the overlay's actual input-acquisition code
(`ui/region_select.py`): it's a `Gtk.WindowType.POPUP` (X11 override-redirect), and acquires input via
an explicit `Gdk.Seat` grab scoped to `KEYBOARD` capabilities only (not `POINTER`), called with no real
event timestamp - a real, independently-plausible weak point, unrelated to the focus-stealing guess.

**Live-tested rather than assumed**: with the block temporarily disabled, opened one editor, kept it
focused, triggered a second capture, and completed a real drag-select over the already-focused editor -
worked correctly, confirmed by direflail ("it worked fine"). The original bug did not reproduce.
Whether it was fixed incidentally by later changes (e.g. task #134's tray-menu-close-race `_defer`
fix, which changed capture-start timing) or was misdiagnosed from the start wasn't pinned down further
- not worth chasing given it doesn't reproduce and matching Windows' actual default behavior is the
right direction regardless.

**Fix**: removed `_block_if_editor_open()` and its five call sites in `app.py` entirely (`start_region_
capture`/`start_full_screen_capture`/`start_active_window_capture`/`start_window_picker`/`start_last_
region_capture`). `self._open_editors`/`register_editor_window`/`unregister_editor_window` stay -
`show_preferences()` still uses the topmost open editor as Preferences' transient parent, and now
correctly tracks more than one.

## Modal-dialog-vs-capture-overlay regression (task #138 follow-up, complete 2026-08-15)

Removing `_block_if_editor_open()` (above) opened a narrower but real hole: reported live by
direflail, while `EditorWindow._on_delete_event`'s "save changes?" prompt (a `Gtk.Dialog.run()`) was
open, triggering a new capture still ran - the screen dimmed and the crosshair cursor appeared, but no
click ever registered, and the overlay silently vanished on the next click with no capture and no error.

Root cause: `ui/region_select.py`'s capture overlay only ever grabs *keyboard* input via `Gdk.Seat`
(see that module's own comment) - it relies on plain, ungrabbed button events for its drag-select, which
normally works fine. `Gtk.Dialog.run()` holds its own process-wide GTK grab for as long as it's open
(used by the save prompt, and 26 other `Gtk.Dialog` call sites in `editor_window.py` alone -
Preferences, Save As, text-entry dialogs, etc.), which intercepts that same pointer input first, so the
overlay never sees the click.

**Fix**: added `_block_if_modal_dialog_open()` in `app.py`, wired into the same five capture-start
methods `_block_if_editor_open()` used to guard. Checks `Gtk.grab_get_current()` - `None` means nothing
is actually grabbing, so the capture proceeds; otherwise it presents the grabbing dialog's toplevel
instead of starting a capture that can never receive input. Deliberately narrower than the removed
`_block_if_editor_open()`: that blocked on *any* open editor regardless of whether it was actually
intercepting input, which is exactly the over-broad behavior task #138 removed. This only blocks when
something concrete is grabbing right now, so multiple editor windows keep coexisting freely - only an
active modal dialog blocks a new capture.

## Fresh captures start "modified" even with zero edits (complete 2026-08-15)

Reported live by direflail: opening a fresh capture in the editor and closing it again *without making
any changes* produced no "save changes?" prompt at all - expected, since nothing was touched. But the
user's own stated intent was broader: "the only time that shouldn't come up is if the last thing you
did was save (or save as)" - i.e. a never-yet-saved capture should always prompt, edited or not, since
nothing has been exported yet.

Checked against the real Windows source before fixing (per [[feedback-faithful-port-verification]]):
`Surface.Modified` defaults `true` at construction (`Surface.cs:328`), and gets explicitly reasserted
`true` when a fresh capture's editor opens - `ImageEditorForm.cs:186`'s
`surface.Modified = !outputMade` - regardless of whether the user has edited anything. Windows'
`Modified` is semantically "not yet exported," not "user touched something." Orcshot's own
`is_modified` (`ui/editor_window.py`) only tracked the latter (`undo_redo.generation !=
_saved_generation`, both starting at `0`) - a real divergence, confirmed by the live report before
fixing, not a guess.

**Fix**: added an `already_saved: bool = False` parameter to `EditorWindow.__init__`. When `False` (the
default - used for every fresh capture via `destination_picker.py`'s `EditorWindow(image)` call),
`_saved_generation` starts at `-1`, a sentinel `undo_redo.generation` (which itself always starts at
`0`) can never equal on its own - so `is_modified` is `True` from construction, matching Windows, until
an actual save happens. When `True` (`open_orcshot_file_in_new_window`, task #123/#129 - opening an
*existing* `.orcshot` file whose on-disk content already matches what's loaded), `_saved_generation`
starts equal to `generation` instead, correctly unchanged from before this fix - closing an unedited
reopened file still doesn't prompt. Live-verified both cases: a fresh, untouched capture now prompts to
save on close; an untouched reopened `.orcshot` file still doesn't.

## Tray icon "Open File..." (task #140, complete 2026-08-15)

direflail noted that opening a saved `.orcshot` file was "a really out of the way path" - it required
already having an editor open (via its own `File > Open`) or going through the file manager; there was
no way to open one directly from the tray, the app's primary entry point when no editor is open yet.

Checked against the real Windows source first: `contextmenu_openfile` is a real, always-present item in
Windows' own tray context menu (`MainForm.Designer.cs:92`), sitting in the real `AddRange` order right
after the capture items and "capture clipboard" (`MainForm.Designer.cs:83-103`), before the settings
section - this port had no equivalent at all. (Windows also has a separate, opt-in
`ClickActions.OPEN_EMPTY_EDITOR` single-click behavior, `MainForm.cs:1277-1278` - a configurable
single-click action in Settings, not a static menu row - deliberately not ported; building the whole
configurable-click-action system for one row wasn't worth it here.)

**Fix**: extracted the existing file-chooser logic out of `EditorWindow._do_open` into a new shared
module-level function, `choose_and_open_orcshot_file(transient_for=None)` in `ui/editor_window.py`, so
both `File > Open` and the new tray entry point get identical dialog behavior and error handling.
Added `OrcshotApplication.open_file_from_tray()` in `app.py` (same topmost-open-editor-as-transient-
parent reasoning as `show_preferences`), a `tray-open-file` GAction, and an "Open File..." row in both
the X11 `AppIndicator3` menu (`_build_tray_menu`) and the Wayland Shell-native panel button's own menu
(`extension.js`'s `_buildTrayButton`), each activating the same GAction.

Verified end-to-end on both platforms: X11 confirmed live by direflail ("works"). Wayland confirmed by
activating `tray-open-file` directly over D-Bus (`org.gtk.Actions.Activate`) and checking, via the
bundled window-calls extension, that a real GTK "Open" file-chooser window appeared - confirms the full
chain (Shell extension menu → GAction → Python handler → dialog) without needing to view any live
capture content.

## Shared vector-icon geometry for the 5 tray icons (task #143, complete 2026-08-16)

The task #137 follow-up section above ends with the 5 tray-menu capture-mode icons hand-ported into
`extension.js` as a second, independent copy of `icons.py`'s own drawing logic - "kept in sync by hand"
was an accepted tradeoff at the time, not a solved problem. direflail asked directly why the two
couldn't just match exactly, and after walking through *why* they're separate processes (GJS running
inside gnome-shell itself, no shared interpreter with Orcshot's own Python process - the same
constraint discussed in that section, restated more plainly), landed on the real distinction: Python
and GJS can never share *code*, but they can share *data*, since any process on the same machine can
read the same file off disk regardless of language.

**Fix**: `icon_geometry.json` (installed alongside `extension.js`/`metadata.json`, read from
`RESOURCES_DIR / "gnome-shell-extensions" / "orcshot-clipboard@orcshot.org" / "icon_geometry.json"` on
the Python side and `this.path` on the GJS side) holds each of the 5 icons as a flat list of drawing
ops - `rectangle`/`rounded_rectangle`/`arc`/`move_to`/`line_to`/`set_line_width`/`set_dash`/
`set_line_join`/`stroke` - with position/size values normalized to 0..1 (fractions of whatever pixel
size the icon renders at) and style values (line width, dash pattern, `rounded_rectangle`'s corner
radius) left as absolute pixels, matching how those were always fixed constants in the original
hand-drawn code regardless of icon size. `icons.py`'s `_render_icon_geometry` and `extension.js`'s
`_renderIconGeometry` are now two small, mechanical interpreters - "loop over ops, dispatch each to
this platform's own Cairo binding" - replacing what used to be 10 separate hand-drawn functions (5
icons × 2 languages) with 1 shared data file + 2 thin interpreters. Any future geometry change happens
once, in the JSON; both platforms pick it up automatically, with nothing left to drift by hand.

The exact normalized coordinates were generated programmatically from the original hand-drawn
functions' own formulas (a small one-off script evaluating each icon's real math - `ICON_SIZE`/
`_MARGIN`-relative expressions, including the repeat-icon's trig for its arrow head) rather than
transcribed by hand, specifically to avoid a transcription error silently drifting the new geometry
from the old.

**Verified two ways before deleting the original functions**: (1) a pixel-diff comparing the old
hand-drawn Python functions against the new geometry-driven `capture_mode_icon_image` - byte-identical
output for all 5 icons; (2) a standalone GJS script (outside the Shell extension entirely, using
`imports.gi.cairo` directly) running the exact same op-interpretation logic against the same JSON file,
with its rendered output pulled back and compared pixel-for-pixel against Python's - also byte-identical
for all 5 icons, on both the host machine and the Ubuntu 26.04 VM. This is a stronger guarantee than the
original hand-ported version ever had: the two platforms aren't just *intended* to match, they're
now provably drawing from the same source data and produce provably identical rasters.

## Duplicate tray icon on delayed extension activation (task #144, complete 2026-08-16)

Live-observed on the Ubuntu 26.04 VM (screenshot: two identical Orcshot tray icons side by side) while
re-testing the Shell extension mid-session. Root cause: `_build_tray_icon`'s AppIndicator3-vs-None
decision runs once, synchronously, in `do_startup` - *before* `maybe_run_first_run_setup` even runs.
For a brand-new Wayland user who says yes to GNOME-native capture during that wizard,
`enable_extension` (`first_run_setup.py`) flips `orcshot-clipboard@orcshot.org` on *after* the tray
decision was already made using the extension's not-yet-enabled state - both the AppIndicator3
fallback built moments earlier and the extension's own now-active Shell-native panel button end up on
screen at once, with nothing ever tearing the first one down. Not purely a VM-testing artifact: this
is a real path a genuine first-time user can hit, not just something specific to this session's manual
extension toggling.

**Fix**: `_recheck_tray_icon_after_extension_change` (`app.py`), called once right after
`maybe_run_first_run_setup` returns. Polls `shell_tray_button_active()` up to 6 times, 500ms apart
(~3s total) rather than checking exactly once more - `enable_extension` only flips a GSettings key,
and GNOME Shell activates the extension in response to that asynchronously, not necessarily by the
time the wizard's own blocking `dialog.run()` has already returned. Tears the AppIndicator3 fallback
down (`set_status(IndicatorStatus.PASSIVE)`) the moment the extension comes up; gives up silently if
it never does (`_check_shell_extension_health`, called earlier in the same `do_startup`, already
covers surfacing that outcome to the user - nothing more to add here for it). Deliberately scoped to
this one concrete, common trigger (every new Wayland user's own first-run wizard) rather than a
general poll for every possible later way the extension could become active - e.g. toggling it by
hand in the GNOME Extensions app while Orcshot happens to already be running is real but much rarer.

**Verified with an isolated harness** rather than a full VM first-run-setup re-run: the real method,
bound to a fake `self` with a stand-in indicator object (`set_status` calls recorded) and
`shell_tray_button_active` mocked to flip from `False` to `True` after a controlled number of calls,
pumping the real `GLib` main loop. Covers three cases - activates on the very first poll, activates
after a couple of delayed polls, and never activates at all - the last one confirming the fallback is
correctly left alone (not torn down) rather than leaving the user with no tray icon at all if the
extension genuinely never comes up. Not yet re-verified by actually running first-run setup fresh
end-to-end on a VM (the concrete scenario that surfaced this) - flagged as a known gap, not silently
skipped.

## Every icon in the app is now hand-drawn, none loaded from the system icon theme (task #146, complete 2026-08-16)

Following directly from task #143 above, direflail asked why *only* the 5 tray icons got the shared-
geometry treatment when the app still had 30 other icons (`edit-undo-symbolic`, `document-save-
symbolic`, `preferences-system-symbolic`, and so on) loaded from the system's installed icon theme via
`Gtk.Image.new_from_icon_name`/`PopupImageMenuItem`. Those guarantee a consistent *name*, not a
consistent *look* - this project's own two real test machines (Mint's default Mint-Y theme, Ubuntu's
default Yaru) render the same name differently, the same root problem the 5 tray icons had for a
different reason (two languages instead of two themes). direflail's own words: "I don't want default
icon sets. they're going to be different between platforms and I don't want that... every icon in the
wayland version [must] look like the x11 version, no exceptions."

**Scope**: every stock icon name used anywhere in the app - `editor_window.py`'s menu bar, action
toolbar, and crop confirm/cancel buttons; `app.py`'s X11 tray menu; and `extension.js`'s Wayland tray
menu *and* its own separate destination-picker popup (`pickDestinationAsync`, which had quietly been
using stock names this whole time even though `icons.py`'s own `destination_icon_image` gave the X11
destination picker hand-drawn icons back in task #96 - a second real instance of the same X11/Wayland
mismatch, found while auditing for this task, not previously known). 30 new names in total, plus
reusing the 5 that already had a hand-drawn equivalent (`_save_icon`/`_print_icon`/`_edit_icon`/
`_clipboard_icon`, retired in favor of the shared geometry entries they were ported into).

**Format extended**: `_render_icon_geometry`/`_renderIconGeometry` gained three ops the original 5
icons never needed - `fill`, `set_line_cap`, `close_path` - required to faithfully port
`_save_icon`'s filled floppy-disk notch and `_edit_icon`'s filled pencil-tip triangle into the shared
format without changing how either looks.

**Geometry generated, not hand-typed**: a one-off Python script defines each new icon using the exact
same method-call style as the original hand-drawn functions (`rectangle`/`arc`/`move_to`/`line_to`/
`fill`/etc. at real `ICON_SIZE`-unit coordinates) against a small recorder object standing in for a
real `cairo.Context`, which captures each call as a normalized op automatically - the same reasoning
as task #143's own extraction script (avoid hand-computing/transcribing 30 icons' worth of fractions
by hand, a real source of silent drift risk). Visually reviewed via a rendered montage before wiring
anything up (caught nothing needing a redesign - all 30 read clearly at real icon size).

**Wiring collapsed to a few shared call sites, not ~40 individual ones**: every menu/toolbar icon in
this app already funneled through a small number of shared builder helpers (`menu_item`/`add_item`/
`add_submenu` in `editor_window.py`'s `_build_menu_bar`, a second `add` in `_populate_zoom_menu`,
`add_button` in `_build_action_toolbar`, `menu_item` in `app.py`'s tray menu) - each one only needed
its single `Gtk.Image.new_from_icon_name(icon_name, ...)` line swapped for `icons.py`'s new
`stock_icon_image(icon_name, icon_color, size=16)`, with `icon_name`/call-site *strings* completely
unchanged (they're also the `icon_geometry.json` keys, so this was a pure substitution). Same idea on
the Wayland side: a new `_buildDrawnMenuItem(iconGeometry, geometryKey, label)` replaced both
`_buildTrayButton`'s inline capture-mode-item construction and every remaining `PopupImageMenuItem`
call, in both `_buildTrayButton` and `pickDestinationAsync`.

**`icon_geometry.json` reading made available outside the Extension class**: `pickDestinationAsync` is
a plain module-level function (not an `Extension` instance method), so it can't reach `this.path` the
way `_buildTrayButton` used to. Switched the geometry loader to resolve the extension's own install
directory via `import.meta.url` (`GLib.filename_from_uri` + `GLib.path_get_dirname`) instead - live-
confirmed with `gjs -m` against a real `.mjs` file on the actual GJS version this Shell ships, since
`import.meta` support isn't universal across every GJS version. Works identically from any scope in
the module, so this is now a plain function, not a method - no instance needed to load geometry at all.

**Verified**: every one of the 35 shared geometry entries (5 original tray icons + 30 new) renders
without error via the Python interpreter; a standalone GJS script (no `gnome-shell` process involved,
just `imports.gi.cairo` directly) running the identical op-interpretation logic against the identical
JSON file produced byte-identical rasters to Python's own output, confirmed for all 35, on both the
host machine and the Ubuntu 26.04 VM. The 5 icons ported from existing hand-drawn functions
(`edit-copy-symbolic`/`document-save-symbolic`/`document-save-as-symbolic`/`applications-graphics-
symbolic`/`document-print-symbolic`) were separately pixel-diffed against their original
`_clipboard_icon`/`_save_icon`/`_edit_icon`/`_print_icon` implementations before those functions were
deleted, confirming the port preserved the exact existing, already-approved (task #96) look. Full test
suite passes throughout. Not yet visually confirmed live by direflail on the actual VM screen (the
Shell-side changes need a logout/login to take effect, per the extension-reload-caching limitation
noted elsewhere in this document) - the pixel-level verification above is strong evidence, but isn't a
substitute for an actual look.

**Correction, same day**: the 30 new icons above were originally *hand-designed* fresh - reasonable-
looking line-art guesses at what each action conventionally looks like, not extracted from anything.
direflail caught a real miss live (Preferences rendered as a plain gear; the real icon everywhere on
this system is a crossed wrench and screwdriver) and clarified what "look like the x11 version" had
actually meant from the start: not a new interpretation of these icons, the *exact* geometry the real
system icon theme was already rendering before this task ever touched them.

**Fix**: replaced all 30 hand-designed geometries with real ones extracted directly from
`/usr/share/icons/Adwaita/symbolic/.../<name>.svg` - the actual files these icon names were resolving
to. Required a real (if small) SVG path parser: SVG's path-data grammar (`M`/`L`/`H`/`V`/`C`/`S`/`A`/`Z`,
absolute and relative, implicit command repetition, and one real gotcha - `A`'s two flag arguments are
single digits allowed to run together with no separator, e.g. `A5.881 5.881 0 001.437 4.75` means
flags `0`,`0` then `x=1.437`, not one number `001.437`) converted into this project's own op format.
One new op, `curve_to` (cubic Bezier - `ctx.curve_to`/`cr.curveTo`, both already native to their
respective Cairo bindings), plus a standard elliptical-arc-to-Bezier conversion (SVG spec Appendix F.6
endpoint-to-center parameterization, split into <=90° segments - Cairo has no native ellipse-arc
primitive either, so this is what every real SVG-to-Cairo renderer already does internally) for the one
icon (`help-browser-symbolic`) whose real SVG actually uses an elliptical arc.

**Re-verified the same way**: visual montage review before wiring anything up (this time genuinely
recognizable as the real, familiar GNOME icon set - Preferences is now the correct crossed tools,
`edit-select-all-symbolic` turned out to be a dot-grid pattern in real Adwaita rather than the corner
brackets guessed the first time around, `help-browser-symbolic` a life-preserver rather than a plain
question mark); all 35 shared geometries (5 original + 30, now real) still produce byte-identical
rasters between the Python and GJS interpreters, arc-derived icon included - confirming the arc-to-
Bezier math is correct, not just plausible-looking, since two independent interpreters agree on every
pixel from the same source data.

## Tray menu greys out when Python isn't running to receive clicks (task #147, complete 2026-08-16)

Live-hit by direflail right after a logout/login: the Wayland tray menu opened and looked completely
normal, but clicking anything - a capture mode, Preferences, Quit - did nothing. Root cause: every
item's `_activateTrayAction` fires its GAction over D-Bus and is deliberately fire-and-forget (no
return value, nothing useful to do if Orcshot isn't running) - if Python hasn't been launched yet this
session (no autostart is wired up on this dev/test setup; a real installed system with "launch on
startup" enabled wouldn't normally hit this window at all), the Shell-native panel button still builds
and opens fine since it lives inside gnome-shell itself, entirely independent of whether Python exists.

direflail asked three direct questions: (1) "I thought we had checks for that now?" - `app.py`'s
`_check_shell_extension_health` only checks Shell-extension health, and can only ever run *from* a live
Python process - there was no way for it to detect its *own* absence, and no code at all on the Shell
side watching for Python specifically. (2) "should we grey the orcshot logo out until it IS loaded?" -
yes, exactly the right fix. (3) explicit ask to fix it.

**Fix**: `extension.js` watches `org.orcshot.Orcshot`'s D-Bus name via `Gio.bus_watch_name` (reacts in
real time to the name appearing/vanishing, not a poll - confirmed live via `gjs -m` that both callback
signatures match GIO's documented `(connection, name[, name_owner])`). Starts pessimistic (every gated
item and the top-bar logo icon begin insensitive/dimmed the moment the tray button is built, before the
watch's first callback has even had a chance to fire) rather than assuming available - a false "looks
fine" was the entire bug. `_setAppAvailable(available)` toggles every capture-mode/Open-File/
Preferences/Quit item's sensitivity plus the logo's `opacity`; Repeat Last Region combines this with
its own pre-existing `SetRepeatAvailable` gate (both booleans now stored and recomputed together, so a
stale `SetRepeatAvailable` call just before Python vanishes can't leave it wrongly clickable).

**Bonus, direflail's own suggestion mid-fix**: "might want to time how long it takes that thing to
load... might help debug" - `enable()` captures `GLib.get_monotonic_time()` (µs, immune to wall-clock/
timezone changes - the correct clock for measuring an elapsed duration, not a timestamp), and the
watcher's appeared callback logs the elapsed seconds since `enable()` to the journal every time Python
successfully appears on the bus, for exactly this kind of debugging going forward.

Syntax-checked and structurally reviewed; not yet visually confirmed live on the VM screen - the JS
change needs another logout/login to take effect, per this document's own extension-reload-caching note.

## Reliable clipboard support is no longer an opt-in checkbox (task #145 follow-up, 2026-08-17)

While verifying task #144 with a real `.deb` install and a genuinely fresh first-run-setup (extension
disabled beforehand, GNOME Shell's own module cache confirmed clear via a full logout/login - see this
document's own extension-reload-caching note), the "Enable reliable 'Copy to Clipboard' support"
checkbox came out of the wizard unchecked despite defaulting to checked, and the extension stayed
disabled. Initially read as the user simply having unchecked it - but this project already has an
open, not-yet-root-caused finding from 2026-08-15 (see the "Real, separate bug found during the .deb
reinstall on the rebuilt VM" section above, task #38's own verification log) that this exact checkbox's
`enable_extension` call sometimes doesn't persist the gsettings write at all, confirmed independently
of any stale-session-bus explanation. Whether today's instance was a deliberate uncheck or that same
unresolved persistence bug wasn't distinguished - moot for what happened next, but worth reading
together if that older bug ever gets chased down, since this section may be its true root cause working
as designed (nothing to fail to persist if there's no longer a checkbox to leave unchecked).

direflail, on why the checkbox shouldn't exist as a choice at all: "we're not installing anything
malicious, and we're trying to develop responsibly... 99% of the users installing this are neither
going to know nor care that the extension exists - only that the program works... it's ALWAYS going to
be enabled, otherwise the program won't work. I wouldn't even have it set up as an option in the source
code... why else would you install this program if you didn't want clipboard support? it's a screenshot
app." The earlier framing in this codebase (and in conversation) treated enabling a Shell extension as
a bigger trust decision than installing the package that ships it - direflail pushed back on that
directly: the real trust decision already happened at `sudo dpkg -i`, and gating one first-party
feature of that same already-approved package behind a second checkbox doesn't protect anyone who
wasn't already going to check it.

**Change**: `ui/first_run_setup.py` no longer builds a `clipboard_check` `Gtk.CheckButton` at all.
`enable_extension(settings_backend, CLIPBOARD_EXTENSION_UUID)` is now called unconditionally whenever
the dialog completes with OK on a session where it applies (`is_gnome_wayland`), the same way autostart
and hotkeys aren't offered as individually-skippable core-functionality choices either. `window_calls_
check` (the "Capture Window" mode extension) deliberately keeps its own checkbox - unlike
`orcshot-clipboard@orcshot.org` (wholly original code for this project, see `extension.js`'s own header
comment), `window-calls@domandoman.xyz` is a bundled *third-party* patched fork (see
[[reference_window_calls_extension]] equivalent in REQUIREMENTS - the "Bundled GNOME extension"
section), a genuinely different provenance question rather than a trust-level one. No documentation
mention added either, direflail's own reasoning: a doc callout is warranted for code sourced from other
projects, not for code written specifically for this one - anyone who cares can already read the source.

Not yet re-verified live after this change - the very next step is exactly the same real `.deb`-install
+ fresh-first-run-setup cycle task #145 was already mid-way through, rebuilt with this change, to
confirm the extension now activates unconditionally and task #144's teardown fix still fires correctly
with no checkbox involved at all.

**Update, same day: `window_calls_check` removed too, and the "requires logging out" warning turned
out to be simply wrong, not a real limitation.** direflail pushed further on the remaining checkbox:
"if the user isn't going to be able to use the program correctly upon install without a login... we
either need to fix it completely or patch it... I don't see any other screenshot programs asking for a
restart." That's the right bar - checked whether a restart is actually required, rather than accepting
it as a given the way the original dialog copy implied.

It isn't. `gnome_clipboard.is_available()` is a live `Ping()` D-Bus probe, called fresh on *every single
capture attempt* - not a value cached once at startup the way `_build_tray_icon`'s AppIndicator3-vs-None
decision was (task #144's actual bug). `gnome_window_picker.is_available()` and `gnome_region_select.
is_available()` both just delegate to that same live probe. Combined with GNOME Shell activating a
freshly-enabled extension in well under a second (measured live earlier this session: ~0.3s), a
first-time user's *actual* first capture attempt - which happens some real seconds after finishing the
dialog, not the same instant - already sees the extension as available. Even a capture attempted within
that sub-second window just falls back gracefully to the portal/invisible-window path instead of
failing. There was never a real case where the user needed to log out first; the dialog's own warning
text was simply stale, predating (or never updated to match) this live-probing architecture.

**Change**: `window_calls_check` removed the same way `clipboard_check` was - `enable_extension(...,
WINDOW_CALLS_EXTENSION_UUID)` is now unconditional too, right alongside the clipboard call, both gated
on the single `is_gnome_wayland` check. The "Requires logging out and back in to take effect." label is
gone entirely, not reworded - it wasn't accurate for either extension. `window-calls@domandoman.xyz`'s
third-party status remains documented where it already was correctly documented -
`THIRD_PARTY_NOTICES.md` and `debian/copyright` - not a new README section (direflail: doc callouts are
for code sourced from other projects, which this already covers; a first-run dialog checkbox was never
the right vehicle for that disclosure in the first place).

An earlier proposal in this same conversation - spinning up a nested `gnome-shell --devkit --wayland`
session as part of onboarding, to sidestep an assumed restart requirement - was correctly never adopted
as real product behavior; it was only ever floated as a possible dev-iteration speedup for testing
`extension.js` edits without a real logout, explicitly out of scope for what a real end user should ever
see. Worth remembering it surfaced at all: it was a well-intentioned reach for a workaround before the
actual question ("does this genuinely require a restart?") had been checked - the real fix, once
checked, needed no workaround at all.

## Portal capture exceptions crash the whole app (task #150, complete 2026-08-18)

Live-observed crash during the same #145 verification pass, unrelated to any of the checkbox/first-run
changes above: a real apport crash report from `/usr/bin/orcshot`, `orcshot.capture.wayland_portal.
PortalRequestFailed: screenshot portal returned response code 2`, with a full traceback from `app.py`'s
tray-click handler down through `region_select.py` -> `region_select_wayland.py` ->
`capture/wayland.py` -> `capture/wayland_portal.py`, completely unhandled.

Grepped the whole codebase before proposing any fix (systematic-debugging, not a guess):
`PortalRequestCancelled`/`PortalRequestFailed`/`PortalRequestTimedOut` (defined in
`capture/wayland_portal.py`) were **never caught anywhere else in this project** - zero matches outside
their own defining module. That means this wasn't specific to response code 2 at all: the completely
ordinary case of a user hitting Escape on the screenshot permission dialog
(`PortalRequestCancelled`, response code 1) would crash the app exactly the same way. This is the
portal-based fallback capture path (`capture_backend.grab()` under Wayland, used whenever
`orcshot-clipboard@orcshot.org` isn't handling the capture itself - i.e. any session before first-run
setup enables it, or where the user declines to) - a completely normal, everyday state, not a rare edge
case, so this was a real, always-reproducible crash for anyone in it.

direflail: "if the user isn't going to be able to use the program correctly upon install without a
login, then [we need a real solution]... if you recommended a subpar solution then we either need to
fix it completely or patch it" - in the course of chasing that down (see the section above), it turned
out there was no actual restart requirement to work around; investigating *that* claim is what surfaced
this crash in the first place, mid-test.

**Fix**: `OrcshotApplication._run_capture` (`app.py`), a single shared wrapper around all five
`start_*_capture` methods (region select, full screen, active window, window picker, last-region
repeat) - the one point both the tray-click path (via `_defer`) and the hotkey/CLI path
(`do_command_line`) already converge through, so one fix covers both invocation paths rather than
patching `region_select.py`/`window_picker.py`/`capture_modes.py` separately. `PortalRequestCancelled`
is swallowed silently, matching every other "user backed out of a capture" convention already in this
app (Escape on the region-select overlay or window picker); `PortalRequestFailed`/
`PortalRequestTimedOut` are surfaced via a real `_notify()` call instead of crashing, matching this
class's own existing notification pattern for other capture-adjacent failures.

**Verified with an isolated harness**, matching this project's own established pattern for GTK-adjacent
`app.py` logic (see task #144's own verification note above) rather than a full pytest suite entry -
`_run_capture` bound to a fake `self` (just a `_notify` recorder), exercised against the real exception
classes: confirmed `PortalRequestCancelled` is swallowed with no notification, `PortalRequestFailed`/
`PortalRequestTimedOut` each produce exactly one notification mentioning the underlying error and are
not re-raised, a normal (non-raising) action still runs through untouched, and - importantly - an
unrelated exception (`ValueError`) is *not* swallowed and still propagates, confirming the catch is
scoped to only the three portal exceptions rather than accidentally hiding real bugs.

**Follow-up, same day: the crash-prevention fix above wasn't the whole story - the underlying capture
was still silently failing every time from the real tray-click path, even though it worked perfectly
every time when called standalone.** direflail's report after the first rebuild: a tray-triggered
region capture's popup closed and nothing else happened - no overlay, and a subsequent drag just
produced the OS's own ordinary desktop rubber-band-select box, meaning `WaylandRegionSelect` never
actually got constructed at all, its own `capture_backend.grab()` call having failed before the
interactive overlay could show itself.

Root-caused by direct comparison rather than more guessing: `capture/wayland_portal.py`'s
`request_screenshot()` (both a hand-written standalone probe using the exact same D-Bus options, and
the real function imported and called directly, out-of-process) succeeded every single time, with no
failures across repeated calls. Only the *real* running app's own tray-click-triggered attempt failed.
That pointed straight at [[feedback_wayland_portal_reentrancy]] - already-documented project knowledge
recorded from earlier work on the eyedropper/window-picker overlays, but this codebase had one call
site that didn't yet follow it: `app.py`'s `_defer()` (the task #134 fix that yields one main-loop
iteration so a tray menu's popdown completes before its capture starts) called
`GLib.idle_add(run)` with no explicit priority - which defaults to `GLib.PRIORITY_DEFAULT_IDLE`, a
*lower* priority than `GLib.PRIORITY_DEFAULT`. `request_screenshot()` nests its own blocking
`GLib.MainLoop().run()` one level inside whatever calls it under Wayland (whenever the Shell extension
isn't handling the capture itself) - and per the existing finding, an idle-priority-deferred callback
nesting a portal call like this can be starved/preempted by other events at or above its own priority,
exactly the class of bug already seen (if not identically manifested - that earlier note describes a
full hang; here the portal backend returned a fast but wrong `response_code=2` instead, still
consistent with the callback's timing being disturbed by priority contention rather than running
cleanly).

**Fix**: `_defer()` now calls `GLib.idle_add(run, priority=GLib.PRIORITY_DEFAULT)`, matching
`eyedropper_wayland.py`'s own `_load_backdrop` call (already correctly using this priority, confirmed
by reading it - the fix this project had already learned once, just not yet applied to this second
call site). Grepped every other `GLib.idle_add` call in the codebase before considering this complete:
`editor_window.py`'s canvas resize and `app.py`'s own update-check-result handoff are unrelated to any
portal call and don't need the same treatment; `window_picker_wayland.py` only mentions `idle_add` in a
comment describing a past, abandoned approach, no live call site there at all.

Not yet re-verified live on the VM after this specific fix - the next step.

**Re-verified live, same night: the priority fix alone did NOT resolve it.** Rebuilt, reinstalled fresh,
retested via the real tray icon - direflail, verbatim: "still broken." No new crash this time (the
exception-handling fix from earlier in this same task still holds - real, confirmed progress, not
undone), but the capture itself still doesn't produce an overlay or any visible result. This was a
well-evidenced hypothesis, not a guess, but it wasn't the (or the whole) root cause - don't treat the
priority bump as *the* fix for this task; it's one real improvement layered under a problem that's
still open. Paused here for the night at direflail's request rather than continuing to guess further -
see this section's own task entry (#150) for the concrete next-session starting points (fresh crash
dump if any, re-run the standalone-vs-real-process comparison specifically post-priority-fix, and
consider whether - per [[feedback_wayland_portal_reentrancy]]'s own explicit warning - one level of
idle-priority deferral simply isn't enough here, the same way the eyedropper overlay needed more than
one fix before its own reentrancy problem was fully resolved).

**Resolved the next day, 2026-08-18: both fixes were actually correct - the "still broken" report was
against a build that hadn't picked up the priority fix cleanly, not a sign the fix itself was wrong.**
Rather than guess again, switched to direct evidence: synced the current (already-fixed) source into
the VM's dev checkout (a plain user-owned directory, no `sudo`/reinstall/logout cycle needed for a
Python-only change - unlike the GNOME Shell extension's own JS caching, a fresh Python process just
re-imports whatever's on disk) and added temporary diagnostic logging directly to `_defer`'s `run()`
and `request_screenshot()` (entry, the `Screenshot()` call, the nested `loop.run()`, and `on_response`
firing) - never committed, VM-only, removed once the answer was in hand.

Triggered a region capture via `gdbus call ... org.gtk.Actions.Activate 'tray-region'` - the exact
same `_defer(handlers["region"])` call a real click reaches, confirmed by reading both
`_register_tray_actions` (the Shell-native GAction path) and `_build_tray_menu`'s `menu_item` calls
(the local/AppIndicator3 path, `region_item = menu_item(..., lambda: _defer(handlers["region"]), ...)`)
- both converge on the identical call, so this synthetic trigger is a faithful stand-in for either real
tray, not an approximation. The log showed a complete, clean success: `request_screenshot()` entered,
`Screenshot()` returned a request handle, the nested loop ran, `on_response` fired ~340ms later with
`response_code=0` and a real screenshot URI, and `_defer.run()` returned with no exception - the
capture-and-overlay flow direflail had reported as producing nothing instead worked exactly as
designed. direflail then independently confirmed via a genuine interactive test on the real VM screen:
captured a region (the overlay from the synthetic trigger above was still sitting there, waiting - direflail
completed that same drag manually), then triggered a second, fully fresh capture via a real tray-icon
click, and confirmed the result pasted correctly into Krita - proving the clipboard delivery path
works end-to-end too, not just the screenshot grab. The diagnostic log recorded both captures
completing normally, timestamped ~2 minutes apart, matching direflail's own two-step description.

Both fixes stand as correct and complete for the actual capture crash/reentrancy problem: the exception
handling (crash prevention) and the `GLib.PRIORITY_DEFAULT` idle priority (the reentrancy fix) were the
whole story for *that specific bug*. The final real-`.deb`-install confirmation pass called for above
did happen (direflail: "let's do it") and surfaced two more, entirely separate real bugs during the
audit that followed - documented in their own sections immediately below, not folded in here, since
neither one is a capture-reentrancy problem at all.

## GioSettingsBackend created a fresh Gio.Settings per call, racing back-to-back writes to the same key (task #150 follow-up, complete 2026-08-18)

Surfaced during the post-#150 audit direflail asked for ("i'm thinking an audit of what we have... is
in order"): first-run-setup enabled `window-calls@domandoman.xyz` correctly but silently dropped
`orcshot-clipboard@orcshot.org`, even though both extensions are now enabled unconditionally,
back-to-back, in the same code path (see the checkbox-removal section above). Root cause, found by
reading rather than guessing further: `GioSettingsBackend._settings()` (`hotkey_setup.py`) called
`Gio.Settings.new(schema)` fresh on *every single* `get_strv`/`set_strv`/`get_string`/`set_string` call,
never reusing an instance. `enable_extension`'s own read-modify-write (read the current list, add the
UUID, write back) is only self-consistent if the read and write happen through the *same* `Gio.Settings`
object - its own internal cache guarantees an immediate `get_strv()` sees a `set_strv()` it just made,
with no round trip needed. Two independent instances racing on the same key have no such guarantee:
the second call's fresh read depends on dconf's own commit-then-notify cycle from the first call's
write having actually completed by then, which isn't instant. This is a real, long-standing fragility,
not new - it very likely explains the previously-unresolved 2026-08-15 finding elsewhere in this
document ("the first-run setup dialog's extension-enable checkboxes don't actually persist").

**Fix**: `GioSettingsBackend.__init__` now holds a `{(schema, path): Gio.Settings}` cache; `_settings()`
returns the cached instance if one exists for that key, constructing and caching a new one only on
first use. No behavior change for any single call - only for repeated calls addressing the same
(schema, path), which now share one object's internally-consistent view instead of racing.

**Verified live against the real gsettings backend**, not just a fake one - `enable_extension` called
twice in a row (`window-calls` then `orcshot-clipboard`, both against a single shared
`GioSettingsBackend` instance) inside a real `GLib.MainLoop`, confirmed by reading the *raw* key
(`gsettings get org.gnome.shell enabled-extensions`) rather than `gnome-extensions list --enabled` -
the latter reflects GNOME Shell's own live activation state, which lags behind the underlying setting
and misled an earlier check into looking like the fix hadn't worked. The raw key correctly contained
both UUIDs after the fix; Shell's own catch-up to actually *activate* newly-enabled extensions (as
opposed to correctly recording that they should be) is a separate, so far unexplained thread, not
something this specific fix was ever meant to address.

## configure_hotkey's name-only idempotency check never updated a stale command (task #150 follow-up, complete 2026-08-18)

Also surfaced during the same audit: four custom keybindings pointing at `PYTHONPATH=~/orcshot-verify`
(a dev checkout from 2026-08-14, since deleted) never got corrected across several first-run-setup
re-runs, even after `_default_executable()` started correctly resolving to the real installed
`/usr/bin/orcshot`. Root cause: `configure_hotkey` (`hotkey_setup.py`) checked only whether a custom
keybinding with the given *name* already existed - "Orcshot - Region Capture" and friends - and
returned immediately if so, never inspecting or correcting the *command* that name pointed at. Since a
stale entry from an old run has the exact same name a fresh run would create, every subsequent run saw
"already configured" and left the stale command untouched indefinitely. This directly undermined
`_default_executable`'s own documented purpose (prefer the installed console script over a dev-only
invocation once one exists) - the right executable was being computed correctly the whole time, nothing
downstream ever acted on a change once a same-named entry already existed.

**Fix**: `configure_hotkey` now compares the existing entry's `command` (and `binding`) against what
would be written fresh, and corrects them in place when they've drifted, rather than treating "a name
exists" as sufficient. Still returns `False` in this case (matching the existing "no *new* binding was
added" contract) - only the in-place correction is new. A differently-named existing entry is still left
completely alone, same as before.

**New test**: `test_updates_a_stale_command_under_a_matching_name` (`tests/unit/test_hotkey_setup.py`) -
seeds a `FakeSettingsBackend` with a same-named entry pointing at an old `PYTHONPATH` command, calls
`configure_hotkey` with the current executable, and asserts the command and binding get corrected in
place with no new slot created. All 40 existing hotkey tests still pass unchanged, confirming the
existing "don't disturb a differently-named binding" and "fully idempotent when nothing changed"
behaviors are untouched.

## Writing enabled-extensions was never enough - Shell needs to be told directly (task #150 follow-up, complete 2026-08-18)

The real, final root cause of this whole night's capture-doesn't-work saga, found only after the two
fixes above were verified individually correct and capture *still* silently did nothing (direflail:
"no change" - and, when told the situation was still unresolved and offered a pause: "please stop
offering to stop... i want to keep going. i have rebooted the vm."). A genuinely fresh boot - ruling
out any live change-notification timing explanation once and for all - still left `window-calls` and
`orcshot-clipboard` both listed correctly in the raw `enabled-extensions` gsettings key but never
actually activated by Shell (`GetExtensionInfo` reported `state: 6` / INITIALIZED, `enabled: false`,
`error: ''` for both - Shell had seen them, not acted on them, no error to explain why).

Isolated by direct comparison: running the official `gnome-extensions enable orcshot-clipboard@orcshot.org`
CLI command against the exact same already-correct gsettings state activated it immediately -
`GetExtensionInfo` went from `state: 6/enabled: false` to `state: 1/enabled: true` right away. That CLI
tool doesn't do anything Orcshot's own `enable_extension` wasn't already doing to the gsettings key
(confirmed by introspecting `org.gnome.Shell`'s own D-Bus interface) - the difference is that it *also*
calls `org.gnome.Shell.Extensions.EnableExtension(uuid)` directly. Writing the persistent setting and
asking the running Shell to act on it turn out to be two genuinely separate steps; this project's code
had only ever done the first.

**Fix**: new `gnome_extension_setup.enable_extension_live(uuid)` - a real-system-only function (same
category as `GioSettingsBackend` itself, never exercised by a test) that calls
`org.gnome.Shell.Extensions.EnableExtension` via a synchronous `Gio.DBusProxy` call.
`ui/first_run_setup.py`'s wizard now calls this for both UUIDs immediately after the existing
`enable_extension` gsettings writes - the write is still what makes the setting survive a *future*
login on its own; this is what makes it actually work *this* session too. Each call is independently
wrapped in a `try/except GLib.Error` - autostart/hotkeys/the gsettings writes already succeeded by this
point in the handler, and one extension's D-Bus hiccup shouldn't take the other down with it or make
the wizard look like it crashed.

**Verified live, twice, both ways**: (1) directly - `enable_extension_live` called for both UUIDs
against a freshly-disabled baseline, confirmed via `gnome-extensions list --enabled` (not just the raw
key this time) showing both genuinely active; (2) end-to-end - relaunched orcshot fresh with the
extension already live, confirmed `_log_session_info` logged "GNOME Shell extension available" at
startup (not falling back to the portal) and `HasTrayButton` returned `true` (the Shell-native panel
button, not the AppIndicator3 fallback), then triggered a real region capture through it with no crash
and no error - the shutter-sound side effect from every earlier test in this document is gone too,
exactly as expected once the Shell-native path is genuinely the one running rather than the portal
fallback.

This also retroactively explains the still-open 2026-08-15 "extension-enable checkbox doesn't persist"
finding referenced earlier in this document, and the `state: 6`/`HasTrayButton` failures direflail hit
repeatedly across this session's own dev-checkout/`.deb`-reinstall cycles - none of those were the
extension-reload JS-caching issue this project had already correctly diagnosed and documented
elsewhere; they were this, a second, previously-unidentified gap in the enable path itself.

**Final end-to-end confirmation, task #145 closed**: a full real `.deb` cycle from a clean baseline -
uninstall, clear `~/.config/orcshot/`, reset both extensions to disabled, reinstall, fresh first-run-
setup - confirmed every piece correct together: `gnome-extensions list --enabled` shows both
`window-calls@domandoman.xyz` and `orcshot-clipboard@orcshot.org` genuinely active (not just listed),
`HasTrayButton` returns `true`, all four hotkeys correctly read `/usr/bin/orcshot --capture-*` (not the
stale dev-checkout path), and a real capture completed with no crash. direflail confirmed independently:
"working again." This closes out task #145's own original goal (verify task #144's fix via a real `.deb`
install) along with the four additional real bugs task #150's investigation surfaced along the way.

## CaptureRect's parameters.deepUnpack() was never callable (task #151, complete 2026-08-18)

After task #150 closed, direflail did further real-world testing against the real `.deb` install and
reported: full-screen capture, active-window capture, and repeat-last-region all "does nothing" (region
capture and window-picker capture, which don't go through this code path, both worked). All three
broken modes share one thing: they resolve a rectangle in the extension (JS side, Shell-native) and
call back into Python's `CaptureRect` D-Bus method with it, rather than the region-select overlay
producing the rectangle itself the way region/window-picker capture do.

Root-caused with a live diagnostic rather than guessed at, per direflail's explicit instruction
("install some diagnostics before you reimplement a fix"): a standalone GJS script
(`Gio.DBusExportedObject.wrapJSObject` + a minimal one-method test interface + `Gio.bus_own_name`)
logged `typeof`, `constructor.name`, and `Array.isArray()` for the `parameters` argument an
`async TestMethodAsync(parameters, invocation)` handler actually receives. On this GJS version
(1.88.0 / Shell 50.1), `parameters` arrives as an already-unpacked plain JS `Array`, not a
`GLib.Variant` - `parameters.deepUnpack` is `undefined`, so
`CaptureRectAsync`'s `const [x, y, width, height] = parameters.deepUnpack();`
(`extension.js`) threw a `TypeError` on every call, silently swallowed with no visible error because
nothing surfaces exceptions thrown inside a GDBusExportedObject async handler back to the caller by
default.

**Fix**: removed the `.deepUnpack()` call - `const [x, y, width, height] = parameters;` - since
`parameters` is already the plain array of unpacked values.

**Verified live**: deployed to the per-user extension override
(`~/.local/share/gnome-shell/extensions/orcshot-clipboard@orcshot.org/`), full logout/login (a genuine
JS reload, not just an extension disable/enable - see the extension-reload-caching finding earlier in
this document), then all three previously-broken capture modes exercised for real. direflail confirmed:
"capture modes all seem to work now."

## Quit only dimmed the Shell-native tray button instead of fully terminating the app (task #151, complete 2026-08-18)

Also from direflail's same round of real-world testing: "quit - just greys out the orcshot icon - this
should quit the whole program." Direction given explicitly: "when the user selects quit, i want all
parts of the program to quit and vanish. it should not be running anymore (until the user restarts).
it should remain this way until the user uninstalls."

Investigation confirmed `self.quit()` alone already fully terminates the Python process - nothing left
in `ps aux` after a plain quit, verified live - so the "still visible" complaint was entirely about the
Shell-native tray panel button, which is owned by the extension (a separate process from Python) and
only reacts to Python's `org.orcshot.Orcshot` D-Bus name vanishing from the bus. That reaction,
`_setAppAvailable(false)`, was written to *dim* the button (per task #147's own "grey out when Python
isn't running to receive clicks" requirement) rather than remove it - the correct behavior for a crash,
where the button dimming while staying put/discoverable is exactly the point, but the wrong behavior
for a deliberate Quit, which the extension has no way to distinguish from a crash on its own since both
just look like "the bus name vanished."

**Fix**: added a `Quitting()` method (no args, no return) to the extension's existing `OrcshotTray`
D-Bus interface (`TRAY_IFACE` in `extension.js`) that destroys the tray button outright -
`this._trayButton.destroy(); this._trayButton = null;` plus clearing its associated menu-item/icon-area
references - distinct from the pre-existing crash-path dimming, which is untouched. Tray-button
construction was extracted out of `enable()` into a new `_ensureTrayButton()` helper so the button can
be rebuilt the next time the app becomes available (both at extension-enable time and from the existing
`Gio.bus_watch_name` "appeared" callback), since a deliberate Quit now actually destroys the GObject
rather than just hiding it.

On the Python side (`app.py`), the Quit tray action now calls a new
`_quit_and_hide_tray_button()` instead of `self.quit()` directly: it best-effort calls the extension's
`Quitting()` over a synchronous `Gio.DBusProxy` (wrapped in `try/except GLib.Error` - the extension
might not be the active tray at all, e.g. X11, or Wayland before first-run-setup has ever enabled it,
and quitting must never be blocked by a Shell extension call failing), then calls `self.quit()` as
before.

**Verified live** on the Ubuntu 26.04 VM, after a full reboot (needed to load the new `Quitting` method
into Shell's cached copy of the extension - see the extension-reload-caching finding earlier in this
document) and using the dev checkout so the new Python code was actually exercised (the system's
autostarted `/usr/bin/orcshot` still runs the pre-fix build until the next `.deb` release): (1) a plain
`kill` of the process (simulating a crash) left `HasTrayButton` reporting `true` - dimmed, not removed,
confirming the crash path is unchanged; (2) relaunching rebuilt the button via the new
`_ensureTrayButton()` path, `HasTrayButton` back to `true` with no duplicate; (3) triggering the real
`tray-quit` GAction (`gdbus call ... org.gtk.Actions.Activate 'tray-quit'`) - the same code path both
the AppIndicator3 menu and the Shell-native panel button's Quit item run through - left `ps aux` showing
no orcshot process at all, the `org.orcshot.Orcshot` D-Bus name gone, and `HasTrayButton` now reporting
`false`: the button is genuinely destroyed, not dimmed, exactly matching direflail's stated requirement.

Still outstanding: this fix has only been deployed to the per-user extension override and the dev
checkout, not the actual shippable `.deb` - rebuilding and reinstalling the package (requiring
direflail's `sudo`) is needed before this is live in the real installed app. (Update, same day: a real
`.deb` containing this fix now exists - see the next section below - but direflail's own attempt to
install it hit an unrelated snag, described there, and a genuine root install still hasn't happened.)

## A stale leftover instance made a real .deb install look broken (task #151 follow-up, complete 2026-08-18)

direflail rebuilt and reinstalled the `.deb` (`sudo dpkg -r orcshot && sudo dpkg -i ...`) to test the two
fixes above for real, and reported: "the tray icon remains, and launching orcshot does nothing." Neither
symptom was actually caused by the reinstall. `dpkg -r`/`dpkg -i` only replace files on disk - they don't
touch already-running processes - and a leftover instance from this session's own prior verification
work (started to restore the VM to a normal running state after an earlier test) was still alive and
still holding the single-instance `org.orcshot.Orcshot` D-Bus name throughout. That explains both
symptoms directly: the tray button stayed because that old process was still running, and "launching
orcshot does nothing" is exactly what GApplication's own single-instance activation does by design - a
second `orcshot` invocation just silently hands off to whatever's already running rather than starting
fresh or showing anything.

Two real, separate problems worth fixing came out of diagnosing this, both agreed with direflail before
implementing:

**1. Don't block the package transaction on a GUI response.** direflail's own framing: "could we simply
cause any open editors to open a 'save as' dialog... THEN we could call `Gtk.Application.quit()` once
those are closed" - but also asked where a "we can't proceed until you close your stuff" warning should
live. Decided against having one: `preinst`/`postinst` run as root, non-interactively, and are frequently
invoked with nobody watching (`unattended-upgrades`, scripted installs, headless CI) - there's no
reliable place to put a blocking warning that's guaranteed to be seen, and a maintainer script that hangs
waiting for a GUI response in a logged-in user's session is a real anti-pattern. The agreed compromise:
best-effort and non-blocking. Replacing files under an already-running process is safe on Linux
regardless of whether anyone responds - the process just keeps executing the old code already loaded
into memory until it next exits on its own.

**Fix**: `debian/orcshot.preinst` (new file) runs on `install`/`upgrade`, before files are replaced. For
every logged-in user with an active D-Bus session (enumerated via `loginctl list-users`, one whose
`/run/user/<uid>/bus` socket actually exists), it uses `runuser` to invoke, as that user, a new
`prepare-for-upgrade` GAction over `gdbus call ... org.gtk.Actions.Activate` - the same mechanism the
Shell-native tray button already uses for every other tray action. Every step is defensively guarded
(`command -v` checks for `gdbus`/`loginctl`/`runuser`, `|| true` on the D-Bus call itself) so a missing
tool or an instance that isn't running can never fail the install.

On the Python side, `OrcshotApplication.prepare_for_upgrade` (`app.py`) does what direflail described:
for each open editor with unsaved changes, calls `EditorWindow.prompt_save_for_upgrade` (new,
`editor_window.py`) - a direct Save As dialog, retitled to "New install incoming — save your work"
(`_do_save` gained an optional `title` parameter for this, defaulting to its original "Save Screenshot"
so its two pre-existing call sites needed no changes), and only closes the window if the save actually
completed - a cancelled save leaves it open, same as the existing close-confirmation flow does elsewhere.
Editors with nothing unsaved just close immediately, no prompt needed. Once every open editor is gone
(tracked via the existing `register_editor_window`/`unregister_editor_window` pair, task #138), the app
quits via the existing `_quit_and_hide_tray_button` (task #151, above) - including immediately, if there
were no open editors to begin with. A `_quit_after_editors_close` flag set at the start of
`prepare_for_upgrade` and checked from `unregister_editor_window` handles the case where the user leaves
a cancelled window open for a while first: whenever they do eventually close it, for any reason, the app
quits then - there's no separate timeout or "this offer has expired" logic, matching the actual goal
(don't run stale code forever) rather than the specific moment the upgrade happened.

**2. Make a second launch attempt visible instead of a silent no-op.** This is what actually explained
"launching orcshot does nothing" and matters independently of the installer - it'll recur any time
someone double-clicks the launcher or runs `orcshot` while it's already running, upgrade or not.
`do_activate` (`app.py`) now tracks `_has_activated_before`; every activation after the first (real
first-launch stays silent, matching existing behavior) sends a desktop notification via the existing
`_notify` helper. That helper's `send_notification` id was hardcoded to `"orcshot-update-available"` -
harmless with one caller, but this is now a second, unrelated caller sharing the same method, and two
different notification kinds sharing one id could silently replace each other. Gave `_notify` an optional
`notification_id` parameter, defaulting to the original hardcoded string so the existing update-check
call site needed no change, with the new call passing its own `"orcshot-already-running"` id.

**Verified live** on the Ubuntu 26.04 VM, all without needing root (this VM's `sudo` password isn't
known to this session - confirmed by one failed authentication attempt, not guessed at further; the
`preinst` script's actual execution during a real `dpkg` transaction, and root's ability to reach a
user's D-Bus session via `runuser`, both remain unverified for exactly this reason). Everything
verifiable without root was checked directly against the real classes, not mocked: a small standalone
script constructed a real `OrcshotApplication` and real `EditorWindow` instances (GTK objects, not test
doubles) and drove `prepare_for_upgrade` through all three paths - cancelled save (window stays open,
quit-pending flag set), completed save (window destroyed), and zero open editors (quits immediately) -
confirming each behaved exactly as designed. A second script called `do_activate()` directly multiple
times on a real `OrcshotApplication`, confirming no notification on the first (real) activation and a
correctly-titled, correctly-worded, correctly-`notification_id`'d call through the real (not mocked)
`Gio.Application.send_notification` on every activation after that. (First attempt at this same
verification produced confusing duplicate results - traced to the test script itself redundantly
double-registering each editor with the app, on top of `EditorWindow.__init__`'s own existing
self-registration; not a bug in the feature code, fixed in the test script.)

**Still outstanding**: a real end-to-end test - `sudo dpkg -i` of the rebuilt package while an editor
with unsaved changes is open, confirming the retitled Save As dialog actually appears and that the app
genuinely exits afterward - needs direflail's own `sudo` access to this VM.

## Task #139: wire window title into the ${title} filename pattern token (complete 2026-08-19)

`core/filename_pattern.py`'s `resolve_filename_pattern` already accepted a `title` parameter and
correctly substituted it into `${title}` (MODE_GREENSHOT) - that part was done from the start. What
was missing: every real call site passed nothing, so the token always resolved to empty. Confirmed by
grep - `resolve_filename_pattern` had exactly three callers (`destination_picker.py`'s `_quick_save`/
`_save_as`, `editor_window.py`'s `_do_quick_save`) and none of them passed `title` at all.

The actual window title was already available - `capture/window.py`'s `WindowInfo` dataclass has always
had a `.title` field, populated by every platform's real `WindowEnumerator` - it just never got carried
from wherever a window was identified through to wherever a filename gets resolved, across four
genuinely separate code paths (X11 active-window/window-picker share `capture/modes.py`'s window
resolution; the Wayland fallback overlay reuses `ui/window_picker.py`'s same `on_selected`; the Wayland
Shell-native window-picker is a fully separate extension.js/D-Bus round trip with no Python-side window
enumeration involved at all).

direflail confirmed scope explicitly before this started: Save/Save As reachable from an *already-open*
editor should also resolve `${title}` correctly (not just quick-save actions reachable straight from the
destination picker), since real Greenshot always has the originating window's title available regardless
of destination.

**Fix, by layer**:

- `capture/modes.py`: `active_window_region` (returned just a clamped `Rect`) renamed to
  `active_window_info`, now returns the whole clamped `WindowInfo` (bounds *and* title) or `None`. Its
  one caller (`ui/capture_modes.py::start_active_window_capture`) and its 4 existing unit tests updated
  accordingly (`tests/unit/capture/test_modes.py`); one new test added for the title itself.
- `ui/capture_modes.py`: `_capture_and_pick` gained a `title` parameter, threaded to both its branches -
  the classic `show_destination_picker` path and the Wayland Shell-native `dispatch_destination` path
  (that one needed no extension.js change: for active-window mode specifically, Python already knows the
  title from its own `WindowEnumerator` call, independent of the `CaptureRect` D-Bus round trip that
  only fetches pixels).
- `ui/destination_picker.py`: `_quick_save`/`_save_as`/`_open_editor` all gained a `title` parameter,
  used in their `resolve_filename_pattern`/`EditorWindow(...)` calls. Every destination handler in
  `_DESTINATION_TABLE` (plus the dynamically-generated Office/ExternalCommand entries) now shares one
  four-argument calling convention (`img, cs, clipboard_backend, title`) - handlers that don't care about
  the title (clipboard, print, external commands, Office) just accept and ignore it, rather than
  special-casing a side channel only for the three that do. `dispatch_destination`/
  `show_destination_picker` both gained a `title` parameter threading through to that call.
- `ui/editor_window.py`: `EditorWindow.__init__` gained a `window_title` parameter (distinct from the
  window's own fixed Gtk chrome title, "Orcshot image editor" - this is the *captured* window's title),
  stored and used by `_do_quick_save`'s own `resolve_filename_pattern` call - satisfies direflail's
  explicit "editor too" scope confirmation. `open_orcshot_file_in_new_window` (reopening a previously-
  saved `.orcshot` file) deliberately leaves it at the default `""` - a reopened file has no originating
  window anymore, same as region/full-screen capture never had one.
- `ui/window_picker.py`: the `on_selected` closure `start_window_picker` builds - shared by *both* the
  X11 `WindowPickerWindow` overlay and the Wayland-without-extension `WaylandWindowPicker` fallback -
  already receives the full `window_info` (title included); it just wasn't passing `.title` through to
  `show_destination_picker`. One-line fix covers both platforms' fallback path at once.
- **extension.js** (Wayland Shell-native window-picker, the one path with no local Python window
  enumeration to draw from): `StartWindowPicker`'s D-Bus reply gained a `title` field -
  `(bsayiiii)` → `(bssayiiii)`, sourced from `Meta.Window.get_title()` on the picked window, wrapped in
  its own try/catch that falls back to `''` rather than letting a title-lookup failure take the whole
  picker down with it (verified `get_title()` is a real method live, via GJS introspection against this
  system's actual `Meta-18.typelib` - `GI_TYPELIB_PATH=/usr/lib/x86_64-linux-gnu/mutter-18`, since `Meta`
  isn't in a standalone `gjs` process's default search path; confirming rather than guessing, per this
  project's own established GJS-verification convention). `capture/gnome_window_picker.py` and
  `ui/window_picker_gnome_shell.py` updated to match the new signature and thread `title` through to
  `dispatch_destination`.

**Verified live** on the Ubuntu 26.04 VM: full test suite green (1031 passed) after every change; the
rebuilt extension.js's `StartWindowPicker` interface introspected live via `gdbus introspect` and
confirmed to export the new `title` out-arg with no JS errors at Shell startup (a real, clean reload,
not just a syntax check); and, most concretely, a standalone script exercised the *entire* active-window
path against real system state - the real GNOME window-calls enumerator, a real focused window (GNOME
Text Editor, "New Document (Draft) - Text Editor"), through `active_window_info` and
`resolve_filename_pattern` with a real `${title}`-containing pattern - producing
`2026-08-19 18_31_25 - New Document (Draft) - Text Editor`, confirming the entire chain end-to-end with
no mocks.

**Not verified live by this session directly**: the three interactive window-*picker* click paths (X11's
`WindowPickerWindow`, the Wayland fallback `WaylandWindowPicker`, and the Wayland Shell-native
`GnomeShellWindowPicker`) - each needs a real hover-then-click gesture over a real window, which has no
synthetic-input equivalent available this session (same limitation this project has always documented
for every interactive overlay - region-select, window-picker, eyedropper - "verified by running it,"
meaning a human actually clicking). direflail did that real testing independently (both this task and
its strftime-suffix follow-up below), confirming: "i have tested this. it works great." Closes out task
#139 fully, including the one gap this session couldn't cover itself.

## Task #139 follow-up: strftime-mode default pattern also gets the title (complete 2026-08-19)

Once task #139 made the real window title available, direflail asked whether the *default* filename
pattern could pick it up too, for window/window-picker captures specifically - matching real Windows
Greenshot's own default, which appends `-${title}` (this module's own docstring already cited
ICoreConfiguration.cs:127 for that, and already explained why this port originally dropped it: the
title wasn't reliably available before task #139 existed to fix that).

The complication: `DEFAULT_FILENAME_PATTERN`/the default mode are both strftime (direflail's own
earlier call, task #127/#128 feedback - standard Linux convention over Windows' `${TOKEN}` scheme), and
strftime mode has no `${title}`-equivalent syntax at all - `%` and `${...}` are deliberately never mixed
in this module (see its own top-of-file docstring for the real corruption case that motivated keeping
the two modes mutually exclusive). So this couldn't be "just add `${title}` to the default pattern
string" the way it might be in Windows' single-syntax world.

Two scope questions, both settled with direflail directly rather than assumed: (1) should this be a
plain, unconditional suffix, or gated so region/full-screen capture (no title) never get a dangling
`" - "` with nothing after it - gated, confirmed by direflail's own worked example
(`"...18_31-25.png"` vs `"...18_31-25 - a picture of a moose.png"`); (2) should this only affect the
untouched factory-default pattern, or *any* strftime-mode pattern including ones already customized -
the latter, direflail's explicit choice, reasoning being that strftime mode has no other way to express
this at all regardless of what pattern text is in the field, so there's no real "already opted out of it"
state to preserve for that mode specifically.

**Fix**: `resolve_filename_pattern`'s own `MODE_STRFTIME` branch (`core/filename_pattern.py`) - the one
place every strftime-mode caller already funnels through - now appends `" - " + make_filename_safe(title)`
after the strftime-resolved string, but only when `title` is non-empty. Region/full-screen/last-region
capture already pass `title=""` (task #139's own design, no single associated window), so they're
completely unaffected - same output as before this change, not even a trailing separator.
MODE_GREENSHOT is untouched too - a user there already has full `${title}` control via the token itself,
so nothing gets auto-appended on top of whatever they chose to write (or not write).

All three existing callers (`destination_picker.py`'s `_quick_save`/`_save_as`,
`editor_window.py`'s `_do_quick_save`) needed zero changes - they already pass `title=...` through as of
task #139, so this was a single-function change plus new tests
(`tests/unit/core/test_filename_pattern.py`: title-appended, no-title-no-separator, and
title-gets-sanitized-too). Full suite green (1034 passed, three more than task #139's own count).

## Task #153: preinst's prepare-for-upgrade save prompt, real repro finally succeeded (complete 2026-08-19)

Follow-up to task #152: direflail's first real end-to-end test (`sudo dpkg -r orcshot && sudo dpkg -i
...` with an editor window open with unsaved changes) reported no visible effect at all - "the editor
didn't do anything different. it just stayed open." This session has no `sudo` access to the VM (one
failed authentication attempt, not pursued further), so isolating this meant working backward through
each piece of the chain individually, asking direflail to run the pieces that genuinely needed root -
per direflail's own "install some diagnostics before you reimplement a fix" precedent from task #150,
not guessing at a fix without evidence.

**Isolated and ruled out, in order**:

1. The D-Bus/GAction path itself - confirmed working by triggering `prepare-for-upgrade` via a real
   `gdbus call` against the actual installed running instance (as the same user, no `runuser` involved):
   the app quit immediately, matching `prepare_for_upgrade`'s own documented "no open editors" behavior
   exactly.
2. `runuser`'s ability to reach the session bus as root - direflail's own first attempt at this hit two
   real red herrings before landing a clean result: an accidental run against the *host* machine instead
   of the VM (`ubuntu2604` "does not exist" there, since that user only exists inside the guest - the
   Claude Code "Run" button executes in the host's own terminal, not inside a VM, something not flagged
   clearly enough beforehand), and a `/run/users/1000/bus` (plural) vs. the real `/run/user/1000/bus`
   (singular) path typo from manually retyping the command instead of copy-pasting it. Once run correctly,
   *inside* the VM, via copy-paste: `()`, and the app quit - `runuser` genuinely works fine as root.
3. The full `preinst` script, run exactly as dpkg invokes it (`sudo sh
   /var/lib/dpkg/info/orcshot.preinst install` - dpkg's own cached copy, confirmed byte-identical to this
   repo's `debian/orcshot.preinst`) - also succeeded, app quit cleanly.

With every individual piece confirmed working, direflail redid the *exact* original repro - a real
`sudo dpkg -r orcshot && sudo dpkg -i ~/orcshot_0.1.0-2_all.deb` cycle with an editor window open with
unsaved changes - and this time it worked completely: the editor immediately showed the retitled Save
As prompt, saved, closed, and orcshot quit cleanly; the freshly-reinstalled package came up working
normally afterward.

**Conclusion**: no code defect was ever found in `preinst`, `prepare_for_upgrade`, or
`prompt_save_for_upgrade` - every piece worked correctly every time it was actually tested in isolation.
The original failure is best explained as transient state specific to that one earlier moment (this same
VM had a well-established history that same session of stale leftover test processes causing exactly
this class of "nothing visibly happens" confusion - see task #152's own "stale leftover instance" section
above) rather than a reproducible bug - three independent successful reproductions since, including the
real end-to-end one, support that conclusion rather than it being a fluke in the other direction.

## Task #141: autostart switched from a .desktop entry to a systemd --user service (complete 2026-08-20)

The previous autostart mechanism (a plain XDG `~/.config/autostart/orcshot.desktop` entry,
`autostart.py`) only ever launched once, at login. If `orcshot.app` crashed later, nothing relaunched
it - and since the Wayland tray panel button now lives in the Shell extension independently of the
Python process (task #137 follow-up), a dead process left a tray icon that still *looked* functional
(hovering/opening the menu still worked) but did nothing on click, silently, since nothing was listening
on `org.orcshot.Orcshot`'s D-Bus name anymore. No error shown anywhere.

**Fix**: `debian/orcshot.user.service`, a systemd `--user` unit with `Restart=on-failure` -
`ExecStart=/usr/bin/orcshot`, `PartOf=graphical-session.target`/`WantedBy=graphical-session.target` (the
standard target pulled in by a real graphical login, matching how session-scoped GUI services are
normally shipped). `autostart.py` was rewritten from file-read/write functions
(`install_autostart_entry`/`is_autostart_enabled`/`remove_autostart_entry`) to three thin wrappers around
real `systemctl --user` calls (`enable_autostart`/`is_autostart_enabled`/`disable_autostart`) - real,
live system calls with no safe way to test without a real systemd user manager, same category as
`gnome_extension_setup.enable_extension_live` and `hotkey_setup.py`'s `GioSettingsBackend` (see either
module's own docstring) - `tests/unit/test_autostart.py` removed entirely, nothing pure left to test.
Both call sites (`ui/first_run_setup.py`'s first-run dialog, `ui/editor_window.py`'s Preferences "Launch
Orcshot on startup" checkbox) updated to match; `disable_autostart()` deliberately does not stop
whatever's running right now (only affects the *next* login) - the checkbox is normally toggled from
inside the app's own currently-open Preferences dialog, and killing that process out from under the user
while they're still looking at it would be a real regression from the old mechanism's own behavior
(which never touched the current session at all).

**A real, non-obvious packaging bug caught before it shipped**: the first attempt named the unit file
`debian/orcshot.service`, following the same naming this project's other `debian/orcshot.<script>`
maintainer-script files use - wrong for a `--user` systemd unit specifically. debhelper's
`dh_installsystemd` (the *system*-unit tool, not `dh_installsystemduser`) picked it up instead, installed
it to `/usr/lib/systemd/system/` (system-wide, root-run, no access to any user's display or session bus
at all), and auto-generated `postinst`/`prerm` hooks that would `deb-systemd-helper enable` +
`systemctl --system daemon-reload` + `deb-systemd-invoke start` it **unconditionally on every install** -
directly violating this project's own standing rule that real system-config writes only ever happen from
an explicit user click (hotkeys, extension-enabling, and now autostart itself all share this rule - see
`autostart.py`'s own module docstring). Caught by actually inspecting the built `.deb`'s contents and
generated maintainer scripts rather than assuming the build succeeding meant it was correct. Fixed by
renaming to the debhelper-mandated `debian/orcshot.user.service` (confirmed via `man dh_installsystemduser`
rather than guessed at a second time) and adding a `debian/rules` override
(`override_dh_installsystemduser: dh_installsystemduser --no-enable`) so the unit ships disabled by
default regardless - `enable_autostart()` is the only thing that ever flips it on, and only from a real
button click, exactly matching the old mechanism's own behavior.

**Verified live** on the Ubuntu 26.04 VM, entirely without needing root (the unit file deployed to the
per-user override path, `~/.config/systemd/user/orcshot.service`, which - like the GNOME Shell
extension per-user override used throughout this session - takes priority over the system-wide path with
no `sudo` required): rebuilt `.deb`'s contents confirmed correct (`usr/lib/systemd/user/orcshot.service`,
`postinst` using `deb-systemd-helper --user` gated on `was-enabled` rather than unconditionally enabling,
no start/restart hooks at all); `is_autostart_enabled()`/`enable_autostart()`/`disable_autostart()` each
called for real against the live unit and confirmed correct (`False` → `True` → `False`); and, most
directly testing the actual point of this task, a running instance was forcibly killed with `SIGKILL`
(simulating a real crash) and systemd relaunched it automatically within seconds, confirmed via a new
PID in `systemctl --user status` - no manual intervention, no custom watchdog code, native OS crash
recovery working exactly as intended.

## Task #141 follow-up: offer autostart during install itself, via debconf (complete 2026-08-20)

direflail asked whether autostart consent could happen at install time rather than requiring a separate
first launch, worked through with direflail directly rather than assumed:

1. **A real graphical session (Wayland/X11) at install time**: a debconf `y/n` prompt ("Start Orcshot
   automatically at login?", default yes) - `debconf`, not a raw shell prompt, specifically because a
   raw `read` in a maintainer script hangs forever with no TTY (unattended-upgrades, scripted/CI
   installs) - debconf shows a real prompt when there's someone to answer it and gracefully
   skips/defaults otherwise. Confirmed with direflail this only needs to cover autostart, not
   hotkeys/the GNOME Shell extensions - "yes" both enables *and* starts Orcshot immediately
   (`systemctl --user enable --now`, already `enable_autostart()`'s own existing behavior, task #141
   above), and launching it for the first time runs `maybe_run_first_run_setup()` exactly the same as
   any other launch (gated purely on the persistent `first_run_setup_done` flag, not on how the process
   started) - so hotkeys/extensions still get asked, one step later, in the flow already built for
   exactly that. Verified live rather than assumed: reset the flag, launched the *real* binary via
   `systemctl --user start` (not a normal click), and confirmed via `org.gnome.Shell.Extensions.Windows`
   a real window - `wm_class: "orcshot"`, `title: "Orcshot Setup"`, PID matching the systemd-launched
   process exactly, `focus: true` - actually rendered on screen with the correct session environment
   inherited.

2. **No graphical session at install time** (a fresh headless install, or installing from a bare TTY
   before ever logging into the desktop graphically): falls straight through to the existing plain
   "open it from your Applications menu" message - no change from before this task.

3. **Bundling into a distro image or fleet deployment, fully unattended**: doesn't need a custom dpkg
   flag (dpkg doesn't pass arbitrary flags through to a package's own scripts that way) - the standard
   Debian mechanism already covers it, `debconf-set-selections` pre-seeds the answer before install runs
   so the question never even appears:
   ```
   echo "orcshot orcshot/enable-autostart boolean true" | debconf-set-selections
   apt install orcshot
   ```

**Implementation**: `debian/orcshot.templates` declares the boolean question (`Default: true`).
`debian/orcshot.config` (new) does the detection - loops `loginctl list-users`/`list-sessions` for the
first session with `Type` of `wayland` or `x11` (narrower than `preinst`'s own existing check, which
only cares whether *any* D-Bus session bus exists - a plain SSH/tty login gets one too under modern
systemd, but isn't somewhere a tray icon could ever appear) - and only calls `db_input high` if one is
found. Only the first graphical session found is acted on; two different users logged in graphically at
once (fast user switching, multi-seat) is a genuine edge case for this app's actual audience, not worth
the complexity of asking per-session. debconf's own answer-tracking means a routine upgrade won't
re-prompt once it's been answered once, whichever way - no extra "already enabled" check needed for
that specifically.

`debian/orcshot.postinst` re-runs the identical detection (a fresh script invocation, no state shared
with `config` except debconf's own stored answer), and on a `true` answer, runs
`runuser -u "$user" -- env DBUS_SESSION_BUS_ADDRESS=... XDG_RUNTIME_DIR=... systemctl --user enable --now
orcshot.service` - the same `runuser`-wrapping-a-real-system-call pattern `preinst` already uses
successfully for task #152's `prepare-for-upgrade` D-Bus call, just wrapping `systemctl` instead of
`gdbus`. `debian/control`'s `debconf (>= 0.5) | debconf-2.0` dependency was added automatically by
`dh_installdebconf` once it saw `debian/orcshot.templates` exist - no manual `Depends:` edit needed.

**Verified as far as possible without root** (this session still has no `sudo` on the VM): both shell
scripts pass `sh -n`; the built `.deb`'s `config`/`templates`/`postinst`/`Depends` all inspected directly
and confirmed correct; and, most concretely, the exact `loginctl`-based detection snippet both scripts
share was run for real on the VM and correctly identified the live Wayland session (`uid=1000
session=1 type=wayland` → match).

**Not verified live**: the actual interactive debconf prompt appearing during a real `dpkg -i`/
`apt install` (needs a genuine TTY, not something `VBoxManage guestcontrol` can drive the same way a real
terminal can), and the specific combination of `runuser` wrapping `systemctl --user enable --now` (each
half proven separately live tonight - `runuser` reaching a real D-Bus call for task #152/#153, and
`systemctl --user enable/disable/is-enabled` working correctly for task #141 above - but not together,
and this needs real `sudo`). direflail's own real `sudo dpkg -r orcshot && sudo dpkg -i
~/orcshot_0.1.0-2_all.deb` test, watching for the debconf prompt and confirming Orcshot actually starts
on "yes", is the remaining confirmation needed to close this out fully.

**Closed out**: direflail ran the real test - `pgrep -af orcshot` showed the process running immediately
after install, and `systemctl --user is-enabled orcshot.service` returned `enabled`, confirming both
previously-unverified pieces together: the debconf prompt was answered, and `runuser` wrapping
`systemctl --user enable --now` worked correctly for real, not just in each half's own separate test.

## Task #157: editor window opened via a Shell-native capture sometimes lands pinned top-left (fixed, verified live 2026-08-20)

direflail's real-world testing after task #141's install-time debconf prompt: "the editor showed up almost
offscreen to the left" right after a fresh `sudo dpkg -r/-i` reinstall, doing a region-select capture and
choosing Edit. Confirmed reproducible on demand ("reinstalling orcshot puts it on the far left again
(normal after)") - not a one-off.

**Investigated live, evidence gathered before touching any code, per this project's own standing rule
against guessing**:

- Constructing an `EditorWindow` directly (bypassing the entire capture + Shell-native destination-picker
  round trip - a standalone script, `show_all()` only) positioned normally (`x=185, y=32` on this VM's
  screen) - real evidence `EditorWindow`'s own construction/resize code (confirmed to have zero
  `.move()`/`set_position()` calls anywhere) isn't the cause on its own.
- direflail captured the actual live numbers for the real bug, via `org.gnome.Shell.Extensions.
  Windows.List` while the misplaced editor was still open: `x=0, y=32, width=650, height=786,
  focus: false`. Not a garbage/negative coordinate - pinned exactly to the screen's top-left corner, and
  critically, never actually focused.

That combination - default-corner placement plus no focus - is a recognized Wayland compositor pattern:
without a legitimate activation context behind a newly-mapped window, compositors commonly skip their
normal smart/centered placement and skip handing it focus. This flow fits: the editor isn't shown from a
direct input-event handler in the Python process - it's shown from an async D-Bus reply callback, after
the GNOME Shell extension (a separate process) resolves the destination-picker interaction and only then
tells Python which destination was chosen. `_open_editor` (`ui/destination_picker.py`, the single
function every "Edit" destination reaches, X11 and every Wayland path alike) only ever called
`show_all()`, never `present()` - and `present()` specifically is GTK's way of asking the compositor to
actually raise/focus a window, unlike a bare `show_all()`.

**Fix attempted, not yet confirmed**: `editor.present()` added right after `show_all()` in `_open_editor`.
Explicitly logged as a well-reasoned candidate, not a confirmed root cause - the actual interactive
Shell-native capture flow (a real mouse drag across the screen, then a real click on the Shell-side
destination-picker popup) couldn't be reproduced or isolated further this session; no synthetic input is
available for Mutter's compositor-level input pipeline, the same wall hit for task #139's window-picker
verification. Full suite green (1022 passed) - no test coverage added, this is GTK/Wayland-interaction
glue with no meaningful headless test, same as every other file in `ui/`.

**Still needed**: direflail's own test on the next real reinstall, watching specifically whether the
editor now opens focused and normally-placed after choosing Edit from a region-select capture.

**Update, same day - `present()` fixed focus but not placement**: direflail retested. Focus is now
correct (confirmed: the editor had focus immediately, no click needed) - `present()` genuinely helped,
ruling out a missing-activation-context explanation as the *whole* story. Placement is still wrong
(pinned top-left again). This is real, useful data: whatever activation gate a compositor checks before
granting focus, this window is now passing it - the remaining bug is specifically in *where* Mutter
places it, not whether it's treated as legitimate.

That redirected the investigation to `_resize_canvas_and_window` (the same method cited in the `show_all`
override's own docstring): the window is first mapped at a default, toolbar-chrome-only size, then grown
via `self.resize()` to fit the actual captured image from a `GLib.idle_add` callback - deliberately
deferred, since it needs real post-layout chrome measurements (`get_allocation()` on the toolbar/menu
bar/canvas scroller) that don't exist before the first show. If Mutter's placement decision is made using
the window's size *at that initial small-size map*, and the later `resize()` grows it from a fixed
top-left anchor rather than re-centering, a large final image would visually end up shifted toward the
top-left relative to where a correctly-centered final-size window would sit. This also explains the
timing sensitivity cleanly: a freshly-started ("cold") process has more competing startup work (first-run
setup, extension-enable D-Bus calls, general first-realize costs), making it more likely the deferred
resize loses whatever race decides Mutter's placement window, while an already-warm process (ordinary
later captures) or a script with nothing else running (this session's own earlier isolated `EditorWindow`
test, which showed normal placement) resolves it fast enough to not matter.

**Second candidate fix**: `self.set_position(Gtk.WindowPosition.CENTER_ALWAYS)` added in
`EditorWindow.__init__`, right after `super().__init__()`. `CENTER_ALWAYS` specifically (not plain
`CENTER`) because its own documented behavior is to re-center the window on every resize, not just the
initial placement - exactly the gap `_resize_canvas_and_window`'s post-map resize creates. No existing
position hint was set anywhere in this class before (confirmed via grep - zero prior
`.move()`/`set_position()`/`WindowPosition` references). Full suite still green (1022 passed) after
adding this alongside the earlier `present()` fix (both are cheap enough to keep together regardless of
which one turns out to matter, or whether both do).

**Still needed**: another real reinstall + region-select-then-Edit test from direflail, to see whether
placement is now correct too.

**Update, same day - direflail suggested real diagnostics instead of more guess-and-check**: "can you
log the coordinates of the window when it starts? this seems like it would go easier." Added a temporary
`configure-event` handler (logs every geometry the compositor actually assigns, timestamped, to stderr -
visible via `journalctl --user -u orcshot.service` since the app runs as the systemd `--user` service)
plus a log line immediately before `_resize_canvas_and_window`'s own `self.resize()` call (requested
size + monitor work area). Full suite green (1022 passed), rebuilt, reinstalled by direflail.

Real data immediately falsified the `_resize_canvas_and_window`-race hypothesis: the window's *first*
`configure-event`, before the deferred resize ever ran, already reported `size=(2239,749)` - wider than
the monitor's entire 1366px work area. Root cause #1 found: `EditorWindow.__init__` called
`self._drawing_area.set_size_request(width, height)` with the *raw captured-image dimensions* (`width,
height = image.shape[:2]`) directly, before `show_all()` - forcing the drawing area, and therefore the
window's very first natural-size computation, to the full image size on the initial map, before
`_resize_canvas_and_window`'s own (correct, zoom-aware, work-area-clamped) sizing ever got a chance to
run. Removed the eager call entirely (dead/redundant - `_resize_canvas_and_window` already recomputes
and sets the same drawing area size correctly, from real post-layout measurements). Rebuilt, reinstalled,
retested.

Still wrong - but with new, decisive evidence: the first `configure-event`'s size was now *constant*
(`2239,749` again) across two different captures in the same run that settled at two different final
sizes (`650,747` and `1312,768`). A size that doesn't vary with the captured image can't be driven by the
canvas at all. Root cause #2 found by reading `_build_style_panel` and the `show_all()` override
together: the style panel builds ~14 field cells (line/fill color, thickness, shadow, obfuscate
mode/fill/text/amount, highlight mode/fill/brightness/blur/magnification), and `_refresh_style_panel`
normally hides all but the active tool's fields. But `show_all()`'s override called `super().show_all()`
*first* - which, on a `Gtk.Window`, both shows every descendant (including every hidden style-panel cell)
*and* synchronously realizes/maps the window using whatever child visibility is current at that instant -
before `self._refresh_style_panel()` (called immediately after, but too late) ever got to hide the extra
cells. The window's real first commit to the Wayland compositor reflected every style-panel field visible
at once, ballooning its natural width past the whole screen. Mutter has no way to center something wider
than the work area, so it clamped the window near a corner to place it at all - and Wayland gives clients
no way to reposition a window after that initial placement (the same constraint that makes
`CENTER_ALWAYS` a no-op there), so it stayed pinned even once `_resize_canvas_and_window` shrank it back
down moments later.

**Real fix**: reordered `show_all()` to show the window's content (and correct the style-panel visibility)
*before* realizing the window itself, not after - `self.get_child().show_all()`, then
`self._refresh_style_panel()`, then `super().show()` (not `show_all()`, since the child's visibility is
already final). The window's first-ever size negotiation now happens only once every descendant already
has its correct, final visibility. Full suite green (1022 passed), rebuilt, reinstalled, retested.

**Confirmed live**: the first `configure-event` now reports `size=(507,749)` - a normal chrome-driven
size, not the screen-exceeding `2239` from before - across every capture in the retest, including a large
region-select. The severe, originally-reported symptom (window pinned hard against the corner, "almost
off-screen") is gone. Position still lands at a consistent `(26,23)` rather than dead-center; per direflail
("not exactly the middle... mostly where it used to show up") this reads as the normal, expected Wayland
placement rather than the bug - consistent with this session's own earlier, separately-confirmed finding
that Wayland's xdg-shell protocol gives clients no way to request or query an absolute window position at
all (initial placement is entirely the compositor's own decision; `CENTER_ALWAYS`/`.move()` cannot
influence it). `(26,23)` is most likely simply Mutter's own default new-toplevel placement on this VM,
not something orcshot's own code can change via GTK APIs - kept `CENTER_ALWAYS` in place regardless since
it's genuinely effective on X11 (Mint/Cinnamon), where `.move()` is not a no-op.

Removed both temporary diagnostics (`configure-event` handler + pre-resize log line) once the fix was
confirmed; not meant to ship. Final clean rebuild (1022 passed) with no diagnostic logging, reinstalled
and copied to the VM.

**Separately noticed, not investigated further**: a same-version reinstall (`0.1.0-2` over the identical
`0.1.0-2`, this session's own rapid dev-iteration pattern) now also logs a harmless
`debconf: Unknown template field '_description', in stanza #1 of /var/lib/dpkg/info/orcshot.templates`
warning during `postinst`. Traced to debconf's own template parser
(`/usr/share/perl5/Debconf/Template.pm:141-152`): it lowercases each field name but never strips the
leading underscore i18n marker before comparing against its known-field set, so `_Description:` (the
correct, standard Debian Policy syntax this project's `debian/orcshot.templates` already uses -
confirmed byte-for-byte via hexdump, no typo) can never match. Doesn't block `postinst` (completed
successfully) and didn't appear during task #156's own real `dpkg -r`/`dpkg -i` verification, so it looks
specific to reinstalling the identical version rather than a genuine packaging defect - not chased
further since it's cosmetic and off this task's critical path.

## Task #159: unwanted audible tone on two Wayland dialogs (fixed, verified live 2026-08-21)

direflail, live: "wayland version, i am not hearing a 'camera' noise when i take the screenshot (I was
yesterday) but i am hearing a tone when the save as screen appears" - the task #73 shutter-sound fix still
held (confirmed separately), but a new, real, unrelated tone showed up on two different Wayland dialogs.
Two genuinely different root causes, found and fixed independently:

**Save As dialog (`ui/destination_picker.py`'s `_save_as`) - fixed.** A full-codebase grep of every
`Gtk.Dialog`/`Gtk.FileChooserDialog`/`Gtk.MessageDialog` construction site (`app.py`, `editor_window.py`,
`printing.py`, `color_dialog.py`, `external_commands.py`, `first_run_setup.py`, `text_obfuscation_dialog.py`)
found this was the *only* one missing `transient_for` - every other dialog already sets it. A parentless
modal `.run()` dialog failing to establish a proper Wayland compositor grab is a known trigger for GDK's
own fallback beep. Fixed by adding `app.py`'s new `topmost_editor()` accessor (extracted from two
duplicated inline lookups already in `show_preferences`/`open_file_from_tray`) and wiring `_save_as`
through it, matching the same "topmost open editor, else None" pattern every other tray/hotkey-reachable
dialog already uses. Confirmed live: tone gone.

**Close-with-unsaved-changes dialog (`ui/editor_window.py`'s `_on_delete_event`) - fixed, took three
attempts.** This dialog already had `transient_for=self` set correctly, so the Save As fix's own theory
didn't apply here - real, useful evidence that ruled out one explanation while the actual one was still
unknown, rather than assuming the same fix would cover both.

1. First attempt: removed a `self.present()` call sitting directly before `dialog.run()` (present since
   the method's original commit, not added to fix any specific prior bug) - theorized as a modal grab
   racing an in-flight present() request. direflail retested: **"the tone remains."** Real negative
   result.
2. Investigated whether the bundled GNOME Shell extension was responsible - genuine Clutter/GJS errors
   (`clutter_actor_set_allocation_internal: assertion ... failed`, `Actor 'unnamed [StDrawingArea]' tried
   to allocate a size of -2147483648.00 x -2147483648.00`, a disposed `PopupBaseMenuItem` access) showed up
   in `journalctl` at roughly the same moment as a reproduction, which looked like a serious lead. Rather
   than assume causation from proximity, added a temporary diagnostic: named every actor `extension.js`'s
   `_buildDrawnMenuItem`/`_buildTrayButton`/`pickDestinationAsync` create (all were previously
   GNOME-Shell-default "unnamed") plus a repaint-time log. Rebuilt, full logout/login (required for a
   `.js` reload - a `.deb` reinstall alone doesn't pick it up), reproduced again. Real result: the crash
   *still* said "unnamed" for both actors, and **no `[orcshot][task159]` log line appeared at all** -
   meaning none of this extension's own code even ran while closing an already-open editor (the
   destination picker only shows after a *new* capture). Conclusively ruled out this extension as the
   cause - the earlier journal proximity was coincidence, not causation. The temporary `console.log` calls
   were removed afterward; the actor names were kept (cheap, real diagnostic value for whatever the next
   Shell-side crash investigation turns out to be, added no matter how this particular one resolved).
3. Real fix: `message_type=Gtk.MessageType.QUESTION` → `Gtk.MessageType.OTHER`. GTK's own
   `libcanberra-gtk-module`, when active, plays a themed system sound keyed directly to a
   `GtkMessageDialog`'s `message_type` (dialog-question/warning/error) the moment it's realized -
   independent of `transient_for`, independent of any Shell extension. This also explains why the Save As
   fix didn't touch this dialog and vice versa: `Gtk.FileChooserDialog` has no `message_type` concept at
   all, so it was never eligible for this specific mechanism in the first place - two dialogs, two
   unrelated bugs, not one bug with two symptoms. `OTHER` shows no icon (appropriate anyway - this is a
   routine "want to save first?" prompt, not a warning) and isn't wired to any canberra sound event.
   direflail, after retest: **"no more tone."**

Full suite green (1028 passed) after every change; each build deployed and tested live before moving to
the next hypothesis, per this project's own systematic-debugging discipline - guessing was avoided in
favor of gathering real evidence (a full dialog-site grep, temporary Shell-extension diagnostics) at each
step where the next cause wasn't already obvious.

**Separately found and fixed during this same investigation - task #160 (see below):** while testing
whether the close-dialog tone happened with Orcshot not running at all, direflail discovered Quit didn't
actually stay quit against the global capture hotkeys. Different bug, different mechanism, fixed
separately - not folded into this write-up beyond this cross-reference.

**Separate platform, resolved separately as task #161:** direflail also reported a distinct
"xylophone"-sounding tone on every Print Screen press on the *real X11 Mint/Cinnamon machine* (not the
Wayland VM) - confirmed not a Cinnamon-native keybinding conflict and not any beep/sound call anywhere in
this codebase's own Python source. Not the same bug as either dialog fix above - see task #161's own
write-up for the real root cause (the "already running" notification firing on every hotkey press) and
resolution.

## Task #160: Quit didn't actually stay quit against global capture hotkeys (fixed, verified live 2026-08-21)

Found serendipitously while isolating task #159's tone: asked direflail to fully quit Orcshot and retest
PrtScr with it dead, to rule out whether the process needed to be running at all. Live-reported: "selecting
quit in the tray icon makes the icon go away, but pressing prtscr starts a capture in orcshot and then
brings the icon back."

Root cause: `hotkey_setup.py`'s global capture hotkeys are registered as Cinnamon/GNOME's own
`custom-keybinding` GSettings entries, which run `/usr/bin/orcshot --capture-*` as an OS-level command -
completely independent of whether an Orcshot process is currently alive. `self.quit()` genuinely already
terminated the process fully (confirmed via `ps aux`, going back to task #150's own original verification)
- the missing piece was never that, it was that the very next hotkey press launches a brand-new instance
from scratch regardless, contradicting direflail's own task #150 requirement verbatim: "it should not be
running anymore... it should remain this way until the user restarts." Worth noting: real Windows
Greenshot's own hotkeys are an in-process `RegisterHotKey` call that dies with the process, so on Windows
quitting *does* silently disable the hotkeys too - this Linux port's prior behavior (hotkey silently
relaunching the app) was an unintentional divergence from that, not a deliberate design choice.

Asked direflail directly how quit-vs-hotkey should behave (AskUserQuestion) rather than assume: chose "the
hotkey should do nothing after quit," matching both real Greenshot's own behavior and task #150's literal
wording.

**Fix**: a real on-disk marker (`settings.py`'s `quit_marker_path()`/`write_quit_marker()`/
`clear_quit_marker()`/`is_quit_marker_set()`, `~/.config/orcshot/quit.marker`, same XDG-path convention as
`config_file_path()`), checked in `app.py`'s `main()` *before* the `Gio.Application` is even constructed -
a hotkey-triggered relaunch never gets far enough to build a tray icon or do anything visible. The
distinguishing signal: a capture-flag invocation (`--capture-region` etc.) while the marker is set can
only be a hotkey relaunch, since every genuine manual reopen (Applications menu, a bare `orcshot` from a
terminal, a `.orcshot` file double-click) never carries one of those flags, matching
`hotkey_setup.py`'s own `HotkeyBinding` table exactly - so a manual reopen instead clears the marker and
proceeds normally, which is what "restarts" (task #150's own wording) means here.

Two related bugs caught and fixed in the same pass, both real correctness gaps against the same
requirement:
- The X11/AppIndicator3 local tray menu's own "Quit" item called bare `self.quit` directly, bypassing
  `_quit_and_hide_tray_button()` (the Shell-native panel button's own D-Bus "tray-quit" action already
  routed through it correctly) - meaning the new marker-write would have silently never applied on X11,
  the very platform this was reported on. Fixed to call `_quit_and_hide_tray_button` like every other quit
  path.
- `_maybe_quit_after_upgrade_prep` (task #151/#152's package-upgrade handling) also routes through
  `_quit_and_hide_tray_button()` - which would have *also* written the marker on every package upgrade,
  incorrectly suppressing the very next capture hotkey even though the user never actually quit. Added a
  `write_marker: bool = True` parameter, with the upgrade path passing `False` - that quit is involuntary
  (systemd/the next login is supposed to bring it back), not the user asking to stay quit.

Six new unit tests (`TestQuitMarker` in `tests/unit/test_settings.py`) cover the pure marker logic - path
resolution, write/is-set/clear round trips, directory auto-creation, clear-when-never-written as a no-op -
same testing approach as every other settings.py function (real file I/O against a temp path). `main()`'s
own check and the app.py quit-path wiring are GTK/GApplication glue with no meaningful headless test, same
precedent as the rest of this project's UI code - verified live instead. Full suite green (1028 passed).

Confirmed live by direflail on the real X11 machine: **"quit stays quit now."**

## Task #161: "already running" notification fired on every capture hotkey press (fixed, verified live 2026-08-21)

Follow-up to task #159's own "still unresolved, separate platform" note: a distinct "xylophone"-sounding
tone on every Print Screen press on the real X11 Mint/Cinnamon machine, confirmed not a Cinnamon-native
keybinding conflict and not any explicit beep/sound call anywhere in this codebase's own Python source.
direflail identified the sound precisely on request: "it's the same noise as Showing Notifications plays -
notification.oga" - a real desktop notification, not a generic system bell, immediately reframing the
whole investigation from "what's ringing a bell" to "what's showing a notification on every hotkey press."

Root cause, found by reading `app.py`'s own `do_command_line`/`do_activate` rather than guessing:
`do_command_line` calls `self.activate()` **unconditionally** at its very top, before the
if/elif/else chain that checks which capture option (if any) was actually given. `do_activate` shows
"Orcshot is already running" (with its own notification sound) whenever `self._has_activated_before` is
already `True` - which, after the very first activation of a session, is true for literally every
subsequent invocation, including every single capture-hotkey press. The existing code comment claimed "A
capture-option or file-open invocation already does something visible on its own... this only covers the
bare 'just open Orcshot' case" - but the actual code never implemented that distinction; the comment
described the *intended* behavior, not what the code did. Confirmed `Gio.ApplicationFlags.
HANDLES_COMMAND_LINE` (set in `__init__`) means GApplication itself never emits `activate` on its own for
this app - `do_activate` is *only* ever reached via `do_command_line`'s own explicit call, so there was no
separate direct-launcher path to account for, fully de-risking the fix. Also matches the "wasn't sure when
it started" symptom exactly: silent on the very first activation of a session (before
`_has_activated_before` flips true), firing on every one after that.

**Fix**: snapshot `was_already_running` before `self.activate()` mutates the flag, and move the
notification out of `do_activate` (now just `self.hold()`) into `do_command_line`'s own bare-invocation
`else` branch - the one branch that genuinely doesn't already show something visible of its own (every
capture option opens an overlay/picker; a `.orcshot` file-open opens the editor). Full suite green (1028
passed). Built, deployed, direflail retested on the real X11 machine with several Print Screen presses in
a row: **"it is gone."**

## Task #158: Play Camera Sound / Show Notification after capture (fixed, verified live 2026-08-21)

Real Windows Greenshot's Capture tab has two settings this port never had: "Play camera sound"
(`PlayCameraSound`, `SoundHelper.Play()`, called from `CaptureHelper.cs`'s `DoCaptureFeedback()` right
after a capture completes) and "Show notification" (`ShowTrayNotification`, a tray balloon with the
chosen destination's own outcome message - "Saved to X", not a generic "capture happened" message).
Neither existed in this port at all before this task - `_build_capture_settings_tab`'s own docstring
used to list them under "deliberately not here... no capture-complete notify/sound feature exists in this
port at all to attach them to."

**Implementation**: two new settings (`settings.py`'s `get_play_capture_sound`/`get_show_capture_notification`
+ setters), a new module (`capture/capture_feedback.py`) with `play_capture_sound()` (GSound,
`gir1.2-gsound-1.0` - a small freedesktop library for themed system sounds by event ID; `"camera-shutter"`
is the same event GNOME's own Screenshot tool uses) and `show_capture_complete_notification()`
(`Gio.Notification`, this app's existing `_notify()`-adjacent mechanism), plus two new checkboxes in the
Preferences Capture tab. `gir1.2-gsound-1.0` added to `debian/control`'s Depends.

**Timing turned out to need two different wiring points, not one**, discovered directly from live
feedback rather than assumed up front:

- X11's classic `Gtk.Menu` picker (`ui/destination_picker.py`'s `show_destination_picker`) calls both
  functions together, once, right at its own top - before the picker is shown, matching
  `DoCaptureFeedback`'s real timing. direflail confirmed this is the correct behavior on X11.
- The Wayland Shell-native path is architecturally different: the *entire* capture-then-show-picker
  round trip happens inside the bundled GNOME Shell extension's own JS code
  (`extension.js`'s `pickDestinationAsync`, shared by `CaptureRect`/`RegionSelectOverlay`/
  `WindowPickerOverlay`) as one opaque D-Bus call - Python's `dispatch_destination` only ever learns of a
  capture *after* the user has already picked a destination inside that JS-side menu. Calling the sound
  from `dispatch_destination` (the natural-looking place) fired it a beat late, direflail catching the
  asymmetry directly: "x11 plays the shutter sound when the popup window... comes up. wayland plays it
  after you select an option. the x11 way is how it should be." Fixed by registering a new
  `"play-capture-sound"` GAction (`app.py`'s `_register_tray_actions`) and having `pickDestinationAsync`
  invoke it, right before its own `menu.open(true)`, via the same `Gio.DBusActionGroup.activate_action`
  mechanism the tray button's own clicks already use (extracted into a shared `_activateOrcshotAction`
  helper, `extension.js`) - JS only signals *when*, Python still owns the actual on/off preference and
  the GSound call. `dispatch_destination` was correspondingly changed to call only
  `show_capture_complete_notification()`, not the sound half, avoiding a double-fire.

**A real, unrelated bug found and fixed along the way**: `ui/destination_picker.py`'s own internal
`show_destination_picker` → `dispatch_destination` delegation for its own menu-item clicks was refactored
to call the destination's `handler` directly instead, both to avoid double-firing feedback and because it
was doing a redundant second `_all_destinations()` lookup.

**A long, genuinely difficult diagnostic detour**: for most of this task's live-testing, the sound simply
never played at all, on Wayland, regardless of the preference - and neither of the temporary diagnostic
log lines added to trace it (first `console.log`, then the plain `log()` global, on the theory that
`console.log` might not route to journald the same way `logError`/`g_warning` reliably do - both already
used elsewhere in this file) ever appeared, across many rebuild-relogin-retest cycles. Also chased and
conclusively ruled out along the way: a real, reproducible Clutter/GJS crash
(`clutter_actor_set_allocation_internal` assertion failure, an actor trying to allocate
`-2147483648.00 x -2147483648.00`, a disposed `PopupBaseMenuItem`) that kept showing up nearby in the
journal - every `St.DrawingArea` this extension creates (region-select overlay, window-picker overlay,
eyedropper overlay, the tray/picker menu icons) was explicitly named (previously all "unnamed", GNOME
Shell's own default) specifically to settle this, and the crash *still* said "unnamed" every time,
including right after an actual capture - conclusively someone else's actor, not orcshot's, and later
confirmed to fire automatically ~15-20s after every login regardless of anything orcshot does. Root
cause of the real "no sound" mystery, found only after checking `journalctl --user -b 0 | grep -i
'orcshot\|extension'` for the *full* boot log rather than just a live `-f` tail: a **stale copy of the
extension in `~/.local/share/gnome-shell/extensions/orcshot-clipboard@orcshot.org`**, left over from
earlier per-user-override dev-testing (a legitimate, faster way to iterate on JS without a full package
reinstall), silently shadowing the
system-wide, `.deb`-installed copy at `/usr/share/gnome-shell/extensions/` on *every single login for the
entire session* - "Extension orcshot-clipboard@orcshot.org already installed in
/home/ubuntu2604/.local/share/gnome-shell/extensions/orcshot-clipboard@orcshot.org. /usr/share/gnome-shell/
extensions/orcshot-clipboard@orcshot.org will not be loaded" was sitting right there in the journal the
whole time, unnoticed. No amount of `sudo dpkg -i` + full logout/login was ever going to surface new JS
changes while that stale local copy existed - not a gap in the established "full logout/login reloads
`.js`" discipline, but a different failure mode entirely (a *local override* permanently beating the
*real* install, regardless of how many times the real one gets reinstalled or the session restarted).
Removing the stale copy (`rm -rf ~/.local/share/gnome-shell/extensions/orcshot-clipboard@orcshot.org`)
immediately fixed it - confirmed live, the very next test: **"camera sound works when enabled, does not
play when disabled."** All temporary diagnostics (the `print()`/`log()` calls, not the permanent actor
naming, which stays - cheap, real value for whatever the next Shell-side crash investigation turns out to
be) removed once confirmed.

**Defaults - both False, diverging from Windows' own True default for each, both per direflail's explicit
live-tested call, not assumed**:
- Play Camera Sound: the sound audibly lags the destination picker's own appearance by a beat on its
  first play of a session (GSound/canberra's first PulseAudio connection) - not a bug, but not a good
  enough first impression to default on.
- Show Notification: plays the same system `notification.oga` sound, but - unlike Windows' own version,
  a real per-destination outcome message - this port's simplified version just confirms a capture
  happened, information the user already has by definition. direflail, on realizing what the noise
  actually was: "did i ask for that? i don't want it."

**A real, adjacent bug found and fixed on the way to diagnosing this one - task #161** (see that task's
own write-up): while narrowing down whether the Wayland sound delay was capture-related at all,
direflail discovered Quit didn't actually stay quit against the global capture hotkeys. Cross-referenced
here since it surfaced mid-investigation, not folded into this write-up otherwise.

Note for anyone (including direflail, across either the VM or the real X11 machine) who explicitly
toggled either checkbox on during earlier testing, before these defaults were changed to False: `dpkg`
never touches `~/.config/orcshot/config.json`, so that earlier explicit choice persists across every
reinstall - the new False default only applies where the setting was never touched at all. If either
checkbox looks "on" after installing this build despite the new default, that's an earlier real choice
being correctly honored, not a bug.

Full suite green (1045 passed - 11 new tests in `tests/unit/capture/test_capture_feedback.py` covering
the settings-gating logic for both functions, individually and combined; 12 new tests in
`tests/unit/test_settings.py` for the two new settings' defaults/round-trips). The GTK/GApplication/GJS
wiring itself has no meaningful headless test, same precedent as the rest of this project's UI and
Shell-extension code - verified live instead, extensively, per this write-up above.

## Task #149: tool-palette overflow when the window is too short for the screen (fixed, verified live 2026-08-21)

Real Windows' `toolsToolStrip` (`ImageEditorForm.Designer.cs`) is a WinForms `ToolStrip`, which has a
built-in `OverflowButton`: when the strip's own tools don't all fit its available length, the ones that
don't fit collapse into a "»" dropdown automatically - Windows never has to think about which specific
tools to hide. This port's palette had no equivalent at all, so on a short screen (1366×768 was the
concrete case that surfaced it) the bottom few tools could run off the window entirely with no way to
reach them.

**Design detour, worth recording since it changed direction mid-implementation**: the first plan was a
curated fixed "More tools" button, moving four specific tools (direflail's own picks: Speech Bubble,
Effects, Obfuscate, Highlight) into a dedicated overflow menu, sized against a live measurement of the
real palette's per-row heights at 1366×768. That design was fully reasoned through - and then abandoned
before implementation, once direflail asked to revisit it: "can we replicate greenshot's behavior
without having things look weird" - i.e. dynamic, order-and-space-driven overflow like the real
`ToolStrip.OverflowButton`, not a hand-picked list that has to be re-curated by hand every time the
palette's own contents change. `Gtk.Toolbar`'s own native overflow mechanism
(`set_show_arrow`, on by default) turned out to be the direct GTK equivalent, so the palette was
rewritten from a plain `Gtk.Box` + `Gtk.RadioButton` (a deliberate earlier choice, made incidentally while
fixing an unrelated padding bug - see that method's own git history) to a real
`Gtk.Toolbar(orientation=VERTICAL)` + `Gtk.RadioToolButton`/`Gtk.ToolButton`, current work committed as a
rollback checkpoint (`37070db`) before starting, per direflail's own explicit request, in case the
architecture change didn't pan out.

**Verified live in isolation before touching the real palette**, via small standalone `Gtk.Toolbar(VERTICAL)`
test scripts run by direflail on both X11 (Mint/Cinnamon) and the Ubuntu 26.04 Wayland VM, rather than
assumed from GTK's docs:

- The overflow arrow does render and work correctly in vertical orientation, not just the far more common
  horizontal case.
- `set_is_important()` does **not** prioritize which items stay visible when space runs out - overflow is
  purely insertion-order + available space (the first N items that fit stay, the rest overflow in the same
  order), confirmed by items deliberately marked important still overflowing. So `_TOOL_LABELS`' own
  existing order (already citing real Windows' `toolsToolStrip.Items` order) is what decides what ends up
  in the overflow menu on a short screen - no separate curation needed.
- `Gtk.ToolButton`'s default auto-generated overflow-menu proxy is built from `set_label()` text, not the
  tooltip - a button with only a tooltip set produces a blank, item-less overflow menu when opened (live-
  reproduced: the popup appeared but had zero visible rows). Every palette button now sets both.
- Clicking an auto-generated proxy for a `Gtk.RadioToolButton` does correctly activate the real button
  (confirmed via a title-bar readout in the test script) - GTK's default proxy wiring is otherwise sound.

**A second, much more expensive round of live misdiagnosis, once the real palette was rewritten**: direflail
reported "x11 has some radio buttons on the left for some and icons for others... wayland does not have
this" while testing with a deliberately short window (to exercise the new overflow arrow). This was
initially - wrongly - diagnosed as Mint-Y's theme drawing a literal radio-dot indicator on
`Gtk.RadioToolButton`'s own CSS `radio` subnode in the *main toolbar*, and "fixed" twice with a screen-wide
`Gtk.CssProvider` targeting `.orcshot-tool-palette radio` - the first attempt (zeroing `min-width`/
`min-height`/padding/margin/`-gtk-icon-source`) blanked the tool icons entirely instead of removing a dot,
direflail's report ("the ones that had radio buttons now have nothing") immediately proving the whole
`radio`-subnode theory wrong rather than just imprecise. Per this project's own systematic-debugging
discipline, a third blind CSS guess was correctly refused - two failed fixes on the same hypothesis is the
threshold for stopping and re-establishing ground truth, not trying a third variant. A follow-up screenshot
with the window resized *tall enough that nothing overflowed at all* settled it conclusively: the main
toolbar had never been broken - every button showed a clean icon, no dot, on both platforms, unaffected by
either CSS attempt (which, in hindsight, couldn't possibly have reached the real cause anyway: a popped-up
`Gtk.Menu` isn't a descendant of the toolbar in the GTK widget tree, so a `.orcshot-tool-palette radio`
descendant-combinator selector was never going to match anything inside it). Both CSS attempts were removed
entirely once this was confirmed. The actual, correct target the whole time was the *auto-generated overflow
menu proxy items* - GTK's default text-only proxy for a checkable tool renders as a `GtkCheckMenuItem`,
which draws its own radio/check glyph (completely normal, expected menu chrome for any checkable row - not
a bug at all), while the equivalent proxy for a non-checkable one (Rotate CW/CCW/Resize) renders as a plain
row, explaining "these are the only ones with icons" on a theme that shows menu icons at all.

**That led to a genuine, separately-scoped follow-up** (direflail explicitly opted in via `AskUserQuestion`
once the actual gap was correctly identified): real Windows' own `ToolStripMenuItem` overflow entries do
carry the owning tool's icon; this port's overflow menu, on both platforms, showed text only, confirmed via
a from-scratch (X11) and Wayland screenshot with the window short enough to force overflow. Fixing this
required building an *explicit* icon-carrying proxy for every palette entry (`_icon_menu_item`, matching
`_build_menu_bar`'s own existing icon+label `Gtk.Box` pattern rather than the deprecated
`Gtk.ImageMenuItem`) instead of relying on GTK's own default. This surfaced one more real, non-obvious GTK
behavior, again only found by writing a small diagnostic script rather than guessing a third time: a plain
`Gtk.ToolItem.set_proxy_menu_item()` call made *before* the toolbar is ever shown is silently ignored for an
actual `Gtk.ToolButton`/`Gtk.RadioToolButton` - `retrieve_proxy_menu_item()` still returns a freshly
GTK-built `GtkCheckMenuItem`/`GtkImageMenuItem`, confirmed live by comparing object identity
(`id(set_proxy) != id(retrieved_proxy)`, wrong type too) across every button tested. `Gtk.ToolButton`'s own
default `"create-menu-proxy"` class handler evidently rebuilds its own proxy unconditionally rather than
checking whether one was already set. The base `Gtk.ToolItem` class (this file's own `Effects` wrapper,
`_build_effects_control`) has no such default handler at all, so a bare `set_proxy_menu_item()` call there
was never being fought over and worked correctly the whole time, unmodified. The fix for every actual
`ToolButton`/`RadioToolButton`, confirmed by the same diagnostic script (side-by-side `[MATCH]` vs
`[MISMATCH]` comparison): connect to the `"create-menu-proxy"` **signal** instead, build the icon-carrying
proxy from inside the handler, and return `True` - standard GTK signal convention for "handled, don't also
run the class default." Extracted into a shared `_connect_overflow_icon_proxy` helper, used by every plain
tool button, the Obfuscate/Highlight/Crop group buttons, and the Rotate CW/CCW/Resize action buttons.

**Also spun off, not part of this task**: while testing #149's overflow arrow specifically required manually
drag-resizing the editor window for what may be the first time since task #157 shipped
`Gtk.WindowPosition.CENTER_ALWAYS`, direflail hit a separate pre-existing bug (the window fighting an
interactive resize-drag, heading toward a screen corner on X11 only, never on Wayland) - confirmed via `git
diff` against this task's own starting commit that nothing in this task's changes touches window
positioning at all. Filed as its own task (#162) rather than folded in here.

Full suite green (1045 passed, 3 skipped, no new failures - `PYTHONPATH=src` needed to run against this
checkout rather than the system-installed `.deb` copy at `/usr/lib/python3/dist-packages/orcshot`, a
reminder this project has hit before, same underlying "the edited source isn't necessarily the one that's
actually running" lesson as task #158's stale-extension-copy investigation). No new automated tests -
`_build_tool_palette` and its overflow wiring have no meaningful headless test, same precedent as the rest
of this project's GTK UI code; verified live instead, on both X11 (Mint/Cinnamon, this dev machine) and the
Ubuntu 26.04 Wayland VM, including: full palette at normal size, keyboard shortcuts, Effects' own dropdown,
Rotate CW/CCW/Resize, and - on a deliberately shrunk window on both platforms - the overflow arrow
appearing, every entry (including Highlight/Obfuscate/Crop and Effects' own submenu) showing a correct
icon, and every overflow entry correctly activating its tool when clicked.

## Task #162: editor window fought a manual X11 resize-drag, heading for a screen corner (fixed, verified live 2026-08-21)

Surfaced as a side effect of testing #149's new overflow arrow, which - for maybe the first time since
task #157 shipped `Gtk.WindowPosition.CENTER_ALWAYS` - required direflail to manually drag-resize the
editor window rather than just opening it and leaving it alone. On X11 (Mint/Cinnamon) only, dragging an
edge to resize (either growing or shrinking) made the window head toward a screen corner instead of
resizing normally, only letting the drag "stick" once it got there. Confirmed via `git diff`/`git log`
that this was pre-existing, not introduced by #149's palette rewrite - nothing in that task's own diff
touches window positioning at all.

**Root cause, confirmed by reading #157's own git history (`b3428dc`, `f8ffa33`) rather than guessed**:
`CENTER_ALWAYS` was added specifically because `_resize_canvas_and_window` (a `GLib.idle_add` callback
that grows the window from its default small map to fit the actual captured image, shortly after first
show) calls `self.resize()`, and `resize()` always grows/shrinks a window from a fixed top-left anchor
regardless of any `WindowPosition` hint - a `WindowPosition` hint only ever affects the very first
placement decision, not later explicit `resize()` calls. Without re-centering after that one deferred
resize, a large captured image could end up visibly shifted toward the top-left. `CENTER_ALWAYS` was the
blunt instrument reached for at the time: it re-centers on *every* size-changing event GTK sees, which
turned out to include the window manager's own interactive-resize-drag configure-events, not just this
port's own explicit `resize()` calls - GTK has no way to distinguish the two once subscribed to
`CENTER_ALWAYS`'s blanket mechanism. (Also confirmed via that same history: `CENTER_ALWAYS` was never
actually necessary for #157's own real bug, a genuinely separate issue in `show_all()`'s ordering - see
that task's own write-up.)

**Fix**: `Gtk.WindowPosition.CENTER` (initial placement only, not continuous) instead of `CENTER_ALWAYS`,
plus an explicit, one-shot `self.move()` call added directly inside `_resize_canvas_and_window`, right
after its own `self.resize()` - computed from the same `work_area` that method already fetches for
clamping. This keeps re-centering exactly where it's actually needed (every place this port's own code
resizes the window: the deferred initial grow-to-fit, zoom changes, whole-image effects) while never
touching a resize the window manager itself is driving on the user's behalf. No-op on Wayland either way
(`move()` is a documented no-op there), matching `CENTER_ALWAYS`'s own prior Wayland behavior exactly -
this only changes anything on X11.

Confirmed live (direflail, X11/Mint): dragging an edge now resizes normally in both directions, and a
freshly-opened editor still lands centered on screen. Full suite still green (1045 passed, 3 skipped).

## Task #149 follow-up: confirm a real capture doesn't open oversized on Wayland (verified 2026-08-21)

direflail asked to specifically double-check editor windows aren't opening too tall for the screen on
the Wayland VM, since #149's overflow work is a good moment to revisit it (a Wayland "too tall" symptom
had been observed there "for a while"). A synthetic test (`EditorWindow` opened directly with an image
taller than the monitor's own full geometry, run via the dev source tree rather than an installed
package) showed correct clamping and canvas-scrolling fallback on both X11 and the Wayland VM - no
overflow in either case. direflail then flagged that the dev-source testing path this whole task's live
verification had used doesn't reflect what's actually *installed* on the VM, which turned out to be the
real explanation: rebuilding a fresh `.deb` from the current tree (`dpkg-buildpackage -us -uc -b`,
running the full suite as part of the build) and installing it on the VM via `sudo dpkg -i` (direflail's
own terminal, since the VM has no GUI package installer available the way Mint's does) confirmed a real
capture opens correctly sized, with the new overflow button present. The earlier "too tall" observation
was against a stale previously-installed build, not a live bug in the current code - no fix needed here,
just confirmation.

## Task #113: Wayland Shell-native picker now shows ExternalCommand entries (fixed, verified live 2026-08-22)

The Wayland Shell-native destination picker (`extension.js`'s `pickDestinationAsync`, used for
region-select/window-picker/active-window/last-region capture) had its own hardcoded copy of just the
five built-in destinations (`clipboard`/`save`/`save_as`/`edit`/`print`) - it never showed the "Office"
destination or any configured ExternalCommand entry (task #110), both of which the X11 classic
`Gtk.Menu` path (`destination_picker.py`'s own `show_destination_picker`) already handles correctly via
`_all_destinations()`.

**Fix**: `destination_picker.py` gets a new `destinations_for_shell()` - `(id, label, geometry_key)`
triples built from the same, already-filtered `_all_destinations()` every other path already uses, with
each entry's handler dropped (Python-only, meaningless once serialized to JS). `app.py`'s
`OrcshotApplication` gets a `do_dbus_register` override exposing this as a real D-Bus method call
(`org.orcshot.Orcshot.Destinations.GetDestinations`) - a GAction wouldn't work here since
`activate_action()` is fire-and-forget with no return value (confirmed against `_activateOrcshotAction`'s
own docstring). `extension.js`'s `pickDestinationAsync` now calls this via
`Gio.DBusProxy.call_sync`/`GetDestinations` instead of iterating a hardcoded `DESTINATIONS` array, which
is deleted entirely - JS is now a pure renderer with no destination list or icon-mapping of its own left
to drift out of sync with Python.

**The one real design gap, closed properly rather than worked around**: X11's `destination_icon_image`
already fell back to a generic hand-drawn "terminal prompt" glyph (`_external_command_icon`) for both
"office" and any `external:*` id (neither has one fixed action to depict) - but that fallback was a
one-off Cairo function, never added to `icon_geometry.json` (task #143's shared-icon-data mechanism), so
`extension.js` had no way to draw it. Added a new `"external-command-symbolic"` geometry key (hand-derived
from `_external_command_icon`'s own simple Cairo calls: a rounded-rect stroke + two line-segment
strokes), verified byte-identical to the original function's output the same way task #143 verified every
other shared icon - a pixel-diff against the pre-change render. `_external_command_icon` is now dead code
and deleted; `destination_icon_image`/the new `destination_icon_geometry_key` both go through the
geometry-JSON path uniformly, no more special-casing.

**A real, non-obvious bug caught by that pixel-diff, not assumed away**: the first geometry attempt set
`line_width`/`line_cap`/`line_join` *before* the rounded-rect stroke, reasoning this was "safer" than
relying on Cairo's implicit defaults - which introduced a genuine 1-value-per-channel diff at the shape's
anti-aliased edges. Checked live (`ctx.get_line_cap()`/`get_line_join()` on a fresh context) rather than
recalled from memory: Cairo's real defaults are `BUTT`/`MITER`, not `ROUND`/`ROUND` - the original
hand-drawn function relied on exactly that default for its first stroke, and explicitly forcing
round/round early changed the rendering. Reordering the ops to match the original's exact sequence
(style-setting only *after* the first stroke) produced true byte-identical output, confirmed by comparing
both renders through the *same* Cairo-surface-to-numpy conversion path (an earlier comparison attempt
that mixed two different conversion paths - raw `cairo_surface_to_numpy` vs. the `Gdk.Pixbuf`-mediated
route the new code actually uses - produced a misleading ±1 diff that was a comparison-methodology
artifact, not a real rendering difference; re-verified through one consistent path before trusting the
"identical" conclusion).

**TDD throughout** (both `destination_picker.py` and `icons.py` had zero prior direct test coverage for
the touched functions - added tests for the existing untested behavior too, not just the new code):
`tests/unit/ui/test_icons.py` (2 new tests, one deliberately watched RED first via the missing geometry
key's `KeyError`), `tests/unit/ui/test_destination_picker.py` (new file, 4 tests for
`destinations_for_shell` - including one that had to explicitly mock out `_find_office_command`, since
this dev machine has `soffice` installed and would otherwise silently add a real 6th "Office" entry,
making the test depend on what's installed on whatever machine runs it rather than on the function's own
behavior).

**Verified live end-to-end**, not just unit-tested: built a full binary `.deb` from the working tree and
installed it fresh on the Ubuntu 26.04 VM (matching how every other Shell-extension change in this
project gets verified - no automated test framework covers GJS/Shell code here). Confirmed via a real
region-select capture: the Wayland picker now shows a configured ExternalCommand entry
("krita") dynamically, with the correct icon, and clicking it correctly launches the command (the actual
D-Bus round-trip and destination dispatch both work) - though that same test surfaced two real, separate,
pre-existing bugs unrelated to this task's own change (filed as their own tasks rather than folded in
here): a Snap-confined target app (Krita via `/snap/bin/krita`, not Flatpak) apparently can't read the
exported handoff file, and copying a capture to clipboard doesn't cross the VM's guest→host clipboard
boundary at all (no error, no output) - the latter looking more like a VirtualBox shared-clipboard
platform limitation than an Orcshot bug, not yet confirmed either way.

Full suite green (1052 passed, 3 skipped - 6 new tests, 1046 pre-existing).

## Task #166: Snap-confined external commands couldn't read their handoff file (fixed, verified live 2026-08-22)

Surfaced live while testing task #113's new dynamic destination picker: a Krita ExternalCommand entry
(`/snap/bin/krita`) showed up correctly in the Wayland picker and launched, but Krita immediately threw
"Cannot open file for reading" against the exported screenshot. `run_external_command`
(`ui/external_commands.py`) writes that handoff file via `orcshot_cache_dir()` - `~/.cache/orcshot/`,
already fixed once (Flatpak's `/tmp` being a private, invisible tmpfs to a sandboxed app) but never tested
against a *Snap*-confined target before now.

**Root cause, confirmed live rather than assumed**: Snap's `home` interface (the permission that grants a
confined snap filesystem access to the user's home directory) explicitly excludes any path with a hidden,
dot-prefixed ancestor - and every XDG convention (`~/.cache`, `~/.config`, `~/.local`) is hidden by
definition, the opposite of Flatpak's more commonly-granted `xdg-cache` permission that made
`orcshot_cache_dir()` work for Flatpak targets in the first place. Confirmed with a real, standalone
repro (not assumed from Snap's general documented behavior): running `/snap/bin/krita` directly against a
manually-placed file at that exact path, entirely outside Orcshot's own code, reproduced the identical
error - ruling out any race/timing theory. The same run's stderr also independently confirmed active
AppArmor enforcement (`label="snap.krita.krita (enforce)"`).

**Fix**: `_is_snap_command()` (`external_commands.py`) detects a Snap target by checking whether its
resolved commandline lives under `/snap/` - Snap always installs its own CLI entry points at
`/snap/bin/<name>`, no need to shell out to `snap` itself. `run_external_command` routes to a new
`orcshot_visible_temp_dir()` (`file_export.py`) - a plain, non-hidden `~/Orcshot` folder - instead of
`orcshot_cache_dir()` when a Snap target is detected. Either way, the handoff file is now deleted once the
command finishes (success, failure, or timeout - `subprocess.run`'s own timeout already blocks until one
of those happens either way), so the new visible folder doesn't accumulate temp screenshots the way the
hidden `.cache` one silently already had been.

**A real bug in the first attempt, caught by live testing rather than assumed away**: the initial
`_is_snap_command` used `os.path.realpath()` to resolve the commandline before checking the `/snap/`
prefix - which turned out to defeat the whole check. Confirmed live: `/snap/bin/krita` is itself a
symlink to `/usr/bin/snap` (snapd's own generic launcher, which inspects the symlink's own name to decide
which snap to actually run), so `realpath` resolved straight past the one signal being checked, to a
target that's never under `/snap/` at all. Fixed by using `os.path.abspath()` instead (normalizes the
path string without following symlinks), with a regression test that mocks `realpath` to lie about where
the path "really" points, proving detection no longer depends on it.

**A second, separate false lead before finding the real problem**: after the `realpath`→`abspath` fix,
a rebuilt-and-reinstalled `.deb` still showed the identical old error. Restarting the systemd `--user`
service didn't help either. Root cause: the local build and the VM's installed package had ended up on
the *same* version number (`0.1.0-5`) across two separate rebuilds in the same session, reusing that
version for a `dpkg -i` reinstall - the installed files on the VM never actually updated, confirmed
directly (`grep` on the VM's own installed file still showed the old `realpath` code, while the same grep
against the freshly-built `.deb`'s own extracted contents showed the fix was genuinely there). Bumping to
a new version number (`0.1.0-6`) for the next rebuild resolved it immediately - worth remembering for any
future same-session iterative VM testing, not just real releases.

**Verified live end-to-end** on the Ubuntu 26.04 VM: a real capture sent to the Krita external command now
opens directly in Krita with no error, from the new `~/Orcshot` folder.

TDD throughout (`_is_snap_command`, `orcshot_visible_temp_dir`, and `run_external_command`'s
directory-routing/cleanup logic all test-first). Full suite green (1062 passed, 3 skipped).

**Spun off, not done here**: task #168, auditing the rest of the project for other places X11 and
Wayland (or here, "any sandboxed target") might have quietly diverged the way this one very nearly
looked like it had, before confirming `run_external_command` is genuinely shared, unforked code and the
real story was Snap confinement instead.

## Task #171: filename pattern saved a literal, unresolved `${...}` filename - redesigned to one unified
pattern language instead of patched (fixed, verified live 2026-08-23)

Live-reported (direflail): a real screenshot saved with the literal filename
`${YYYY}-${MM}-${DD} ${hh}_${mm}_${ss}.png`, not an actual timestamp. Root-caused against direflail's own
`~/.config/orcshot/config.json`: `filename_pattern` still held the old Greenshot-style `${...}` text while
`filename_pattern_mode` had drifted to `"strftime"` - a combination that was never valid under either mode
as designed (strftime mode never parses `${...}` at all). Confirmed via git history, not assumed: task
#127/#128 changed `DEFAULT_FILENAME_PATTERN`'s own *value* (Greenshot-style → strftime-style) in the same
commit that changed `filename_pattern_mode`'s default - but `get_output_settings()`'s save-merge logic
(`{k: v for k, v in saved.items() if k in defaults}`) has no versioning concept at all, so any config
written before that commit kept its old pattern *text* forever while silently inheriting the new mode
default the next time the app ran. Cross-checked orcshot's own token catalog against the real Greenshot
reference source (`FilenameHelper.cs`) before designing a fix, not just this port's own comments about
it: `${YYYY}`/`${MM}`/`${DD}`/`${hh}`/`${mm}`/`${ss}` and their exact zero-pad widths (4/2/2/2/2/2) are
genuine, faithfully-ported Greenshot tokens (`case "YYYY":`, etc.) - the old default wasn't a mistake or
an invention, just a value nothing ever migrated.

**direflail's own call, once the actual root cause was understood**: rather than detecting and repairing
the stale combination (a translator between the two syntaxes was designed and prototyped first, then
discarded), retire the `mode` concept entirely. `${TOKEN}` substitution and strftime's own `%` directives
are now both always active in the same pattern, resolved in that order - `${...}` first, then the result
handed to `datetime.strftime()`. This doesn't just fix the reported bug, it makes the underlying bug class
structurally impossible: there's no longer a separately-persisted mode field that can drift out of sync
with the pattern text, so an old Greenshot-style pattern just resolves correctly under the new unified
resolver regardless of what a since-deleted mode field used to say next to it.

**The corruption risk the original two-mode split existed to prevent, re-examined rather than assumed
gone**: strftime's own `%` is genuinely ambiguous next to arbitrary text (confirmed live in an earlier
session: `strftime("a%screenshot.png")` silently ate the "s"), which is exactly why `${...}` and `%` were
kept mutually exclusive in the first place. Verified live (via a real Python prototype, not just reasoned
about) that unifying them doesn't reopen this: every *substituted* token value is percent-escaped before
strftime ever sees it - the only new "%" that could reach strftime from this module's own substitution is
inside a value the user doesn't directly type (a captured window's title, in particular), and that's
exactly what gets escaped. The user's own raw "%" directives in the pattern text are untouched and behave
exactly as documented, standard strftime always has.

**A second, real feature added alongside the fix, not scope creep**: direflail proposed a new
`${"affix"?TOKEN}` conditional form - renders nothing at all if TOKEN has no value, or the literal affix
text immediately followed by TOKEN's value if it does (e.g. `${" - "?title}` renders " - My Window", or
nothing at all with no title). This replaces the previous strftime-mode-only special case that
unconditionally auto-appended " - {title}" whenever a title existed, with no way to opt out or reposition
it - checked against the real Greenshot source first: `FilenameHelper.cs`'s own `case "title":` is a
plain, unconditional token with no special-casing at all (`replaceValue = title`), and real Greenshot's
actual default pattern (`${capturetime:d"..."}-${title}`) just accepts a dangling "-" before the extension
on a title-less capture as a result. The new conditional form gets the best of both: `${title}` is now a
fully ordinary, explicit, positionable token like any other (faithful to the real app, no resolver-level
magic), while `DEFAULT_FILENAME_PATTERN` itself
(`'%Y-%m-%d %H_%M_%S${" - "?title}'`) avoids that dangling-separator wart structurally, via pattern text
alone.

**Cleanup, not just the fix**: `MODE_GREENSHOT`/`MODE_STRFTIME` constants, the `OutputSettings.
filename_pattern_mode` field, the "Pattern style" combo box in Preferences, and `resolve_filename_
pattern`'s own `mode` parameter are all deleted outright, not deprecated. Removing the field from the
dataclass is itself the entire migration for old configs - the existing saved-keys-filtered-by-known-
fields merge logic already silently drops a now-unrecognized `filename_pattern_mode` key with no explicit
migration code needed. The Preferences Output tab gained a "Default" button next to the pattern field
(direflail's own request) that fills in `DEFAULT_FILENAME_PATTERN` directly.

TDD throughout, including a live-verified regex/resolver design (a small standalone Python prototype
proved the `${"affix"?TOKEN}` grammar, the percent-escaping, and the exact worked example direflail gave -
`%Y${" - "?title}` renders "2026" with no title, "2026 - test title" with one - before any of it was
written into the real module). Full suite green (1119 passed, 3 skipped). Verified live against the real
installed `.deb`, not just unit tests: rebuilt, reinstalled, opened the real Preferences dialog
(screenshotted), confirmed the mode dropdown is gone and the Default/`?` buttons both work as designed.

## Task #172: Primary output format observed as TIFF instead of PNG - investigated, closed unreproduced
(2026-08-23)

Live-reported (direflail): Preferences -> Output tab's "Primary format" was set to TIFF, not PNG, causing
quick-saves to write `.tiff` files. Fixed manually (switched back to PNG) before it could be inspected
live, so direct evidence of *how* it happened doesn't exist - this entry records the investigation that
followed, not a fix, since none was needed once nothing wrong could be found.

**Checked and ruled out, not just read past**: `OutputSettings.primary_format`'s dataclass default
confirmed `"png"` via a genuinely fresh config (no prior `output_settings` key at all) - `get_
output_settings(path=<fresh temp path>)` returns `primary_format="png"` every time, ruling out a
first-run-path bug specifically. Every real write path (`editor_window.py`'s handful of `update_output_
settings`/`set_output_settings` call sites) goes through `dataclass_replace(get_output_settings(), **
changes)` - always reading current settings first and replacing only the one changed field - never
reconstructing a fresh `OutputSettings()` from scratch, so there's no path where writing one field could
silently clobber another back to a wrong value. The format combo box's own `set_active_id()` call runs
before `.connect("changed", ...)` is attached, so loading the saved value into the widget can't itself
spuriously fire a write back to disk. Also checked whether this was the same *class* of bug as task #171
(a coded default that changed value over time, with an old config never migrated) - git history rules
this out too: `primary_format`'s default has always been `"png"`, never anything else, in every commit
that touches it.

**Closed as unreproduced**, direflail's own call - genuinely doesn't understand how it happened, hasn't
seen it before or since, and a real investigation found nothing wrong in the code paths that could cause
it. Documented here rather than just dropped, specifically so a recurrence doesn't require re-deriving
this same investigation from scratch - if it happens again, this write-up is the starting point, and the
fact that a first pass found nothing is itself useful information (points toward something environmental,
a one-off manual selection, or a trigger this investigation didn't think to check, rather than a repeat
of an already-understood mechanism).

**Aside, found while investigating, not itself the cause**: `editor_window.py`'s `_SAVE_AS_FORMATS`
includes `("gif", "GIF")` as a selectable primary format, but `file_export.py`'s `_EXTENSION_TO_TYPE` has
no `".gif"` entry - picking GIF as the primary format would silently save as PNG instead
(`_EXTENSION_TO_TYPE.get(path.suffix.lower(), "png")`'s own fallback). A real, separate, minor latent bug,
left unfixed here since it's unrelated to what was actually reported.

## Task #168: audit for unintentional X11/Wayland backend divergence - one real fix shipped, findings sorted
(2026-08-23)

direflail's own request (2026-08-22), prompted by confirming task #166 (Snap-confined external commands)
affects both platforms identically since `run_external_command` is genuinely shared code: "honestly that
should go for everything in this project. make a task to audit that." Scope: a systematic review of every
feature existing on both X11 and Wayland, checking whether each one shares one backend implementation
versus having quietly grown two separate, potentially-drifting ones - and, the opposite failure shape, a
single shared code path that behaves correctly on one platform and incorrectly on the other.

**Audit covered** `capture/`, `ui/`, and the bundled GNOME Shell extension (`extension.js`, 2227 lines,
read in full). **Confirmed correctly unified**, worth naming as good examples, not just non-findings:
`backend_select.py`'s single X11/Wayland decision point; `icon_geometry.json`'s shared-data pattern (task
#143), still paying off for more than its original 5 tray icons; `capture/gdk_screen_layout.py`'s
monitor-geometry code, shared verbatim; the window-capturability filter (`capture/window.py`); capture-
feedback sound/notification (task #158, already fixed); and three `ui/*_wayland.py` files that correctly
import their constants from the X11 sibling rather than copying them (`eyedropper_wayland.py`,
`window_picker_wayland.py`, `region_select_wayland.py`).

**Real divergence found and fixed this same pass**: the magnifier/eyedropper/selection-overlay numbers
(patch size, gap, diameter divisor/rounding, ring/crosshair sizes, the eyedropper's fixed loupe size, every
overlay color) were independently hardcoded a fifth time in `extension.js` - the exact #143 shape, never
given the `icon_geometry.json` treatment. Fixed via a new `magnifier_constants.json`, shared the same way -
see this same file's "Task #168: share magnifier/eyedropper/selection-overlay constants with extension.js"
commit (also documented in `BACKLOG.md`'s former #168 entry, now closed) for the full write-up, including
why only the *values* could be shared, not the offset-search algorithm itself (GJS can't import Python -
a completely separate process).

**Correction, added during task #174 below**: that commit's own "verified live" claim (via `gnome-
extensions disable/enable` on the VM) turned out not to be real verification - `disable()`/`enable()`
doesn't force GJS to re-import the module, so the old module (with value-identical hardcoded constants)
was almost certainly still what actually ran. Retroactively confirmed genuine via task #174's own real VM
reboot instead - see that entry for the full story of how this was caught and why the module-level
JavaScript execution model makes that retroactive confirmation valid.

**Real divergence found, not fixed here** - spun off as `BACKLOG.md` #174: `settings.
get_show_magnifier_while_selecting()` is honored by both X11 and the Wayland portal-fallback path, but
never read at all by the Wayland Shell-native `RegionSelectOverlay` - already self-documented as a known
gap elsewhere, confirmed still live.

**Two genuine "needs live hardware" gaps investigated, not just re-flagged** - `capture/gnome_window_calls.
py`'s `Meta.WindowType` index-to-name mapping was one of three items initially filed as "uncertain," but
turned out fully resolvable *without* live hardware: Muffin (Cinnamon's own Mutter fork) ships the same
public enum via local GI introspection data, and a direct index-by-index comparison confirmed correct - all
16 indices match. **Closed, not a gap.** The other two - `capture/wayland.py`'s crop-offset origin
assumption (spun off as `BACKLOG.md` #175, also independently found restated repeatedly elsewhere in this
file, going back to task #49) and cross-monitor drag continuity across separate per-monitor `MonitorWindow`
instances (spun off as `BACKLOG.md` #176, narrowed from the original vague "cross-monitor handoff" framing
to the specific unanswered question - does an *in-progress drag* survive crossing a monitor boundary, not
just ordinary event routing, which is sound and universal) - remain genuinely open, needing real
multi-monitor Wayland hardware neither the code nor this project's single-monitor VM can settle.

**A second, separate audit pass** swept `REQUIREMENTS.md` itself (this file) for other cases of the #93/
i18n shape - real deferred work sitting undiscovered inside an entry tagged as complete. Found six more:
task #111 ("Reuse Editor" setting, assigned a number, never built, referenced as still-missing days later,
then never mentioned again), the same multi-monitor crop-offset gap independently rediscovered (confirming
#175 above rather than adding a new item), the GIF-primary-format bug (already captured in this file's own
task #172 entry above), the same Wayland-magnifier-setting gap independently rediscovered (confirming #174
above), the "Online Help" menu item linking to a bare GitHub repo instead of real help content (a
content-writing follow-up that was promised and never happened), and Insert Window never getting the nicer
Wayland Shell-native picker overlay (`force_plain_overlay=True`, a known, deliberately-scoped gap never
revisited). Not yet triaged into `BACKLOG.md` - direflail's own call pending on which are worth tracking
formally versus letting go.

## Task #177: "Online Help" menu item now actually opens the wiki (fixed 2026-08-23)

Filed and closed the same session it was found. `_do_open_online_help`'s own docstring had said "real
help-page content... doesn't exist yet" since task #95 part 1 - true then, no longer true once the wiki
gained real content earlier this same session (the "Destinations" page). Re-checked against current code
before filing to `BACKLOG.md` as #177, rather than trusting the older write-up as still accurate - found
`_WIKI_URL` (task #142's own constant) already existed in the same file, just wired to a different help
dialog. One-line fix: `_do_open_online_help` now opens `self._WIKI_URL` instead of the bare repo root. Full
suite green (1121 passed, 3 skipped, unchanged - no test coverage existed or was added for this GTK
glue/`webbrowser.open` call, consistent with this file's own established convention).

## Task #174: "Show magnifier while selecting" now honored by the Wayland Shell-native overlay (fixed,
verified live 2026-08-23) - plus a real correction to an earlier verification claim this same session

Fix itself is small: `StartRegionSelect` (the D-Bus method `gnome_region_select.py` calls to run the whole
Shell-native selection flow) gained one new in-arg, `showMagnifier` - `gnome_region_select.py` now passes
`settings.get_show_magnifier_while_selecting()` through; `extension.js`'s `RegionSelectOverlay` stores it
and gates `_sampleLoupe` (the actual `Shell.Screenshot.composite_to_stream()` grab, not just the draw step
- `_onRepaint`'s own "if (this._loupePixbuf !== null)" check already means never populating it is enough
to also stop it drawing, no second gate needed). One real implementation subtlety caught before it became
a bug: `StartRegionSelectAsync`'s own `parameters` arg does NOT need `.deepUnpack()` on this GJS version -
confirmed by re-reading `CaptureRectAsync`'s own already-live-verified comment on the exact same question
(task #150) instead of assuming a generic GJS pattern.

**The real story of this task is a verification methodology bug, not just a feature gap - worth recording
in full.** Testing on the Wayland VM via `gnome-extensions disable/enable` (used earlier this same session
to "verify" task #168's magnifier-constants-sharing fix, and used again here) produced a completely
misleading result: the extension reported `State: ACTIVE` with zero errors, region-select worked
end-to-end - and yet a direct `gdbus call` to `StartRegionSelect` with the new boolean argument came back
with "Introspection data indicates 0 parameters but more was passed." **The running Shell process was
still serving the old, pre-edit interface**, despite the JS file on disk (confirmed directly) having the
new one. `disable()`/`enable()` re-invokes those lifecycle methods on the *same already-imported* module
instance - it does not force GJS to re-import the module file, so a module-level `const` like `CAPTURE_IFACE`
(a string literal baked into the module at import time) never picks up an edit until the module is
genuinely re-imported, which - on Wayland, no in-place Shell restart being possible - means a real
logout/login or reboot, not a disable/enable toggle.

This means task #168's own "verified live" claim, made earlier this same session, was not actually
verified - the old module's hardcoded magnifier constants happen to be value-identical to the new
JSON-loaded ones (that was the whole point of the refactor: a pure, no-behavior-change migration), so
"zero errors, correct-looking values" was consistent with the stale module never having reloaded at all.
Caught only because *this* task's change (a genuine interface/signature change, not just internal
constant-loading) produced an observable difference a value-identical refactor couldn't have. Retroactively
confirmed as a happy accident rather than a real gap, though: a real VM reboot (`VBoxManage controlvm
... reset`, no guest credentials needed - graceful `sudo reboot`/`systemctl reboot` both require
interactive polkit auth that a non-interactive guest-control session can't satisfy) forced a genuine
module re-import, confirmed directly via `gdbus introspect` showing the correct new `StartRegionSelect`
signature - and because a JS module's top-level code executes atomically, that one piece of live evidence
confirms *every* top-level line in the module ran fresh, including #168's own constants-loading code, not
just this task's own change. Both fixes are now genuinely, not just apparently, verified live.

**A second real bug found live as a side effect of the reboot, not this task's own subject** - spun off as
`BACKLOG.md` #180: a stale, pre-task-#141 XDG autostart entry on this VM raced `orcshot.service` at boot,
reproducing task #170's exact orphaned-process symptom from a third, untouched launch path. See that
backlog entry for the full write-up; cleaned up manually on this VM, not fixed in code.

Both magnifier-setting directions confirmed live post-reboot: disabled -> no magnifier while dragging;
re-enabled -> magnifier shows again. Full suite green (1121 passed, 3 skipped) - this D-Bus call itself
has no unit coverage, consistent with `gnome_region_select.py`'s own established "only verified live"
convention for the same reason `test_gnome_region_select.py` already states.

## Task #175: multi-monitor Wayland crop-offset origin assumption - closed for GNOME (2026-08-23)

Long-standing concern (`BACKLOG.md`, restated at least five times across earlier `REQUIREMENTS.md`
entries): `capture/wayland.py`'s `_crop_to_rect` assumes the portal's screenshot starts at the virtual
screen's own origin (`bounds.left`, `bounds.top`), untested against real multi-monitor Wayland hardware
because this project's only Wayland rig was a single-monitor VM.

Genuinely closed this time, not just re-deferred: gave the Ubuntu 26.04 VM a real second monitor
(`VBoxManage modifyvm --monitorcount 2`, then `controlvm setscreenlayout` - discovered along the way that
this API requires every screen's layout in one atomic call; issuing them per-screen fails with
`NS_ERROR_INVALID_ARG` even with otherwise-valid arguments). Rather than fighting VirtualBox's own
absolute-mouse-integration desync across two separate screen windows (a real, reproduced quirk after
forcing a layout outside the guest's normal auto-resize negotiation), drove GNOME's own
`org.gnome.Mutter.DisplayConfig.ApplyMonitorsConfig` directly via `VBoxManage guestcontrol` (credentials
in the gitignored `vmpw.txt`, username `ubuntu2604` - not `direflail`, corrected after an initial failed
logon attempt) to attempt a genuinely negative-origin arrangement (monitor 2 at x=-1366).

Mutter rejected it outright, live: `"Invalid logical monitor position (-1366, 0)"`. Traced to source rather
than accepted at face value - fetched upstream Mutter's `meta-monitor-config-manager.c` and confirmed
`meta_verify_logical_monitor_config` unconditionally rejects any logical monitor with x<0 or y<0 before
applying any layout at all, no exceptions. This is doubly confirmed, not just a docs claim: the live VM's
own rejection message matches that exact source pattern verbatim, so whatever Mutter version Ubuntu
26.04 actually ships enforces the same rule.

**This flips the original question.** The task was never going to find a real negative-origin monitor to
capture from, because GNOME structurally cannot produce one - not a gap in this project's test rig, a real
guarantee of the compositor itself. Since `ScreenLayout.virtual_bounds` (`capture/backend.py`) is the union
of individual monitor bounds, and every individual monitor origin is guaranteed non-negative by Mutter,
`bounds.left`/`bounds.top` can never be negative on GNOME either. `_crop_to_rect`'s own comment (previously
"NOT YET verified... bounds.left/top can be negative") was rewritten to state this as a proven guarantee,
not an open question, with the citation trail.

Deliberately left open, narrow, and low-priority (`BACKLOG.md` #181, this entry's own narrowed successor):
orcshot's Wayland path reads monitor geometry through GDK's compositor-agnostic enumeration
(`gdk_screen_layout`), not a GNOME-specific API, so a non-GNOME Wayland compositor could in principle use a
different coordinate convention - not checked, since orcshot's Wayland support is built around a bundled
GNOME Shell extension and was never a supported target elsewhere.

## Task #180: stale pre-migration XDG autostart entry raced orcshot.service at boot (fixed 2026-08-23)

Found live (2026-08-23) as a genuine side effect while verifying task #174 on the Wayland VM, not by
inspection: a real, reproducible boot-time instance of task #170's exact symptom (`systemctl status`
showing `inactive`/exited-0 while a real, working, untracked process owns the D-Bus name), but from a
*different* trigger than #170's own fix covers.

Root cause: `~/.config/autostart/orcshot.desktop` (dated well before task #141's systemd-unit migration,
`Exec=/usr/bin/orcshot` - a bare exec, plus a stale dev-checkout icon path) was still present on that VM.
GNOME session's own XDG-autostart mechanism launches it independently of, and racing against,
`orcshot.service`'s own `WantedBy=graphical-session.target` startup - confirmed live: after a real VM
reboot, `orcshot.service` itself exited cleanly within 3ms (the *correct*, safe forwarding behavior for a
second instance losing the race, not a crash), while a separate, systemd-untracked process from the
autostart entry ended up owning `org.orcshot.Orcshot` on the session bus.

Not a flaw in task #170's own fix - that fix wraps the *current* entry points (the Applications-menu
`.desktop` file, the four global hotkeys) and correctly prevents *those* from racing. This was a third,
independent launch path #170 never touched, left over from before `autostart.py` was rewritten (task #141)
to manage a systemd unit instead of writing its own XDG autostart file. That migration's own docstring
documented *what* replaced the old mechanism but never mentioned cleaning up a file a previous version had
already written - any real install that had autostart enabled before that migration carried this exact
stale file forward, silently, forever.

Fixed with the smallest change that actually closes the gap for already-affected installs, not just new
ones: `autostart.py` gained `remove_legacy_autostart_entry()` (TDD, `tests/unit/test_autostart.py`, 3 new
tests), deleting `$XDG_CONFIG_HOME/autostart/orcshot.desktop` if present via `Path.unlink(missing_ok=True)`
- naturally idempotent, so unlike `maybe_seed_default_external_commands` there's no separate "already ran"
flag to persist. Considered gating it behind `enable_autostart()`/`disable_autostart()` (only firing on an
explicit Preferences checkbox toggle) but rejected that: a user who already has the stale file and never
touches that checkbox again would keep racing at every boot forever, which wouldn't actually fix the bug for
the affected population. Called unconditionally from `app.py`'s `do_startup`, next to
`maybe_seed_default_external_commands()`'s own "must run regardless of whether the user ever opens
Preferences" call. Full suite green (1124 passed, 3 skipped).

## Task #176: cross-monitor drag continuity - verified live on real 2-monitor Wayland hardware (2026-08-23)

Found during task #168's audit, narrower than it first looked once actually read: `ui/monitor_window.py`'s
own docstring already made a sound claim that ordinary event-to-window routing (motion/button events going
to whichever window is physically under the cursor) is universal windowing behavior, not something
Wayland-specific - true on every desktop, X11 included. The real open question was more specific: does an
*in-progress drag* (a region-select rectangle) that starts on one monitor's own top-level `MonitorWindow`
correctly continue once the cursor crosses onto a second monitor's separate window, or does it break/reset
at the boundary? Wayland's per-monitor-TOPLEVEL architecture (necessary since Wayland forbids absolute
window positioning) makes this a real, monitor-boundary-specific question X11's single spanning `POPUP`
window never has to answer.

Read the actual wiring before testing rather than assuming: `region_select_wayland.py`'s `WaylandRegionSelect`
keeps `_drag_origin`/`_selection`/`_cursor_pos` as single shared instance state, not per-`MonitorWindow` -
every window created by `create_monitor_windows` is wired to the exact same `_on_motion`/`_on_button_press`/
`_on_button_release` methods, each of which receives already-translated global coordinates (`MonitorWindow.
to_global`) and updates that one shared state, then calls `queue_draw_all` to redraw every window from it.
`eyedropper_wayland.py` follows the identical pattern (`self._dragging` as shared instance state). By
construction, a drag should continue correctly across the boundary regardless of which physical window the
motion events arrive on - the one thing code-reading alone can't prove is whether GTK/GDK actually delivers
motion-notify events cleanly to the newly-entered TOPLEVEL with no dead zone, which needed real hardware.

Verified live on the same 2-monitor VM set up for task #175 (`Virtual-1` primary, `Virtual-2` adjacent):
positioned the two VirtualBox "Virtual Screen" windows side-by-side on the host desktop, started a
region-select drag inside one, dragged across the shared edge into the other without releasing, and
released there. direflail confirmed all three pass/fail criteria: the selection rectangle tracked
continuously across the crossing with no freeze/reset/glitch, the dimmed overlay updated correctly in both
windows throughout, and the resulting capture was correct - a single rectangle properly spanning both
monitors. `monitor_window.py`'s own docstring (previously "NOT independently live-verified for real
cross-monitor handoff") updated to record this as confirmed rather than an open question.

## Task #173: gettext infrastructure landed - i18n phase 1 complete (2026-08-24)

Phase 1 only (infrastructure + sweep) - see BACKLOG.md's now-removed #173 entry for the original scoping
split from task #93 (2026-08-10). Phase 2 (producing and maintaining actual `.po` language files) stays
deliberately deferred, same reasoning as the original scoping decision: translating and maintaining N
language files is a dedicated effort of its own, not something this phase's own scope needed to pull in
to be complete.

**What was built**: `src/orcshot/i18n.py` binds `_()`/`ngettext()` once at import time via the stdlib
`gettext` module (`gettext.translation("orcshot", localedir=..., fallback=True)`), resolving its locale
directory the same package-relative way icons and `magnifier_constants.json` already do, rather than the
system `/usr/share/locale/` - resolves identically in a dev checkout and an installed `.deb`.
`fallback=True` means `_()` is currently an inert passthrough (no real `.mo` catalogs ship yet - this
phase is infrastructure-only), which is exactly why every pre-existing test's expected UI-text output was
unaffected by wrapping every genuinely user-facing literal across the whole `ui/` tree and `app.py`
(task-by-task sweep, `b809516`..`159d554`, 11 commits - the range excludes `b809516` itself, which is the
scanner commit, not a sweep commit). `scripts/extract_pot.sh` is dev-only tooling (deliberately not wired
into `debian/rules`/`debian/control` - see the design doc's "Extraction tooling" section) that runs
`xgettext` over `src/orcshot` and writes `po/orcshot.pot`; current run (after the final whole-branch
review's sink-list expansion, below) extracts 357 `msgid` entries excluding the PO header, 358 distinct
source string literals - one entry short of the literal count because
`text_obfuscation_dialog.py`'s `ngettext("{} match", "{} matches", n)` collapses two source literals into
one `msgid`/`msgid_plural` entry.

**The regression guard**: `tests/unit/_i18n_scan.py`'s `scan_source()` is an AST walker, not a text-shape
heuristic - it flags any bare string-literal argument reaching one of a fixed set of GTK/Gio text-setting
sinks (`set_text`, `set_label`, `set_title`, `set_tooltip_text`, `set_markup`, `Gtk.Label(label=...)`,
`Gio.Notification.new(...)`, etc. - full list in the design doc) that isn't already wrapped in
`_()`/`ngettext()` or explicitly exempted with a `# noqa: i18n` comment. A heuristic like "capitalized
with a space" would miss short unspaced labels like "OK"/"Cancel", which is why this is sink-based
instead of shape-based. `tests/unit/test_i18n_coverage.py` (task 14, the closing acceptance gate) wires it
up for real - 30 in-scope files (every `src/orcshot/ui/*.py` plus `app.py`) - rather than the synthetic
fixtures `test_i18n_scan.py` uses to test the scanner itself. It runs as a normal part of
`pytest tests/unit`, so it's already enforced everywhere the suite already runs, including
`debian/rules`' own `override_dh_auto_test` at package-build time - no new CI/packaging wiring needed.

**Two real false positives found during planning, not just anticipated in the abstract**: `set_text` as a
bare method name is too broad a sink signal on its own, because it also matches two calls that aren't UI
chrome at all. `render.py:318` and `printing.py:100` both call `layout.set_text(text, -1)` -
`Pango.Layout.set_text()` rendering the *user's own typed annotation text* onto the canvas; wrapping it in
`_()` would try to gettext-translate arbitrary user content, which is nonsensical and would silently
corrupt behavior the moment a real catalog ships. `destination_picker.py:160` and `:204`'s
`Gtk.Clipboard.get_default(...).set_text(str(path), -1)` match the identical method name while copying a
*file path* to the clipboard - also not translatable text. Both share the exact method name with the
legitimate `Gtk.Entry`/`Gtk.Label` sinks, so a name-only AST matcher can't tell them apart without real
receiver-type inference; resolved with an explicit `# noqa: i18n` and a stated reason at each of the four
call sites rather than teaching the scanner type inference for a distinction that doesn't come up
anywhere else in the codebase.

**A real entanglement bug found and fixed during the sweep, not a hypothetical**: `editor_window.py`'s
`_TOOL_TOOLTIP_SHORTCUTS` dict was originally keyed by each tool's display-label string (`"Select"`,
`"Rectangle"`, ...), looked up at its call site as `_TOOL_TOOLTIP_SHORTCUTS.get(label)` against an
*already-`_()`-wrapped* label. Harmless today only because `_()` is still an inert passthrough - but once
a real translation catalog ships, that lookup would silently stop matching for every non-English locale (a
translated label string would never equal an English dict key), quietly dropping every tool's
keyboard-shortcut tooltip suffix with no error and no test failure to catch it, since the wrapped `_()`
call still returns its English argument unchanged today. Task 9 (`b02ee17`) re-keyed the dict by `Tool`
(the stable enum, immune to translation entirely) instead of the label string, and updated the one call
site (`editor_window.py:1923`) to `_TOOL_TOOLTIP_SHORTCUTS.get(tool)`. Left a comment at the dict's own
definition (`editor_window.py:577-584`) recording why, so a future edit doesn't re-key it back to the
label string out of habit.

Full suite green: 1134 passed, 3 skipped - up from the pre-phase-1 baseline, the increase coming from this
phase's own new tests (`tests/unit/test_i18n.py`, `test_i18n_scan.py`, `test_extract_pot.py`, and this
task's `test_i18n_coverage.py`).

**Final whole-branch review (2026-08-24), fixed in place**: each of the 14 phase-1 tasks had already passed
its own individual review, but a review of the whole branch together found the sink list above was missing
four common GTK text-setting shapes - `Gtk.Dialog.add_buttons()`/`.add_button()` (non-stock labels),
`Gtk.RadioButton.new_with_label()`/`.new_with_label_from_widget()`, `Gtk.FileFilter.set_name()`, and
`Gtk.ComboBoxText.append_text()` - which had left real user-facing strings unwrapped throughout the sweep.
Added to `_SINK_METHODS`, then re-run against the full `ui/` tree + `app.py`: 24 newly-flagged hits across
`color_dialog.py`, `editor_window.py`, `external_commands.py`, `first_run_setup.py`, `printing.py`, and
`text_obfuscation_dialog.py`, plus a handful the scanner structurally can't reach - positional
`Gtk.TreeViewColumn(title, ...)` arguments, `super().__init__(title=...)` (`EditorWindow`'s own window
title), and `ComboBoxText.append(id, text)`'s second positional argument - found and wrapped by hand.
`editor_window.py`'s own local `add_button(icon_name, tooltip, handler)` toolbar helper (unrelated to
`Gtk.Dialog.add_button`) was renamed to `add_tool_button` first, to avoid a name collision with the
newly-added sink method.

The same review also found and fixed: five spots where `_` was reassigned as a throwaway
tuple-unpacking variable in a scope that also calls `_()` (harmless only because `_()` wasn't yet called in
those *exact* scopes - a latent shadowing bug for the next edit, invisible to any test or the scanner);
a stale Preferences-dialog tooltip that named the now-closed "task #109 (i18n infrastructure)" to end
users; one `_()`-bound function default argument (`_do_save`'s `title` parameter), which evaluates once at
import time rather than per call; a fragment-concatenation regression in the zoom menu's "- Actual Size"
suffix, the exact disconnected-fragment anti-pattern `first_run_setup.py` was refactored away from earlier
in this same phase; and an inconsistency between two write sites for the same numeric-only dimensions
label (`editor_window.py`), one correctly left unwrapped with a `# noqa: i18n (numeric only)`, the other
wrapping it in `_()` for no reason. `tests/unit/test_i18n.py` gained two new test methods covering
`ngettext()`'s actual fallback plural-selection behavior (previously only `_()` itself was tested). Full
suite green after all of the above: 1136 passed, 3 skipped - up by exactly the 2 new `ngettext()` tests
just mentioned, otherwise unchanged; every other fix here is behavior-preserving, matching `_()`'s
still-inert passthrough. See BACKLOG.md's `#182` entry for phase 2 (authoring real translations), the
deliberately-deferred remainder this phase never claimed to cover.

## Task #182: i18n phase 2 - real translations for 7 languages, language picker, and packaging (2026-08-25)

Closes the deliberately-deferred remainder of task #173. `_()`/`ngettext()` are no longer an inert
passthrough for anyone but English speakers: `po/{es,fr,de,uk,hi,ja,zh}.po` (Spanish, French, German,
Ukrainian, Hindi, Japanese, Chinese - direflail's own explicit list) each translate all 357 real msgids
from `po/orcshot.pot` (358 `msgid` entries including the header), verified clean via
`msgfmt --check-format --check-domain -o /dev/null` on every file. `po/orcshot.pot` itself is now a real
committed contribution template rather than a gitignored dev artifact (`.gitignore`'s old `po/*.pot` line
removed); `src/orcshot/resources/locale/` (the compiled `.mo` output) is gitignored instead, matching every
other build artifact in this repo - source of truth stays the `.po` files.

**Translation authorship**: seven independent agents, one per language (`superpowers:dispatching-parallel-agents`),
each given the full `.pot`, the exact `Plural-Forms` header for its language (French's `nplurals=2;
plural=(n > 1);` - 0 is grammatically singular in French, unlike English; Ukrainian's full three-way Slavic
plural rule; Japanese/Chinese's `nplurals=1; plural=0;` - no grammatical plural at all), and instructed to
preserve `{}` placeholders and never translate "Orcshot." All seven re-verified directly by the controller
afterward, not just trusted.

**Packaging**: `debian/rules` gained `override_dh_auto_build`, compiling every `po/*.po` to
`src/orcshot/resources/locale/<lang>/LC_MESSAGES/orcshot.mo` via `msgfmt` before the real `dh_auto_build`
runs; `debian/control`'s `Build-Depends` gained `gettext` (deliberately deferred in phase 1 since nothing
was compiled at build time then). No `debian/orcshot.install` entry needed - hatchling's existing
`packages = ["src/orcshot"]` already bundles the compiled `.mo` files the same way it bundles icons.

**Contribution workflow**: `TRANSLATING.md` documents a Poedit-based process (download the `.pot` or an
existing `.po`, edit in the free Poedit GUI, send back via PR or `<orc.shot@yahoo.com>` for non-GitHub
contributors) - chosen specifically so contributing a translation never requires reading source code or
raw `.po` syntax, per direflail's own stated goal ("i'd rather not make someone dig through the source
code").

**A real language picker, not just catalogs**: phase 1 had already added a "Language" row to Preferences,
permanently disabled with a tooltip claiming no translations existed - now that real ones do, all seven
translator agents independently flagged that same dropdown as stale/misleading. `settings.py` gained
`get_language()`/`set_language()` (`""` = "System Default"); `i18n.py`'s `_resolve_languages()` reads that
once at the module's own import time and, if non-empty, overrides gettext's normal OS-locale env-var
negotiation. Default behavior is unchanged - Orcshot still follows the Linux system locale unless a user
explicitly picks something else in Preferences. The override only takes effect after a restart (documented
honestly in the dropdown's own tooltip and in `i18n.py`'s docstring), the same known limitation as every
other `_()`-bound module-level constant in this codebase, not a new one this feature introduced.

**Two more real cross-language bugs, surfaced independently by multiple translator agents while actually
reading the render code, not guessed**: (1) `ObfuscateShape.fill_text` was both a stable storage key
(persisted in `.orcshot` files, used as a dict key in `editor_window.py`) and, previously, the literal text
drawn onto the image - conflating "internal key" with "displayed text" meant the redaction stamp itself
(`"REDACTED"`, `"CENSORED"`, etc.) never actually translated. Fixed by moving
`OBFUSCATE_FILL_TEXT_PRESETS`/`OBFUSCATE_FILL_TEXT_LABELS` to `core/shapes.py` so `render.py`'s
`render_obfuscate` can translate the key to its display label at the point of drawing, while the stored key
itself stays stable and untranslated. (2) `msgid "Edit"` collided between the Edit menu and the destination
picker's "open in editor" button - grammatically fine as a menu label but reads as a fragment on a button.
Resolved by pointing `destination_picker.py` at an already-existing, already-translated msgid (`"Edit..."`,
used elsewhere for an external-editor button) instead of introducing `msgctxt`/`pgettext` for one string.

**A real production bug, not hypothetical**: `gettext.translation(..., fallback=True)` only protects
against `find()` returning no candidate `.mo` at all - once a candidate path exists but can't be opened
(permission denied, corrupt file), it raises `OSError` uncaught even with `fallback=True` set. Found live
during VM verification: a root-owned `.mo` file crash-looped the whole app on every startup instead of
silently staying in English. Fixed with `i18n.py`'s new `_load_translation()`, wrapping the call in
`try/except OSError: return gettext.NullTranslations()`.

**Two real build-breaking bugs, found via an actual `dpkg-buildpackage -us -uc -b` run, not caught by
`pytest` alone**: `test_i18n_coverage.py` and `test_extract_pot.py` both assumed `Path(__file__).parent.parent.parent`
resolves to the repo root - true in a dev checkout, false inside `dh_auto_test`'s pybuild build tree, where
hatchling flattens `src/orcshot/` to a plain `orcshot/` package and doesn't copy `scripts/` at all. Fixed by
resolving via `Path(orcshot.__file__).parent` (same trick `RESOURCES_DIR` already uses) and by skipping the
`extract_pot.sh`-dependent test when that dev-only script isn't present. Also fixed `scripts/extract_pot.sh`'s
unquoted `$(find ...)` (word-split/glob risk, noted as a loose end in phase 1's own final review) with
`find ... -print0 | xargs -0`.

Verified live end-to-end on a real Ubuntu 26.04 Wayland VM with the system language actually switched to
Spanish (not an env-var shortcut) - Preferences and the tray menu both rendered in Spanish. Full suite
green: 1143 passed, 3 skipped. Documentation translation (README/docs into the same 7 languages, and how to
make GitHub display multiple documentation languages) remains an explicit, separate follow-up - raised by
direflail but deliberately not part of this task's scope.

## Task #183: the language picker actually working, end to end (2026-08-26)

BACKLOG.md's own `#183` entry already carries the root cause and fix for the core packaging bug (hatchling's
wheel build silently dropping `src/orcshot/resources/locale/` because it's gitignored, with no `artifacts`
entry telling it otherwise) - this closes it out along with everything direflail's own live re-testing found
on top of that first fix, across several rounds on the same real Ubuntu 26.04 Wayland VM. Every fix below
was verified against real evidence gathered live (journalctl, a real installed `.deb`, GNOME Shell's own
extracted source, real `gjs` runs) before landing, not assumed correct from the surrounding code reading
right.

**Packaging fix**: `pyproject.toml`'s `[tool.hatch.build.targets.wheel]` gained `artifacts =
["src/orcshot/resources/locale/**/*.mo"]`. Also surfaced a real test-isolation gap: with real compiled `.mo`
catalogs now sitting in the dev tree and a real language set in `~/.config/orcshot/config.json` from
live-testing this exact bug, the whole pytest suite silently started running in Japanese - 4 tests failed
asserting on English text. `tests/conftest.py` (new) points `XDG_CONFIG_HOME` at an isolated temp directory
before any test module is imported, so the suite no longer depends on the developer's own machine state.

**Restart-for-language-change, three attempts, each root-caused before moving to the next**: the first
implementation (`os.execv` re-exec in place) just quit instead of restarting - reproduced outside this app
entirely with an isolated `Type=dbus`/`BusName=` systemd user unit matching `debian/orcshot.service`'s own
config exactly: the moment `execv`'s process-image replacement makes the D-Bus name transiently vanish,
systemd's own `Type=dbus` tracking considers the unit stopped and tears it down before the freshly-exec'd
image can reacquire the name. Spawning `systemctl --user restart` from inside the same process was tried
next and has its own race (that subprocess inherits the unit's own cgroup and can be killed as collateral
damage of the "stop" half of its own restart command). What actually works, confirmed the same way: exiting
with a non-zero status and letting the *already-configured* `Restart=on-failure`/`RestartSec=2` do the
relaunch - the one restart path `Type=dbus` supervision is actually built to support.

**Two more real i18n gaps found live**: no explicit "English" option in the picker (only "System Default" -
added `("en", "English")`, no `i18n.py` change needed since `gettext.translation(languages=["en"],
fallback=True)` already falls back to a plain passthrough with no `en.po` catalog); Preferences >
Destinations' "Destination"/"Command" column headers stayed English in every language, a real coverage gap
in `tests/unit/_i18n_scan.py`'s AST scanner (it only flags string literals reaching a sink directly, not
ones threaded through a variable a frame up, via the `build_checklist(store, column_label)` helper) - fixed
at both call sites, with a comment at the helper's own definition explaining the scanner's blind spot for
next time.

**The Wayland tray menu, four more rounds, each with real evidence gathered on the VM**:

1. The tray menu (built by `extension.js`, GNOME Shell's own extension mechanism - a separate GJS runtime
   inside `gnome-shell` itself) was never part of phase 1's Python-only `xgettext` sweep at all. Gave it its
   own gettext domain (`orcshot-tray`, `metadata.json`'s `gettext-domain`), confirmed correct against GNOME
   Shell 50.1's own actual source (extracted live from `libshell-18.so` on the test VM via `gresource
   extract`, not assumed from documentation) and proven with a real `gjs` script exercising the same
   `bindtextdomain`/`dgettext` calls `ExtensionBase.initTranslations()` uses. All 8 msgids are byte-identical
   to ones already translated in `po/<lang>.po` for the X11 fallback menu's own equivalent items, so
   `debian/rules` derives this domain's `.mo` files from `po/<lang>.po` via `msgmerge` at build time - no
   second `po/orcshot-tray-<lang>.po` set to maintain, and no new step for translators (documented in
   `TRANSLATING.md`, all 8 language versions, per direflail's own request).
2. "Orcshot worked. translation of tray menu didn't" - the tray menu only ever followed the real system
   locale, with no visibility into Orcshot's own Preferences language override
   (`settings.get_language()`), which is deliberately independent of the OS locale. Fixed by having the
   extension read Orcshot's `config.json` directly (`GLib.get_user_config_dir()`, the same
   `$XDG_CONFIG_HOME` resolution `settings.config_file_path()` uses) - an established pattern for this
   extension, which already reads two of Orcshot's other JSON files the same way.
3. "Restarted. tray menu does not match." - root-caused with hard timestamp evidence
   (`ps -o lstart= -C gnome-shell` vs. `stat` on `config.json`): the tray panel button is only ever built
   once per `gnome-shell` session (`_ensureTrayButton`'s own `if (this._trayButton) return;` guard);
   Orcshot restarting on its own never touched it again. Fixed by reusing `Quitting()` (the D-Bus method
   `_quit_and_hide_tray_button` already calls before a normal quit, which destroys the button and lets
   `_ensureTrayButton` rebuild it fresh next time Orcshot's name reappears) from the language-restart path
   too, via a new shared `_notify_tray_extension_quitting()`.
4. "Changed to espanol, restarted, tray menu was in espanol. Changed to francais, restarted, tray menu
   still in espanol" - the *first* language switch each session worked, every one after that silently
   didn't. Root-caused with three separate `gjs` probes on the VM, each disproving a hypothesis before the
   real one: re-`setlocale()`, "bouncing" through `'C'` and back, and even a brand-new never-used gettext
   domain name all still returned the *first* language's text (the fresh-domain case fell back to English
   instead of resolving French at all, proving this wasn't a per-domain cache but glibc's `dcgettext()`
   itself not re-reading `$LANGUAGE` after its first real resolution in a process - `gnome-shell` is one
   long-running process for the whole session, so this hit every language change after the first, unlike
   `orcshot.i18n`'s own Python side, where each restart is a genuinely fresh process). Fixed by sidestepping
   gettext's own catalog resolution entirely for this case: `_parseMoFile` reads the target `.mo` file's
   binary format directly (the documented GNU MO format) into a plain lookup Map, with no
   `dgettext`/`setlocale`/`$LANGUAGE` involved. Verified by replaying the exact reported sequence
   (`default -> es -> fr -> de -> es -> ja`) in one `gjs` process - every transition resolved correctly,
   including switching back to a previously-used language.

Confirmed working live by direflail on the real VM after all four tray-menu rounds. Full suite green
throughout every round: 1143 passed, 3 skipped.

## Licensing

**Status: decided — GPLv3.** Greenshot (Windows) is GPLv3; this is a derivative work — same feature
set, same design lineage — even though no source code is shared. (No longer "same name" as of the
Orcshot rebrand, task #105 - GPLv3 covers the code being a derivative work regardless; the name/logo
were always a separate trademark/copyright concern, addressed by the rebrand itself, not by this
license choice.) Confirmed with the
user (not just this file's own recommendation) when a real `LICENSE` file became a genuine blocker
for `debian/copyright` during packaging. `LICENSE` at the repo root is the verbatim text from
`gnu.org`, fetched via `curl` rather than a web-fetch tool that summarizes content through a model —
a legal document needs to be byte-exact, not paraphrased.
