# Flathub Readiness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Orcshot's Flatpak manifest genuinely ready for real Flathub submission (BACKLOG #194) - vendor its network-dependent build step, add a real AppStream metainfo file with a real screenshot and real OARS content ratings, and validate it all with Flathub's own linter in CI.

**Architecture:** Four sequential tasks, each producing the real, concrete input the next one needs: vendor the Python deps first (so later tasks build against the final manifest shape), take the real screenshot second (so its real commit SHA exists before the metainfo references it), write the metainfo third (now that a real screenshot URL exists to put in it), then wire up CI validation last (now that a real metainfo file exists to validate).

**Tech Stack:** `flatpak-builder`, AppStream/`flatpak-builder-lint`, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-09-02-flathub-readiness-design.md` - read this too, the plan argues from it and doesn't repeat all of its own live-verified reasoning.

## Global Constraints

- No task subagent ever pushes to `main` directly - PR-only, controller merges after explicit direflail confirmation, matching every other plan this project has used.
- **direflail must see the real generated final output before anything ships** (opens as a PR): the real `org.orcshot.Orcshot.metainfo.xml` content, the real screenshot image, and the real manifest diff. This is a standing requirement (not optional) - the controller must actually show these to direflail and get their explicit go-ahead before pushing/opening the PR in Task 4, even though the design itself was already approved. Showing a description of the files is not enough - direflail needs to see the actual content/image.
- The vendored-dependency module content in Task 1 must be used exactly as given below (real, already-verified `flatpak-pip-generator` output run against `org.gnome.Sdk`//50) - not regenerated or hand-modified.
- `orcshot.org` is confirmed live and safe to use as the metainfo's homepage URL as-is (spec's own Known Open Items - already resolved 2026-09-02, don't re-check unless something seems off).
- The screenshot must be taken on the real Ubuntu 26.04 GNOME VM, not this project's own X11 dev host - already decided in the spec (real window-decoration accuracy), not a task-level decision to revisit.
- Task 3's `flatpak-builder-lint` validation must show **zero errors and zero warnings** - Flathub's own real review bar treats both as failures, so this plan does too.

---

### Task 1: Vendor the three pip-installed Python dependencies

**Files:**
- Modify: `org.orcshot.Orcshot.yaml:74-88`

**Interfaces:**
- Consumes: nothing from another task.
- Produces: a manifest that builds with no network access anywhere - Task 2 builds and runs the app using this task's own output as its starting point.

- [ ] **Step 1: Remove the network-dependent build step**

In `org.orcshot.Orcshot.yaml`, the `orcshot` module currently has (lines 74-88):

```yaml
    build-options:
      build-args:
        - --share=network
    build-commands:
      - pip3 install --prefix=/app --no-deps .
      # Pinned to requirements.txt's own versions (final-review finding,
      # 2026-08-31) - that file exists specifically so every channel's
      # actual dependency versions match what Aikido/Semgrep SCA
      # scanning checks (see its own header comment); apt/Snap both get
      # distro-pinned versions via debian/control, so this was the one
      # channel building against whatever PyPI happened to serve that
      # day. Keep these three in sync with requirements.txt by hand -
      # RELEASING.md step 3 already re-verifies requirements.txt itself
      # against the dev venv every release.
      - pip3 install --prefix=/app numpy==2.5.2 shapely==2.1.2 python-xlib==0.33
      - install -Dm644 org.orcshot.Orcshot.desktop /app/share/applications/org.orcshot.Orcshot.desktop
```

Remove the whole `build-options:` block (the `--share=network` build-arg) and remove the
`pip3 install --prefix=/app numpy==2.5.2 shapely==2.1.2 python-xlib==0.33` line specifically -
replace it with nothing (the vendored modules in Step 2 install these instead). Leave the
`pip3 install --prefix=/app --no-deps .` and `install -Dm644 ...desktop...` lines exactly as
they are. Also delete the two comment lines directly above the removed pip line (the
"Pinned to requirements.txt's own versions..." comment block) - it describes the approach this
step removes; Step 2 adds its own comment explaining the new approach.

Result should read:

```yaml
    build-commands:
      - pip3 install --prefix=/app --no-deps .
      - install -Dm644 org.orcshot.Orcshot.desktop /app/share/applications/org.orcshot.Orcshot.desktop
```

- [ ] **Step 2: Add the three vendored-dependency modules**

Still in `org.orcshot.Orcshot.yaml`, add three new entries to the top-level `modules:` list -
place them directly after the `orcshot` module (before `bundled-extensions`) so build order
doesn't matter (these three have no dependency on `orcshot`'s own module, but keeping them
adjacent to where the old pip line used to be makes the diff easy to review):

```yaml
  # Real, already-verified flatpak-pip-generator output (Flathub's own
  # official tool, flatpak/flatpak-builder-tools/pip - not the
  # same-named PyPI package, which is an unofficial repackaging), run
  # against org.gnome.Sdk//50 with --prefer-wheels. Replaces the old
  # `pip3 install --prefix=/app numpy==... shapely==... python-xlib==...`
  # line, which needed --share=network at build time - disallowed by
  # Flathub's own build policy (BACKLOG #194). This run also caught two
  # real things a hand-rolled fix would likely have missed: the
  # runtime's actual Python is 3.13 (cp313 wheel tags), not 3.12 as
  # naively assumed from an unrelated host Python; and python-xlib has
  # its own previously-unpinned transitive dependency, six>=1.10.0.
  - name: python3-numpy
    buildsystem: simple
    build-commands:
      - pip3 install --verbose --exists-action=i --no-index --find-links="file://${PWD}"
        --prefix=${FLATPAK_DEST} "numpy==2.5.2" --no-build-isolation
    sources:
      - &numpy-x86_64
        type: file
        url: https://files.pythonhosted.org/packages/7b/44/59a1eb68e773c4098d107ef34a0dbdeca501d72ffcfbff9a7707343921ce/numpy-2.5.2-cp313-cp313-manylinux_2_27_x86_64.manylinux_2_28_x86_64.whl
        sha256: 29b86ff8a6cc556b47ec6b64b194815cc80e6bf5eedcc6cddfd65318cb0b4eee
        only-arches: [x86_64]
      - &numpy-aarch64
        type: file
        url: https://files.pythonhosted.org/packages/29/f1/2a64a307d92c5d98f5255a4014eb43bb6103ee477087b61ecae44a3aa9b9/numpy-2.5.2-cp313-cp313-manylinux_2_27_aarch64.manylinux_2_28_aarch64.whl
        sha256: 0aadf13b60048d501e05fa699efaf7734e2494f3498a4c2a5521d822640324f3
        only-arches: [aarch64]
  - name: python3-shapely
    buildsystem: simple
    build-commands:
      - pip3 install --verbose --exists-action=i --no-index --find-links="file://${PWD}"
        --prefix=${FLATPAK_DEST} "shapely==2.1.2" --no-build-isolation
    sources:
      - *numpy-x86_64
      - *numpy-aarch64
      - type: file
        url: https://files.pythonhosted.org/packages/f2/a2/83fc37e2a58090e3d2ff79175a95493c664bcd0b653dd75cb9134645a4e5/shapely-2.1.2-cp313-cp313-manylinux2014_x86_64.manylinux_2_17_x86_64.whl
        sha256: 7ed1a5bbfb386ee8332713bf7508bc24e32d24b74fc9a7b9f8529a55db9f4ee6
        only-arches: [x86_64]
      - type: file
        url: https://files.pythonhosted.org/packages/2d/5e/7d7f54ba960c13302584c73704d8c4d15404a51024631adb60b126a4ae88/shapely-2.1.2-cp313-cp313-manylinux2014_aarch64.manylinux_2_17_aarch64.whl
        sha256: fe7b77dc63d707c09726b7908f575fc04ff1d1ad0f3fb92aec212396bc6cfe5e
        only-arches: [aarch64]
  - name: python3-python-xlib
    buildsystem: simple
    build-commands:
      - pip3 install --verbose --exists-action=i --no-index --find-links="file://${PWD}"
        --prefix=${FLATPAK_DEST} "python-xlib==0.33" --no-build-isolation
    sources:
      - type: file
        url: https://files.pythonhosted.org/packages/fc/b8/ff33610932e0ee81ae7f1269c890f697d56ff74b9f5b2ee5d9b7fa2c5355/python_xlib-0.33-py2.py3-none-any.whl
        sha256: c3534038d42e0df2f1392a1b30a15a4ff5fdc2b86cfa94f072bf11b10a164398
      - type: file
        url: https://files.pythonhosted.org/packages/b7/ce/149a00dd41f10bc29e5921b496af8b574d8413afcd5e30dfa0ed46c2cc5e/six-1.17.0-py2.py3-none-any.whl
        sha256: 4721f391ed90541fddacab5acf947aa0d3dc7d27b2e1e8eda2be8970586c3274
```

Use this content verbatim (real, already-verified pinned URLs/hashes) - do not regenerate or
hand-edit it.

- [ ] **Step 3: Validate YAML syntax**

Run: `python3 -c "import yaml; yaml.safe_load(open('org.orcshot.Orcshot.yaml'))" && echo valid`
Expected: `valid` printed, no exception.

- [ ] **Step 4: Real from-scratch build with no network share anywhere**

Run: `flatpak-builder --user --force-clean --install --state-dir=.flatpak-builder-state build-dir org.orcshot.Orcshot.yaml`

(`org.gnome.Platform`//50 and `org.gnome.Sdk`//50 must already be installed - `flatpak install
--user flathub org.gnome.Platform//50 org.gnome.Sdk//50` first if not.)

Expected: build succeeds, ending in `Installing app/org.orcshot.Orcshot/x86_64/master`. No
`--share=network` appears anywhere in the manifest at this point (grep to confirm:
`grep -c "share=network" org.orcshot.Orcshot.yaml` must print `0`).

- [ ] **Step 5: Confirm the real app still launches and survives `do_startup`**

```bash
flatpak run org.orcshot.Orcshot --help
```
Expected: exit 0, real `--help` output.

```bash
nohup flatpak run org.orcshot.Orcshot > /tmp/launch.log 2>&1 &
disown
sleep 2
gdbus call --session --dest org.orcshot.Orcshot --object-path /org/orcshot/Orcshot --method org.gtk.Actions.List
```
Expected: a real list of tray action names (e.g. `tray-quit`, `play-capture-sound`, etc.) - not
an error, not an empty list. Then `pkill -f "flatpak run org.orcshot.Orcshot"` to clean up.

- [ ] **Step 6: Confirm numpy/shapely/python-xlib are genuinely importable inside the built app**

```bash
flatpak run --command=python3 org.orcshot.Orcshot -c "import numpy, shapely, Xlib; print('all three import cleanly')"
```
Expected: `all three import cleanly` printed, no `ImportError`/`ModuleNotFoundError`.

- [ ] **Step 7: Clean up and commit**

```bash
flatpak uninstall --user -y org.orcshot.Orcshot org.orcshot.Orcshot.Debug
rm -rf build-dir .flatpak-builder-state
git add org.orcshot.Orcshot.yaml
git commit -m "Vendor numpy/shapely/python-xlib for Flatpak: no network access needed at build time"
```

---

### Task 2: Take the real screenshot on the real GNOME VM

**Files:**
- Create: `metainfo-screenshots/editor-annotated.png`

**Interfaces:**
- Consumes: Task 1's own manifest (the app this task builds and screenshots already has Task 1's fix in place).
- Produces: a real, committed PNG at the path above, and the real commit SHA it lands in (needed verbatim by Task 3 to build the screenshot's pinned URL).

**Real VM access** (from this project's own saved VM registry - use exactly this, don't
rediscover):
- `VBoxManage startvm "Ubuntu 26.04" --type gui` (real window opens on the host's own X11
  desktop - host is Mint/Cinnamon, X11; find it with `wmctrl -l | grep -i "ubuntu 26.04"`).
  Boots to an already-logged-in `ubuntu2604` desktop (auto-login), but the screen may be locked
  from inactivity - if so, wake it (click) and ask direflail to type their login password
  directly into that VM window (never handle this password yourself; wait for their
  confirmation before continuing).
- SSH: `ssh -i ~/.ssh/orcshot_dev_vm -p 2222 ubuntu2604@localhost` (port-forward already set up
  persistently; if `VBoxManage controlvm "Ubuntu 26.04" natpf1 "ssh,tcp,,2222,,22"` errors "a
  NAT rule of this name already exists," that's success, not failure).
- `sudo` is passwordless on this account (`NOPASSWD` already configured) - `ssh ...
  "sudo apt-get install -y ..."` works directly, no GUI/password step needed for `sudo` itself.
- `org.gnome.Platform`//50 and `org.gnome.Sdk`//50 should already be installed on this VM from
  prior session work - `flatpak list --runtime | grep gnome` to confirm; install via
  `flatpak install -y --user flathub org.gnome.Platform//50 org.gnome.Sdk//50` if not.
- **Always** `xdotool windowactivate --sync <id>` immediately before typing/clicking into the
  VM's GUI window, and verify with `xdotool getactivewindow getwindowname` if there's any doubt
  - focus silently drifts back to your own client window between tool calls. Screenshot
  (`import -window <id> <path>.png`) and visually verify typed text is byte-correct before
  pressing Return - `xdotool type` can drop/scramble characters even with a delay.

- [ ] **Step 1: Get the real, Task-1-fixed manifest onto the VM and build it there**

Copy this task's working tree (with Task 1's commit already in it) to the VM, or `git pull` a
pushed copy of the branch - whichever is simpler given how this task is being executed. Then,
over SSH:

```bash
ssh -i ~/.ssh/orcshot_dev_vm -p 2222 ubuntu2604@localhost \
  "cd <path-to-repo-on-vm> && flatpak-builder --user --force-clean --install --state-dir=.flatpak-builder-state build-dir org.orcshot.Orcshot.yaml"
```

Expected: build succeeds (same expectation as Task 1 Step 4, now proven on a second real
machine).

- [ ] **Step 2: Launch the real app inside the VM's own GUI session and drive a real capture + annotation**

Using the GUI window (real display, real GNOME Shell, real window decoration) - not SSH, since
this needs a real visible window:

1. Open a terminal inside the VM's desktop (real terminal icon in the dock, or however the VM's
   desktop already exposes one - a real terminal was already open and usable during earlier
   session work on this same VM).
2. Run `flatpak run org.orcshot.Orcshot` inside it - the real app launches with a real tray
   icon/window.
3. Trigger a real region capture (through however Orcshot's own UI exposes this - the tray menu
   or a configured hotkey).
4. In the editor that opens with the captured image, use at least one real annotation tool
   (arrow, text, or highlight) to mark up the image - a real, visible annotation, not an empty
   canvas.

- [ ] **Step 3: Screenshot the real editor window - windowed, with real decoration, no desktop background**

Per Flathub's own quality guidelines (cited in the spec): the screenshot must show the app
window's own title bar/shadow/rounded corners, must not include the desktop wallpaper or other
chrome, and the window must not be maximized (maximizing removes the shadow/rounding).

Preferred method, if available inside the VM: a native "capture just this window" tool (e.g.
`gnome-screenshot --window --file=/tmp/editor-annotated.png` run inside the VM, which captures
only the focused window plus its shadow, no desktop background) - check if `gnome-screenshot` is
installed (`ssh ... "which gnome-screenshot"`); install via `sudo apt-get install -y
gnome-screenshot` if not (passwordless sudo, no GUI step needed for this specific install).

Fallback if no native window-capture tool is practical to use here: capture the whole VM window
from the host (`import -window <vm-window-id> /tmp/full.png`), then crop tightly to just
Orcshot's own window + its shadow using ImageMagick (`convert /tmp/full.png -crop
WxH+X+Y /tmp/editor-annotated.png`), confirming the crop bounds visually (zoom into the
candidate image and check no VirtualBox chrome or GNOME desktop background remains) before
finalizing - do not guess crop coordinates without checking the actual result.

Either way, pull the final image back to the working tree:
```bash
scp -i ~/.ssh/orcshot_dev_vm -P 2222 ubuntu2604@localhost:/tmp/editor-annotated.png metainfo-screenshots/editor-annotated.png
```
(create the `metainfo-screenshots/` directory first if it doesn't exist)

- [ ] **Step 4: Verify the real image content directly - don't just assert a file exists**

Read the actual saved `metainfo-screenshots/editor-annotated.png` file and confirm, by looking
at it: a real GNOME-decorated window (title bar, shadow, rounded corners), Orcshot's real editor
UI, a real captured image with a real, visible annotation mark on it, no desktop wallpaper or
VirtualBox chrome visible, not maximized. If anything is wrong, redo Steps 2-3 rather than
committing a bad screenshot - this is a real deliverable direflail will see directly per this
plan's own Global Constraints, not just an internal test fixture.

- [ ] **Step 5: Clean up the VM and commit**

```bash
ssh -i ~/.ssh/orcshot_dev_vm -p 2222 ubuntu2604@localhost \
  "cd <path-to-repo-on-vm> && flatpak uninstall --user -y org.orcshot.Orcshot org.orcshot.Orcshot.Debug && rm -rf build-dir .flatpak-builder-state"
git add metainfo-screenshots/editor-annotated.png
git commit -m "Add the real editor screenshot for the Flathub metainfo"
git rev-parse HEAD
```

Record the printed commit SHA - Task 3 needs it verbatim for the screenshot's pinned URL.

---

### Task 3: Write `org.orcshot.Orcshot.metainfo.xml`

**Files:**
- Create: `org.orcshot.Orcshot.metainfo.xml`
- Modify: `org.orcshot.Orcshot.yaml` (add one install line to the `orcshot` module's
  `build-commands`, right after the existing `.desktop` install line)

**Interfaces:**
- Consumes: Task 2's real commit SHA (for the screenshot's pinned URL) and the real current
  `pyproject.toml` version (for the `<release>` tag).
- Produces: a real, Flathub-lint-passing metainfo file, installed into the Flatpak build.

- [ ] **Step 1: Get the two real values this file needs**

```bash
grep -m1 '^version' pyproject.toml
```
Note the real version string (e.g. `0.2.0`) - use it verbatim for `CURRENT_PYPROJECT_VERSION`
below. Use today's real date (format `YYYY-MM-DD`) for the `<release date="...">` value. Use
Task 2's own recorded commit SHA for `PINNED_COMMIT_SHA` below.

- [ ] **Step 2: Write the file**

Create `org.orcshot.Orcshot.metainfo.xml` at the repo root with this exact content, substituting
only the three bracketed placeholders (`CURRENT_PYPROJECT_VERSION`, `TODAY`,
`PINNED_COMMIT_SHA`) with the real values from Step 1 - every other line is final, not a draft:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<component type="desktop-application">
  <id>org.orcshot.Orcshot</id>
  <metadata_license>CC0-1.0</metadata_license>
  <project_license>GPL-3.0-or-later</project_license>
  <name>Orcshot</name>
  <summary>Capture, annotate, and share screenshots</summary>
  <developer id="org.orcshot">
    <name>Orcshot</name>
  </developer>
  <description>
    <p>
      Orcshot is a screenshot capture and annotation tool for Linux, ported from Windows
      Greenshot. Capture a region, a window, or the full screen, then annotate with shapes,
      text, arrows, and effects before saving, copying, or sending the result wherever it
      needs to go.
    </p>
    <ul>
      <li>Region, window, and full-screen capture on both X11 and Wayland</li>
      <li>A full annotation editor: shapes, text, arrows, highlighting, blur and pixelize
      effects</li>
      <li>Configurable global capture hotkeys</li>
      <li>Send captures straight to the clipboard, a file, or an external command</li>
    </ul>
  </description>
  <launchable type="desktop-id">org.orcshot.Orcshot.desktop</launchable>
  <url type="homepage">https://orcshot.org</url>
  <url type="bugtracker">https://github.com/artificialorctelligence/orcshot/issues</url>
  <url type="vcs-browser">https://github.com/artificialorctelligence/orcshot</url>
  <branding>
    <color type="primary" scheme_preference="light">#8aff01</color>
    <color type="primary" scheme_preference="dark">#3d3d3d</color>
  </branding>
  <content_rating type="oars-1.1" />
  <screenshots>
    <screenshot type="default">
      <image>https://raw.githubusercontent.com/artificialorctelligence/orcshot/PINNED_COMMIT_SHA/metainfo-screenshots/editor-annotated.png</image>
      <caption>Annotate a capture with shapes, text, and effects</caption>
    </screenshot>
  </screenshots>
  <releases>
    <release version="CURRENT_PYPROJECT_VERSION" date="TODAY">
      <description>
        <p>Initial Flathub-ready release.</p>
      </description>
    </release>
  </releases>
</component>
```

The `<description>` prose is a first draft (per the spec's own Known Open Items) - give it one
real read for accuracy against the app's actual current feature set (cross-check against
`debian/control`'s own `Description:` field) before finalizing; fix anything that's drifted, but
don't rewrite it wholesale without a real reason.

- [ ] **Step 3: Install it in the manifest**

In `org.orcshot.Orcshot.yaml`, the `orcshot` module's `build-commands` currently ends (after
Task 1's own edit) with:

```yaml
      - install -Dm644 org.orcshot.Orcshot.desktop /app/share/applications/org.orcshot.Orcshot.desktop
```

Add directly after it:

```yaml
      - install -Dm644 org.orcshot.Orcshot.metainfo.xml /app/share/metainfo/org.orcshot.Orcshot.metainfo.xml
```

- [ ] **Step 4: Real validation against Flathub's own linter**

```bash
flatpak install -y --user flathub org.flatpak.Builder
flatpak run --command=flatpak-builder-lint org.flatpak.Builder appstream org.orcshot.Orcshot.metainfo.xml
```

Expected: exits clean, **zero errors and zero warnings** (Flathub's own real review bar treats
both as failures - a run reporting only warnings is not a pass for this task). If it reports
anything, read the actual message and fix the real cause in the metainfo file - don't suppress
or work around the linter's own complaint.

- [ ] **Step 5: Real build+install confirms the file lands where it should**

```bash
flatpak-builder --user --force-clean --install --state-dir=.flatpak-builder-state build-dir org.orcshot.Orcshot.yaml
flatpak run --command=cat org.orcshot.Orcshot /app/share/metainfo/org.orcshot.Orcshot.metainfo.xml | head -5
```
Expected: the real file's real first few lines print back, confirming it's actually installed at
the right path inside the built app, not just present in the source tree.

```bash
flatpak uninstall --user -y org.orcshot.Orcshot org.orcshot.Orcshot.Debug
rm -rf build-dir .flatpak-builder-state
```

- [ ] **Step 6: Commit**

```bash
git add org.orcshot.Orcshot.metainfo.xml org.orcshot.Orcshot.yaml
git commit -m "Add org.orcshot.Orcshot.metainfo.xml, validated clean against Flathub's own linter"
```

---

### Task 4: CI validation + finish the branch

**Files:**
- Modify: `.github/workflows/flatpak.yml` (add one new step to the `build-flatpak` job)

**Interfaces:**
- Consumes: Task 3's real, lint-clean `org.orcshot.Orcshot.metainfo.xml`.
- Produces: nothing further - this is the plan's own final task.

- [ ] **Step 1: Add the real linter step to CI**

In `.github/workflows/flatpak.yml`, the `build-flatpak` job currently ends with (after the
"Build the Flatpak" step, before "Bundle it into a single distributable file"):

```yaml
      - name: Build the Flatpak
        run: flatpak-builder --force-clean --repo=repo build-dir org.orcshot.Orcshot.yaml

      - name: Bundle it into a single distributable file
```

Insert a new step between them:

```yaml
      - name: Build the Flatpak
        run: flatpak-builder --force-clean --repo=repo build-dir org.orcshot.Orcshot.yaml

      - name: Validate the real metainfo against Flathub's own linter
        run: |
          sudo flatpak install -y flathub org.flatpak.Builder
          flatpak run --command=flatpak-builder-lint org.flatpak.Builder appstream org.orcshot.Orcshot.metainfo.xml

      - name: Bundle it into a single distributable file
```

- [ ] **Step 2: Confirm the whole file is still valid YAML**

Run: `python3 -c "import yaml; yaml.safe_load(open('.github/workflows/flatpak.yml'))" && echo valid`
Expected: `valid` printed.

- [ ] **Step 3: Show direflail the real final output before anything ships**

Per this plan's own Global Constraints: before pushing or opening a PR, show direflail directly
(not just describe) all three real artifacts this plan produced:
- The real, final `git diff` for `org.orcshot.Orcshot.yaml` (Task 1 + Task 3's combined changes).
- The real, full content of `org.orcshot.Orcshot.metainfo.xml`.
- The real screenshot image at `metainfo-screenshots/editor-annotated.png` (send the actual
  file, not a description of it).

Wait for direflail's explicit go-ahead before Step 4.

- [ ] **Step 4: Push, open the PR, confirm real CI passes**

```bash
git push -u origin <branch-name>
gh pr create --base main --title "Flathub readiness: vendored deps, real metainfo, real screenshot, lint validation (BACKLOG #194)" --body "..."
```

Watch the real GitHub Actions run for this PR - confirm `flatpak / build` (including the new
lint step specifically) and `flatpak / verify` both pass for real, not just that the workflow
file parses. Report the real run URL and result.

Per this plan's own Global Constraints, no task subagent merges this PR - report it ready and
wait for the controller/direflail to merge after explicit confirmation.
