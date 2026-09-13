# Snap launcher icon — design

**Date:** 2026-09-12 · **Backlog:** #217 (in front of the Snap Store half of #198) · **Follows:**
#215 (`2026-09-12-snap-save-home-plug-design.md` §5), which gave the snap its desktop file.

## Why

Since #215 the snap registers `/var/lib/snapd/desktop/applications/orcshot_orcshot.desktop`
with the source file's `Icon=org.orcshot.Orcshot` carried over verbatim. That is an icon-theme
*name*; nothing on a snap-only machine exports an icon by that name, so the app grid, dock and
switcher show GNOME's generic placeholder. The 26.04 VM showed the real icon only because the
Flatpak is installed beside the snap and exports
`~/.local/share/flatpak/exports/share/icons/hicolor/scalable/apps/org.orcshot.Orcshot.svg`
(VERIFICATION.md Scenario 4, re-run A2 — the first look said PASS for the wrong reason).

## What was verified before this was written

snapd `wrappers/desktop.go`, `rewriteIconLine` (main, fetched 2026-09-12):

- an `Icon=` value containing a path separator must start with `${SNAP}/` and be canonical;
  the line is kept and `${SNAP}` is substituted with `<mount dir>/../current`, i.e.
  `/snap/orcshot/current/…` — a path every host session can read;
- an `Icon=snap.orcshot.<x>` value is rewritten to the instance name and resolved through the
  icons snapd exports from `meta/gui/icons/` (`wrappers/icons.go`, glob `snap.<name>.*`);
- any other value is "allowed through unchanged" — our case; nothing exports it.

The PNG is already inside the snap at
`$SNAP/usr/share/icons/hicolor/128x128/apps/org.orcshot.Orcshot.png` (#215's `override-build`).
The Flatpak and the .deb are unaffected: each ships and names its own icon (Flatpak exports
`org.orcshot.Orcshot.svg`; the .deb installs `orcshot.png` with `Icon=orcshot`).

## Design

One line in `snapcraft.yaml`'s `orcshot` part `override-build`, after the two `install` lines:

```yaml
      # BACKLOG #217: snapd keeps a theme-name Icon= verbatim and exports
      # nothing for it, so a snap-only machine shows the placeholder. A
      # ${SNAP} path is the one form snapd rewrites to a host-readable
      # /snap/orcshot/current/... path (wrappers/desktop.go rewriteIconLine).
      # Edited on the installed copy only: the source file's theme name is
      # right for the Flatpak and the .deb.
      sed -i 's|^Icon=.*|Icon=${SNAP}/usr/share/icons/hicolor/128x128/apps/org.orcshot.Orcshot.png|' "$CRAFT_PART_INSTALL/usr/share/applications/org.orcshot.Orcshot.desktop"
```

Nothing else changes: same PNG, same path, same desktop file, no new plug or key. The source
`org.orcshot.Orcshot.desktop` is untouched.

Not chosen: exporting a theme icon via `meta/gui/icons/…/snap.orcshot.org.orcshot.Orcshot.png`
+ `Icon=snap.orcshot.org.orcshot.Orcshot`. Its only advantage over a `${SNAP}` path is
HiDPI-aware theme lookup, which needs a scalable asset the snap does not ship; it costs a second
copy of the PNG and a snapd naming convention. If an SVG is ever added to the snap, revisit.

## Testing

- CI (`snap.yml` verify job, after `snap install --dangerous`): one added assertion that the
  registered desktop file's `Icon=` is a `/snap/orcshot/current/…` path that exists:
  `grep '^Icon=/snap/orcshot/current/' /var/lib/snapd/desktop/applications/orcshot_orcshot.desktop`
  and `test -f "$(sed -n 's/^Icon=//p' /var/lib/snapd/desktop/applications/orcshot_orcshot.desktop)"`.
  This is the whole mechanism, provable headless; it fails if snapd ever rejects the line.
- No Python changes, no unit tests.

## Live verification (VERIFICATION.md, appended to Scenario 4 as a dated re-run)

Ubuntu 26.04 VM, CI snap installed `--dangerous`:

- **E. Icon resolves without the Flatpak.** The registered file's `Icon=` line is the
  `/snap/orcshot/current/…png` path and the file exists. In the host session,
  `Gio.DesktopAppInfo.new("orcshot_orcshot.desktop").get_icon()` is a `Gio.FileIcon` whose file
  is that PNG — not a `Gio.ThemedIcon` named `org.orcshot.Orcshot` (which is what the Flatpak
  export was satisfying before). A path icon needs no theme lookup, so the Flatpak's presence
  cannot mask a failure here.
- **F. Seen, not inferred.** Screenshot the app grid entry, and — with the snap running — the
  dock/switcher entry for the running window (GNOME matches a snap's windows to
  `orcshot_orcshot.desktop` through the `snap.orcshot.orcshot` cgroup), both showing the Orcshot
  mark. To rule out the Flatpak export answering instead, run the same screenshots after
  `flatpak uninstall --user org.orcshot.Orcshot` on the VM, then reinstall the Flatpak bundle
  from the session scratchpad (`orcshot_0.3.0.flatpak`, still under `bundle2/`) so the VM's
  state is as before.

## Scope boundaries

- **The Snap Store listing icon** (`icon:` top-level key in `snapcraft.yaml`, shown on
  snapcraft.io and in `snap info`) is a separate asset with the store's own size rules and is
  not set here. It is part of #198's snap-half onboarding, and how Orcshot's mark is presented
  there is direflail's decision, not a build detail — ask before choosing an asset or wrapping
  the non-square PNG the way the Flatpak build does.
- #214 (SVG pixbuf loader log line) untouched; it does not affect the launcher icon (a PNG).
- Flatpak and .deb icons untouched.
