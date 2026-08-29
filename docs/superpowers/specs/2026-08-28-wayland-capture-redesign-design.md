# Wayland Capture Redesign: Dropping the Shell-Extension Dependency

## Goal

Make Orcshot's Wayland experience work without depending on the bundled `orcshot-clipboard@orcshot.org`
GNOME Shell extension, so Orcshot can ship on Snap and Flatpak in addition to the existing `.deb`/PPA -
while working identically from the end user's perspective on every distribution channel (Snap, Flatpak,
`.deb`/apt, and whatever each platform's own software-center app shows). No feature regression, no
per-channel behavioral drift.

## Why

GNOME Software's browsable catalog doesn't surface plain apt/PPA packages on Ubuntu at all (confirmed live,
both 24.04 and 26.04) - Snap or Flatpak are the only paths to that kind of discoverability. Orcshot's
current Wayland architecture blocks that: its bundled Shell extension calls directly into `org.gnome.Shell`
(`BUS_NAME = "org.gnome.Shell"`, confirmed in `gnome_clipboard.py`), and a real, direct precedent (a
strict-confinement Snap attempting the same class of call, denied by AppArmor, no interface to fix it - a
Snap maintainer's own words: "the trust model of snaps (untrusted and hence confined) is not compatible
with gnome-shell extensions...") shows that pattern doesn't survive Snap confinement. This redesign removes
that dependency where it can be removed cleanly, and is explicit about the one place it can't.

## Non-negotiable constraints

- **Must work across apt, Snap, Flatpak, and each platform's own software-center app** - stated explicitly,
  more than once, by direflail. Not a nice-to-have to trade away for convenience.
- **Must work exactly as it does today from the end user's perspective** - same features, same
  interaction model. Backend implementation is free to change as long as the visible result doesn't.
- **Orcshot must never hand any piece of its own UX to another screenshot app's own interface** - a
  standing principle (see `[[feedback-no-delegating-to-other-screenshot-apps]]`), not just local to this
  task. Ruled out the XDG portal's native `target=Window` picker on exactly this basis, even after
  confirming it technically works.
- **Prefer solid, proven technology over what's merely familiar.** The existing stack turned out to
  include a component its own upstream has declared obsolete - stated preference now is to check current
  ecosystem state rather than default to what Orcshot already uses.

## Architecture: four independent pieces, evaluated separately

Orcshot's Wayland experience isn't one thing depending on the Shell extension - it's four loosely-coupled
capabilities with different levels of dependency on it.

### 1. Region-select capture and its interactive UI

**Status: already solved, already shipped, no change needed.**

`WaylandCaptureBackend` (portal-based pixel grab, `org.freedesktop.portal.Screenshot` with `target=Screen`)
plus `region_select_wayland.py` (Orcshot's own client-side overlay - frozen backdrop, drag-to-select, and
the loupe/magnifier, real and wired up: `draw_magnifier`, `_show_magnifier`) is *already* the automatic
fallback whenever the Shell extension isn't available, and has been confirmed live against the real portal
backend already. Zero `org.gnome.Shell` dependency. This capability doesn't need touching.

### 2. Clipboard

**Status: already solved, already shipped, no change needed.**

`WaylandClipboardBackend` (invisible-window/focus-wait technique) is the existing non-extension fallback,
with one documented, accepted side effect (a window-list reflow). No `org.gnome.Shell` dependency.

### 3. Window Picker

**Status: unchanged, deliberately.**

Stays on the third-party `window-calls@domandoman.xyz` extension (a separate, vendored, non-Orcshot-owned
extension providing window enumeration - Wayland has no portable equivalent at all, confirmed: this isn't
a GNOME-Shell-specific gap, it's a Wayland protocol-design limitation).

The obvious alternative - the XDG portal's `Screenshot` interface's own `target=Window` option - was tested
live and genuinely works (see "Research notes" below), but was rejected on principle, not a technical
failing: it hands the entire window-picking interaction to GNOME's own native Screenshot app, GNOME-branded
chrome, not Orcshot's, with no way to get raw window data back for Orcshot to render its own picker on top
of it. direflail: *"i do not want to use another screenshot app. that's why we developed orcshot."* This
is the one piece that keeps a real `org.gnome.Shell`-adjacent dependency (via `window-calls`) and whatever
Snap-confinement risk comes with it; that risk is accepted, scoped to this one capability, not eliminated.

### 4. Tray icon and menu

**Status: redesigned.** This is the actual substance of this spec.

**What's being replaced and why.** Orcshot's current Wayland fallback for the tray (`AyatanaAppIndicator3`,
i.e. `libayatana-appindicator`) is built on a library its own upstream has declared obsolete: its GitHub
description reads *"Gtk-based, DBusMenu-based, **OBSOLETE**, please use libayatana-appindicator-glib for
new implementations."* Its concrete symptom in Orcshot today: menu-item icons render right-aligned on
Wayland, a bug confirmed to live entirely in a *different* project's code
(`ubuntu-appindicators@ubuntu.com`'s `dbusMenu.js`, which hard-codes `xAlign: Clutter.ActorAlign.END` with
no DBusMenu property a client can override - confirmed by pulling and reading the actual installed source,
not assumed) that Orcshot has no ability to fix from its own side under the old architecture.

**The new design:**

- Orcshot publishes its tray menu as a `Gio.Menu` + `Gio.SimpleActionGroup`, exported over D-Bus via
  `Gio.DBusConnection.export_menu_model()`/`export_action_group()` - core, official PyGObject/Gio APIs
  (confirmed against `api.pygobject.gnome.org`'s own class docs), already the same `Gio` module used
  throughout Orcshot's codebase today. **No new external dependency** - `libayatana-appindicator-glib`
  itself isn't needed as a library; Orcshot can talk the modern protocol directly with what it already
  uses.
- A new, small, **Orcshot-specific** (not general-purpose) GNOME Shell extension consumes that export and
  builds a real `PanelMenu.Button` with a `PopupMenu` driven by the exported menu/actions - the same
  general shape Orcshot's *current* Shell-native tray button already uses (`orcshot-clipboard@orcshot.org`
  already builds its own `PanelMenu.Button`), just fed from Orcshot's own GMenu export instead of a custom
  `org.gnome.Shell`-hosted interface.
- The extension finds Orcshot via `Gio.bus_watch_name` on Orcshot's own well-known bus name, not by trying
  to become the system's `org.kde.StatusNotifierWatcher` (the SNI/tray-icon registration mechanism). This
  is a deliberate scope decision, not a shortcut: implementing SNI registration would mean either competing
  for `StatusNotifierWatcher` ownership (the exact problem that makes `status-tray`, a similarly-scoped
  real project, silently inert against the pre-installed `ubuntu-appindicators` on real Ubuntu/Mint - it
  uses `Gio.BusNameOwnerFlags.NONE` and simply never wins the race, confirmed by reading its actual
  source), or solving the SNI `Menu` property's protocol ambiguity for arbitrary apps (it's just an
  untyped object path - `<property name="Menu" type="o"/>`, confirmed from the real `notification-item.xml`
  - "dbusmenu lives there" has only ever been convention). Scoping the extension to Orcshot specifically
  sidesteps both: it already knows exactly what to expect, no negotiation needed, and it draws its own
  panel button directly instead of registering as a generic SNI item at all.
- This also finally fixes the icon-alignment bug for real, since Orcshot's own extension controls the
  entire rendering path end to end - no third-party `dbusMenu.js` to work around.

**Why this survives Snap confinement, specifically:** the call direction is what matters, not whether a
Shell extension is involved at all. `org.kde.StatusNotifierWatcher` - itself implemented by a Shell
extension - is explicitly on Snap's sanctioned `desktop`-interface allowlist (confirmed against `snapd`'s
own AppArmor policy source, `interfaces/builtin/desktop.go`), concrete proof that "a Shell extension is
involved" was never the disqualifying factor. What's blocked is Orcshot's own confined process calling
*into* `org.gnome.Shell`. This design never does that: Orcshot only ever *exports* on its own D-Bus
connection (a fundamentally different, much less restricted direction than calling into someone else's
named service), and the new Shell extension - itself never Snap-confined, since it runs inside
`gnome-shell`'s own separate, unconfined process, loaded from the ordinary per-user extensions path
(`~/.local/share/gnome-shell/extensions/`, reachable via the `home`/`--filesystem=home` grants both Snap
and Flatpak commonly hand out) - is the one reaching out to read what Orcshot published.

**Unrelated, permanent limitation worth remembering regardless of this redesign:** AppIndicator-family
icons have no distinct left-click ("activate") action once a menu is attached - a real, documented, upstream
protocol limitation (see https://bugs.launchpad.net/bugs/1910521), not something this redesign changes
either way. X11 keeps its own separate `Gtk.StatusIcon` with a real left-click-for-instant-capture shortcut
specifically because of this; that reasoning is unaffected by anything here.

## Live verification performed

Everything above with a "confirmed" attached to it was checked directly, not assumed - real source pulled
off a running VM, real portal calls made and screenshotted, or a real minimal prototype built and run.
Specifically for the tray-icon redesign, a two-stage prototype was built and run on a real Ubuntu 26.04
Wayland VM:

1. **Data flow**: a plain Python script exporting `Gio.Menu` + `Gio.SimpleActionGroup` over D-Bus, and a
   bare `gjs` script (same methodology this project already used to verify the tray-menu gettext bug in
   task #183) consuming it via `Gio.DBusMenuModel`/`Gio.DBusActionGroup`. Real data round-tripped
   correctly - labels, action names, and the icon attribute all arrived intact. Actions become available
   via `action-added` signals with correct bare names after normal async proxy-sync latency (not a defect
   - the reason a real consumer reacts to signals rather than polling).
2. **Real Shell-extension rendering**: a minimal real GNOME Shell extension (`orcshot-tray-test@test.local`)
   installed to the per-user extensions path, enabled, and loaded via a genuine VM reboot (extensions
   don't reload without a full session restart - see `[[feedback-extension-reload-caching]]`). It watches
   for the exporter's bus name via `Gio.bus_watch_name`, builds a real `PanelMenu.Button` +
   `PopupMenu.PopupMenuItem`s from the exported menu, and wires actions to `activate_action()` calls. Ran
   with **zero errors anywhere in the full chain** - constructor, menu-model/action-group creation, menu
   build, `Main.panel.addToStatusArea()` all completed successfully, confirmed via step-by-step logging.
   Direct diagnostic confirmed the button is real and live: `visible=true width=60 height=16 mapped=true
   opacity=255`, with a real icon child similarly `visible=true`. The icon's exact on-screen pixel
   rendering has an unresolved sizing/CSS detail (icon renders at an unexpected 36×16 rather than a normal
   square size, and setting `icon_size` explicitly didn't yet change that) - a genuine, open, but ordinary
   front-end bug, not a sign anything about the approach is unsound. Flagged as a first task for whoever
   picks up implementation, not a blocker to this design.

## What implementation actually needs to resolve, in order

1. **Fix the icon-rendering CSS/sizing detail** from the prototype above - the one loose end from tonight's
   verification. Small, bounded, front-end debugging, not architectural.
2. **Build the real extension** (not the throwaway test one) as `orcshot-tray@orcshot.org` or similar,
   replacing `orcshot-clipboard@orcshot.org`'s tray-button responsibility specifically (region-select and
   clipboard don't need it, per sections 1-2 above; Window Picker's `window-calls` dependency is separate
   and unaffected).
3. **Rewrite `app.py`'s `_build_tray_icon`/`_build_tray_menu`** to export via `Gio.Menu`/
   `Gio.SimpleActionGroup` on Wayland instead of building an `AyatanaAppIndicator3.Indicator` with a
   `Gtk.Menu`. X11 is unaffected - it keeps `Gtk.StatusIcon` exactly as today (see the left-click-action
   note above for why that's deliberate, not an oversight).
4. **Menu translation**: confirm the new Python-side GMenu construction uses the same gettext catalog the
   rest of the app already loads (this was never actually broken for AppIndicator3's own menu - `X11`'s
   `Gtk.StatusIcon` and the AppIndicator3 fallback already share one `_build_tray_menu` function, proven
   correctly translated by X11 already shipping - the gettext-caching bug fixed earlier this project
   session was specific to the *old* Shell-extension's separate GJS-side `.mo`-parsing, a different
   codebase this redesign removes entirely).
5. **Package the new extension** for all three current targets (Mint, Ubuntu 24.04, Ubuntu 26.04) via the
   existing `.deb`, and separately verify it installs correctly to the per-user path when Orcshot itself
   ships as a Snap or Flatpak (not yet tested - the prototype installed it directly, not through either
   packaging format's own install mechanism).
6. **Real end-to-end test on an actual Snap build** - everything above establishes that nothing in this
   design *should* be blocked by Snap confinement, backed by real policy-source evidence, but a real Snap
   package built and run under genuine strict confinement hasn't been done yet. This is the actual proof
   this design has been aiming at; RELEASING.md's own standard (verify live, not assumed) applies here too.

## Explicitly out of scope for this spec

- **RPM/Fedora and other non-Debian-family distros** - tracked separately (BACKLOG.md #132), explicitly
  lower priority, "maybe at some point."
- **A Wayland-only Flatpak build** - tracked separately (BACKLOG.md #185), a narrower, additive
  distribution-channel decision independent of this redesign; this redesign is what would make that build
  (or a Snap) viable in the first place, but doesn't itself decide whether to build it.
- **Whether Flatpak's `fallback-x11` socket could give the existing dual-mode `.deb` genuine direct X11
  capture inside a Flatpak sandbox** - tracked separately (BACKLOG.md #187), sequenced after this work.
