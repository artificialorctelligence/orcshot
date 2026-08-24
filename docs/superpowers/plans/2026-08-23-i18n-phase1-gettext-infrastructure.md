# i18n Phase 1: gettext Infrastructure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Route every genuinely user-facing string in orcshot through `gettext`'s `_()`, with zero real non-English translations authored yet, plus a regression guard that stops new unwrapped strings from creeping back in.

**Architecture:** A tiny `orcshot.i18n` wrapper module binds `_`/`ngettext` once via stdlib `gettext.translation(..., fallback=True)`, reading catalogs from a package-relative `resources/locale/` directory (same convention as the existing `RESOURCES_DIR`). Since zero `.mo` catalogs ship in this phase, `_()` always falls back to returning its argument unchanged - so the sweep is a pure refactor with no observable behavior change, and existing tests should not need rewrites. A sink-list-based AST scanner (not text-shape heuristics - see spec for why) enforces going forward that new sink-call-site strings go through `_()`.

**Tech Stack:** Python stdlib `gettext`, `ast` module for the scanner, `xgettext` (external tool, dev-only, not a packaged dependency).

**Spec:** [docs/superpowers/specs/2026-08-23-i18n-phase1-gettext-infrastructure-design.md](../specs/2026-08-23-i18n-phase1-gettext-infrastructure-design.md) - read it first; this plan assumes the sink list, wrapper module shape, and scope boundary defined there.

## Global Constraints

- No changes to `debian/rules` or `debian/control` in this phase (nothing is compiled/installed - see spec's "Extraction tooling" section).
- Zero real `.po`/`.mo` files authored or shipped this phase.
- No in-app language-preference override - relies on standard `gettext` env-var negotiation (spec's "Language selection" section).
- The sink list (method names and constructor-kwarg patterns) is fixed as enumerated in the spec's "The regression guard" section, including the two false-positive exclusions (`Pango.Layout.set_text`, `Gtk.Clipboard...set_text`) and the numeric-label exclusions added there during planning.
- Every sweep task's acceptance criterion: the full existing test suite (`.venv/bin/pytest tests/unit -q`) stays green with the exact same pass count as before that task - since `_()` always falls back to the identical string in this phase, no existing test's expected output should change.

---

## Shared rule for every sweep task (Tasks 4-12)

Read this once; it applies to all sweep tasks below rather than being repeated in each.

**The sink list** (a string literal argument at one of these call shapes needs `_()`, unless excluded below):
- Method calls: `set_text`, `set_tooltip_text`, `set_label`, `set_title`, `set_markup`, `set_placeholder_text`, `set_body`, `format_secondary_text`, `set_program_name`, `set_comments`
- Constructor kwargs (`label=`, `title=`, `text=`, `secondary_text=`) on: `Gtk.Label`, `Gtk.CheckButton`, `Gtk.Frame`, `Gtk.Button`, `Gtk.Dialog`, `Gtk.FileChooserDialog`, `Gtk.MenuItem`, `Gtk.MenuButton`, `Gtk.ColorChooserDialog`, `Gtk.ImageMenuItem`, `Gtk.MessageDialog`
- `Gio.Notification.new(...)` (first positional argument)

**Excluded, never wrapped:**
- `layout.set_text(...)` where `layout` is a `Pango.Layout` rendering user-typed annotation text (found in `render.py`, `printing.py`) - add `# noqa: i18n (user-typed annotation text, not UI chrome)` on that line.
- `Gtk.Clipboard...set_text(...)` copying a file path or other data, not UI text - add `# noqa: i18n (clipboard data, not UI text)`.
- Purely numeric/punctuation content with nothing to translate (e.g. `f"{width} x {height}"` dimension or coordinate labels) - add `# noqa: i18n (numeric only)`.
- GSettings/dconf keys, D-Bus interface/method names, file paths, `print(..., file=sys.stderr)` diagnostics, CSS class names, config JSON keys - these don't match the sink list at all, so they need no comment, just leave them alone.
- A proper noun that happens to hit a sink (e.g. `set_program_name("Orcshot")`) - `# noqa: i18n (proper noun)`.

**f-strings:** `xgettext` cannot extract through an f-string. Convert `f"...{x}..."` to `_("...{}...").format(x)` form - plain positional `{}` placeholders, no named placeholders needed yet.

**Indirected values:** if a sink call's argument is a variable or a helper-function call, not a literal, trace it to its actual source (the variable's assignment, or the helper function's own `return` statements) and apply the same wrap-or-exclude decision there instead of at the call site.

**Per-task steps** (same shape for every sweep task):
1. Run the grep command given in the task to enumerate every sink hit in the file(s) - the count given in each task is a floor (from a simple single-line grep), so also scan visually for multi-line calls the grep missed.
2. For each hit: wrap with `_()` (converting f-strings to `.format()` first if needed), trace indirected values to their source and decide there, or add the specified `# noqa: i18n` with a reason if excluded.
3. Add `from orcshot.i18n import _` (or `_, ngettext` if a plural form is genuinely needed) to the file's imports.
4. Run: `.venv/bin/pytest tests/unit -q` - expect the exact same pass/skip count as before this task (a regression here means a wrap changed real behavior, not just moved a string - stop and investigate rather than adjusting the test).
5. Commit.

---

### Task 1: i18n wrapper module

**Files:**
- Create: `src/orcshot/i18n.py`
- Test: `tests/unit/test_i18n.py`

**Interfaces:**
- Produces: `orcshot.i18n._(text: str) -> str`, `orcshot.i18n.ngettext(singular: str, plural: str, n: int) -> str` - every later task imports `_` from here.

- [ ] **Step 1: Write the failing test for the fallback path**

```python
from orcshot.i18n import _


class TestFallbackTranslation:
    def test_returns_the_argument_unchanged_when_no_catalog_is_installed(self):
        assert _("Preferences") == "Preferences"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/unit/test_i18n.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'orcshot.i18n'`

- [ ] **Step 3: Write the wrapper module**

```python
"""gettext wrapper (i18n phase 1, BACKLOG.md's resolved #173 successor
work) - binds _()/ngettext() once at import time. localedir reuses the
existing RESOURCES_DIR convention (package-relative, not the system
/usr/share/locale/) so this resolves identically in a dev checkout and
an installed .deb, same trick already used for icons/
magnifier_constants.json.

No real .mo catalogs ship yet (this phase is infrastructure-only, see
docs/superpowers/specs/2026-08-23-i18n-phase1-gettext-infrastructure-design.md) -
fallback=True means _() always returns its argument unchanged for now,
which is why every existing test's expected UI-text output is
unaffected by the whole sweep this phase does.
"""

from __future__ import annotations

import gettext
from pathlib import Path

_LOCALE_DIR = Path(__file__).parent / "resources" / "locale"
_translation = gettext.translation("orcshot", localedir=_LOCALE_DIR, fallback=True)
_ = _translation.gettext
ngettext = _translation.ngettext
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/unit/test_i18n.py -v`
Expected: PASS

- [ ] **Step 5: Write the failing test for real substitution (proves the mechanism works, not just the fallback)**

```python
    def test_a_real_catalog_actually_substitutes(self, tmp_path):
        import gettext as gettext_module

        locale_dir = tmp_path / "locale"
        mo_dir = locale_dir / "fr" / "LC_MESSAGES"
        mo_dir.mkdir(parents=True)
        po_source = (
            'msgid ""\n'
            'msgstr "Content-Type: text/plain; charset=UTF-8\\n"\n'
            "\n"
            'msgid "Preferences"\n'
            'msgstr "Préférences"\n'
        )
        po_path = tmp_path / "orcshot.po"
        po_path.write_text(po_source)
        import subprocess

        subprocess.run(
            ["msgfmt", str(po_path), "-o", str(mo_dir / "orcshot.mo")], check=True,
        )
        translation = gettext_module.translation(
            "orcshot", localedir=str(locale_dir), languages=["fr"], fallback=True,
        )
        assert translation.gettext("Preferences") == "Préférences"
```

- [ ] **Step 6: Run test to verify it passes**

Run: `.venv/bin/pytest tests/unit/test_i18n.py -v`
Expected: PASS (2 passed). If `msgfmt` isn't installed, install it first: `sudo apt install gettext` (a dev-machine tool, not a packaged Build-Depends per this phase's scope).

- [ ] **Step 7: Commit**

```bash
git add src/orcshot/i18n.py tests/unit/test_i18n.py
git commit -m "i18n phase 1: add gettext wrapper module (src/orcshot/i18n.py)"
```

---

### Task 2: `.pot` extraction script

**Files:**
- Create: `scripts/extract_pot.sh`
- Test: `tests/unit/test_extract_pot.py`

**Interfaces:**
- Consumes: nothing from Task 1.
- Produces: `po/orcshot.pot` (generated file, not committed - add `po/*.pot` to `.gitignore`).

- [ ] **Step 0 (prerequisite, not a test step): confirm `xgettext` is installed**

Run: `xgettext --version`
Expected: prints a version string. If instead `command not found`: `sudo apt install gettext` (a dev-machine tool for this phase, not a packaged `Build-Depends` - see the spec's "Extraction tooling" section for why).

- [ ] **Step 1: Write the failing test**

```python
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent


class TestExtractPot:
    def test_the_script_produces_a_non_empty_pot_file(self):
        result = subprocess.run(
            [str(REPO_ROOT / "scripts" / "extract_pot.sh")],
            cwd=REPO_ROOT, capture_output=True, text=True,
        )
        assert result.returncode == 0, result.stderr
        pot_path = REPO_ROOT / "po" / "orcshot.pot"
        assert pot_path.exists()
        assert pot_path.stat().st_size > 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/unit/test_extract_pot.py -v`
Expected: ERROR (not FAILED) with `FileNotFoundError` - `subprocess.run` can't exec a script that doesn't exist yet. This is pytest's own status label for an uncaught exception versus a plain assertion failure, but it's still failing for the right reason (the script genuinely doesn't exist), not a typo in the test - proceed to Step 3.

- [ ] **Step 3: Write the script**

```bash
#!/bin/sh
# i18n phase 1: dev-only string extraction, not part of the packaged
# build (see docs/superpowers/specs/2026-08-23-i18n-phase1-gettext-infrastructure-design.md's
# "Extraction tooling" section for why this deliberately doesn't touch
# debian/rules or debian/control).
set -e
cd "$(dirname "$0")/.."
mkdir -p po
xgettext --language=Python --keyword=_ --keyword=ngettext:1,2 \
    --output=po/orcshot.pot \
    $(find src/orcshot -name '*.py')
echo "Wrote po/orcshot.pot"
```

```bash
chmod +x scripts/extract_pot.sh
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/unit/test_extract_pot.py -v`
Expected: PASS

- [ ] **Step 5: Add the generated file to .gitignore**

Add a line to `.gitignore`:
```
po/*.pot
```

- [ ] **Step 6: Commit**

```bash
git add scripts/extract_pot.sh tests/unit/test_extract_pot.py .gitignore
git commit -m "i18n phase 1: add dev-only .pot extraction script"
```

---

### Task 3: sink-list scanner core logic

**Files:**
- Create: `tests/unit/_i18n_scan.py` (test-only helper module - not shipped runtime code, only imported by `test_i18n_coverage.py`)
- Test: `tests/unit/test_i18n_scan.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `scan_source(source: str, filename: str = "<test>") -> list[Violation]`, where `Violation` is a small dataclass with `line: int` and `message: str`. Task 13 (final) imports `scan_source` and runs it against every real in-scope file.

- [ ] **Step 1: Write the failing tests against small in-memory fixtures**

```python
from tests.unit._i18n_scan import scan_source


class TestScanSource:
    def test_flags_an_unwrapped_label_kwarg(self):
        source = 'Gtk.Label(label="Hello")\n'
        violations = scan_source(source)
        assert len(violations) == 1
        assert violations[0].line == 1

    def test_does_not_flag_an_already_wrapped_label(self):
        source = 'Gtk.Label(label=_("Hello"))\n'
        assert scan_source(source) == []

    def test_does_not_flag_a_call_outside_the_sink_list(self):
        source = 'subprocess.run(["echo", "Hello"])\n'
        assert scan_source(source) == []

    def test_respects_a_noqa_comment_on_the_same_line(self):
        source = 'dialog.set_program_name("Orcshot")  # noqa: i18n (proper noun)\n'
        assert scan_source(source) == []

    def test_flags_an_unwrapped_method_call_sink(self):
        source = 'widget.set_tooltip_text("Click to capture")\n'
        violations = scan_source(source)
        assert len(violations) == 1

    def test_flags_gio_notification_new(self):
        source = 'Gio.Notification.new("Update available")\n'
        violations = scan_source(source)
        assert len(violations) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/unit/test_i18n_scan.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'tests.unit._i18n_scan'`

- [ ] **Step 3: Write the scanner**

```python
"""AST-based sink-list scanner for the i18n regression guard (i18n
phase 1). Test-only tooling, not shipped runtime code - see
docs/superpowers/specs/2026-08-23-i18n-phase1-gettext-infrastructure-design.md's
"The regression guard" section for why this is sink-list-based (does a
string literal reach a known GTK/Gio text-setting call?) rather than
text-shape-heuristic-based (a heuristic like "capitalized with a
space" would miss short unspaced labels like "OK"/"Cancel").
"""

from __future__ import annotations

import ast
from dataclasses import dataclass

_SINK_METHODS = {
    "set_text", "set_tooltip_text", "set_label", "set_title", "set_markup",
    "set_placeholder_text", "set_body", "format_secondary_text",
    "set_program_name", "set_comments",
}

_SINK_CONSTRUCTORS = {
    "Label", "CheckButton", "Frame", "Button", "Dialog", "FileChooserDialog",
    "MenuItem", "MenuButton", "ColorChooserDialog", "ImageMenuItem", "MessageDialog",
}

_SINK_KWARGS = {"label", "title", "text", "secondary_text"}


@dataclass
class Violation:
    line: int
    message: str


def _line_has_noqa(source_lines: list[str], line: int) -> bool:
    if line - 1 >= len(source_lines):
        return False
    return "# noqa: i18n" in source_lines[line - 1]


def scan_source(source: str, filename: str = "<test>") -> list[Violation]:
    # Only ast.Constant string-literal arguments are ever flagged below
    # (not ast.Call, ast.BinOp, etc.) - this is what makes an
    # already-wrapped _("...") or _("...").format(...) argument
    # naturally pass through unflagged with no separate "is this
    # wrapped" check needed: neither is a bare Constant node.
    tree = ast.parse(source, filename=filename)
    source_lines = source.splitlines()
    violations: list[Violation] = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue

        # Gio.Notification.new("...") - first positional arg.
        if (
            isinstance(node.func, ast.Attribute)
            and node.func.attr == "new"
            and isinstance(node.func.value, ast.Attribute)
            and node.func.value.attr == "Notification"
        ):
            if node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                if not _line_has_noqa(source_lines, node.lineno):
                    violations.append(Violation(node.lineno, "unwrapped Gio.Notification.new(...) title"))
            continue

        # method_call sinks: widget.set_text("...")
        if isinstance(node.func, ast.Attribute) and node.func.attr in _SINK_METHODS:
            for arg in node.args:
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    if not _line_has_noqa(source_lines, node.lineno):
                        violations.append(Violation(node.lineno, f"unwrapped string in .{node.func.attr}(...)"))
            continue

        # constructor kwargs: Gtk.Label(label="...")
        callee_name = None
        if isinstance(node.func, ast.Attribute):
            callee_name = node.func.attr
        elif isinstance(node.func, ast.Name):
            callee_name = node.func.id
        if callee_name in _SINK_CONSTRUCTORS:
            for kw in node.keywords:
                if kw.arg in _SINK_KWARGS and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
                    if not _line_has_noqa(source_lines, node.lineno):
                        violations.append(Violation(node.lineno, f"unwrapped {kw.arg}= on {callee_name}(...)"))

    return violations
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/unit/test_i18n_scan.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add tests/unit/_i18n_scan.py tests/unit/test_i18n_scan.py
git commit -m "i18n phase 1: add sink-list AST scanner (test-only tooling)"
```

---

### Task 4: sweep - render.py, printing.py

**Files:**
- Modify: `src/orcshot/ui/render.py`, `src/orcshot/ui/printing.py`

**Grep to enumerate hits:**
```bash
grep -nE '\.(set_text|set_tooltip_text|set_label|set_title|set_markup|set_placeholder_text|set_body|format_secondary_text|set_program_name|set_comments)\(|Gtk\.(Label|CheckButton|Frame|Button|Dialog|FileChooserDialog|MenuItem|MenuButton|ColorChooserDialog|ImageMenuItem|MessageDialog)\([^)]*\b(label|title|text|secondary_text)=|Gio\.Notification\.new\(' src/orcshot/ui/render.py src/orcshot/ui/printing.py
```

**Worked examples:**
- `render.py:318` and `printing.py:100`: `layout.set_text(text, -1)` - this is `Pango.Layout.set_text()` rendering the user's own typed annotation text. **Do not wrap.** Add `# noqa: i18n (user-typed annotation text, not UI chrome)` on the line.
- `printing.py:156`: `Gtk.Dialog(title="Orcshot print options", ...)` -> `Gtk.Dialog(title=_("Orcshot print options"), ...)`
- `printing.py:162`: `Gtk.Frame(label="Page layout settings")` -> `Gtk.Frame(label=_("Page layout settings"))`
- `printing.py:165`: `Gtk.CheckButton(label="Shrink printout to fit paper size")` -> wrap the same way.

Apply the shared per-task steps (grep, wrap/exclude/trace, add import, test, commit) from the "Shared rule for every sweep task" section above.

- [ ] **Step 1-4: grep, wrap, add `from orcshot.i18n import _` to both files, run `.venv/bin/pytest tests/unit -q`**
- [ ] **Step 5: Commit**

```bash
git add src/orcshot/ui/render.py src/orcshot/ui/printing.py
git commit -m "i18n phase 1: wrap user-facing strings in render.py, printing.py"
```

---

### Task 5: sweep - destination_picker.py, first_run_setup.py

**Files:**
- Modify: `src/orcshot/ui/destination_picker.py`, `src/orcshot/ui/first_run_setup.py`

**Grep to enumerate hits:**
```bash
grep -nE '\.(set_text|set_tooltip_text|set_label|set_title|set_markup|set_placeholder_text|set_body|format_secondary_text|set_program_name|set_comments)\(|Gtk\.(Label|CheckButton|Frame|Button|Dialog|FileChooserDialog|MenuItem|MenuButton|ColorChooserDialog|ImageMenuItem|MessageDialog)\([^)]*\b(label|title|text|secondary_text)=|Gio\.Notification\.new\(' src/orcshot/ui/destination_picker.py src/orcshot/ui/first_run_setup.py
```

**Worked examples:**
- `destination_picker.py:159,203`: `Gtk.Clipboard.get_default(...).set_text(str(path), -1)` - copies a file path, not UI text. **Do not wrap.** Add `# noqa: i18n (clipboard data, not UI text)`.
- `destination_picker.py:183`: `Gtk.FileChooserDialog(title="Save Screenshot As", ...)` -> wrap with `_()` directly, it's a literal.
- `destination_picker.py:396`: `Gtk.Label(label=label)` - `label` is NOT a literal here, it's the second element of the `(item_id, label, handler)` tuples `_all_destinations()` yields (see the `for item_id, label, handler in _all_destinations():` loop a few lines above line 396). Read `_all_destinations()`'s own definition: it composes a list mixing static built-in destination names (e.g. "Quick Save", "Save As", "Copy to Clipboard") with dynamically-named entries (e.g. an `ExternalCommand.name`, which is user-configured data). Wrap only the static literal names at their point of definition inside `_all_destinations()`; leave any `command.name`-style dynamic entry alone (it's user data, not translatable source text).
- `first_run_setup.py:156`: `Gtk.Dialog(title="Orcshot Setup", transient_for=parent)` -> wrap directly.
- `first_run_setup.py:171`: `Gtk.CheckButton(label="Start automatically at login")` -> wrap directly.
- `first_run_setup.py:188`: `Gtk.CheckButton(label=label)` - trace `label`'s source the same way as `destination_picker.py:396` above before deciding.

- [ ] **Step 1-4: grep, wrap/exclude/trace, add import, test**
- [ ] **Step 5: Commit**

```bash
git add src/orcshot/ui/destination_picker.py src/orcshot/ui/first_run_setup.py
git commit -m "i18n phase 1: wrap user-facing strings in destination_picker.py, first_run_setup.py"
```

---

### Task 6: sweep - color_dialog.py, external_commands.py

**Files:**
- Modify: `src/orcshot/ui/color_dialog.py`, `src/orcshot/ui/external_commands.py`

**Grep to enumerate hits:**
```bash
grep -nE '\.(set_text|set_tooltip_text|set_label|set_title|set_markup|set_placeholder_text|set_body|format_secondary_text|set_program_name|set_comments)\(|Gtk\.(Label|CheckButton|Frame|Button|Dialog|FileChooserDialog|MenuItem|MenuButton|ColorChooserDialog|ImageMenuItem|MessageDialog)\([^)]*\b(label|title|text|secondary_text)=|Gio\.Notification\.new\(' src/orcshot/ui/color_dialog.py src/orcshot/ui/external_commands.py
```

**Worked examples:**
- `color_dialog.py:77`: `Gtk.Dialog(title="Select Color", transient_for=parent)` -> wrap directly.
- `color_dialog.py:105`: `hex_entry.set_text(_color_to_hex(state["color"]))` - a computed hex color string like `"#FF00AA"`, not translatable. **Do not wrap** (no noqa needed either - it's not a literal, the scanner won't flag it).
- `color_dialog.py:126`: `Gtk.Label(label="Recently used colors")` -> wrap directly.
- `color_dialog.py:149`: `Gtk.Label(label="Hex:")` -> wrap directly.
- `external_commands.py:556`: `name_entry.set_text(existing.name if existing else "")` - populating a text field with a user's existing config value or an empty string, not a UI label. **Do not wrap.**
- `external_commands.py:557`: `Gtk.Label(label="Name:", xalign=0)` -> wrap directly.
- `external_commands.py:561`: `command_entry.set_text(existing.commandline if existing else "")` - same as line 556, user data. **Do not wrap.**

- [ ] **Step 1-4: grep, wrap/exclude, add import, test**
- [ ] **Step 5: Commit**

```bash
git add src/orcshot/ui/color_dialog.py src/orcshot/ui/external_commands.py
git commit -m "i18n phase 1: wrap user-facing strings in color_dialog.py, external_commands.py"
```

---

### Task 7: sweep - app.py, text_obfuscation_dialog.py

**Files:**
- Modify: `src/orcshot/app.py`, `src/orcshot/ui/text_obfuscation_dialog.py`

**Grep to enumerate hits:**
```bash
grep -nE '\.(set_text|set_tooltip_text|set_label|set_title|set_markup|set_placeholder_text|set_body|format_secondary_text|set_program_name|set_comments)\(|Gtk\.(Label|CheckButton|Frame|Button|Dialog|FileChooserDialog|MenuItem|MenuButton|ColorChooserDialog|ImageMenuItem|MessageDialog)\([^)]*\b(label|title|text|secondary_text)=|Gio\.Notification\.new\(' src/orcshot/app.py src/orcshot/ui/text_obfuscation_dialog.py
```

**Worked examples:**
- `app.py:918`: `indicator.set_title("Orcshot")` - a proper noun (the app's own name). Add `# noqa: i18n (proper noun)`.
- `app.py:925`: `icon.set_tooltip_text("Orcshot")` - same, `# noqa: i18n (proper noun)`.
- `app.py:970`: `Gtk.ImageMenuItem(label=label)` - trace `label`'s source the same way as Task 5's destination-list cases.
- `app.py:1171`: `f"You're running the latest version ({installed_version('orcshot')})."` passed to `secondary_text=` - convert the f-string first: `_("You're running the latest version ({}).").format(installed_version('orcshot'))`, then use that as `secondary_text=`.
- `app.py:1162`: `secondary_text="No response from GitHub - check your network connection and try again."` -> wrap directly, no dynamic content.
- `text_obfuscation_dialog.py:135`: `dialog.format_secondary_text(secondary)` - trace `secondary`'s source (likely a variable built from a literal a few lines up); wrap at its actual definition site if it's static text.
- `text_obfuscation_dialog.py:199`: `Gtk.Dialog(title=_DIALOG_TITLE, transient_for=editor)` - `_DIALOG_TITLE` is a module-level constant; find its definition (`grep -n "_DIALOG_TITLE\s*=" src/orcshot/ui/text_obfuscation_dialog.py`) and wrap the literal there: `_DIALOG_TITLE = _("...")`.
- `text_obfuscation_dialog.py:218`: `self._search_entry.set_placeholder_text("Search text (min. 3 characters)...")` -> wrap directly.

- [ ] **Step 1-4: grep, wrap/exclude/trace, add import, test**
- [ ] **Step 5: Commit**

```bash
git add src/orcshot/app.py src/orcshot/ui/text_obfuscation_dialog.py
git commit -m "i18n phase 1: wrap user-facing strings in app.py, text_obfuscation_dialog.py"
```

---

### Task 8: sweep - editor_window.py, lines 1-1400 (module helpers + early EditorWindow methods)

**Files:**
- Modify: `src/orcshot/ui/editor_window.py` (lines 1-1400 only - later line ranges are separate tasks below, to keep each task independently reviewable on a file this large)

**Grep to enumerate hits in this range:**
```bash
sed -n '1,1400p' src/orcshot/ui/editor_window.py | grep -nE '\.(set_text|set_tooltip_text|set_label|set_title|set_markup|set_placeholder_text|set_body|format_secondary_text|set_program_name|set_comments)\(|Gtk\.(Label|CheckButton|Frame|Button|Dialog|FileChooserDialog|MenuItem|MenuButton|ColorChooserDialog|ImageMenuItem|MessageDialog)\([^)]*\b(label|title|text|secondary_text)=|Gio\.Notification\.new\('
```
(Line numbers from this command are relative to line 1 of the extract, i.e. already correct against the real file since the range starts at line 1.)

**Worked examples:**
- Line 603: `Gtk.Label(label=label)` - a module-level helper `_icon_menu_item(label: str, icon_image: Gtk.Image, handler)` (see line 577) takes `label` as a parameter; this is a shared UI-chrome-building helper called from many places with literal label strings - do **not** wrap inside the helper itself (it's a passthrough), instead find every *caller* of `_icon_menu_item(...)` in this line range and wrap the literal argument they pass in.
- Line 1376: `self._obfuscate_amount_label.set_text(self._obfuscate_amount_label_text(amount_tool))` - trace `_obfuscate_amount_label_text`'s own definition (`grep -n "_obfuscate_amount_label_text" src/orcshot/ui/editor_window.py`); if it returns something like `f"Amount: {amount}"`, convert to `_("Amount: {}").format(amount)` inside that helper. If it's purely numeric, leave it and note why in the commit.
- Line 1400: `self._obfuscate_fill_text_button.set_label(self._obfuscate_fill_text_label(fill_text))` - same tracing pattern as line 1376, different helper (`_obfuscate_fill_text_label`).

- [ ] **Step 1-4: grep (scoped to this line range), wrap/exclude/trace, ensure `from orcshot.i18n import _` is present once near the top of the file (not per-range - it's one file), test**
- [ ] **Step 5: Commit**

```bash
git add src/orcshot/ui/editor_window.py
git commit -m "i18n phase 1: wrap user-facing strings in editor_window.py (module helpers + early methods)"
```

---

### Task 9: sweep - editor_window.py, lines 1400-2800

**Files:**
- Modify: `src/orcshot/ui/editor_window.py` (lines 1400-2800)

**Grep to enumerate hits in this range:**
```bash
sed -n '1400,2800p' src/orcshot/ui/editor_window.py | grep -n -E '\.(set_text|set_tooltip_text|set_label|set_title|set_markup|set_placeholder_text|set_body|format_secondary_text|set_program_name|set_comments)\(|Gtk\.(Label|CheckButton|Frame|Button|Dialog|FileChooserDialog|MenuItem|MenuButton|ColorChooserDialog|ImageMenuItem|MessageDialog)\([^)]*\b(label|title|text|secondary_text)=|Gio\.Notification\.new\(' | awk -F: '{printf "%d:%s\n", $1+1399, substr($0, index($0,$2))}'
```
(This adds the 1399-line offset back so the printed line numbers match the real file directly.)

**Worked examples (real file line numbers):**
- Line ~1415: `self._obfuscate_mode_button.set_label(self._obfuscate_mode_label(obfuscate_mode_tool))` - same helper-tracing pattern as Task 8's line 1376/1400 examples; find `_obfuscate_mode_label`'s definition and wrap/exclude there.
- Line ~1422: `self._highlight_mode_button.set_label(self._highlight_mode_label(highlight_mode_tool))` - same pattern, `_highlight_mode_label`.

- [ ] **Step 1-4: grep (scoped), wrap/exclude/trace, test**
- [ ] **Step 5: Commit**

```bash
git add src/orcshot/ui/editor_window.py
git commit -m "i18n phase 1: wrap user-facing strings in editor_window.py (lines 1400-2800)"
```

---

### Task 10: sweep - editor_window.py, lines 2800-4200

**Files:**
- Modify: `src/orcshot/ui/editor_window.py` (lines 2800-4200)

**Grep to enumerate hits in this range:**
```bash
sed -n '2800,4200p' src/orcshot/ui/editor_window.py | grep -n -E '\.(set_text|set_tooltip_text|set_label|set_title|set_markup|set_placeholder_text|set_body|format_secondary_text|set_program_name|set_comments)\(|Gtk\.(Label|CheckButton|Frame|Button|Dialog|FileChooserDialog|MenuItem|MenuButton|ColorChooserDialog|ImageMenuItem|MessageDialog)\([^)]*\b(label|title|text|secondary_text)=|Gio\.Notification\.new\(' | awk -F: '{printf "%d:%s\n", $1+2799, substr($0, index($0,$2))}'
```

**Worked examples (real file line numbers):**
- Line ~2805: `Gtk.Label(label="Mode:")` -> wrap directly.
- Line ~2806: `Gtk.MenuButton(label=self._highlight_mode_label(self._default_highlight_mode))` - trace `_highlight_mode_label` (same helper as Task 9's example - only wrap its internals once, don't duplicate the change if Task 9 already handled it; check with `grep -n "def _highlight_mode_label" src/orcshot/ui/editor_window.py` first).
- Line ~2810: `Gtk.Label(label="Fill:")` -> wrap directly.

- [ ] **Step 1-4: grep (scoped), wrap/exclude/trace, test**
- [ ] **Step 5: Commit**

```bash
git add src/orcshot/ui/editor_window.py
git commit -m "i18n phase 1: wrap user-facing strings in editor_window.py (lines 2800-4200)"
```

---

### Task 11: sweep - editor_window.py, lines 4200-5225 (end of EditorWindow class)

**Files:**
- Modify: `src/orcshot/ui/editor_window.py` (lines 4200-5225)

**Grep to enumerate hits in this range:**
```bash
sed -n '4200,5225p' src/orcshot/ui/editor_window.py | grep -n -E '\.(set_text|set_tooltip_text|set_label|set_title|set_markup|set_placeholder_text|set_body|format_secondary_text|set_program_name|set_comments)\(|Gtk\.(Label|CheckButton|Frame|Button|Dialog|FileChooserDialog|MenuItem|MenuButton|ColorChooserDialog|ImageMenuItem|MessageDialog)\([^)]*\b(label|title|text|secondary_text)=|Gio\.Notification\.new\(' | awk -F: '{printf "%d:%s\n", $1+4199, substr($0, index($0,$2))}'
```

**Worked examples (real file line numbers):**
- Line ~4303: `self._zoom_label.set_text(zoom_percent_label(self._zoom))` - trace `zoom_percent_label`'s definition (likely in `render.py` or a helpers module - `grep -rn "def zoom_percent_label" src/orcshot/`); if it returns something purely numeric like `f"{percent}%"`, **do not wrap** (numeric only, matches the exclusion category), add `# noqa: i18n (numeric only)` at its own definition site if it's a literal there, or just leave alone if it's pure f-string formatting with no static text component.
- Line ~4354: `self._dimensions_label = Gtk.Label(label=f"{img_w} x {img_h}")` - purely numeric dimensions display. **Do not wrap** - convert to a `# noqa: i18n (numeric only)` comment on this line since the scanner would otherwise need the f-string converted to see inside it (an f-string itself isn't flagged by the scanner from Task 3, since it only matches `ast.Constant` string literals, not `ast.JoinedStr` - so no noqa is strictly required here for the scanner to pass, but add the comment anyway for a future human reader's clarity).

- [ ] **Step 1-4: grep (scoped), wrap/exclude/trace, test**
- [ ] **Step 5: Commit**

```bash
git add src/orcshot/ui/editor_window.py
git commit -m "i18n phase 1: wrap user-facing strings in editor_window.py (lines 4200-5225)"
```

---

### Task 12: sweep - editor_window.py, lines 5226-6012 (Preferences dialog tabs)

**Files:**
- Modify: `src/orcshot/ui/editor_window.py` (lines 5226-6012 - the `_build_general_settings_tab`/`_build_capture_settings_tab`/`_build_output_settings_tab`/`_build_destinations_settings_tab`/`_build_printer_settings_tab` functions and the `show_preferences_dialog`/file-chooser helper functions above them)

**Grep to enumerate hits in this range:**
```bash
sed -n '5226,6012p' src/orcshot/ui/editor_window.py | grep -n -E '\.(set_text|set_tooltip_text|set_label|set_title|set_markup|set_placeholder_text|set_body|format_secondary_text|set_program_name|set_comments)\(|Gtk\.(Label|CheckButton|Frame|Button|Dialog|FileChooserDialog|MenuItem|MenuButton|ColorChooserDialog|ImageMenuItem|MessageDialog)\([^)]*\b(label|title|text|secondary_text)=|Gio\.Notification\.new\(' | awk -F: '{printf "%d:%s\n", $1+5225, substr($0, index($0,$2))}'
```

**Worked examples (real file line numbers):**
- Line 5239: `Gtk.FileChooserDialog(title="Open", transient_for=transient_for, action=Gtk.FileChooserAction.OPEN)` -> wrap directly.
- Line 5278: `error_dialog.format_secondary_text(str(exc))` - `str(exc)` is an exception's own message, dynamic and not a literal. **Do not wrap** the call itself; however check whether `exc` is one this codebase raises with a literal message (e.g. `raise ValueError("Could not open file")`) - if so, that raise site's own literal message string is a separate, real user-facing string worth wrapping at its source, out of scope for this specific line but worth noting in the commit message if found.
- Line 5337: `Gtk.Dialog(title="Preferences", transient_for=parent)` -> wrap directly.
- Around line 5354-5608 (`_build_general_settings_tab` through `_build_output_settings_tab`): the five tab-label literals found earlier this session (`Gtk.Label(label="General")`, `"Capture"`, `"Output"`, `"Destinations"`, `"Printer"`) live just above this range at line 5343-5347 (inside the caller that builds the `Gtk.Notebook`, not inside these tab-content functions themselves) - confirm with `grep -n 'Gtk.Label(label="General")' src/orcshot/ui/editor_window.py` and wrap those five directly if they fall inside this task's line range; if they land in Task 11's range instead per the actual grep output, wrap them there.

- [ ] **Step 1-4: grep (scoped), wrap/exclude/trace, test**
- [ ] **Step 5: Commit**

```bash
git add src/orcshot/ui/editor_window.py
git commit -m "i18n phase 1: wrap user-facing strings in editor_window.py (Preferences dialog tabs)"
```

---

### Task 13: verify the zero-hit files have no missed strings

**Files:**
- Modify (only if something is found): any of `src/orcshot/ui/composite.py`, `gdk_convert.py`, `cairo_convert.py`, `magnifier.py`, `monitor_window.py`, `window_picker.py`, `window_picker_wayland.py`, `window_picker_gnome_shell.py`, `region_select.py`, `region_select_wayland.py`, `region_select_gnome_shell.py`, `eyedropper.py`, `eyedropper_wayland.py`, `effects.py`, `orcshot_file.py`, `file_export.py`, `capture_modes.py`, `icons.py`, `ocr.py`, `update_check.py`

These files showed zero hits under the single-line grep used to scope Tasks 4-12, which undercounts multi-line calls and variable indirection - this task exists specifically to confirm that's a true zero, not a grep blind spot, before relying on it.

- [ ] **Step 1: Run a broader, multi-line-aware check using Python's own ast module (catches what grep can't)**

```bash
.venv/bin/python3 -c "
from tests.unit._i18n_scan import scan_source
from pathlib import Path

files = [
    'composite.py', 'gdk_convert.py', 'cairo_convert.py', 'magnifier.py',
    'monitor_window.py', 'window_picker.py', 'window_picker_wayland.py',
    'window_picker_gnome_shell.py', 'region_select.py', 'region_select_wayland.py',
    'region_select_gnome_shell.py', 'eyedropper.py', 'eyedropper_wayland.py',
    'effects.py', 'orcshot_file.py', 'file_export.py', 'capture_modes.py',
    'icons.py', 'ocr.py', 'update_check.py',
]
for name in files:
    path = Path('src/orcshot/ui') / name
    violations = scan_source(path.read_text(), filename=str(path))
    for v in violations:
        print(f'{path}:{v.line}: {v.message}')
"
```

- [ ] **Step 2: For each line printed (if any), apply the same wrap-or-exclude decision as the sweep tasks above**, then re-run the check to confirm it's now silent.

- [ ] **Step 3: Also check `ui/icons.py` and `ui/render.py`'s cairo `show_text(...)` calls by hand** (the AST scanner doesn't cover Cairo drawing calls, only the enumerated GTK/Gio sink list) - confirm each one renders purely numeric/coordinate content (as already established for `region_select.py`, `eyedropper.py`, `region_select_wayland.py`, `eyedropper_wayland.py` during planning) rather than natural-language text. Run: `grep -n "show_text(" src/orcshot/ui/icons.py src/orcshot/ui/render.py` and inspect each hit's source `text` variable.

- [ ] **Step 4: Run the full suite**

Run: `.venv/bin/pytest tests/unit -q`
Expected: same pass count as before this task (or higher, if Step 2 found and fixed something real).

- [ ] **Step 5: Commit** (even if no code changed, commit a short note - or skip the commit entirely if genuinely nothing was found; don't create an empty commit)

```bash
git add -A
git commit -m "i18n phase 1: verify remaining ui/ files have no unwrapped user-facing strings" --allow-empty-message 2>/dev/null || echo "nothing to commit - verification found no gaps"
```

---

### Task 14: wire the scanner into a real acceptance test (final task)

**Files:**
- Create: `tests/unit/test_i18n_coverage.py`

**Interfaces:**
- Consumes: `scan_source` from Task 3's `tests/unit/_i18n_scan.py`.

This is the actual regression guard from the spec - it only goes green once every sweep task (4-13) above is complete, which is why it's the last task in the plan.

- [ ] **Step 1: Write the test**

```python
"""The i18n regression guard (i18n phase 1) - fails if any in-scope
file has a string literal reaching a known GTK/Gio text-setting sink
without going through _()/ngettext(), per the sink list in
docs/superpowers/specs/2026-08-23-i18n-phase1-gettext-infrastructure-design.md.
Runs as a normal part of the suite, so it's already enforced everywhere
pytest already runs, including debian/rules' own override_dh_auto_test
at package-build time - no new CI/packaging wiring needed.
"""

from pathlib import Path

from tests.unit._i18n_scan import scan_source

_REPO_ROOT = Path(__file__).parent.parent.parent
_IN_SCOPE_FILES = sorted((_REPO_ROOT / "src" / "orcshot" / "ui").glob("*.py")) + [
    _REPO_ROOT / "src" / "orcshot" / "app.py",
]


class TestI18nCoverage:
    def test_no_unwrapped_user_facing_strings_remain(self):
        all_violations = []
        for path in _IN_SCOPE_FILES:
            for violation in scan_source(path.read_text(), filename=str(path)):
                all_violations.append(f"{path.relative_to(_REPO_ROOT)}:{violation.line}: {violation.message}")
        assert all_violations == [], "\n".join(all_violations)
```

- [ ] **Step 2: Run it**

Run: `.venv/bin/pytest tests/unit/test_i18n_coverage.py -v`
Expected: PASS. If it fails, the output lists exactly which file:line still needs a wrap or a `# noqa: i18n` - go fix those specific lines (this means an earlier sweep task missed something; fix it in the relevant file, no need to reopen the earlier task).

- [ ] **Step 3: Run the full suite one more time**

Run: `.venv/bin/pytest tests/unit -q`
Expected: all green, same or higher pass count than before Task 1 (higher because of the new tests added in Tasks 1-3 and 14).

- [ ] **Step 4: Commit**

```bash
git add tests/unit/test_i18n_coverage.py
git commit -m "i18n phase 1: add the sink-list regression guard as a real acceptance test"
```

- [ ] **Step 5: Close out BACKLOG.md and REQUIREMENTS.md**, matching this project's established per-task documentation pattern (see REQUIREMENTS.md's existing "Task #NNN" entries for the format): remove/replace #173's BACKLOG.md entry to note phase 1 is done and phase 2 (actual translations) is the deliberately-deferred remainder, and add a REQUIREMENTS.md write-up covering what was built, the two false-positive sink-list refinements found during planning (Pango.Layout.set_text, Gtk.Clipboard.set_text), and the final test count.
