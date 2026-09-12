# Cutting an Orcshot release

A checklist for going from "code on `main`" to a tagged, installable, discoverable release.
Written because task #103 (Check for Updates) polls GitHub's `releases/latest` API — until a real
release exists there, that feature has nothing to find, and `pyproject.toml`'s version has been
sitting at `0.1.0` since the very first commit.

## 1. Pick a version

Decide the new version number (semver: `MAJOR.MINOR.PATCH`). Update it in two places - they must
match, or the built `.deb`'s own version won't line up with the source tree that produced it:

- `pyproject.toml` → `version = "X.Y.Z"`
- `debian/changelog` → add a **new** top entry (newest first, standard Debian changelog format):

  ```
  orcshot (X.Y.Z-1) noble; urgency=medium

    * <one-line summary of what's new since the last release>

   -- Orcshot <314918217+artificialorctelligence@users.noreply.github.com>  <RFC 2822 date>
  ```

  `noble` (not `unstable`) - this targets the PPA build in step 7 below. `unstable` is a
  Debian-native distribution name; Launchpad rejects an upload whose changelog distribution isn't
  one of the PPA's own supported Ubuntu series, so an `unstable` upload just fails outright.

  (`date -R` prints the date in the right format.)

## 2. Full test suite

```bash
.venv/bin/pytest tests/ -q
```

Must be fully green before building - the package build itself re-runs the whole suite for real via
`dh_auto_test`/pybuild (see step 5), so a failure here just means finding out later instead of now.

This step, step 5 (`dpkg-buildpackage`), and step 6 (`lintian`) now also run automatically on every
push and PR via `.github/workflows/apt.yml` - running them by hand here is still the fastest local
feedback loop, not a redundant step; see step 11 below for confirming CI's own view before release.

## 3. Upload the GNOME Shell extension to extensions.gnome.org (only if it changed)

The extension (`orcshot@orcshot.org`) is a second artifact with its own store. Flatpak installs it
from there, Snap sends users there, and GNOME keeps every per-user copy on EGO's version - EGO
owns the version once published (spec 2026-09-11 §5). This step is **not a gate**: EGO review is
human, unbounded, and prioritises small diffs; the app tolerates one release of extension skew via
the capability handshake. Skip it entirely when
`git diff $(git describe --tags --abbrev=0) -- src/orcshot/resources/gnome-shell-extensions` is empty.

**One-time setup:** an extensions.gnome.org account for `artificialorctelligence`, its password in
`~/.config/orcshot/ego-password` (chmod 0600, never printed, never committed), and the first
submission accepted by EGO's reviewers. Check:
`curl -sf 'https://extensions.gnome.org/extension-query/?search=orcshot' | grep -q orcshot@orcshot.org`

**Preconditions:** `metadata.json`'s `version-name` was bumped in the commit that changed the
extension. This runs on a machine with GNOME Shell ≥ 50 (the 26.04 VM over SSH), not the Mint host.

**Run:** /orc-publish gnome-shell-extension.js.linux.ego

## 4. Security check

Surfaced as a real gap during the 0.1.1 release (direflail, 2026-08-23): the release went to the
PPA without ever running a security scan, and `requirements.txt` (kept for SCA scanning, see its own
header comment) turned out to still be accurate but had never actually been checked against the dev
venv. This step exists so that stops being ad-hoc.

**One-time setup**, once per machine - Semgrep's CLI needs its own login:

```bash
python3 -m venv ~/.venvs/semgrep && ~/.venvs/semgrep/bin/pip install semgrep
~/.venvs/semgrep/bin/semgrep login   # interactive - opens a browser to authorize
```

Not tracked in this repo or `pyproject.toml` - release tooling, not an app dependency, same as
`dpkg-buildpackage`/`gpg`/`dput` below being assumed-present rather than project state.

**Every release:**

```bash
~/.venvs/semgrep/bin/semgrep ci
diff <(.venv/bin/pip freeze | grep -iE "^(hypothesis|iniconfig|numpy|packaging|pluggy|pycairo|Pygments|PyGObject|pytest|python-xlib|scipy|shapely|six|sortedcontainers)==" | sort) <(grep -v '^#' requirements.txt | grep -v '^$' | sort)
```

`semgrep ci` is the whole of this step's tooling, deliberately. It covers both SAST and Supply
Chain (dependency/lockfile) findings across the entire tree in one run, uploaded to the Semgrep
dashboard, and it is free.

**Aikido used to be named here and no longer is** (BACKLOG `#200`, decided 2026-09-07). Its prose
claimed `aikido_full_scan` covered SAST and secrets, but nothing ever invoked it - whether a release
got an Aikido scan depended entirely on whether whoever ran the release happened to run one by hand.
Making it a real requirement turned out to cost real money: Aikido's free tier does scan a connected
repo server-side every 3 days, but its **Public REST API - which the MCP tools go through - starts at
the Basic tier, $300/month** (confirmed live on aikido.dev/pricing, 2026-09-07; `aikido_issues_list`
returns "This action is only available for paying customers" on this account). Automating it was
therefore not available, and hand-feeding it does not scale: the MCP tool takes file *contents*
inline, capped at 50 files, so scanning this project's 82 shipped `.py` files (1,052,354 bytes) means
about nine batched calls per release. A step that expensive gets skipped, which is the exact problem
this step was written to end.

**What that leaves uncovered, stated plainly rather than quietly dropped**: secrets detection. Semgrep
covers SAST and dependencies; nothing here scans for committed credentials. That is a real gap, not a
solved problem - see `#200` for the free options considered (a `gitleaks`/`trufflehog` CI step being
the obvious one) and why none was adopted at the time.

The `diff` regenerates `requirements.txt` (see its own header) if it's gone stale - empty output means
it's still accurate.

Any new high/critical finding gets flagged and understood before continuing, the
same standard step 6's `lintian` warnings already get - not silently waved through, but not
necessarily a blocker either (a finding can be a confirmed false positive, same as `update_check.py`'s
own dynamic-`urllib` finding turned out to be: `_RELEASES_LATEST_URL` is a hardcoded module-level
constant, never influenced by user or network input).

## 5. Build the `.deb`

```bash
dpkg-buildpackage -us -uc -b
```

Produces `../orcshot_X.Y.Z-1_all.deb` (and a `.buildinfo`/`.changes` alongside it). Runs the full
test suite again as part of the build - a real build failure here (not just a test failure) means
something's wrong with `debian/control`'s dependency list or `pyproject.toml` itself, not the code.

## 6. Lint it

```bash
lintian ../orcshot_X.Y.Z-1_all.deb
```

Zero errors expected. A few harmless warnings are already documented in REQUIREMENTS.md's own
Packaging section (e.g. the icon-size mismatch) - anything new should be understood, not just
dismissed.

## 7. Upload to the PPA (task #102)

`ppa:artificialorctelligence/orcshot` on Launchpad. PPAs build from a *source* upload, not the
binary `.deb` from step 5 - Launchpad's own build farm compiles/assembles the package itself.

**One-time setup:** the signing key must exist in this machine's keyring. It cannot be derived
from the package - see below.

Check whether it is already there: `gpg --list-secret-keys FAF777B27363A1BBB445E2F2596233AC9F58280A`

If it is not, import or generate the key registered to the Launchpad account before going further.
Discovering this at `debsign` time leaves a built, unsigned package and a half-done step.

```bash
dpkg-buildpackage -us -uc -S -sa
debsign -kFAF777B27363A1BBB445E2F2596233AC9F58280A ../orcshot_X.Y.Z-1_source.changes
dput ppa:artificialorctelligence/orcshot ../orcshot_X.Y.Z-1_source.changes
```

`-sa` forces the (native-format) source tarball to be included even on a non-first upload to this
version - without it `dpkg-genchanges` may assume Launchpad already has it and omit it, which fails
validation.

**`-k` is required, and its absence is not a warning.** Found live during the 0.3.0 release: with
no `-k`, `debsign` derives the signing identity from `debian/changelog`'s maintainer field. That
field is a GitHub `noreply` address which no key exists for, so it fails outright -
`gpg: skipped "...": No secret key` / `debsign: gpg error occurred!  Aborting`. The real signing
identity is a different one, and both previously accepted uploads were verified as signed by this
same key (`gpg --verify` on the `0.1.1-3` and `0.2.0-1` `.changes` files). Launchpad rejects
unsigned or unrecognized-key uploads, so this is what stands between a build and a publish.

Requires a one-time local `~/.dput.cf` entry (not part of this repo - it's a per-machine config, not
project state):

```ini
[orcshot-ppa]
fqdn = ppa.launchpad.net
method = ftp
incoming = ~artificialorctelligence/orcshot/ubuntu/
login = anonymous
allow_unsigned_uploads = 0
```

Then `dput orcshot-ppa ../orcshot_X.Y.Z-1_source.changes` (or just `dput ppa:artificialorctelligence/orcshot ...`
as above - `dput` understands the `ppa:` shorthand directly without needing the `[orcshot-ppa]` section
at all; the section above is only needed if that shorthand ever stops resolving correctly).

**Only one series needs a real upload.** Orcshot is `Architecture: all` with no series-specific
build-dependencies (confirmed against Launchpad's own packaging docs), so the binary built for
`noble` (24.04) is copied to `resolute` (26.04) rather than built from a second source upload.
That copy is **step 8**, and it must not run until this step's build has actually succeeded.
Check build status/logs at
`https://launchpad.net/~artificialorctelligence/+archive/ubuntu/orcshot/+packages`.

## 8. Copy the built package to 26.04

**Preconditions:** the `noble` build has **succeeded** on Launchpad — not merely been accepted.
Check the PPA's package page before running this; the script also refuses if it hasn't.

**One-time setup:** authorizing this machine against Launchpad's API, once per machine.

Check whether it is already done: `python3 scripts/ppa-copy-series.py --check`

If it is not, run `python3 scripts/ppa-copy-series.py --version <X.Y.Z-1>` once and complete the
browser authorization it opens.

**Run:** /orc-publish desktop.python.linux.ppa.resolute

## 9. Install-test on every target

This is the actual point of tasks #37/#38/#50 - the `.deb` itself never changes per target
(`Architecture: all`, no compiled code), but whether each target's own repos carry every declared
dependency **by that exact name** does vary (the `gir1.2-ayatanaappindicator3-0.1` vs. the older
`gir1.2-appindicator3-0.1` naming split is the concrete example already baked into `debian/control`).
For each target below: copy the `.deb` over, install it fresh, and confirm apt dependency resolution
succeeds *and* the installed binary (`/usr/bin/orcshot`, not a dev venv) actually launches.

- [x] **Mint/Cinnamon** (this host) - `sudo apt install ./orcshot_X.Y.Z-1_all.deb`
- [x] **Ubuntu 26.04 LTS** (task #50, verified) - re-check on each new version regardless
- [x] **Ubuntu 24.04 LTS / GNOME** (task #38, verified) - re-check on each new version regardless;
      confirm the actual login session is Wayland before trusting the result (see
      REQUIREMENTS.md's task #38 section for why this isn't a safe assumption)
- [ ] *(later, task #37)* other Debian-family targets - pure Debian, Pop!_OS, etc.

`VBoxManage guestcontrol <vm> copyto` + `run` is the established pattern for the VMs (see the
project's own VM-testing notes) - copy the built `.deb` in, install, launch, confirm the tray icon
appears and a capture round-trips.

RPM-based distros (Fedora/openSUSE) and Arch/AUR are a separate, later effort (task #132) - a
different package format entirely, not another entry on this list.

## 10. Commit, tag, push

```bash
git add pyproject.toml debian/changelog
git commit -m "Release vX.Y.Z"
git tag -a vX.Y.Z -m "vX.Y.Z"
git push origin main
git push origin vX.Y.Z
```

## 11. Confirm CI is green on the just-pushed commit

Step 10 just pushed the release commit to `main`, which triggers `.github/workflows/apt.yml` (build,
install-and-launch, the headless-Shell tray check), `.github/workflows/snap.yml` (the same, for the
Snap channel), and `.github/workflows/flatpak.yml` (the same, for the Flatpak channel) for real -
confirm all three actually passed before publishing anything downstream. See `CI.md` for what this
actually looks like (the GitHub Actions web page, no terminal required) if you'd rather click through
it than run a command:

```bash
gh run list --workflow=apt.yml --limit 1
gh run list --workflow=snap.yml --limit 1
gh run list --workflow=flatpak.yml --limit 1
```

Expected: `completed` / `success` for that commit, on all three. If any is still running, wait for
it; if any failed, stop here and fix forward before step 12 - don't publish a release CI itself
flagged as broken.

## 12. Publish the GitHub Release

Create a release for the `vX.Y.Z` tag (web UI or `gh release create vX.Y.Z`) and attach the built
`.deb` as a release asset. This is the step task #103 actually depends on - `releases/latest` only
returns something once a real, non-draft, non-prerelease release exists.

## 13. Sanity-check the update checker

Once published, confirm task #103 actually sees it: Help > Check for Updates... on a build one
version behind should report the new release; on the just-built version itself, "up to date."

For `0.2.0`: covered incidentally rather than via a dedicated re-test - the 24.04 VM was still on
the prior release (about a week old) going into step 9's install-test, and installing `0.2.0-1`
over it is the same real "one version behind" transition this step asks for. Accepted as
sufficient (direflail, 2026-08-27) rather than reinstalling an old build just to click the menu
item separately.
