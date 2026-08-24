# i18n Phase 1: gettext infrastructure - design

Status: approved by direflail, 2026-08-23. Successor work item to BACKLOG.md #173.

## Goal

Give orcshot real, standard Linux i18n infrastructure - every genuinely user-facing string
routed through `gettext`'s `_()` - without yet authoring any actual translation beyond
English. This phase is deliberately infrastructure-only: it makes the codebase translatable
and guards against regression, and stops there. Actually translating into other languages
(authoring real `.po` files) is out of scope, tracked as a separate future phase.

## Why this shape

orcshot currently has zero i18n infrastructure - every user-facing string across `ui/` and
`app.py` is a hardcoded English literal (BACKLOG.md #173, originally scoped in task #93,
2026-08-10: "a foundational rework... touches nearly every file under ui/"). Real Greenshot
ships 39 translated languages via its own bespoke XML resource scheme; orcshot has nothing
comparable. `gettext` (`.po`/`.mo`, `_()` wrapping) is the standard Linux/GTK convention,
chosen over inventing a bespoke resource format because it composes naturally with the
existing Debian packaging rather than needing new build tooling of its own.

## Scope

**In scope:** every genuinely user-facing string across the `ui/` tree (29 files) *and*
outside it wherever real user-facing text is produced - `app.py`'s notification bodies and
tray menu labels, and any `capture/`/`core/` exception message that actually reaches a
dialog or notification (not just an internal log). This is wider than BACKLOG #173's literal
wording ("ui/"), an explicit scope decision made during brainstorming: leaving app.py's
notification text out would ship phase 1 with a known, immediately-visible gap.

**Explicitly not wrapped** (the same line the sink-list guard encodes, see below): GSettings/
dconf keys, D-Bus interface/method names, file paths, `print(..., file=sys.stderr)`
diagnostics, CSS class names, config JSON keys, log messages - any quoted literal that's
never actually shown to a person.

**Out of scope for this phase:**
- Authoring any real non-English `.po` file/translation
- An in-app language-preference override (see "Language selection" below)
- Plural-form (`ngettext`) usage, unless the sweep finds a string that genuinely needs it
- Any change to `debian/rules` or `debian/control` (nothing new is installed or built at
  package time in this phase - see "Extraction tooling")

## Architecture

### Wrapper module

New `src/orcshot/i18n.py`. Binds `_` (and `ngettext`, if the sweep finds a real plural-form
need) once at import time:

```python
import gettext
from pathlib import Path

_LOCALE_DIR = Path(__file__).parent / "resources" / "locale"
_translation = gettext.translation("orcshot", localedir=_LOCALE_DIR, fallback=True)
_ = _translation.gettext
ngettext = _translation.ngettext
```

`localedir` reuses the existing `RESOURCES_DIR` convention (`Path(__file__).parent /
"resources"`, already used for icons/`magnifier_constants.json`) instead of the system
`/usr/share/locale/` path - this is the same trick that already makes that constant resolve
identically in a dev checkout and an installed `.deb`, so no separate dev/production
path-resolution logic is needed here either.

`fallback=True` means: when no matching `.mo` catalog is found (true for every locale in this
phase, since zero `.mo` files are shipped), `_()` returns its argument unchanged. This is
built-in `gettext` behavior, not something this module implements.

### Language selection

`gettext.translation(..., languages=None)` (the call above) uses standard `gettext`
environment-variable negotiation: `$LANGUAGE`, then `$LC_ALL`, `$LC_MESSAGES`, `$LANG` (first
one set wins), matched against whatever locale directories exist under `_LOCALE_DIR`. This
follows the established GTK/GNOME desktop convention (change language system-wide via
Settings > Region & Language, or per-app via `LANGUAGE=fr_FR command`) rather than real
Greenshot's own in-app language dropdown, which is more a Windows-ism than a Linux one.

Deliberately no in-app language-preference override in this phase: with zero real
translations shipped, a picker would have exactly one working option and nothing to test
against. Revisit once phase 2 (actual translations) gives it something real to select
between - not a decision this phase needs to make.

Since no `.mo` files exist yet, this whole mechanism is currently inert: regardless of the
system locale, every lookup misses and `fallback=True` always returns the raw English string.

## Extraction tooling

A new dev-only script, `scripts/extract_pot.sh`:

```bash
#!/bin/sh
set -e
xgettext --language=Python --keyword=_ --keyword=ngettext:1,2 \
    --output=po/orcshot.pot \
    $(find src/orcshot -name '*.py')
```

Generates `po/orcshot.pot` - a template ready for a future translator to copy into a real
`.po` file. Not itself shipped, installed, or referenced at runtime.

Following the same precedent this project already set with Semgrep ("release tooling, not an
app dependency" - RELEASING.md's Security check step), this is a manual dev utility: it does
**not** add `gettext` to `debian/control`'s `Build-Depends`, and does **not** touch
`pyproject.toml`. Since phase 1 compiles and installs zero `.mo` catalogs, `debian/rules`
needs zero changes in this phase. Real per-language `.po`/`.mo` compilation and packaging
(`msgfmt`, install paths, `Build-Depends: gettext`) is deferred entirely to whenever phase 2
(actual translations) happens.

## The wrapping sweep

Mechanical per-string conversion across every in-scope file:

- Plain literal: `Gtk.Label(label="Preferences")` -> `Gtk.Label(label=_("Preferences"))`
- Dynamic content: `xgettext` cannot extract through an f-string at all (the pieces are
  gone by the time it's a string constant), so a real example already in the codebase -
  `app.py:1171`'s `f"You're running the latest version ({installed_version('orcshot')})."` -
  must become `_("You're running the latest version ({}).").format(installed_version('orcshot'))`
  - a real per-string transformation, not just a wrap. Plain positional `{}` placeholders are
  fine for this phase (no real translator to need reordering yet); upgrading to named
  placeholders is a cheap future fast-follow, not something to solve preemptively here.
- Strings excluded per the "explicitly not wrapped" list above are left untouched.

Given the real size (roughly 300-500 individual wrap-edits across ~30 files, confirmed via a
rough grep during brainstorming), land this as several focused commits grouped by related
files, not one giant diff - matches how every other change has been committed this session.

## The regression guard

New `tests/unit/test_i18n_coverage.py`, run as a normal part of the suite (so it's already
enforced everywhere `pytest` already runs, including `debian/rules`' own
`override_dh_auto_test` at package-build time - zero new CI/packaging wiring needed).

**Sink-list based, not text-shape-heuristic based** - this was an explicit correction made
during brainstorming. A heuristic like "flag any capitalized string containing a space" would
systematically miss exactly the strings that matter most: short single-word labels with no
space ("OK", "Cancel", "Save", "Apply", "Close", "Quit"), and strings passed through a
variable instead of a literal argument. A sink-list approach doesn't care what the string
*looks like*, only *where it's used* - it catches "OK" exactly the same as a full sentence.

The sink list, grounded in this codebase's actual current usage (via a real grep sweep during
brainstorming, not a generic assumed list - two rounds of it, since the first pass missed
`Gtk.MessageDialog`'s `.format_secondary_text()` and `Gtk.AboutDialog`'s `set_program_name`/
`set_comments` entirely, both confirmed as real call sites already in the codebase):

- Method calls: `set_text`, `set_tooltip_text`, `set_label`, `set_title`, `set_markup`,
  `set_placeholder_text`, `set_body`, `format_secondary_text`, `set_program_name`,
  `set_comments`
- Constructor kwargs (`label=`, `title=`, `text=`, `secondary_text=`) on: `Gtk.Label`,
  `Gtk.CheckButton`, `Gtk.Frame`, `Gtk.Button`, `Gtk.Dialog`, `Gtk.FileChooserDialog`,
  `Gtk.MenuItem`, `Gtk.MenuButton`, `Gtk.ColorChooserDialog`, `Gtk.ImageMenuItem`,
  `Gtk.MessageDialog`
- `Gio.Notification.new(...)` (first positional argument)

Confirms the `# noqa: i18n` escape hatch isn't just theoretical: `editor_window.py`'s
`dialog.set_program_name("Orcshot")` matches this sink shape but is a proper noun that must
never be translated - a real example of a string that needs the exemption, not a wrap.

**A more serious false-positive found during implementation planning:** `set_text` as a bare
method name is too broad a sink signal on its own. `render.py`/`printing.py`'s
`layout.set_text(text, -1)` is `Pango.Layout.set_text()` rendering the *user's own typed
annotation text* onto the canvas, not application UI chrome - wrapping it would try to
`gettext`-translate arbitrary user content, which is nonsensical and would silently corrupt
behavior once a real catalog exists. `destination_picker.py`'s
`Gtk.Clipboard.get_default(...).set_text(str(path), -1)` is the same method name copying a
*file path* to the clipboard - also not translatable text. Both share the identical method
name with the legitimate `Gtk.Entry`/`Gtk.Label` UI-chrome sinks, so a name-only AST matcher
can't distinguish them without real type inference. Resolution: these specific call sites get
an explicit `# noqa: i18n` with a stated reason, rather than teaching the scanner
receiver-type inference - two known, permanent exceptions are simpler than a more complex
scanner for a distinction that doesn't otherwise come up.

Also excluded on the same "not natural language" grounds as the Cairo `show_text` coordinate
overlays already covered under "explicitly not wrapped": purely numeric labels like
`editor_window.py`'s `Gtk.Label(label=f"{img_w} x {img_h}")` (image dimensions) and its zoom
percentage label - digits and punctuation only, nothing for a translator to translate.

Several sink call sites take the return value of a helper function
(`self._obfuscate_amount_label_text(amount_tool)`, `zoom_percent_label(self._zoom)`,
`self._highlight_mode_label(...)`) rather than a literal directly - for these, the actual
wrap (or exclusion, if it turns out to be numeric-only like the zoom/dimensions labels above)
belongs inside the helper function's own definition, not at the widget-construction call
site. The sweep needs to trace every non-literal argument at a sink call site back to its
source before deciding wrap vs. exclude, not just skip anything that isn't a bare string
literal.

The AST walker flags any string-literal argument at one of these sink call sites that isn't
wrapped in `_()`/`ngettext()` (or a `.format()` call on one, for the f-string-conversion
case) and isn't exempted via an inline `# noqa: i18n` comment on that line - the same
escape hatch this project already uses `flake8`-style comments for elsewhere. Since the guard
is added *after* the sweep has already cleared every current false positive, whatever it
flags at introduction time gets a one-time `# noqa: i18n` if it's a legitimately technical
string that happens to match a sink's shape; from then on its only job is catching new
unwrapped text.

The sink list is expected to need occasional one-line additions as new widget-construction
patterns get introduced, but starts complete for everything currently in use.

## Testing plan

Since this phase ships zero real translations, `_()` always falls back to the literal English
string - every existing test that asserts on UI text keeps passing unchanged, no existing
test rewrites required by the sweep itself. Three new things get direct coverage:

1. `i18n.py`'s wrapper: `_("x")` returns `"x"` unchanged with no catalog installed (the
   fallback path), plus one test installing a synthetic `.mo` in a temp locale directory to
   prove real substitution *would* work once a translation exists - the one genuinely new
   runtime behavior this phase introduces.
2. The sink-list guard test itself (`tests/unit/test_i18n_coverage.py`).
3. A light smoke test that `scripts/extract_pot.sh` runs clean and produces a non-empty
   `.pot` file, catching a broken `xgettext` invocation early.
