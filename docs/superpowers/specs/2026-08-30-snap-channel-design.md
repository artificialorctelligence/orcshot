# Snap channel — design

## Goal

Ship a real, non-throwaway Snap of Orcshot — the second of the three channels the approved
cross-channel pipeline spec (`docs/superpowers/specs/2026-08-29-cross-channel-build-pipeline-design.md`)
calls for, following directly on from the apt/.deb channel's own CI automation
(`docs/superpowers/plans/2026-08-29-apt-ci-automation.md`), and from `#184`'s own live-verified
finding that Snap's confinement genuinely does not block the redesigned Wayland tray's D-Bus menu
export. Unlike Flatpak (Wayland-only, per the parent spec's own scope), this Snap ships **both**
X11 and Wayland — Snap's X11 support is confirmed genuine and unmediated (Flameshot's own real,
published `strict`-confinement `snapcraft.yaml` uses the plain `x11` interface, not a portal).

## Real, live-verified groundwork this design depends on

Three things were confirmed live during this same design's own brainstorm, not assumed:

- **`base: core24`, not `core26`.** `core26` was checked live and found to have been published to
  the stable channel only 8 days before this spec was written — real, but with far less real-world
  mileage across different hosts' `snapd` versions than `core24`, which is also what Flameshot's own
  working manifest uses (a direct, line-by-line comparison point this design can lean on).
- **`personal-files` genuinely works for its intended purpose, but only via `$SNAP_REAL_HOME`, not
  `$HOME`.** A real spike (throwaway, deleted once answered — see this session's own transcript for
  the full recipe) built a minimal strict-confinement snap, connected `personal-files` manually
  against a `--dangerous` local install (no Canonical review needed for that path), and had a
  confined app copy a real extension file out. The first attempt used `$HOME` and appeared to
  succeed - but landed the file in Snap's own always-writable, private `~/snap/<name>/<revision>/`
  directory, which needs no special interface at all and proves nothing. Confined app code's `$HOME`
  stays redirected even with `personal-files` connected; `$SNAP_REAL_HOME` (a real, documented snapd
  env var - "the vanilla home directory before snapd-induced remapping") is what actually resolves to
  the real, un-redirected path. Once corrected, the file landed at the genuine
  `~/.local/share/gnome-shell/extensions/orcshot-tray@orcshot.org/`, and headless GNOME Shell (the
  exact recipe already proven for the apt channel's own CI) loaded it - extension's own diagnostic
  line fired (`orcshot-tray-diag: bus name vanished`), zero JS errors.
- **A `dbus` slot is required**, not optional - already found live during `#184`'s own earlier
  investigation (a real `AccessDenied owning org.orcshot.Orcshot` AppArmor denial without one).

## Scope

**In scope:** a real `snapcraft.yaml` (X11 + Wayland, strict confinement), the new
`channel_detect.py` module (channel detection + sandboxed extension install, shared groundwork any
sandboxed channel needs - Flatpak's own later plan will reuse `detect_channel()`), the Snap-specific
first-run UX for `personal-files` never being auto-connected, and `.github/workflows/snap.yml`
(build + two-tier verify, matching apt's own proven shape).

**Out of scope:** Flatpak (separate, later plan), any publish/upload automation (Snap Store
submission - a distinct, later phase per the parent spec's own scope section), and the real Canonical
review needed before `personal-files` auto-connects for an end user (an external, non-automatable
dependency - see "Known open items" below, not something this design can close out itself).

## Packaging (`snapcraft.yaml`)

```yaml
name: orcshot
base: core24
confinement: strict
grade: stable
version: <mirrors pyproject.toml's version, same as debian/changelog does for apt>

apps:
  orcshot:
    command: bin/orcshot
    plugs:
      - x11
      - wayland
      - desktop
      - desktop-legacy
      - gsettings
      - dot-local-share-gnome-shell

slots:
  dbus-orcshot:
    interface: dbus
    bus: session
    name: org.orcshot.Orcshot

plugs:
  dot-local-share-gnome-shell:
    interface: personal-files
    write:
      - $HOME/.local/share/gnome-shell/extensions

parts:
  orcshot:
    plugin: python
    source: .
    stage-packages:
      - python3-gi
      - python3-gi-cairo
      - python3-cairo
      - python3-numpy
      - python3-shapely
      - python3-xlib
      - gir1.2-gtk-3.0
      - gir1.2-rsvg-2.0
      - gir1.2-gdkpixbuf-2.0
      - gir1.2-pango-1.0
      - gir1.2-glib-2.0
      - gir1.2-gsound-1.0

  bundled-extensions:
    plugin: dump
    source: src/orcshot/resources/gnome-shell-extensions
    organize:
      "*": share/orcshot/gnome-shell-extensions/
```

`stage-packages` is `debian/control`'s real `Depends` list, transcribed - not re-derived, not
hand-trimmed - for the same reason `apt.yml`'s `apt-get build-dep -y .` reads it directly rather than
duplicating it: one real source of truth, one thing to keep in sync.

The `x11` + `wayland` plugs sit alongside each other deliberately (not X11-only, not Wayland-only) -
this project's own runtime already branches on `XDG_SESSION_TYPE` (`backend_select.py`), so one Snap
covering both sessions matches how the `.deb` already works, rather than needing two separate Snap
builds.

## `channel_detect.py` (new module)

```python
def detect_channel() -> Literal["deb", "flatpak", "snap"] | None:
    """$SNAP/$SNAP_NAME set -> "snap". $FLATPAK_ID set, or /.flatpak-info
    exists -> "flatpak". Neither -> "deb" (the existing, already-working
    apt install - dh_install already placed extensions system-wide, this
    function's whole purpose from here is knowing when NOT to act)."""


def install_bundled_extension_if_needed(uuid: str) -> bool:
    """No-op returning True immediately when detect_channel() == "deb".
    Otherwise: if the extension isn't already at the real per-user
    path, copy it there from wherever it's bundled read-only inside the
    package ($SNAP/share/orcshot/gnome-shell-extensions/<uuid>/ for Snap;
    Flatpak's own bundled path once that channel's plan defines it).
    Returns True on success (including the already-installed case),
    False if the copy failed (e.g. Snap's personal-files not connected)
    so the caller can react.

    Snap-specific, spike-confirmed detail: the destination is built from
    $SNAP_REAL_HOME, never $HOME - $HOME stays redirected to Snap's own
    private per-revision directory even with personal-files connected,
    and writing there needs no special permission at all, so using it
    would silently "succeed" while placing the file somewhere GNOME
    Shell never scans. Flatpak has no equivalent redirection - its own
    --filesystem grant already exposes the real path directly as $HOME.
    """
```

Lives alongside `gnome_extension_setup.py`, not inside it - channel detection and sandboxed-install
are a genuinely separate concern from that module's existing job (talking to gsettings/D-Bus to
enable an extension already known to be on disk). `gnome_extension_setup.py` itself is unchanged.

## Wiring into `first_run_setup.py`

The hook point is immediately before the existing `is_gnome_wayland:` block
(`src/orcshot/ui/first_run_setup.py`), since `enable_extension`/`enable_extension_live` both assume
the extension's files already exist on disk:

```python
if is_gnome_wayland:
    tray_installed = install_bundled_extension_if_needed(TRAY_EXTENSION_UUID)
    clipboard_installed = install_bundled_extension_if_needed(CLIPBOARD_EXTENSION_UUID)
    window_calls_installed = install_bundled_extension_if_needed(WINDOW_CALLS_EXTENSION_UUID)
    if detect_channel() == "snap" and not (tray_installed and clipboard_installed and window_calls_installed):
        show_snap_connect_prompt(parent)
    enable_extension(settings_backend, WINDOW_CALLS_EXTENSION_UUID)
    enable_extension(settings_backend, CLIPBOARD_EXTENSION_UUID)
    enable_extension(settings_backend, TRAY_EXTENSION_UUID)
    # ...unchanged from here down (enable_extension_live loop)...
```

For plain `.deb` installs this is a zero-behavior-change no-op (`detect_channel()` returns `"deb"`,
`install_bundled_extension_if_needed` returns `True` immediately) - the existing, already-working
install path is untouched.

**`show_snap_connect_prompt`**: a small dialog with the exact command in a copyable field:

```
snap connect orcshot:dot-local-share-gnome-shell
```

No attempt to launch a terminal or run the command automatically (not reliably possible under strict
confinement, and fragile even where it might be) - matches this same file's existing pattern for
desktops without automatic hotkey support (a manual, cut-and-pasteable cheat sheet, not an attempted
automation). Real research (done during the parent spec's own brainstorm) found GIMP's, Firefox's,
and Thunderbird's official Snap packaging all declare `personal-files` with no in-app handling of the
missing-connection case at all - this dialog is proportionate, not a corner cut, since there's no
stronger established ecosystem norm to match.

## CI (`.github/workflows/snap.yml`)

Same two-job shape as `apt.yml`, same reasoning for the split (a well-understood `build` signal stays
stable; a newer, less-proven `verify` tier iterates independently):

- **`build`**: `canonical/action-build@v1`, uploads the built `.snap` as an artifact.
- **`verify`, cheap tier**: `snap install --dangerous <artifact>`, then a launch smoke test (same
  spirit as apt's `orcshot --help` - confirms the installed binary starts without needing a display).
- **`verify`, hard tier** (now genuinely proven, not aspirational - this spec's own spike is the
  live evidence): `snap connect orcshot:dot-local-share-gnome-shell` (manual connect against a
  `--dangerous` local install needs no Canonical review - confirmed live), trigger the app's real
  first-run extension-install path (exercising the actual `channel_detect.py` code, not a throwaway
  stand-in), then the same proven headless-GNOME-Shell recipe from the apt channel: fixed-address
  `dbus-daemon --fork`, `gnome-shell --headless --virtual-monitor`, a bounded wait on
  `"GNOME Shell started"`, `gnome-extensions enable orcshot-tray@orcshot.org`, a bounded wait on the
  extension's own `orcshot-tray-diag` line, and a negative grep for `JS ERROR`/`Gjs-CRITICAL` -
  transcribing apt's own final-review-hardened version of this check, not the plan's original
  (buggier) one.

## Known open items, carried forward honestly

- **Store-published Snaps still need a real Canonical review before `personal-files` auto-connects
  for an end user** - this CI only proves the local, `--dangerous`-install path (which needs no
  review). That's an external, non-automatable dependency, not something this design closes out -
  already flagged in the parent spec's own "Known open items," reconfirmed here rather than silently
  dropped.
- **The exact review process/timeline** for that Canonical review is real but not yet started - the
  parent spec's own research (a real, current privileged-interface review thread) found ~2 days for
  first response in the cited example, with real back-and-forth, not a single fire-and-forget
  request. Budgeting for iteration belongs to whoever actually submits that review, not this design.
- **`snapcraft`'s Python plugin's exact interaction with this project's `pyproject.toml`/`hatchling`
  build backend** has not yet been live-tested the way apt's own `pip install -e ".[dev]"` was (and
  needed two rounds of real fixes - `--system-site-packages`, then `xvfb-run` - before it worked).
  The implementation plan should expect at least one real, CI-discovered surprise here too, the same
  honest expectation apt's own plan carried and was right to carry.
