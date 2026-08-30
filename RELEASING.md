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

  `noble` (not `unstable`) - this targets the PPA build in step 6 below. `unstable` is a
  Debian-native distribution name; Launchpad rejects an upload whose changelog distribution isn't
  one of the PPA's own supported Ubuntu series, so an `unstable` upload just fails outright.

  (`date -R` prints the date in the right format.)

## 2. Full test suite

```bash
.venv/bin/pytest tests/ -q
```

Must be fully green before building - the package build itself re-runs the whole suite for real via
`dh_auto_test`/pybuild (see step 4), so a failure here just means finding out later instead of now.

This step, step 4 (`dpkg-buildpackage`), and step 5 (`lintian`) now also run automatically on every
push and PR via `.github/workflows/apt.yml` - running them by hand here is still the fastest local
feedback loop, not a redundant step; see step 9 below for confirming CI's own view before release.

## 3. Security check

Surfaced as a real gap during the 0.1.1 release (direflail, 2026-08-23): the release went to the
PPA without ever running a security scan, and `requirements.txt` (kept for SCA scanning, see its own
header comment) turned out to still be accurate but had never actually been checked against the dev
venv. This step exists so that stops being ad-hoc.

**One-time setup**, once per machine - Semgrep's CLI needs its own login, separate from the Aikido
MCP session:

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

`semgrep ci` covers both SAST and Supply Chain (dependency/lockfile) findings in one run, uploaded to
the Semgrep dashboard - Aikido's own local scan (`aikido_full_scan`, run on the changed files) covers
SAST and secrets, but its Supply Chain/SCA feed is a paid-tier-only feature this project doesn't have
(confirmed live, 2026-08-23: `aikido_issues_list` returns "only available for paying customers"), so
Semgrep is what actually covers dependency vulnerabilities here, not belt-and-suspenders duplication
of Aikido. The `diff` regenerates `requirements.txt` (see its own header) if it's gone stale - empty
output means it's still accurate.

Any new high/critical finding from either tool gets flagged and understood before continuing, the
same standard step 5's `lintian` warnings already get - not silently waved through, but not
necessarily a blocker either (a finding can be a confirmed false positive, same as `update_check.py`'s
own dynamic-`urllib` finding turned out to be: `_RELEASES_LATEST_URL` is a hardcoded module-level
constant, never influenced by user or network input).

## 4. Build the `.deb`

```bash
dpkg-buildpackage -us -uc -b
```

Produces `../orcshot_X.Y.Z-1_all.deb` (and a `.buildinfo`/`.changes` alongside it). Runs the full
test suite again as part of the build - a real build failure here (not just a test failure) means
something's wrong with `debian/control`'s dependency list or `pyproject.toml` itself, not the code.

## 5. Lint it

```bash
lintian ../orcshot_X.Y.Z-1_all.deb
```

Zero errors expected. A few harmless warnings are already documented in REQUIREMENTS.md's own
Packaging section (e.g. the icon-size mismatch) - anything new should be understood, not just
dismissed.

## 6. Upload to the PPA (task #102)

`ppa:artificialorctelligence/orcshot` on Launchpad. PPAs build from a *source* upload, not the
binary `.deb` from step 4 - Launchpad's own build farm compiles/assembles the package itself.

```bash
dpkg-buildpackage -us -uc -S -sa
debsign ../orcshot_X.Y.Z-1_source.changes
dput ppa:artificialorctelligence/orcshot ../orcshot_X.Y.Z-1_source.changes
```

`-sa` forces the (native-format) source tarball to be included even on a non-first upload to this
version - without it `dpkg-genchanges` may assume Launchpad already has it and omit it, which fails
validation. `debsign` prompts for your GPG key (the one registered to the Launchpad account) to sign
the `.changes` file - Launchpad rejects unsigned or unrecognized-key uploads.

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
build-dependencies (confirmed against Launchpad's own packaging docs) - once the `noble` (24.04)
build succeeds, use the PPA's own "Copy packages" page (Launchpad web UI) to copy that same binary
to `resolute` (26.04) rather than uploading source a second time. Check build status/logs at
`https://launchpad.net/~artificialorctelligence/+archive/ubuntu/orcshot/+packages`.

## 7. Install-test on every target

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

## 8. Commit, tag, push

```bash
git add pyproject.toml debian/changelog
git commit -m "Release vX.Y.Z"
git tag -a vX.Y.Z -m "vX.Y.Z"
git push origin main
git push origin vX.Y.Z
```

## 9. Confirm CI is green on the just-pushed commit

Step 8 just pushed the release commit to `main`, which triggers `.github/workflows/apt.yml` for
real (build, install-and-launch, and the headless-Shell tray check) - confirm it actually passed
before publishing anything downstream:

```bash
gh run list --workflow=apt.yml --limit 1
```

Expected: `completed` / `success` for that commit. If it's still running, wait for it; if it
failed, stop here and fix forward before step 10 - don't publish a release CI itself flagged as
broken.

## 10. Publish the GitHub Release

Create a release for the `vX.Y.Z` tag (web UI or `gh release create vX.Y.Z`) and attach the built
`.deb` as a release asset. This is the step task #103 actually depends on - `releases/latest` only
returns something once a real, non-draft, non-prerelease release exists.

## 11. Sanity-check the update checker

Once published, confirm task #103 actually sees it: Help > Check for Updates... on a build one
version behind should report the new release; on the just-built version itself, "up to date."

For `0.2.0`: covered incidentally rather than via a dedicated re-test - the 24.04 VM was still on
the prior release (about a week old) going into step 7's install-test, and installing `0.2.0-1`
over it is the same real "one version behind" transition this step asks for. Accepted as
sufficient (direflail, 2026-08-27) rather than reinstalling an old build just to click the menu
item separately.
