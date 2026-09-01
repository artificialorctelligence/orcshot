# Using the CI workflows

Orcshot's `.deb`, `.snap`, and Flatpak build, test, and verify steps run automatically on GitHub
Actions — you don't invoke anything by hand. This page is about what you'll actually see and click,
not commands to memorize.

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

All three workflows' pass/fail show up directly on the PR's own page as normal checks - no need to go
to the Actions tab separately if you're already looking at a PR. The apt checks are named `build` and
`verify`; the snap checks are named `snap / build` and `snap / verify`; the Flatpak checks are named
`flatpak / build` and `flatpak / verify` - so it's still clear which row belongs to which channel even
though only apt's own doesn't spell it out in its name.

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

## The Flatpak CI workflow

The Flatpak channel (`.github/workflows/flatpak.yml`) runs on the same triggers, shows up on the same
Actions page and the same PR checks, and its job shape mirrors the apt/snap workflows above - build,
then install-and-verify the thing `build` produced.

### A single Flatpak run's page

- Overall status and total duration at the top, same as an apt or snap run
- Two boxes, one per job:
  - **`flatpak / build`** - installs `flatpak-builder` plus the `org.gnome.Platform`/`org.gnome.Sdk`
    runtime and SDK, builds the app from `org.orcshot.Orcshot.yaml`, bundles it into one
    `orcshot_<version>.flatpak` file (the version comes straight from `pyproject.toml`, same one
    `RELEASING.md` step 1 has you update), uploads it
  - **`flatpak / verify`** - installs the built bundle, confirms it launches, runs a regression check
    that would have caught this channel's own worst bug (an autostart call that silently aborted the
    entire first-run setup dialog - see BACKLOG #185's resolution if you want the story), runs the
    app's real first-run extension-install code path, then boots the same kind of real headless GNOME
    Shell as the apt/snap workflows and confirms the `orcshot-tray@orcshot.org` extension both loads
    with no errors *and* that the activation actually reached the host's real settings (the part that
    answers "does this survive a logout")
- Click into either box for the step-by-step log, same as apt/snap.
- An **Artifacts** section at the bottom - the built `orcshot_<version>.flatpak` itself, and
  `shell-log`, both downloadable per run.

## What to actually do with this

- **After pushing to `main`:** glance at the top row of each workflow. Green means nothing broke.
- **Before cutting a release:** `RELEASING.md`'s own step 9 has you check the row for your release
  commit specifically before publishing anything downstream - for the apt, snap, and Flatpak workflows
  all three.
- **If something's red:** click the run, click the failed job box, read the log right there. No
  terminal required, though `gh run view <id> --log-failed` works too if you'd rather stay in a
  terminal.

## Scope

This covers all three of Orcshot's packaging channels: apt/.deb (`.github/workflows/apt.yml`), Snap
(`.github/workflows/snap.yml`), and Flatpak (`.github/workflows/flatpak.yml`) - see
`docs/superpowers/specs/2026-08-29-cross-channel-build-pipeline-design.md` for the overall
cross-channel plan.
