# XApp status icon on Cinnamon — design

**Date:** 2026-09-12 · **Backlog:** #208 · **Supersedes:** the Cinnamon-applet half of the
2026-08-28 Wayland tray redesign, and the Spices half of the 2026-09-11 extension-delivery spec.

## Why

The 2026-08-28 tray redesign gave Cinnamon a native *applet*. Every Cinnamon applet carries
Cinnamon's own **About…** and **Remove '<name>'** entries in its right-click menu; Mint's review
rules treat them as mandatory. Nobody put the applet on a real Cinnamon panel until the Spices
screenshot on 2026-09-11, when direflail saw those entries on their own desktop for the first time
and does not want them. Their other tray icons don't have them because those are *status icons*,
owned by the app and displayed by Cinnamon's stock `xapp-status` applet.

So the Cinnamon tray becomes an `XApp.StatusIcon` owned by the app. That also removes the entire
Cinnamon Spices submission (nothing to install), and the two latent applet bugs found the same
night (#196's greyed items, and captures started from the menu containing the menu).

## What was verified before this was written

All on direflail's Mint host (Cinnamon, X11), against the running 0.3.0 `.deb` Orcshot, with a
standalone prototype that talks to the app over D-Bus exactly as the shipped code will
(session scratchpad `xapp_proto3.py`):

- `XApp.StatusIcon` appears among the other status icons; right-click shows the app's exported
  menu built with `Gtk.Menu.new_from_model` — **with the per-item icons**, and with no About /
  Remove. direflail: "what is running on right now looks acceptable."
- Left-click starts a region capture (direflail chose this over "open the menu").
- The icon "blinking out" during a region capture is the region-select overlay dimming the whole
  screen, panel included (measured: the panel's far end dims by the same amount at the same
  instant). Pre-existing, by design, not this feature's.
- **Menu-in-capture, reproduced then fixed.** With a plain `Gtk.Menu.new_from_model`, choosing
  *Capture Full Screen → Save* produced a file with the menu in it. With a proxy action group
  that pops the menu down and forwards the real action 150 ms later, the same test produced a
  file without it. direflail verified the fixed prototype by hand.
- Research (BACKLOG #208 has the sources): `gir1.2-xapp-1.0` is in Ubuntu noble (2.8.2) and
  resolute (3.2.2), Mint has 3.2.3; Warpinator on Flathub builds libxapp as a module
  (`linuxmint/xapp` tag 3.2.2, `-Dapp-lib-only=true`) and declares
  `--own-name=org.x.StatusIcon.warpinator` + `--talk-name=org.x.StatusIconMonitor.*`; libxapp
  names the icon `org.x.StatusIcon.<prgname>` unless `name` is a valid 4-part
  `org.x.StatusIcon.*` name — so `org.x.StatusIcon.orcshot`.

## Design

### When

The desktop is Cinnamon: `hotkey_setup.cinnamon_keybindings_available()`, the same check
first-run already uses, on any channel. GNOME keeps the Shell extension tray; the two never
coexist (a session is one desktop). Snap is untouched (Cinnamon-on-Snap is out of scope).

### `ui/xapp_tray.py`

One module, no class hierarchy:

```python
def build_menu(model: Gio.MenuModel, forward: Callable[[str], None], delay_ms: int = 150) -> Gtk.Menu
```

Builds `Gtk.Menu.new_from_model(model)` and inserts, under the `app` prefix, a
`Gio.SimpleActionGroup` of stateless actions named after every `app.*` action the model
references. Each proxy action pops the menu down and schedules `forward(name)` after `delay_ms`
via `GLib.timeout_add`. Nothing else: no state, no enabled-tracking (the app's actions are always
enabled; the greyed-items bug was the applet's cross-process latency, which does not exist
in-process).

```python
def create_status_icon(app) -> XApp.StatusIcon | None
```

Imports `XApp` inside a `try` (`gi.require_version("XApp", "1.0")`); on `ImportError`/`ValueError`
prints one `[orcshot]` line and returns `None`. Otherwise: `XApp.StatusIcon.new()`,
`set_icon_name("orcshot")`, `set_tooltip_text("Orcshot")`,
`set_secondary_menu(build_menu(app._tray_menu, lambda n: app.activate_action(n, None)))`,
and `activate` → button 1 → `app.activate_action("tray-region", None)`. The icon is stored on the
app (`app._xapp_icon`) so it lives as long as the process; quitting the process removes it, and
the existing `_quit_and_hide_tray_button` needs no change.

### `app.py`

In `do_startup`, immediately after `_export_tray_menu()`:

```python
if cinnamon_keybindings_available():
    self._xapp_icon = create_status_icon(self)
```

`_export_tray_menu` already keeps `self._tray_menu` alive; the XApp menu is a second consumer of
the same model, so labels, order and icons cannot drift between desktops.

### Packaging

- `.deb`: `Depends:` gains `gir1.2-xapp-1.0`. `debian/orcshot.install` loses its two
  `cinnamon-applets` lines; the package upgrade removes the applet files from
  `/usr/share/cinnamon/applets/`.
- Flatpak (`org.orcshot.Orcshot.yaml`): a `xapps` module, Warpinator's verbatim with the
  Python path for our runtime (`-Dpy-overrides-dir=/app/lib/python3.13/site-packages/gi/overrides`;
  the GNOME 50 runtime's Python is 3.13, checked), placed before the `orcshot` module; and two
  finish-args, `--own-name=org.x.StatusIcon.orcshot` and `--talk-name=org.x.StatusIconMonitor.*`,
  with a comment citing Warpinator. `flatpak-builder-lint manifest` must stay clean.
- Snap: untouched.

### Deleted

`src/orcshot/resources/cinnamon-applets/` (the applet, its `metadata.json`, and the two fixes
made to it on 2026-09-11 — they were fixes to something now retired), the two `orcshot.install`
lines, and every docstring/comment that names the applet as a live component
(`gnome_extension_setup.py`, `hotkey_setup.py`, `gnome_tray_export.py`, `app.py`,
`ui/extension_install.py`). `debian/copyright` if it lists the applet path.

### Not in scope

Autostart on Snap/Flatpak (#207). Anything on GNOME. The overlay dimming the panel during region
select. Cinnamon on Wayland is covered by the same code (xapp-status is D-Bus) but is verified
only if a Cinnamon-Wayland session is at hand; noted, not gated on.

## Testing

**Unit (pytest, headless):**
- `build_menu`: given a `Gio.Menu` with two `app.x` items and a recording `forward`, activating a
  proxy action does not call `forward` synchronously and does call it with the bare name after
  the delay (drive the main loop for `delay_ms + 50`).
- `build_menu`: the proxy group contains exactly the action names the model references.
- `create_status_icon` with `XApp` unavailable (monkeypatch `gi.require_version` to raise) returns
  `None` and does not raise.

**Live, on the Mint host, from the dev checkout** (`.venv/bin/python -m orcshot.app` after
quitting the running `.deb` instance):
1. Icon appears among the status icons; tooltip "Orcshot".
2. Right-click: the menu with icons, no About/Remove.
3. Left-click: region overlay; Escape cancels.
4. *Capture Full Screen → Save* from the menu: the saved PNG, cropped at the menu's screen
   position, shows desktop content, not the menu (the 2026-09-12 test, re-run).
5. Quit from the menu: icon gone, no process left.

**Flatpak, on the Mint host** (Mint ships Flatpak): install the CI bundle with
`flatpak install --user`, repeat 1–5. This is also the proof that the `xapps` module builds.

**CI:** `flatpak.yml` builds the module (build failure = red); `apt.yml` unchanged.

## Verification items (facts to confirm while building, not decisions)

1. That `Gtk.Menu.new_from_model` in the *app* process needs the proxy at all — it does no harm
   either way, and the test in step 4 is the arbiter; keep the proxy regardless (it also made the
   cross-process prototype correct, and costs nothing).
2. The exact `-Dpy-overrides-dir` the runtime expects, by inspecting `/app/lib/python3.13` in the
   built Flatpak.
