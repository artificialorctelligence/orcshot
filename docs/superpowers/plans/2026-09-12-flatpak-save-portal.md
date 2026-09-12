# Flatpak Save through the file-chooser portal — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Save (quick Save and every file dialog) actually write a file the user can find when Orcshot runs inside the Flatpak sandbox — BACKLOG #210, the blocker for the Flathub half of #198.

**Architecture:** Three independent pieces. (1) One `--filesystem=xdg-pictures:create` grant so the out-of-box default `~/Pictures/Screenshots` works with no dialog. (2) Every `Gtk.FileChooserDialog` becomes `Gtk.FileChooserNative`, which is the portal dialog when sandboxed and the plain GTK dialog otherwise — one code path for .deb/snap/Flatpak. (3) Quick Save checks that its target folder is not on the sandbox's own evaporating tmpfs (`st_dev` equals `/`'s) and, if it is, runs the existing folder picker once; the portal's document grant is persistent, so later Saves are silent.

**Tech Stack:** Python 3, PyGObject / GTK 3.24, xdg-desktop-portal FileChooser, flatpak-builder. Tests: pytest, `monkeypatch`, no GTK windows created in tests.

**Spec:** `docs/superpowers/specs/2026-09-12-flatpak-save-portal-design.md` — read it first; its "What was verified" section is the evidence for every design choice below.

## Global Constraints

- The `st_dev` test runs **only** when `detect_channel() == "flatpak"`; on a plain install `/home` may be its own filesystem and the comparison means nothing.
- No new dependencies. No new `--filesystem` grant other than `xdg-pictures:create`.
- apt/PPA behaviour must be unchanged: `Gtk.FileChooserNative` outside a sandbox is the ordinary GTK dialog.
- Every string shown to the user goes through `_()` (the i18n scan test enforces this).
- Commit after every task; never commit `BACKLOG.md` changes you did not make.
- Snap Save (#212) and external commands under Flatpak (#213) are **out of scope** — do not touch `snapcraft.yaml` or `external_commands.py` beyond the one dialog swap in Task 4.

---

### Task 1: `settings.output_directory_is_reachable`

**Files:**
- Modify: `src/orcshot/settings.py` (imports at top; new function after `set_output_directory`, ~line 141)
- Test: `tests/unit/test_settings.py`

**Interfaces:**
- Consumes: `orcshot.channel_detect.detect_channel() -> str` (existing).
- Produces: `output_directory_is_reachable(directory: Path) -> bool` — Task 2 calls it.

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_settings.py` (add `output_directory_is_reachable` to the existing `from orcshot.settings import (...)` block, and `import os` at the top if not present):

```python
class TestOutputDirectoryIsReachable:
    """BACKLOG #210: inside the Flatpak sandbox, $HOME is the sandbox's
    own tmpfs - writes succeed and evaporate. Anything on the same
    device as / is that tmpfs; real host mounts differ."""

    def test_true_outside_flatpak_whatever_the_path(self, tmp_path, monkeypatch):
        monkeypatch.setattr("orcshot.settings.detect_channel", lambda: "deb")
        assert output_directory_is_reachable(tmp_path / "Screenshots") is True

    def test_false_under_flatpak_when_on_the_sandbox_root_device(self, tmp_path, monkeypatch):
        monkeypatch.setattr("orcshot.settings.detect_channel", lambda: "flatpak")
        root_dev = os.stat("/").st_dev
        real_stat = os.stat

        def same_device_as_root(path, *args, **kwargs):
            result = real_stat(path, *args, **kwargs)
            if str(path) == str(tmp_path / "Screenshots"):
                return os.stat_result(result[:2] + (root_dev,) + result[3:])
            return result

        monkeypatch.setattr("orcshot.settings.os.stat", same_device_as_root)
        assert output_directory_is_reachable(tmp_path / "Screenshots") is False

    def test_true_under_flatpak_on_a_different_device(self, tmp_path, monkeypatch):
        monkeypatch.setattr("orcshot.settings.detect_channel", lambda: "flatpak")
        root_dev = os.stat("/").st_dev
        real_stat = os.stat

        def different_device(path, *args, **kwargs):
            result = real_stat(path, *args, **kwargs)
            if str(path) == str(tmp_path / "Screenshots"):
                return os.stat_result(result[:2] + (root_dev + 1,) + result[3:])
            return result

        monkeypatch.setattr("orcshot.settings.os.stat", different_device)
        assert output_directory_is_reachable(tmp_path / "Screenshots") is True

    def test_creates_the_directory_before_checking(self, tmp_path, monkeypatch):
        monkeypatch.setattr("orcshot.settings.detect_channel", lambda: "deb")
        target = tmp_path / "Pictures" / "Screenshots"
        output_directory_is_reachable(target)
        # "deb" returns early without touching disk; only the flatpak
        # branch mkdirs. Pin that: the sandbox test above depends on
        # the directory existing for os.stat.
        assert not target.exists()
        monkeypatch.setattr("orcshot.settings.detect_channel", lambda: "flatpak")
        output_directory_is_reachable(target)
        assert target.is_dir()
```

Note on the `st_dev` fakes: `os.stat_result` is a tuple subclass whose index 2 is `st_dev`; rebuilding it with one field swapped is the smallest honest fake. The function must call `os.stat` through the `os` module (`os.stat(...)`, not `from os import stat`) so the patch takes effect.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/unit/test_settings.py -k OutputDirectoryIsReachable -v`
Expected: 4 × FAIL / ERROR with `ImportError: cannot import name 'output_directory_is_reachable'`.

- [ ] **Step 3: Implement**

In `src/orcshot/settings.py`, add to the imports (after `from pathlib import Path`):

```python
from orcshot.channel_detect import detect_channel
```

(`channel_detect` imports only `os`; no cycle.) Then after `set_output_directory`:

```python
def output_directory_is_reachable(directory: Path) -> bool:
    """True unless we are inside the Flatpak sandbox and ``directory`` is
    on the sandbox's own tmpfs (BACKLOG #210). Inside the sandbox $HOME
    is a tmpfs: mkdir and the write both *succeed*, no error is raised,
    and the file is gone when the process exits - confirmed live in the
    installed Flatpak. Anything sharing /'s device number is that tmpfs;
    every real host mount (~/.var/app, /run/user/<uid>/doc, a granted
    xdg-pictures) has a different st_dev. Only meaningful under
    Flatpak - on a plain install /home may or may not be its own
    filesystem, so the comparison says nothing there and is skipped.
    """
    if detect_channel() != "flatpak":
        return True
    directory.mkdir(parents=True, exist_ok=True)
    return os.stat(directory).st_dev != os.stat("/").st_dev
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/unit/test_settings.py -v`
Expected: all PASS (the 4 new ones and every existing one).

- [ ] **Step 5: Commit**

```bash
git add src/orcshot/settings.py tests/unit/test_settings.py
git commit -m "settings: output_directory_is_reachable - detect the Flatpak sandbox's evaporating tmpfs (#210)

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 2: `ensure_output_directory` guards both quick-save paths

**Files:**
- Modify: `src/orcshot/ui/destination_picker.py` (imports ~lines 61-90; new function before `_quick_save`, ~line 165; `_quick_save` body ~line 178)
- Modify: `src/orcshot/ui/editor_window.py:1787` (`_do_quick_save`)
- Test: `tests/unit/ui/test_destination_picker.py`

**Interfaces:**
- Consumes: `output_directory_is_reachable(directory: Path) -> bool` (Task 1); `editor_window._choose_save_location(parent: Gtk.Window | None) -> None` (existing, module-level).
- Produces: `destination_picker.ensure_output_directory(parent: Gtk.Window | None = None) -> Path | None`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/ui/test_destination_picker.py` (add `from pathlib import Path` and `import logging` at the top; extend the existing `from orcshot.ui.destination_picker import ...` line with `ensure_output_directory`):

```python
class TestEnsureOutputDirectory:
    """BACKLOG #210: quick Save must never write into the Flatpak
    sandbox's evaporating tmpfs. Both quick-save paths (tray/picker and
    the editor menu) go through this one function."""

    def test_returns_the_directory_when_reachable_without_asking(self, tmp_path, monkeypatch):
        monkeypatch.setattr("orcshot.ui.destination_picker.get_output_directory", lambda: tmp_path)
        monkeypatch.setattr("orcshot.ui.destination_picker.output_directory_is_reachable", lambda d: True)
        asked = []
        monkeypatch.setattr("orcshot.ui.destination_picker._choose_location", lambda parent: asked.append(parent))

        assert ensure_output_directory(parent=None) == tmp_path
        assert asked == []

    def test_asks_once_and_returns_the_newly_chosen_directory(self, tmp_path, monkeypatch):
        chosen = tmp_path / "picked"
        current = {"dir": tmp_path / "tmpfs"}
        monkeypatch.setattr("orcshot.ui.destination_picker.get_output_directory", lambda: current["dir"])
        monkeypatch.setattr(
            "orcshot.ui.destination_picker.output_directory_is_reachable", lambda d: d == chosen,
        )

        def pick(parent):
            current["dir"] = chosen

        monkeypatch.setattr("orcshot.ui.destination_picker._choose_location", pick)

        assert ensure_output_directory(parent=None) == chosen

    def test_cancelled_picker_returns_none_and_warns(self, tmp_path, monkeypatch, caplog):
        monkeypatch.setattr("orcshot.ui.destination_picker.get_output_directory", lambda: tmp_path / "tmpfs")
        monkeypatch.setattr("orcshot.ui.destination_picker.output_directory_is_reachable", lambda d: False)
        monkeypatch.setattr("orcshot.ui.destination_picker._choose_location", lambda parent: None)

        with caplog.at_level(logging.WARNING, logger="orcshot.ui.destination_picker"):
            assert ensure_output_directory(parent=None) is None
        assert "no reachable" in caplog.text
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/unit/ui/test_destination_picker.py -k EnsureOutputDirectory -v`
Expected: ImportError on `ensure_output_directory`.

- [ ] **Step 3: Implement in `destination_picker.py`**

Add `import logging` to the stdlib imports and `_LOG = logging.getLogger(__name__)` after the imports (same convention as `ui/external_commands.py:71`). Add `output_directory_is_reachable` to the existing `from orcshot.settings import (...)` block. Then, immediately above `_quick_save`:

```python
def _choose_location(parent) -> None:
    # Lazy, like _open_editor's EditorWindow import above: editor_window
    # is the heavy module and destination_picker is imported first.
    from orcshot.ui.editor_window import _choose_save_location
    _choose_save_location(parent)


def ensure_output_directory(parent: Gtk.Window = None) -> Path | None:
    """The folder quick Save writes into, or None if there is none
    (BACKLOG #210). Under Flatpak the configured folder may sit on the
    sandbox's own tmpfs, where a write succeeds and evaporates; when it
    does, run the Screenshot Save Location picker once - through the
    portal, whose document grant is persistent - and re-check. Shared by
    this module's _quick_save and EditorWindow._do_quick_save so neither
    path can save into nothing.
    """
    directory = get_output_directory()
    if output_directory_is_reachable(directory):
        return directory
    _choose_location(parent)
    directory = get_output_directory()
    if output_directory_is_reachable(directory):
        return directory
    _LOG.warning("Save skipped: no reachable output directory was chosen")
    return None
```

Add `from pathlib import Path` to the imports if it is not already there. In `_quick_save`, replace

```python
    directory = get_output_directory()
    directory.mkdir(parents=True, exist_ok=True)
```

with

```python
    app = Gio.Application.get_default()
    directory = ensure_output_directory(app.topmost_editor() if app is not None else None)
    if directory is None:
        return
    directory.mkdir(parents=True, exist_ok=True)
```

(`app.topmost_editor()` is the same parent `_save_as` two functions below already uses.)

- [ ] **Step 4: Implement in `editor_window.py` `_do_quick_save`**

Replace `directory = get_output_directory()` (the line after the second `settings = get_output_settings()`) with:

```python
        from orcshot.ui.destination_picker import ensure_output_directory  # lazy: see _open_editor's mirror import there
        directory = ensure_output_directory(self)
        if directory is None:
            return
```

Leave `get_output_directory` imported — the dialogs and the preferences label still use it.

- [ ] **Step 5: Run the tests**

Run: `.venv/bin/python -m pytest tests/unit/ui/test_destination_picker.py tests/unit/test_settings.py -v`
Expected: all PASS.

- [ ] **Step 6: Smoke the editor path imports cleanly**

Run: `.venv/bin/python -c "import orcshot.ui.editor_window, orcshot.ui.destination_picker; print('ok')"`
Expected: `ok` (no circular-import error).

- [ ] **Step 7: Commit**

```bash
git add src/orcshot/ui/destination_picker.py src/orcshot/ui/editor_window.py tests/unit/ui/test_destination_picker.py
git commit -m "Quick Save: never write into the Flatpak sandbox tmpfs - pick a reachable folder once via the portal (#210)

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 3: Manifest grant

**Files:**
- Modify: `org.orcshot.Orcshot.yaml` (`finish-args`, after the `--talk-name=org.x.StatusIconMonitor.*` line)

- [ ] **Step 1: Add the grant**

Insert into `finish-args`:

```yaml
  # BACKLOG #210: the default output directory is ~/Pictures/Screenshots.
  # The same static grant Flameshot (xdg-pictures) and Kooha (xdg-videos)
  # ship on Flathub; :create so the folder can be made on first Save.
  # Any other folder the user picks goes through the FileChooser portal
  # (persistent document grant) - see settings.output_directory_is_reachable.
  - --filesystem=xdg-pictures:create
```

- [ ] **Step 2: Lint the manifest exactly as CI does**

Run (needs `org.flatpak.Builder` installed from flathub, which CI installs; install it once with `flatpak install -y flathub org.flatpak.Builder` if missing):

```bash
flatpak run --command=flatpak-builder-lint org.flatpak.Builder --exceptions --user-exceptions flathub-lint-exceptions.json manifest org.orcshot.Orcshot.yaml
```

Expected: exit 0, no new finding (the `finish-args-own-name-org.x.StatusIcon.orcshot` exception stays the only one).

- [ ] **Step 3: Commit**

```bash
git add org.orcshot.Orcshot.yaml
git commit -m "Flatpak: --filesystem=xdg-pictures:create for the default screenshot folder (#210)

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 4: Eight plain dialogs become `Gtk.FileChooserNative`

**Files:**
- Modify: `src/orcshot/ui/destination_picker.py` (`_save_as`, ~line 214)
- Modify: `src/orcshot/ui/external_commands.py` (`on_browse`, ~line 568)
- Modify: `src/orcshot/ui/editor_window.py`: `_do_save_objects` (~3301), `_do_load_objects` (~3336), `_do_insert_image` (~3485), `_do_insert_svg` (~3515), the module-level Open dialog (~5302), `_choose_save_location` (~5362)
- Test: `tests/unit/ui/test_no_in_process_file_chooser.py` (new)

**Interfaces:**
- Consumes: `output_directory_is_reachable` (Task 1).
- Produces: nothing new; Task 5 follows the same recipe.

Mechanics, identical at every site:
- `Gtk.FileChooserDialog(title=…, transient_for=…, action=…)` → `Gtk.FileChooserNative(title=…, transient_for=…, action=…)`. Default accept/cancel labels are GTK's own "_Open"/"_Save"/"_Cancel", so the `add_buttons(...)` line is deleted. The one site with a custom label (`_("Select")`) passes `accept_label=_("Select")`.
- `Gtk.ResponseType.OK` → `Gtk.ResponseType.ACCEPT` in every `dialog.run()` comparison.
- `add_filter`, `set_current_name`, `set_do_overwrite_confirmation`, `get_filename`, `destroy` are unchanged.
- `set_current_folder(str(get_output_directory()))` becomes guarded: only when the folder is reachable — pointing the portal at a tmpfs path is meaningless.

- [ ] **Step 1: Write the regression guard test**

`tests/unit/ui/test_no_in_process_file_chooser.py`:

```python
"""BACKLOG #210: Gtk.FileChooserDialog never goes through the desktop
portal, so under Flatpak it browses the sandbox's private tmpfs and
returns paths the app cannot really write. Every file dialog is
Gtk.FileChooserNative (portal when sandboxed, plain GTK dialog
otherwise). This pins that no in-process chooser sneaks back in.
"""

from pathlib import Path

SRC = Path(__file__).resolve().parents[3] / "src" / "orcshot"


def test_no_gtk_file_chooser_dialog_anywhere():
    offenders = [
        f"{p.relative_to(SRC)}:{n}"
        for p in SRC.rglob("*.py")
        for n, line in enumerate(p.read_text().splitlines(), 1)
        if "Gtk.FileChooserDialog(" in line
    ]
    assert offenders == []
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/ui/test_no_in_process_file_chooser.py -v`
Expected: FAIL listing 9 offenders.

- [ ] **Step 3: `destination_picker._save_as`**

```python
    dialog = Gtk.FileChooserNative(title=_("Save Screenshot As"), transient_for=parent, action=Gtk.FileChooserAction.SAVE)
    directory = get_output_directory()
    if output_directory_is_reachable(directory):
        dialog.set_current_folder(str(directory))
```

Delete the `dialog.add_buttons(...)` call (3 lines). Change `if dialog.run() == Gtk.ResponseType.OK:` → `Gtk.ResponseType.ACCEPT`. Keep the rest.

- [ ] **Step 4: `external_commands.on_browse`**

```python
        chooser = Gtk.FileChooserNative(
            title=_("Select Command"), transient_for=parent_dialog, action=Gtk.FileChooserAction.OPEN,
        )
        try:
            if chooser.run() == Gtk.ResponseType.ACCEPT:
                command_entry.set_text(chooser.get_filename())
        finally:
            chooser.destroy()
```

- [ ] **Step 5: `editor_window._do_save_objects`**

```python
        dialog = Gtk.FileChooserNative(title=_("Save Objects"), transient_for=self, action=Gtk.FileChooserAction.SAVE)
        directory = get_output_directory()
        if output_directory_is_reachable(directory):
            dialog.set_current_folder(str(directory))
        dialog.set_current_name("objects.json")
```

Delete `add_buttons`; `OK` → `ACCEPT`. Add `output_directory_is_reachable` to editor_window's `from orcshot.settings import (...)` block (~line 177).

- [ ] **Step 6: `editor_window._do_load_objects`, `_do_insert_image`, `_do_insert_svg`**

Each: `Gtk.FileChooserDialog(` → `Gtk.FileChooserNative(`; delete the `add_buttons` line; `if dialog.run() != Gtk.ResponseType.OK:` → `!= Gtk.ResponseType.ACCEPT`. Nothing else.

- [ ] **Step 7: module-level Open dialog (~5302)**

```python
    dialog = Gtk.FileChooserNative(title=_("Open"), transient_for=transient_for, action=Gtk.FileChooserAction.OPEN)
    directory = get_output_directory()
    if output_directory_is_reachable(directory):
        dialog.set_current_folder(str(directory))
```

Delete `add_buttons`; `!= OK` → `!= ACCEPT`.

- [ ] **Step 8: `_choose_save_location` (~5362)**

```python
    dialog = Gtk.FileChooserNative(
        title=_("Screenshot Save Location"), transient_for=parent, action=Gtk.FileChooserAction.SELECT_FOLDER,
        accept_label=_("Select"),
    )
    current = get_output_directory()
    if output_directory_is_reachable(current):
        dialog.set_current_folder(str(current))
    try:
        if dialog.run() == Gtk.ResponseType.ACCEPT:
            set_output_directory(Path(dialog.get_filename()))
    finally:
        dialog.destroy()
```

(`output_directory_is_reachable` already does the `mkdir`, so the old `current.mkdir(...)` line goes.)

- [ ] **Step 8b: Preferences location label — mark the known ceiling**

In `show_preferences_dialog` (~5889), above `location_label = Gtk.Label(label=str(get_output_directory()))`, add:

```python
    # ponytail: under Flatpak a portal-picked folder shows as
    # /run/user/<uid>/doc/<id>/<name>; show the host path via the
    # Documents portal's GetHostPaths if anyone minds (BACKLOG #210).
```

- [ ] **Step 9: Run the guard and the whole unit suite**

Run: `.venv/bin/python -m pytest tests/unit/ui/test_no_in_process_file_chooser.py -v`
Expected: FAIL with exactly one offender left — the Save Screenshot dialog (`ui/editor_window.py` ~3402, Task 5).

Run: `.venv/bin/python -m pytest tests -q`
Expected: everything else passes (the i18n scan included — `_("Select")` is still wrapped).

- [ ] **Step 10: Smoke one dialog for real on the dev checkout (.deb code path)**

Run the app from the checkout (`.venv/bin/python -m orcshot.app`), open the editor, *File → Screenshot Save Location…*. Expected: the ordinary GTK folder chooser with a **Select** button; choosing a folder updates Preferences' location label. Then *Object → Save objects…*: ordinary GTK save dialog, `objects.json` suggested. Close the app.

- [ ] **Step 11: Commit**

```bash
git add src/orcshot/ui/destination_picker.py src/orcshot/ui/external_commands.py src/orcshot/ui/editor_window.py tests/unit/ui/test_no_in_process_file_chooser.py
git commit -m "Every file dialog is Gtk.FileChooserNative - the portal under Flatpak, plain GTK elsewhere (#210)

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 5: Save Screenshot dialog — the format combo becomes a chooser choice

**Files:**
- Modify: `src/orcshot/ui/editor_window.py` `_do_save_as` (~3395-3460)
- Test: `tests/unit/ui/test_no_in_process_file_chooser.py` (from Task 4; now must pass)

**Interfaces:**
- Consumes: `_SAVE_AS_FORMATS` (existing list of `(value, label)`), `output_directory_is_reachable`.

`Gtk.FileChooser.add_choice(id, label, options, option_labels)` / `get_choice(id)` / `set_choice(id, option)` exist since GTK 3.22 precisely so portal dialogs can carry a combo; the plain GTK dialog renders it as one. `set_extra_widget` has no portal equivalent.

- [ ] **Step 1: Rewrite the dialog construction**

Replace everything from `dialog = Gtk.FileChooserDialog(` through `dialog.set_do_overwrite_confirmation(True)` with:

```python
        dialog = Gtk.FileChooserNative(title=title, transient_for=self, action=Gtk.FileChooserAction.SAVE)
        directory = get_output_directory()
        if output_directory_is_reachable(directory):
            dialog.set_current_folder(str(directory))

        # "orcshot" only here, not in _SAVE_AS_FORMATS - that list is
        # shared with the Output tab's "Primary format" dropdown
        # (quick-save's default raster format), and this isn't a valid
        # choice there. Matches real Windows exactly: its own
        # OutputFileFormat setting's docstring explicitly lists only
        # "bmp, gif, jpg, png, tiff" - "greenshot" is a Save-As-only
        # format on Windows too, never a quick-save default there
        # either (ICoreConfiguration.cs:130-132).
        formats = list(_SAVE_AS_FORMATS) + [("orcshot", "Orcshot")]
        # A chooser *choice* rather than set_extra_widget: choices are
        # the one custom control the FileChooser portal carries into
        # its dialog (BACKLOG #210); the plain GTK dialog shows them as
        # a combo too. The live rename on change that the old combo did
        # is gone - the with_suffix fix-up below already makes the
        # extension follow the chosen format.
        dialog.add_choice("format", _("Save as type:"), [v for v, _l in formats], [l for _v, l in formats])
        initial = output_settings.primary_format if output_settings.primary_format in dict(formats) else "png"
        dialog.set_choice("format", initial)
        dialog.set_current_name(f"screenshot.{initial}")
        dialog.set_do_overwrite_confirmation(True)
```

- [ ] **Step 2: Rewrite the result handling**

```python
        saved = False
        try:
            if dialog.run() == Gtk.ResponseType.ACCEPT:
                output_format = dialog.get_choice("format") or initial
                path = Path(dialog.get_filename())
```

The remainder of the `try` body (suffix fix-up, `.orcshot` branch, quality dialog, clipboard, `saved = True`) and the `finally: dialog.destroy()` stay exactly as they are. Delete the now-unused `format_combo`/`on_format_changed`/`extra` code — nothing else referenced them (verify with `grep -n "format_combo\|on_format_changed" src/orcshot/ui/editor_window.py` → no output).

- [ ] **Step 3: Run the guard and the suite**

Run: `.venv/bin/python -m pytest tests -q`
Expected: all PASS, including `test_no_gtk_file_chooser_dialog_anywhere`.

- [ ] **Step 4: Smoke on the dev checkout**

`.venv/bin/python -m orcshot.app`, take any capture into the editor, *File → Save As…*. Expected: the GTK save dialog shows a **Save as type:** combo listing PNG/JPEG/…/Orcshot; picking JPEG and saving `x` yields `x.jpg`.

- [ ] **Step 5: Commit**

```bash
git add src/orcshot/ui/editor_window.py
git commit -m "Save Screenshot dialog: format picker as a chooser choice so the portal carries it (#210)

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 6: Live verification on the CI-built Flatpak, recorded in VERIFICATION.md

**Files:**
- Modify: `VERIFICATION.md` (new scenario via `/orc-todo add verification`)

**Interfaces:** none — evidence only. Nothing in this task is a code change; if a scenario fails, the fix goes back into the task that owns it, then this task re-runs.

- [ ] **Step 1: Push the branch and get the CI bundle**

```bash
git push -u origin HEAD
gh run list --workflow=flatpak.yml --limit 1
```

Wait for it to go green (`gh run watch <id>`), then download the `orcshot_<version>.flatpak` artifact (`gh run download <id>`), and on the Mint host:

```bash
flatpak kill org.orcshot.Orcshot; flatpak install --user -y --reinstall orcshot_*.flatpak
flatpak info --show-permissions org.orcshot.Orcshot | grep filesystems
```

Expected: `filesystems=xdg-pictures:create`.

- [ ] **Step 2: Scenario A — today's repro (Mint host, `~/Screenshots` configured)**

Confirm the Flatpak's own config has `"output_directory": "/home/direflail/Screenshots"` (`cat ~/.var/app/org.orcshot.Orcshot/config/orcshot/config.json`; set it if not). Launch the Flatpak, tray → *Capture Full Screen → Save*. Expected: the portal folder picker titled *Screenshot Save Location* appears **once**; direflail picks `~/Screenshots`; a new PNG appears in `~/Screenshots` on the host (`ls -t ~/Screenshots | head -1`). Second *Save*: no dialog, a second PNG lands. The config now holds a `/run/user/1000/doc/…/Screenshots` path.

- [ ] **Step 3: Scenario B — restart persistence**

`flatpak kill org.orcshot.Orcshot`, relaunch, *Save* again. Expected: no dialog, file lands in `~/Screenshots`. (The document grant survived — `xdp-documents.c` registers with `DOCUMENT_ADD_FLAGS_PERSISTENT`.)

- [ ] **Step 4: Scenario C — out of the box**

`mv ~/.var/app/org.orcshot.Orcshot/config/orcshot/config.json{,.bak}`; ensure `~/Pictures` exists on the host (`mkdir -p ~/Pictures`). Relaunch, *Save*. Expected: **no dialog at any point**; file in `~/Pictures/Screenshots`. Restore the config afterwards.

- [ ] **Step 5: Scenario D — Save As with the format choice**

In the Flatpak, capture into the editor, *File → Save As…*. Expected: the portal save dialog shows a **Save as type:** combo; choose JPEG, save to `~/Screenshots/portal-test`; `~/Screenshots/portal-test.jpg` exists on the host and `file` reports JPEG. This is spec verification item 2 (`get_choice` through the -gtk/-xapp backend). Also note whether the dialog opened in `~/Screenshots` (spec verification item 3, `set_current_folder` on a doc path) — record either way, harmless if not.

- [ ] **Step 6: Scenario E — Open / Insert Image through the portal**

*Edit → Insert Image…*, pick any PNG outside `~/Pictures` (e.g. in `~/Downloads`). Expected: the image appears in the editor. (Spec verification item 1 is settled by Scenario A showing a *folder* picker, not a file picker.)

- [ ] **Step 7: Scenario F — Ubuntu 26.04 / GNOME 50 VM**

Registry memory `project_orcshot_vm_access.md` has the access details. Copy the bundle in, `flatpak install --user`, set `output_directory` to `~/Screenshots` in the Flatpak's config, and repeat Scenario A's two Saves. Expected: same result through xdg-desktop-portal-gnome. Drive the dialog with the registry's xdotool method if no one is at the VM's console.

- [ ] **Step 8: Record the scenario**

```bash
python3 /home/direflail/.claude/plugins/cache/orclab/orclab/0.16.0/skills/orc-todo/scripts/run.py add verification "Flatpak Save through the file-chooser portal (spec 2026-09-12)" <<'EOF'
Scenarios for docs/superpowers/specs/2026-09-12-flatpak-save-portal-design.md, on the CI bundle
from run <id>, <date>. One line per scenario A-F above: what was done, the command that produced
the evidence (ls/file/cat config.json), PASS or FAIL, machine.
EOF
```

Write the real results, not the template — each line names the command and its output the way Scenario 2 does.

- [ ] **Step 9: Resolve #210 in BACKLOG.md**

Per `orclab:backlog-discipline`: append `(RESOLVED <today's date>)` to #210's title line and a **Resolved for real, not just tracked:** paragraph naming scenarios A-F and the CI run. Do not edit #210's original text.

- [ ] **Step 10: Commit**

```bash
git add VERIFICATION.md BACKLOG.md
git commit -m "Resolve BACKLOG #210: Flatpak Save verified on the Mint host and the GNOME 50 VM (CI bundle)

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

Then hand off to `superpowers:finishing-a-development-branch`.
