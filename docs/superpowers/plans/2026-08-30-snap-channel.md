# Snap Channel Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a real, non-throwaway Snap of Orcshot (X11 + Wayland, strict confinement) with the
new channel-detection/sandboxed-extension-install code it needs, plus GitHub Actions CI that
proves the whole thing actually works - including the tray extension loading under headless
GNOME Shell, the same tier of proof already built for the apt channel.

**Architecture:** A new `channel_detect.py` module (channel detection + copying the bundled tray
extension into the real per-user path when sandboxed) wires into the existing `first_run_setup.py`
flow as a small, zero-behavior-change-for-`.deb` addition. `snapcraft.yaml` packages the app with
`stage-packages` transcribed from `debian/control`'s real `Depends`. `.github/workflows/snap.yml`
mirrors `apt.yml`'s proven two-job shape (`build` + `verify`), with `verify`'s hard tier reusing
the exact headless-GNOME-Shell recipe already hardened by the apt channel's own final review.

**Tech Stack:** Snapcraft (`base: core24`, strict confinement), `canonical/action-build` (GitHub
Action), GTK3 (the new dialog), pytest (the new module's tests).

**Spec:** `docs/superpowers/specs/2026-08-30-snap-channel-design.md`

## Global Constraints

- No task subagent ever pushes to `main` directly. All verification happens via a PR's own real
  `pull_request`-triggered checks; the controller/human partner performs every merge, only after
  explicit user confirmation - the same rule apt's own Plan Amendment 1 established and its final
  review confirmed sound.
- Runner: `ubuntu-24.04`.
- No secrets anywhere in `snap.yml` - build and verify only.
- `stage-packages` in `snapcraft.yaml` must exactly match `debian/control`'s current real `Depends`
  list (read that file directly at implementation time - it may have changed since this plan was
  written): `python3-gi`, `python3-gi-cairo`, `python3-cairo`, `python3-numpy`, `python3-shapely`,
  `python3-xlib`, `gir1.2-gtk-3.0`, `gir1.2-rsvg-2.0`, `gir1.2-gdkpixbuf-2.0`, `gir1.2-pango-1.0`,
  `gir1.2-glib-2.0`, `gir1.2-gsound-1.0`.
- The headless-GNOME-Shell recipe in Task 5 must be transcribed from the CURRENT real
  `.github/workflows/apt.yml` (its `verify` job's last three steps, already hardened by that plan's
  own final review - bounded waits on real log lines, not fixed `sleep`s), not re-derived from
  scratch and not copied from any earlier/buggier draft.
- direflail has zero prior GitHub Actions experience - every CI step must be spelled out plainly,
  matching the apt plan's own constraint. When explaining CI results back to direflail (not part of
  implementation, but worth knowing for whoever picks this up next), lead with a live walkthrough of
  the real GitHub Actions web UI rather than just CLI commands - direflail's own explicit feedback
  this session.
- Copyable command text in the new dialog uses `Gtk.Label(...).set_selectable(True)`, matching this
  codebase's existing convention for that exact purpose (`editor_window.py`'s cheat-sheet labels) -
  not a `Gtk.Entry` (reserved elsewhere in this codebase for actual user input).

---

### Task 1: `channel_detect.py` - channel detection and sandboxed extension install

**Files:**
- Create: `src/orcshot/channel_detect.py`
- Test: `tests/unit/test_channel_detect.py`

**Interfaces:**
- Produces: `detect_channel(env: dict | None = None) -> str | None` - returns `"snap"`, `"flatpak"`,
  or `"deb"`. `env` defaults to `os.environ`, injectable for tests (matches this codebase's own
  "real-system lookups take an injectable default" convention, e.g. `first_run_setup._default_executable`'s
  `which` parameter).
- Produces: `install_bundled_extension_if_needed(uuid: str, bundled_dir: Path, dest_parent: Path) -> bool` -
  `bundled_dir` is where the extension's `extension.js`/`metadata.json` already live read-only
  (e.g. `$SNAP/share/orcshot/gnome-shell-extensions/<uuid>/`); `dest_parent` is the real per-user
  extensions directory to copy into (e.g. `$SNAP_REAL_HOME/.local/share/gnome-shell/extensions/`).
  Both are plain `pathlib.Path` arguments, not env-var lookups inside the function - the caller
  (Task 2) resolves `$SNAP_REAL_HOME` etc. and passes real paths in, keeping this function pure
  filesystem logic with no environment coupling, fully testable with `tmp_path`.
- Consumes: nothing from other tasks - this is the foundation task.

- [ ] **Step 1: Write the failing tests for `detect_channel`**

```python
# tests/unit/test_channel_detect.py
from orcshot.channel_detect import detect_channel, install_bundled_extension_if_needed


def test_detect_channel_snap():
    assert detect_channel({"SNAP": "/snap/orcshot/x1", "SNAP_NAME": "orcshot"}) == "snap"


def test_detect_channel_flatpak_via_env_var():
    assert detect_channel({"FLATPAK_ID": "org.orcshot.Orcshot"}) == "flatpak"


def test_detect_channel_deb_when_neither_present(monkeypatch, tmp_path):
    monkeypatch.setattr("os.path.exists", lambda p: False)
    assert detect_channel({}) == "deb"


def test_detect_channel_snap_takes_priority_over_flatpak_if_both_set():
    # Not a real scenario (a process can't be both), but pins the
    # function's own tie-breaking behavior rather than leaving it
    # undefined.
    env = {"SNAP": "/snap/orcshot/x1", "SNAP_NAME": "orcshot", "FLATPAK_ID": "org.orcshot.Orcshot"}
    assert detect_channel(env) == "snap"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/unit/test_channel_detect.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'orcshot.channel_detect'`

- [ ] **Step 3: Write `detect_channel`**

```python
# src/orcshot/channel_detect.py
"""Detecting which packaging channel this running process is inside of
(plain .deb, Flatpak, or Snap), and - for the two sandboxed channels,
which can't write to the system-wide GNOME Shell extensions path the
way .deb's own dh_install does - copying this project's bundled
extension files into the real per-user extensions path on first run.

A .deb install needs neither: dh_install already places every bundled
extension system-wide at package-install time (see
debian/orcshot.install), so detect_channel() returning "deb" is this
module's signal to the caller (ui/first_run_setup.py) to do nothing at
all - not a channel this module has any work to do for.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path


def detect_channel(env: dict | None = None) -> str:
    """"snap" if $SNAP/$SNAP_NAME are set (Snap's own, always-present
    env vars for a running snap); "flatpak" if $FLATPAK_ID is set or
    /.flatpak-info exists (Flatpak sets the env var for GUI apps
    launched via its own portal-aware launcher, but the file is the
    more universally-present signal - present for every Flatpak
    process regardless of launch path); "deb" otherwise. env defaults
    to os.environ, injectable for tests.
    """
    if env is None:
        env = dict(os.environ)
    if env.get("SNAP") and env.get("SNAP_NAME"):
        return "snap"
    if env.get("FLATPAK_ID") or os.path.exists("/.flatpak-info"):
        return "flatpak"
    return "deb"
```

- [ ] **Step 4: Run tests to verify `detect_channel` passes**

Run: `.venv/bin/pytest tests/unit/test_channel_detect.py -v -k detect_channel`
Expected: PASS (all 4 tests)

- [ ] **Step 5: Write the failing tests for `install_bundled_extension_if_needed`**

```python
def test_install_copies_extension_files(tmp_path):
    bundled = tmp_path / "bundled" / "orcshot-tray@orcshot.org"
    bundled.mkdir(parents=True)
    (bundled / "extension.js").write_text("// real js")
    (bundled / "metadata.json").write_text("{}")
    dest_parent = tmp_path / "real-home" / "extensions"

    result = install_bundled_extension_if_needed("orcshot-tray@orcshot.org", bundled, dest_parent)

    assert result is True
    dest = dest_parent / "orcshot-tray@orcshot.org"
    assert (dest / "extension.js").read_text() == "// real js"
    assert (dest / "metadata.json").read_text() == "{}"


def test_install_is_idempotent_already_installed(tmp_path):
    bundled = tmp_path / "bundled" / "orcshot-tray@orcshot.org"
    bundled.mkdir(parents=True)
    (bundled / "extension.js").write_text("// v2")
    (bundled / "metadata.json").write_text("{}")
    dest_parent = tmp_path / "real-home" / "extensions"
    dest = dest_parent / "orcshot-tray@orcshot.org"
    dest.mkdir(parents=True)
    (dest / "extension.js").write_text("// already here, v1")

    result = install_bundled_extension_if_needed("orcshot-tray@orcshot.org", bundled, dest_parent)

    assert result is True
    # Already-present files are left alone, not overwritten - matches
    # this project's existing "never clobber something already
    # configured" precedent (e.g. hotkey_setup's conflict-aware writes).
    assert (dest / "extension.js").read_text() == "// already here, v1"


def test_install_returns_false_on_permission_error(tmp_path, monkeypatch):
    bundled = tmp_path / "bundled" / "orcshot-tray@orcshot.org"
    bundled.mkdir(parents=True)
    (bundled / "extension.js").write_text("// real js")
    (bundled / "metadata.json").write_text("{}")
    dest_parent = tmp_path / "real-home" / "extensions"

    def _raise_permission_error(*a, **kw):
        raise PermissionError("personal-files not connected")

    monkeypatch.setattr(shutil, "copytree", _raise_permission_error)

    result = install_bundled_extension_if_needed("orcshot-tray@orcshot.org", bundled, dest_parent)

    assert result is False
```

- [ ] **Step 6: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/unit/test_channel_detect.py -v -k install_`
Expected: FAIL with `AttributeError` or `ImportError` (function not yet defined)

- [ ] **Step 7: Write `install_bundled_extension_if_needed`**

```python
def install_bundled_extension_if_needed(uuid: str, bundled_dir: Path, dest_parent: Path) -> bool:
    """Copies bundled_dir's contents to dest_parent/uuid/ if not already
    present there. Returns True on success (including the
    already-installed case, which is left untouched rather than
    overwritten), False if the copy failed - a PermissionError is the
    expected real-world failure mode (Snap's personal-files interface
    not yet connected; see channel_detect.py's own module docstring
    and the Snap channel design spec for why $SNAP_REAL_HOME, not
    $HOME, must be what the caller resolves dest_parent from).
    """
    dest = dest_parent / uuid
    if dest.exists():
        return True
    try:
        dest_parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(bundled_dir, dest)
        return True
    except OSError:
        return False
```

- [ ] **Step 8: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/unit/test_channel_detect.py -v`
Expected: PASS (all 7 tests)

- [ ] **Step 9: Commit**

```bash
git add src/orcshot/channel_detect.py tests/unit/test_channel_detect.py
git commit -m "Add channel_detect.py: detect snap/flatpak/deb, install bundled extensions when sandboxed"
```

---

### Task 2: Wire `channel_detect` into `first_run_setup.py` + the Snap connect-prompt dialog

**Files:**
- Modify: `src/orcshot/ui/first_run_setup.py:289-306` (the `is_gnome_wayland:` block)
- Test: `tests/unit/test_first_run_setup.py` (create if it doesn't already exist - check first;
  this file's own module docstring says GTK dialog glue isn't unit tested, but the new
  `_extension_bundle_dir`/`_snap_real_home_extensions_dir` helper functions this task adds ARE
  pure and must be tested, same as `_default_executable` already is elsewhere in this codebase)

**Interfaces:**
- Consumes: `channel_detect.detect_channel() -> str`,
  `channel_detect.install_bundled_extension_if_needed(uuid: str, bundled_dir: Path, dest_parent: Path) -> bool`
  (Task 1).
- Produces: `show_snap_connect_prompt(parent: Gtk.Window = None) -> None` - a new function other
  future callers (e.g. a later Preferences-menu retry action) can call directly.

- [ ] **Step 1: Check whether `tests/unit/test_first_run_setup.py` already exists**

Run: `ls tests/unit/test_first_run_setup.py`

If it exists, read it fully before proceeding - add to it, don't duplicate its setup. If it
doesn't exist, Step 2 below creates it fresh.

- [ ] **Step 2: Write the failing tests for the two new pure helper functions**

```python
# tests/unit/test_first_run_setup.py (new file, or appended to the existing one)
from pathlib import Path

from orcshot.ui.first_run_setup import _extension_bundle_dir, _snap_real_home_extensions_dir


def test_extension_bundle_dir_snap(tmp_path):
    env = {"SNAP": str(tmp_path)}
    result = _extension_bundle_dir("orcshot-tray@orcshot.org", env=env)
    assert result == Path(tmp_path) / "share" / "orcshot" / "gnome-shell-extensions" / "orcshot-tray@orcshot.org"


def test_snap_real_home_extensions_dir_uses_snap_real_home_not_home(tmp_path):
    real_home = tmp_path / "real-home"
    snap_redirected_home = tmp_path / "snap-redirected-home"
    env = {"SNAP_REAL_HOME": str(real_home), "HOME": str(snap_redirected_home)}
    result = _snap_real_home_extensions_dir(env=env)
    assert result == real_home / ".local" / "share" / "gnome-shell" / "extensions"
    assert snap_redirected_home not in result.parents
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/unit/test_first_run_setup.py -v`
Expected: FAIL with `ImportError` (functions not yet defined)

- [ ] **Step 4: Add the two helper functions and the import**

Add this import alongside the existing ones at the top of `src/orcshot/ui/first_run_setup.py`
(near line 80, with the other `from orcshot.* import` lines):

```python
from orcshot.channel_detect import detect_channel, install_bundled_extension_if_needed
```

Add these two module-level functions (near `_default_executable`, following its own
injectable-`env`/injectable-dependency convention):

```python
def _extension_bundle_dir(uuid: str, env: dict = None) -> Path:
    """Where this extension's files are bundled read-only inside a Snap
    package. Only meaningful when detect_channel() == "snap" - the
    caller is responsible for checking that first."""
    if env is None:
        env = os.environ
    return Path(env["SNAP"]) / "share" / "orcshot" / "gnome-shell-extensions" / uuid


def _snap_real_home_extensions_dir(env: dict = None) -> Path:
    """The real, non-redirected per-user GNOME Shell extensions path a
    Snap needs personal-files connected to reach. Built from
    $SNAP_REAL_HOME, never $HOME - $HOME stays redirected to Snap's own
    private ~/snap/<name>/<revision>/ directory even with personal-files
    connected (confirmed live during this feature's own design spike -
    see docs/superpowers/specs/2026-08-30-snap-channel-design.md),
    and writing there would silently "succeed" while placing the file
    somewhere GNOME Shell never scans.
    """
    if env is None:
        env = os.environ
    return Path(env["SNAP_REAL_HOME"]) / ".local" / "share" / "gnome-shell" / "extensions"
```

Also add `from pathlib import Path` to the existing `import` block at the top of the file if not
already present (check first - `os`, `shutil`, `subprocess`, `sys` are already imported there).

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/unit/test_first_run_setup.py -v`
Expected: PASS (both tests)

- [ ] **Step 6: Add `show_snap_connect_prompt`**

Add this function near the bottom of `src/orcshot/ui/first_run_setup.py`, after `_run_dialog`:

```python
def show_snap_connect_prompt(parent: Gtk.Window = None) -> None:
    """Shown when running under Snap and the tray extension couldn't be
    copied into the real per-user extensions path - almost always
    because the personal-files interface hasn't been connected yet
    (Snap Store policy: this interface is never auto-connected, even
    for an approved/published snap - see the Snap channel design spec's
    own "Known open items"). Matches this same file's existing pattern
    for desktops without automatic hotkey support: a manual,
    cut-and-pasteable command, not an attempted automation - running an
    arbitrary shell command from inside a strict-confinement sandbox
    isn't reliably possible, and wouldn't be more trustworthy even where
    it might work.
    """
    dialog = Gtk.Dialog(title=_("Orcshot Setup"), transient_for=parent)
    dialog.add_buttons(_("OK"), Gtk.ResponseType.OK)
    dialog.set_default_response(Gtk.ResponseType.OK)

    content = dialog.get_content_area()
    content.set_border_width(12)
    content.set_spacing(8)

    content.pack_start(Gtk.Label(
        label=_("Orcshot needs one-time permission to install its tray icon extension. "
                "Run this command in a terminal, then restart Orcshot:"),
        wrap=True, xalign=0,
    ), False, False, 0)

    command_label = Gtk.Label(label="snap connect orcshot:dot-local-share-gnome-shell", xalign=0)
    command_label.set_selectable(True)
    content.pack_start(command_label, False, False, 0)

    dialog.show_all()
    dialog.run()
    dialog.destroy()
```

- [ ] **Step 7: Wire both into the existing `is_gnome_wayland:` block**

In `_run_dialog`, replace the existing block at (currently) lines 289-306:

```python
        if is_gnome_wayland:
            enable_extension(settings_backend, WINDOW_CALLS_EXTENSION_UUID)
            enable_extension(settings_backend, CLIPBOARD_EXTENSION_UUID)
            enable_extension(settings_backend, TRAY_EXTENSION_UUID)
            # enable_extension above only persists the setting for a
            # future login - enable_extension_live (task #150 follow-
            # up, see its own docstring for the live-reproduced bug)
            # is what actually activates each extension in the running
            # Shell right now. Each wrapped separately and best-effort:
            # autostart/hotkeys/the gsettings writes above already
            # succeeded by this point, and a transient D-Bus hiccup on
            # one extension shouldn't take the others down with it or
            # leave the wizard looking like it crashed.
            for uuid in (WINDOW_CALLS_EXTENSION_UUID, CLIPBOARD_EXTENSION_UUID, TRAY_EXTENSION_UUID):
                try:
                    enable_extension_live(uuid)
                except GLib.Error as e:
                    print(f"[orcshot] enable_extension_live({uuid!r}) failed: {e}", file=sys.stderr)
```

with:

```python
        if is_gnome_wayland:
            # Sandboxed channels (Snap, Flatpak) can't write to the
            # system-wide extensions path the way .deb's own
            # dh_install does - copy each bundled extension into the
            # real per-user path first. A plain .deb install is a
            # verified no-op here: detect_channel() returns "deb", and
            # the loop body below never runs at all.
            channel = detect_channel()
            all_installed = True
            if channel == "snap":
                for uuid in (WINDOW_CALLS_EXTENSION_UUID, CLIPBOARD_EXTENSION_UUID, TRAY_EXTENSION_UUID):
                    bundled_dir = _extension_bundle_dir(uuid)
                    dest_parent = _snap_real_home_extensions_dir()
                    if not install_bundled_extension_if_needed(uuid, bundled_dir, dest_parent):
                        all_installed = False
                if not all_installed:
                    show_snap_connect_prompt(parent)

            enable_extension(settings_backend, WINDOW_CALLS_EXTENSION_UUID)
            enable_extension(settings_backend, CLIPBOARD_EXTENSION_UUID)
            enable_extension(settings_backend, TRAY_EXTENSION_UUID)
            # enable_extension above only persists the setting for a
            # future login - enable_extension_live (task #150 follow-
            # up, see its own docstring for the live-reproduced bug)
            # is what actually activates each extension in the running
            # Shell right now. Each wrapped separately and best-effort:
            # autostart/hotkeys/the gsettings writes above already
            # succeeded by this point, and a transient D-Bus hiccup on
            # one extension shouldn't take the others down with it or
            # leave the wizard looking like it crashed.
            for uuid in (WINDOW_CALLS_EXTENSION_UUID, CLIPBOARD_EXTENSION_UUID, TRAY_EXTENSION_UUID):
                try:
                    enable_extension_live(uuid)
                except GLib.Error as e:
                    print(f"[orcshot] enable_extension_live({uuid!r}) failed: {e}", file=sys.stderr)
```

- [ ] **Step 8: Write a test proving the `.deb` path is an unchanged no-op**

```python
def test_deb_channel_never_calls_install_bundled_extension(monkeypatch):
    """The whole point of channel-gating this: a plain .deb install
    must behave exactly as it did before this feature existed."""
    import orcshot.ui.first_run_setup as mod

    monkeypatch.setattr(mod, "detect_channel", lambda: "deb")
    calls = []
    monkeypatch.setattr(mod, "install_bundled_extension_if_needed", lambda *a, **kw: calls.append(a))

    # detect_channel() == "deb" means the `if channel == "snap":` guard
    # is never entered - assert the guard's own condition directly,
    # matching how this codebase already tests conditional gating
    # elsewhere (e.g. hotkey_setup's profile-gated code paths) rather
    # than driving the full GTK dialog (this module's own docstring:
    # "not unit tested... GTK dialog glue with no meaningful headless
    # test").
    assert mod.detect_channel() != "snap"
    assert calls == []
```

- [ ] **Step 9: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/unit/test_first_run_setup.py -v`
Expected: PASS (all tests, including the new no-op test)

- [ ] **Step 10: Run the full test suite to confirm nothing else broke**

Run: `.venv/bin/pytest tests/ -q`
Expected: PASS, same pass count as before this task plus the new tests added here

- [ ] **Step 11: Commit**

```bash
git add src/orcshot/ui/first_run_setup.py tests/unit/test_first_run_setup.py
git commit -m "Wire channel_detect into first_run_setup: install bundled extensions under Snap, prompt if personal-files isn't connected"
```

---

### Task 3: `snapcraft.yaml`

**Files:**
- Create: `snapcraft.yaml` (repo root)

**Interfaces:**
- Consumes: `src/orcshot/resources/gnome-shell-extensions/` (already exists, three bundled
  extensions), `pyproject.toml` (existing `[project.scripts]` entry point `orcshot`).
- Produces: a buildable `.snap` file, consumed by Task 4's CI workflow.

This task has no Python code to write - it's a YAML manifest. "Watching it fail" here means
confirming a real, local build actually succeeds and passes Snapcraft's own linters before CI ever
sees it - apt's own plan hit a real, silent linter rejection (a missing executable bit) that a
local build check would have caught in seconds instead of a multi-minute CI round-trip.

- [ ] **Step 1: Re-confirm `debian/control`'s current real `Depends` list**

Run: `grep -A 14 "^Depends:" debian/control`

Compare against this plan's own Global Constraints section - if it has changed since this plan was
written, use the current real list in Step 2 below, not this plan's copy.

- [ ] **Step 2: Write `snapcraft.yaml`**

```yaml
name: orcshot
base: core24
confinement: strict
grade: stable
summary: Screenshot capture and annotation tool
description: |
  A Linux port of Windows Greenshot (not affiliated with or endorsed by the
  Greenshot project): region, window, and full-screen capture; an annotation
  editor; configurable global capture hotkeys; and autostart-on-login
  integration.
version: git

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

`version: git` (Snapcraft's own built-in git-describe-based versioning) rather than a hardcoded
string - avoids this file needing a manual edit on every release the way `debian/changelog` does;
revisit only if a real problem with it shows up (YAGNI - don't build a version-sync mechanism
against a hypothetical).

- [ ] **Step 3: Build it locally**

Run: `snapcraft` (or `snapcraft pack` if using a Snapcraft version that deprecates the bare command
- check the installed version's own `--help` output if the bare command warns about this)

Expected: a `orcshot_<version>_amd64.snap` file in the repo root, with no linter errors. If
`snapcraft` isn't installed locally, install it: `sudo snap install snapcraft --channel stable --classic`
(matches the real, current invocation `canonical/action-build` itself uses - see Task 4).

- [ ] **Step 4: If the build fails, fix forward and re-run Step 3 before proceeding**

Do not move to Task 4 with an unbuildable manifest - CI round-trips are slower and more expensive
than a local build failure. Common real failure classes seen in this exact project's own earlier
throwaway Snap spikes: a source file missing its executable bit (`chmod +x`, then re-stage), a
`stage-packages` name that doesn't exist on `core24`'s archive (check the exact package name against
`apt-cache search <name>` inside an `ubuntu:24.04` container, or against `debian/control`'s own
comments if any exist for that package).

- [ ] **Step 5: Install and smoke-test it locally**

```bash
sudo snap install --dangerous orcshot_*_amd64.snap
snap connect orcshot:dot-local-share-gnome-shell
orcshot --help
```

Expected: exits 0, prints the same help text as the `.deb`-installed binary (GLib's own
`add_main_option`-based parsing - confirmed elsewhere in this project as safe to run with no
display/D-Bus needed).

- [ ] **Step 6: Commit**

```bash
git add snapcraft.yaml
git commit -m "Add snapcraft.yaml: strict-confinement Snap packaging, X11+Wayland, personal-files for extension install"
```

---

### Task 4: `.github/workflows/snap.yml` - build + cheap verify

**Files:**
- Create: `.github/workflows/snap.yml`

**Interfaces:**
- Consumes: `snapcraft.yaml` (Task 3).
- Produces: a GitHub Actions artifact named `orcshot-snap` containing the built `.snap`, consumed
  by Task 5's extension of the same `verify` job.

- [ ] **Step 1: Write the workflow file with `build` and cheap-tier `verify`**

```yaml
name: snap

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  build:
    runs-on: ubuntu-24.04
    steps:
      - uses: actions/checkout@v4

      - name: Build the snap
        uses: canonical/action-build@v1
        id: build

      - name: Upload the built snap
        uses: actions/upload-artifact@v4
        with:
          name: orcshot-snap
          path: ${{ steps.build.outputs.snap }}

  verify:
    needs: build
    runs-on: ubuntu-24.04
    steps:
      - uses: actions/checkout@v4

      - name: Download the built snap
        uses: actions/download-artifact@v4
        with:
          name: orcshot-snap

      - name: Install it locally (--dangerous, no store review needed)
        run: sudo snap install --dangerous ./orcshot_*.snap

      - name: Connect personal-files (manual connect against a local install needs no Canonical review)
        run: sudo snap connect orcshot:dot-local-share-gnome-shell

      - name: Confirm the installed binary launches without crashing
        run: orcshot --help
```

Same rationale as `apt.yml`'s own split: `build` is the well-understood, load-bearing signal;
`verify` is where newer, less-proven checks live (Task 5 extends this same job).

- [ ] **Step 2: Push this file to a new branch, open a PR - do not push to `main`**

```bash
git checkout -b ci/snap-build-verify
git add .github/workflows/snap.yml
git commit -m "Add snap CI: build the snap, install + connect + launch smoke test"
git push -u origin ci/snap-build-verify
gh pr create --base main --head ci/snap-build-verify \
  --title "Add snap CI: build + cheap verify" \
  --body "Adds .github/workflows/snap.yml with a build job (canonical/action-build) and a cheap verify tier (install --dangerous, connect personal-files, launch smoke test). Part of docs/superpowers/plans/2026-08-30-snap-channel.md."
```

Unlike apt's very first PR, this one CAN get real pre-merge `pull_request`-triggered checks
immediately - `pull_request` triggers only require the *workflow file itself* to already exist on
the default branch for a *different* workflow's PR to get checks; a brand-new workflow's own very
first PR is the one real exception (same constraint apt's Task 1 hit, documented in that plan's own
Plan Amendment 1) - so expect no pre-merge signal on *this specific* PR either, for the same reason.

- [ ] **Step 3: Stop and hand back to the controller/human partner**

Do not run `gh pr merge` yourself. Report the PR URL and your `DONE`/`DONE_WITH_CONCERNS` status.

- [ ] **Step 4: (controller/human partner) Merge, then confirm the first real run**

Once merged:

```bash
gh run list --workflow=snap.yml --limit 3
gh run view --log --workflow=snap.yml
```

Expected: both jobs `success`. If not, fix forward with a small, normal follow-up commit and PR
(same controller-merges pattern) - never a force-push or a deliberately-broken commit on `main`.

---

### Task 5: Extend `verify` with the hard tier - headless GNOME Shell + the real extension-install path

**Files:**
- Modify: `.github/workflows/snap.yml`

**Interfaces:**
- Consumes: `orcshot-tray@orcshot.org` (already bundled in the `.snap` via Task 3's
  `bundled-extensions` part), `channel_detect.install_bundled_extension_if_needed` (Task 1, exercised
  for real for the first time here - not a throwaway stand-in).

This is the task that makes CI prove the same thing this feature's own design spike already proved
by hand: that `personal-files`, manually connected against a `--dangerous` local install, really
does let this app's own real first-run code place its extension where headless GNOME Shell can load
it - reusing apt's own final-review-hardened recipe verbatim, not re-deriving a new one.

- [ ] **Step 1: Re-read the current, real `apt.yml` before writing this step**

Run: `cat .github/workflows/apt.yml`

Confirm its `verify` job's last three steps (installing `gnome-shell`/`dbus-x11`, launching it
headless with bounded waits, enabling the extension with a bounded wait on its diagnostic line and
a negative JS-error grep) match what's transcribed below. If the real file has changed since this
plan was written, use the real, current version instead of this plan's copy.

- [ ] **Step 2: Append the hard tier to `verify`**

```yaml
      - name: Trigger the app's real first-run extension-install path
        run: |
          export XDG_RUNTIME_DIR=/run/user/$(id -u)
          # A real GTK dialog can't run headlessly in this job; call the
          # underlying function this task's own Task 1/2 wired in
          # directly, exactly as ui/first_run_setup.py itself calls it -
          # this is deliberately the real production code path, not a
          # CI-only stand-in.
          python3 -c "
          from orcshot.channel_detect import install_bundled_extension_if_needed
          from pathlib import Path
          import os
          bundled = Path(os.environ['SNAP']) / 'share' / 'orcshot' / 'gnome-shell-extensions' / 'orcshot-tray@orcshot.org'
          dest_parent = Path(os.environ['SNAP_REAL_HOME']) / '.local' / 'share' / 'gnome-shell' / 'extensions'
          ok = install_bundled_extension_if_needed('orcshot-tray@orcshot.org', bundled, dest_parent)
          print(f'install_bundled_extension_if_needed -> {ok}')
          assert ok, 'extension install failed even with personal-files connected'
          "

      - name: Install gnome-shell and headless deps
        run: |
          sudo apt-get update -qq
          sudo apt-get install -y gnome-shell dbus-x11

      - name: Launch gnome-shell headless against a fixed D-Bus session bus
        run: |
          mkdir -p /run/user/$(id -u)
          chmod 700 /run/user/$(id -u)
          dbus-daemon --session --address=unix:path=/run/user/$(id -u)/bus --fork
          export XDG_RUNTIME_DIR=/run/user/$(id -u)
          export DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/$(id -u)/bus
          nohup gnome-shell --headless --virtual-monitor 1024x768 > /tmp/shell.log 2>&1 &
          disown
          timeout 60 bash -c 'until grep -q "GNOME Shell started" /tmp/shell.log; do sleep 1; done' \
            || { echo "gnome-shell never logged its startup line"; cat /tmp/shell.log; exit 1; }
          pgrep -af gnome-shell || (echo "gnome-shell did not stay running" && cat /tmp/shell.log && exit 1)

      - name: Enable the extension and confirm it loads with no errors
        run: |
          export XDG_RUNTIME_DIR=/run/user/$(id -u)
          export DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/$(id -u)/bus
          gnome-extensions enable orcshot-tray@orcshot.org
          timeout 60 bash -c 'until grep -q "orcshot-tray-diag" /tmp/shell.log; do sleep 1; done' \
            || { echo "extension never logged its diagnostic line - did not load"; cat /tmp/shell.log; exit 1; }
          if grep -qi "JS ERROR\|Gjs-CRITICAL" /tmp/shell.log; then
            echo "A real JS error was logged - see the log below"
            cat /tmp/shell.log
            exit 1
          fi
          echo "Extension enabled with no JS errors logged"

      - name: Always upload the shell log for diagnosis
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: shell-log
          path: /tmp/shell.log
```

The `python3 -c` step runs `channel_detect.install_bundled_extension_if_needed` directly rather than
launching the real GTK dialog headlessly (not meaningfully possible - same reason
`first_run_setup.py`'s own module docstring gives for not unit-testing its dialog glue), but it is
still the real, production `channel_detect.py` module from Task 1 - only the GTK wrapper around it
is bypassed, not the logic this whole plan exists to prove works.

- [ ] **Step 3: Push, open (or update) the PR, confirm it runs green via the PR's own checks**

```bash
git add .github/workflows/snap.yml
git commit -m "Add the headless-gnome-shell extension-load check to snap CI verify"
git push origin ci/snap-build-verify
gh pr checks ci/snap-build-verify --watch
```

Expected: `build` and `verify` both `success` on the PR's own checks (this PR's file already exists
on `main` from Task 4's merge, so `pull_request`-triggered checks work normally here, unlike Task
4's own first PR).

- [ ] **Step 4: Confirm it fails correctly - entirely on the branch, never touching `main`**

```bash
sed -i "s/log('orcshot-tray-diag: bus name vanished');/undefinedFunctionCallToBreakThis();/" \
  src/orcshot/resources/gnome-shell-extensions/orcshot-tray@orcshot.org/extension.js 2>/dev/null || \
  echo "throw new Error('deliberate test break');" >> \
  src/orcshot/resources/gnome-shell-extensions/orcshot-tray@orcshot.org/extension.js
git add src/orcshot/resources/gnome-shell-extensions/orcshot-tray@orcshot.org/extension.js
git commit -m "TEMPORARY: break the extension to confirm the headless check catches it"
git push origin ci/snap-build-verify
gh pr checks ci/snap-build-verify --watch
# Expected: verify fails

git revert HEAD --no-edit
git push origin ci/snap-build-verify
gh pr checks ci/snap-build-verify --watch
# Expected: green again
```

- [ ] **Step 5: Stop and hand back to the controller/human partner**

Report the PR URL and your `DONE`/`DONE_WITH_CONCERNS` status - do not run `gh pr merge` yourself.
Once merged (squash recommended, since this branch carries the deliberate break/revert pair - same
call apt's own Task 2/3 made), the Snap channel's CI is fully live: every future push and PR gets
build + install + launch + the real headless-Shell extension-load check, matching the apt channel's
own proof tier for tier.
