# Orcshot Test Gates Before 0.4.0 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Get one `/orc-test analyze` run to pass both gates — line coverage ≥ 80% and TCE ≥ 70% — before the 0.4.0 release goes to any store.

**Architecture:** Three levers, in descending order of lines-per-unit-of-work. (1) *Contract tests over near-duplicate families*: the eight region-select / window-picker / eyedropper files are two shared contracts, not eight problems — every variant exposes `__init__` + `show()`, and the three Wayland overlays additionally share `_on_motion` / `_on_button_press` / `_on_button_release`. The repo already uses this idiom in `tests/unit/capture/test_*_contract.py`. (2) *Construction-plus-wiring tests for GTK windows*: constructing a window executes its whole build path — one `EditorWindow()` covered 33% of a 2678-line file — and the wiring assertions on top are what make the coverage mean something. (3) *Targeted mutant-killing* in code the suite already executes but tests weakly, which is pure TCE work and independent of coverage.

**Tech Stack:** pytest 7.4.4, pytest-cov 4.1.0, mutmut 3.7.0, PyGObject/GTK 3, Xvfb.

## Global Constraints

- **Both gates must pass on the same run, at the end.** Coverage ≥ 80% (`/orc-test coverage src`), TCE ≥ 70% (`/orc-test analyze`). Baseline 2026-09-26: coverage 44.4% (4308/9712), TCE 75.6% (8340 caught of 11028 scored, 15468 skipped as unreachable). TCE has only 5.6 points of headroom and **coverage work converts skipped mutants into scoreable ones**, so TCE is expected to fall as coverage rises. Never treat the baseline TCE as still valid after adding tests.
- **Every task proves its tests can fail.** test-discipline rule 5, both halves: plant one real defect in the code under test, run the tests, record which failed and with what, revert. A plant that is caught by nothing means the test is weak — write a better one before moving on. Three of the first four slices hit exactly this.
- **After every rule-5 revert, clear the bytecode cache before re-running.**

```bash
find src tests -name __pycache__ -type d -exec rm -rf {} + ; rm -rf .pytest_cache
```

  Not optional and not hygiene. A plant that swaps one identifier for another of the same length leaves the `.py` file's *size* unchanged, and CPython's default `.pyc` validation compares the recorded source mtime and size — so a `cp`-based revert can leave the cached bytecode accepted and the interpreter still running the defect while `git diff --stat src/` reports clean. Hit for real 2026-09-26: `center_check` -> `footer_check` in `ui/printing.py` (both 12 characters), four tests failing on pristine source, ~20 minutes lost. It cuts both ways — a stale cache can make a reverted defect look still-present, and it can make a coverage measurement describe defective code.
- **Never change `src/` behaviour to make a test pass.** Where a test reveals surprising behaviour, pin the actual behaviour, document why in the test, and add it to BACKLOG #220. `ui/effects.py`'s double shadow padding is the precedent.
- **A GTK test needs a display.** Module-level `pytestmark = pytest.mark.skipif(not os.environ.get("DISPLAY"), reason=...)` — this repo's existing idiom, not a new marker. CI already runs under `xvfb-run`; do **not** use the `x11` marker, which CI deselects and which 6 window-enumerator tests fail under bare Xvfb.
- **Realistic data.** Capture-shaped RGBA arrays with real per-pixel variation, not `np.zeros`. Reuse the `_capture()` / `_photo()` helpers' shape from `tests/unit/ui/test_editor_window.py`.
- **Isolation.** `tests/conftest.py` points `XDG_CONFIG_HOME` at a temp dir before collection, so settings writes are already isolated. Anything else leaving the process — D-Bus, subprocess, the clock, network — is faked.
- **Run tests as** `xvfb-run -a python3 -m pytest tests -q --ignore-glob='*mutants/*' -m "not x11 and not wayland"`.
- Commit per task. Trailer: `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`.

## Where the uncovered lines are

Measured 2026-09-26 after the first four commits on `test/coverage-to-80` (58.0% overall, 4086 of 9712 lines uncovered). Need **+2144 covered** to reach 80%.

| Cluster | Lines | Task |
|---|---|---|
| `ui/editor_window.py` input handlers | 291 | 2 |
| `ui/editor_window.py` dialog actions | 315 | 3 |
| `app.py` | 304 | 4 |
| The 8 overlay/picker files (two contracts) | ~941 | 5 |
| `ui/text_obfuscation_dialog.py` | 215 | 6 |
| `ui/color_dialog.py` + `ui/printing.py` | 234 | 7 |
| `ui/external_commands.py` + `destination_picker.py` + `first_run_setup.py` | 297 | 8 |

Total available across tasks 2–8: ~2597 against a need of 2144, so the plan has headroom for tasks that come in under target.

## File Structure

- Create `.orclab/test.yaml` — pins the coverage path and both gates so every future `/orc-test` run measures the right denominator without an argument.
- Create one test file per task, all disjoint, so tasks 2–8 can run in parallel with no shared state:
  - `tests/unit/ui/test_editor_window_input.py`
  - `tests/unit/ui/test_editor_window_actions.py`
  - `tests/unit/test_app.py`
  - `tests/unit/ui/test_capture_overlay_contract.py`
  - `tests/unit/ui/test_text_obfuscation_dialog.py`
  - `tests/unit/ui/test_color_dialog.py`, `tests/unit/ui/test_printing.py`
  - `tests/unit/ui/test_external_commands.py`, `tests/unit/ui/test_first_run_setup.py`
  - `tests/unit/ui/test_icons.py`, `tests/unit/ui/test_render_mutants.py` (task 9)
- Modify `tests/unit/ui/test_destination_picker.py` (task 8, additions only).
- No `src/` file is modified by any task.

---

### Task 1: Pin the measurement so every run means the same thing

**Why this is first:** `/orc-test coverage` with no path reported **7.4% on a 57,890-line denominator** for a 9,712-line project, because its `--cov` walk sweeps in all three stale worktrees under `.claude/worktrees/` and the gitignored `debian/orcshot/usr/lib/python3/dist-packages/` dpkg staging tree. Every later task measures its own progress, so they must all measure the same thing.

**Files:**
- Create: `.orclab/test.yaml`

**Interfaces:**
- Produces: the canonical measurement command every later task uses to report its number.

- [ ] **Step 1: Write the config**

```yaml
# /orc-test's own gates for this project. Both are the defaults; they are
# written down because BACKLOG #220 turns on them and a silent change to
# either would be invisible.
coverage: 80
tce: 70
languages:
  python:
    # Without a path, /orc-test's --cov walk descends into every
    # directory holding a .py file that lacks an __init__.py. In this
    # checkout that is three stale worktrees under .claude/worktrees/
    # (each a full copy of src/) and debian/orcshot/usr/lib/python3/
    # dist-packages/ (the gitignored dpkg staging tree, a second copy
    # again) - a 57890-line denominator for a 9712-line project,
    # reported as 7.4% on 2026-09-26. src/ is what ships.
    test: python3 -m pytest -q --ignore-glob=*mutants/*
```

- [ ] **Step 2: Confirm the denominator is right**

Run: `python3 <orclab>/skills/orc-test/scripts/run.py coverage src`
Expected: a denominator of 9712 (±20 as tests land), not 57890.

- [ ] **Step 3: Commit**

```bash
git add .orclab/test.yaml
git commit -m "Pin /orc-test's gates and note why coverage needs a path"
```

---

### Task 2: `editor_window.py` input handlers (291 lines)

**Files:**
- Create: `tests/unit/ui/test_editor_window_input.py`
- Read first: `src/orcshot/ui/editor_window.py` — `_on_key_press` (5073, 80 lines uncovered), `_on_button_release` (4968, 70), `_on_button_press` (4807, 60), `_on_motion` (4922, 32), `_on_draw` (4729, 23), `_draw_crop_overlay` (4765, 26)

**Interfaces:**
- Consumes: the `editor` fixture pattern and `_capture()` helper from `tests/unit/ui/test_editor_window.py` (copy them; test modules must not import each other).
- Produces: nothing other tasks depend on.

- [ ] **Step 1: Read all six handlers before writing anything.** They branch on `event.button`, `event.state` modifiers, `event.keyval`, and on `self.tool`. Enumerate the branches first; the branch list *is* the test list.

- [ ] **Step 2: Build the event fakes**

The handlers take Gdk events. Do not synthesise real ones — construct the minimal stand-in the handler actually reads:

```python
from dataclasses import dataclass, field

from gi.repository import Gdk


@dataclass
class FakeButtonEvent:
    x: float = 10.0
    y: float = 20.0
    button: int = 1
    state: Gdk.ModifierType = Gdk.ModifierType(0)
    type: Gdk.EventType = Gdk.EventType.BUTTON_PRESS


@dataclass
class FakeKeyEvent:
    keyval: int = Gdk.KEY_Escape
    state: Gdk.ModifierType = Gdk.ModifierType(0)
```

If a handler reads an attribute these lack, add it — do not give the fake attributes nothing reads.

- [ ] **Step 3: Write one test per branch.** Behaviours worth pinning, not smoke tests:
  - Escape with an unconfirmed crop clears the crop rather than closing the window.
  - A shift-click on an already-selected shape toggles it out of the selection (task #125's multi-select); a plain click replaces the selection.
  - Press-drag-release with the Rectangle tool appends exactly one shape to the layer and leaves it selected.
  - Press-drag-release with a Crop tool sets `_crop_selection` and creates no shape.
  - `_on_motion` with no button held does not mutate the layer.
  - `_on_draw` against a real `cairo.Context` from `cairo.ImageSurface(cairo.FORMAT_ARGB32, w, h)` returns without raising for every `Tool` value.

- [ ] **Step 4: Run them**

Run: `xvfb-run -a python3 -m pytest tests/unit/ui/test_editor_window_input.py -q --ignore-glob='*mutants/*'`
Expected: all pass.

- [ ] **Step 5: Rule 5.** Plant two defects and record the result. Suggested: in `_on_button_press`, drop the shift-modifier branch so every click replaces the selection; in `_on_key_press`, change the Escape branch to fall through. Each must fail a named test. Revert both and confirm `git diff --stat src/` is empty.

- [ ] **Step 6: Report and commit.** Report `editor_window.py`'s before/after percentage from the Task 1 command.

```bash
git add tests/unit/ui/test_editor_window_input.py
git commit -F - # message: what was covered, the rule 5 result, before -> after
```

---

### Task 3: `editor_window.py` dialog actions (315 lines)

**Files:**
- Create: `tests/unit/ui/test_editor_window_actions.py`
- Read first: `_do_show_help` (3787, 50), `_do_torn_edge_settings` (4664, 44), `_do_resize` (4543, 44), `_do_save` (3391, 38), `_do_drop_shadow_settings` (4613, 35), `_do_load_objects` (3325, 25), `_do_insert_image` (3484, 22), `_do_insert_svg` (3526, 21), `_do_save_objects` (3294, 18), `_do_open_in_external_editor` (3670, 18), `_maybe_show_quality_dialog` (1806, 19)

**Interfaces:**
- Consumes: the `editor` fixture and `_capture()` helper (copy them).
- Produces: nothing other tasks depend on.

- [ ] **Step 1: Read each action.** Each opens a modal dialog. `Gtk.Dialog.run()` blocks forever under a test, so every one of these needs its dialog neutralised.

- [ ] **Step 2: Neutralise the modal, not the logic.** Patch the dialog class the action constructs so `run()` returns a chosen response and `get_filename()` (etc.) returns a chosen value. Monkeypatch by the name the module under test looks up — `orcshot.ui.editor_window.Gtk.FileChooserDialog`, not `gi.repository.Gtk.FileChooserDialog`:

```python
class FakeDialog:
    """Stands in for one Gtk.Dialog: run() answers instead of blocking."""

    def __init__(self, response=Gtk.ResponseType.OK, filename=None, **_kwargs):
        self._response = response
        self._filename = filename
        self.destroyed = False

    def run(self):
        return self._response

    def destroy(self):
        self.destroyed = True

    def get_filename(self):
        return self._filename
```

  Assert the dialog is **destroyed** on both the OK and Cancel paths — a leaked modal is a real bug this shape of test catches for free.

- [ ] **Step 3: Write the tests.** Per action, at minimum: the Cancel path changes nothing and destroys the dialog; the OK path performs exactly the documented change. Specifically:
  - `_do_resize` with OK resizes `base_image` to the requested size and pushes one undo entry; with Cancel leaves `base_image` identical.
  - `_do_save` with a chosen filename writes a real file into `tmp_path` and clears `is_modified`.
  - `_do_insert_image` / `_do_insert_svg` with a real file written into `tmp_path` append one `ImageShape`; with Cancel append none.
  - `_do_save_objects` then `_do_load_objects` round-trips the layer through a `.orcshot` file in `tmp_path`.
  - `_do_open_in_external_editor` never runs a real process — fake `subprocess` and assert the argv it would have used.
  - `_maybe_show_quality_dialog` prompts for a lossy format and does not for a lossless one.

- [ ] **Step 4: Run them.** Same command as Task 2, this file.

- [ ] **Step 5: Rule 5.** Suggested plants: make `_do_resize` ignore the Cancel response and resize anyway; make `_do_save` skip clearing the saved generation so `is_modified` stays true. Revert both.

- [ ] **Step 6: Report and commit.**

---

### Task 4: `app.py` (304 lines)

**Files:**
- Create: `tests/unit/test_app.py`
- Read first: `src/orcshot/app.py` — `OrcshotApplication` (170), `main` (1015)

**Interfaces:**
- Consumes: nothing from other tasks.
- Produces: nothing other tasks depend on.

- [ ] **Step 1: Read it.** This is a `Gtk.Application` with single-instance activation over D-Bus and command-line handling. The D-Bus name is `org.orcshot.Orcshot` — the same name the Snap Store declaration was granted for; **nothing in this task may claim that bus name**, or it will collide with a running tray app (BACKLOG memory: the .deb tray app steals the bus name from a Flatpak launch).

- [ ] **Step 2: Test the command-line surface, not the main loop.** `main()` ends in `Gtk.Application.run`, which never returns under a test. Target instead:
  - the argument parsing / `do_command_line` handling: each flag routed to the right action, an unknown flag rejected with a non-zero status
  - `do_startup`'s action registration: assert the expected action names exist after startup, without activating the app on the real bus
  - the single-instance hand-off logic, with the remote-activation call faked
  Construct the application with `application_id=None` (or the test-only id the code already allows, if it does) so no bus name is claimed. If the code offers no such seam, **do not add one** — test the module-level helpers instead and note the ceiling in the commit message and BACKLOG #220.

- [ ] **Step 3: Run them.**

- [ ] **Step 4: Rule 5.** Plant a defect in the flag routing — send `--region` to the fullscreen action — and confirm a named test fails. Revert.

- [ ] **Step 5: Report and commit.** If `app.py` cannot reach 80% without a seam that does not exist, say so explicitly with the number reached; the plan has headroom.

---

### Task 5: The capture-overlay contract — 8 files, two contracts (~941 lines)

**This is the highest-leverage task in the plan.** Read the reasoning in Architecture before starting.

**Files:**
- Create: `tests/unit/ui/test_capture_overlay_contract.py`
- Read first, all eight: `ui/region_select.py` (`RegionSelectWindow` 87, `start_region_capture` 343), `ui/region_select_wayland.py` (`WaylandRegionSelect` 77), `ui/region_select_gnome_shell.py` (`GnomeShellRegionSelect` 41), `ui/window_picker.py` (`WindowPickerWindow` 58, `start_window_picker` 214), `ui/window_picker_wayland.py` (`WaylandWindowPicker` 57), `ui/window_picker_gnome_shell.py` (`GnomeShellWindowPicker` 35), `ui/eyedropper.py` (`_EyedropperOverlay` 71, `start_eyedropper` 176), `ui/eyedropper_wayland.py` (`_WaylandEyedropperOverlay` 92)
- Pattern to follow: `tests/unit/capture/test_backend_contract.py`

**Interfaces:**
- Consumes: nothing from other tasks.
- Produces: nothing other tasks depend on.

- [ ] **Step 1: Read all eight and write down the two contracts.** Confirmed 2026-09-26: every one of the five variant classes exposes `__init__` + `show()`. The three Wayland overlays additionally share `_on_motion(global_x, global_y)`, `_on_button_press(global_x, global_y)` and `_on_button_release(global_x, global_y)`. If reading shows a variant that does not fit, give it its own test rather than bending the contract — a contract test that special-cases half its parameters is worse than two honest tests.

- [ ] **Step 2: Write the shared contract with a parametrised fixture**

```python
pytestmark = [
    pytest.mark.skipif(
        not os.environ.get("DISPLAY"),
        reason="the overlays are real Gtk widgets - constructing one needs a display (CI: xvfb-run)",
    ),
    pytest.mark.parametrize(
        "overlay_name",
        ["region_select_wayland", "region_select_gnome_shell",
         "window_picker_wayland", "window_picker_gnome_shell"],
    ),
]
```

  with a fixture that imports and constructs the named class, and a `_fake_shell()` / `_fake_portal()` double for whatever each one is handed. Nothing in this file may make a real D-Bus call or a real portal request: the portal paths must never be renamed or invoked for real (BACKLOG memory).

- [ ] **Step 3: Assert the contract.** For every parameter: construction succeeds and sets no selection yet; `show()` with the shell/portal faked reaches its own presentation call exactly once and raises nothing; the selection callback, invoked with a known `Rect`, delivers that rect through to the handed-in `on_selected`; a cancelled selection delivers nothing.

- [ ] **Step 4: Add the pointer-interaction contract** for the Wayland overlays only, as a second parametrised class: press at a point then motion then release produces the rect those three points describe; press and release at the same point produces no selection (a click is not a zero-area region); motion with no press held changes nothing.

- [ ] **Step 5: Cover the two X11 windows and the two eyedroppers** in the same file as their own classes — `RegionSelectWindow`, `WindowPickerWindow`, `_EyedropperOverlay`, `_WaylandEyedropperOverlay`. The eyedroppers read pixels from a capture backend; hand them `FakeCaptureBackend` from `orcshot.capture.fake`, which already exists.

- [ ] **Step 6: Run them.**

- [ ] **Step 7: Rule 5.** Plant one defect *per contract*, not one for the file: make one Wayland overlay's `_on_button_release` forget to deliver the rect, and make one `show()` skip its presentation call. Each must fail a named parameter. Revert both.

- [ ] **Step 8: Report and commit.** Report each of the eight files' before/after percentage separately — this task's value is in the total, and a file that stayed at 0% needs saying out loud.

---

### Task 6: `ui/text_obfuscation_dialog.py` (215 lines)

**Files:**
- Create: `tests/unit/ui/test_text_obfuscation_dialog.py`
- Read first: `do_obfuscate_text` (152), `_TextObfuscationDialog` (192), and `DEFAULT_TEXT_OBFUSCATION_SETTINGS`

**Interfaces:**
- Consumes: nothing from other tasks.
- Produces: nothing other tasks depend on.

- [ ] **Step 1: Read it.** `do_obfuscate_text(editor)` takes an editor and runs OCR-driven obfuscation. OCR shells out to tesseract (`ui/ocr.py`'s `tesseract_available(which=shutil.which)` is already dependency-injected — use that seam, never the real binary).

- [ ] **Step 2: Fake OCR, not the dialog logic.** Supply a known `OcrResult` with realistic word boxes — words with a quote in one, a word at the image edge, an empty result — and assert which regions get obfuscated for each mode. The defaults dict is a contract worth pinning field by field: a silently changed default is a user-visible behaviour change.

- [ ] **Step 3: Assert the no-OCR path.** With `tesseract_available` returning False, the dialog must say so and obfuscate nothing, rather than raising.

- [ ] **Step 4: Run them.**

- [ ] **Step 5: Rule 5.** Plant: make the empty-OCR-result path fall through to obfuscating the whole image. Revert.

- [ ] **Step 6: Report and commit.**

---

### Task 7: `ui/color_dialog.py` (130) + `ui/printing.py` (104)

**Files:**
- Create: `tests/unit/ui/test_color_dialog.py`, `tests/unit/ui/test_printing.py`
- Read first: `show_color_picker` (color_dialog.py:70), `print_image` (printing.py)

**Interfaces:**
- Consumes: nothing from other tasks.
- Produces: nothing other tasks depend on.

- [ ] **Step 1: Read both.** Both end in a modal; use Task 3's `FakeDialog` shape (copy it — test modules must not import each other).

- [ ] **Step 2: `show_color_picker`.** OK returns the chosen colour; Cancel returns None (confirm which — read it, do not assume); the dialog is destroyed on both paths; the initial colour shown is the one passed in.

- [ ] **Step 3: `print_image`.** Never reach a real printer or spooler: fake `Gtk.PrintOperation` and assert the operation is configured with the expected page setup and that a cancelled print writes nothing. `ui/printing.py` is at 16.8%, so the uncovered part is the configuration path, which is exactly what these assertions walk.

- [ ] **Step 4: Run, Step 5: Rule 5** (plant: `show_color_picker` returns the colour on Cancel too), **Step 6: commit.**

---

### Task 8: `external_commands` (128) + `destination_picker` (100) + `first_run_setup` (69)

**Files:**
- Create: `tests/unit/ui/test_external_commands.py`, `tests/unit/ui/test_first_run_setup.py`
- Modify: `tests/unit/ui/test_destination_picker.py` — additions only, leave the existing tests alone
- Read first: `ui/external_commands.py` (at 59.9%, and **72% TCE with 133 survivors** — this file needs both kinds of work), `ui/destination_picker.py` (35.5%), `ui/first_run_setup.py` (31.7%, `run_setup_dialog`)

**Interfaces:**
- Consumes: nothing from other tasks.
- Produces: nothing other tasks depend on.

- [ ] **Step 1: `external_commands`.** Never execute a command — fake the process layer and assert the argv, the working directory, and the placeholder substitution in the command template, including a path containing a space and one containing a quote.

- [ ] **Step 2: `destination_picker`.** The existing tests cover `destinations_for_shell` and `_should_reuse_editor`. Uncovered is the GTK picker itself and `ensure_output_directory`. For the latter, the hostile cases are the point: a path that exists as a file, a directory with no write permission (`os.chmod(0o500)` under `tmp_path`), and a path whose parent does not exist. `output_directory_is_reachable` has a documented history of letting an unwritable existing directory through (BACKLOG #216) — assert it does not.
- [ ] **Step 3: `first_run_setup`.** `run_setup_dialog(parent)` with the dialog faked: accepting enables the hotkeys and autostart it offered, declining changes nothing. Autostart writes a real `.desktop` file — `XDG_CONFIG_HOME` is already a temp dir, so assert on the file's presence and contents there.

- [ ] **Step 4: Run, Step 5: Rule 5** (plant: `ensure_output_directory` stops checking writability), **Step 6: commit.**

---

### Task 9: Pay down mutation debt in code the suite already runs

**Runs after tasks 2–8 land**, because its target list must be recomputed from a fresh mutation run — coverage work changes which mutants are scoreable.

**Files:**
- Create: `tests/unit/ui/test_icons.py`, and one file per other target the fresh run names
- Read first: the survivor list, recomputed — not the 2026-09-26 one

**Interfaces:**
- Consumes: the full test suite from tasks 2–8.
- Produces: the run that Task 10 gates on.

- [ ] **Step 1: Recompute the survivor list.**

```bash
rm -rf mutants && timeout 5400 python3 -m mutmut run
```

  then tally per file from `mutants/**/*.meta` (`exit_code_by_key`: 1/3 killed, 36/24/-24/152/255 timeout, 0 survived, anything else not scored).

- [ ] **Step 2: Work worst-TCE-first, not most-survivors-first.** The 2026-09-26 baseline for orientation only: `ui/extension_install.py` 41% (84 survivors), `capture/x11_window.py` 47% (109), `capture/fake.py` 58% (45), `ui/icons.py` 60% (**789** — the largest single pool), `ui/orcshot_file.py` 66% (42), `capture/shell_bridge.py` 67% (88), `ui/xapp_tray.py` 67% (49), `ui/render.py` 72% (374).

- [ ] **Step 3: For each survivor, write the test that goes red on exactly that change.** Rule 5 is free here — the mutant *is* the planted defect. Re-run and confirm it is now killed. `ui/icons.py`'s 789 survivors are very likely geometry constants no assertion reads; pinning icon geometry means asserting rendered output properties, not constants.

- [ ] **Step 4: Stop at 70% plus a margin, not at 70%.** Aim for ≥ 75% so the gate does not fail on run-to-run mutation-timeout variance (the baseline run had 62 timeouts and 10 suspicious).

- [ ] **Step 5: Commit per file, not one commit for the task.**

---

### Task 10: The gate run

**Files:** none created. This task's deliverable is a measurement and a decision.

- [ ] **Step 1: Full clean run**

```bash
rm -rf mutants .orclab/test
python3 <orclab>/skills/orc-test/scripts/run.py run
python3 <orclab>/skills/orc-test/scripts/run.py audit
python3 <orclab>/skills/orc-test/scripts/run.py analyze src
```

- [ ] **Step 2: Both gates, one run.** Coverage ≥ 80% **and** TCE ≥ 70%. If either fails, the failing gate names the next task; do not release on one of two.

- [ ] **Step 3: Confirm CI agrees.** Push the branch, open a draft PR (this repo's workflows run only on `main` pushes and PRs — a feature-branch push triggers no CI), and confirm the suite is green there. CI deselects `x11` and `wayland`; every test written under this plan must pass in that selection.

- [ ] **Step 4: Update BACKLOG #220** with the final numbers and resolve it, layering the resolution rather than overwriting the baseline.

- [ ] **Step 5: Hand back to the release.** 0.4.0's chain is otherwise unblocked: the Snap dbus declaration was granted 2026-09-17 (forum thread 53283). EGO's review of the extension is still pending and gates snap `stable` and the Flathub merge, not this.

---

## Self-Review

**Coverage of the requirement.** The requirement is both gates before release. Tasks 2–8 carry ~2597 available lines against a need of +2144 — headroom for two tasks to come in under target. Task 9 is the only TCE-specific work and is correctly sequenced after coverage, since coverage changes the mutant population. Task 10 is the single point where both gates are checked together, which is the Global Constraint that matters most.

**Parallelism.** Tasks 2–8 create disjoint files, modify no `src/` file, and share no fixtures (each copies what it needs, because pytest's importlib mode forbids test modules importing each other). They can run concurrently. Task 1 must precede them so they all report the same denominator; task 9 must follow them; task 10 is last.

**Known ceilings, stated rather than hidden.** `app.py` may not reach 80% without a seam for the D-Bus application id that may not exist — Task 4 says to report the shortfall rather than add production code for a test. `ui/icons.py`'s 789 survivors may resist cheap kills if they are geometry constants, which is why Task 9 targets worst-TCE-first rather than largest-pool-first.

**Not in scope.** Fixing the two `ui/effects.py` padding oddities (BACKLOG #220 — direflail's call, a live-verified visual effect). Orclab's own `orc-test` coverage-walk defect, which reported 7.4% here — Orclab is under its own testing sweep and Task 1 works around it locally.
