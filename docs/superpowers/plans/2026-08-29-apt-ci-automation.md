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
- No task subagent pushes to `main` directly, at any point (see Plan Amendment 1). All verification
  happens via a PR's own real checks on its own branch; the controller/human partner performs every
  merge to `main`.

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

- [ ] **Step 3: Open a PR - do not push to `main` yourself**

Per **Plan Amendment 1** (see bottom of this document), `push`-triggered workflows do NOT need any
pre-registration on `main` - unlike `workflow_dispatch`, a `push` event fires the moment the pushed
commit itself contains the workflow file, including the very first time. There is nothing to
"register" here, so there is also nothing that justifies pushing to `main` directly.

```bash
gh pr create --base main --head ci/apt-build-job \
  --title "Add apt CI: build, test, lint" \
  --body "Wraps RELEASING.md's existing manual build/test/lint steps (2, 4, 5) into a GitHub Actions job that runs on every push to main. Part of docs/superpowers/plans/2026-08-29-apt-ci-automation.md."
```

Because this is the *first* version of a brand-new workflow file, GitHub's `pull_request` trigger
requirement (the workflow must already exist on the default branch - see Plan Amendment 1) means
there is genuinely no way to get an automated pre-merge check on this specific PR. That's a real,
documented GitHub platform limitation for a workflow's first-ever version, not a shortcut being
taken here - review the YAML by eye, then stop.

**Stop here and hand back to the controller/human partner.** Merging to `main` is a side effect
outside this task's own branch - do not run `gh pr merge` yourself. Report the PR URL and your
`DONE`/`DONE_WITH_CONCERNS` status; the controller merges it.

- [ ] **Step 4: (controller/human partner) Merge the PR, then confirm the first real run**

Once merged (a normal, non-destructive merge - no force-pushes, no history rewriting), the merge
push itself is what triggers the workflow for the very first time:

```bash
gh run list --workflow=apt.yml --limit 3
gh run view --log --workflow=apt.yml
```

Expected: `success`. If it fails, fix forward with a small, normal follow-up commit and PR (same
merge-via-controller pattern) - never a deliberately-broken commit pushed to `main`, and never a
force-push or reset. A job failing on a bad step (bad package name, wrong path, etc.) reporting red
in the Actions UI is GitHub's own well-established platform guarantee, not something this project
needs to re-prove for itself by breaking `main` on purpose.

---

### Task 2: The `verify` job - install and confirm it launches

**Files:**
- Modify: `.github/workflows/apt.yml`

**Interfaces:**
- Consumes: the `orcshot-deb` artifact Task 1's `build` job uploads.

- [ ] **Step 0: Add `pull_request` as a second trigger**

`apt.yml` now exists on `main` (Task 1 landed it), so per Plan Amendment 1, `pull_request`-triggered
checks now work correctly for every future PR that touches this file - GitHub runs the *PR branch's*
version of an already-registered workflow, giving real pre-merge signal. Add it alongside the
existing `push` trigger (don't replace it - pushes straight to `main`, e.g. a hotfix, still need
their own run):

```yaml
on:
  push:
    branches: [main]
  pull_request:
    branches: [main]
```

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

- [ ] **Step 2: Push and open (or update) the PR - confirm it runs green via the PR's own checks**

```bash
git add .github/workflows/apt.yml
git commit -m "Add the apt CI verify job: install the built .deb, confirm it launches"
git push origin ci/apt-build-job
```

Because `apt.yml` already exists on `main` (Step 0 above explains why this matters), the
`pull_request` trigger now fires for real on this branch's own commits - no push to `main` needed:

```bash
gh pr create --base main --head ci/apt-build-job \
  --title "Add apt CI: build, test, lint, and install-and-launch verification" \
  --body "Extends the apt CI workflow with a verify job that installs the built .deb and confirms it launches. Part of docs/superpowers/plans/2026-08-29-apt-ci-automation.md." \
  2>/dev/null || echo "PR already exists from Task 1 - pushing to the branch updates it automatically"

gh pr checks ci/apt-build-job --watch
```

Expected: both `build` and `verify` show `success` on the PR's own checks.

- [ ] **Step 3: Confirm `verify` fails correctly on a real install problem - entirely on the branch**

Deliberately break something, push it to the *branch*, watch the PR's own check go red, then
revert - never touching `main`:

```bash
sed -i 's/gir1.2-gtk-3.0,/gir1.2-gtk-3.0-DOES-NOT-EXIST,/' debian/control
git add debian/control
git commit -m "TEMPORARY: break a real dependency to confirm verify catches an install failure"
git push origin ci/apt-build-job
gh pr checks ci/apt-build-job --watch
# Expected: build itself likely fails here (a bad Depends line breaks dpkg-buildpackage) -
# confirms the failure surfaces somewhere real, even if it's caught one job earlier than verify
# specifically.

git revert HEAD --no-edit
git push origin ci/apt-build-job
gh pr checks ci/apt-build-job --watch
# Expected: green again
```

- [ ] **Step 4: Stop and hand back to the controller/human partner**

The branch and its PR are ready, both jobs verified green (and verified to correctly go red) via
the PR's own real checks. Report the PR URL and your `DONE`/`DONE_WITH_CONCERNS` status - do not
run `gh pr merge` yourself. Nothing was ever pushed to `main` directly in this task, so there is
nothing to reset.

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

- [ ] **Step 2: Push and confirm it runs green via the PR's own checks**

```bash
git add .github/workflows/apt.yml
git commit -m "Add the headless-gnome-shell tray-extension-load check to verify"
git push origin ci/apt-build-job
gh pr checks ci/apt-build-job --watch
```

Expected: `build` and `verify` both `success`, and the run's `shell-log` artifact (find the run via
`gh run list --branch ci/apt-build-job --limit 1`, then `gh run download <run-id> -n shell-log`)
shows `GNOME Shell started` with no `JS ERROR`/`Gjs-CRITICAL` lines.

- [ ] **Step 3: Confirm it fails correctly - entirely on the branch, never touching `main`**

```bash
sed -i "s/log('orcshot-tray-diag: bus name vanished');/undefinedFunctionCallToBreakThis();/" \
  src/orcshot/resources/gnome-shell-extensions/orcshot-tray@orcshot.org/extension.js 2>/dev/null || \
  echo "throw new Error('deliberate test break');" >> \
  src/orcshot/resources/gnome-shell-extensions/orcshot-tray@orcshot.org/extension.js
git add src/orcshot/resources/gnome-shell-extensions/orcshot-tray@orcshot.org/extension.js
git commit -m "TEMPORARY: break the extension to confirm the headless check catches it"
git push origin ci/apt-build-job
gh pr checks ci/apt-build-job --watch
# Expected: verify fails

git revert HEAD --no-edit
git push origin ci/apt-build-job
gh pr checks ci/apt-build-job --watch
# Expected: green again
```

- [ ] **Step 4: Stop and hand back to the controller/human partner**

The PR (opened in Task 1, extended by Tasks 2 and 3) now has all three verification tiers green
on its own real checks, and each was confirmed to correctly go red. Report the PR URL and your
`DONE`/`DONE_WITH_CONCERNS` status - do not run `gh pr merge` yourself. Nothing was ever pushed to
`main` directly across any of the three tasks, so there is nothing to reset. Once the controller
merges, the workflow is live on every future push to `main`, exactly as intended.

---

## Plan Amendment 1 (during Task 1 execution)

Task 1's implementer hit a real, hard block: this environment's own permission classifier refuses
a direct `git push` to `main` from an agent, regardless of prior in-chat user authorization for
that specific action - the classifier evaluates the live push itself, and does not treat another
agent's dispatch context as consent. The implementer correctly refused to route around the block
via an equivalent action (e.g. `gh pr merge`) and reported back instead of guessing.

Investigating the root premise (rather than just finding a workaround) turned up that the premise
itself was wrong: GitHub's official docs confirm `push`-triggered workflows do **not** require any
pre-registration on the default branch - that constraint is real, but specific to
`workflow_dispatch` (confirmed earlier in this project via a real, live spike). A `push`-triggered
workflow fires correctly the very first time, from the very commit that adds the file. `pull_request`-
triggered workflows genuinely DO require the workflow file to already exist on the default branch
first - a real, asymmetric platform rule, not something this plan can design around for a
brand-new file's very first version.

**Revised mechanism**, replacing the "temporarily push to main / prove red / force-reset" steps
throughout: implementer subagents never push to `main` directly, in any task. Task 1 opens a PR
with the first version of the workflow (no pre-merge CI possible for this one PR - a real,
disclosed limitation, not a shortcut) and hands back to the controller/human partner to merge.
Once `apt.yml` exists on `main`, `pull_request` becomes an additional trigger (Task 2's Step 0) -
every later PR against this file gets real pre-merge signal from the PR's own commits, including
the deliberate-break-then-revert verification steps, entirely on the branch. Every task ends by
handing back to the controller for the actual merge - a merge to a shared branch is explicitly a
"stop and ask" action, not something a task subagent decides on its own.

This is a strictly safer design than the one it replaces (no force-pushes, no history rewrites, no
commits that deliberately break `main` even briefly) as well as a correct one - not a compromise
made to route around the permission block, but the fix the investigation actually pointed to.

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
