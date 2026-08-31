# Flatpak Channel Design

## Goal

Ship Orcshot as a real, single Flatpak package - the third and final channel of the
cross-channel build pipeline (`docs/superpowers/specs/2026-08-29-cross-channel-build-pipeline-design.md`),
after apt/.deb and Snap. One package, not a split build: both X11 and Wayland capture, plus the
Wayland tray extension, all in one manifest.

This supersedes BACKLOG #185's original framing entirely. That entry proposed a *Wayland-only*
Flatpak build - X11 support dropped, X11 users redirected to the `.deb` via a listing-level link
and a runtime warning dialog - because at the time it was written, whether `fallback-x11` gave
real X11 capture under Flatpak confinement was an open, unresearched question. It no longer is.

## Real, live-verified groundwork (2026-08-30/31, BACKLOG #187)

Everything below was proven live this session, not reasoned about from documentation:

- **`fallback-x11` gives genuine, unrestricted native X11 capture.** A throwaway `flatpak-builder`
  spike declaring only `--socket=wayland` + `--socket=fallback-x11` (no portal, no broader X11
  socket) made a real X11 protocol read (`root.get_image()`, the same operation
  `X11CaptureBackend` performs via GDK) from inside the confined sandbox on a real X11 session
  (this project's own Mint/Cinnamon dev host) and got back real, varied screen pixel data - not a
  black or blocked response.
- **The Screenshot portal (`org.freedesktop.portal.Screenshot`) works completely under real
  strict confinement on real GNOME Wayland - end to end, not just "the socket connects."** A
  second spike, run on the project's own real Ubuntu 26.04/GNOME Shell 50.1 VM, needed two real
  fixes before it worked:
  1. A genuine `Gtk.Window`, actually mapped and given real focus by the window manager - a
     headless CLI-only process can never show the portal's Access dialog at all
     (`org.freedesktop.DBus.Error.AccessDenied: Only the focused app is allowed to show a system
     access dialog`, a real, documented GNOME Shell policy -
     confirmed via `flatpak/xdg-desktop-portal#1338` upstream).
  2. A real `.desktop` file with a real `Name=`. Without one, GNOME Shell's own `_windowTracker`
     has no way to associate the confined app's window with a recognized "app" at all, independent
     of genuine X11/Wayland-level keyboard focus (confirmed live: even with `is_active()=True
     has_toplevel_focus=True` reported by GTK's own API, the call still failed identically until a
     `.desktop` file was added).
  Once both were in place: a real Access dialog appeared ("Allow Orcshot Portal Spike to Take
  Screenshots?"), was approved, and the call succeeded - `response_code=0`, a real 195KB PNG
  returned through the document-portal FUSE mount (`/run/user/<uid>/doc/...`), exactly matching
  what `wayland_portal.py`'s own code comment already predicted a sandboxed caller would get.
- **`--filesystem=~/.local/share/gnome-shell/extensions:create` grants write access to that one
  directory with no separate runtime "connect" step** - simpler than Snap's `personal-files`
  interface, which needs `snap connect` after install. A confined process wrote and read back real
  content immediately after install.

**Not literally tested**: a single manifest with *both* `--socket=wayland` and
`--socket=fallback-x11` declared together, run live on an actual Wayland session, to directly
confirm nothing about `fallback-x11`'s declared-but-conditionally-revoked presence interferes with
the portal path. Flatpak's own documented, already-observed behavior (`fallback-x11` is revoked
automatically whenever Wayland is present, a purely conditional grant with no other side effects)
makes this very likely a non-issue, but the two capabilities were proven in separate spikes, not
literally combined in one live run. Listed under Known Open Items below.

## Scope

Build the real Flatpak package (manifest, CI build + verify) with:
- Both X11 (native, via `fallback-x11`) and Wayland (portal) capture in one build
- The Wayland tray extension (`orcshot-tray@orcshot.org`) and its sibling bundled extensions,
  matching what Snap ships - `channel_detect.py`'s existing mechanism, extended to Flatpak
- Real CI verification, matching the rigor apt and Snap CI already established (a real headless
  GNOME Shell check that the confined extension-install path and the extension itself actually
  work, not just that the build succeeds)

**Explicitly out of scope**, matching how apt and Snap were each scoped:
- Actual Flathub submission (appstream metadata, screenshots, the Flathub review process) - this
  plan produces a real, CI-verified `.flatpak` bundle, not a published listing
- An automated CI check of the Screenshot portal's own capture path - not scriptable headlessly
  (needs a real, interactive Access-dialog approval); the mechanism is proven by this session's own
  spike, documented above, not re-proven on every CI run

## Packaging

`org.orcshot.Orcshot.yaml` (repo root):

```yaml
app-id: org.orcshot.Orcshot
runtime: org.gnome.Platform
runtime-version: '50'
sdk: org.gnome.Sdk
command: orcshot
finish-args:
  - --socket=wayland
  - --socket=fallback-x11
  - --filesystem=~/.local/share/gnome-shell/extensions:create
modules:
  - name: orcshot
    plugin: python
    source: .
    # Same real, live-confirmed fixes Snap's own snapcraft.yaml already needed, for the identical
    # underlying reasons - PyGObject/pycairo have no PyPI wheels, dconf's own GIO module isn't
    # discoverable without an explicit env var, GI_TYPELIB_PATH needs the same treatment. Read the
    # current snapcraft.yaml directly for the exact, real, already-proven values rather than
    # transcribing from memory here.
    build-packages: [python3-gi, python3-gi-cairo, python3-cairo]
    build-environment:
      - PARTS_PYTHON_VENV_ARGS: "--system-site-packages"
    stage-packages: # transcribed from debian/control's real current Depends list at plan time
      - dconf-gsettings-backend
      # ... (the same set snapcraft.yaml already stages, minus anything GNOME Platform 50 already
      # provides - Task 1 of the implementation plan confirms which, rather than assuming)
    # environment: GI_TYPELIB_PATH / GIO_EXTRA_MODULES as needed - Flatpak's own /app-prefix
    # convention differs from Snap's $SNAP, exact paths confirmed during implementation, not
    # guessed here.
  - name: bundled-extensions
    plugin: dump
    source: src/orcshot/resources/gnome-shell-extensions
    organize:
      "*": share/orcshot/gnome-shell-extensions/
```

`org.orcshot.Orcshot.desktop`, installed to `/app/share/applications/`:
```
[Desktop Entry]
Name=Orcshot
Exec=orcshot
Icon=org.orcshot.Orcshot
Type=Application
Categories=Graphics;
```
(Proven this session to be a hard requirement for the Wayland Access dialog, not optional
polish.)

## Code changes (`src/orcshot/`)

`channel_detect.detect_channel()` already correctly identifies Flatpak - no change.

`ui/first_run_setup.py`:
- `_extension_bundle_dir(uuid)` currently does `Path(env["SNAP"]) / "share" / ...` -
  `KeyError`s under Flatpak. Fix: Flatpak always mounts the app's own install prefix at the fixed
  path `/app` (no env-var indirection the way Snap's `$SNAP` needs), so this becomes a one-line
  branch on `detect_channel()`.
- `_install_bundled_extensions_for_snap()` (extracted during the BACKLOG #191 fix) generalizes to
  cover both sandboxed channels. Flatpak's `dest_parent` is simply
  `Path.home() / ".local" / "share" / "gnome-shell" / "extensions"` - no `$SNAP_REAL_HOME`-style
  redirection needed, since Flatpak doesn't redirect `$HOME` the way Snap does (confirmed live this
  session: a plain `os.path.expanduser("~/...")` write succeeded against the
  `--filesystem=...:create` grant with no special resolution). The Snap-only
  `show_snap_connect_prompt` stays Snap-only - Flatpak's filesystem grant is install-time, no
  separate "connect" step exists to prompt for, so an install failure there is a genuine
  unexpected I/O error, not a "run this command" situation.

## CI architecture (`.github/workflows/flatpak.yml`)

Mirrors apt.yml/snap.yml's own proven two-job shape:

- **`build`**: `flatpak-builder` build, `flatpak build-bundle` to produce a distributable
  `.flatpak` file, uploaded as an artifact (matching the `.deb`/`.snap` upload pattern already
  established).
- **`verify`**: install the bundle (`flatpak install --user` from the bundle file), confirm it
  runs, then the same hard-tier check apt and Snap both already use - trigger the real
  `install_bundled_extension_if_needed` code path through the confined process (via `flatpak run
  --command=...`, matching Snap's own `snap run --shell` pattern), confirm the write lands in the
  real per-user extensions directory, launch `gnome-shell --headless`, confirm the extension
  actually loads (bounded waits on real log lines, matching the already-proven apt/Snap recipe
  exactly - not re-derived from scratch).

No automated portal-Screenshot capture check in CI - see Scope above for why.

## Known open items

- **Not literally tested**: both sockets declared together, run live on a real Wayland session
  (see Groundwork above). Low risk given Flatpak's own documented `fallback-x11` revocation
  behavior, but flagged rather than silently assumed.
- **Bundled-extension upgrade path** (BACKLOG #191's own finding, already fixed in
  `channel_detect.install_bundled_extension_if_needed` for Snap) applies identically to Flatpak -
  no new design needed, the fix already covers both channels since it lives in the shared function.
- **`version` scheme** - matching Snap's own `adopt-info` + `pyproject.toml`-reading fix (BACKLOG
  #191), not `flatpak-builder`'s own git-describe-style default, for the same one-source-of-truth
  reason.
- **RPM-family/Arch scope (BACKLOG #132)** and **Flathub submission itself** remain explicitly
  separate, later efforts, not part of this plan.
