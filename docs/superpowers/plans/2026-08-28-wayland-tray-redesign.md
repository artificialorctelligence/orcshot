# Wayland Tray Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace Orcshot's Wayland tray icon/menu mechanism (currently `AyatanaAppIndicator3`, built on a
library its own upstream has declared obsolete) with a `Gio.Menu` export consumed by a new, small,
Orcshot-specific GNOME Shell extension - removing the last piece of Orcshot's Wayland experience that
depends on GNOME-Shell-extension trickery unrelated to Window Picker, and doing so in a way proven to
survive Snap's strict confinement model.

**Architecture:** Orcshot is already a `Gio.Application` (`org.orcshot.Orcshot`) that already exports its
tray actions automatically via GApplication's standard `org.gtk.Actions` D-Bus interface
(`_register_tray_actions`, confirmed already-working, no change needed). The only missing piece is the
*menu structure* itself - build it as a `Gio.Menu`, export it via the app's own already-owned D-Bus
connection (`export_menu_model`, no new bus name needed), and have a new Shell extension watch for it and
render a real `PanelMenu.Button`/`PopupMenu` from it, activating the app's existing actions by name.

**Tech Stack:** PyGObject (`Gio.Menu`, `Gio.DBusConnection.export_menu_model`) on the Python side - no new
dependency; plain GJS (ES-module GNOME Shell extension, `Gio.DBusMenuModel`/`Gio.DBusActionGroup`) on the
Shell side.

**Spec:** `docs/superpowers/specs/2026-08-28-wayland-capture-redesign-design.md`

## Global Constraints

- Must work identically across `.deb`/apt, Snap, and Flatpak - no per-channel behavioral drift (spec).
- Must work exactly as it does today from the end user's perspective - same tray menu items, same icons,
  same click behavior (spec).
- **Every icon must be one of Orcshot's own hand-drawn icons - never a system icon-theme name.** Direct,
  already-established user requirement (task #146, `icons.py`'s own docstring): *"I don't want default
  icon sets. they're going to be different between platforms and I don't want that... every icon in the
  wayland version [must] look like the x11 version, no exceptions."* Any `Gio.ThemedIcon`/`icon-name`
  based icon in this feature is a bug, not a shortcut.
- No new dependency beyond what Orcshot already uses (PyGObject/`Gio`, already used throughout this
  codebase) - matches the spec's explicit finding that `libayatana-appindicator-glib` isn't needed as a
  library dependency.
- GNOME Shell extensions require a full logout/login to pick up code changes or even be newly discovered -
  never trust a result without one (`[[feedback-extension-reload-caching]]`).

---

### Task 1: A `Gio.Icon`-producing sibling to `icons.py`'s existing Cairo drawing

**Files:**
- Modify: `src/orcshot/ui/icons.py` (add new functions near `_drawn_icon_image`, line ~915)
- Test: `tests/unit/ui/test_icons_gicon.py` (new)

**Interfaces:**
- Produces: `capture_mode_gicon(mode: str, color: Color = _DEFAULT_COLOR, size: int = ICON_SIZE) -> Gio.Icon`
  - `mode` is one of `"region"`/`"full_screen"`/`"active_window"`/`"window_picker"`/`"repeat_region"` (the
    same keys `_tray_action_handlers()` in `app.py` already uses).
  - `Color` is the existing `icons.py` type alias (a 4-tuple of 0-255 ints), already imported by callers.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/ui/test_icons_gicon.py
"""Pure coverage for the Gio.Icon-producing icon helpers - same
headless-safe pattern as test_gnome_clipboard.py's PNG round-trip
test, no display needed."""
import gi

gi.require_version("Gio", "2.0")
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import Gio, GdkPixbuf

from orcshot.ui.icons import capture_mode_gicon


class TestCaptureModeGicon:
    def test_returns_a_real_gio_icon(self):
        icon = capture_mode_gicon("region")
        assert isinstance(icon, Gio.Icon)

    def test_serializes_and_deserializes_to_the_same_icon(self):
        icon = capture_mode_gicon("region")
        variant = icon.serialize()
        restored = Gio.Icon.deserialize(variant)
        assert isinstance(restored, Gio.BytesIcon)

    def test_bytes_are_a_valid_decodable_png_at_the_requested_size(self):
        icon = capture_mode_gicon("region", size=32)
        assert isinstance(icon, Gio.BytesIcon)
        png_bytes = icon.get_bytes().get_data()
        pixbuf = GdkPixbuf.Pixbuf.new_from_stream(
            Gio.MemoryInputStream.new_from_bytes(icon.get_bytes()), None,
        )
        assert pixbuf.get_width() == 32
        assert pixbuf.get_height() == 32

    def test_different_modes_produce_different_icons(self):
        region_bytes = capture_mode_gicon("region").get_bytes().get_data()
        window_bytes = capture_mode_gicon("active_window").get_bytes().get_data()
        assert region_bytes != window_bytes
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/unit/ui/test_icons_gicon.py -v`
Expected: FAIL with `ImportError: cannot import name 'capture_mode_gicon'`

- [ ] **Step 3: Write minimal implementation**

Add to `src/orcshot/ui/icons.py`, right after `_drawn_icon_image` (~line 922, before
`capture_mode_icon_image`):

```python
def _drawn_icon_gicon(geometry_key: str, color: Color, size: int) -> Gio.Icon:
    """Same Cairo drawing as _drawn_icon_image, but wrapped as a real
    Gio.Icon (raw PNG bytes) instead of a Gtk.Image widget - for
    contexts that need to hand an icon to something outside this
    process (a D-Bus-exported Gio.Menu item), where a live widget
    reference is meaningless. Deliberately still Orcshot's own
    hand-drawn geometry, never a system icon-theme name - see this
    module's own stock_icon_image docstring (task #146) for why
    that's a hard requirement, not a style preference.
    """
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, size, size)
    ctx = cairo.Context(surface)
    r, g, b, a = color
    ctx.set_source_rgba(r / 255, g / 255, b / 255, a / 255)
    _render_icon_geometry(ctx, _icon_geometry()[geometry_key], size)
    pixbuf = Gdk.pixbuf_get_from_surface(surface, 0, 0, surface.get_width(), surface.get_height())
    _, png_bytes = pixbuf.save_to_bufferv("png", [], [])
    return Gio.BytesIcon.new(GLib.Bytes.new(png_bytes))


def capture_mode_gicon(mode: str, color: Color = _DEFAULT_COLOR, size: int = ICON_SIZE) -> Gio.Icon:
    """Gio.Icon counterpart to capture_mode_icon_image, for the
    Wayland tray menu's D-Bus-exported Gio.Menu (see
    gnome_tray_export.py) - same modes, same geometry data, same
    hand-drawn requirement.
    """
    return _drawn_icon_gicon(mode, color, size)
```

Add the two new imports this needs at the top of `icons.py` (check first - `Gio`/`GLib` may already be
imported there; if `gi.require_version("Gio", "2.0")` isn't already present, add it alongside the existing
`gi.require_version` calls):

```python
gi.require_version("Gio", "2.0")
gi.require_version("GLib", "2.0")
from gi.repository import Gio, GLib
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/unit/ui/test_icons_gicon.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add src/orcshot/ui/icons.py tests/unit/ui/test_icons_gicon.py
git commit -m "Add capture_mode_gicon: Gio.Icon counterpart to the existing hand-drawn icons"
```

---

### Task 2: Build and export the tray `Gio.Menu`

**Files:**
- Create: `src/orcshot/capture/gnome_tray_export.py`
- Test: `tests/unit/capture/test_gnome_tray_export.py`

**Interfaces:**
- Consumes: `capture_mode_gicon(mode, color, size) -> Gio.Icon` (Task 1). Action names already registered
  by `app.py`'s existing `_register_tray_actions()`: `tray-region`, `tray-full_screen`,
  `tray-active_window`, `tray-window_picker`, `tray-repeat_region`, `tray-open-file`, `tray-preferences`,
  `tray-quit` - referenced here with the standard GApplication `"app."` prefix.
- Produces:
  - `build_tray_menu(labels: dict[str, str], color: Color) -> Gio.Menu` - `labels` maps the same mode keys
    above to their already-translated display strings (caller passes already-`_()`-translated text, this
    function does no translation itself).
  - `export_tray_menu(app: Gio.Application, menu: Gio.Menu, object_path: str = TRAY_MENU_PATH) -> int` -
    returns the export registration id (as `Gio.DBusConnection.export_menu_model` does), for the caller to
    hold onto if it ever needs to unexport.
  - `TRAY_MENU_PATH = "/org/orcshot/Orcshot/TrayMenu"` (module-level constant, the extension's own
    `MENU_PATH` in Task 3 must match this exactly).

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/capture/test_gnome_tray_export.py
"""Pure coverage for the tray Gio.Menu structure - the actual D-Bus
export needs a real running Gio.Application with a live D-Bus
connection, only verified live (see Task 7). Matches this project's
own established split between headless-testable pure logic and
live-verified D-Bus behavior (test_gnome_clipboard.py's own docstring
states the same reasoning)."""
import gi

gi.require_version("Gio", "2.0")
from gi.repository import Gio

from orcshot.capture.gnome_tray_export import build_tray_menu

_LABELS = {
    "region": "Capture Region",
    "full_screen": "Capture Full Screen",
    "active_window": "Capture Active Window",
    "window_picker": "Capture Window...",
    "repeat_region": "Repeat Last Region",
}


class TestBuildTrayMenu:
    def test_returns_a_real_gio_menu(self):
        menu = build_tray_menu(_LABELS, (60, 60, 60, 255))
        assert isinstance(menu, Gio.Menu)

    def test_has_one_item_per_capture_mode_plus_the_fixed_items(self):
        menu = build_tray_menu(_LABELS, (60, 60, 60, 255))
        # 5 capture modes + open-file + preferences + quit = 8
        assert menu.get_n_items() == 8

    def test_first_item_matches_the_first_label_and_correct_action(self):
        menu = build_tray_menu(_LABELS, (60, 60, 60, 255))
        label = menu.get_item_attribute_value(0, "label", None).get_string()
        action = menu.get_item_attribute_value(0, "action", None).get_string()
        assert label == "Capture Region"
        assert action == "app.tray-region"

    def test_every_capture_mode_item_has_an_icon_attribute(self):
        menu = build_tray_menu(_LABELS, (60, 60, 60, 255))
        for i in range(5):
            icon_value = menu.get_item_attribute_value(i, "icon", None)
            assert icon_value is not None, f"item {i} has no icon"

    def test_quit_is_the_last_item_with_the_right_action(self):
        menu = build_tray_menu(_LABELS, (60, 60, 60, 255))
        n = menu.get_n_items()
        action = menu.get_item_attribute_value(n - 1, "action", None).get_string()
        assert action == "app.tray-quit"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/unit/capture/test_gnome_tray_export.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'orcshot.capture.gnome_tray_export'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/orcshot/capture/gnome_tray_export.py
"""Publishes Orcshot's Wayland tray menu as a real Gio.Menu, exported
over D-Bus on this app's own already-owned connection - the
replacement for the AyatanaAppIndicator3/dbusmenu path on Wayland (see
docs/superpowers/specs/2026-08-28-wayland-capture-redesign-design.md).

Deliberately doesn't export a new Gio.SimpleActionGroup or own a new
bus name: app.py's own _register_tray_actions() already exports every
tray action automatically via GApplication's standard org.gtk.Actions
interface at /org/orcshot/Orcshot, since this app is already a
registered Gio.Application - this module only needs to publish the
*menu structure* referencing those already-exported actions by name
("app.tray-<mode>", the standard GApplication action-group prefix).
"""

from __future__ import annotations

import gi

gi.require_version("Gio", "2.0")
from gi.repository import Gio

from orcshot.core.shapes import Color
from orcshot.ui.icons import capture_mode_gicon

TRAY_MENU_PATH = "/org/orcshot/Orcshot/TrayMenu"

# Same 5 capture modes as app.py's _tray_action_handlers(), same
# order _build_tray_menu (the X11/AppIndicator3 Gtk.Menu builder)
# already uses - keep these in sync if that ordering ever changes.
_CAPTURE_MODES = ("region", "full_screen", "active_window", "window_picker", "repeat_region")


def build_tray_menu(labels: dict[str, str], color: Color) -> Gio.Menu:
    """labels maps each of _CAPTURE_MODES to its already-translated
    display text, plus "open_file"/"preferences"/"quit" for the three
    fixed items below the capture modes - same set app.py's
    _build_tray_menu (the Gtk.Menu builder) already needs, so callers
    typically already have all of these translated strings on hand.
    """
    menu = Gio.Menu()
    for mode in _CAPTURE_MODES:
        item = Gio.MenuItem.new(labels[mode], f"app.tray-{mode}")
        item.set_icon(capture_mode_gicon(mode, color))
        menu.append_item(item)

    menu.append_item(Gio.MenuItem.new(labels["open_file"], "app.tray-open-file"))
    menu.append_item(Gio.MenuItem.new(labels["preferences"], "app.tray-preferences"))
    menu.append_item(Gio.MenuItem.new(labels["quit"], "app.tray-quit"))
    return menu


def export_tray_menu(app: Gio.Application, menu: Gio.Menu, object_path: str = TRAY_MENU_PATH) -> int:
    """Exports on the app's own already-connected D-Bus connection -
    Gio.Application.get_dbus_connection() only returns non-None once
    the application is actually registered (after Gio.Application.run()
    has started, or a manual register() call) - callers must call this
    after that point, not during __init__.
    """
    connection = app.get_dbus_connection()
    return connection.export_menu_model(object_path, menu)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/unit/capture/test_gnome_tray_export.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add src/orcshot/capture/gnome_tray_export.py tests/unit/capture/test_gnome_tray_export.py
git commit -m "Add gnome_tray_export: builds and exports the Wayland tray Gio.Menu"
```

---

### Task 3: The `orcshot-tray@orcshot.org` GNOME Shell extension

**Files:**
- Create: `src/orcshot/resources/gnome-shell-extensions/orcshot-tray@orcshot.org/metadata.json`
- Create: `src/orcshot/resources/gnome-shell-extensions/orcshot-tray@orcshot.org/extension.js`

**Interfaces:**
- Consumes: `TRAY_MENU_PATH = "/org/orcshot/Orcshot/TrayMenu"` (Task 2, must match exactly) on bus name
  `org.orcshot.Orcshot` (already Orcshot's fixed `application_id`, `app.py:67`). Action group already
  exported by GApplication at object path `/org/orcshot/Orcshot` (same bus name), standard
  `org.gtk.Actions` interface - action names arrive un-prefixed at this layer (e.g. `tray-region`, not
  `app.tray-region` - the `"app."` prefix is a menu-item-local convention, not part of the action group's
  own wire format, confirmed live in this project's own earlier GMenu/GActionGroup prototype).

Not unit tested - matches this project's established convention for GJS/Shell-extension code (verified
live only, same as `orcshot-clipboard@orcshot.org`/`window-calls@domandoman.xyz`). Acceptance is Task 7's
live verification, not a test suite.

- [ ] **Step 1: Write `metadata.json`**

```json
{
  "name": "Orcshot Tray",
  "description": "Renders Orcshot's Wayland tray icon and menu from the app's own exported Gio.Menu - see the project's own REQUIREMENTS.md and docs/superpowers/specs/2026-08-28-wayland-capture-redesign-design.md for why this exists as a separate, narrowly-scoped extension rather than a general-purpose tray renderer.",
  "uuid": "orcshot-tray@orcshot.org",
  "shell-version": ["45", "46", "47", "48", "49", "50"]
}
```

- [ ] **Step 2: Write `extension.js`**

```javascript
import St from 'gi://St';
import Gio from 'gi://Gio';
import GObject from 'gi://GObject';
import * as PanelMenu from 'resource:///org/gnome/shell/ui/panelMenu.js';
import * as PopupMenu from 'resource:///org/gnome/shell/ui/popupMenu.js';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import { Extension } from 'resource:///org/gnome/shell/extensions/extension.js';

// Must match app.py's fixed application_id and
// gnome_tray_export.py's TRAY_MENU_PATH exactly.
const BUS_NAME = 'org.orcshot.Orcshot';
const MENU_PATH = '/org/orcshot/Orcshot/TrayMenu';
const ACTIONS_PATH = '/org/orcshot/Orcshot';

const OrcshotTrayButton = GObject.registerClass(
class OrcshotTrayButton extends PanelMenu.Button {
    _init() {
        super._init(0.0, 'Orcshot');

        this._menuModel = Gio.DBusMenuModel.get(Gio.DBus.session, BUS_NAME, MENU_PATH);
        this._actionGroup = Gio.DBusActionGroup.get(Gio.DBus.session, BUS_NAME, ACTIONS_PATH);
        this.menu.actionGroup = this._actionGroup;

        this._rebuild();
        this._itemsChangedId = this._menuModel.connect('items-changed', () => this._rebuild());
        // Standard Clutter.Actor 'destroy' signal, matching this
        // project's own orcshot-clipboard@orcshot.org convention for
        // cleanup-on-destroy - not a `_destroy_impl` vfunc override,
        // which isn't a real GJS-exposed hook on this class hierarchy
        // and would silently leak this signal connection.
        this.connect('destroy', () => this._menuModel.disconnect(this._itemsChangedId));
    }

    _rebuild() {
        this.menu.removeAll();
        let n = this._menuModel.get_n_items();
        for (let i = 0; i < n; i++) {
            let label = this._menuModel.get_item_attribute_value(i, 'label', null)?.deep_unpack() ?? '';
            let action = this._menuModel.get_item_attribute_value(i, 'action', null)?.deep_unpack();
            let iconValue = this._menuModel.get_item_attribute_value(i, 'icon', null);

            let item = new PopupMenu.PopupMenuItem(label);
            if (iconValue) {
                try {
                    let gicon = Gio.Icon.deserialize(iconValue);
                    let iconWidget = new St.Icon({ gicon, style_class: 'popup-menu-icon', icon_size: 16 });
                    // Left-aligned by construction: icon inserted
                    // BEFORE the label in child order, matching
                    // native GNOME PopupImageMenuItem's own layout -
                    // NOT ubuntu-appindicators@ubuntu.com's hard-coded
                    // xAlign: Clutter.ActorAlign.END, the bug this
                    // whole redesign exists to route around.
                    item.insert_child_below(iconWidget, item.label);
                    // First item's icon is also the panel button's
                    // own icon (Orcshot's own hand-drawn "region"
                    // icon, task #146 - never a system theme name).
                    if (i === 0 && !this._panelIconSet) {
                        this.add_child(new St.Icon({ gicon, style_class: 'system-status-icon', icon_size: 16 }));
                        this._panelIconSet = true;
                    }
                } catch (e) {
                    logError(e, 'orcshot-tray: bad icon data');
                }
            }
            if (action) {
                // Bare name, no "app." prefix - see this file's own
                // Interfaces note above for why.
                let bareAction = action.includes('.') ? action.split('.').slice(1).join('.') : action;
                item.connect('activate', () => this._actionGroup.activate_action(bareAction, null));
            }
            this.menu.addMenuItem(item);
        }
    }

});

export default class OrcshotTrayExtension extends Extension {
    enable() {
        this._button = null;
        this._watchId = Gio.bus_watch_name(
            Gio.BusType.SESSION, BUS_NAME, Gio.BusNameWatcherFlags.NONE,
            () => {
                if (this._button)
                    return;
                try {
                    this._button = new OrcshotTrayButton();
                    Main.panel.addToStatusArea('orcshot-tray', this._button);
                } catch (e) {
                    logError(e, 'orcshot-tray: failed to build tray button');
                }
            },
            () => {
                if (this._button) {
                    this._button.destroy();
                    this._button = null;
                }
            },
        );
    }

    disable() {
        if (this._watchId) {
            Gio.bus_unwatch_name(this._watchId);
            this._watchId = null;
        }
        if (this._button) {
            this._button.destroy();
            this._button = null;
        }
    }
}
```

Note on the panel-icon logic: the extension above reuses the first menu item's icon (Orcshot's own
hand-drawn "region" icon) for the panel button itself, rather than matching AppIndicator3's current choice
of `LOGO_PATH` (Orcshot's app logo). Decision: keep the reused capture-mode icon, don't add a second export
path just for the panel button. Reasoning: `LOGO_PATH` is a PNG file on disk, not something
`gnome_tray_export.py` currently exports over D-Bus at all (Task 2 only exports the menu structure) - adding
a second, logo-specific export path purely to match AppIndicator3's cosmetic choice is exactly the kind of
unrequested extra surface this project avoids elsewhere (see `[[feedback_root_cause_not_bandaid]]`'s own
sibling principle against solving more than what's asked). If this cosmetic difference matters once seen
live in Task 7, swapping to the real logo is a two-line follow-up (export `LOGO_PATH` as a second `Gio.Icon`
in Task 2, reference it here instead of item 0's icon) - not a redesign.

- [ ] **Step 3: Commit**

```bash
git add "src/orcshot/resources/gnome-shell-extensions/orcshot-tray@orcshot.org/"
git commit -m "Add the orcshot-tray@orcshot.org Shell extension"
```

---

### Task 4: Wire `app.py`'s Wayland tray path onto the new export

**Files:**
- Modify: `src/orcshot/app.py` (`_build_tray_icon`, ~line 929; `_register_tray_actions`, ~line 571; the
  method that constructs the tray icon at startup, e.g. `_build_ui`/`do_activate` - find the call site)

**Interfaces:**
- Consumes: `gnome_tray_export.build_tray_menu(labels, color) -> Gio.Menu`,
  `gnome_tray_export.export_tray_menu(app, menu) -> int` (Task 2).

- [ ] **Step 1: Read the current `_build_tray_icon` in full**

```bash
sed -n '929,1016p' src/orcshot/app.py
```

Confirm the exact current structure before editing - this plan was written against a specific snapshot of
this method; re-read it live since other work may have touched it since.

- [ ] **Step 2: Replace the Wayland branch**

In `_build_tray_icon`, replace the entire `if os.environ.get("XDG_SESSION_TYPE") == "wayland":` block
(currently checking `shell_tray_button_active()` and returning `None` only when the old extension is
active, falling through to `AyatanaAppIndicator3` otherwise) with an unconditional early return - the new
extension now owns the Wayland tray unconditionally, the same way the old one did only when present:

```python
        if os.environ.get("XDG_SESSION_TYPE") == "wayland":
            # No local widget at all, same reasoning as the old
            # Shell-native panel-button path this replaces (see
            # docs/superpowers/specs/2026-08-28-wayland-capture-redesign-design.md) -
            # orcshot-tray@orcshot.org owns the tray unconditionally
            # on Wayland now; unlike the extension it replaces, there
            # is no AppIndicator3 fallback to fall through to if it's
            # unavailable (first boot before a relogin, or the user
            # disabling extensions) - see _export_tray_menu's own
            # docstring for how that gap is surfaced instead.
            return None
```

Delete the now-unreachable `AyatanaAppIndicator3` construction code below it (the `gi.require_version
("AyatanaAppIndicator3", "0.1")` block through `return indicator`) - X11's `Gtk.StatusIcon` branch at the
bottom of the method is unaffected, keep it exactly as-is.

- [ ] **Step 3: Export the menu at startup on Wayland**

Find where `self._register_tray_actions()` is currently called (search `_register_tray_actions()` call
site, likely in `do_activate` or an app-init method near where `_build_tray_icon` is also called). Add a
sibling call right after it, gated the same way:

```python
        self._register_tray_actions()
        if os.environ.get("XDG_SESSION_TYPE") == "wayland":
            self._export_tray_menu()
```

Add the new method near `_register_tray_actions`:

```python
    def _export_tray_menu(self) -> None:
        """Publishes the Wayland tray menu for orcshot-tray@orcshot.org
        to render - see gnome_tray_export.py's own module docstring
        for why this doesn't need a new bus name or action group, just
        the menu structure itself.
        """
        from orcshot.capture.gnome_tray_export import build_tray_menu, export_tray_menu

        labels = {
            "region": _("Capture Region"),
            "full_screen": _("Capture Full Screen"),
            "active_window": _("Capture Active Window"),
            "window_picker": _("Capture Window..."),
            "repeat_region": _("Repeat Last Region"),
            "open_file": _("Open..."),
            "preferences": _("Preferences"),
            "quit": _("Quit"),
        }
        color = _rgba_to_color(Gtk.Window().get_style_context().get_color(Gtk.StateFlags.NORMAL))
        menu = build_tray_menu(labels, color)
        export_tray_menu(self, menu)
```

Check the exact existing translated strings in `_build_tray_menu` (the X11/old-AppIndicator3 builder,
`_build_tray_menu` at the line found in Task 4 Step 1) and use the identical `_()`-wrapped source strings
here - the two menus must show the same English text so `po/<lang>.po` already covers both without any new
translator work, matching this project's own established "no new strings to translate for a menu that
already exists elsewhere" precedent (task #183's own tray-menu translation work took the same approach).

- [ ] **Step 4: Remove the two other methods whose entire premise depended on the AppIndicator3 fallback**

Found during this plan's own pre-flight review, not in the original task scope - two more methods call
`shell_tray_button_active()`/`get_tray_button_error()` beyond `_build_tray_icon` itself, and both become
obsolete once Step 2 removes the AppIndicator3 fallback entirely:

**Remove `_recheck_tray_icon_after_extension_change` in full** (its own method body, roughly lines 878-927 -
confirm the exact range by reading the method, it runs from its own `def` to the `GLib.timeout_add(500,
_poll)` line immediately before `_build_tray_icon`). Its entire purpose was tearing down a fallback
AppIndicator3 icon once the Shell-native one caught up - with no more fallback icon to ever build in the
first place, this can't happen anymore. Also remove its call site: `self._recheck_tray_icon_after_extension_change()`
in `do_startup`.

**Narrow `_check_shell_extension_health` - keep its version-staleness check, remove its tray-button check.**
This method currently does two unrelated things: (1) warns if the extension's clipboard/region-select API
is stale after an upgrade (`EXPECTED_API_VERSION`/`get_live_api_version()`, still valid - clipboard and
region-select keep using `orcshot-clipboard@orcshot.org` unchanged per this plan's own scope), and (2) warns
if the tray button specifically failed to activate (`shell_tray_button_active()`/`get_tray_button_error()`).
Remove only part (2) - the `if not shell_tray_button_active(): ...` block and its notification - keeping
part (1) (the staleness check and its own notification) exactly as-is, including its own `is_available()`
guard and early-return structure above the removed block.

**Ruling, recorded because it's a real, deliberate scope decision, not a silent gap:** this removal drops
the "your tray icon fell back to a plain version" notification with no replacement. There is no longer a
fallback to report on the *Wayland* side - the new `orcshot-tray@orcshot.org` extension is unconditional -
and building an equivalent health-check for it would mean Orcshot querying back into extension-hosted state,
which is a real, separate design question this plan doesn't take on. If `orcshot-tray@orcshot.org` doesn't
activate (first boot before a relogin, a user disabling extensions, a stale cache after upgrade - the same
real scenarios the removed code already enumerated), the user now gets no tray icon *and* no notification
explaining why, whereas before they got a degraded-but-present icon with a notification. Cost if this
matters: a real, silent UX regression for whichever of those scenarios actually occurs; recorded in this
plan's own Task 7 as something to watch for during live verification, and worth its own BACKLOG.md follow-up
if Task 7 confirms it's a real, frequent enough gap to need its own fix.

Run: `.venv/bin/pytest tests/ -q` after this step - same expectation as Step 5 below, confirms nothing else
references the removed methods.

- [ ] **Step 5: Manual verification (no automated test - needs a real Wayland session)**

Run: `.venv/bin/pytest tests/ -q`
Expected: full suite still green - this task doesn't add new testable pure logic, it wires together
Tasks 1-3, so the safety net here is "nothing else broke," not new coverage.

- [ ] **Step 6: Commit**

```bash
git add src/orcshot/app.py
git commit -m "Wire the Wayland tray onto the new Gio.Menu export, drop AppIndicator3"
```

---

### Task 5: Remove the old extension's now-dead tray code

**Plan amendment (recorded in the SDD ledger):** the originally dispatched implementer correctly
refused to execute Step 1 literally and reported BLOCKED with two concrete, evidence-backed findings:
(1) `app.py` still has a live caller of the exact `TRAY_IFACE`/`OrcshotTray` D-Bus interface Step 1
says to delete wholesale (`_notify_tray_extension_quitting()`, called from `_quit_and_hide_tray_button`
and `_maybe_restart_after_language_change`, invoking the `Quitting` method Step 1's own XML block
defines) - the same class of oversight Task 4's Step 4 already fixed for three sibling functions, just
missed for this fourth one; (2) Step 1's 8-identifier list undersizes the real dead-code surface by
roughly 150 lines - a whole self-contained tray-button subsystem (`_buildTrayButton` and everything it
alone calls) that Step 1 as originally written would leave behind as unreachable code with a dangling
reference to the deleted `TRAY_MODE_ITEMS` constant.

**Ruling:** both findings are real and load-bearing, not the implementer being overcautious. Removing
`_notify_tray_extension_quitting()` is correct and safe: the new `orcshot-tray@orcshot.org` extension
(Task 3) already tears its own button down automatically via `Gio.bus_watch_name`'s vanished-callback
when Orcshot's bus name drops at quit, so there is nothing left for an explicit `Quitting()` D-Bus call
to accomplish once the old extension's tray machinery is gone. Task 5 is expanded (below) to remove the
full tray-button subsystem, not just the original 8 identifiers, and to remove
`_notify_tray_extension_quitting` and its two `app.py` call sites. Cost if this ruling is wrong: the
`Quitting()` call was serving some purpose invisible to this plan/spec (none found in the design doc or
git history during this ruling) - if Task 7's live verification ever shows a stale tray icon lingering
briefly after quit that this removal caused, that's the signal this ruling was wrong; recorded here for
that live-verification pass to watch for.

**Files:**
- Modify: `src/orcshot/resources/gnome-shell-extensions/orcshot-clipboard@orcshot.org/extension.js`
- Modify: `src/orcshot/capture/gnome_region_select.py`
- Modify: `src/orcshot/app.py` (only `_notify_tray_extension_quitting` and its two call sites, plus the
  `_remember_region` call site to `notify_repeat_available` Step 2 already covers - nothing else in this
  large file)
- Modify: `debian/rules`
- Delete: `po/orcshot-tray.pot`

**Interfaces:**
- Consumes: nothing new. This task only removes code Task 3/4 made unreachable, plus (per the ruling
  above) the one caller Task 4 missed. If any function this task removes still has a live caller beyond
  what this amended text already accounts for, treat that as a new, separate load-bearing finding - stop
  and confirm before removing, don't silently remove a function something still calls.

- [ ] **Step 1: Remove the old extension's entire tray-button subsystem**

In `orcshot-clipboard@orcshot.org/extension.js`, remove the full tray-button subsystem, confirmed by the
blocked implementer's own full read of the file:

- `TRAY_OBJECT_PATH`, the D-Bus interface XML block (named `TRAY_IFACE` in the live file; contains
  `SetRepeatAvailable`, `HasTrayButton`, `GetTrayButtonError`, and `Quitting` method declarations),
  `TRAY_MODE_ITEMS`
- `_ensureTrayButton`, `_activateTrayAction`, `_buildTrayButton`, `_setAppAvailable`, `_trayIconPath`
- The D-Bus method implementations: `SetRepeatAvailable`, `HasTrayButton`, `GetTrayButtonError`,
  `Quitting`
- The `_appWatchId`/`Gio.bus_watch_name(...)` block inside `enable()`/`disable()` (exists solely to
  drive tray-button sensitivity - nothing else depends on it)
- `_loadTrayCatalog`, `_parseMoFile`, `_readOrcshotLanguageOverride` (called only from inside
  `_ensureTrayButton`)
- `_extractionOnlyTrayModeLabels`, `_trayRoundedRectPath`, `_TRAY_ICON_SIZE`
- Instance fields: `_trayButton`, `_trayButtonError`, `_appAvailable`, `_repeatAvailable`,
  `_enabledAtUs`, `_repeatItem`, `_repeatIconArea`, `_appGatedItems`, `_logoIcon`
- The `this._trayDbus` wrap/export/unexport calls in `enable()`/`disable()`

**Must be kept - shared with the still-live destination picker, do NOT remove:** `_loadIconGeometry()`
(also called by `pickDestinationAsync`), `_buildDrawnMenuItem()` (also called by `pickDestinationAsync`),
`_renderIconGeometry()` (called transitively via `_buildDrawnMenuItem`'s own drawing-area repaint
handler). Grep each removal candidate for callers before deleting it - if a name you're about to remove
turns out to have a caller outside the tray-button subsystem, stop and treat that as a new finding rather
than removing it anyway.

Keep everything related to region-select (`StartRegionSelect`) and clipboard
(`org.orcshot.Orcshot.Clipboard`-style interfaces) exactly as-is - only tray-button code is dead here.

- [ ] **Step 1b: Remove `app.py`'s now-dead `Quitting()` caller**

Remove `_notify_tray_extension_quitting` in full (`app.py`, confirmed at lines 701-725 as of the blocked
implementer's read - re-confirm the live range) and both its call sites: inside
`_quit_and_hide_tray_button` (around line 698) and inside `_maybe_restart_after_language_change` (around
line 837). These calls invoke the `Quitting` D-Bus method Step 1 deletes from the old extension's
`TRAY_IFACE` - once that method no longer exists on the other end, calling it would raise a live D-Bus
error at quit time and at every language-change restart, so this removal isn't optional cleanup, it's
required for Step 1 to be safe to land at all.

- [ ] **Step 2: Remove the now-dead Python wrapper functions**

In `gnome_region_select.py`, remove `shell_tray_button_active()`, `notify_repeat_available()`, and
`get_tray_button_error()` (their only caller, `app.py`'s old `_build_tray_icon` Wayland branch, was deleted
in Task 4). Search for any other callers first:
`grep -rn "shell_tray_button_active\|notify_repeat_available\|get_tray_button_error" src/`
- if `_remember_region`'s call to `notify_repeat_available` (mentioned in that function's own docstring
  from the original code) still exists, remove that call site too, and check whether
  `notify_repeat_available`'s own docstring reasoning ("push to the Shell-native tray panel button... no
  way to poll this app's last_region state") still applies - it doesn't, once Task 3/4 land, since the new
  extension reads live from the exported `Gio.Menu`/`items-changed` instead of needing a push.

- [ ] **Step 3: Remove the dead `orcshot-tray.mo` derivation from packaging**

In `debian/rules`, remove the second `for po in po/??.po; do ... orcshot-tray.mo ...; done` block and its
preceding "Task #183 follow-up" comment block (the one deriving
`orcshot-clipboard@orcshot.org/locale/$lang/LC_MESSAGES/orcshot-tray.mo` via `msgmerge`/`po/orcshot-tray.pot`)
- confirmed dead: the new extension has no gettext domain of its own at all, translation happens
Python-side in `_export_tray_menu` (Task 4) using the same catalog the rest of the app already loads.

```bash
git rm po/orcshot-tray.pot
```

- [ ] **Step 4: Run the full suite and lint the removed-code paths**

Run: `.venv/bin/pytest tests/ -q`
Expected: full suite green - if anything references the removed Python functions, this catches it as an
import/collection error, not a silent gap.

- [ ] **Step 5: Commit**

```bash
git add "src/orcshot/resources/gnome-shell-extensions/orcshot-clipboard@orcshot.org/extension.js" \
        src/orcshot/capture/gnome_region_select.py src/orcshot/app.py debian/rules
git commit -m "Remove the old extension's now-dead tray-button code and its .mo derivation"
```

---

### Task 6: Package the new extension

**Files:**
- Modify: `debian/orcshot.install`

**Interfaces:** none - purely packaging.

- [ ] **Step 1: Add install lines for the new extension**

Add these two lines to `debian/orcshot.install`, matching the existing style for the other two bundled
extensions:

```
src/orcshot/resources/gnome-shell-extensions/orcshot-tray@orcshot.org/extension.js usr/share/gnome-shell/extensions/orcshot-tray@orcshot.org/
src/orcshot/resources/gnome-shell-extensions/orcshot-tray@orcshot.org/metadata.json usr/share/gnome-shell/extensions/orcshot-tray@orcshot.org/
```

- [ ] **Step 2: Build the package and confirm the new extension is present**

Run: `dpkg-buildpackage -us -uc -b`
Run: `dpkg -c ../orcshot_*_all.deb | grep orcshot-tray`
Expected: both `extension.js` and `metadata.json` listed under
`usr/share/gnome-shell/extensions/orcshot-tray@orcshot.org/`

- [ ] **Step 3: Lint**

Run: `lintian ../orcshot_*_all.deb`
Expected: zero new errors (matches RELEASING.md's own existing standard).

- [ ] **Step 4: Commit**

```bash
git add debian/orcshot.install
git commit -m "Package the new orcshot-tray@orcshot.org extension"
```

---

### Task 7: Real end-to-end verification

**Files:** none - this is a live-testing task, per this project's established convention that
Shell-extension behavior is verified live, not by an automated test suite.

**Interfaces:** none - this task consumes the finished result of Tasks 1-6 as a whole.

- [ ] **Step 1: Real logout/login test on a genuine Wayland session**

Install the freshly-built `.deb` (`sudo apt install ./orcshot_*_all.deb`) on a real Ubuntu 24.04 or 26.04
Wayland session (VM or hardware), full logout/login (not a lock/unlock - see this plan's Global
Constraints), then confirm: the tray icon appears with a correctly-drawn Orcshot icon (not a system theme
icon, not a right-aligned or missing icon), every menu item shows the correct label and a correctly
left-aligned icon, and each item actually performs its action (a real region capture, opening Preferences,
Quit actually quitting).

- [ ] **Step 2: Confirm translation**

Switch Orcshot's language in Preferences to a non-English language, restart (matching the app's own
existing restart-for-language-change flow), and confirm the tray menu shows correctly translated text -
no separate extension-side translation step should be needed (Task 4's `_export_tray_menu` uses the app's
own already-loaded catalog).

- [ ] **Step 3: A real, minimal Snap-confinement check**

This is the actual proof this whole redesign was aiming for - confirm nothing above is blocked under
genuine strict confinement, not just reasoned to be safe.

Write a minimal `snapcraft.yaml` (throwaway, not a production package - see the spec's own "Explicitly out
of scope" section) with `confinement: strict` and a `desktop` interface plug, wrapping just enough of
Orcshot to reach the point of calling `_export_tray_menu()`. Build it (`snapcraft`), install it
(`sudo snap install --dangerous ./orcshot_*.snap`), run it, and confirm via `journalctl` that the
`export_menu_model` call succeeds with no AppArmor denial logged (the same kind of check this project used
live throughout this whole design's own research phase - `apparmor="DENIED"` lines are the specific,
searchable signal to confirm are absent).

- [ ] **Step 4: Record the result**

Whatever Step 3 finds - success or a real, new blocker - write it into `BACKLOG.md` under a closing note on
#184's own entry, the same way every other finding this design was built on got recorded. If it's a real
blocker, this plan's own remaining tasks may need revisiting; if it confirms clean, #184 can be marked
resolved and this becomes the basis for actually building the Snap/Flatpak distribution channels
(BACKLOG.md #185 and beyond).
