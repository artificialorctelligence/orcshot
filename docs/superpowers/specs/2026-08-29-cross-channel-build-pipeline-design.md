# Cross-channel build/release pipeline — design

## Goal

Catch cross-channel packaging breakage early — on every change, automatically — rather than
discovering it at release time. This is the direct lesson of the `AyatanaAppIndicator3`/Snap-
incompatibility discovery that started #184: a real, working feature that turned out to be
fundamentally incompatible with a distribution channel, found only when someone actually tried to
ship it there. Sequenced, per direflail's own explicit preference: build the "catch it early"
piece first (no secrets, no publish automation), extend to full release automation later once
that's solid and trusted.

direflail's own framing of the actual pain point: "if we change something, i want to make sure it
works in everything early. if a change breaks a build, i want to know early. and i don't want to
go through long processes every time where one or both of us get distracted."

## Scope

**In scope now:**
- Automating the existing apt-family release path (Ubuntu 24.04 "noble", Ubuntu 26.04 "resolute",
  Linux Mint) - already hand-verified today per `RELEASING.md`'s own checklist, not yet automated.
  Confirmed: `Architecture: all` with no series-specific build-dependencies means this is really
  *one* build verified across three targets, not three separate compiles.
- A real, non-throwaway Flatpak build (BACKLOG #185) - Wayland-only, no X11, since Flatpak's X11
  path is unreliable/portal-forced (already-recorded finding; BACKLOG #187 is the still-open
  question of whether `fallback-x11` could change this later).
- A real, non-throwaway Snap build (direct follow-on from #184's own live-verified Snap-
  confinement proof) - ships **both** X11 and Wayland, since Snap's X11 support is confirmed
  genuine/unmediated (Flameshot's own real, published `strict`-confinement snapcraft.yaml uses the
  plain `x11` interface, not portal-mediated).
- CI automation (GitHub Actions) that builds and verifies all of the above on every push to `main`.

**Explicitly out of scope for now, but must not be designed against:**
- Fedora/RPM (BACKLOG #132, stays at its existing "someday" priority). Whatever gets built here
  must stay flexible enough to add an RPM build later without a rewrite - see "Extensibility"
  below for what that actually means in practice.
- Publish/upload automation (PPA upload, Snap Store submission, Flathub submission) - a distinct,
  later phase. This spec covers build + verify only.
- "Software Manager" (Mint's `mintinstall`, GNOME Software) is not its own build target - both are
  front-ends that consume already-published Snap/Flatpak/apt packages. Nothing here builds
  specifically *for* them.

## Real distribution-format research, not assumption

Two questions this design depends on were answered live, not read from documentation alone,
during this same session:

**Can a sandboxed app get `orcshot-tray@orcshot.org`'s files into GNOME Shell's discoverable
per-user extensions path?** Yes, for both formats, via genuinely different mechanisms:
- **Flatpak**: `--filesystem=~/.local/share/gnome-shell/extensions` in `finish-args` - a scoped,
  real (non-redirected) home-directory grant, auto-connected at install with no store-review gate.
  Confirmed via a real, current (GNOME Platform 49), actively-maintained Flatpak app
  ([mjakeman/extension-manager](https://github.com/mjakeman/extension-manager)) whose own manifest
  declares exactly this.
- **Snap**: the `personal-files` interface - grants a specific real path, bypassing Snap's normal
  `$HOME` redirection to a private `~/snap/<name>/<rev>/` directory (confirmed live: a throwaway
  strict-confinement Snap hit a real `apparmor="DENIED"` writing to the real path via the plain
  `home` interface alone; `personal-files` is what actually works). **Not** auto-connected even for
  an approved/published snap (confirmed against the interface's own docs, and against a real,
  current [privileged-interface review thread](https://forum.snapcraft.io/t/privileged-interface-review-request-for-downman-personal-files-x4-shutdown/52854)
  from days before this spec was written) - the user must manually run `snap connect` after
  install. Marked "super-privileged," requiring a real Canonical review before store distribution
  (real, current process: post in the Snapcraft forum's `privileged-interfaces` category with the
  snap name, manifest link, upstream repo, and a per-path technical justification; real observed
  turnaround in the cited example was ~2 days for first response). Reviewers actively push back on
  broad `personal-files` requests - Orcshot's own ask (one specific, standard, narrow GNOME path,
  for the specific, legitimate purpose of installing its own bundled extension) is a much easier
  case than most requests found during this research.

**Does headless GNOME Shell + real extension loading work in CI at all?** Yes, on a real
GitHub Actions VM runner - confirmed live in this same session (see "Verify job" below for the
exact recipe). An LXD container was tried first and failed (a `systemd-logind` D-Bus activation
timeout specific to that container's restricted init), which could have wrongly been read as "this
doesn't work" - the real GitHub-hosted VM runner, which has a full systemd/init stack, had no such
problem: GNOME Shell started, ran the actual `orcshot-tray@orcshot.org` extension.js unmodified,
and the extension's own diagnostic log line fired with zero JS errors anywhere in the log.

## New Orcshot code needed

Neither Flatpak nor Snap can write to the system-wide `/usr/share/gnome-shell/extensions/` the way
`.deb`'s root-privileged `dh_install` can - both need a **new, currently-nonexistent** first-run
step: detect which sandboxed channel (if any) the app is running under, and if so, copy the
already-bundled extension files to the per-user path.

**Channel detection**: `$FLATPAK_ID`/`/.flatpak-info` for Flatpak, `$SNAP`/`$SNAP_NAME` for Snap,
neither present means a plain `.deb` install (this logic does nothing at all in that case - the
package's own install step already placed the files system-wide).

**First-run copy**: if sandboxed and the extension files at
`~/.local/share/gnome-shell/extensions/orcshot-tray@orcshot.org/` are missing or stale, copy them
from wherever they're bundled read-only inside the package (`/app/...` for Flatpak, `$SNAP/...`
for Snap).

This plugs into the *existing* `gnome_extension_setup.py`/`first_run_setup.py` wizard, not a new
UI flow - same "enabling only ever happens from the user's own confirmation click" principle
already established there, just gated on "and copy the files first, if sandboxed."

**Snap-specific UX, since `personal-files` is never auto-connected**: if the copy fails because
the interface isn't connected, show a dialog explaining what's needed with the exact
`snap connect orcshot:dot-local-share-gnome-shell` command in a copyable field (a "Copy to
Clipboard" button) - not attempting to launch a terminal (not reliably possible under strict
confinement, and fragile even where it might be). This matches an already-established pattern in
this exact codebase: `first_run_setup.py`'s own "manual, cut-and-pasteable CLI-flag cheat sheet"
for hotkey auto-configuration on desktops it can't configure automatically. Real research (GIMP,
Firefox, and Thunderbird's own official Snap packaging all declare `personal-files` for real needs,
none show any in-app handling of the missing-connection case) suggests this friction is accepted,
unsolved friction across the wider Snap ecosystem, not something Orcshot is uniquely bad at -
matching this existing pattern is proportionate, not a corner cut.

## CI architecture

**GitHub Actions, one pair of workflow files per channel, each independent.** Chosen over a single
combined workflow (risks one channel's edits breaking another's job) and over a shared reusable-
workflow template (premature abstraction while still learning what each channel's job actually
needs). Building out one channel at a time - get it working and trusted before starting the next -
was direflail's own explicit call, given how much a single tool (Snap/LXD) ate today.

**Build order: apt first** (already exists, lowest risk - just wraps existing
`dpkg-buildpackage`/`pytest` in CI), **then Snap and Flatpak** (both need a real, non-throwaway
manifest built from scratch - order between these two left to whoever picks up the implementation
plan, since neither has a clearly stronger claim to go first).

**Per channel, two separate jobs, not one:**

- **`build`**: package + test + lint (`pytest` + `dpkg-buildpackage` + `lintian` for apt;
  `canonical/action-build` for Snap; `flatpak/flatpak-github-actions` for Flatpak). Uploads the
  built artifact.
- **`verify`**: depends on `build`'s artifact. Installs it, confirms the binary launches without
  crashing (cheap - a few lines, not worth deferring), then runs the headless-Shell extension-load
  check below.

Split deliberately, not merged into one job: `build` is the well-understood, load-bearing signal
("did I break the package") and should stay stable; `verify`'s headless-Shell check is newer and
less proven (one still-unexplained quirk from today's own spike - see "Known open items" below) -
keeping it separate means iterating on `verify` later carries zero risk to `build`'s own
reliability, and a `verify` failure with `build` green is immediately, visibly a different class of
problem than a `build` failure.

**The `verify` job's headless-Shell recipe** (proven live, not theoretical - this is the exact
recipe that worked on a real `ubuntu-24.04` GitHub-hosted runner):

```bash
sudo apt-get install -y gnome-shell dbus-x11
mkdir -p ~/.local/share/gnome-shell/extensions/orcshot-tray@orcshot.org
cp <bundled extension.js/metadata.json> ~/.local/share/gnome-shell/extensions/orcshot-tray@orcshot.org/

mkdir -p /run/user/$(id -u) && chmod 700 /run/user/$(id -u)
dbus-daemon --session --address=unix:path=/run/user/$(id -u)/bus --fork
export XDG_RUNTIME_DIR=/run/user/$(id -u)
export DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/$(id -u)/bus
gnome-shell --headless --virtual-monitor 1024x768 &
sleep 8   # let it fully initialize before touching it

gnome-extensions enable orcshot-tray@orcshot.org
# then confirm no JS errors/exceptions in the shell's own log
```

## Known open items, carried forward honestly rather than papered over

- **`gnome-extensions list`/`info` returned exit 2 immediately after a successful `enable`** in
  today's real GitHub Actions run, while `enable` itself succeeded cleanly (exit 0) and the
  extension's own log line fired with no errors. Not yet root-caused - likely a timing/sync quirk
  specific to those two subcommands, not evidence the core mechanism is broken, but worth
  understanding properly during real implementation rather than just working around it blindly.
- **Snap's `personal-files` review timeline is a real, external dependency** for ever *publishing*
  a real Snap (not for the build/verify CI this spec covers, which builds and installs locally via
  `--dangerous`, no store review needed for that). Real observed turnaround was ~2 days for a first
  response in the cited example, but that thread also shows real back-and-forth/pushback -
  budget for iteration, not a single fire-and-forget request.
- **Order between Snap and Flatpak's own implementation** is left open (see "Build order" above).

## Extensibility - what "flexible enough for Fedora later" actually means here

Nothing in this design assumes exactly three channels. The per-channel-workflow-file structure
means adding a `fedora.yml` later (`build` + `verify` jobs, an RPM spec file, whatever build action
turns out to be the current, real one for RPM packaging at that time) is additive - it touches
nothing this spec builds now. The new "detect channel, copy extension files if sandboxed" module
is already written generically enough (channel detection returns one of a small set of known
values, not hardcoded to exactly two) that adding a Fedora-specific sandboxing model (if it turns
out to even need one - plain RPM installs are unsandboxed, closer to `.deb` than to Flatpak/Snap)
is a small, additive change, not a rewrite.
