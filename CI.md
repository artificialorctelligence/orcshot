# Using the apt CI workflow

Orcshot's `.deb` build, test, and lint steps run automatically on GitHub Actions — you don't invoke
anything by hand. This page is about what you'll actually see and click, not commands to memorize.

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

### A single run's page

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

The same pass/fail shows up directly on the PR's own page as a normal check - no need to go to the
Actions tab separately if you're already looking at a PR.

## What to actually do with this

- **After pushing to `main`:** glance at the top row. Green means nothing broke.
- **Before cutting a release:** `RELEASING.md`'s own step 9 has you check the row for your release
  commit specifically before publishing anything downstream.
- **If something's red:** click the run, click the failed job box, read the log right there. No
  terminal required, though `gh run view <id> --log-failed` works too if you'd rather stay in a
  terminal.

## Scope

This covers only the apt/.deb channel today (`.github/workflows/apt.yml`). Snap and Flatpak get
their own workflows, and their own version of this page, once those channels exist -
see `docs/superpowers/specs/2026-08-29-cross-channel-build-pipeline-design.md` for the overall plan.
