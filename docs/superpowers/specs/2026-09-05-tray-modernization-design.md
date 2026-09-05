# Tray Modernization (BACKLOG #189) - Design

**Status:** Approved in chat (sectioned walkthrough), written up per direflail's "write it up."
Supersedes any earlier framing of #189 as "harmless deprecated API, maybe just document it."

## Problem

BACKLOG #189 started as: "`app.py`'s X11 tray icon uses `Gtk.StatusIcon`, deprecated since GTK
3.14 with no GTK4 replacement - is this a real problem or a harmless one?" Investigation (this
session, 2026-09-05) found it's neither as originally framed - the real picture is bigger and
different:

1. **`Gtk.StatusIcon` relies on the legacy XEmbed tray protocol.** `REQUIREMENTS.md:1613-1614`
   (written during original tray implementation) already noted "Cinnamon still supports the
   legacy XEmbed tray protocol... unlike pure GNOME Shell." GNOME Shell has not hosted XEmbed
   icons since GNOME 3.26 (2017), **regardless of X11 or Wayland session**. Every tray-mechanism
   branch in this codebase (`capture/backend_select.py`) gates on `XDG_SESSION_TYPE`, never on
   desktop - so `app.py:_build_tray_icon`'s current `else` branch hands GNOME-on-X11 users a
   `Gtk.StatusIcon` that very likely renders invisibly. This is a real, separate, pre-existing bug
   this design incidentally fixes, not something migration introduces.
2. **The generic AppIndicator/StatusNotifierItem protocol has a real, permanent limitation**: no
   distinct left-click ("activate") action once a menu is attached
   ([bug #1910521](https://bugs.launchpad.net/bugs/1910521)). This is why #184 (Wayland tray
   redesign) didn't just point X11 at a standard AppIndicator library.
3. **That limitation only applies to a *generic* third-party SNI host** (`ubuntu-appindicators`,
   a standard KDE/XFCE systray, etc.) implementing the spec as written. It does **not** apply to
   a shell/DE extension this project writes and owns - `orcshot-tray@orcshot.org` (the GNOME
   Shell extension #184 built) isn't going through the SNI protocol at all; it's a custom
   `PanelMenu.Button` consuming Orcshot's own `Gio.Menu`/`org.gtk.Actions` D-Bus export, so it can
   implement whatever click behavior we want. **It currently doesn't** - `button-press-event` is
   wired for diagnostic logging only, so Wayland's tray today is menu-only, no left-click
   shortcut, unlike X11's current `Gtk.StatusIcon` (`"activate"` -> instant capture, `"popup-menu"`
   -> menu).
4. **Cinnamon has its own, independent equivalent**: the Cinnamon Spices applet system (JS-based,
   forked long ago from early GNOME Shell, structurally similar but a separate, incompatible
   codebase - `REQUIREMENTS.md:2898-2917`). A Cinnamon applet can consume the exact same D-Bus
   export the GNOME extension does (`Gio.DBusMenuModel`/`Gio.DBusActionGroup` are plain
   GLib/Gio APIs, not GNOME-Shell-specific) and implement the same left-click/right-click split.

## Scope (binding for this design)

This project's real, documented support matrix (`README.md:41-42`, `hotkey_setup.py`'s own
scope docstring): **Linux Mint (Cinnamon) and Ubuntu 24.04/26.04 LTS (GNOME)**. Nothing else has
ever been targeted for desktop-specific automation in this codebase, and this design does not
change that:

- **Mint/Cinnamon** - X11 today. Cinnamon's own Wayland session isn't released yet (see below).
- **Ubuntu 24.04** - GNOME Shell 46, X11 and Wayland sessions both real and used.
- **Ubuntu 26.04** - GNOME Shell 50.1, X11 and Wayland sessions both real and used.
- **XFCE, KDE, MATE: explicitly out of scope**, matching this project's existing, repeated
  precedent (`hotkey_setup.py`: "deliberately out of scope, not an oversight";
  `REQUIREMENTS.md:2762`: "Still X11/Cinnamon-and-GNOME only, not XFCE/KDE/MATE"). Building
  native XFCE panel plugins (C), KDE Plasmoids (QML), or MATE applets (C) would be a real,
  separate scope-expansion decision, not something to fold into this fix.

**Cinnamon-on-Wayland real status** (WebSearch, 2026-09-05, sourced): Cinnamon 6.8 (shipping in
Linux Mint 23, targeted Christmas 2026, currently in Alpha) has Wayland support that "graduated
from experimental to fully supported" per a June 2026 update, explicitly including fixes for
applet popup/context menu positioning under Wayland
([itsfoss.com](https://itsfoss.com/news/linux-mint-wayland-stable/),
[linuxiac.com](https://linuxiac.com/linux-mints-next-release-will-fully-support-wayland-in-cinnamon/)).
Structurally, a Cinnamon Spices applet is a Cinnamon-Shell-level abstraction the same way a GNOME
Shell extension is GNOME-Shell-level - it should not need separate X11/Wayland code, mirroring
the GNOME extension's own session-agnostic design. **But Mint 23 has not shipped and this project
has no VM running it** - the applet is built session-agnostic (costs nothing extra) but Cinnamon-
on-Wayland is explicitly *not verified* until a real Mint 23 exists to test on. BACKLOG must
record this distinction, not claim verified Wayland-Cinnamon support.

## Design

### 1. Detection: desktop-type, not session-type

Today `app.py:_build_tray_icon` branches on `XDG_SESSION_TYPE == "wayland"`. Replace with a check
on `XDG_CURRENT_DESKTOP`:

- Contains `GNOME` -> use the GNOME Shell extension path (regardless of X11/Wayland).
- Contains `X-Cinnamon` (Cinnamon's real `XDG_CURRENT_DESKTOP` value) -> use the new Cinnamon
  applet path (regardless of X11/Wayland, so it's ready the day Mint 23 ships).

`Gtk.StatusIcon` and the X11-only `Gtk.Menu`-building code in `app.py` (`_build_tray_menu`'s
local-widget variant, the `"activate"`/`"popup-menu"` signal wiring) are deleted entirely -
nothing in the real support matrix needs them once both remaining desktops go through their own
native extension/applet.

Real values already established and reused as-is (no renaming): `BUS_NAME = "org.orcshot.Orcshot"`
(`app.py:67`, `APPLICATION_ID`), `MENU_PATH = "/org/orcshot/Orcshot/TrayMenu"`
(`gnome_tray_export.py:TRAY_MENU_PATH`), `ACTIONS_PATH = "/org/orcshot/Orcshot"`, default
left-click action name `"tray-region"` (`app.py:608`, `f"tray-{mode}"` where `mode="region"` -
matches `start_capture()`'s existing behavior, `app.py:383-388`, "Windows tray default").

### 2. GNOME extension: add real left-click

In `resources/gnome-shell-extensions/orcshot-tray@orcshot.org/extension.js`, the existing (today
diagnostic-only) `button-press-event` handler on `OrcshotTrayButton` gets real logic:

```js
this.connect('button-press-event', (actor, event) => {
    if (event.get_button() === Clutter.BUTTON_PRIMARY) {
        this._actionGroup.activate_action('tray-region', null);
        return Clutter.EVENT_STOP;
    }
    return Clutter.EVENT_PROPAGATE;
});
```

Non-primary clicks fall through to `PanelMenu.Button`'s own default (toggle `this.menu`),
matching X11's current `"popup-menu"` -> show-menu behavior exactly. The temporary diagnostic
`log()` calls (added for Task 7's live debugging, per the file's own comment) are removed as part
of this change - the bug they were added to chase is unrelated and already resolved.

### 3. New Cinnamon applet - same server, same contract, new consumer

New directory `resources/cinnamon-applets/orcshot-tray@orcshot.org/` (`applet.js` +
`metadata.json`), consuming the *exact same* D-Bus export the GNOME extension reads - nothing
server-side (`gnome_tray_export.py`, `_register_tray_actions`) changes for this at all.

`metadata.json` (real Cinnamon schema, confirmed via `linuxmint/Cinnamon`'s own wiki and shipped
applets, e.g. `user@cinnamon.org`):

```json
{
  "uuid": "orcshot-tray@orcshot.org",
  "name": "Orcshot Tray",
  "description": "Renders Orcshot's tray icon and menu from the app's own exported Gio.Menu - the Cinnamon counterpart to orcshot-tray@orcshot.org's GNOME Shell extension.",
  "cinnamon-version": ["5.0", "5.2", "5.4", "5.6", "5.8", "6.0", "6.2", "6.4", "6.6", "6.8"],
  "max-instances": "1"
}
```

`applet.js` extends `Applet.IconApplet` (icon-only, matching the GNOME extension's icon-only
`St.Icon` and `Gtk.StatusIcon`'s own look), builds an `Applet.AppletPopupMenu` +
`PopupMenu.PopupMenuManager` populated from the same `Gio.DBusMenuModel` the GNOME extension
reads, and implements the click split:

- `on_applet_clicked(event)` - Cinnamon's own applet base class calls this automatically for a
  primary (left) click; wire it to `this._actionGroup.activate_action('tray-region', null)`
  directly, same as the GNOME side.
- Right-click - Cinnamon's `Applet.Applet` base class already reserves right-click for its own
  built-in context menu ("Remove '<name>' from panel", "Configure..."). **Exact mechanism to
  confirm against real `Applet.js` source at implementation time** (not guessed here): either
  override the base class's right-click dispatch to show our own `AppletPopupMenu` instead, or
  add our menu's items alongside Cinnamon's built-in ones - whichever the real source shows is the
  intended extension point. This is the one real open implementation detail in this design;
  everything else is confirmed against real shipped code or documentation.

### 4. Packaging

**`.deb` (Mint's real channel, also Ubuntu's PPA)**: two new lines in `debian/orcshot.install`,
mirroring the existing GNOME extension lines exactly:

```
src/orcshot/resources/cinnamon-applets/orcshot-tray@orcshot.org/applet.js usr/share/cinnamon/applets/orcshot-tray@orcshot.org/
src/orcshot/resources/cinnamon-applets/orcshot-tray@orcshot.org/metadata.json usr/share/cinnamon/applets/orcshot-tray@orcshot.org/
```

Cinnamon scans `/usr/share/cinnamon/applets/<uuid>/` system-wide the same way GNOME Shell scans
`/usr/share/gnome-shell/extensions/<uuid>/` - same distribution pattern already proven for the
three existing GNOME extensions under `.deb`.

**Snap/Flatpak**: extend the existing sandboxed-channel loop
(`ui/first_run_setup.py:_install_bundled_extensions_for_sandboxed_channel`) to also install the
Cinnamon applet UUID, in case a Mint user installs via Snap/Flatpak instead of the PPA -
`channel_detect.install_bundled_extension_if_needed()` is already generic (`uuid`, `bundled_dir`,
`dest_parent`), needs no changes; just add `orcshot-tray-cinnamon` (real uuid:
`orcshot-tray@orcshot.org`, same as `.deb` - one uuid, one applet, installed to
`~/.local/share/cinnamon/applets/` instead of the GNOME extensions path) to the loop's uuid list
with the right `dest_parent`.

### 5. Verification plan

- **GNOME X11**: live-tested on the real 26.04/24.04 VMs, switched to "Ubuntu on Xorg" at the
  GDM login screen (VM registry memory has SSH/GUI access details for both).
- **GNOME Wayland**: already the primary-tested path from #184; re-confirm left-click after this
  change.
- **Cinnamon X11**: live-tested on the real Mint dev host (this project's original/primary dev
  target).
- **Cinnamon Wayland**: **not verified this round** - Mint 23 isn't released. BACKLOG records the
  applet as shipped session-agnostic, Wayland behavior unconfirmed, to be tested once Mint 23 is
  real.

## Out of scope / explicitly deferred

- XFCE, KDE, MATE native tray support - real, separate scope-expansion decision if ever wanted,
  not part of this fix.
- Any GTK3->GTK4 migration - unrelated, project-wide decision (`REQUIREMENTS.md:23`), not
  triggered by this design.
