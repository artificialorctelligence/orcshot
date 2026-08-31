# Flatpak Channel Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship Orcshot as a real, single Flatpak package - both X11 (native, via `fallback-x11`)
and Wayland (portal) capture, plus the Wayland tray extension, in one manifest - with real CI
build + verify, matching the rigor already established for the apt and Snap channels.

**Architecture:** A `flatpak-builder` manifest (`org.orcshot.Orcshot.yaml`) at the repo root,
built on `org.gnome.Platform`//50. Two small, mechanical generalizations to existing Snap-only
helper functions in `ui/first_run_setup.py` extend the already-proven bundled-extension-install
mechanism to Flatpak. CI mirrors `snap.yml`'s own already-hardened two-job shape exactly.

**Tech Stack:** `flatpak-builder`, `org.gnome.Platform`/`org.gnome.Sdk` 50, Python 3 (`plugin:
python`), GitHub Actions (`ubuntu-24.04`).

**Spec:** `docs/superpowers/specs/2026-08-31-flatpak-channel-design.md`

## Global Constraints

- No task subagent ever pushes to `main` directly - PR-only, controller merges after explicit
  user confirmation.
- CI runner: `ubuntu-24.04`.
- No secrets in the CI workflow.
- `stage-packages`/`build-packages` in `org.orcshot.Orcshot.yaml` must be transcribed from
  `debian/control`'s real current `Depends` list (reproduced in Task 1 below - already read
  directly from the file, not from memory), not invented.
- The Task 4 headless-Shell recipe must be transcribed from the CURRENT real
  `.github/workflows/snap.yml` (reproduced in Task 4 below - already read directly from the
  file), including its systemd `--user` session-bus fix and its "gnome-shell must already be
  running before the confined write" ordering - both are real, already-hardened fixes for real
  bugs, not incidental style.
- No automated CI check of the Screenshot portal's own capture path - not scriptable headlessly,
  deliberately out of scope per the spec.
- `org.orcshot.Orcshot.desktop` with a real `Name=` is a proven hard requirement (spec's own
  groundwork section) - must not be treated as optional polish or deferred.
- direflail has zero prior GitHub Actions experience - when results are walked through with them,
  show the real GitHub Actions web UI live (via the Browser tool), not just CLI output or prose.

---

### Task 1: `org.orcshot.Orcshot.yaml` + `org.orcshot.Orcshot.desktop`

**Files:**
- Create: `org.orcshot.Orcshot.yaml` (repo root)
- Create: `org.orcshot.Orcshot.desktop` (repo root)

**Interfaces:**
- Consumes: nothing from other tasks.
- Produces: a real, locally-buildable Flatpak manifest later tasks' CI workflow builds and
  installs. App-id `org.orcshot.Orcshot`, command name `orcshot`.

- [ ] **Step 1: Write the manifest**

`debian/control`'s real current `Depends` list (already read directly from the file - use exactly
this list, do not re-derive it):
```
python3-gi, python3-gi-cairo, python3-cairo, python3-numpy, python3-shapely, python3-xlib,
gir1.2-gtk-3.0, gir1.2-rsvg-2.0, gir1.2-gdkpixbuf-2.0, gir1.2-pango-1.0, gir1.2-glib-2.0,
gir1.2-gsound-1.0
```

`snapcraft.yaml`'s current, real, already-proven content (read directly - reproduced here for
reference) shows the *shape* of every fix needed and *why* each one exists: `PARTS_PYTHON_VENV_ARGS:
--system-site-packages` (PyGObject/pycairo have no PyPI wheels), `dconf-gsettings-backend` +
`GIO_EXTRA_MODULES` (GLib's dconf backend module isn't discoverable without it, silently falls back
to a broken keyfile backend), `GI_TYPELIB_PATH` (GObject-Introspection's compiled-in default points
at the base image's own `/usr`, not this app's own staged tree), an `adopt-info`/`craftctl set
version` step reading `pyproject.toml` directly (one source of truth, no manual per-release version
edit). The *reasoning* for every one of these transfers directly to Flatpak; the *path values* do
not - Snap's `$SNAP` env var has no Flatpak equivalent, Flatpak always mounts the app's own install
prefix at the fixed path `/app` instead. Write the manifest:

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
    build-packages:
      - python3-gi
      - python3-gi-cairo
      - python3-cairo
    build-environment:
      - PARTS_PYTHON_VENV_ARGS: "--system-site-packages"
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
      - dconf-gsettings-backend
    # /app/usr is where the python plugin's --system-site-packages venv
    # sees these apt-staged bindings from at RUNTIME (build-time
    # discovery via --system-site-packages is separate from what the
    # packaged app can see once running - the exact gap
    # GI_TYPELIB_PATH/GIO_EXTRA_MODULES exist to close, matching
    # snapcraft.yaml's own proven fix for the identical class of gap).
    build-commands:
      - pip3 install --prefix=/app --no-deps .
    post-install:
      - install -Dm644 ../org.orcshot.Orcshot.desktop /app/share/applications/org.orcshot.Orcshot.desktop
  - name: bundled-extensions
    plugin: dump
    source: src/orcshot/resources/gnome-shell-extensions
    organize:
      "*": share/orcshot/gnome-shell-extensions/
```

**Do not treat the `GI_TYPELIB_PATH`/`GIO_EXTRA_MODULES`/`command:` values above as final** - they
are the best real-evidence-grounded starting point from `snapcraft.yaml`'s own proven fixes, but
Flatpak's own module/typelib search-path conventions for a `plugin: python` module writing into
`/app` were not verified live during this plan's own writing. Step 3 below is where they get
confirmed or corrected against a real build - if the real build in Step 3 shows a different path is
needed (e.g. `/app/lib/python3.*/site-packages` instead of a bare pip `--prefix=/app` layout, or a
different typelib directory name than Snap's own triplet-based one), fix it there and note what
changed and why.

- [ ] **Step 2: Write the `.desktop` file**

Proven hard requirement (spec's own groundwork section) - without a real `Name=`, GNOME Shell's own
window tracker can't associate a Flatpak app's window with a recognized "app" at all, and the
portal's Access dialog never appears.

```
[Desktop Entry]
Name=Orcshot
Comment=Screenshot capture and annotation tool
Exec=orcshot
Icon=org.orcshot.Orcshot
Type=Application
Categories=Graphics;
```

- [ ] **Step 3: Build it for real, locally, and fix whatever the real build says is wrong**

```bash
flatpak install --user -y flathub org.gnome.Platform//50 org.gnome.Sdk//50  # if not already installed
flatpak-builder --user --force-clean --install build-dir org.orcshot.Orcshot.yaml
```

Expected on first attempt: something in the guessed `GI_TYPELIB_PATH`/module-path values above is
probably wrong, or the `pip3 install --prefix=/app` step needs adjusting to find the
`--system-site-packages`-staged bindings the way Snap's own Task 4 needed multiple real, live-
debugged rounds to get right (PyGObject building from source instead of reusing apt's, then a
`ModuleNotFoundError: No module named 'gi'` at runtime, then `ValueError: Namespace Gtk not
available`, then a `libblas.so.3`-class staging gap - see `snapcraft.yaml`'s own accumulated
comments for the full, real history of each). Expect the same *category* of issues here, not
necessarily the same three - debug each one live, root cause it (systematic-debugging skill), fix
`org.orcshot.Orcshot.yaml`, rebuild, repeat until:

```bash
flatpak run org.orcshot.Orcshot --help
```

exits 0 with real `--help` output, not a traceback.

- [ ] **Step 4: Confirm the extension-install path's real prerequisite is present**

Snap needed `gnome-shell-common` staged plus an explicit `glib-compile-schemas` step for
`gnome_shell_present()`'s own `Gio.SettingsSchemaSource.get_default()` call to resolve
`org.gnome.shell` at all (BACKLOG #192's own full history). Check whether `org.gnome.Platform`//50
already provides this schema (a GNOME-focused runtime plausibly already bundles GNOME Shell's own
schemas as part of its standard stack, unlike Snap's minimal `core24` base) - don't assume either
way:

```bash
flatpak run --command=python3 org.orcshot.Orcshot -c "
import gi
gi.require_version('Gio', '2.0')
from gi.repository import Gio
source = Gio.SettingsSchemaSource.get_default()
print('source:', source)
print('org.gnome.shell resolvable:', source.lookup('org.gnome.shell', True) is not None if source else False)
"
```

If this returns `False` or crashes, add `gnome-shell-common` to `stage-packages` and the same
`glib-compile-schemas "$FLATPAK_DEST/share/glib-2.0/schemas"` compile step (via `post-install` or
`build-commands`, whichever `flatpak-builder`'s own lifecycle makes correct - confirm live, matching
Snapcraft's own `override-prime` timing requirement for the identical reason: staging never runs a
`.deb`'s own postinst/dpkg-trigger machinery, so the raw schema XML never gets compiled without an
explicit step) to `org.orcshot.Orcshot.yaml`, rebuild, and re-run this exact check until it prints
`True`. If it already prints `True` with nothing added, say so explicitly rather than adding the
fix speculatively - `org.gnome.Platform` including it directly would be a real, worth-recording
difference from Snap's own `core24` base.

- [ ] **Step 5: Commit**

```bash
git add org.orcshot.Orcshot.yaml org.orcshot.Orcshot.desktop
git commit -m "Add org.orcshot.Orcshot.yaml: Flatpak manifest, X11+Wayland+tray in one build"
```

---

### Task 2: Generalize the bundled-extension-install helpers to cover Flatpak

**Files:**
- Modify: `src/orcshot/ui/first_run_setup.py:120-126` (`_extension_bundle_dir`)
- Modify: `src/orcshot/ui/first_run_setup.py:144-165` (`_install_bundled_extensions_for_snap`,
  renamed)
- Modify: `src/orcshot/ui/first_run_setup.py:340` (the one call site, in `_run_dialog`)
- Test: `tests/unit/ui/test_first_run_setup.py`

**Interfaces:**
- Consumes: `orcshot.channel_detect.detect_channel() -> str` (already returns `"flatpak"` when
  `FLATPAK_ID` is set or `/.flatpak-info` exists - already correct, no change needed there).
  `orcshot.channel_detect.install_bundled_extension_if_needed(uuid: str, bundled_dir: Path,
  dest_parent: Path) -> bool` (already channel-agnostic, no change needed there either).
- Produces: `_extension_bundle_dir(uuid: str, env: dict = None) -> Path` (Flatpak-aware).
  `_flatpak_home_extensions_dir(env: dict = None) -> Path` (new, mirrors
  `_snap_real_home_extensions_dir`'s own env-injectable convention).
  `_install_bundled_extensions_for_sandboxed_channel(parent) -> bool` (renamed from
  `_install_bundled_extensions_for_snap`, now covers both `"snap"` and `"flatpak"`).

- [ ] **Step 1: Write the failing tests**

Existing tests in `tests/unit/ui/test_first_run_setup.py` call
`mod._install_bundled_extensions_for_snap(...)` by that exact name - they will fail with
`AttributeError` once the rename below happens, which is the correct signal this step is renaming a
real call site, not just adding new behavior. Update those three existing call sites' function name
(`test_deb_channel_never_installs_bundled_extensions`,
`test_snap_channel_installs_each_bundled_extension`,
`test_snap_channel_prompts_when_an_install_fails` - all three currently call
`mod._install_bundled_extensions_for_snap`) to call
`mod._install_bundled_extensions_for_sandboxed_channel` instead - same arguments, same
assertions, nothing else about them changes. Then add:

```python
def test_extension_bundle_dir_flatpak(tmp_path):
    env = {"FLATPAK_ID": "org.orcshot.Orcshot"}
    result = _extension_bundle_dir("orcshot-tray@orcshot.org", env=env)
    assert result == Path("/app") / "share" / "orcshot" / "gnome-shell-extensions" / "orcshot-tray@orcshot.org"


def test_flatpak_home_extensions_dir_uses_real_home(tmp_path):
    real_home = tmp_path / "home" / "direflail"
    env = {"HOME": str(real_home)}
    result = _flatpak_home_extensions_dir(env=env)
    assert result == real_home / ".local" / "share" / "gnome-shell" / "extensions"


def test_flatpak_channel_installs_each_bundled_extension(monkeypatch, tmp_path):
    import orcshot.ui.first_run_setup as mod

    monkeypatch.setattr(mod, "detect_channel", lambda: "flatpak")
    monkeypatch.setattr(mod, "_extension_bundle_dir", lambda uuid: tmp_path / "bundled" / uuid)
    monkeypatch.setattr(mod, "_flatpak_home_extensions_dir", lambda: tmp_path / "real-home")
    calls = []
    monkeypatch.setattr(
        mod, "install_bundled_extension_if_needed", lambda uuid, bundled, dest: calls.append(uuid) or True
    )
    prompted = []
    monkeypatch.setattr(mod, "show_snap_connect_prompt", lambda parent: prompted.append(parent))

    acted = mod._install_bundled_extensions_for_sandboxed_channel(None)

    assert acted is True
    assert calls == [mod.WINDOW_CALLS_EXTENSION_UUID, mod.CLIPBOARD_EXTENSION_UUID, mod.TRAY_EXTENSION_UUID]
    # Flatpak's --filesystem grant is install-time - there's no "connect"
    # step to prompt for the way Snap has, so even a failed install must
    # not trigger Snap's own connect-prompt dialog.
    assert prompted == []


def test_flatpak_channel_never_prompts_on_install_failure(monkeypatch, tmp_path):
    import orcshot.ui.first_run_setup as mod

    monkeypatch.setattr(mod, "detect_channel", lambda: "flatpak")
    monkeypatch.setattr(mod, "_extension_bundle_dir", lambda uuid: tmp_path / "bundled" / uuid)
    monkeypatch.setattr(mod, "_flatpak_home_extensions_dir", lambda: tmp_path / "real-home")
    monkeypatch.setattr(mod, "install_bundled_extension_if_needed", lambda *a, **kw: False)
    prompted = []
    monkeypatch.setattr(mod, "show_snap_connect_prompt", lambda parent: prompted.append(parent))

    acted = mod._install_bundled_extensions_for_sandboxed_channel(None)

    assert acted is True
    assert prompted == []
```

Also update the import at the top of the test file (`from orcshot.ui.first_run_setup import (
_default_executable, _extension_bundle_dir, _snap_real_home_extensions_dir, )`) to add
`_flatpak_home_extensions_dir` to that same import list.

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/unit/ui/test_first_run_setup.py -v`
Expected: the three renamed tests fail with `AttributeError:
module 'orcshot.ui.first_run_setup' has no attribute '_install_bundled_extensions_for_sandboxed_channel'`;
the new Flatpak tests fail with `AttributeError` on `_flatpak_home_extensions_dir` not existing, or
`ImportError` on the updated import line.

- [ ] **Step 3: Implement**

In `src/orcshot/ui/first_run_setup.py`, replace `_extension_bundle_dir` (currently lines 120-126):

```python
def _extension_bundle_dir(uuid: str, env: dict = None) -> Path:
    """Where this extension's files are bundled read-only inside a Snap
    or Flatpak package. Only meaningful when detect_channel() is "snap"
    or "flatpak" - the caller is responsible for checking that first."""
    if env is None:
        env = os.environ
    if env.get("SNAP"):
        return Path(env["SNAP"]) / "share" / "orcshot" / "gnome-shell-extensions" / uuid
    # Flatpak always mounts the app's own install prefix at the fixed
    # path /app - no env-var indirection the way Snap's $SNAP needs
    # (confirmed live, BACKLOG #187, 2026-08-31).
    return Path("/app") / "share" / "orcshot" / "gnome-shell-extensions" / uuid
```

Add `_flatpak_home_extensions_dir` right after `_snap_real_home_extensions_dir` (currently ending
at line 141):

```python
def _flatpak_home_extensions_dir(env: dict = None) -> Path:
    """The real per-user GNOME Shell extensions path a Flatpak install
    can reach once --filesystem=~/.local/share/gnome-shell/extensions:create
    is granted (install-time, no separate "connect" step the way Snap's
    personal-files interface needs - confirmed live, BACKLOG #187,
    2026-08-31). Unlike Snap, Flatpak doesn't redirect $HOME to a
    private path at all, so this is plain $HOME, env-injectable for
    tests to match _snap_real_home_extensions_dir's own convention.
    """
    if env is None:
        env = os.environ
    return Path(env["HOME"]) / ".local" / "share" / "gnome-shell" / "extensions"
```

Replace `_install_bundled_extensions_for_snap` (currently lines 144-165) with the renamed,
generalized version:

```python
def _install_bundled_extensions_for_sandboxed_channel(parent) -> bool:
    """Copies each bundled extension into the real per-user extensions
    path when running under Snap or Flatpak - sandboxed channels can't
    write to the system-wide path the way .deb's own dh_install does.
    Returns whether this actually ran: True only for snap/flatpak, so a
    plain .deb install (detect_channel() == "deb") is a verified no-op
    - the loop body never executes at all, matching this feature's own
    whole point of channel-gating (BACKLOG #191 - extracted so this
    gating is exercised by a real test, not just a monkeypatch's own
    return value asserted back at itself). Generalized from Snap-only to
    also cover Flatpak (BACKLOG #185/#187, 2026-08-31): Flatpak's own
    --filesystem=...:create grant is install-time, no separate "connect"
    step exists the way Snap's personal-files needs, so only Snap's own
    failure path prompts for one.
    """
    channel = detect_channel()
    if channel == "snap":
        dest_parent = _snap_real_home_extensions_dir()
    elif channel == "flatpak":
        dest_parent = _flatpak_home_extensions_dir()
    else:
        return False
    all_installed = True
    for uuid in (WINDOW_CALLS_EXTENSION_UUID, CLIPBOARD_EXTENSION_UUID, TRAY_EXTENSION_UUID):
        bundled_dir = _extension_bundle_dir(uuid)
        if not install_bundled_extension_if_needed(uuid, bundled_dir, dest_parent):
            all_installed = False
    if not all_installed and channel == "snap":
        show_snap_connect_prompt(parent)
    return True
```

Update the one call site at (currently) line 340, inside `_run_dialog`, from
`_install_bundled_extensions_for_snap(parent)` to
`_install_bundled_extensions_for_sandboxed_channel(parent)`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/unit/ui/test_first_run_setup.py tests/unit/test_channel_detect.py -v`
Expected: all pass, including the pre-existing Snap-path tests unchanged (a real regression check -
the rename/restructure must not have broken Snap's own already-proven behavior).

- [ ] **Step 5: Run the full suite**

Run: `xvfb-run -a .venv/bin/pytest tests -m "not x11 and not wayland" -q`
Expected: all pass (this project's full suite was at 1152 passing before this task; expect
1152 + 6 new = 1158, but don't hard-code that number into an assertion anywhere - just confirm the
run is clean).

- [ ] **Step 6: Commit**

```bash
git add src/orcshot/ui/first_run_setup.py tests/unit/ui/test_first_run_setup.py
git commit -m "Generalize bundled-extension install to cover Flatpak, not just Snap"
```

---

### Task 3: `.github/workflows/flatpak.yml` - build + cheap verify

**Files:**
- Create: `.github/workflows/flatpak.yml`

**Interfaces:**
- Consumes: `org.orcshot.Orcshot.yaml` (Task 1).
- Produces: a `build-flatpak` job uploading a `.flatpak` bundle artifact named `orcshot-flatpak`,
  and a `verify-flatpak` job that installs and smoke-tests it. Task 4 extends `verify-flatpak`
  with the hard tier - do not mark this task's own verify job "complete" in a way that discourages
  Task 4 from editing the same file.

- [ ] **Step 1: Write the workflow**

`snap.yml`'s current, real, already-hardened top-level shape (permissions, concurrency,
timeout-minutes, the two-job build/verify split) is the proven pattern - reproduced here, adapted
for `flatpak-builder` instead of `canonical/action-build`:

```yaml
name: flatpak

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

permissions:
  contents: read

concurrency:
  group: ${{ github.workflow }}-${{ github.ref }}
  cancel-in-progress: true

jobs:
  build-flatpak:
    name: flatpak / build
    runs-on: ubuntu-24.04
    timeout-minutes: 20
    steps:
      - uses: actions/checkout@v4

      - name: Install flatpak-builder and add flathub
        run: |
          sudo apt-get update -qq
          sudo apt-get install -y flatpak flatpak-builder
          sudo flatpak remote-add --if-not-exists flathub https://flathub.org/repo/flathub.flatpakrepo

      - name: Install the GNOME runtime and SDK
        run: sudo flatpak install -y flathub org.gnome.Platform//50 org.gnome.Sdk//50

      - name: Build the Flatpak
        run: flatpak-builder --force-clean --repo=repo build-dir org.orcshot.Orcshot.yaml

      - name: Bundle it into a single distributable file
        run: flatpak build-bundle repo orcshot.flatpak org.orcshot.Orcshot

      - name: Upload the built bundle
        uses: actions/upload-artifact@v4
        with:
          name: orcshot-flatpak
          path: orcshot.flatpak

  verify-flatpak:
    name: flatpak / verify
    needs: build-flatpak
    runs-on: ubuntu-24.04
    timeout-minutes: 20
    steps:
      - uses: actions/checkout@v4

      - name: Download the built bundle
        uses: actions/download-artifact@v4
        with:
          name: orcshot-flatpak

      - name: Install flatpak and add flathub
        run: |
          sudo apt-get update -qq
          sudo apt-get install -y flatpak
          sudo flatpak remote-add --if-not-exists flathub https://flathub.org/repo/flathub.flatpakrepo

      - name: Install the GNOME runtime (the SDK isn't needed to just run the app)
        run: sudo flatpak install -y flathub org.gnome.Platform//50

      - name: Install the built bundle
        run: sudo flatpak install -y ./orcshot.flatpak

      - name: Confirm the installed binary launches without crashing
        run: flatpak run org.orcshot.Orcshot --help
```

- [ ] **Step 2: Confirm `flatpak run` itself doesn't hit `snap run`'s own "not a snap cgroup"-class
      bug**

`snap.yml`'s own real, hard-won fix (its "Start a real systemd --user session bus" step - read
that file directly, reproduced in Task 4 below) exists because `snap run` needs
`org.freedesktop.systemd1.Manager` on the session bus to create its own confinement scope, and a
bare `dbus-daemon` without a real `systemd --user` behind it breaks that. Confirm live in CI,
before assuming it does or doesn't transfer, whether `flatpak run` has the same requirement - it
may not (Flatpak's own confinement mechanism, `bwrap`, doesn't necessarily need the identical
systemd-scope-creation handshake `snap-confine` does). Push this task's branch, open the PR, and
read the real `flatpak / verify` job's log for this step. If `flatpak run org.orcshot.Orcshot
--help` fails with anything resembling `snap run`'s own cgroup/scope error class, add the exact
same fix (`sudo systemctl start user@$(id -u).service`, waiting for the session bus, as `snap.yml`
already does) as its own step before this one. If it just works without that fix, leave it out -
don't add unneeded steps preemptively, and note in the commit message that this was checked live,
not assumed either way.

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/flatpak.yml
git commit -m "Add flatpak CI: build + cheap verify"
```

---

### Task 4: Extend `verify-flatpak` with the hard tier - real extension-install + headless Shell load

**Files:**
- Modify: `.github/workflows/flatpak.yml` (the `verify-flatpak` job, adding steps after "Confirm
  the installed binary launches without crashing")

**Interfaces:**
- Consumes: `_install_bundled_extensions_for_sandboxed_channel`,
  `channel_detect.install_bundled_extension_if_needed` (Task 2).
- Produces: nothing further - this is the plan's own final task.

- [ ] **Step 1: Add the extension-install-path trigger**

`snap.yml`'s own current, real "Trigger the app's real first-run extension-install path" step
(read directly, reproduced below with the Snap-specific parts translated to Flatpak's own real
mechanism per this plan's Task 1/2 work - Flatpak's `--filesystem=...:create` needs no
`$SNAP_REAL_HOME`-style env-var resolution, and no `snap run --shell` wrapper - `flatpak run
--command=python3` is the direct equivalent):

```yaml
      - name: Trigger the app's real first-run extension-install path
        run: |
          # Deliberately the real production code path
          # (install_bundled_extension_if_needed, via
          # _install_bundled_extensions_for_sandboxed_channel), not a
          # CI-only stand-in - matching apt.yml/snap.yml's own established
          # pattern. Flatpak's --filesystem=...:create grant is
          # install-time (confirmed live, BACKLOG #187) - no
          # $SNAP_REAL_HOME-style env resolution needed, plain $HOME
          # already resolves correctly inside confinement.
          mkdir -p "$HOME/.local/share/gnome-shell/extensions"
          cat > "$HOME/.local/share/gnome-shell/extensions/install_check.py" << 'PYEOF'
          from orcshot.channel_detect import install_bundled_extension_if_needed
          from pathlib import Path
          bundled = Path("/app/share/orcshot/gnome-shell-extensions/orcshot-tray@orcshot.org")
          dest_parent = Path.home() / ".local" / "share" / "gnome-shell" / "extensions"
          ok = install_bundled_extension_if_needed("orcshot-tray@orcshot.org", bundled, dest_parent)
          print(f"install_bundled_extension_if_needed -> {ok}")
          assert ok, "extension install failed even with the filesystem grant in place"
          PYEOF
          flatpak run --command=python3 org.orcshot.Orcshot "$HOME/.local/share/gnome-shell/extensions/install_check.py"
```

**Verify this file path is actually readable from inside confinement before trusting it** - Snap's
own equivalent step needed a real, live-discovered workaround (writing the check script inside the
one AppArmor-granted directory, since `/tmp` is a confined-empty per-snap mount and bare `$HOME`
outside the granted path is `EACCES`). Flatpak's `--filesystem=` grant may have different, possibly
simpler, bind-mount semantics - confirm live via the real CI run rather than assuming this exact
placement transfers unchanged. If it doesn't work as written, root-cause it the same way Snap's own
task did (systematic-debugging skill, not a guess) and record what's actually true for Flatpak here.

- [ ] **Step 2: Add gnome-shell + headless-launch steps**

`snap.yml`'s own current, real, already-hardened steps (read directly, reproduced verbatim except
for the s/snap/flatpak/ header text - the mechanism itself, bounded waits on real log lines, is
unchanged since it doesn't depend on which sandbox technology is involved):

```yaml
      - name: Install gnome-shell and headless deps
        run: |
          sudo apt-get update -qq
          sudo apt-get install -y gnome-shell dbus-x11

      - name: Start a real systemd --user session bus
        run: |
          sudo systemctl start user@$(id -u).service
          timeout 30 bash -c 'until [ -S "/run/user/$(id -u)/bus" ]; do sleep 0.5; done' \
            || { echo "systemd --user session bus never appeared"; exit 1; }

      - name: Launch gnome-shell headless
        run: |
          export XDG_RUNTIME_DIR=/run/user/$(id -u)
          export DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/$(id -u)/bus
          nohup gnome-shell --headless --virtual-monitor 1024x768 > /tmp/shell.log 2>&1 &
          disown
          timeout 60 bash -c 'until grep -q "GNOME Shell started" /tmp/shell.log; do sleep 1; done' \
            || { echo "gnome-shell never logged its startup line"; cat /tmp/shell.log; exit 1; }
          pgrep -af gnome-shell || (echo "gnome-shell did not stay running" && cat /tmp/shell.log && exit 1)
```

Include the "Start a real systemd --user session bus" step here **only if Task 3's Step 2 found
`flatpak run` actually needs it** - if that step's live check showed `flatpak run` works fine
without it, this step becomes redundant scaffolding for a bug that doesn't exist here and should be
left out (ladder/lazy - don't carry a Snap-specific fix into a manifest that never needed it).

- [ ] **Step 3: Add the confined write + headless-load steps**

Order matters here exactly as it did for Snap - `enable_extension()`'s own write needs
`dconf-service` already reachable, which needs `gnome-shell` (and the session bus) already running,
which is why this step comes *after* "Launch gnome-shell headless", not before (Snap's own plan hit
this exact ordering bug live and fixed it - don't rediscover it):

```yaml
      - name: "Exercise Orcshot's own enable_extension() write, confined, and confirm it persists"
        run: |
          export XDG_RUNTIME_DIR=/run/user/$(id -u)
          export DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/$(id -u)/bus
          flatpak run --command=python3 org.orcshot.Orcshot -c "
          from orcshot.hotkey_setup import GioSettingsBackend
          from orcshot.gnome_extension_setup import enable_extension, TRAY_EXTENSION_UUID
          enable_extension(GioSettingsBackend(), TRAY_EXTENSION_UUID)
          "
          flatpak run --command=python3 org.orcshot.Orcshot -c "
          from orcshot.hotkey_setup import GioSettingsBackend
          current = GioSettingsBackend().get_strv('org.gnome.shell', '/', 'enabled-extensions')
          print('enabled-extensions ->', current)
          assert 'orcshot-tray@orcshot.org' in current, 'enable_extension write did not persist'
          "

      - name: "Confirm the already-running Shell loads the extension from that write alone"
        run: |
          timeout 60 bash -c 'until grep -q "orcshot-tray-diag" /tmp/shell.log; do sleep 1; done' \
            || { echo "extension never logged its diagnostic line - did not load"; cat /tmp/shell.log; exit 1; }
          if grep -qi "JS ERROR\|Gjs-CRITICAL" /tmp/shell.log; then
            echo "A real JS error was logged - see the log below"
            cat /tmp/shell.log
            exit 1
          fi
          echo "Extension loaded from the persisted write alone, no JS errors logged"

      - name: Always upload the shell log for diagnosis
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: shell-log
          path: /tmp/shell.log
```

**Note the one deliberate difference from `snap.yml`'s own version of this step**: Snap's plan
found `enable_extension_live()` (the direct D-Bus call that activates *this session* immediately)
AppArmor-blocked, and confirmed the persisted-write-alone path works instead (BACKLOG #192).
Whether Flatpak's own `bwrap`-based confinement blocks that same D-Bus call, or whether the persist
-only path is needed here too, wasn't tested this session - **use the persist-only check above
either way** (it's already proven sufficient for Snap and is the more conservative, always-correct
test), but if there's time and interest, calling `enable_extension_live()` too and seeing what
actually happens under Flatpak is a genuinely open, real question worth a BACKLOG entry if left
unexplored rather than silently assumed to behave like Snap.

- [ ] **Step 4: Push, open the PR, watch it run for real**

```bash
git push -u origin <branch-name>
gh pr create --repo artificialorctelligence/orcshot --base main --title "..." --body "..."
```

Confirm both `flatpak / build` and `flatpak / verify` pass for real before considering this task
done - this plan's own final review happens on the whole branch, but each task should already be
green before moving to the next.

- [ ] **Step 5: Commit**

```bash
git add .github/workflows/flatpak.yml
git commit -m "Add the extension-install + headless-Shell hard tier to flatpak CI verify"
```
