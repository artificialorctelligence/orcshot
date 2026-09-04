# Backlog

Open items not yet scheduled into a task. Each entry keeps the context that
led to it - not just "what," but "why this matters" - so picking it up later
doesn't require re-deriving the reasoning from scratch.

## #195: Flatpak channel ships with no capture-complete sound at all - GSound gap was never actually tracked (RESOLVED 2026-09-01)

Found during the flatpak-channel final review's fix round (2026-08-31): `org.orcshot.Orcshot.yaml`'s
`gnome-shell-schema` module comment (added fix round 1) claims the GSound deferral is "deferred,
tracked as a real gap, not silently dropped" - but nowhere in this file ever mentioned GSound before
this entry. The only record anywhere was that one YAML comment.

**Real, permanent user-visible consequence, not cosmetic:** `gir1.2-gsound-1.0`'s `GSound-1.0.typelib`
has no equivalent in `org.gnome.Platform//50` or `org.gnome.Sdk//50` (confirmed live, fix round 1).
`capture/capture_feedback.py` guards the import (`except ValueError`) so this degrades gracefully -
`play_capture_sound()` becomes a silent no-op instead of crashing every launch. (Correcting this
entry's own earlier claim here: `settings.get_play_capture_sound()` defaults to `False`, not on -
direflail's own explicit call, made for an unrelated timing reason, documented in that function's own
docstring - so this gap only ever bit someone who specifically opted in, on this one channel.)

**Resolved for real, not just tracked**: `capture/capture_feedback.py` no longer uses GSound at all -
rewritten to play a bundled sound file (`resources/camera-shutter.oga`, the real freedesktop theme
file GSound's own `"camera-shutter"` event ID already resolved to on a standard install - see
THIRD_PARTY_NOTICES.md for the licensing) via GStreamer instead. GStreamer's Python bindings and the
`playbin`/`vorbisdec` elements this needs are already part of `org.gnome.Platform//50`'s own base
runtime (confirmed live via `gst-inspect-1.0` - no new Flatpak module needed), and real Ubuntu packages
for apt/Snap (`gir1.2-gstreamer-1.0` + `gstreamer1.0-plugins-base`). One channel-specific manifest
change was needed on top: Flatpak's `--socket=pulseaudio` (added to `org.orcshot.Orcshot.yaml`) and
Snap's `audio-playback` plug (added to `snapcraft.yaml`) - neither channel had real audio-sink access
granted before this, a gap that only surfaced because this fix added a genuine live playback
verification pass, not just a decode/crash check.

Verified live, not assumed: real audible playback confirmed on three separate real machines (this
project's own Mint dev host, a real Ubuntu 24.04.4 LTS VM, a real Ubuntu 26.04/GNOME 50 VM), and
inside a real confined Flatpak build specifically (`GstPulseSinkClock` connecting, a real `EOS`
reached, and - the strongest signal - direflail directly heard the sound play from the sandboxed app).
`capture_feedback.py`'s own module docstring has the full story.

## #194: The Flatpak manifest isn't Flathub-submission-ready as-is

Found during the flatpak-channel final review's fix round (2026-08-31), while pinning the manifest's
previously-unpinned pip dependencies. Three real gaps, none blocking for a direct-download/GitHub-
Release-asset distribution (this channel's actual current scope), all worth knowing about before any
future "submit to Flathub" effort:

- **`build-options: build-args: [--share=network]`** - network access during the build sandbox (used
  to `pip3 install` `numpy`/`shapely`/`python-xlib`, none of which have a runtime-provided equivalent -
  see the manifest's own comment) is disallowed by Flathub's build policy outright. A real submission
  would need to either vendor these as pre-built wheels/sdists via `sources:` entries (flatpak-builder
  supports this, no network needed at build time) or find them already staged in a shared BaseApp/
  extension.
  **Fixed, merged to `main` (#16, #17):** `--share=network` is gone, and `numpy`/`shapely`/`python-xlib`
  are now vendored as pinned, pre-built wheels via `sources:` entries (`python3-numpy`/`python3-shapely`/
  `python3-python-xlib` modules), generated with the official `flatpak-pip-generator` tool against
  `org.gnome.Sdk//50` - exactly the fix this bullet describes. A fourth module, `python3-hatchling`, was
  needed too: removing `--share=network` exposed a second, previously-hidden network dependency
  (`orcshot`'s own `pyproject.toml` declares `build-backend = "hatchling.build"`, and pip's build
  isolation tries to fetch that backend from PyPI for every `pip3 install .` of a local source dir) -
  vendored the same way, with `cleanup: ['*']` so hatchling/pathspec/pluggy/tomlkit/trove_classifiers
  (build-only, no runtime purpose) don't ship inside the final app.
- **`--talk-name=org.gnome.Shell`** - a real session-bus grant a Flathub reviewer would ask about.
  Narrowing it to `org.gnome.Shell.Extensions` (`com.mattjakeman.ExtensionManager`'s own precedent on
  Flathub) was tried and reverted in this same fix round after live-verifying it does not work on a
  real GNOME Shell (46.2) - that name isn't an owned/activatable bus name there, so dialing it fails
  outright rather than reaching the running Shell (see `gnome_extension_setup.py`'s own comment for
  the full live-tested story). Worth re-testing against a newer GNOME Shell version someday, but not
  assumed to work without doing so again for real. Still open - unrelated to the `flathub-readiness`
  branch's work.
- **No AppStream metadata at all** (`org.orcshot.Orcshot.appdata.xml` / `org.orcshot.Orcshot.metainfo.xml`)
  - Flathub requires this for the store listing (screenshots, description, release notes); nothing in
  this manifest or repo produces one yet.
  **Fixed, merged to `main` (#16, #17):** `org.orcshot.Orcshot.metainfo.xml` now exists (screenshots,
  description, release notes) and validates against `flatpak-builder-lint`'s `appstream` check with
  genuinely **0 errors and 0 warnings**, confirmed live in real CI against the real, pushed screenshot
  commit (`docs.flathub.org`'s own linter, `org.flatpak.Builder`).

Two of the three gaps are now fixed and merged (2026-09-03/04). The `--talk-name` narrowing above is
still genuinely open. Not tracked as fully resolved for that reason - the actual Flathub submission
itself (the PR against `flathub/flathub`, their human review) also remains a separate, later action not
attempted here.

## #193: GitHub Actions `ubuntu-24.04` runners hit `dconf-CRITICAL: Permission denied` on a real, unconfined `gnome-shell` too (RESOLVED 2026-09-04)

Found as a side effect of BACKLOG #185's Flatpak CI hard tier (task #4's own real live testing,
2026-08-31). The runner's `dconf-CRITICAL **: unable to create file '/run/user/<uid>/dconf/user':
Permission denied` warning, first seen from inside a Flatpak-confined process, turned out to also hit
the real, completely unconfined `gnome-shell --headless` process itself on this exact runner image -
confirmed by pulling the actual job log and finding the identical error at that process's own startup,
not just the Flatpak-confined one. Originally recorded as *not* affecting anything this project
tested, since `enable_extension_live()`'s direct D-Bus activation bypasses `dconf` entirely.

**That turned out to be wrong** (PR #18, 2026-09-04): `flatpak.yml`'s own final persistence check
(`gsettings get org.gnome.shell enabled-extensions`, reading the real host dconf directly) failed
with this exact warning on a PR that touched nothing but `BACKLOG.md` - then passed clean on an
immediate re-run of the identical code, confirming the warning's real-world effect is genuinely
intermittent, not the harmless no-op it was first assumed to be.

**Real root cause**: `systemctl start user@<uid>.service` (this job's own way of getting a user D-Bus
session bus without a real login) brings up the session bus but, unlike a real login opened via
`pam_systemd`, does not create `/run/user/<uid>/dconf/` - `dconf-service` creates that subdirectory
itself, lazily, on first use, and loses that race against this exact runner's timing often enough to
matter. `snap.yml`'s own equivalent persistence check never showed this flakiness not because it
solved the race, but because it reads back through the same confined settings backend it wrote
through instead of host dconf directly - never actually exposed to it.

**Fix, confirmed live**: `flatpak.yml` now creates `/run/user/<uid>/dconf/` explicitly, right after
the session bus appears and before anything tries to write through it - removes the race instead of
hoping to win it. Confirmed with three separate, consecutive `flatpak / verify` re-runs on the same
PR (#19), all green - deliberately more than the single green run that got this issue
mischaracterized as harmless in the first place.

## #192: Snap channel - gnome_shell_present() crash, and whether the tray extension actually works under strict confinement (RESOLVED 2026-08-30)

Started as a real crash risk (`Gio.SettingsSchemaSource.get_default()` returning `None` under strict
confinement, causing an unhandled `AttributeError` in `gnome_shell_present()`), confirmed live via a
diagnostic CI probe on PR #9. Two separable questions followed: (1) the crash fix itself, and (2) the
larger question direflail explicitly asked to be tackled next - does the Wayland tray extension
actually *function* under Snap at all, not just fail gracefully. Both are now resolved, PR #10, each
finding confirmed live in real CI, not guessed:

1. **The crash**: fixed - `gnome_shell_present()` now treats `get_default()` returning `None` as
   "schema not found" (`False`), same as apt/.deb's own already-correct behavior.
2. **The schema itself was genuinely unresolvable under confinement**, not just returning `False` on
   a real check: `gnome-shell-common`'s schema wasn't staged in `snapcraft.yaml` at all, and even once
   staged, Snapcraft's staging never runs the `.deb`'s own postinst/dpkg-trigger machinery, so the raw
   XML never got compiled into `gschemas.compiled` - fixed with an explicit `glib-compile-schemas`
   step (same class of gap as this file's existing BLAS/LAPACK workaround).
3. **Even correctly staged and compiled, nothing made it discoverable at runtime**: this snap uses no
   desktop-integration extension (`extensions: [gnome]` was deliberately set aside in Task 3 for a
   minimal manual-plugs approach), so nothing sets `XDG_DATA_DIRS`/`GSETTINGS_SCHEMA_DIR` the way a
   `desktop-launch` wrapper would - fixed by setting `GSETTINGS_SCHEMA_DIR` explicitly, same pattern
   already used for `PYTHONPATH`/`GI_TYPELIB_PATH`.
4. **The confined write itself (`enable_extension()`) silently fell back to GLib's keyfile backend**
   and failed outright, because the dconf GSettingsBackend GIO module (`dconf-gsettings-backend`'s
   `libdconfsettings.so`) was never staged either - fixed by staging it and adding `GIO_EXTRA_MODULES`.
5. **CI itself broke `snap run` entirely** once a session D-Bus bus existed
   (`... is not a snap cgroup for tag snap.orcshot.orcshot`) - a documented, `core24`-specific snapd
   bug (https://bugs.launchpad.net/snapd/+bug/2075560): a bare `dbus-daemon --session` has no real
   `systemd --user` behind it, and `snap run` needs `org.freedesktop.systemd1.Manager` on that bus to
   create its own confinement scope. Fixed by starting the real `systemd --user` instance instead.
6. **The deeper functional question**: `gnome_extension_setup.enable_extension_live()` (the direct
   `org.gnome.Shell.Extensions.EnableExtension` D-Bus call that normally makes the extension activate
   *this session*, not just on next login) is confirmed AppArmor-blocked under Snap's strict
   confinement (`AccessDenied`, live-tested) - no interface this snap plugs grants that call, and none
   safely could. **This turned out not to matter**: live-tested against the real, representative
   scenario (GNOME Shell already running, matching how the first-run dialog is actually ever used),
   the already-running Shell picks up `enable_extension()`'s persisted gsettings write on its own,
   with no live D-Bus call at all - confirmed via the same headless-Shell-load check the apt channel's
   own CI already relies on. `extensions: [gnome]` was not needed after all.

**Net result**: the Wayland tray extension genuinely functions under the Snap channel end-to-end -
schema resolves, the real production write persists, GNOME Shell loads it. All of this is now a
permanent, non-throwaway part of `.github/workflows/snap.yml`'s verify job, exercising Orcshot's own
real production code (`enable_extension`, `install_bundled_extension_if_needed`) through actual strict
confinement, not a stand-in.

## #191: Snap channel - deferred findings from the final review (RESOLVED 2026-08-30)

Final whole-branch review of `docs/superpowers/plans/2026-08-30-snap-channel.md` (2026-08-30, PR #9)
flagged several real, non-blocking findings. All fixed:

- **`version: git` resolved to `0+git.<sha>` in CI.** Replaced with `adopt-info: orcshot` +
  `craftctl set version=...` reading `pyproject.toml` directly - one source of truth, mirrors how
  `debian/changelog` already drives the apt channel's version, no dependency on the checkout's tag
  history. Verified locally: packs as `orcshot_0.2.0_amd64.snap`, matching `pyproject.toml` exactly.
- **Bundled extensions could never be upgraded once installed under Snap.**
  `install_bundled_extension_if_needed` now compares `metadata.json`'s own `version` field and
  replaces `dest` when the bundled copy is genuinely newer (missing treated as `0`, so
  `orcshot-tray@orcshot.org`'s own historically-versionless metadata - now given `"version": 1` -
  becomes upgradeable too). Also copies to a temp sibling and swaps it in, so an interrupted copy
  never corrupts or half-writes an existing install. TDD, full test coverage, feeds the same design
  into the Flatpak channel's own future brainstorm.
- **`RELEASING.md`'s CI-check step only mentioned `apt.yml`.** Now checks both `apt.yml` and
  `snap.yml`, matching what a real release push actually triggers.
- **The `test_deb_channel_never_calls_install_bundled_extension` test was tautological** (asserted a
  monkeypatch's own return value back at itself). The snap-path gating logic is now extracted into
  `_install_bundled_extensions_for_snap()`, a real function tests can call directly - the deb-channel
  no-op, the snap-channel install-all-three, and the prompt-on-failure path are each now genuinely
  exercised.
- **The blunt global `os.path.exists` monkeypatch** in `test_channel_detect.py` is gone -
  `detect_channel()` now takes an injectable `path_exists` parameter, matching the `env` injection
  pattern it already used.
- **Neither `apt.yml` nor `snap.yml` declared a `permissions:` block** - see `#190`, fixed for both
  files together.

Left as genuinely non-actionable: the CI check script writing into the live GNOME Shell extensions
directory rather than a `.ci/` subdirectory - harmless residue on an ephemeral, destroyed-after-the-job
CI runner, not worth the complexity of a separate directory.

## #190: apt CI workflow hardening (RESOLVED 2026-08-30)

Final whole-branch review of `docs/superpowers/plans/2026-08-29-apt-ci-automation.md` (2026-08-29)
flagged several Minor, non-blocking hardening items. All fixed, applied to both `apt.yml` and
`snap.yml` together (the same gaps existed in both):

- **`permissions: contents: read`** added at the top level of both workflows - makes the
  already-default repo setting explicit at the file level, not dependent on a setting someone could
  change later.
- **`concurrency:` group + `cancel-in-progress: true`** added to both - repeated pushes to the same
  PR branch now cancel the superseded run instead of all running in parallel.
- **`timeout-minutes: 20`** added to every job in both workflows - bounds a hung step (e.g.
  `gnome-shell` never logging its startup line) instead of burning the default 6-hour job timeout.
- **A clarifying comment on what the headless-Shell check actually proves** - added to both
  `apt.yml` and `snap.yml`'s equivalent check: it proves the extension loads, initializes, and its
  D-Bus name-watcher wires up correctly; it does not exercise menu construction or rendering.

Reviewed and deliberately left as-is:
- **The test suite running twice in `build`** (explicit `pytest` step + `dpkg-buildpackage`'s own
  `override_dh_auto_test`) - catches a real, distinct signal (PyPI-resolved dev deps vs. the distro's
  `python3-pytest`), not pure waste.
- **Mixed merge styles in `main`'s history** - already settled in practice via this session's own
  squash-merge convention for the two most recent large PRs; no code change needed.

## #187: Prove (or disprove) whether `fallback-x11` gives real, unrestricted X11 capture under Flatpak (RESOLVED 2026-08-30)

**Proven true, for real, not just reasoned about.** A throwaway `flatpak-builder` spike (`org.freedesktop.Platform`/`Sdk` 24.08, `finish-args` declaring
*only* `--socket=wayland` and `--socket=fallback-x11` - no portal, no D-Bus, no filesystem access at
all, confirmed by reading the exported metadata directly) made a real X11 protocol call (raw
`python-xlib`, `root.get_image()` on this host's own Mint/Cinnamon X11 session - the identical
protocol-level operation `X11CaptureBackend` performs via GDK, just without pulling in the whole GTK3
stack for a spike) from inside the confined sandbox:

```
root window geometry: 4480x1440
captured 25804800 bytes
unique byte values in first 10000 bytes: 40
SPIKE RESULT: REAL CAPTURE - varied pixel data returned through fallback-x11
```

Real, varied screen pixel data, not a black/blocked response - `fallback-x11` genuinely grants
unrestricted native X11 capture on a pure-X11 session, exactly as the reasoning below predicted. The
exported metadata does list `sockets=x11;wayland;fallback-x11` together - this is `fallback-x11`'s own
correct, documented representation (a conditional x11 grant, active only when Wayland isn't the session
type), not a broader permission that crept in; the manifest itself only ever declared the two intended
sockets. Spike code discarded per its own classification - nothing kept, this entry is the record.

**What this means for #185**: its "Wayland-only, X11 users redirected elsewhere" framing is
unnecessarily narrow, confirmed now rather than assumed - a single Flatpak build can genuinely support
both X11 (via `fallback-x11`, full native `X11CaptureBackend`, no portal) and Wayland (via the portal
or `#184`'s now-proven extension-install path). Worth folding into `#185`'s own design pass before
building it, not treated as a separate follow-up.

**Follow-up raised directly by direflail after the above (2026-08-30): does the same reasoning hold for
Wayland's own portal-based capture path, and does `#184`'s Flatpak-filesystem-grant question (the
`channel_detect.py` extension-install mechanism) hold too? IN PROGRESS, not yet fully answered:**

1. **`--filesystem=~/.local/share/gnome-shell/extensions:create` - CONFIRMED WORKING.** Same throwaway-spike
   method as above (`org.gnome.Platform`/`Sdk` 49 this time). A confined process wrote and read back real
   content with no separate runtime "connect" step - simpler than Snap's `personal-files`, which needs
   `snap connect` after install. `channel_detect.install_bundled_extension_if_needed`'s own mechanism
   should transfer to Flatpak cleanly on this specific point.

2. **Portal `Screenshot` (`org.freedesktop.portal.Screenshot`) - genuinely inconclusive on this dev
   machine, root-caused rather than left as a guess.** First attempt (unconfined AND confined, on this
   machine's own Mint/Cinnamon desktop) failed with `response_code=2`, traced via the real portal log to
   `Failed to show access dialog: Timeout was reached` - confirmed via `xdg-desktop-portal`'s own
   `.portal` files that `xdg-desktop-portal-xapp` (Cinnamon's backend) implements `Screenshot` but *not*
   `org.freedesktop.impl.portal.Access` (the consent-dialog interface), and `xdg-desktop-portal-gtk`
   (which does implement `Access`) is `UseIn=gnome` only - a real Cinnamon-specific portal gap, not a
   Flatpak-confinement finding.
   - Retested **unconfined** on the project's own real Ubuntu 26.04/GNOME Shell 50.1 VM
     (`XDG_CURRENT_DESKTOP=ubuntu:GNOME`, genuine Wayland session): **succeeded cleanly**,
     `response_code=0`, a real 92800-byte PNG (1366x768) written to `~/Pictures/` and read back - no
     Access-dialog timeout at all. Consistent with `wayland_portal.py`'s own docstring
     ("confirmed live that calling the portal from an unsandboxed process didn't show one here").
   - **Confined-on-GNOME test run for real (2026-08-31), root-caused, not left as a bare failure.**
     `org.orcshot.SpikePortalGnome` (zero `finish-args` - strictest possible test) built and run on the
     real GNOME Wayland VM, both over SSH and from a genuinely focused terminal window (GUI mode +
     `xdotool`, to rule out "no focused app" as an artifact of SSH specifically) - both failed
     identically, `response_code=2`. The real portal log gives the exact reason, confirmed as a known,
     documented class of issue via a real upstream GitHub issue
     (flatpak/xdg-desktop-portal#1338, GNOME Shell's own `accessDialog.js`):
     ```
     Failed to show access dialog: GDBus.Error:org.freedesktop.DBus.Error.AccessDenied:
     Only the focused app is allowed to show a system access dialog
     ```
     This is **not a Flatpak-confinement wall** - it's a real, deliberate GNOME Shell security policy:
     the *requesting app itself* must be the currently-focused window. The spike script is a headless
     CLI process with no GUI window of its own at all, so it can never satisfy this check regardless of
     confinement - the terminal that launched it is a different application from GNOME Shell's window
     tracker's point of view. A real GUI app (which Orcshot genuinely is) satisfies this naturally the
     moment a user triggers a capture from within its own actual window - this was never exercised by
     the spike's own design, not a property of Flatpak.
   - **Closed completely (2026-08-31): a real GTK window spike, proven, not just reasoned about.**
     Built `org.orcshot.SpikePortalGtk` - a genuine `Gtk.Window`, shown and given 2 real seconds to be
     mapped/focused by the window manager before firing the same `Screenshot` call from inside its own
     GTK main loop. First attempt still failed identically (`response_code=2`), *despite* the window
     self-reporting `is_active()=True has_toplevel_focus=True` via GTK's own API - proving client-side
     focus alone isn't what GNOME Shell's check actually looks at. Root cause found, not guessed: the
     build had "No appstream data" (flagged in its own build log) - no `.desktop` file at all, so GNOME
     Shell's `_windowTracker` had no way to associate the window with a recognized "app" entry in the
     first place, independent of genuine X11/Wayland-level keyboard focus. Added a minimal
     `.desktop` file (`Name=Orcshot Portal Spike`, installed to `/app/share/applications/`) and
     rebuilt - **the real Access dialog appeared** ("Allow Orcshot Portal Spike to Take Screenshots?"),
     was approved, and the call succeeded cleanly:
     ```
     response_code=0
     RESULT: SUCCESS, uri=file:///run/user/1000/doc/1c3e7475/Screenshot-1.png
     RESULT: read 195685 bytes, PNG_magic=True
     ```
     Real PNG, returned through the document-portal FUSE mount exactly as `wayland_portal.py`'s own
     code comment already predicted a sandboxed caller would get (not a direct `~/Pictures` path).
     **Net result: the Screenshot portal genuinely works under real Flatpak strict confinement on real
     GNOME Wayland, end to end - real Access dialog, real user consent, real image data.** The one
     requirement it surfaced (a proper `.desktop` file with a real `Name=`) is not a workaround or a
     special case - it's standard Flatpak packaging convention any real, published Orcshot build would
     already have. Spike code and app uninstalled, nothing kept per its own classification - this
     entry is the record.

Surfaced directly questioning #185's "Wayland-only" framing (direflail, 2026-08-28): "you're SURE we can't
just use that fallback socket to run it in x11 anyway?" Good pushback - the honest answer right now is
reasoned, not proven, and the reasoning actually points the other way from what #185 assumed.

**The case for it working, not just as a redirect dialog but as real capture**: X11 itself has no
per-client security model at all - Flatpak's own sandbox-permissions docs say outright, "X11 lacks GUI
isolation, making any attempt of sandboxing futile." Once a `fallback-x11` socket is actually live (which
it is on a genuine pure-X11 session - only revoked when Wayland is also present, confirmed earlier for
#185), the connected client should have the exact same unrestricted X11 protocol access an unsandboxed
client would - there's no mechanism for Flatpak to selectively block screen-content reads while allowing
window drawing, because X11 doesn't support that granularity to begin with. If that holds, Orcshot's
existing `X11CaptureBackend` should work completely unmodified through that socket, no portal involved.

**Why this isn't already assumed true**: the original Flatpak rejection in this doc's own Packaging
section uses the word "tendency," not a documented technical wall - reads more like it may have been
ecosystem convention (portable capture libraries often auto-detect Flatpak sandboxing via
`/.flatpak-info` and route to the portal unconditionally as a *design choice*, independent of whether
direct X11 access happens to also work) than something actually verified for this specific case. Worth
being honest that swapping one unverified claim for another isn't progress - this needs a real test.

**The actual test, cheap and already possible on this machine**: a minimal `flatpak-builder` manifest
declaring only `wayland` + `fallback-x11` sockets (nothing else), making one real X11 capture call from
inside the sandbox on this host's own X11 (Mint/Cinnamon) session, and checking whether it succeeds or
hits some sandbox-level restriction. Direct, empirical, no VM needed - Flatpak's already confirmed
available here.

**Why this matters beyond curiosity**: if it works, #185's whole "Wayland-only, X11 users redirected
elsewhere" framing may be unnecessarily narrow - a single Flatpak build might genuinely work on both X11
(via fallback-x11, full native capture) and Wayland (via the portal or #184's redesigned path), using the
same kind of session-type branching `backend_select.py` already does in the `.deb` today, instead of
needing the listing-link/runtime-redirect mitigations #185 currently plans for.

direflail's own sequencing (2026-08-28): after #184 (the Snap-capable Wayland redesign), which is next up.

## #186: Find out what download/install metrics are actually available, across every channel

direflail's own request (2026-08-28): "find out what metrics we can get about how many downloads we
get. i don't want anything but numbers to make myself feel good." Explicit constraint, not just phrasing
- this is about checking what the existing distribution channels already expose, not about adding any
kind of tracking, telemetry, or analytics to Orcshot itself. No phone-home code, no third-party analytics
script on the wiki, nothing that reports on real users - just reading whatever numbers Launchpad/GitHub
already publish on their own.

**Already confirmed real, no research needed**: GitHub Releases exposes a genuine per-asset download
counter today - `gh release view v0.2.0 --json assets` (used earlier this same session to verify the
`.deb` attached correctly) returned a real `downloadCount` field per asset, currently `0` since the
release just went live. Trivial to check any time with that same command.

**Not yet checked**: whether Launchpad exposes any public download/install statistics for PPA packages
at all - historically a well-known gap/frustration in the Launchpad community (unlike Debian's opt-in
popularity-contest mechanism), but not confirmed one way or the other for this project's own PPA, not
assumed. Also unchecked: whether `apt install` from the PPA is even the kind of thing Launchpad *could*
count (PPA downloads happen from Launchpad's own mirror infrastructure, not a single tracked endpoint the
way a GitHub Release asset is).

Not investigated yet - direflail wants this recorded as a task, not resolved right now.

## #178: Insert Window never uses the nicer Wayland Shell-native window-picker overlay

Found by a REQUIREMENTS.md sweep (2026-08-23, task #99's own original write-up), re-checked against current
code: `editor_window.py`'s `_do_insert_window` still passes `force_plain_overlay=True` to
`start_window_picker`. Understood, not mysterious - the Shell-native fast path (`window_picker.py`'s own
docstring) has no hook to hand a captured image back without routing it through the standard destination
picker (save/clipboard/edit/print/external-command), but Insert Window needs the raw image placed directly
into the *current* editor's own layer stack instead, a fundamentally different use case the Shell-native
path was never built to support.

Not a bug, a real architectural gap - revisit only if `GnomeShellWindowPicker` (or whatever backs the
Shell-native path) grows a way to hand back an image directly instead of always dispatching to a
destination.

## #179: "Reuse Editor" setting (task #111) - assigned a number, never built

Found by a REQUIREMENTS.md sweep (2026-08-23), re-checked against current code: `editor_window.py`'s
`_do_open` (task #129, File > Open) still says in its own docstring "task #111's 'Reuse Editor' setting
doesn't exist yet" - confirming the setting genuinely was never built, not just historically noted as
missing once. Every capture and every opened `.orcshot` file becomes its own new `EditorWindow`
unconditionally; there's no way to configure "open into the existing window instead."

Original context (task #93, 2026-08-10): "confirmed portable... but not built this round - left as an open
decision, not yet implemented, pending confirmation it's wanted." That confirmation never happened.
Whoever picks this up should start by asking direflail whether it's actually wanted at all before
implementing - task #93's own framing was explicitly conditional on that, not a settled "yes, build this."

## #167: VM clipboard doesn't carry images across the host/guest boundary

Surfaced live (direflail, 2026-08-22), same testing session as #166. Text
clipboard sharing between the Ubuntu 26.04 Wayland VM (guest) and the X11
host works correctly (VirtualBox Guest Additions bidirectional clipboard,
set up in an earlier session) - but capturing a screenshot in the VM via
Orcshot's "Copy to Clipboard" destination and trying to paste it out to the
host produces no output and no error at all.

Not yet root-caused. Most likely explanation, not confirmed: VirtualBox's
shared clipboard has a long-documented history of unreliable or entirely
absent support for non-text formats (images/pixmaps) between host and
guest, independent of anything the guest-side application does - this may
not be a real Orcshot bug at all, just a platform limitation of VirtualBox's
own shared-clipboard implementation. Needs investigation to confirm whether
this is fixable from Orcshot's side (e.g. a different clipboard target/MIME
type that VBox's shared clipboard *does* support) or is a hard platform
limitation worth just documenting as a known gap for VM-based Wayland
testing specifically - real Wayland hardware, or a non-VM Wayland session,
wouldn't hit this at all, so it may only ever matter for this project's own
dev-testing setup, not real users.

## #189: Audit the X11 tray path for the same "deprecated tech" problem that motivated #184

direflail (2026-08-29), right after #184's Wayland redesign landed: "add a task to check the x11 side to
make sure it's using modern packaging/techniques." Direct follow-through on the same standing concern
that started #184 in the first place - direflail's own words from that earlier conversation: "you've
explicitly told me we can't put the app on Snap the way it is. combine that with the technologies being
17 years deprecated in cases, and i'm thinking nobody's going to want to install this app... find out if
[modern GNOME tech] can be used to make the version of this app... that will work properly and be
accepted by snap, flatpak, and apt." #184 answered that for Wayland (`AyatanaAppIndicator3` → GMenu/GAction
over D-Bus). The X11 side was never audited against the same standard.

**What's already known, not yet acted on**: `app.py`'s `_build_tray_icon` X11 branch uses `Gtk.StatusIcon`
- confirmed still in place after #184's redesign (X11's branch was deliberately left untouched, out of
that plan's scope). `Gtk.StatusIcon` has been deprecated since GTK 3.14 (2014) with **no direct GTK4
replacement at all** - GTK4 removed the API entirely, pushing every app toward exactly the
StatusNotifierItem/AppIndicator-style mechanisms #184 just finished moving Orcshot's Wayland side *away*
from. Worth checking directly (not assuming either "it's fine, GTK3 still supports it" or "it's exactly
the same problem #184 just solved") whether this specific deprecation actually causes any of the same
real, concrete problems #184 found for Wayland - Snap/Flatpak packaging friction, distro-level removal
plans, or actual runtime breakage on any of this project's three real test targets - or whether it's a
harmless "deprecated but still fully functional and unlikely to be removed" situation, which
`Gtk.StatusIcon` genuinely might be, given GTK3 itself (not just this one API) is the thing actually aging
out project-wide.

**Scope check needed before this becomes a plan**: is this really about `Gtk.StatusIcon` specifically, or
a broader "is anything else in this app's X11 path resting on similarly old GTK3/legacy APIs" audit?
direflail's request as given is general ("make sure it's using modern packaging/techniques"), not scoped
to the tray icon alone - worth a clarifying pass before writing an implementation plan, same as #184 got
before its own plan was written.

## #184: Explore a Wayland capture path that doesn't depend on the bundled GNOME Shell extension, to open up Snap and Flatpak (RESOLVED 2026-08-30)

**The one remaining open caveat from this entry's own final review (below - "extension-install-from-
sandbox step... still an open prototype") is now closed.** The real, non-throwaway Snap channel plan
(PR #9, hardened by `#192`'s own investigation in PR #10) built and live-verified exactly that: a
confined Snap process installing `orcshot-tray@orcshot.org`'s files into the real per-user extensions
path (`channel_detect.install_bundled_extension_if_needed`), its `enable_extension()` write reaching
real, persistent dconf storage, and GNOME Shell loading the extension from that write - all confirmed
live in real CI, not reasoned about. See `#192`'s own entry above for the full trail. The redesign
itself was already live-verified (Task 7, below); this closes the one caveat left after that.

**Confirmed wanted (direflail, 2026-08-28): "we definitely want to do this."** Ready to move past the
thinking-it-over stage whenever picked up - next step is the brainstorming skill's normal process
(questions, approaches, a real design) before any implementation, given the scope here (redesigning a
core capture subsystem) is squarely architectural, not a small bounded change.

**Hard constraint, stated explicitly (direflail, 2026-08-28): "whatever the plan is, it must include being
compatible with snap, flatpak, software manager, and apt. i don't want any more surprises at distribution
time."** Not a nice-to-have - the design needs to hold up across all four from the start, not get
retrofitted after landing on one and discovering it breaks another (which is exactly what happened with
the original Flatpak rejection, and what #187 is now re-litigating with real evidence instead of
assumption). "Software Manager" here likely means Mint's own `mintinstall`, not GNOME Software
specifically - worth confirming which the whole "surprises" list actually means before designing, since
GNOME Software's own discoverability ceiling (confirmed earlier: won't show a plain apt/PPA package at
all, only Snap/Flatpak) isn't something this redesign can independently fix - it's already covered by
"Snap" and "Flatpak" being separately on the list.

**Direct sequencing from direflail (2026-08-28): this is next, ahead of #187 and #185's own further
design.**

Surfaced during a conversation with direflail (2026-08-28) about why Orcshot isn't discoverable via GNOME
Software/App stores on Ubuntu - confirmed live that GNOME Software's browsable catalog doesn't surface
plain apt/PPA packages at all on either 24.04 or 26.04, regardless of caching state, and the only way in
is Snap or Flatpak.

The bundled GNOME Shell extension (`orcshot-clipboard@orcshot.org`) is what currently powers the
Wayland-native fast path: the window picker, the translated tray menu on Wayland, Shell-native region
select. Real research this session (not assumed) found the sandboxing story is more nuanced than first
guessed:

- Flatpak's rejection in this doc's own Packaging section ("avoids Flatpak's sandbox tendency to force
  portal-mediated capture even under X11") is specifically about X11 - doesn't automatically rule out
  Wayland-only Flatpak/Snap builds.
- Snap's strict confinement can get *direct* X11 access via the plain `x11` interface (confirmed against
  Flameshot's real, published `strict`-confinement snapcraft.yaml) - not portal-forced the way Flatpak is.
- The Shell extension itself doesn't strictly require the system-wide `/usr/share/gnome-shell/extensions/`
  path that only `.deb`'s root-privileged postinst can write to - GNOME Shell has always supported a
  per-user path (`~/.local/share/gnome-shell/extensions/<uuid>`, confirmed via GNOME's own admin docs),
  reachable with the ordinary `home`/`--filesystem=home` grants both Flatpak and Snap commonly hand out.
  Not yet proven for Orcshot specifically - would need an actual prototype.

**What this task is actually about**: rather than relying on that per-user-path workaround to keep the
existing Shell-extension architecture alive inside a sandbox, consider whether the Wayland fast path
could be redesigned to not depend on a GNOME Shell extension at all - something portable across
compositors and packaging formats, not just GNOME-Shell-specific machinery smuggled through a permission
grant. Worth weighing against what's actually lost: the Shell extension is also what gets you the
translated tray menu, the Shell-native window picker, and per [[feedback-extension-reload-caching]],
whatever replaces it needs its own answer to "how does a code change actually take effect" that doesn't
require a full logout/login either.

**Design progress (2026-08-28), from a real brainstorming session with direflail - most of this is now
verified live, not theorized:**

- **Region-select and clipboard are already solved, today, with zero extension dependency.** Read the
  actual code rather than assumed: `WaylandCaptureBackend` (portal-based pixel grab) +
  `region_select_wayland.py` (Orcshot's own client-side overlay, loupe included - `draw_magnifier`,
  `_show_magnifier`, real and active) is *already* the automatic fallback whenever the Shell extension
  isn't available, already confirmed live against the real portal backend. Same story for
  `WaylandClipboardBackend`. Neither needs redesigning - they're already the portable answer.
- **The `org.gnome.Shell` D-Bus wall is real, confirmed via direct precedent**: a strict-confinement Snap
  trying to call GNOME Shell's own D-Bus interfaces (same class of call Orcshot's bundled extension uses -
  `BUS_NAME = "org.gnome.Shell"`, confirmed in `gnome_clipboard.py`) got denied by AppArmor with no
  interface to fix it - a Snap maintainer's own words: "the trust model of snaps (untrusted and hence
  confined) is not compatible with gnome-shell extensions (trusted, deeply integrated with the desktop,
  unconfined...)." Anything still calling `org.gnome.Shell` directly carries this same risk under strict
  confinement; anything using only the standard portal (`org.freedesktop.portal.Desktop`) shouldn't, since
  portals are the actual sanctioned bridge for confined apps.
- **The XDG portal's `Screenshot` interface has a `target` option (v3: Screen/Window/Area/Active Window)
  that Orcshot's own `wayland_portal.py` already defines constants for but never uses** (only
  `TARGET_SCREEN` is called anywhere). Live-tested `target=Area`: works, renders GNOME's own native
  Screenshot UI (Selection/Screen/Window tabs) - genuinely GNOME's real screenshot tool, not a bare portal
  placeholder, confirmed via a live VirtualBox screenshot of the actual rendered UI.
- **`target=Window` was tested twice.** First attempt showed a black screen - traced to a real crash
  (`xdg-desktop-portal-gnome.service: Main process exited, code=dumped, status=11/SEGV`), but a clean
  retest (session confirmed awake, not idle/locked first) rendered fine with zero portal errors in the
  journal - the crash was session-timeout interference, not a real bug in the feature. Corrected from an
  earlier wrong conclusion that `target=Window` was broken.
- **`target=Window` was rejected anyway, on a real product principle, not a technical one.** Even working,
  it hands the entire window-picking interaction to GNOME's own native Screenshot app - GNOME-branded
  chrome, not Orcshot's. The portal owns that UI end-to-end opaquely; there's no way to get raw window
  data back for Orcshot to render its own picker on top of it. direflail's own words: "i do not want to
  use another screenshot app. that's why we developed orcshot." Recorded as a standing principle -
  [[feedback-no-delegating-to-other-screenshot-apps]] - not just a decision local to this task: Orcshot
  must never hand any piece of its own UX to another screenshot app's own interface, even via a sanctioned,
  portable mechanism like a portal.

**Resulting shape of the design, not yet fully written up as a spec:**

- Region-select, clipboard: unchanged, already extension-free, already proven.
- Window Picker: stays on the third-party `window-calls` extension - not replaced by the portal, per the
  principle above. This is the one piece that keeps the real `org.gnome.Shell` dependency and its
  associated Snap-confinement risk; everything else avoids it.
- **Tray icon/menu - redesigned further (2026-08-28), not just "translate the existing AppIndicator3
  menu."** direflail pushed back hard on settling for AppIndicator3's known icon-alignment limitation,
  correctly identifying that the underlying stack is genuinely legacy tech, not just "proven and safe."
  Verified, not assumed:
  - `libayatana-appindicator` (what Orcshot uses today, the "3" in `AyatanaAppIndicator3`) is **officially
    declared obsolete by its own upstream** - its own GitHub description: "Gtk-based, DBusMenu-based,
    OBSOLETE, please use libayatana-appindicator-glib for new implementations."
  - The real successor, `libayatana-appindicator-glib` (2.0.3, actively released), drops dbusmenu entirely
    in favor of `org.gtk.Menus`/`org.gtk.Actions` (GMenuModel/GActionGroup) - confirmed no dbusmenu
    fallback/compat mode exists.
  - **Orcshot doesn't need that library as a dependency at all** - `Gio.DBusConnection.export_menu_model()`/
    `export_action_group()` are core, official PyGObject/Gio APIs (confirmed against
    api.pygobject.gnome.org's own class docs), already the same `Gio` module used throughout this
    codebase. Publishing a GMenu-based tray menu is achievable with zero new dependencies.
  - **The real gap, confirmed by checking actual source, not assumed**: no GNOME Shell extension anywhere
    renders GMenu-model-published SNI menus. Checked the Ayatana org's own repo list (no GNOME Shell
    extension maintained by them at all - their only confirmed renderer is `qmenumodel`, a Qt5/KDE one);
    checked both real GNOME candidates' actual source directly (`ubuntu-appindicators@ubuntu.com` and
    `status-tray`) - zero GMenu-handling code in either. The SNI spec's own `Menu` property is just an
    untyped D-Bus object path (`<property name="Menu" type="o"/>`, confirmed from
    `notification-item.xml`) - "dbusmenu lives there" has only ever been convention, never something the
    interface itself declares, so a *general* watcher has no standard way to know when to expect GMenu
    instead.
  - **Snap compatibility, confirmed against real policy source, not assumed**: `org.kde.StatusNotifierWatcher`
    (the actual tray-icon registration mechanism, itself implemented by a Shell extension today) is
    explicitly on the sanctioned list for Snap's standard `desktop` interface (`snapd`'s own
    `interfaces/builtin/desktop.go`). This is concrete proof that "a Shell extension is involved" was never
    the disqualifying factor - what got denied before (`org.gnome.Shell` itself, confirmed via the
    Extension Manager AppArmor precedent) is a *different*, unsanctioned name, called in the *opposite
    direction* (Orcshot's confined code reaching out to it). A new design where Orcshot only ever exports
    on its own connection, and an unconfined Shell extension reads *from* Orcshot rather than Orcshot
    calling *into* anything privileged, doesn't hit that wall - Shell extensions are never Snap-confined
    in the first place, regardless of which direction anything points.
  - **Decision: build a new, Orcshot-specific GNOME Shell extension for this, not a general-purpose one.**
    direflail's own call, backed by real technical reasoning, not just scope discipline: scoping narrowly
    sidesteps the SNI `Menu`-property ambiguity above entirely (a general watcher has to guess/negotiate
    protocol for arbitrary apps; an Orcshot-specific one just already knows what to expect from Orcshot)
    and avoids competing for `StatusNotifierWatcher` ownership at all (no need to be a general watcher,
    just needs to find and render Orcshot's own indicator) - the same ownership-race problem that makes
    `status-tray` silently inert against `ubuntu-appindicators` on real Ubuntu/Mint targets, sidestepped by
    construction rather than fixed. Also finally fixes the icon-alignment bug for real, since Orcshot would
    control the entire rendering path end to end - no third-party `dbusMenu.js` hard-coding
    `xAlign: Clutter.ActorAlign.END` to work around.
  - **Core mechanism proven live (2026-08-28), not just reasoned about.** Built a minimal real test: a
    Python script exporting a `Gio.Menu` + `Gio.SimpleActionGroup` over D-Bus on its own well-known name
    (`Gio.DBusConnection.export_menu_model`/`export_action_group`), and a bare `gjs` script (same
    methodology this project already used to verify the tray-menu gettext bug in task #183) consuming it
    via `Gio.DBusMenuModel`/`Gio.DBusActionGroup` - the exact runtime `gnome-shell` itself uses. Real data
    round-tripped correctly: labels, action names, and **the icon attribute** all arrived intact
    (`icon=test-icon-1`, exactly as published). Actions become available via `action-added` signals with
    correct bare names (not the menu's own `group.action` prefixed form - that prefix is a local
    menu-mounting convention, not part of the wire format) after some real async proxy-sync latency - a
    normal D-Bus proxy behavior a real implementation handles by reacting to signals, not a defect.
  - **Still open, and now the actual next real question**: this test used a plain custom bus name
    (`org.orcshot.TrayTest`), not real SNI/`StatusNotifierWatcher` registration for the tray *icon* itself
    - the menu-export mechanism is proven, but how the new extension actually discovers "this is Orcshot's
    indicator, here's where its menu lives" in a real tray-icon context (some form of SNI registration for
    the icon specifically, vs. bypassing SNI entirely via `Gio.bus_watch_name` for Orcshot's own name) is
    still unresolved - the next real prototyping step, not resolvable from documentation alone.
  - **Unrelated, permanent, already-true-today limitation worth remembering regardless of any of this**:
    AppIndicator-family icons have no distinct left-click ("activate") action once a menu is attached - a
    real, documented, upstream protocol limitation (`app.py`'s own comment on `_build_tray_icon`, citing
    https://bugs.launchpad.net/bugs/1910521), not something GMenu vs. dbusmenu changes either way. X11's
    `Gtk.StatusIcon` keeps its own separate left-click-for-instant-capture shortcut specifically because of
    this - deliberately not unified onto one tray mechanism for both platforms, and that reasoning doesn't
    change here.
- Net effect of the whole #184 design as it now stands: the bundled `orcshot-clipboard@orcshot.org`
  extension's role shrinks to *only* whatever Window Picker still needs (via the separate third-party
  `window-calls` extension it already depends on) - region-select, clipboard, and the tray icon/menu all
  move to mechanisms with no `org.gnome.Shell` dependency at all, via the portal and a new, narrowly-scoped,
  Orcshot-specific Shell extension respectively.

Not yet written up as a formal design doc - still mid-brainstorm, but the shape is now real and detailed
enough that formalizing it into `docs/superpowers/specs/` is the natural next step whenever picked up.

**RESOLVED (2026-08-28/29) - the Snap-compatibility question that motivated this entry is now answered,
live, not just reasoned about.** Formalized as
`docs/superpowers/specs/2026-08-28-wayland-capture-redesign-design.md` and implemented via
`docs/superpowers/plans/2026-08-28-wayland-tray-redesign.md` (7 tasks, subagent-driven-development, all
merged to `worktree-wayland-tray-redesign`): a new `orcshot-tray@orcshot.org` extension (GMenu/GAction
over D-Bus, exported on Orcshot's own already-owned connection) replaces `AyatanaAppIndicator3` entirely
on Wayland; region-select, clipboard, and Window Picker were unaffected per the design's own scope.

- **The actual proof point, done for real**: a throwaway `snapcraft.yaml` (`confinement: strict`,
  `base: core24`, `extensions: [gnome]`, a `dbus` slot for `org.orcshot.Orcshot`) built and installed on
  both a Linux Mint host (`snapcraft pack --destructive-mode` doesn't work cross-distro - built via a real
  LXD-managed build instead) and the Ubuntu 26.04 Wayland VM. On the VM, under real strict AppArmor
  confinement: `gnome_tray_export.export_tray_menu()`'s `export_menu_model()` call succeeded with **zero**
  `apparmor="DENIED"` lines anywhere near `TrayMenu`/`org.gtk.Menus`/`export_menu` - confirmed not just by
  absence of denials but by a live `gdbus call` against the confined process's own exported object
  returning real, correct menu data (label, action, icon bytes all intact). The standard `desktop`
  interface plus one `dbus` slot declaration is all a real Snap package would need - no special AppArmor
  carve-out required. This is the exact mechanism (a confined process registering objects on its own
  already-owned D-Bus connection, never calling *out* to an unsanctioned bus name like `org.gnome.Shell`)
  the whole redesign was architected around, now proven under real confinement, not just read from
  `snapd`'s AppArmor policy source.
- **Expected, not a new problem**: the (out-of-scope, unchanged) clipboard extension's own
  `Ping()`-to-`org.gnome.Shell` availability check *was* denied under confinement in the same test run -
  exactly the disqualifying pattern this whole redesign exists to route around for the tray, just not yet
  applied to clipboard/region-select (tracked separately, not part of this entry's own scope).
- **Real bugs live-caught during Task 7 verification, neither Tasks 1-6 nor their reviews caught**: (1)
  the Wayland tray menu was missing icons on Open File/Preferences/Quit, a direct violation of task #146's
  existing "every icon in the wayland version must look like the x11 version" rule - fixed
  (`stock_icon_gicon()`, hand-drawn Adwaita-lookalike geometry, same as the X11 builder already used).
  (2) The panel button's own icon reused the "region" capture-mode glyph instead of Orcshot's real logo -
  a deliberate, plan-documented tradeoff direflail asked to change once actually seen live ("please don't
  change the branding on the app without talking to me first" - now a standing memory). Fixed via
  `Gio.ThemedIcon.new('orcshot')`, no new D-Bus export needed. (3) A real, root-caused bug where the
  exported `Gio.Menu` was built as a dead local variable with nothing keeping it alive -
  `g_dbus_connection_export_menu_model`'s own docs say "the data is owned by the caller of the method,"
  and every known-good example of this API (including this project's own earlier prototype) keeps it
  alive as a persistent reference. Fixed by storing it on `self._tray_menu`.
- **Open, unresolved risk, not papered over**: after the above fixes, the tray menu still failed to
  populate/respond to clicks following a plain reinstall+logout/login cycle - only a full VM *reboot*
  fixed it. Diagnostic logging (temporarily left in `extension.js`, tagged `orcshot-tray-diag`) proved
  `items-changed` never fired and the button was inert to `button-press-event`/`touch-event` entirely on
  the broken boot, while a clean reboot showed the complete correct sequence. Matches the general class of
  issue already documented in `REQUIREMENTS.md` and the `feedback-extension-reload-caching` memory
  (extension-reload cycling causing session-level corruption reaching beyond the reloaded code itself),
  but this is the first time it's been severe enough that logout/login alone wasn't sufficient - full
  reboot was needed. direflail's own read: "we didn't have this issue before. i'm guessing we'll see it
  again." **Not closed out as solved** - if this recurs on a genuinely fresh boot (not a session that's
  been through many reinstalls/logouts like today's testing), it needs real investigation, not another
  reboot-and-move-on.
- **A second, separate gap found and only partly fixed**: the new extension's UUID
  (`orcshot-tray@orcshot.org`) was missing from `gnome_extension_setup.py`/`first_run_setup.py`'s
  enable-on-first-run wizard entirely - fixed for *fresh* installs. Still open: an **existing** install
  upgrading from before this redesign already has `is_first_run_setup_done() = true`, so the wizard won't
  re-show and the new extension has no path to get enabled short of a Preferences action or a new
  upgrade-specific consent flow - deliberately not invented as part of this work, since
  `gnome_extension_setup.py`'s own docstring is explicit that enabling must only ever happen from the
  user's own confirmation click, never as a side effect of an upgrade. Real UX gap for anyone upgrading an
  existing Orcshot install to this version on GNOME Wayland - worth its own follow-up task before this
  ships as a real release.
- Also found and fixed inline (not part of the original 7-task plan): `debian/control` still required
  `gir1.2-ayatanaappindicator3-0.1` even though nothing imports `AyatanaAppIndicator3` anymore.

**One thing this result does NOT prove, caught by the final whole-branch review**: Task 7's Snap test
covered only `export_menu_model()` surviving confinement - it never exercised actually *installing* the
`orcshot-tray@orcshot.org` extension's files from inside a Snap or Flatpak sandbox at all (the throwaway
snap only shipped the app, not the extension). The "not yet proven for Orcshot specifically - would need
an actual prototype" caveat on the per-user extension-install path (this entry's own text, above) is still
exactly as unproven as it was before this branch. #185 and the real Snap package need that prototype
before either can be considered genuinely unblocked - it is not automatically covered by this result.

**Next step**: this branch (Tasks 1-7 complete, live-verified) is ready for final whole-branch review and
merge. #185 (Flatpak) and the real, non-throwaway Snap package are meaningfully closer given this result
(the actual D-Bus/AppArmor mechanism is proven), but NOT fully unblocked - the extension-install-from-
sandbox step above is still an open prototype, alongside the upgrade-path gap (#188) and the not-yet-
closed reboot-vs-logout finding.

## #185: A Wayland-only Flatpak build, alongside the existing dual-mode (X11+Wayland) `.deb`/PPA release (RESOLVED 2026-08-31)

Originally scoped (2026-08-28) as a *Wayland-only* second build: drop X11 support entirely for
Flatpak, redirect X11 users to the `.deb`/PPA at the listing level, and add an in-app runtime warning
dialog for anyone who installed it anyway on a pure-X11 session. That framing is superseded entirely -
not just refined - by what was actually designed and shipped.

**What shipped instead, and why it could**: `#187`'s own live proof (below) settled the question this
entry's original framing was working around - `fallback-x11` genuinely gives real, unrestricted X11
capture under Flatpak, with no portal involved, contrary to the original "Flatpak forces X11 through
the portal" rejection this entry was originally sidestepping. That made the Wayland-only design
unnecessary: a single manifest (`org.orcshot.Orcshot.yaml`) declares `--socket=wayland` **and**
`--socket=fallback-x11` together and gets full, direct capture on both - Flatpak's own
Wayland-present-revokes-X11-socket mechanism (real, confirmed during the original spike) turns out not
to matter, because the fallback socket being revoked on Wayland sessions is exactly correct: those
sessions use the Wayland path, X11 sessions keep the fallback socket and get real X11 access. No
listing-level redirect, no runtime warning dialog, no split "Wayland users get Flathub, X11 users get
the PPA" story - one build, one manifest, feature parity with the `.deb`/PPA release on the same host
this project's other channels already run on.

**Also resolved along the way**, each with its own BACKLOG entry: `#187` (fallback-x11 proof),
`#192`'s Snap-channel precedent for the Shell-extension/schema/confinement questions this design also
had to answer for Flatpak, and this same fix round's own final-review pass (9 commits,
`f9a48e8..8c5a743` plus this fix round) - including a real Critical bug (autostart silently aborting
first-run setup on this channel, fixed by hiding the autostart checkbox outright here since there's no
systemd access to offer it against at all) and a live attempt to narrow the `--talk-name` D-Bus grant
this design needs for the tray extension to activate immediately, reverted after live-testing showed
it genuinely doesn't work on a real GNOME Shell (see `#194` below). See
`.superpowers/sdd/2026-08-31-flatpak-channel/` for the full design spec, plan, and final review.

**Still open, tracked separately now rather than under this entry**: `#194` (Flathub submission
readiness - `--share=network` during build, appstream metadata) and `#195` (the Flatpak channel's own
GSound gap - no capture-complete sound on this channel).

## #132: RPM-family distros (Fedora, openSUSE) and Arch/AUR - real scope, not yet started

Already referenced in passing in `RELEASING.md` step 7 ("a separate, later effort") with zero detail
anywhere - this entry is the actual sizing, worked through with direflail (2026-08-28) after the Snap/
Flatpak conversation raised the natural follow-up question. Explicitly a "maybe at some point" - not
committed to, not scheduled, just no longer a bare cross-reference to nothing.

**Why this is a genuinely separate track, not a fourth target alongside the existing three**: Mint,
Ubuntu 24.04, and Ubuntu 26.04 all share one `.deb` today precisely because they're all Debian-family -
`RELEASING.md` step 6 says outright that `Architecture: all` with no series-specific build-deps means one
upload covers everything, no per-target packaging work. Fedora breaks that assumption entirely:

- **New packaging format**: an RPM `.spec` file, different tooling (`rpmbuild`/`rpmlint` vs.
  `dpkg-buildpackage`/`lintian`) - though Fedora's `%pyproject_*` macros are a real, mature equivalent to
  Debian's `pybuild` for a `pyproject.toml`+hatchling project like this one, not exotic territory.
- **Real dependency-name research, not assumed**: every line of `debian/control`'s deps needs its actual
  Fedora name found and verified - `python3-gi` → `python3-gobject`, `gir1.2-gtk-3.0` → Fedora's own
  GTK3/typelib split, and down the rest of the list (hatchling, pytest, hypothesis, scipy, numpy, shapely,
  xlib, rsvg, gdkpixbuf, pango, glib). Almost certainly all exist given Fedora's own strong Python
  packaging culture, but "almost certainly" isn't this project's bar for anything else, and shouldn't be
  here either.
- **Its own hosting**: Fedora's PPA-equivalent is COPR - a new one-time setup, parallel to the existing
  Launchpad PPA config.
- **Its own live compat round, not a rerun of the existing one**: Fedora Workstation defaults to
  GNOME/Wayland even more consistently than Ubuntu, so the existing Shell-extension architecture should
  carry over conceptually - but Fedora ships newer GNOME Shell versions faster than Ubuntu LTS does, the
  same axis (GNOME Shell version drift) that already caused real, documented bugs between 24.04 and 26.04
  this project has directly hit. A real Fedora VM and its own logout/login reload-testing cycle
  ([[feedback-extension-reload-caching]]) is needed, not assumed to just work.

**Net assessment**: comparable in scope to the *original* `.deb` packaging effort, not a cheap addition
to what already exists. openSUSE (also RPM-based) and Arch/AUR would each need their own version of this
same research even if the RPM spec itself carries over partially to openSUSE - not free just because
Fedora's done first.

Not scoped, not designed, no decision made - explicitly lower priority than #184/#185.

## #181: Crop-offset origin assumption unverified specifically for non-GNOME Wayland compositors

Narrowed successor to the old #175 (closed for GNOME - see REQUIREMENTS.md's Task #175 entry for the full
resolution). `capture/wayland.py`'s Wayland path reads monitor geometry through GDK's compositor-agnostic
enumeration (`gdk_screen_layout`), not a GNOME-specific API, so in principle a different Wayland compositor
(KWin, a wlroots-based one) could use a different coordinate convention for `bounds.left`/`bounds.top` than
Mutter's proven-always-non-negative guarantee. Not checked, and not urgent: orcshot's Wayland support is
built around a bundled GNOME Shell extension and isn't a supported target on other compositors anyway -
revisit only if that ever changes.
