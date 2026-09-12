# XApp Status Icon Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** On Cinnamon, replace the Cinnamon applet with an `XApp.StatusIcon` owned by the app — the same tray icon kind as every other status icon on a Mint panel, no About/Remove — and retire the applet and everything packaged for it.

**Architecture:** One new module `ui/xapp_tray.py` builds a `Gtk.Menu` from the `Gio.Menu` the app already exports for the GNOME tray, in front of a proxy action group that pops the menu down and forwards each action 150 ms later (so a capture never contains the menu), and wraps it in an `XApp.StatusIcon`. `app.py` creates it on Cinnamon after exporting the tray menu. Packaging adds `gir1.2-xapp-1.0` to the `.deb` and Warpinator's `xapps` module plus two bus-name grants to the Flatpak. Spec: `docs/superpowers/specs/2026-09-12-xapp-status-icon-design.md`.

**Tech Stack:** Python 3 / PyGObject (Gtk 3, Gio, GLib, XApp 1.0), libxapp 3.2.x, pytest, flatpak-builder, debhelper.

## Global Constraints

- Cinnamon is detected with `hotkey_setup.cinnamon_keybindings_available()`, nothing else. GNOME keeps the Shell extension; Snap is untouched.
- The XApp menu is built from `app._tray_menu` — the same `Gio.Menu` `_export_tray_menu` exports — never a second menu definition.
- Menu items must pop the menu down and forward the real action after **150 ms** (`delay_ms=150`); left-click on the icon activates `tray-region`.
- Icon name `orcshot`, tooltip `Orcshot`; the bus name is `org.x.StatusIcon.orcshot` (derived from the program name by libxapp — do not set `name` to anything else).
- Flatpak: module `xapps` from `https://github.com/linuxmint/xapp.git` tag `3.2.2`, meson, `-Dapp-lib-only=true`, `-Dpy-overrides-dir=/app/lib/python3.13/site-packages/gi/overrides`; finish-args `--own-name=org.x.StatusIcon.orcshot` and `--talk-name=org.x.StatusIconMonitor.*`. `flatpak-builder-lint manifest` stays clean.
- `.deb`: `Depends:` gains `gir1.2-xapp-1.0`; the two `cinnamon-applets` lines leave `debian/orcshot.install`.
- A missing `XApp` typelib is one `[orcshot]` stderr line and no icon — never a crash.
- `.venv/bin/pytest tests/ -q` stays green after every task; `po/orcshot.pot` regenerated with `scripts/extract_pot.sh` if user-facing strings change (only "Orcshot" here, already present).
- Commit after every task; messages end with `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`. Branch off `main`.

---

## File map

| Path | Responsibility | Task |
|---|---|---|
| `src/orcshot/ui/xapp_tray.py` (new) | `build_menu(model, forward, delay_ms)` and `create_status_icon(app)` | 1 |
| `tests/unit/ui/test_xapp_tray.py` (new) | proxy delay/forward, action-name mapping, missing-XApp path | 1 |
| `src/orcshot/app.py` | create the icon on Cinnamon in `do_startup` | 2 |
| `src/orcshot/resources/cinnamon-applets/` (deleted), `debian/orcshot.install`, `debian/control`, docstrings | retire the applet, add the dependency | 3 |
| `org.orcshot.Orcshot.yaml` | `xapps` module + two finish-args | 4 |
| Mint host | live acceptance for `.deb`-equivalent (dev checkout) and Flatpak | 5 |
| `BACKLOG.md`, `VERIFICATION.md` | resolve #208, record the scenario | 5 |

---

### Task 1: `ui/xapp_tray.py` — the menu proxy and the icon factory

**Files:**
- Create: `src/orcshot/ui/xapp_tray.py`
- Test: `tests/unit/ui/test_xapp_tray.py`

**Interfaces:**
- Consumes: nothing project-specific beyond `orcshot.i18n._`.
- Produces:
  ```python
  def build_menu(model: Gio.MenuModel, forward: Callable[[str], None], delay_ms: int = 150) -> Gtk.Menu
  def proxy_action_names(model: Gio.MenuModel) -> list[str]     # bare names of every "app.<name>" action the model references, depth-first, no duplicates
  def create_status_icon(app) -> "XApp.StatusIcon | None"        # app has ._tray_menu (Gio.Menu) and .activate_action(name, param)
  ```

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/ui/test_xapp_tray.py
"""Pure coverage for ui/xapp_tray.py. Gtk is initialised headless
(Gtk.init_check) - a Gtk.Menu can be built without a display; only
showing it needs one. XApp itself is never imported here: the icon
factory is tested for its no-XApp path, and the real icon is verified
live on a Cinnamon panel (VERIFICATION.md)."""

import gi

gi.require_version("Gio", "2.0")
gi.require_version("GLib", "2.0")
gi.require_version("Gtk", "3.0")
from gi.repository import Gio, GLib, Gtk
import pytest

from orcshot.ui import xapp_tray


def _model():
    menu = Gio.Menu()
    section = Gio.Menu()
    section.append("Capture Region", "app.tray-region")
    section.append("Capture Full Screen", "app.tray-full_screen")
    menu.append_section(None, section)
    menu.append("Quit", "app.tray-quit")
    return menu


def _spin(ms):
    loop = GLib.MainLoop()
    GLib.timeout_add(ms, loop.quit)
    loop.run()


def test_proxy_action_names_walks_sections_without_duplicates():
    assert xapp_tray.proxy_action_names(_model()) == ["tray-region", "tray-full_screen", "tray-quit"]


def test_build_menu_forwards_after_the_delay_not_synchronously():
    Gtk.init_check([])
    forwarded = []
    menu = xapp_tray.build_menu(_model(), forwarded.append, delay_ms=50)
    group = menu.get_action_group("app")
    assert set(group.list_actions()) == {"tray-region", "tray-full_screen", "tray-quit"}
    group.activate_action("tray-full_screen", None)
    assert forwarded == []            # nothing yet - the menu is still popping down
    _spin(120)
    assert forwarded == ["tray-full_screen"]


def test_build_menu_default_delay_is_150ms():
    Gtk.init_check([])
    forwarded = []
    menu = xapp_tray.build_menu(_model(), forwarded.append)
    menu.get_action_group("app").activate_action("tray-region", None)
    _spin(100)
    assert forwarded == []            # 100 ms < 150 ms
    _spin(100)
    assert forwarded == ["tray-region"]


def test_create_status_icon_without_xapp_returns_none_and_logs(monkeypatch, capsys):
    import gi as gi_module
    real = gi_module.require_version

    def refuse(namespace, version):
        if namespace == "XApp":
            raise ValueError("Namespace XApp not available")
        return real(namespace, version)

    monkeypatch.setattr(gi_module, "require_version", refuse)

    class App:
        _tray_menu = _model()
        def activate_action(self, name, param): pass

    assert xapp_tray.create_status_icon(App()) is None
    assert "XApp" in capsys.readouterr().err
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/unit/ui/test_xapp_tray.py -q`
Expected: `ModuleNotFoundError: No module named 'orcshot.ui.xapp_tray'`

- [ ] **Step 3: Write the module**

```python
# src/orcshot/ui/xapp_tray.py
"""The Cinnamon tray: an XApp.StatusIcon owned by this process, showing
the same Gio.Menu the GNOME Shell extension renders. Replaces the
Cinnamon applet (BACKLOG #208): a Cinnamon applet always carries
Cinnamon's own About/Remove entries, a status icon does not, and a
status icon needs nothing installed on any channel.

Two things were verified on a real Cinnamon panel before this existed
(spec docs/superpowers/specs/2026-09-12-xapp-status-icon-design.md):
Gtk.Menu.new_from_model renders the model's per-item icons, and a
capture started from the menu contains the menu unless the menu is
popped down and the action delayed - hence build_menu's proxy.
"""

from __future__ import annotations

import sys
from typing import Callable

import gi

gi.require_version("Gio", "2.0")
gi.require_version("GLib", "2.0")
gi.require_version("Gtk", "3.0")
from gi.repository import Gio, GLib, Gtk

from orcshot.i18n import _

ICON_NAME = "orcshot"
LEFT_CLICK_ACTION = "tray-region"


def proxy_action_names(model: Gio.MenuModel) -> list[str]:
    """Bare names of every `app.<name>` action the model references,
    depth-first through section and submenu links, first occurrence
    wins."""
    names: list[str] = []

    def walk(m: Gio.MenuModel) -> None:
        for i in range(m.get_n_items()):
            action = m.get_item_attribute_value(i, "action", GLib.VariantType("s"))
            if action is not None:
                name = action.get_string()
                if name.startswith("app."):
                    bare = name[4:]
                    if bare not in names:
                        names.append(bare)
            for link in ("section", "submenu"):
                sub = m.get_item_link(i, link)
                if sub is not None:
                    walk(sub)

    walk(model)
    return names


def build_menu(model: Gio.MenuModel, forward: Callable[[str], None], delay_ms: int = 150) -> Gtk.Menu:
    """A Gtk.Menu for the model whose `app.*` actions are proxied: each
    pops the menu down and calls forward(bare_name) delay_ms later. The
    delay is what keeps the menu out of the capture it starts - the
    app's own one-main-loop-turn deferral (app.py's _defer) is not
    enough for a popup that is still fading, measured 2026-09-12."""
    menu = Gtk.Menu.new_from_model(model)
    proxy = Gio.SimpleActionGroup()
    for name in proxy_action_names(model):
        action = Gio.SimpleAction.new(name, None)

        def fire(_action, _param, name=name):
            menu.popdown()
            GLib.timeout_add(delay_ms, _forward_once, forward, name)

        action.connect("activate", fire)
        proxy.add_action(action)
    menu.insert_action_group("app", proxy)
    menu.show_all()
    return menu


def _forward_once(forward, name) -> bool:
    forward(name)
    return GLib.SOURCE_REMOVE


def create_status_icon(app):
    """The icon, or None (with one stderr line) when the XApp typelib is
    not installed - a Cinnamon machine without gir1.2-xapp-1.0 gets no
    tray rather than a crash. Kept on the app by the caller so it lives
    exactly as long as the process; nothing to tear down on quit."""
    try:
        gi.require_version("XApp", "1.0")
        from gi.repository import XApp
    except (ImportError, ValueError) as error:
        print(f"[orcshot] XApp status icon unavailable ({error}); no Cinnamon tray icon", file=sys.stderr, flush=True)
        return None

    icon = XApp.StatusIcon.new()
    icon.set_icon_name(ICON_NAME)
    icon.set_tooltip_text(_("Orcshot"))
    icon.set_secondary_menu(build_menu(app._tray_menu, lambda name: app.activate_action(name, None)))

    def on_activate(_icon, button, _time):
        if button == 1:
            app.activate_action(LEFT_CLICK_ACTION, None)

    icon.connect("activate", on_activate)
    return icon
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/unit/ui/test_xapp_tray.py -q`
Expected: `4 passed`. If `test_create_status_icon_without_xapp_returns_none_and_logs` fails because `gi.require_version` was already satisfied for XApp earlier in the process, the monkeypatch still intercepts the call — check the exception type raised in the test matches the `except` tuple.

- [ ] **Step 5: Commit**

```bash
git add src/orcshot/ui/xapp_tray.py tests/unit/ui/test_xapp_tray.py
git commit -m "Add ui/xapp_tray: XApp status icon and the pop-down-then-forward menu proxy (#208)

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 2: Create the icon on Cinnamon in `do_startup`

**Files:**
- Modify: `src/orcshot/app.py` (imports near line 59-65; `do_startup` right after the `_export_tray_menu()` try/except, around line 212-223)

**Interfaces:**
- Consumes: `create_status_icon(app)` (Task 1), `hotkey_setup.cinnamon_keybindings_available()`.
- Produces: `OrcshotApplication._xapp_icon` (the icon or `None`).

- [ ] **Step 1: Add the imports**

Next to `from orcshot.ui.first_run_setup import maybe_run_first_run_setup` add:

```python
from orcshot.hotkey_setup import cinnamon_keybindings_available
from orcshot.ui.xapp_tray import create_status_icon
```

(Check whether `cinnamon_keybindings_available` is already imported in `app.py`; if so, don't duplicate.)

- [ ] **Step 2: Create the icon after the tray menu is exported**

In `do_startup`, directly after the `except (GLib.Error, AttributeError)` block that follows `self._export_tray_menu()`:

```python
        # BACKLOG #208: on Cinnamon the tray is an XApp status icon owned
        # by this process (no applet, no About/Remove, nothing to
        # install) rendering the same self._tray_menu the GNOME Shell
        # extension consumes. Created here, after the export, because
        # build_menu reads self._tray_menu.
        self._xapp_icon = None
        if cinnamon_keybindings_available():
            self._xapp_icon = create_status_icon(self)
```

`_export_tray_menu` can fail (the try/except above) and leave `self._tray_menu` unset; guard with `getattr(self, "_tray_menu", None) is not None and cinnamon_keybindings_available()` so the icon is skipped, not crashed, in that case.

- [ ] **Step 3: Update `_quit_and_hide_tray_button`'s docstring**

Append one sentence to its docstring: "The XApp status icon (BACKLOG #208) dies with the process too — `self._xapp_icon` needs no explicit teardown."

- [ ] **Step 4: Run the suite**

Run: `.venv/bin/pytest tests/ -q`
Expected: all pass (no app-level test constructs `OrcshotApplication`).

- [ ] **Step 5: Live check from the dev checkout on the Mint host**

Quit the running `.deb` Orcshot first (tray → Quit, or `pkill -f 'bin/orcshot'`), then:

```bash
cd ~/projects/orcshot && .venv/bin/python -m orcshot.app
```

Expected: an Orcshot icon among the status icons; right-click shows the menu with icons and no About/Remove; left-click opens the region overlay (Escape cancels). Then Quit from the menu: icon gone, `pgrep -af orcshot.app` empty.

- [ ] **Step 6: Commit**

```bash
git add src/orcshot/app.py
git commit -m "Create the XApp status icon on Cinnamon after exporting the tray menu (#208)

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 3: Retire the applet; add the `.deb` dependency

**Files:**
- Delete: `src/orcshot/resources/cinnamon-applets/` (whole directory)
- Modify: `debian/orcshot.install` (the two `cinnamon-applets` lines), `debian/control` (`Depends:`)
- Modify (docstrings/comments only): `src/orcshot/resources.py:5-12`, `src/orcshot/channel_detect.py:3`, `src/orcshot/app.py` lines ~392, 570, 590-591, 639, 655, 695, 839, `src/orcshot/ui/extension_install.py:1-16`, `src/orcshot/ui/editor_window.py:3760`, `src/orcshot/gnome_extension_setup.py`, `src/orcshot/hotkey_setup.py`, `src/orcshot/capture/gnome_tray_export.py`

**Interfaces:** none new.

- [ ] **Step 1: Delete the applet and its install lines**

```bash
git rm -r -q src/orcshot/resources/cinnamon-applets
```

In `debian/orcshot.install` delete both lines starting `src/orcshot/resources/cinnamon-applets/`. In `debian/control`, in the `Depends:` list of the `orcshot` package, add a line `         gir1.2-xapp-1.0,` beside `python3-gi,` with a comment line above the Depends block if the file's style has one (look at how `python3-shapely` is annotated and match it):

```
# gir1.2-xapp-1.0: XApp.StatusIcon, the Cinnamon tray icon (BACKLOG #208).
# Harmless on GNOME, where it is never imported.
```

- [ ] **Step 2: Fix every docstring that names the applet as a live component**

For each file listed above: `grep -n "applet" <file>` and reword so the applet is described in the past tense or removed. Concretely:
- `resources.py` docstring: "both the GNOME Shell extension and the Cinnamon applet reference it by icon-theme name" → "the GNOME Shell extension and the XApp status icon (ui/xapp_tray.py) reference it by icon-theme name".
- `channel_detect.py` docstring: drop "/ Cinnamon applet".
- `app.py` `_register_tray_actions` docstring ("the GNOME Shell extension or the Cinnamon applet, both rendering the menu") → "the GNOME Shell extension, or ui/xapp_tray.py's XApp status icon on Cinnamon".
- `app.py` `_export_tray_menu` docstring: same substitution where "Cinnamon applet" appears.
- `ui/extension_install.py` module docstring: "The Cinnamon tray is becoming an XApp.StatusIcon…" → "The Cinnamon tray is an XApp.StatusIcon owned by the app (ui/xapp_tray.py), which needs no install."
- `gnome_extension_setup.py` / `hotkey_setup.py` / `gnome_tray_export.py` / `editor_window.py`: reword or drop the applet mention; keep any history that explains a decision, marked as history.

Then: `grep -rn -i "cinnamon.applet\|applet.js\|orcshot-tray@orcshot.org" src debian` must print nothing.

- [ ] **Step 3: Build the `.deb` and check its contents**

```bash
dpkg-buildpackage -us -uc -b > /tmp/deb-build.log 2>&1; echo exit=$?
dpkg-deb -c ../orcshot_*_all.deb | grep -c cinnamon
dpkg-deb -f ../orcshot_*_all.deb Depends | tr ',' '\n' | grep xapp
```

Expected: exit 0, `0` cinnamon paths, `gir1.2-xapp-1.0` in Depends. (`lintian` per RELEASING.md step 6 if you want the full check.)

- [ ] **Step 4: Run the suite and commit**

Run: `.venv/bin/pytest tests/ -q` — expected all pass.

```bash
git add -A src debian
git commit -m "Retire the Cinnamon applet; the .deb depends on gir1.2-xapp-1.0 (#208)

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 4: Flatpak — the `xapps` module and the two bus grants

**Files:**
- Modify: `org.orcshot.Orcshot.yaml` (`finish-args` block at the top; `modules:` — insert before `- name: orcshot` at ~line 87)

**Interfaces:** none new.

- [ ] **Step 1: Add the finish-args**

After the `--talk-name=org.gnome.Shell` line:

```yaml
  # BACKLOG #208: the Cinnamon tray is an XApp.StatusIcon owned by the
  # app. libxapp registers the icon under org.x.StatusIcon.<prgname>
  # (read from xapp-status-icon.c) and talks to Cinnamon's monitor
  # applet under org.x.StatusIconMonitor.*. Same two lines Warpinator
  # (flathub/org.x.Warpinator, Mint's own app) declares.
  - --own-name=org.x.StatusIcon.orcshot
  - --talk-name=org.x.StatusIconMonitor.*
```

- [ ] **Step 2: Add the module**

Before `- name: orcshot`:

```yaml
  # BACKLOG #208: libxapp for XApp.StatusIcon, exactly as Warpinator's
  # Flathub manifest builds it - app-lib-only skips everything but the
  # library and its GI/Python bindings. The GNOME 50 runtime's Python is
  # 3.13 (checked), hence the overrides dir. Only used on Cinnamon; on
  # GNOME the module is dead weight of a few hundred kB.
  - name: xapps
    buildsystem: meson
    config-opts:
      - -Dapp-lib-only=true
      - -Dpy-overrides-dir=/app/lib/python3.13/site-packages/gi/overrides
    sources:
      - type: git
        url: https://github.com/linuxmint/xapp.git
        tag: "3.2.2"
        commit: 913b2a2b441ec24daf3aa92e2863cc40e1c43650
```

(The commit hash is the one Warpinator pins for tag 3.2.2; confirm with `git ls-remote https://github.com/linuxmint/xapp.git refs/tags/3.2.2` before committing — a tag's commit vs its annotated object can differ; use whichever `ls-remote` prints for `refs/tags/3.2.2^{}` if present.)

- [ ] **Step 3: Lint and build locally if flatpak-builder is available, else rely on CI**

```bash
flatpak run --command=flatpak-builder-lint org.flatpak.Builder manifest org.orcshot.Orcshot.yaml; echo lint-exit=$?
```

Expected: exit 0. Full local build (optional; CI does it): `flatpak run org.flatpak.Builder --user --force-clean --install build-dir org.orcshot.Orcshot.yaml`.

- [ ] **Step 4: Commit and push a branch; open a draft PR to run CI**

```bash
git add org.orcshot.Orcshot.yaml
git commit -m "Flatpak: build libxapp (Warpinator's module) and grant the XApp status-icon bus names (#208)

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
git push -u origin HEAD
gh pr create --draft --title "BACKLOG #208: XApp status icon on Cinnamon" --body "Replaces the Cinnamon applet with an app-owned XApp.StatusIcon (spec docs/superpowers/specs/2026-09-12-xapp-status-icon-design.md).

🤖 Generated with [Claude Code](https://claude.com/claude-code)"
gh run watch --exit-status "$(gh run list --workflow flatpak.yml -L1 --json databaseId --jq '.[0].databaseId')"
```

Expected: `flatpak / build` green (the module compiled), `flatpak / verify` green. If the module fails to build, read the meson error: the likely causes are a missing `-Dapp-lib-only` option in an older tag (then pin a newer tag) or a Python-path mismatch (then fix `-Dpy-overrides-dir` from the runtime's actual `/app/lib/python3.*`).

---

### Task 5: Live acceptance on the Mint host, records, resolve #208

**Files:**
- Modify: `VERIFICATION.md` (new scenario via `/orc-todo add verification`), `BACKLOG.md` (#208 resolution)

**Interfaces:** none.

- [ ] **Step 1: Dev-checkout pass (the `.deb` code path)**

Quit any running Orcshot, then `cd ~/projects/orcshot && .venv/bin/python -m orcshot.app &`. Check, and record each result:
1. Icon present among the status icons, tooltip "Orcshot".
2. Right-click: menu with per-item icons; no About, no Remove.
3. Left-click: region overlay; Escape cancels.
4. **Menu-in-capture:** right-click → *Capture Full Screen* → in the destination menu choose *Save*. Open the newest file in `~/Pictures/Screenshots` and crop where the menu was; expected: desktop content, no menu. (Automatable: pop the menu at a known spot with a test hook is *not* available in the shipped code — do this by hand, then delete the test capture.)
5. Quit from the menu: icon gone; `pgrep -af orcshot.app` empty.

- [ ] **Step 2: Flatpak pass on the Mint host**

```bash
gh run download "$(gh run list --workflow flatpak.yml -L1 --json databaseId --jq '.[0].databaseId')" -n orcshot-flatpak -D /tmp/orcshot-flatpak
flatpak install --user -y /tmp/orcshot-flatpak/*.flatpak
flatpak info --show-permissions org.orcshot.Orcshot | grep -i "StatusIcon"
flatpak run org.orcshot.Orcshot &
```

Expected: the permissions list shows both `org.x.StatusIcon.orcshot` (own) and `org.x.StatusIconMonitor.*` (talk); then checks 1–5 again. If the icon does not appear: `flatpak run --command=python3 org.orcshot.Orcshot -c "import gi; gi.require_version('XApp','1.0'); from gi.repository import XApp; print(XApp.StatusIcon)"` tells whether the typelib landed; `journalctl --user -f | grep -i "statusicon\|xapp"` tells whether the name was owned.

- [ ] **Step 3: Record**

```bash
python3 /home/direflail/.claude/plugins/cache/orclab/orclab/*/skills/orc-todo/scripts/run.py add verification "XApp status icon on Cinnamon (spec 2026-09-12)" <<'EOF'
Scenarios for docs/superpowers/specs/2026-09-12-xapp-status-icon-design.md, on the Mint host
(Cinnamon, X11). Each line names the command/action and the result with date.

- Dev checkout (`.venv/bin/python -m orcshot.app`): icon among the status icons, tooltip
  "Orcshot"; right-click menu with icons, no About/Remove; left-click opens the region overlay;
  Quit removes the icon and the process. — <PASS/FAIL date>
- Menu-in-capture: right-click → Capture Full Screen → Save; the saved PNG cropped at the menu's
  position shows desktop content, not the menu. — <PASS/FAIL date>
- Flatpak (CI bundle, `flatpak install --user`): `flatpak info --show-permissions` lists
  `org.x.StatusIcon.orcshot` (own) and `org.x.StatusIconMonitor.*` (talk); the same five checks
  pass. — <PASS/FAIL date>
- Not verified: Cinnamon on Wayland (no session at hand). xapp-status is D-Bus, so the same code
  path; recorded as unverified rather than assumed.
EOF
```

Replace each `<PASS/FAIL date>` with the real result before committing (the allocator writes the text as given).

In `BACKLOG.md`, per `backlog-discipline`: add `(RESOLVED <date>)` to #208's title and a **Resolved** paragraph citing the VERIFICATION scenario number and the CI run that built the Flatpak module.

- [ ] **Step 4: Commit, mark the PR ready, merge**

```bash
git add VERIFICATION.md BACKLOG.md
git commit -m "Resolve BACKLOG #208: XApp status icon verified on the Mint host, .deb path and Flatpak

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
git push
gh pr ready
gh pr merge --merge --delete-branch
```

Then on `main`: `.venv/bin/pytest tests/ -q` green.

---

## Self-review against the spec

- *When* → Task 2 (`cinnamon_keybindings_available()` gate). *`ui/xapp_tray.py`* → Task 1 (both functions, proxy with `delay_ms=150`, `XApp` import guarded, icon name/tooltip/left-click). *`app.py`* → Task 2 (after `_export_tray_menu`, stored on the app). *Packaging* → Task 3 (`.deb` Depends, install lines) and Task 4 (Flatpak module + finish-args, lint). *Deleted* → Task 3. *Testing* → Task 1 unit tests (proxy delay, action names, missing XApp), Task 5 live checks 1–5 for both the dev checkout and the Flatpak, CI in Task 4. *Verification items* → item 1 is settled by keeping the proxy and running Task 5 check 4; item 2 by Task 4 Step 2's note to confirm the overrides dir.
- Names consistent across tasks: `build_menu(model, forward, delay_ms=150)`, `proxy_action_names(model)`, `create_status_icon(app)`, `app._tray_menu`, `app._xapp_icon`, `LEFT_CLICK_ACTION = "tray-region"`.
- No placeholders: every code step has the code; the one manual check (menu-in-capture) says exactly how to perform it and why it isn't automated in shipped code.
