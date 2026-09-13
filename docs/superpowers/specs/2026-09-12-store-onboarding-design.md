# Snap Store and Flathub onboarding — design

**Date:** 2026-09-12 · **Backlog:** #198 (this spec), #197 (its snap/flatpak halves), #214 and
#219 (folded into the Snap track) · **Depends on:** #205 code (merged, PR #23); EGO acceptance
gates only the *public* steps, see §4 · **Builds on:** `2026-08-30-snap-channel-design.md`,
`2026-09-02-flathub-readiness-design.md`, `2026-09-11-snap-compliant-extension-delivery-design.md`,
and Orclab's shipped `snap` and `flatpak` ingredients (`orc-package`, live-researched 2026-09-11).

## Why this exists

Both channels build green in CI and have been install-tested on real VMs, and neither has ever
reached a user: `snap info orcshot` still says "no snap found" and
`flathub.org/api/v2/appstream/org.orcshot.Orcshot` still 404s. #198 has been open since
2026-09-07; its blockers (#205's `personal-files` plug, #209's manifest lint, #210/#212/#215's
Save under confinement, #217's launcher icon) are all resolved. What is left is sequencing and
executing the onboarding, and fixing whatever reality disagrees with along the way.

The *mechanism* is not designed here from scratch. Orclab ships a `snap` and a `flatpak`
ingredient whose `/orc-package` application writes the `channels.yaml` leaves, the `RELEASING.md`
steps and their `**One-time setup:**` blocks. This spec fixes the decisions the ingredients leave
to the project and the order everything runs in.

## Decisions

1. **One spec, two tracks, strict order:** Snap track → 0.4.0 release → Flathub track. The two
   channels have different blockers and different accounts, but they land in the same
   `RELEASING.md` and `channels.yaml`, and the checklist should be renumbered once, not twice.
2. **The snap that is uploaded is the CI-built artifact**, not a local `snapcraft pack`. It is
   the binary already install-tested on the 26.04 VM, traceable to a commit and a run, and it
   needs no LXD/Multipass on the Mint host. The local build is written down as the fallback for
   the day the artifact is gone (90-day retention) or GitHub is down — one sentence, not a second
   pipeline.
3. **#214 and #219 are the Snap track's first tasks**, not separate prerequisites and not
   deferred to "before stable". The first store upload, even to `beta`, is not shipped with a
   broken SVG loader or a placeholder icon.
4. **0.4.0 is a normal `/orc-release` run of the existing `RELEASING.md`**, which by then
   contains the Snap Store step. It is the first release that exercises that step as a checklist
   step, and it is the tag the Flathub submission points at. No one-off uploads outside the
   process.
5. **The Flathub manifest is derived, not maintained.** `scripts/flathub-manifest.py <tag>`
   rewrites exactly one source block of the repo manifest (`type: dir` → `type: git` + tag +
   commit). The repo manifest stays as it is, so local and CI builds keep building the working
   tree. Switching the repo manifest to a git source would make the Flatpak verify job test the
   last tag instead of the PR; maintaining two manifests by hand drifts within a week.
6. **Nothing public waits on extensions.gnome.org, and nothing public ships without it.** Snap
   goes to `beta` (unlisted) whenever it is ready. The Flathub submission PR is opened whenever
   `v0.4.0` exists (review takes days regardless). Promotion to snap `stable` and the Flathub
   merge — the two steps that put Orcshot in front of GNOME users — wait until EGO lists
   `orcshot@orcshot.org` and a released tag's `EGO_URL` points at it. Until then a GNOME
   first-run would promise an extension that is not there.
7. **Every irreversible, externally visible action is direflail's to trigger**: `snapcraft
   upload`, the forum post, opening and merging the Flathub PRs, and `/orc-package` itself
   (user-invoked by design). The work here prepares each one and shows its exact content first.

## 1. Scope

**In:** #214, #219, the Snap Store first upload and `dbus` slot declaration, `RELEASING.md` and
`channels.yaml` for both channels, `scripts/flathub-manifest.py`, the Flathub submission PR and
its reviewer answers, the per-release Flathub update action, #197's snap/flatpak halves.

**Out:** #186 (reading real download numbers — the leaves' `metrics:` lines arrive with the
ingredients, but nothing is measurable until something is published), #132 (RPM/Arch), #213
(external commands under Flatpak), #207 (autostart under snap), #197's PPA half (GPG passphrase
caching, hardware keys — stays open), and editing Orclab's ingredients. The ingredient deltas
this work surfaces go into one closing BACKLOG update for Orclab #33; nothing in `~/projects/orclab`
is touched from this repo.

## 2. Snap track

One branch, one PR. Task order is fixed because each step's verification depends on the previous
one's artifact.

### 2.1 #214 — the SVG loader

The CI snap logs `g_module_open() failed for .../libpixbufloader_svg.so: undefined symbol:
rsvg_handle_get_pixbuf_and_error` at startup. The entry's hypothesis — `stage-packages` pulls
Ubuntu 24.04's `librsvg2-2` via `gir1.2-rsvg-2.0`, and the platform snap's newer loader resolves
the older staged library first — is confirmed before anything is changed: `snap run --shell
orcshot`, then `ldd` on the loader and `nm -D` on both librsvg copies. Whether toolbar icons
(`ui/icons.py`) and Insert SVG actually break is recorded from the 26.04 VM at the same time.

Fix: drop `gir1.2-rsvg-2.0` (and the librsvg it drags in) from `stage-packages` if the `gnome`
extension's platform snap already provides the `Rsvg-2.0` typelib and library — the reasoning
that removed GTK/pixbuf staging under #206. If it does not, pin the platform content snap's
track instead. `THIRD_PARTY_NOTICES.md` is updated if a staged package leaves. Verified on the
26.04 VM from the branch's CI artifact: no loader error in the log, toolbar icons render, Insert
SVG works.

### 2.2 #219 — the store icon

A Snap Store listing icon comes from a top-level `icon:` in `snapcraft.yaml` (which #219 notes
also becomes the launcher icon, so #217's verification is re-run). The store wants ≥ 256×256
PNG; the only PNG in the repo is 155×147.

Per the standing rule, the visual choice is direflail's: the real candidates (the existing SVG
rasterised at 256 and 512, the existing PNG upscaled for contrast) are shown as the store page
would render them, and the chosen file is committed in the repo and referenced by a top-level `icon:` (the
repo keeps `snapcraft.yaml` at its root; the path is whatever the file's real home is).
`review-tools` runs again afterwards because the icon is part of the reviewed package.

### 2.3 `/orc-package snap`

direflail types it. Inputs: snap `orcshot`, publisher `artificialorctelligence`, first channel
`beta`, architecture `amd64`, parent `desktop.python.linux.snap`. Its two checks — `snapcraft
whoami` (piped through the ingredient's e-mail redaction) and `snapcraft names` — should both pass:
login and registration were done 2026-09-11 (login expires 2027-09-11). It writes the leaf, the
`RELEASING.md` step and its one-time-setup block; the existing placeholder leaf (only
`requirements:`) is replaced, with its EGO-dependency line kept and reworded ("until EGO lists the
extension, GNOME-Wayland features run on the portal fallback").

### 2.4 Reshape to the CI artifact (decision 2)

The ingredient's leaf assumes `prepare: snapcraft pack`. For Orcshot:

- `prepare:` downloads the `snap / build` artifact of the workflow run for `HEAD`'s commit with
  `gh run download` (looked up by `--commit`), into a scratch directory. If no successful run
  exists for that SHA the command fails with that message — that failure *is* the "CI is green"
  gate, and it is why this step sits after the confirm-CI step in the checklist.
- `artifact:` is the downloaded `orcshot_<version>_amd64.snap`, version read the same way the
  ingredient reads it (`pyproject.toml`; `snapcraft.yaml`'s `version:` already comes from there).
- `action:` is unchanged: `snapcraft upload --release=beta <artifact>`.
- `requirements:` gain the fallback sentence: if the artifact has expired, `snapcraft pack`
  locally (needs LXD or Multipass once) and upload that, noting in the release that the uploaded
  binary is not the VM-tested one.
- `.github/workflows/snap.yml` does not change.

### 2.5 First upload and the `dbus` declaration

Sequence, each step confirmed before the next:

1. `review-tools.snap-review` on the downloaded artifact (it must sit under
   `~/snap/review-tools/common/`). Expected: exactly one `human review required` line, the `dbus`
   slot's `deny-connection` constraint. Anything else is a defect fixed on this branch first.
2. direflail runs `snapcraft upload --release=beta` (via `/orc-publish desktop.python.linux.snap`
   once the leaf is written). The revision is held.
3. direflail posts in the snapcraft forum's `store-requests` category. The text is drafted here:
   snap `orcshot`, bus name `org.orcshot.Orcshot`, one paragraph — the app owns the name for
   single-instance activation and its tray/actions export, the GNOME Shell extension calls in,
   nothing is exported beyond the app's own name. Precedent in the ingredient: BusyMax, two days.
4. After the grant, the **same** artifact is re-uploaded (held revisions are not released
   retroactively). `snap info orcshot` now shows a `beta` channel map — the only proof a revision
   got past review.
5. One `snap install --beta orcshot` on a clean 26.04 VM snapshot: first-run, one capture, no
   loader error, toolbar icons present. This is #214's proof and the store's first real install.

`stable` promotion (`snapcraft release orcshot <rev> stable`) is a later, separate decision,
after decision 6's EGO condition holds. The `RELEASING.md` step says so.

## 3. The 0.4.0 release

A normal `/orc-release` run. Two things pinned here so it does not stumble:

- **Metainfo `<releases>`** tops out at 0.2.0. The release adds 0.3.0 and 0.4.0 entries; Flathub's
  linter fails a metainfo whose newest release is not the built version. This recurs every
  release, so `RELEASING.md`'s "Pick a version" step gains the reminder.
- **Extension skew.** The app tolerates one release of extension skew through the capability
  handshake, so 0.4.0 does not wait for EGO. `EGO_URL` in `ui/extension_install.py` stays the
  placeholder unless EGO accepts before the release is cut, in which case it is pointed at the
  listing in the release commit.

The Flathub track starts when `v0.4.0` exists on origin.

## 4. Flathub track

One branch, one PR in this repo; two PRs on GitHub against Flathub, both direflail's.

### 4.1 `scripts/flathub-manifest.py <tag>`

Reads `org.orcshot.Orcshot.yaml`, finds the module named `orcshot`, replaces its single
`type: dir` source with

```yaml
- type: git
  url: https://github.com/artificialorctelligence/orcshot.git
  tag: <tag>
  commit: <sha the tag points at, resolved with git rev-list -n1>
```

and writes the result to stdout. Nothing else changes, so what Flathub builds is the recipe CI
verifies, differing only in where the source comes from. It refuses a tag that does not exist
locally and a manifest with anything other than exactly one `orcshot` module with one `dir`
source. Uses PyYAML (present on the Mint host, 6.0.1; not a project dependency, and the script
says so if it is not importable rather than falling back to regex). One test: on a fixture
manifest the output differs from the input in exactly that one source block, and every other
module is byte-identical.

`flathub-lint-exceptions.json` is copied into the Flathub repo beside the manifest, unchanged.

### 4.2 `/orc-package flatpak`

direflail types it. Inputs: app id `org.orcshot.Orcshot`, manifest `org.orcshot.Orcshot.yaml`,
GitHub user `artificialorctelligence`, upstream `github.com/artificialorctelligence/orcshot`,
parent `desktop.python.linux.flatpak`. Its checks: `gh auth status` as that user, and
`gh api user --jq .two_factor_authentication` printing `true` — **2FA is direflail's to enable
before submission**, or Flathub's write invitation cannot be accepted. The per-app check
(appstream API 200) fails today, correctly; the recipe is written anyway.

### 4.3 Reshape

The ingredient's per-release `action:` edits the Flathub manifest with `sed` on `tag:`/`commit:`
lines. For Orcshot the action regenerates it instead: `scripts/flathub-manifest.py "$V" >
"$TMPDIR/flathub-org.orcshot.Orcshot/org.orcshot.Orcshot.yaml"`, then commit, push, `gh pr
create` as the ingredient has it. Merging stays manual and out of the action.

### 4.4 The submission PR

Against `flathub/flathub`, branch from `new-pr`, PR against `new-pr`, title `Add
org.orcshot.Orcshot`, first comment `bot, build`. The branch holds the generated manifest for
`v0.4.0` and `flathub-lint-exceptions.json`. direflail forks and opens it; the description is
drafted here and answers the three questions a reviewer will ask before they ask:

1. **`--own-name=org.x.StatusIcon.orcshot`** — libxapp can only register a tray icon under the
   `org.x.StatusIcon.*` prefix (Cinnamon's monitor applet discovers icons by it; read in
   `xapp-status-icon.c`). Warpinator carries the identical line on Flathub as the linter's only
   StatusIcon exception. Requesting the same. If refused, the line goes and Flatpak-on-Cinnamon
   has no tray icon — the state before #208 — and nothing else changes.
2. **`--talk-name=org.gnome.Shell` cannot be narrowed** — clipboard and window capture call
   custom interfaces on that same bus name, and Flatpak filters by bus name only (#194's
   finding, 2026-09-04). The extension itself is installed through
   `org.gnome.Shell.Extensions.InstallRemoteExtension`, never a filesystem grant (#205).
3. **`--filesystem=xdg-pictures:create`** — Save's default folder; Save As and any other folder
   go through the file-chooser portal (#210).

### 4.5 Merge precondition (decision 6)

The submission PR is merged only when EGO lists `orcshot@orcshot.org` and a released tag's
`EGO_URL` points at it. If reviewers approve first, the PR waits with a comment saying why;
nobody merges it to finish the task. After the merge: accept the write invitation to
`flathub/org.orcshot.Orcshot` within a week, install the published build on the Mint host
(Flathub is Mint's home channel), first-run and one capture.

## 5. Shared: `RELEASING.md`, `channels.yaml`, #197

**`RELEASING.md`** gains two steps at the positions the ingredients specify, renumbered as
contiguous integers (`/orc-release`'s parser drops a `6a`):

- *Upload the snap to the Snap Store (beta)* — after "Confirm CI is green on the just-pushed
  commit" (it downloads that run's artifact) and before "Publish the GitHub Release".
- *Update Flathub* — after "Commit, tag, push" (the tag must exist) and before "Publish the
  GitHub Release".

Each carries a `**One-time setup:**` block whose checks `/orc-release` runs every release and
whose setup it never performs: snap — `snapcraft whoami` (redacted), `snapcraft names`, the
`dbus` declaration (`snap info orcshot` shows a channel map), the store listing done in the
dashboard; Flathub — appstream API 200, collaborator permission `write`, 2FA on. The 13-step
checklist becomes 15.

**`channels.yaml`**: the two placeholder leaves are replaced by the real ones from §2.4 and §4.3.

**#197** for these two channels is answered by those blocks: snap = the keyring login from
`snapcraft login`, expiring yearly; Flathub = a GitHub account with 2FA and write access to the
app repo. Nothing else is per-machine. #197 stays open for its PPA half and says so.

## 6. Verification and the record

- **Snap:** `review-tools` output before each upload; `snap info orcshot` after the grant; the
  clean-VM `snap install --beta` in §2.5 step 5.
- **Flathub:** the bot's test build from the submission PR installed with `flatpak install
  --user <link>` on the Mint host, first-run and one capture through it; after merge, the
  appstream API lists 0.4.0.
- **`VERIFICATION.md`:** one scenario per channel — install from the store, first-run, one
  capture — with the real results.
- **`BACKLOG.md`:** #214 and #219 resolved on the Snap track's branch; #198 and #197's
  snap/flatpak halves resolved when the Flathub merge lands, with what actually happened
  (review turnaround, what the ingredients got wrong — the CI-artifact `prepare:`, the derived
  manifest, anything the reviewers asked that the drafts did not cover). Those deltas are one
  entry's worth of input for Orclab #33.
- **Tests:** `scripts/flathub-manifest.py` has its one unit test. Nothing else here is code.

## Open questions resolved during brainstorming (for the record)

- Local `snapcraft pack` vs. CI artifact → CI artifact, with local build as the written fallback
  (decision 2; LXD/Multipass explained as the throwaway build environment snapcraft would need).
- Whether the snap works on Mint regardless → yes; Mint's `nosnap.pref` blocks snapd for every
  snap, and Flathub/PPA are Mint's channels. Audience fact, not a build fact.
- Gate on EGO or not → decision 6.
