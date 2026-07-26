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

### Annotation tools (faithful port of `Greenshot.Editor/Drawing`)
Rectangle, Ellipse, Line, Arrow, Freehand, Text, Speech bubble, Step-number labels, Highlight,
Icon/stamp, Crop, Cursor overlay, embedded Image, embedded SVG, Blur filter, Pixelize filter.

**Status: all ported at the pure-data-model level** (`src/greenshot_linux/core/shapes.py`,
`drawing.py`, `filters.py`, `crop.py`), TDD throughout, 266 tests. Not yet done: wiring these into
an actual GTK/Cairo editor UI (drag-to-create, resize handles, live rendering) — every shape here
is a plain value object with a `clickable_at`/hit-test method and no rendering code at all, by
design, since there's no renderer yet. See individual module docstrings for scoped-out rendering
details (GDI+ Bezier smoothing, exact stroked-path geometry, font measurement) — each is a
rendering-layer concern, not a data-model gap.

### Export
- Copy to clipboard
- Save to file
- **Basic print** (send bitmap to a printer via the OS print dialog — easy on GTK via
  `Gtk.PrintOperation`/CUPS, in scope for initial build)

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
