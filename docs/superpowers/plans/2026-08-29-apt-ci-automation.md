# apt/.deb CI Automation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wrap `RELEASING.md`'s existing manual build/test/lint checklist (steps 2, 4, 5) into a
GitHub Actions workflow that runs automatically on every push to `main`, plus a real install-and-
launch verification pass — so a change that breaks the `.deb` build, or breaks the Wayland tray
extension, is caught within minutes of pushing it, not discovered at release time.

**Architecture:** One new workflow file, `.github/workflows/apt.yml`, with two jobs. `build`
does exactly what `RELEASING.md` steps 2/4/5 already do by hand (`pytest`, `dpkg-buildpackage`,
`lintian`) and uploads the resulting `.deb` as a build artifact. `verify` downloads that artifact,
installs it fresh, confirms the binary launches, then runs a real headless GNOME Shell to confirm
`orcshot-tray@orcshot.org` (already merged into `main`, from #184's own redesign) loads with no
errors - the exact recipe already proven live on a real `ubuntu-24.04` GitHub Actions runner
earlier in this same project. This is the first of several channel-specific CI workflows the
project's own pipeline design calls for; Snap and Flatpak get their own, later, separate plans.

**Tech Stack:** GitHub Actions (`ubuntu-24.04` runner), the project's existing `dpkg-buildpackage`/
`pytest`/`lintian` toolchain (nothing new there), `gnome-shell`/`dbus-x11` for the headless
verification step (new to CI, not new to the project - this is real Ubuntu package, already used
manually on the project's own test VM).

**Spec:** `docs/superpowers/specs/2026-08-29-cross-channel-build-pipeline-design.md`

## Global Constraints

- Trigger: on every push to `main` (spec's own Goal - catch breakage on every change, not just at
  release time).
- Runner: `ubuntu-24.04` (a real target this project already ships to; also the version this
  project's own headless-GNOME-Shell recipe was proven against).
- No secrets, no publishing anywhere (PPA, GitHub Releases, etc.) - build and verify only. This
  plan does not touch `RELEASING.md`'s steps 6-10 (PPA upload, tag/push, GitHub Release) at all.
- `build` and `verify` are separate jobs, not one - a `verify` failure (the newer, less-proven
  headless-Shell check) must never look like a `build` failure (the well-understood "does the
  package compile" signal) in the Actions UI. `verify` depends on `build`'s uploaded artifact via
  `actions/upload-artifact`/`actions/download-artifact`, not by rebuilding.
- This project has zero prior GitHub Actions experience on direflail's side - every step below
  spells out exact commands and exact places to look in the GitHub UI, not just "set up CI."

---

### Task 1: The `build` job - package, test, lint

**Files:**
- Create: `.github/workflows/apt.yml`

**Interfaces:**
- Produces: a GitHub Actions artifact named `orcshot-deb` containing the built `orcshot_*_all.deb`,
  consumed by Task 2's `verify` job via `actions/download-artifact@v4` with that same name.

This task has no Python code to write - it's a YAML workflow file. "Watching it fail" here means
confirming the job actually reports failure when something's broken (not just trusting that it
would), the CI-native equivalent of red-before-green.

- [ ] **Step 1: Write the workflow file with just the `build` job**

```yaml
name: apt

on:
  push:
    branches: [main]

jobs:
  build:
    runs-on: ubuntu-24.04
    steps:
      - uses: actions/checkout@v4

      - name: Install build dependencies
        run: |
          sudo apt-get update -qq
          sudo apt-get build-dep -y .

      - name: Run the test suite
        run: |
          python3 -m venv .venv
          .venv/bin/pip install -e ".[dev]"
          .venv/bin/pytest tests/ -q

      - name: Build the .deb
        run: dpkg-buildpackage -us -uc -b

      - name: Lint the .deb
        run: lintian ../orcshot_*_all.deb

      - name: Upload the built .deb
        uses: actions/upload-artifact@v4
        with:
          name: orcshot-deb
          path: ../orcshot_*_all.deb
```

`apt-get build-dep -y .` reads `debian/control`'s own `Build-Depends` directly, rather than this
workflow hardcoding a duplicate package list that could drift out of sync with it later.

- [ ] **Step 2: Push this file to a new branch, not `main` directly**

```bash
git checkout -b ci/apt-build-job
git add .github/workflows/apt.yml
git commit -m "Add the apt CI build job (test + dpkg-buildpackage + lintian)"
git push -u origin ci/apt-build-job
```

- [ ] **Step 3: Register the workflow with GitHub's Actions API**

A brand-new workflow file only becomes triggerable via `workflow_dispatch`/API once it exists on
the repository's *default* branch (`main`) - a real GitHub quirk, confirmed live earlier in this
project. Since this workflow triggers on `push: branches: [main]` (not `workflow_dispatch`), the
simplest way to get a first real run without merging unverified code to `main` is to temporarily
push this one file directly to `main`, confirm the job works, and only then open a real PR for it
(Step 6 below) - the same pattern already used successfully once earlier in this project for a
throwaway CI spike.

```bash
git checkout main
git checkout ci/apt-build-job -- .github/workflows/apt.yml
git add .github/workflows/apt.yml
git commit -m "Temporarily add apt.yml to main to register it with the Actions API"
git push origin main
```

- [ ] **Step 4: Confirm the job actually runs and succeeds**

```bash
gh run list --workflow=apt.yml --limit 3
```

Expected: a run appears with status `in_progress`, then (after a minute or two) `completed` /
`success`. If you'd rather watch it in a browser: `https://github.com/<owner>/<repo>/actions`.

If it fails, get the full log before guessing at a fix:

```bash
gh run view --log --workflow=apt.yml
```

- [ ] **Step 5: Confirm it correctly reports failure too - don't just trust the happy path**

Deliberately break something cheap and obvious, push it, confirm the job goes red, then revert:

```bash
echo "def this_is_not_valid_python(" >> tests/unit/test_settings.py
git add tests/unit/test_settings.py
git commit -m "TEMPORARY: break a test to confirm the CI job reports failure correctly"
git push origin main
gh run list --workflow=apt.yml --limit 1
# Expected: status completed, conclusion failure

git revert HEAD --no-edit
git push origin main
gh run list --workflow=apt.yml --limit 1
# Expected: status completed, conclusion success again
```

- [ ] **Step 6: Move the real work back to the branch and open it as a normal change**

The two commits made directly to `main` above (Step 3's temporary add, Step 5's break-then-revert
pair) were only to get a first real signal - `main`'s own history now has some noise from that.
Reset `main` back to before this task started, and land the *real*, single clean commit through
the branch instead:

```bash
git log --oneline -5   # find the commit SHA from before Step 3's temporary push
git checkout main
git reset --hard <sha-from-before-step-3>
git push origin main --force-with-lease
git checkout ci/apt-build-job
git push -u origin ci/apt-build-job --force-with-lease
```

`--force-with-lease` (not bare `--force`) refuses to overwrite if someone else pushed to `main` in
the meantime - confirm nothing else landed there since Step 3 before running this.

---

### Task 2: The `verify` job - install and confirm it launches

**Files:**
- Modify: `.github/workflows/apt.yml`

**Interfaces:**
- Consumes: the `orcshot-deb` artifact Task 1's `build` job uploads.

- [ ] **Step 1: Add the `verify` job, depending on `build`**

```yaml
  verify:
    needs: build
    runs-on: ubuntu-24.04
    steps:
      - name: Download the built .deb
        uses: actions/download-artifact@v4
        with:
          name: orcshot-deb

      - name: Install it
        run: sudo apt-get install -y ./orcshot_*_all.deb

      - name: Confirm the installed binary launches without crashing
        run: orcshot --help
```

`orcshot --help` is a safe, real smoke test - GLib's own option-parsing machinery handles it
without opening a window, registering D-Bus, or needing a display, so it genuinely just confirms
the installed binary starts and every import it needs actually resolves (a real, common class of
bug: a dependency missing from `debian/control` that happened to already be present in whatever
environment someone last tested on by hand).

- [ ] **Step 2: Push and confirm it runs green**

```bash
git add .github/workflows/apt.yml
git commit -m "Add the apt CI verify job: install the built .deb, confirm it launches"
git push origin ci/apt-build-job
```

This branch isn't on `main` yet, so this push alone won't trigger anything (the workflow's trigger
is `push: branches: [main]`). Repeat Task 1 Step 3's same temporary-push pattern to get a real run:

```bash
git checkout main
git checkout ci/apt-build-job -- .github/workflows/apt.yml
git add .github/workflows/apt.yml
git commit -m "Temporarily add the verify job to main to test it"
git push origin main
gh run list --workflow=apt.yml --limit 1
gh run view --log --workflow=apt.yml
```

Expected: both `build` and `verify` show `success`.

- [ ] **Step 3: Confirm `verify` fails correctly on a real install problem**

```bash
sed -i 's/gir1.2-gtk-3.0,/gir1.2-gtk-3.0-DOES-NOT-EXIST,/' debian/control
git add debian/control
git commit -m "TEMPORARY: break a real dependency to confirm verify catches an install failure"
git push origin main
gh run list --workflow=apt.yml --limit 1
# Expected: build itself likely fails here (a bad Depends line breaks dpkg-buildpackage) -
# confirms the failure surfaces somewhere real, even if it's caught one job earlier than verify
# specifically. Revert either way:
git revert HEAD --no-edit
git push origin main
```

- [ ] **Step 4: Reset `main` and land the real change through the branch, same as Task 1 Step 6**

```bash
git log --oneline -6   # find the commit SHA from before this task's temporary pushes
git checkout main
git reset --hard <sha-from-before-this-task>
git push origin main --force-with-lease
git checkout ci/apt-build-job
git push -u origin ci/apt-build-job --force-with-lease
```

---

### Task 3: Headless GNOME Shell check - confirm the tray extension actually loads

**Files:**
- Modify: `.github/workflows/apt.yml`

**Interfaces:**
- Consumes: `orcshot-tray@orcshot.org`'s real extension files, already present in this repo at
  `src/orcshot/resources/gnome-shell-extensions/orcshot-tray@orcshot.org/{extension.js,metadata.json}`
  (merged into `main` by #184's own Wayland tray redesign - nothing new to build here, just
  exercising what's already there).

This is the exact recipe already proven live on a real `ubuntu-24.04` GitHub Actions runner earlier
in this project (a throwaway spike workflow, since deleted per its own "delete once answered"
promise) - transcribe it into this permanent job rather than re-deriving it.

- [ ] **Step 1: Extend the `verify` job with the headless-Shell steps**

```yaml
      - name: Install gnome-shell and headless deps
        run: |
          sudo apt-get install -y gnome-shell dbus-x11

      - name: Copy the real extension into the per-user extensions path
        run: |
          mkdir -p ~/.local/share/gnome-shell/extensions/orcshot-tray@orcshot.org
          cp src/orcshot/resources/gnome-shell-extensions/orcshot-tray@orcshot.org/extension.js \
             src/orcshot/resources/gnome-shell-extensions/orcshot-tray@orcshot.org/metadata.json \
             ~/.local/share/gnome-shell/extensions/orcshot-tray@orcshot.org/

      - name: Launch gnome-shell headless against a fixed D-Bus session bus
        run: |
          mkdir -p /run/user/$(id -u)
          chmod 700 /run/user/$(id -u)
          dbus-daemon --session --address=unix:path=/run/user/$(id -u)/bus --fork
          export XDG_RUNTIME_DIR=/run/user/$(id -u)
          export DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/$(id -u)/bus
          nohup gnome-shell --headless --virtual-monitor 1024x768 > /tmp/shell.log 2>&1 &
          disown
          sleep 8
          pgrep -af gnome-shell || (echo "gnome-shell did not stay running" && cat /tmp/shell.log && exit 1)

      - name: Enable the real extension and confirm it loads with no errors
        run: |
          export XDG_RUNTIME_DIR=/run/user/$(id -u)
          export DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/$(id -u)/bus
          gnome-extensions enable orcshot-tray@orcshot.org
          sleep 2
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

Note: `src/orcshot/resources/gnome-shell-extensions/...` is read directly from this job's own
checkout of the repo, not from the installed `.deb` - this step doesn't need `actions/checkout` to
run again since `verify` is a separate job in the same workflow (each job gets its own fresh
checkout automatically via `actions/checkout@v4` in `build`'s steps, but `verify` needs its own
`actions/checkout@v4` step too, since jobs don't share a filesystem). Add that as this task's own
first step, immediately after the `needs: build` job header, before the download-artifact step.

- [ ] **Step 2: Push, register, and confirm it runs green**

Same temporary-push-to-`main` pattern as the previous two tasks:

```bash
git add .github/workflows/apt.yml
git commit -m "Add the headless-gnome-shell tray-extension-load check to verify"
git checkout main
git checkout ci/apt-build-job -- .github/workflows/apt.yml
git add .github/workflows/apt.yml
git commit -m "Temporarily add the headless-Shell check to main to test it"
git push origin main
gh run list --workflow=apt.yml --limit 1
gh run view --log --workflow=apt.yml
```

Expected: `build` and `verify` both `success`, and the run's `shell-log` artifact (downloadable via
`gh run download <run-id> -n shell-log`) shows `GNOME Shell started` with no `JS ERROR`/
`Gjs-CRITICAL` lines.

- [ ] **Step 3: Confirm it fails correctly - a real JS error in the extension should fail the job**

```bash
sed -i "s/log('orcshot-tray-diag: bus name vanished');/undefinedFunctionCallToBreakThis();/" \
  src/orcshot/resources/gnome-shell-extensions/orcshot-tray@orcshot.org/extension.js 2>/dev/null || \
  echo "throw new Error('deliberate test break');" >> \
  src/orcshot/resources/gnome-shell-extensions/orcshot-tray@orcshot.org/extension.js
git add src/orcshot/resources/gnome-shell-extensions/orcshot-tray@orcshot.org/extension.js
git commit -m "TEMPORARY: break the extension to confirm the headless check catches it"
git push origin main
gh run list --workflow=apt.yml --limit 1
# Expected: verify fails
git revert HEAD --no-edit
git push origin main
```

- [ ] **Step 4: Reset `main` and land the final, real change through a real PR**

```bash
git log --oneline -8   # find the commit SHA from before Task 1 Step 3's first temporary push
git checkout main
git reset --hard <sha-from-before-task-1>
git push origin main --force-with-lease
git checkout ci/apt-build-job
git push -u origin ci/apt-build-job --force-with-lease
gh pr create --base main --head ci/apt-build-job \
  --title "Add apt CI: build, test, lint, and headless tray-extension verification" \
  --body "Wraps RELEASING.md's existing manual build/test/lint steps into GitHub Actions, running on every push to main, plus a real install-and-launch check and a headless GNOME Shell check confirming orcshot-tray@orcshot.org loads with no errors. First of three channel-specific CI workflows per docs/superpowers/specs/2026-08-29-cross-channel-build-pipeline-design.md - Snap and Flatpak follow in their own separate plans."
```

Merge the PR once GitHub's own PR checks show the workflow passing on the branch itself (a PR
against `main` with a workflow already registered on `main` triggers real checks on the PR's own
commits, the same as any other CI-backed PR) - at that point the workflow is live for real, on
every future push to `main`, exactly as intended.

---

## Self-Review Notes

- **Spec coverage**: this plan implements exactly the "apt.yml" bullet from the spec's own "CI
  architecture" section (`build` + `verify`, split per its own reasoning), using the exact
  `verify`-job headless-Shell recipe the spec itself documents as already proven. The new channel-
  detection/extension-install Python module, Snap, Flatpak, and any publish automation are all
  explicitly out of this plan's scope per the spec's own phasing - not gaps, deliberate exclusions.
- **The "register on main before merging" pattern** appears three times (once per task) because
  each task needs its own real, live confirmation that the growing workflow still works - deferring
  all three to one final check at the end of Task 3 would mean a failure discovered there could be
  in any of three different additions, harder to isolate than confirming incrementally.
- **Type/interface consistency**: Task 2 and Task 3 both extend the same `verify:` job block Task 1
  first establishes the shape of (`needs: build`, `runs-on: ubuntu-24.04`) - no renamed keys or
  restructuring between tasks.
