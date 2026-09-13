# Snap Save: `home` plug and the portal-path guard under snap — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Save produce a file the user can find when Orcshot runs as the strict snap — BACKLOG #212, the prerequisite for the Snap Store half of #198 — and close the snap-shaped hole in #210's portal-path guard.

**Architecture:** Three small changes. (1) `snapcraft.yaml` gains the auto-connected `home` plug so the default `~/Pictures/Screenshots` is writable. (2) `settings.is_portal_document_path` accepts `/run/user/<uid>/doc` as well as `$XDG_RUNTIME_DIR/doc`, because a snap's `XDG_RUNTIME_DIR` is `/run/user/<uid>/snap.<name>` while snapd mounts the document portal at the user's runtime dir. (3) `settings.output_directory_is_reachable` treats a `PermissionError` from `mkdir` as unreachable on every channel, so a folder no plug covers yields the portal folder picker once instead of a traceback. Then a CI grep that `home` stays connected, and live verification on the Ubuntu 26.04 VM against the CI-built snap.

**Tech Stack:** Python 3, snapcraft (core24, `gnome` extension), snapd interfaces, pytest.

**Spec:** `docs/superpowers/specs/2026-09-12-snap-save-home-plug-design.md` — read it first; its "What was verified" section is the evidence.

## Global Constraints

- No plug other than `home` is added. No `removable-media`.
- `output_directory_is_reachable`'s Flatpak `st_dev` test stays exactly as it is; only `mkdir` moves above the channel check.
- Every user-facing string goes through `_()` (this plan adds none).
- Commit after every task. `BACKLOG.md`/`VERIFICATION.md` entries go through `/orc-todo`, never hand-numbered.
- #207 (snap autostart) and #213 (external commands) are out of scope.
- Tests run as `.venv/bin/python -m pytest` from the main checkout, or `PYTHONPATH=src ../../../.venv/bin/python -m pytest` from a `.claude/worktrees/` checkout (the venv's editable install points at the main checkout).

---

### Task 1: `is_portal_document_path` recognises the snap's mount point

**Files:**
- Modify: `src/orcshot/settings.py:160-174` (`is_portal_document_path`)
- Test: `tests/unit/test_settings.py` (`class TestIsPortalDocumentPath`, ~line 727)

**Interfaces:**
- Produces: `is_portal_document_path(path: Path) -> bool` — same signature; now also True for `/run/user/<uid>/doc/…` when `XDG_RUNTIME_DIR` points elsewhere.

- [ ] **Step 1: Write the failing test**

Append inside `class TestIsPortalDocumentPath` in `tests/unit/test_settings.py`:

```python
    def test_true_under_snap_where_the_env_var_is_the_snaps_own_runtime_dir(self, monkeypatch):
        # BACKLOG #212: a snap sees XDG_RUNTIME_DIR=/run/user/<uid>/snap.<name>,
        # but snapd mounts the document portal at the *user's* runtime dir
        # (snapd desktop/portal/document.go GetDefaultMountPoint).
        uid = os.getuid()
        monkeypatch.setenv("XDG_RUNTIME_DIR", f"/run/user/{uid}/snap.orcshot")
        assert is_portal_document_path(Path(f"/run/user/{uid}/doc/54b8e4a6/snap-test")) is True

    def test_false_for_the_snaps_own_runtime_dir_without_doc(self, monkeypatch):
        uid = os.getuid()
        monkeypatch.setenv("XDG_RUNTIME_DIR", f"/run/user/{uid}/snap.orcshot")
        assert is_portal_document_path(Path(f"/run/user/{uid}/snap.orcshot/orcshot.sock")) is False
```

- [ ] **Step 2: Run the tests to verify the first fails**

Run: `.venv/bin/python -m pytest tests/unit/test_settings.py -k IsPortalDocumentPath -v`
Expected: `test_true_under_snap_where_the_env_var_is_the_snaps_own_runtime_dir` FAILS (`assert False is True`); the rest PASS.

- [ ] **Step 3: Implement**

Replace the body of `is_portal_document_path` (the two lines after the docstring) with:

```python
    user_runtime_dir = Path(f"/run/user/{os.getuid()}")
    env_runtime_dir = Path(os.environ.get("XDG_RUNTIME_DIR") or user_runtime_dir)
    path = Path(path)
    return path.is_relative_to(env_runtime_dir / "doc") or path.is_relative_to(user_runtime_dir / "doc")
```

And append this paragraph to the docstring, before its closing `"""`:

```
    Two prefixes, not one (BACKLOG #212): under Flatpak $XDG_RUNTIME_DIR is
    the user's runtime dir, so "$XDG_RUNTIME_DIR/doc" is the mount; under
    a snap the variable is /run/user/<uid>/snap.<name> while snapd mounts
    the portal at /run/user/<uid>/doc (snapd desktop/portal/document.go,
    GetDefaultMountPoint) - so the user's runtime dir is checked as well,
    unconditionally, since on a plain install it is simply never a path
    a dialog returns.
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/unit/test_settings.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/orcshot/settings.py tests/unit/test_settings.py
git commit -m "is_portal_document_path: recognise /run/user/<uid>/doc - the snap's XDG_RUNTIME_DIR is not where snapd mounts the portal (#212)

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 2: A denied folder is unreachable on every channel

**Files:**
- Modify: `src/orcshot/settings.py:142-157` (`output_directory_is_reachable`)
- Test: `tests/unit/test_settings.py` (`class TestOutputDirectoryIsReachable`, ~line 677; `test_creates_the_directory_before_checking` ~line 714)

**Interfaces:**
- Produces: `output_directory_is_reachable(directory: Path) -> bool` — same signature; now False when the directory cannot be created.

- [ ] **Step 1: Rewrite the disk-touch test and add the denial tests**

Replace `test_creates_the_directory_before_checking` with:

```python
    def test_creates_the_directory_on_every_channel(self, tmp_path, monkeypatch):
        # BACKLOG #212: mkdir runs before the channel check so a denied
        # folder (snap without a covering plug, a read-only folder on
        # the .deb) is reported unreachable instead of raising later.
        target = tmp_path / "Pictures" / "Screenshots"
        monkeypatch.setattr("orcshot.settings.detect_channel", lambda: "deb")
        assert output_directory_is_reachable(target) is True
        assert target.is_dir()

    def test_false_when_the_directory_cannot_be_created(self, tmp_path, monkeypatch):
        def denied(self, *args, **kwargs):
            raise PermissionError(13, "Permission denied", str(self))

        monkeypatch.setattr(Path, "mkdir", denied)
        for channel in ("snap", "deb", "flatpak"):
            monkeypatch.setattr("orcshot.settings.detect_channel", lambda c=channel: c)
            assert output_directory_is_reachable(tmp_path / "denied") is False, channel
```

- [ ] **Step 2: Run the tests to verify the new ones fail**

Run: `.venv/bin/python -m pytest tests/unit/test_settings.py -k OutputDirectoryIsReachable -v`
Expected: `test_creates_the_directory_on_every_channel` FAILS (`target.is_dir()` is False — "deb" returned before mkdir); `test_false_when_the_directory_cannot_be_created` FAILS with the `PermissionError` propagating.

- [ ] **Step 3: Implement**

Replace the body of `output_directory_is_reachable` (the four lines after the docstring) with:

```python
    try:
        directory.mkdir(parents=True, exist_ok=True)
    except PermissionError:
        return False
    if detect_channel() != "flatpak":
        return True
    return os.stat(directory).st_dev != os.stat("/").st_dev
```

And append to the docstring, before its closing `"""`:

```
    A folder that cannot be created is unreachable on every channel
    (BACKLOG #212): under the snap that is any path no plug covers, on the
    .deb a read-only folder. The caller then runs the Screenshot Save
    Location picker once - through the portal, whose document grant is
    writable regardless of plugs - instead of raising later in Save.
```

- [ ] **Step 4: Run the whole suite**

Run: `.venv/bin/python -m pytest tests -q`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/orcshot/settings.py tests/unit/test_settings.py
git commit -m "output_directory_is_reachable: a folder that cannot be created is unreachable on every channel (#212)

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 3: The `home` plug, and CI proving it stays connected

**Files:**
- Modify: `snapcraft.yaml:33-45` (`apps.orcshot.plugs`)
- Modify: `.github/workflows/snap.yml:47-48` (after the `snap install --dangerous` step)

**Interfaces:** none.

- [ ] **Step 1: Add the plug**

In `snapcraft.yaml`, after the `- audio-playback` line inside `plugs:`:

```yaml
      # BACKLOG #212: Save writes to the configured output directory
      # (~/Pictures/Screenshots by default). home is auto-connected on
      # classic distros, needs no store review, and covers every
      # non-hidden path under the real home. A folder outside home goes
      # through the FileChooser portal instead (settings.
      # output_directory_is_reachable) - no removable-media plug.
      - home
```

- [ ] **Step 2: Add the CI assertion**

In `.github/workflows/snap.yml`, directly after the "Install it locally" step:

```yaml
      - name: "Assert the home plug is connected (BACKLOG #212: Save writes to ~/Pictures/Screenshots)"
        run: snap connections orcshot | grep -E '^home +orcshot:home +:home'
```

(`snap connections` prints one `interface plug slot notes` row per plug; a disconnected plug shows `-` in the slot column, so the `:home` slot match is the assertion.)

- [ ] **Step 3: Validate the YAML parses and the plug is where snapcraft expects**

Run: `python3 -c "import yaml; d=yaml.safe_load(open('snapcraft.yaml')); print(d['apps']['orcshot']['plugs'])"`
Expected: `['audio-playback', 'home']`.

Run: `python3 -c "import yaml; yaml.safe_load(open('.github/workflows/snap.yml')); print('ok')"`
Expected: `ok`.

- [ ] **Step 4: Commit**

```bash
git add snapcraft.yaml .github/workflows/snap.yml
git commit -m "snap: home plug so Save can write the output directory; CI asserts it stays connected (#212)

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 4: `real_home()` — the user's home under the snap, not `$SNAP_USER_DATA`

**Files:**
- Modify: `src/orcshot/settings.py:108-114` (`default_output_directory`; new `real_home` above it)
- Modify: `src/orcshot/ui/file_export.py:109-139` (`orcshot_visible_temp_dir`, the `home = Path.home()` default)
- Test: `tests/unit/test_settings.py` (`class TestDefaultOutputDirectory`, ~line 119), `tests/unit/ui/test_file_export.py`

**Interfaces:**
- Produces: `settings.real_home() -> Path`. `default_output_directory()` and `orcshot_visible_temp_dir()` signatures unchanged.

**Why (found by the Task 5 baseline on the VM):** snapd sets `HOME=$SNAP_USER_DATA`
(`/home/<user>/snap/orcshot/<rev>`), so `Path.home()` is the snap's private data dir and the
default output directory became `~/snap/orcshot/<rev>/Screenshots` — the write succeeds, in a
folder no user looks in. snapd exports `SNAP_REAL_HOME=/home/<user>`. On the .deb and under
Flatpak that variable is unset and `HOME` is the real home, so those channels are untouched.

- [ ] **Step 1: Write the failing tests**

In `tests/unit/test_settings.py`, add `real_home` to the `from orcshot.settings import (...)` block and replace `class TestDefaultOutputDirectory` with:

```python
class TestRealHome:
    """BACKLOG #212: under the snap HOME is $SNAP_USER_DATA; the user's
    actual home is SNAP_REAL_HOME. Elsewhere the variable is unset."""

    def test_is_path_home_when_snap_real_home_is_unset(self, monkeypatch):
        monkeypatch.delenv("SNAP_REAL_HOME", raising=False)
        assert real_home() == Path.home()

    def test_is_snap_real_home_when_set(self, monkeypatch, tmp_path):
        monkeypatch.setenv("SNAP_REAL_HOME", str(tmp_path / "realhome"))
        assert real_home() == tmp_path / "realhome"


class TestDefaultOutputDirectory:
    def test_returns_a_path_under_home(self, monkeypatch):
        monkeypatch.delenv("SNAP_REAL_HOME", raising=False)
        result = default_output_directory()
        assert Path.home() in result.parents

    def test_under_the_snap_it_is_under_the_real_home_not_snap_user_data(self, monkeypatch, tmp_path):
        snap_home = tmp_path / "snap" / "orcshot" / "x1"
        real = tmp_path / "realhome"
        (real / "Pictures").mkdir(parents=True)
        monkeypatch.setenv("HOME", str(snap_home))
        monkeypatch.setenv("SNAP_REAL_HOME", str(real))
        result = default_output_directory()
        assert result == real / "Pictures" / "Screenshots"
        assert snap_home not in result.parents

    def test_under_the_snap_without_pictures_it_falls_back_to_the_real_home(self, monkeypatch, tmp_path):
        real = tmp_path / "realhome"
        real.mkdir()
        monkeypatch.setenv("HOME", str(tmp_path / "snap" / "orcshot" / "x1"))
        monkeypatch.setenv("SNAP_REAL_HOME", str(real))
        assert default_output_directory() == real / "Screenshots"
```

In `tests/unit/ui/test_file_export.py`, append:

```python
def test_visible_temp_dir_defaults_to_the_real_home_under_the_snap(monkeypatch, tmp_path):
    # BACKLOG #212: ~/Orcshot must be the user's home, not $SNAP_USER_DATA.
    real = tmp_path / "realhome"
    real.mkdir()
    monkeypatch.setenv("HOME", str(tmp_path / "snap" / "orcshot" / "x1"))
    monkeypatch.setenv("SNAP_REAL_HOME", str(real))
    assert orcshot_visible_temp_dir() == real / "Orcshot"
    assert (real / "Orcshot").is_dir()
```

(`Path.home()` reads `$HOME` on POSIX, so `monkeypatch.setenv("HOME", …)` is a faithful stand-in for snapd's environment.)

- [ ] **Step 2: Run the tests to verify they fail**

Run: `PYTHONPATH=src ../../../.venv/bin/python -m pytest tests/unit/test_settings.py tests/unit/ui/test_file_export.py -k "RealHome or DefaultOutputDirectory or real_home" -v`
Expected: `ImportError` for `real_home`; once the import line is added, the two "under_the_snap" tests and the file_export test FAIL (paths under the fake snap HOME).

- [ ] **Step 3: Implement**

In `src/orcshot/settings.py`, directly above `default_output_directory`:

```python
def real_home() -> Path:
    """The user's home directory - the one they look in (BACKLOG #212).
    Under the snap, HOME is $SNAP_USER_DATA (~/snap/orcshot/<rev>), so
    Path.home() is the snap's private data dir; snapd exports the real
    one as SNAP_REAL_HOME. Everywhere else the variable is unset and
    HOME is already the real home - the .deb and the Flatpak are
    untouched by this. Only for folders the user is meant to find
    (the screenshot folder, ~/Orcshot); config/cache/autostart paths
    keep XDG/Path.home(), which under the snap are meant to be private.
    """
    return Path(os.environ.get("SNAP_REAL_HOME") or Path.home())
```

and in `default_output_directory` replace the two `Path.home()` calls:

```python
    home = real_home()
    pictures = home / "Pictures"
    base = pictures if pictures.is_dir() else home
    return base / _DEFAULT_OUTPUT_DIRNAME
```

In `src/orcshot/ui/file_export.py`, add `from orcshot.settings import real_home` to the imports (first confirm no cycle: `grep -n "file_export" src/orcshot/settings.py` → nothing), and in `orcshot_visible_temp_dir` replace `home = Path.home()` with `home = real_home()`. Append to that docstring, before its closing `"""`:

```
    Under the snap "~" is the user's real home via settings.real_home(),
    not $SNAP_USER_DATA (BACKLOG #212).
```

- [ ] **Step 4: Run the whole suite**

Run: `PYTHONPATH=src ../../../.venv/bin/python -m pytest tests -q`
Expected: all PASS.

- [ ] **Step 5: Commit**

Stage the four files (`src/orcshot/settings.py`, `src/orcshot/ui/file_export.py`, `tests/unit/test_settings.py`, `tests/unit/ui/test_file_export.py`) and commit with the subject:

`real_home(): under the snap the screenshot folder and ~/Orcshot live in SNAP_REAL_HOME, not $SNAP_USER_DATA (#212)`

plus the usual `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>` trailer.

---

### Task 5: Live verification on the Ubuntu 26.04 VM, recorded in VERIFICATION.md

**Files:**
- Modify: `VERIFICATION.md` (new scenario via `/orc-todo add verification`)
- Modify: `BACKLOG.md` (resolve #212 per `orclab:backlog-discipline`)

**Interfaces:** none — evidence only. A failing scenario goes back to the task that owns it.

VM access: registry memory `project_orcshot_vm_access.md`. `ssh -i ~/.ssh/orcshot_dev_vm -p 2222 ubuntu2604@localhost`; start with `DISPLAY=:0 VBoxManage startvm "Ubuntu 26.04" --type gui` if `VBoxManage list runningvms` does not list it. The VM currently has the 0.3.0 snap installed (`snap list orcshot` → `0.3.0 x4`), which is the unfixed baseline.

- [ ] **Step 1: Baseline — the bug, observed, on the 0.3.0 snap — DONE 2026-09-12**

Result: *Save* raised nothing and wrote `~/snap/orcshot/x4/Screenshots/2026-09-12 19_32_53.png`;
the real `~/Pictures/Screenshots` was untouched. Cause: `HOME=$SNAP_USER_DATA` (Task 4). #212's
"AppArmor-denied / PermissionError" guess was wrong — say so in the resolution paragraph. The
`home` plug alone (this branch before Task 4, CI run 34728131086, snap x1) produced the identical
result. The procedure, kept for re-runs: On the VM, make sure nothing else owns the bus name (`gdbus call --session --dest org.freedesktop.DBus --object-path /org/freedesktop/DBus --method org.freedesktop.DBus.NameHasOwner org.orcshot.Orcshot` → `false`; `flatpak kill org.orcshot.Orcshot` / quit any .deb instance if not). Launch the snap inside the graphical session with `systemd-run --user --unit=orcshot-snap -p StandardOutput=file:/tmp/orcshot-snap.log -p StandardError=file:/tmp/orcshot-snap.log snap run orcshot`, confirm the owner PID's `/proc/<pid>/cgroup` contains `snap.orcshot`, then `gdbus call --session --dest org.orcshot.Orcshot --object-path /org/orcshot/Orcshot --method org.gtk.Actions.Activate tray-full_screen '@av []' '@a{sv} {}'`, choose *Save* in the Shell-native picker (screenshot first — it pops at the pointer). Record: what `/tmp/orcshot-snap.log` shows (expected a `PermissionError` traceback), and that `~/Pictures/Screenshots` gained no file. This replaces #212's "presumably" with a fact. Then `snap remove orcshot`.

- [ ] **Step 2: Push, get the CI snap**

```bash
git push -u origin HEAD
gh run list --workflow=snap.yml --limit 1
```

The snap workflow runs on `pull_request` — open a draft PR against `main` if one is not open yet. Wait for it green (`gh run watch <id>`; the verify job's new grep must pass), `gh run download <id> -D snap-bundle`, `scp` the `orcshot_*.snap` to the VM, `sudo snap install --dangerous ./orcshot_*.snap` there (sudo is passwordless for `ubuntu2604`), then `snap connections orcshot | grep home` → `home  orcshot:home  :home  -`.

- [ ] **Step 3: Scenario A — default folder**

No `output_directory` in `~/snap/orcshot/current/.config/orcshot/config.json` (the snap's `XDG_CONFIG_HOME`; delete the key if present). Launch as in Step 1, capture, *Save*. Expected: no dialog; a new PNG in the **real** `~/Pictures/Screenshots` on the VM; nothing new under `~/snap/orcshot/<rev>/Screenshots`; log clean apart from the known `libpixbufloader_svg.so` line (BACKLOG #214 — also note in the report whether the editor's toolbar icons render in Scenario B's screenshot, since that line means GdkPixbuf's SVG loader failed to load).

- [ ] **Step 4: Scenario B — Save As through the portal, the section-2 fix**

Capture → *Edit…* → in the editor Ctrl+S. Expected: the GNOME portal save dialog (owned by `xdg-desktop-portal-gnome`, not the snap). Type `snap-test`, choose JPEG in *Save as type*, Save. Expected: the *Saved as PNG* info dialog; after OK, `~/Pictures/Screenshots/snap-test` is a PNG (`file`), and `ls -A ~/Pictures/Screenshots | grep xdp` is empty. (On #210's merged code this strands `.xdp-snap-test.jpg-XXXXXX` — that is the regression this scenario guards.)

- [ ] **Step 5: Scenario C — folder outside home**

`sudo mkdir -p /media/orcshot-test && sudo chown ubuntu2604 /media/orcshot-test`; set `"output_directory": "/media/orcshot-test"` in the snap's config. Kill and relaunch the snap, capture, *Save*. Expected: the portal folder picker appears once; pick `/media/orcshot-test`; file lands there; config now `/run/user/1000/doc/…/orcshot-test`. Second *Save*: no dialog, second file.

- [ ] **Step 6: Scenario D — restart**

Kill the snap (`snap run` process), relaunch, *Save*: silent, third file in `/media/orcshot-test`.

- [ ] **Step 7: Record the scenario**

```bash
python3 /home/direflail/.claude/plugins/cache/orclab/orclab/0.16.0/skills/orc-todo/scripts/run.py add verification "Snap Save: home plug and the portal-path guard under snap (spec 2026-09-12)" <<'EOF'
<the real results: baseline observation with the exact log line, then A-D, one line each
naming the command that produced the evidence, PASS/FAIL, the CI run id, the date>
EOF
```

- [ ] **Step 8: Resolve #212**

Append `(RESOLVED <today's date>)` to #212's title line in `BACKLOG.md` and a **Resolved for real, not just tracked:** paragraph: what the baseline actually showed, the three changes, scenarios A–D, the CI run. Do not edit the original text.

- [ ] **Step 9: Commit, and hand off**

```bash
git add VERIFICATION.md BACKLOG.md
git commit -m "Resolve BACKLOG #212: snap Save verified on the Ubuntu 26.04 VM (CI snap)

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
git push
```

Then `superpowers:finishing-a-development-branch`.
