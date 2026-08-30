# Using the CI workflows

Orcshot's `.deb` and `.snap` build, test, and verify steps run automatically on GitHub Actions — you
don't invoke anything by hand. This page is about what you'll actually see and click, not commands to
memorize.

## When it runs

- Every push to `main`
- Every pull request targeting `main`

## Where to look

**[github.com/artificialorctelligence/orcshot/actions](https://github.com/artificialorctelligence/orcshot/actions)**

That's the whole interface - a normal GitHub web page, always up to date, nothing to set up.

### The list view

One row per run, newest first. Each row shows what triggered it (a commit or a pull request), which
branch, and a status icon:

- ✅ green checkmark = passed
- ❌ red X = failed
- 🟡 yellow dot = still running

### A single apt run's page

Click any row to open it. You'll see:

- Overall status ("Success" / "Failure") and total duration at the top
- Two boxes, one per job:
  - **`build`** - installs dependencies, runs the test suite, builds the `.deb`, lints it, uploads it
  - **`verify`** - installs the built `.deb`, confirms it launches, boots a real headless GNOME
    Shell and confirms the `orcshot-tray@orcshot.org` extension loads with no errors
- Click into either box to expand the step-by-step log. If a step failed, that's where the red X and
  the actual error output are.
- An **Artifacts** section at the bottom - the built `.deb` itself, and `shell-log` (the real GNOME
  Shell log from the headless check), both downloadable per run.

### On a pull request

Both workflows' pass/fail show up directly on the PR's own page as normal checks - no need to go to
the Actions tab separately if you're already looking at a PR. The apt checks are named `build` and
`verify`; the snap checks are named `snap / build` and `snap / verify`, so it's still clear which row
belongs to which channel even though only one of the two workflows spells it out in its name.

## The snap CI workflow

The Snap channel (`.github/workflows/snap.yml`) runs on the same triggers, shows up on the same
Actions page and the same PR checks, and its job shape mirrors the apt workflow above almost exactly
- just building and exercising a `.snap` instead of a `.deb`.

### A single snap run's page

- Overall status and total duration at the top, same as an apt run
- Two boxes, one per job:
  - **`snap / build`** - builds the `.snap` with `canonical/action-build`, uploads it
  - **`snap / verify`** - installs the built `.snap` with `--dangerous`, connects the
    `personal-files` interface it needs, confirms it launches, runs the app's real first-run
    extension-install code path, then boots the same kind of real headless GNOME Shell as the apt
    workflow and confirms the `orcshot-tray@orcshot.org` extension loads with no errors
- Click into either box for the step-by-step log, same as apt.
- An **Artifacts** section at the bottom - the built `.snap` itself, and `shell-log`, both
  downloadable per run.

## What to actually do with this

- **After pushing to `main`:** glance at the top row of each workflow. Green means nothing broke.
- **Before cutting a release:** `RELEASING.md`'s own step 9 has you check the row for your release
  commit specifically before publishing anything downstream - for both the apt and snap workflows.
- **If something's red:** click the run, click the failed job box, read the log right there. No
  terminal required, though `gh run view <id> --log-failed` works too if you'd rather stay in a
  terminal.

## Scope

This covers the apt/.deb channel (`.github/workflows/apt.yml`) and the Snap channel
(`.github/workflows/snap.yml`). Flatpak gets its own workflow, and its own version of this page, once
that channel exists - see `docs/superpowers/specs/2026-08-29-cross-channel-build-pipeline-design.md`
for the overall plan.
