# Tray Modernization (BACKLOG #189) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove `Gtk.StatusIcon` (deprecated, XEmbed-based, likely already invisible on GNOME-X11)
entirely, replacing it with the real support matrix's two native mechanisms: the existing GNOME
Shell extension (extended to X11 sessions too, plus real left-click) and a brand-new Cinnamon
Spices applet.

**Architecture:** Both desktops consume the exact same, already-existing server-side export
(`gnome_tray_export.py`'s `Gio.Menu` over D-Bus, plus every tray action already exported via the
app's standard `org.gtk.Actions` interface) - no new server-side surface. `app.py` stops building
any local widget at all: once this lands, the app never constructs a tray icon itself on any
desktop, it only exports; each desktop's own shell (GNOME Shell / Cinnamon) loads whichever of the
two bundled extension/applet files it understands and renders the icon itself. This is a
deliberate simplification versus the design spec's "detect `XDG_CURRENT_DESKTOP`, branch in
Python" framing (spec section "Design > 1") - found while planning that no Python-side detection
is needed at all, since GNOME Shell only ever loads GNOME Shell extensions and Cinnamon only ever
loads Cinnamon applets; shipping both files unconditionally and letting each desktop's own loader
sort it out is simpler and has no misdetection risk. Everything else in the spec (left-click
behavior, packaging shape, scope, Cinnamon-Wayland caveat) is unchanged.

**Tech Stack:** Python/PyGObject (`app.py`), GJS/ESM (GNOME Shell extension), GJS/legacy `imports.*`
(Cinnamon applet - confirmed via this session's real, installed `/usr/share/cinnamon/js/ui/applet.js`,
Cinnamon 6.6.9 on this host), Debian packaging (`debian/orcshot.install`).

**Spec:** `docs/superpowers/specs/2026-09-05-tray-modernization-design.md`

## Global Constraints

- Scope is strictly GNOME (Ubuntu 24.04/26.04, X11+Wayland) and Cinnamon (Mint, X11 now/Wayland
  later) - no XFCE/KDE/MATE work of any kind.
- `Gtk.StatusIcon` and its local `Gtk.Menu` path must be deleted entirely, not kept as a fallback.
- Cinnamon-on-Wayland must never be claimed as verified/working anywhere (code, commit messages,
  BACKLOG) until a real Mint 23 install confirms it - ship session-agnostic, record it as
  unverified.
- Real values to reuse exactly, never rename: `BUS_NAME = "org.orcshot.Orcshot"`,
  `MENU_PATH = "/org/orcshot/Orcshot/TrayMenu"`, `ACTIONS_PATH = "/org/orcshot/Orcshot"`, default
  left-click action name `"tray-region"`.
- direflail must see the real generated diffs (extension.js, the new applet.js/metadata.json,
  the debian/orcshot.install diff, the app.py diff) before anything ships as a PR - standing
  requirement, not optional.
- No task subagent pushes to main directly - PR-only, controller merges after direflail's explicit
  confirmation.

---

## Task 1: Delete the local X11 tray widget; export unconditionally

**Files:**
- Modify: `src/orcshot/app.py:201-237` (`do_startup`), `src/orcshot/app.py:894-1067`
  (`_build_tray_icon`, `_build_tray_menu`, `_show_tray_menu`), `src/orcshot/app.py:171`,
  `src/orcshot/app.py:193`, `src/orcshot/app.py:230` (init/call sites),
  `src/orcshot/app.py:390-406` (`_remember_region`)

**Interfaces:**
- Consumes: `orcshot.capture.gnome_tray_export.export_tray_menu`/`build_tray_menu` (unchanged,
  already exist).
- Produces: nothing new. `self._tray_repeat_action` (already exists, unchanged) remains the only
  mechanism `_remember_region` needs - both later consumers (Tasks 2 and 3) read its `enabled`
  state over the existing `org.gtk.Actions` D-Bus interface, same as today.

Real current code being touched (`app.py`):

```python
    def do_startup(self):
        Gtk.Application.do_startup(self)
        _log_session_info()
        Gtk.Window.set_default_icon_from_file(str(LOGO_PATH))
        self._register_tray_actions()
        if os.environ.get("XDG_SESSION_TYPE") == "wayland":
            # ... (comment block)
            try:
                self._export_tray_menu()
            except (GLib.Error, AttributeError) as e:
                print(f"[orcshot] _export_tray_menu() failed: {e}", file=sys.stderr)
        self._tray_icon = self._build_tray_icon()
        self._check_shell_extension_health()
```

- [ ] **Step 1: Make the menu export unconditional**

`_export_tray_menu()` itself (`app.py:649-688`) has nothing Wayland-specific in its body - it's a
plain `Gio.Menu` build + D-Bus export, safe on every desktop. Both GNOME-X11 and Cinnamon now need
this export just as much as Wayland always did. Remove the `if os.environ.get("XDG_SESSION_TYPE")
== "wayland":` gate so the try/except always runs:

```python
        self._register_tray_actions()
        # Every desktop this project supports (GNOME X11/Wayland, Cinnamon
        # X11/Wayland) now consumes this export - see BACKLOG #189's
        # tray-modernization plan. _export_tray_menu()'s own body has
        # nothing session-specific in it.
        try:
            self._export_tray_menu()
        except (GLib.Error, AttributeError) as e:
            print(f"[orcshot] _export_tray_menu() failed: {e}", file=sys.stderr)
        self._check_shell_extension_health()
```

Keep the existing comment above the try/except (the one explaining why a bare except-and-continue
matters here) - only the `if` gate and the `self._tray_icon = self._build_tray_icon()` line go
away.

Leave `_check_shell_extension_health()` (`app.py:858-893`) and its own internal
`XDG_SESSION_TYPE != "wayland": return` guard completely untouched - it checks the
*clipboard*/*region-select* GNOME extensions for a stale-cache-after-upgrade condition, which
remain Wayland-only concerns (X11's clipboard/region-select still use native Xlib code, not a
Shell extension, regardless of desktop). Don't broaden this function; it is not part of this
task.

- [ ] **Step 2: Delete `_build_tray_icon`, `_build_tray_menu`, `_show_tray_menu`**

Delete all three methods (`app.py:894-1067` in full - the whole `_build_tray_icon` method, the
whole `_build_tray_menu` method including its nested `menu_item` helper, and `_show_tray_menu`).
Nothing else in the file calls any of them once Step 1's `do_startup` edit lands.

- [ ] **Step 3: Remove the now-permanently-dead `_tray_icon`/`_repeat_item` state**

`self._tray_icon = None` (`app.py:171`) - delete this line; nothing sets or reads
`self._tray_icon` anywhere once Step 2 lands.

`self._repeat_item = None` (`app.py:193`) - delete this line; its only setter was inside the
now-deleted `_build_tray_menu`.

In `_remember_region` (`app.py:390-406`), remove the now-permanently-`None` guard:

```python
    def _remember_region(self, rect) -> None:
        self.last_region = rect
        # Updating the exported GAction's own `enabled` property is
        # sufficient - it propagates to every real consumer (GNOME
        # Shell extension, Cinnamon applet) automatically over the
        # org.gtk.Actions D-Bus interface (Gio.SimpleAction.set_enabled),
        # no export/refresh step of our own needed the way the menu
        # structure itself (_export_tray_menu) does.
        if self._tray_repeat_action is not None:
            self._tray_repeat_action.set_enabled(True)
```

- [ ] **Step 4: Verify by import and grep, then run the existing suite**

`app.py` has no dedicated unit test file today (it's GTK/D-Bus glue, matching this project's own
established "no meaningful headless test" pattern for files like this) - real verification here
is: confirm the file still imports cleanly, confirm no dangling references remain, and confirm
nothing else in the suite broke.

```bash
cd /home/direflail/projects/orcshot
python3 -c "import orcshot.app"
grep -n "_build_tray_icon\|_build_tray_menu\|_show_tray_menu\|self\._tray_icon\|self\._repeat_item" src/orcshot/app.py
```

Expected: the import succeeds with no traceback; the grep prints nothing (all four names are now
fully gone from the file).

```bash
python3 -m pytest tests/unit -q
```

Expected: PASS, same pass count as before this task (this task deletes dead code and removes a
conditional - it should not change any existing test's outcome).

- [ ] **Step 5: Commit**

```bash
git add src/orcshot/app.py
git commit -m "BACKLOG #189: delete Gtk.StatusIcon, export tray menu on every desktop

Gtk.StatusIcon depends on the legacy XEmbed tray protocol, which GNOME
Shell hasn't hosted since 3.26 (any session type) - X11 GNOME users
likely got an invisible tray icon already. Both remaining supported
desktops (GNOME, Cinnamon) will consume the existing Gio.Menu/
org.gtk.Actions D-Bus export via their own native extension/applet
(Tasks 2-3), so app.py no longer builds any local widget - it only
exports, unconditionally, on every desktop."
```

---

## Task 2: GNOME extension - real left-click, remove diagnostics

**Files:**
- Modify: `src/orcshot/resources/gnome-shell-extensions/orcshot-tray@orcshot.org/extension.js`

**Interfaces:**
- Consumes: `this._actionGroup` (`Gio.DBusActionGroup`, already built in `_init`, unchanged),
  action name `'tray-region'` (bare, no `app.` prefix - matches this file's own existing
  `bareAction` handling at line 168, and `app.py`'s `Gio.SimpleAction.new(f"tray-{mode}", None)`
  with `mode="region"`).
- Produces: nothing new for later tasks - this is the GNOME-only half of the click-behavior
  contract Task 3 (Cinnamon) independently re-implements against the same server-side actions.

The whole file's diagnostic logging (added for a since-resolved menu-doesn't-open bug, per the
file's own "TEMPORARY diagnostics... remove once the menu-doesn't-open bug is actually found"
comment) is removed in this task, alongside adding the real click split.

- [ ] **Step 1: Replace the `_init` diagnostics block and button-press-event handler**

Real current code (lines 44-61):

```js
        // TEMPORARY diagnostics (Task 7 live debugging, direflail
        // asked for click-behavior visibility) - remove once the
        // menu-doesn't-open bug is actually found. All go through
        // log() with a fixed, greppable prefix so `journalctl
        // GLIB_DOMAIN=GNOME Shell` or a plain grep for
        // "orcshot-tray-diag" finds every line.
        log(`orcshot-tray-diag: _init starting, get_n_items()=${this._menuModel.get_n_items()}`);
        this.connect('button-press-event', () => {
            log('orcshot-tray-diag: button-press-event fired');
            return Clutter.EVENT_PROPAGATE;
        });
        this.connect('touch-event', () => {
            log('orcshot-tray-diag: touch-event fired');
            return Clutter.EVENT_PROPAGATE;
        });
        this.menu.connect('open-state-changed', (menu, open) => {
            log(`orcshot-tray-diag: menu open-state-changed, open=${open}, numMenuItems=${this.menu.numMenuItems}`);
        });
```

Replace with:

```js
        // BACKLOG #189: left-click captures directly (matching the
        // real Windows tray default, and X11's own former
        // Gtk.StatusIcon "activate" signal before it was deleted) -
        // right-click (or any other button) falls through to
        // PanelMenu.Button's own default handling, which toggles
        // this.menu, unchanged from today.
        this.connect('button-press-event', (actor, event) => {
            if (event.get_button() === Clutter.BUTTON_PRIMARY) {
                this._actionGroup.activate_action('tray-region', null);
                return Clutter.EVENT_STOP;
            }
            return Clutter.EVENT_PROPAGATE;
        });
```

- [ ] **Step 2: Remove the remaining diagnostic `log()` calls**

In the `items-changed` handler (lines 65-68):

```js
        this._itemsChangedId = this._menuModel.connect('items-changed', (model, pos, removed, added) => {
            this._rebuild();
        });
```

In the `action-enabled-changed` handler (lines 69-79, keep the explanatory comment, drop only the
`log(...)` line):

```js
        this._actionEnabledChangedId = this._actionGroup.connect('action-enabled-changed', (group, name, enabled) => {
            // A full rebuild, not a targeted item lookup: this fires
            // rarely (once per capture, for "repeat_region" only, see
            // app.py's _remember_region) so the cost of re-walking the
            // whole menu is not a real concern, and it's the same
            // "just re-render everything" approach 'items-changed'
            // above already takes rather than maintaining a parallel
            // name-to-item map.
            this._rebuild();
        });
```

In `_rebuild()` (lines 98-104), drop both `log(...)` lines:

```js
    _rebuild() {
        this._disconnectSectionSignals();
        this.menu.removeAll();
        this._addModelItems(this._menuModel);
    }
```

In `enable()` (lines 179-213), drop the three `log(...)` calls (`'bus name appeared'`,
`'button constructed and added to status area'`, `'bus name vanished'`) - keep every other line
(the `try`/`catch` with `logError`, the role-name comment, the watch/unwatch structure) unchanged.

- [ ] **Step 3: Live-verify on the real Ubuntu 26.04 GNOME Wayland VM**

Per the VM registry: start the VM, launch Orcshot from the on-screen terminal (not a detached
SSH command - see the registry's own gotcha about `WAYLAND_DISPLAY`/`XDG_SESSION_TYPE`). Confirm:
left-click on the tray icon triggers a real region capture (a real crosshair overlay appears);
right-click still opens the tray menu with all items present and correctly enabled/disabled
(Repeat Last Region greyed out until a region has actually been captured once).

- [ ] **Step 4: Live-verify on the same VM, switched to GNOME X11**

At the GDM login screen, select the gear icon and choose "Ubuntu on Xorg" before logging in
(real X11 GNOME session - this is the case Task 1 made newly reachable, since the extension no
longer needs `XDG_SESSION_TYPE == "wayland"` to be exported to). Repeat Step 3's checks. This is
real, live confirmation of the spec's central hypothesis - that GNOME-X11 previously got an
invisible `Gtk.StatusIcon` and now gets a working extension-based tray instead. Report plainly
what was actually seen on screen (a rendered icon, a working left-click, a working right-click
menu) - don't just assert it worked.

- [ ] **Step 5: Commit**

```bash
git add src/orcshot/resources/gnome-shell-extensions/orcshot-tray@orcshot.org/extension.js
git commit -m "BACKLOG #189: real left-click on the GNOME tray, drop debug logging

button-press-event now activates tray-region directly on a primary
click, matching X11's former Gtk.StatusIcon behavior and the real
Windows tray default. The Task 7 diagnostic log() calls (added to
chase a since-resolved menu-doesn't-open bug) are removed."
```

---

## Task 3: New Cinnamon applet

**Files:**
- Create: `src/orcshot/resources/cinnamon-applets/orcshot-tray@orcshot.org/metadata.json`
- Create: `src/orcshot/resources/cinnamon-applets/orcshot-tray@orcshot.org/applet.js`

**Interfaces:**
- Consumes: the same `BUS_NAME = 'org.orcshot.Orcshot'`, `MENU_PATH =
  '/org/orcshot/Orcshot/TrayMenu'`, `ACTIONS_PATH = '/org/orcshot/Orcshot'`, action name
  `'tray-region'` as Task 2's extension.js - same server, same contract, different consumer.
- Produces: nothing later tasks depend on directly; Task 4 packages the two files this task
  creates.

Confirmed against this host's real, installed `/usr/share/cinnamon/js/ui/applet.js` (Cinnamon
6.6.9) rather than guessed - this resolves the spec's one flagged-open item:

- `Applet`'s own `_onButtonPressEvent` (base class, never overridden by us) already handles the
  click split *for us*: button 1 calls `this.on_applet_clicked(event)` (meant to be overridden by
  subclasses - exactly matching Task 2's left-click contract); button 3 toggles
  `this._applet_context_menu` automatically, *if it has any items* (`_getMenuItems().length > 0`).
  There is no need to override `_onButtonPressEvent` or inspect `event.get_button()` ourselves at
  all.
- `this._applet_context_menu` (an `AppletContextMenu extends PopupMenu.PopupMenu`, constructed by
  the base class itself) is also where Cinnamon's own built-in "Remove '<name>' from panel" /
  "Configure..." / "About..." items get added (`applet.js:580-619` on this host). The correct,
  idiomatic way to get our tray items to show up on right-click *alongside* Cinnamon's own
  built-in ones is to add our own `PopupMenu.PopupMenuItem`s into this same
  `this._applet_context_menu` - not to construct a second, separate menu.

`metadata.json`:

```json
{
  "uuid": "orcshot-tray@orcshot.org",
  "name": "Orcshot Tray",
  "description": "Renders Orcshot's tray icon and menu from the app's own exported Gio.Menu - the Cinnamon counterpart to orcshot-tray@orcshot.org's GNOME Shell extension.",
  "cinnamon-version": ["5.0", "5.2", "5.4", "5.6", "5.8", "6.0", "6.2", "6.4", "6.6", "6.8"],
  "max-instances": "1"
}
```

`applet.js`:

```js
const Applet = imports.ui.applet;
const Gio = imports.gi.Gio;
const PopupMenu = imports.ui.popupMenu;
const St = imports.gi.St;

// Must match app.py's fixed application_id and gnome_tray_export.py's
// TRAY_MENU_PATH exactly - same values orcshot-tray@orcshot.org's
// GNOME Shell extension uses, see that file's own comment.
const BUS_NAME = 'org.orcshot.Orcshot';
const MENU_PATH = '/org/orcshot/Orcshot/TrayMenu';
const ACTIONS_PATH = '/org/orcshot/Orcshot';

class OrcshotTrayApplet extends Applet.IconApplet {
    constructor(metadata, orientation, panel_height, instance_id) {
        super(orientation, panel_height, instance_id);

        // Same real app logo the GNOME extension uses
        // (Gio.ThemedIcon.new("orcshot"), usr/share/icons/hicolor/
        // 128x128/apps/orcshot.png via debian/orcshot.install) - not a
        // generic action icon, so no theme ships a replacement for a
        // name it's never heard of.
        this.set_applet_icon_symbolic_name('orcshot');
        this.set_applet_tooltip('Orcshot');

        this._menuModel = Gio.DBusMenuModel.get(Gio.DBus.session, BUS_NAME, MENU_PATH);
        this._actionGroup = Gio.DBusActionGroup.get(Gio.DBus.session, BUS_NAME, ACTIONS_PATH);

        this._sectionSignalIds = [];
        this._rebuild();
        this._itemsChangedId = this._menuModel.connect('items-changed', () => this._rebuild());
        this._actionEnabledChangedId = this._actionGroup.connect(
            'action-enabled-changed', () => this._rebuild());
    }

    // Called automatically by Applet's own _onButtonPressEvent on a
    // primary (left) click - see this file's own header comment for
    // why no manual button.get_button() check is needed here.
    on_applet_clicked(event) {
        this._actionGroup.activate_action('tray-region', null);
    }

    _disconnectSectionSignals() {
        for (let [model, id] of this._sectionSignalIds)
            model.disconnect(id);
        this._sectionSignalIds = [];
    }

    // Populates this._applet_context_menu (built by the Applet base
    // class itself) directly, rather than a separate menu of our own -
    // this is what makes our items show up on right-click alongside
    // Cinnamon's own built-in Remove/Configure/About entries, which
    // the base class also adds to this same menu instance.
    _rebuild() {
        this._disconnectSectionSignals();
        this._applet_context_menu.removeAll();
        this._addModelItems(this._menuModel);
    }

    // Same recursive section-walk as orcshot-tray@orcshot.org's GNOME
    // Shell extension (_addModelItems there) - same Gio.MenuModel
    // shape, same reasoning for why every section link needs its own
    // 'items-changed' listener.
    _addModelItems(model) {
        let n = model.get_n_items();
        for (let i = 0; i < n; i++) {
            let section = model.get_item_link(i, Gio.MENU_LINK_SECTION);
            if (section) {
                if (this._applet_context_menu._getMenuItems().length > 0)
                    this._applet_context_menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());
                let id = section.connect('items-changed', () => this._rebuild());
                this._sectionSignalIds.push([section, id]);
                this._addModelItems(section);
                continue;
            }

            let label = model.get_item_attribute_value(i, 'label', null)?.deep_unpack() ?? '';
            let action = model.get_item_attribute_value(i, 'action', null)?.deep_unpack();
            let iconValue = model.get_item_attribute_value(i, 'icon', null);

            let item = new PopupMenu.PopupIconMenuItem(
                label, iconValue ? Gio.Icon.deserialize(iconValue) : null,
                St.IconType.SYMBOLIC);
            let bareAction = null;
            if (action) {
                bareAction = action.includes('.') ? action.split('.').slice(1).join('.') : action;
                item.connect('activate', () => this._actionGroup.activate_action(bareAction, null));
                item.setSensitive(this._actionGroup.get_action_enabled(bareAction));
            }
            this._applet_context_menu.addMenuItem(item);
        }
    }
}

function main(metadata, orientation, panel_height, instance_id) {
    return new OrcshotTrayApplet(metadata, orientation, panel_height, instance_id);
}
```

- [ ] **Step 1: Write both files exactly as above**

**Deliberate scope boundary, not an oversight**: `first_run_setup.py`'s existing first-run wizard
auto-enables the three GNOME extensions via `enable_extension`/`enable_extension_live`
(gsettings + live D-Bus `EnableExtension`, both GNOME-Shell-only mechanisms - `TRAY_EXTENSION_UUID`
is reused for the Cinnamon applet's *file path* in Task 4, but must NOT be added to that GNOME-only
enable loop). Cinnamon has its own separate mechanism for this (writing to `org.cinnamon`'s own
`enabled-applets` gsettings key), but auto-enabling the applet on first run was never part of the
approved spec - only installing the files was. A Mint user adds it manually via Cinnamon Settings
> Applets > "+" (the same step Step 2 below performs for verification). If direflail wants
first-run auto-enable for Cinnamon too, that's a real, separate follow-up - flag it, don't build
it silently here.

- [ ] **Step 2: Live-install and verify on the real Mint/Cinnamon dev host**

Copy both files into the real per-user applets path and enable the applet:

```bash
mkdir -p ~/.local/share/cinnamon/applets/orcshot-tray@orcshot.org
cp src/orcshot/resources/cinnamon-applets/orcshot-tray@orcshot.org/{applet.js,metadata.json} \
   ~/.local/share/cinnamon/applets/orcshot-tray@orcshot.org/
```

Add it via `cinnamon-settings applets` (Panel tab, "+", search "Orcshot Tray", Add), or `dconf`
if driving this headlessly is easier. With Orcshot itself running (so the D-Bus export exists to
consume):

- Confirm the real icon renders in the panel.
- Left-click: confirm a real region capture starts.
- Right-click: confirm the menu shows both the Orcshot tray items (Capture Region, Capture Full
  Screen, etc.) *and* Cinnamon's own built-in "Remove 'Orcshot Tray' from panel" / "Configure..."
  entries in the same menu. Describe exactly what appears on screen - this is the one part of the
  design that was a real open question, now resolved against source but not yet watched live.

- [ ] **Step 3: Commit**

```bash
git add src/orcshot/resources/cinnamon-applets/orcshot-tray@orcshot.org/
git commit -m "BACKLOG #189: add native Cinnamon tray applet

Consumes the same Gio.Menu/org.gtk.Actions D-Bus export the GNOME
Shell extension already uses. Populates Cinnamon's own
_applet_context_menu directly (confirmed against this host's real
/usr/share/cinnamon/js/ui/applet.js) so our items appear alongside
Cinnamon's built-in Remove/Configure entries on right-click; left-click
is handled automatically via on_applet_clicked. Built session-agnostic
- not yet verified on Cinnamon-Wayland since Mint 23 hasn't shipped."
```

---

## Task 4: Packaging

**Files:**
- Modify: `debian/orcshot.install`
- Modify: `snapcraft.yaml`
- Modify: `org.orcshot.Orcshot.yaml`
- Modify: `src/orcshot/ui/first_run_setup.py`
- Test: `tests/unit/test_first_run_setup.py` (create if it doesn't already cover the sandboxed-dir
  helpers - check first; extend the existing dest-dir tests' pattern either way)

**Interfaces:**
- Consumes: `orcshot.channel_detect.install_bundled_extension_if_needed` (unchanged signature:
  `(uuid: str, bundled_dir: Path, dest_parent: Path) -> bool`).
- Produces: nothing later tasks depend on.

- [ ] **Step 1: `debian/orcshot.install`**

Add two lines, mirroring the existing `orcshot-tray@orcshot.org` GNOME extension lines exactly
(same file, different destination root):

```
src/orcshot/resources/cinnamon-applets/orcshot-tray@orcshot.org/applet.js usr/share/cinnamon/applets/orcshot-tray@orcshot.org/
src/orcshot/resources/cinnamon-applets/orcshot-tray@orcshot.org/metadata.json usr/share/cinnamon/applets/orcshot-tray@orcshot.org/
```

- [ ] **Step 2: `snapcraft.yaml` - stage the applet the same way the GNOME extensions are staged**

The real, existing part (`snapcraft.yaml:158-162`):

```yaml
  bundled-extensions:
    plugin: dump
    source: src/orcshot/resources/gnome-shell-extensions
    organize:
      "*": share/orcshot/gnome-shell-extensions/
```

Add a new sibling part directly below it:

```yaml
  bundled-cinnamon-applets:
    plugin: dump
    source: src/orcshot/resources/cinnamon-applets
    organize:
      "*": share/orcshot/cinnamon-applets/
```

- [ ] **Step 3: `org.orcshot.Orcshot.yaml` - same for the Flatpak manifest**

The real, existing module (`org.orcshot.Orcshot.yaml:262-269`):

```yaml
  - name: bundled-extensions
    buildsystem: simple
    sources:
      - type: dir
        path: src/orcshot/resources/gnome-shell-extensions
    build-commands:
      - mkdir -p /app/share/orcshot/gnome-shell-extensions
      - cp -r . /app/share/orcshot/gnome-shell-extensions/
```

Add a new sibling module directly below it:

```yaml
  - name: bundled-cinnamon-applets
    buildsystem: simple
    sources:
      - type: dir
        path: src/orcshot/resources/cinnamon-applets
    build-commands:
      - mkdir -p /app/share/orcshot/cinnamon-applets
      - cp -r . /app/share/orcshot/cinnamon-applets/
```

This step is why Steps 2-3 above exist at all: `_extension_bundle_dir` (read next) resolves the
*installed*, real runtime path inside a built Snap/Flatpak (`$SNAP/share/orcshot/...` or
`/app/share/orcshot/...`) - it has nothing to do with the source tree layout. Without these two
manifest edits, `install_bundled_extension_if_needed` would look for a `cinnamon-applets`
directory that was never actually staged into the sandboxed build, and silently fail (returns
`False`, `all_installed` goes `False`, the Snap path shows the "connect personal-files" prompt for
no real reason).

- [ ] **Step 4: Read the existing sandboxed-channel install code before extending it**

Read `src/orcshot/ui/first_run_setup.py`'s `_extension_bundle_dir`, `_snap_real_home_extensions_dir`,
`_flatpak_home_extensions_dir`, and `_install_bundled_extensions_for_sandboxed_channel` in full
(they're short - roughly lines 120-200) to match their exact real structure before adding to it.
Real, current `_extension_bundle_dir` (do not change its signature - other callers rely on it
exactly as-is):

```python
def _extension_bundle_dir(uuid: str, env: dict = None) -> Path:
    if env is None:
        env = os.environ
    if env.get("SNAP"):
        return Path(env["SNAP"]) / "share" / "orcshot" / "gnome-shell-extensions" / uuid
    if env.get("FLATPAK_ID"):
        return Path("/app") / "share" / "orcshot" / "gnome-shell-extensions" / uuid
    raise ValueError("_extension_bundle_dir called outside snap/flatpak (env has neither SNAP nor FLATPAK_ID)")
```

- [ ] **Step 5: Add a new `_cinnamon_applet_bundle_dir` and the Cinnamon dest-dir helpers**

A new sibling function, not a change to `_extension_bundle_dir` - same real logic, pointed at the
new `cinnamon-applets` staging path from Steps 2-3:

```python
def _cinnamon_applet_bundle_dir(uuid: str, env: dict = None) -> Path:
    """Where the Cinnamon applet's files are bundled read-only inside a
    Snap or Flatpak package - same real reasoning as
    _extension_bundle_dir, pointed at the cinnamon-applets staging path
    snapcraft.yaml/org.orcshot.Orcshot.yaml's own bundled-cinnamon-applets
    part/module installs (BACKLOG #189)."""
    if env is None:
        env = os.environ
    if env.get("SNAP"):
        return Path(env["SNAP"]) / "share" / "orcshot" / "cinnamon-applets" / uuid
    if env.get("FLATPAK_ID"):
        return Path("/app") / "share" / "orcshot" / "cinnamon-applets" / uuid
    raise ValueError("_cinnamon_applet_bundle_dir called outside snap/flatpak (env has neither SNAP nor FLATPAK_ID)")
```

Directly below `_flatpak_home_extensions_dir`:

```python
def _snap_real_home_cinnamon_applets_dir(env: dict = None) -> Path:
    """Cinnamon's own per-user applets path, reached the same way
    _snap_real_home_extensions_dir reaches GNOME Shell's - via
    $SNAP_REAL_HOME, never $HOME (Snap redirects $HOME to a private,
    per-snap path Cinnamon never scans)."""
    if env is None:
        env = os.environ
    return Path(env["SNAP_REAL_HOME"]) / ".local" / "share" / "cinnamon" / "applets"


def _flatpak_home_cinnamon_applets_dir(env: dict = None) -> Path:
    """Cinnamon's own per-user applets path under Flatpak - plain
    $HOME, same reasoning as _flatpak_home_extensions_dir (Flatpak
    doesn't redirect $HOME the way Snap does)."""
    if env is None:
        env = os.environ
    return Path(env["HOME"]) / ".local" / "share" / "cinnamon" / "applets"
```

- [ ] **Step 6: Wire the Cinnamon applet into the existing install loop**

`_install_bundled_extensions_for_sandboxed_channel` currently installs three GNOME extension
UUIDs into one `dest_parent`. The Cinnamon applet needs a *different* `dest_parent`
(`.../cinnamon/applets`, not `.../gnome-shell/extensions`) *and* a different bundle-dir resolver
(`_cinnamon_applet_bundle_dir` from Step 5, not `_extension_bundle_dir` - they point at two
different staged directories per Steps 2-3). Same UUID string (`orcshot-tray@orcshot.org` - fine
to reuse, since the two are installed to entirely separate paths and never collide):

```python
def _install_bundled_extensions_for_sandboxed_channel(parent) -> bool:
    channel = detect_channel()
    if channel == "snap":
        gnome_dest_parent = _snap_real_home_extensions_dir()
        cinnamon_dest_parent = _snap_real_home_cinnamon_applets_dir()
    elif channel == "flatpak":
        gnome_dest_parent = _flatpak_home_extensions_dir()
        cinnamon_dest_parent = _flatpak_home_cinnamon_applets_dir()
    else:
        return False
    all_installed = True
    for uuid in (WINDOW_CALLS_EXTENSION_UUID, CLIPBOARD_EXTENSION_UUID, TRAY_EXTENSION_UUID):
        bundled_dir = _extension_bundle_dir(uuid)
        if not install_bundled_extension_if_needed(uuid, bundled_dir, gnome_dest_parent):
            all_installed = False
    cinnamon_bundled_dir = _cinnamon_applet_bundle_dir(TRAY_EXTENSION_UUID)
    if not install_bundled_extension_if_needed(TRAY_EXTENSION_UUID, cinnamon_bundled_dir, cinnamon_dest_parent):
        all_installed = False
    if not all_installed and channel == "snap":
        show_snap_connect_prompt(parent)
    return True
```

- [ ] **Step 7: Test the two new dest-dir helpers, and `_cinnamon_applet_bundle_dir`**

Mirror whatever test already exists for `_snap_real_home_extensions_dir`/
`_flatpak_home_extensions_dir` (find it first - `grep -rn
"_snap_real_home_extensions_dir\|_flatpak_home_extensions_dir" tests/`) and add the same shape of
test for the two new Cinnamon functions:

```python
def test_snap_real_home_cinnamon_applets_dir():
    env = {"SNAP_REAL_HOME": "/home/real-user"}
    assert _snap_real_home_cinnamon_applets_dir(env) == Path("/home/real-user/.local/share/cinnamon/applets")


def test_flatpak_home_cinnamon_applets_dir():
    env = {"HOME": "/home/real-user"}
    assert _flatpak_home_cinnamon_applets_dir(env) == Path("/home/real-user/.local/share/cinnamon/applets")


def test_cinnamon_applet_bundle_dir_snap():
    env = {"SNAP": "/snap/orcshot/x1"}
    assert _cinnamon_applet_bundle_dir("orcshot-tray@orcshot.org", env) == \
        Path("/snap/orcshot/x1/share/orcshot/cinnamon-applets/orcshot-tray@orcshot.org")


def test_cinnamon_applet_bundle_dir_flatpak():
    env = {"FLATPAK_ID": "org.orcshot.Orcshot"}
    assert _cinnamon_applet_bundle_dir("orcshot-tray@orcshot.org", env) == \
        Path("/app/share/orcshot/cinnamon-applets/orcshot-tray@orcshot.org")
```

Run: `python3 -m pytest tests/unit/test_first_run_setup.py -v` (adjust to the real existing test
file name found in Step 4's grep). Expected: PASS.

- [ ] **Step 8: Build the real `.deb` and confirm the applet is packaged**

```bash
# Use this project's own existing local .deb build process (check
# RELEASING.md or CI.md for the exact real command already in use
# rather than guessing a new one).
dpkg -c ../orcshot_*.deb | grep cinnamon/applets
```

Expected: both `applet.js` and `metadata.json` listed under
`usr/share/cinnamon/applets/orcshot-tray@orcshot.org/`.

- [ ] **Step 9: Commit**

```bash
git add debian/orcshot.install snapcraft.yaml org.orcshot.Orcshot.yaml \
        src/orcshot/ui/first_run_setup.py tests/unit/test_first_run_setup.py
git commit -m "BACKLOG #189: package the Cinnamon tray applet

.deb: two new install lines, mirroring the existing GNOME extension
pattern exactly. snapcraft.yaml/org.orcshot.Orcshot.yaml: a new sibling
part/module stages the applet into the sandboxed build the same way
bundled-extensions already does for the GNOME extensions. Snap/Flatpak:
the sandboxed-channel install loop now also installs the Cinnamon
applet at runtime, for a Mint user who installs via Snap/Flatpak
instead of the PPA."
```

---

## Task 5: BACKLOG.md write-up

**Files:**
- Modify: `BACKLOG.md` (`#189` entry)

**Interfaces:** none - documentation only.

- [ ] **Step 1: Read the current `#189` entry in full**

```bash
grep -n "^## #189" -A 40 BACKLOG.md
```

- [ ] **Step 2: Layer a resolution note on top (don't delete the original diagnostic text)**

Following this project's own established convention (see how `#193`/`#194`/`#179` were each
closed out), append a resolution section. Only mark this RESOLVED once Tasks 1-4 have actually
been live-verified per their own steps above - the note must accurately reflect what was really
watched happen, not what was merely built:

```markdown
**RESOLVED 2026-09-05.** `Gtk.StatusIcon` (deprecated, XEmbed-based) is gone entirely. Real
finding that reframed this ticket: GNOME Shell hasn't hosted XEmbed tray icons since 3.26,
regardless of session type - GNOME-X11 users very likely got an invisible tray icon before this
fix, not a deprecated-but-working one. Both real supported desktops now get a native,
non-deprecated tray via the same D-Bus export (`Gio.Menu`/`org.gtk.Actions`) this project already
built for #184's Wayland redesign:

- **GNOME** (Ubuntu 24.04/26.04, X11 and Wayland both) - the existing `orcshot-tray@orcshot.org`
  Shell extension, now reachable on X11 too, with real left-click-to-capture added (previously
  Wayland's tray was menu-only, unlike X11's old `Gtk.StatusIcon`). Live-verified on the real
  26.04 VM, both session types.
- **Cinnamon** (Mint) - a brand-new native Cinnamon Spices applet, consuming the exact same D-Bus
  export. Live-verified on X11 (Cinnamon's only real session type today).
- **Cinnamon-on-Wayland**: shipped session-agnostic (no X11/Wayland branching in the applet code)
  since Cinnamon 6.8/Mint 23's Wayland support is architecturally expected to work the same way -
  but **not verified**, since Mint 23 hasn't shipped yet. Revisit once it has.

XFCE/KDE/MATE remain explicitly out of scope, matching this project's existing precedent
elsewhere (hotkeys, window-picker automation).

Full design: `docs/superpowers/specs/2026-09-05-tray-modernization-design.md`. Full plan:
`docs/superpowers/plans/2026-09-05-tray-modernization.md`.
```

- [ ] **Step 3: Commit**

```bash
git add BACKLOG.md
git commit -m "BACKLOG #189: mark resolved, real tray-modernization write-up"
```
