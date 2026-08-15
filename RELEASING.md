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
  orcshot (X.Y.Z-1) unstable; urgency=medium

    * <one-line summary of what's new since the last release>

   -- Orcshot <314918217+greenshotlinux@users.noreply.github.com>  <RFC 2822 date>
  ```

  (`date -R` prints the date in the right format.)

## 2. Full test suite

```bash
.venv/bin/pytest tests/ -q
```

Must be fully green before building - the package build itself re-runs the whole suite for real via
`dh_auto_test`/pybuild (see step 3), so a failure here just means finding out later instead of now.

## 3. Build the `.deb`

```bash
dpkg-buildpackage -us -uc -b
```

Produces `../orcshot_X.Y.Z-1_all.deb` (and a `.buildinfo`/`.changes` alongside it). Runs the full
test suite again as part of the build - a real build failure here (not just a test failure) means
something's wrong with `debian/control`'s dependency list or `pyproject.toml` itself, not the code.

## 4. Lint it

```bash
lintian ../orcshot_X.Y.Z-1_all.deb
```

Zero errors expected. A few harmless warnings are already documented in REQUIREMENTS.md's own
Packaging section (e.g. the icon-size mismatch) - anything new should be understood, not just
dismissed.

## 5. Install-test on every target

This is the actual point of tasks #37/#38/#50 - the `.deb` itself never changes per target
(`Architecture: all`, no compiled code), but whether each target's own repos carry every declared
dependency **by that exact name** does vary (the `gir1.2-ayatanaappindicator3-0.1` vs. the older
`gir1.2-appindicator3-0.1` naming split is the concrete example already baked into `debian/control`).
For each target below: copy the `.deb` over, install it fresh, and confirm apt dependency resolution
succeeds *and* the installed binary (`/usr/bin/orcshot`, not a dev venv) actually launches.

- [ ] **Mint/Cinnamon** (this host) - `sudo apt install ./orcshot_X.Y.Z-1_all.deb`
- [ ] **Ubuntu 26.04 LTS** (task #50 - existing VM, already used for Wayland work, but never yet
      install-tested via the real `.deb` - everything there so far ran from source via `PYTHONPATH`)
- [ ] **Ubuntu 24.04 LTS / GNOME** (task #38 - VM in progress)
- [ ] *(later, task #37)* other Debian-family targets - pure Debian, Pop!_OS, etc.

`VBoxManage guestcontrol <vm> copyto` + `run` is the established pattern for the VMs (see the
project's own VM-testing notes) - copy the built `.deb` in, install, launch, confirm the tray icon
appears and a capture round-trips.

RPM-based distros (Fedora/openSUSE) and Arch/AUR are a separate, later effort (task #132) - a
different package format entirely, not another entry on this list.

## 6. Commit, tag, push

```bash
git add pyproject.toml debian/changelog
git commit -m "Release vX.Y.Z"
git tag -a vX.Y.Z -m "vX.Y.Z"
git push origin main
git push origin vX.Y.Z
```

## 7. Publish the GitHub Release

Create a release for the `vX.Y.Z` tag (web UI or `gh release create vX.Y.Z`) and attach the built
`.deb` as a release asset. This is the step task #103 actually depends on - `releases/latest` only
returns something once a real, non-draft, non-prerelease release exists.

## 8. Sanity-check the update checker

Once published, confirm task #103 actually sees it: Help > Check for Updates... on a build one
version behind should report the new release; on the just-built version itself, "up to date."
