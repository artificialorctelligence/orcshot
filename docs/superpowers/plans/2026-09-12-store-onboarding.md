# Snap Store and Flathub Onboarding Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Get Orcshot's already-green snap and Flatpak in front of users: a `dbus`-declared snap on the Snap Store `beta` channel and an accepted Flathub listing, both driven from `RELEASING.md` steps that `/orc-release` runs every release.

**Architecture:** Two independent tracks around one normal release. The Snap track fixes the two defects in front of a store upload (#214 SVG loader, #219 store icon), applies Orclab's `snap` ingredient and reshapes it to upload the CI-built artifact, then obtains the `dbus` declaration with a held (unreleased) upload. The 0.4.0 release is the first released revision. The Flathub track adds `scripts/flathub-manifest.py` (derives a tag-pinned manifest from the repo one), applies the `flatpak` ingredient, and opens the submission PR against `v0.4.0`; merge waits on extensions.gnome.org.

**Tech Stack:** snapcraft 9 + `review-tools` (snaps), `gh` CLI (artifact download, Flathub PRs), `flatpak-builder-lint` via `org.flatpak.Builder`, Python 3 + PyYAML (host 6.0.1) for the manifest script, pytest. Spec: `docs/superpowers/specs/2026-09-12-store-onboarding-design.md`.

## Global Constraints

- Every irreversible, externally visible action is direflail's to run: `snapcraft upload`, the forum post, `/orc-package`, opening and merging Flathub PRs. The task prepares the exact content and hands it over; it never runs these. (Spec decision 7.)
- No icon/logo/visual mark changes without direflail choosing it from real candidates shown first. (§2.2.)
- The uploaded snap is the CI artifact from `snap.yml` (`orcshot-snap`), never a local `snapcraft pack`. (Decision 2.)
- The repo manifest `org.orcshot.Orcshot.yaml` keeps `type: dir, path: .` for the `orcshot` module. (Decision 5.)
- Nothing public before EGO lists `orcshot@orcshot.org`: no snap `stable`, no Flathub merge. (Decision 6.)
- `RELEASING.md` steps are contiguous integers; `**One-time setup:**` and `**Run:**` markers verbatim (`/orc-release` parses them). Ingredient positions: snap step after "Confirm CI is green", Flathub step after "Commit, tag, push", both before "Publish the GitHub Release".
- Secrets never reach the transcript: `snapcraft whoami` piped through `sed 's/\(email:\).*/\1 <redacted>/'`; no password files printed.
- Live-verify on the real VM (`"Ubuntu 26.04"`, user `ubuntu2604`, key `~/.ssh/orcshot_dev_vm`, `NOPASSWD` sudo) before claiming a snap fix works. Re-run `VBoxManage list vms` first.
- Backlog entries are edited per `backlog-discipline` (layered resolution notes, never renumbered).
- Commits end with `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`.

---

## Track 1 — Snap (branch `store-onboarding-snap`)

Create the branch from `main` before Task 1: `git checkout -b store-onboarding-snap`.

### Task 1: #214 — the snap's SVG loader

**Files:**
- Modify: `snapcraft.yaml:120-132` (the `orcshot` part's `stage-packages`)
- Modify: `.github/workflows/snap.yml` (verify job, after "Confirm the installed binary launches without crashing")
- Modify: `BACKLOG.md` (#214 entry at line ~1878)

**Interfaces:**
- Produces: a `main`-mergeable `snapcraft.yaml` whose CI artifact starts without `g_module_open() failed`. Task 3's artifact download and Task 4's `review-tools` run consume the artifact of this branch's green run.

- [ ] **Step 1: Reproduce and confirm the mechanism on the VM (do not skip — the entry's mechanism is a hypothesis)**

Get the latest `main` snap artifact onto the VM and install it:

```bash
RUN=$(gh run list --workflow=snap.yml --branch main --status success --limit 1 --json databaseId --jq '.[0].databaseId')
gh run download "$RUN" --name orcshot-snap --dir /tmp/claude-1000/-home-direflail-projects-orcshot/2e5f3efb-7792-45a4-af07-d216aa853059/scratchpad/snap214
scp -i ~/.ssh/orcshot_dev_vm /tmp/claude-1000/-home-direflail-projects-orcshot/2e5f3efb-7792-45a4-af07-d216aa853059/scratchpad/snap214/orcshot_*.snap ubuntu2604@<vm-ip>:/tmp/
ssh -i ~/.ssh/orcshot_dev_vm ubuntu2604@<vm-ip> 'sudo snap install --dangerous /tmp/orcshot_*.snap'
```

Then inside the confined shell, find both librsvg copies and the loader's unresolved symbol:

```bash
ssh -i ~/.ssh/orcshot_dev_vm ubuntu2604@<vm-ip> 'snap run --shell orcshot -c "
  loader=\$(find \$SNAP/gnome-platform \$SNAP/usr -name libpixbufloader_svg.so 2>/dev/null); echo LOADER \$loader;
  ldd \$loader | grep rsvg;
  for l in \$(find \$SNAP/usr/lib \$SNAP/gnome-platform/usr/lib -name \"librsvg-2.so.2*\" 2>/dev/null); do echo == \$l; nm -D \$l | grep -c rsvg_handle_get_pixbuf_and_error; done;
  ls \$SNAP/gnome-platform/usr/lib/x86_64-linux-gnu/girepository-1.0/ | grep -i rsvg;
  ls \$SNAP/usr/lib/x86_64-linux-gnu/girepository-1.0/ 2>/dev/null | grep -i rsvg"'
```

Expected: `ldd` resolves `librsvg-2.so.2` to the **staged** copy under `$SNAP/usr/lib`, whose `nm` count is `0`; the platform copy's count is `1`; and `Rsvg-2.0.typelib` is present under `gnome-platform`. If the typelib is **not** in the platform snap, stop and re-plan: the fix below would break Insert SVG (`ui/render.py:66` needs `Rsvg` via GI), and the alternative is pinning the platform content snap's track — record what was found in #214 and ask direflail before continuing.

Also record what the loader failure actually breaks: launch `orcshot` in the VM's GUI session (see the VM registry memory for the xdotool method), open the editor on a capture, and note whether toolbar icons render and whether Insert SVG works.

- [ ] **Step 2: Remove the staged librsvg**

In `snapcraft.yaml`, delete the `- gir1.2-rsvg-2.0` line from the `orcshot` part's `stage-packages` and add, in its place, a comment in the file's existing style:

```yaml
      # BACKLOG #214: no gir1.2-rsvg-2.0 here. It staged core24's librsvg2-2, which the
      # gnome extension's platform snap's own (newer) libpixbufloader_svg.so then resolved
      # first and failed on (undefined symbol rsvg_handle_get_pixbuf_and_error). The
      # platform snap ships librsvg and Rsvg-2.0.typelib itself (verified on the 26.04 VM).
```

Check whether `gir1.2-rsvg-2.0` also appears in the part's `build-packages`; if it does, leave it — build-packages do not enter the snap.

- [ ] **Step 3: Add the CI regression guard**

In `.github/workflows/snap.yml`'s verify job, after the "Confirm the installed binary launches without crashing" step:

```yaml
      - name: "Assert no GdkPixbuf loader fails to load under confinement (BACKLOG #214)"
        run: |
          # A staged library older than the platform snap's loader shows up here as
          # `g_module_open() failed for .../libpixbufloader_*.so: undefined symbol ...`.
          out=$(snap run --shell orcshot -c "python3 -c 'import gi; gi.require_version(\"GdkPixbuf\", \"2.0\"); from gi.repository import GdkPixbuf; print([f.get_name() for f in GdkPixbuf.Pixbuf.get_formats()])'" 2>&1)
          echo "$out"
          ! echo "$out" | grep -q 'g_module_open() failed'
          echo "$out" | grep -q "'svg'"
```

- [ ] **Step 4: Push, wait for CI, verify on the VM**

```bash
git add snapcraft.yaml .github/workflows/snap.yml
git commit -m "BACKLOG #214: stop staging librsvg in the snap; the platform snap's loader needs its own

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
git push -u origin store-onboarding-snap
gh run watch $(gh run list --workflow=snap.yml --branch store-onboarding-snap --limit 1 --json databaseId --jq '.[0].databaseId')
```

Expected: both snap jobs `success`, the new step printing a format list containing `'svg'`. Then download this run's artifact, install it on the VM as in Step 1, and confirm: `journalctl --user -b | grep g_module_open` is empty after a launch; toolbar icons render; Insert SVG renders a test SVG. Keep the downloaded `.snap` — Task 4 uses this branch's final artifact.

- [ ] **Step 5: Resolve #214 in BACKLOG.md**

Append to the #214 entry (do not rewrite the original text) a `**Resolved 2026-09-XX:**` paragraph with: the confirmed mechanism from Step 1 (staged vs. platform copy, `nm` counts), what the breakage actually looked like in the UI, the fix (dropped stage package, CI guard step name), and the VM verification. Change the heading to `## #214: ... (RESOLVED 2026-09-XX)`.

```bash
git add BACKLOG.md
git commit -m "Resolve BACKLOG #214: snap SVG loader loads again once the staged librsvg is gone

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

### Task 2: #219 — the store icon

**Files:**
- Create: `snap/gui/icon.svg` **or** `snap/gui/icon.png` (direflail's choice)
- Modify: `snapcraft.yaml` (top-level `icon:` after `grade:` at line 4)
- Modify: `.github/workflows/snap.yml` (verify job)
- Modify: `BACKLOG.md` (#219 at line ~2094; #217's note about `icon:` at line ~2013 stays as is)

**Interfaces:**
- Produces: the built snap carries `meta/gui/icon.<ext>`; the launcher `Icon=` now points at it (snapcraft rewrites the desktop file when `icon:` is set — #219's coupling note), and #217's existing CI assertion must still pass.

- [ ] **Step 1: Check what the store accepts, live**

Per `currency-discipline`, read the current snapcraft reference for the top-level `icon` key (`https://documentation.ubuntu.com/snapcraft/stable/reference/project-file/snapcraft-yaml/` — search for `icon`) and confirm: accepted formats (PNG, SVG), size limits ("between 40x40 and 512x512 pixels, 256x256 recommended, < 256 KB" per #219's read of `models/project.py`), and where snapcraft looks for it (`snap/gui/icon.*` is picked up automatically; `icon:` overrides). Note the date and URL in the commit message.

- [ ] **Step 2: Produce the candidates in the scratchpad**

Candidate (a), the Flatpak's square wrapper, from the same code the manifest runs (`org.orcshot.Orcshot.yaml:183-200`):

```bash
cd /home/direflail/projects/orcshot
python3 - <<'PYEOF'
import base64, struct
S="/tmp/claude-1000/-home-direflail-projects-orcshot/2e5f3efb-7792-45a4-af07-d216aa853059/scratchpad/icon219"
import os; os.makedirs(S, exist_ok=True)
data_bytes = open("src/orcshot/resources/orcshot.png","rb").read()
w, h = struct.unpack(">II", data_bytes[16:24])
data = base64.b64encode(data_bytes).decode("ascii")
size = max(w, h); x = (size - w)//2; y = (size - h)//2
svg = (f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
       f'viewBox="0 0 {size} {size}" width="{size}" height="{size}">'
       f'<image x="{x}" y="{y}" width="{w}" height="{h}" xlink:href="data:image/png;base64,{data}"/></svg>')
open(f"{S}/candidate-a.svg","w").write(svg)
PYEOF
```

Candidate (b), a padded 256×256 PNG, via GdkPixbuf on the host (no new dependency):

```bash
python3 - <<'PYEOF'
import gi; gi.require_version("GdkPixbuf","2.0"); from gi.repository import GdkPixbuf
S="/tmp/claude-1000/-home-direflail-projects-orcshot/2e5f3efb-7792-45a4-af07-d216aa853059/scratchpad/icon219"
src = GdkPixbuf.Pixbuf.new_from_file("src/orcshot/resources/orcshot.png")
side = 256; scale = side / max(src.get_width(), src.get_height())
w, h = round(src.get_width()*scale), round(src.get_height()*scale)
scaled = src.scale_simple(w, h, GdkPixbuf.InterpType.HYPER)
canvas = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, True, 8, side, side); canvas.fill(0x00000000)
scaled.copy_area(0, 0, w, h, canvas, (side-w)//2, (side-h)//2)
canvas.savev(f"{S}/candidate-b.png", "png", [], [])
PYEOF
```

Render both onto a mock of the snapcraft.io listing card (a small HTML file in the scratchpad with the store's white card, the icon at 128 px beside "orcshot", and the launcher size at 48 px), screenshot it, and send the screenshot with `SendUserFile`, naming (c) "no icon: — dashboard only" as the third option. Ask direflail which one. **Do not proceed until they answer.**

- [ ] **Step 3: Commit the chosen asset and set `icon:`**

```bash
mkdir -p snap/gui
cp <scratchpad>/candidate-<a|b>.<svg|png> snap/gui/icon.<svg|png>
```

In `snapcraft.yaml`, after `grade: stable`:

```yaml
# BACKLOG #219: the Snap Store listing icon (meta/gui/icon.*). Same mark as every other
# channel; direflail chose <a: the Flatpak's square wrapper | b: a padded 256x256 raster>
# on 2026-09-XX. snapcraft also rewrites the launcher desktop file's Icon= to this file,
# superseding #217's sed; #217's CI assertion still holds and proves it.
icon: snap/gui/icon.<svg|png>
```

If (c) was chosen: no file, no `icon:` line; append a `**Decided 2026-09-XX:**` note to #219 saying the store icon is set in the dashboard, and skip Step 4's assertion.

- [ ] **Step 4: CI assertion that the icon is in the package**

In `snap.yml`'s verify job, after the #217 assertion:

```yaml
      - name: "Assert the store icon is packed (BACKLOG #219)"
        run: unsquashfs -l ./orcshot_*.snap | grep -E '^squashfs-root/meta/gui/icon\.(svg|png)$'
```

- [ ] **Step 5: Push, watch CI, check the launcher on the VM**

```bash
git add snap/gui snapcraft.yaml .github/workflows/snap.yml
git commit -m "BACKLOG #219: Snap Store listing icon, chosen by direflail (source: <URL from Step 1>, read 2026-09-XX)

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
git push
gh run watch $(gh run list --workflow=snap.yml --branch store-onboarding-snap --limit 1 --json databaseId --jq '.[0].databaseId')
```

Expected: `success`; the #217 and #219 assertions both pass. Install this artifact on the VM and confirm the app grid shows the icon (`gnome-shell` app grid screenshot via the xdotool method). Resolve #219 in `BACKLOG.md` the same way as #214 (heading + appended resolution paragraph naming the choice and why), commit.

### Task 3: Apply the snap ingredient and reshape it to the CI artifact

**Files:**
- Modify: `.orclab/publish/channels.yaml` (the `snap:` leaf under `desktop.python.linux`)
- Modify: `RELEASING.md` (new step after "11. Confirm CI is green"; "1. Pick a version" gains the metainfo reminder; renumbering)
- Modify: `BACKLOG.md` (#198 progress note)

**Interfaces:**
- Consumes: Orclab's shipped `snap` ingredient via `/orc-package snap` — **direflail types it**; the command asks for inputs and writes the recipe. Inputs to give: snap `orcshot`, publisher `artificialorctelligence`, first channel `beta`, architecture `amd64`, parent `desktop.python.linux.snap`.
- Produces: the leaf `desktop.python.linux.snap` with `prepare:`/`artifact:`/`action:` that Task 4 and the 0.4.0 release run through `/orc-publish desktop.python.linux.snap`.

- [ ] **Step 1: direflail runs `/orc-package snap`**

Ask them to type it and give the inputs above. Its checks should report: `snapcraft whoami` satisfied (redacted), `snapcraft names` lists `orcshot`, the `dbus` declaration not yet done, the store listing not yet done. Review what it wrote (`git diff`) before touching it. If the command refuses because the existing placeholder `snap:` leaf is "already present", delete the placeholder leaf first (keep its EGO sentence for Step 2) and re-run.

- [ ] **Step 2: Reshape the leaf to download the CI artifact**

Replace the written leaf's `prepare:` and `artifact:` with:

```yaml
      snap:
        # BACKLOG #198, spec 2026-09-12 decision 2: the uploaded snap is the CI-built artifact
        # for HEAD's commit - the binary the VM tests ran on, traceable to a run - never a local
        # `snapcraft pack`. If no successful snap.yml run exists for HEAD this fails with that
        # message, which is the "CI is green" gate in executable form.
        prepare: >-
          RUN=$(gh run list --workflow=snap.yml --commit "$(git rev-parse HEAD)" --status success --json databaseId --jq '.[0].databaseId');
          test -n "$RUN" || { echo "no successful snap.yml run for $(git rev-parse HEAD) - push and wait for CI first"; exit 1; };
          rm -rf dist/snap && gh run download "$RUN" --name orcshot-snap --dir dist/snap
        artifact: "dist/snap/orcshot_$(grep -m1 '^version' pyproject.toml | sed -E 's/^version *= *\"([^\"]+)\"/\\1/')_amd64.snap"
        preflight: [no-vcs, no-tool-state]
        action: "snapcraft upload --release=beta dist/snap/orcshot_$(grep -m1 '^version' pyproject.toml | sed -E 's/^version *= *\"([^\"]+)\"/\\1/')_amd64.snap"
        confirm:
          url: "https://snapcraft.io/orcshot"
        metrics: "snapcraft metrics orcshot --format=json --name weekly_installed_base_by_operating_system"
        requirements:
          - "Run review-tools on the downloaded artifact first (RELEASING.md's step shows the
             command). Any `human review required` line other than none is a store hold."
          - "`snapcraft whoami` must succeed on this machine (login done 2026-09-11, expires 2027-09-11)."
          - "The dbus slot declaration must already be granted (BACKLOG #198, forum request from
             the held first upload); until it is, an upload is held and never reaches beta."
          - "First release goes to beta, never straight to stable. Promote with
             `snapcraft release orcshot <revision> stable` only after one real
             `snap install --beta orcshot` on a clean machine AND extensions.gnome.org lists
             orcshot@orcshot.org (spec 2026-09-12 decision 6)."
          - "Until EGO lists the extension, the snap's GNOME-Wayland features run on the portal
             fallback; first-run sends the user to extensions.gnome.org (spec 2026-09-11 §4)."
        issues:
          - "Fallback if the CI artifact has expired (90 days) or GitHub is unreachable:
             `snapcraft pack` locally (needs LXD or Multipass once) and upload that file, noting
             in the release that the uploaded binary is not the VM-tested one."
          - "Only amd64 is built and published; the snap is invisible to arm64 users."
```

Keep every other key the ingredient wrote unless it contradicts the above. `dist/` is gitignored already.

- [ ] **Step 3: Dry-run it**

```bash
# via the user's /orc-publish, or directly if the skill exposes a dry run:
/orc-publish desktop.python.linux.snap --dry-run
```

Expected: the plan shows prepare → inspect → action, reports "will be inspected after prepare", and does not run anything. If the current branch's HEAD has a green run, a non-dry `prepare` alone may be exercised by running the `prepare:` command by hand in a shell and checking `dist/snap/orcshot_0.3.0_amd64.snap` appears.

- [ ] **Step 4: Fix up the RELEASING.md step and the version reminder**

The ingredient inserted a step after "Confirm CI is green". Edit it to this exact text (keeping its number), then renumber every later step so they are contiguous:

```markdown
## 12. Upload the snap to the Snap Store (beta)

**One-time setup:** three things, once per snap, all yours to do:
- Store login and name registration: check with `snapcraft whoami | sed 's/\(email:\).*/\1 <redacted>/'`
  and `snapcraft names`. If missing: `snapcraft login`, then `snapcraft register orcshot`.
  Both done 2026-09-11; the login expires 2027-09-11.
- The `dbus` slot declaration for `org.orcshot.Orcshot`: the first upload was held with
  `human review required due to 'deny-connection' constraint` and a request posted in the
  snapcraft forum's `store-requests` category (BACKLOG #198). Check: `snapcraft status orcshot`
  lists no held revision, or `snap info orcshot` shows a channel map.
- The store listing (screenshots, category, description) is set in the snapcraft.io dashboard
  (`https://snapcraft.io/orcshot/listing`); the icon comes from `snapcraft.yaml`'s `icon:` (#219).

**Preconditions:** step 11 is green for this commit - this step downloads that run's artifact.

**Run:** /orc-publish desktop.python.linux.snap

Before confirming the real run, put the store's own reviewer on the file it just downloaded:

```bash
cp dist/snap/orcshot_*.snap ~/snap/review-tools/common/ && review-tools.snap-review ~/snap/review-tools/common/orcshot_*.snap
```

(`sudo snap install review-tools` once.) Expected: no `human review required` lines. Confirm the
publish with `snap info orcshot`: the new version is on `beta`. Promote to `stable` only after
one real `snap install --beta orcshot` on a clean machine, and only once extensions.gnome.org
lists `orcshot@orcshot.org` (spec 2026-09-12 decision 6). Fallback if the artifact is gone:
`snapcraft pack` locally (LXD/Multipass) and upload that, noting it is not the VM-tested binary.
```

In "## 1. Pick a version", add one line: "Also add a `<release version="X.Y.Z" date="...">` entry at the top of `org.orcshot.Orcshot.metainfo.xml`'s `<releases>` - Flathub's linter fails a metainfo whose newest release is not the built version. (0.3.0 was never added; add it alongside 0.4.0.)"

Verify the numbering: `grep -n '^## [0-9]' RELEASING.md` prints 1..14 contiguous, and the step count referenced anywhere else in the file (step 9 → 10 references etc.) is updated — grep for `step 1[0-9]` and `step [0-9]` mentions and fix each.

- [ ] **Step 5: Update #198, commit, open the PR**

Append to #198 an `**Update 2026-09-XX - Snap track (branch store-onboarding-snap):**` paragraph: #214 and #219 resolved on this branch, ingredient applied, the CI-artifact reshape and why (decision 2), what the ingredient got wrong for Orcshot (to carry to Orclab #33: `prepare:` assumed a local pack; the RELEASING step's review-tools command needs the copy into `~/snap/review-tools/common/`).

```bash
git add .orclab/publish/channels.yaml RELEASING.md BACKLOG.md
git commit -m "BACKLOG #198: Snap Store leaf and RELEASING step, uploading the CI artifact (/orc-package snap, reshaped)

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
git push
gh pr create --title "Snap Store onboarding: #214 SVG loader, #219 store icon, Snap Store release step (#198)" --body "$(cat <<'EOF'
Track 1 of docs/superpowers/specs/2026-09-12-store-onboarding-design.md.

- #214: the snap no longer stages librsvg; the platform snap's SVG loader loads (CI guard added, VM-verified).
- #219: Snap Store listing icon chosen by direflail; `icon:` set; CI asserts meta/gui/icon.* is packed.
- #198: `desktop.python.linux.snap` leaf uploads the CI-built artifact for HEAD; RELEASING.md step 12 with its one-time setup; steps renumbered to 14.

No upload has happened. The held first upload and the dbus forum request follow on main (Task 4).

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

Wait for CI on the PR (all workflows), ask direflail to merge.

### Task 4: The held upload and the `dbus` declaration (on `main`, after the PR merges)

**Files:**
- Modify: `VERIFICATION.md` (one new scenario, results filled in during the 0.4.0 release)
- Modify: `BACKLOG.md` (#198 note)

**Interfaces:**
- Consumes: the merged leaf; the `snap.yml` run for `main`'s merge commit.
- Produces: a granted `dbus` declaration, so the 0.4.0 release's `snapcraft upload --release=beta` is not held.

- [ ] **Step 1: Download main's artifact and run review-tools**

```bash
git checkout main && git pull
RUN=$(gh run list --workflow=snap.yml --commit "$(git rev-parse HEAD)" --status success --json databaseId --jq '.[0].databaseId'); test -n "$RUN"
rm -rf dist/snap && gh run download "$RUN" --name orcshot-snap --dir dist/snap
snap list review-tools >/dev/null 2>&1 || echo "direflail: sudo snap install review-tools"
cp dist/snap/orcshot_*.snap ~/snap/review-tools/common/ && review-tools.snap-review ~/snap/review-tools/common/orcshot_*.snap
```

Expected: exactly one `human review required` line, for the `dbus` slot's `deny-connection` constraint. Any other finding is a defect: fix it on a new branch first (it would hold the store upload too).

- [ ] **Step 2: direflail uploads without releasing**

Hand over the exact command; they run it in their own terminal:

```bash
snapcraft upload dist/snap/orcshot_0.3.0_amd64.snap
```

Expected output mentions the revision number and that it is held for manual review. Record the revision number.

- [ ] **Step 3: Draft the forum post; direflail posts it**

Category: `store-requests` on `https://forum.snapcraft.io`. Title: `dbus slot declaration request for orcshot (org.orcshot.Orcshot)`. Body to hand over verbatim:

> Orcshot (snap `orcshot`, revision N, strict confinement) is a screenshot capture and annotation app. It owns the session bus name `org.orcshot.Orcshot` via a `dbus` slot for two things: single-instance activation (a second launch hands its arguments to the running instance) and exporting its tray menu actions over `org.gtk.Actions`. Its GNOME Shell extension, distributed separately on extensions.gnome.org, calls methods on that name; the snap itself exports nothing beyond its own app-id name and requests no `personal-files` or other privileged interface. Requesting the slot declaration so uploads pass automated review. Source: https://github.com/artificialorctelligence/orcshot (snapcraft.yaml at the repo root).

Ask direflail to post it and paste back the thread URL; note the URL and date in #198.

- [ ] **Step 4: Confirm the grant, record**

When the reviewer replies granted: `snapcraft status orcshot` (or the store dashboard) shows the held revision as approved/unreleased. Add to `VERIFICATION.md` a scenario **"Snap Store: install from beta on a clean 26.04 VM"** — steps: `snap install --beta orcshot`, first-run dialog, one capture, `journalctl --user -b | grep g_module_open` empty — with a result line reading "pending: first released revision is the 0.4.0 release". Append to #198: upload date, revision, forum URL, grant date, turnaround.

```bash
git add VERIFICATION.md BACKLOG.md
git commit -m "BACKLOG #198: dbus slot declaration granted for orcshot; first released revision is 0.4.0

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
git push
```

---

## Checkpoint — the 0.4.0 release (not a task; direflail's `/orc-release` run)

The normal `RELEASING.md` run, now 14 steps. What this plan expects from it:

- Step 1 adds the 0.3.0 and 0.4.0 `<release>` entries to the metainfo (Task 3 Step 4's reminder).
- `EGO_URL` in `src/orcshot/ui/extension_install.py` is pointed at the real listing **only if** EGO has accepted by then; otherwise it stays.
- Step 12 is the first `snapcraft upload --release=beta`; `snap info orcshot` shows `beta`. Then the clean-VM `snap install --beta orcshot` from `VERIFICATION.md`'s new scenario, results filled in (this closes #214's proof).
- `git tag v0.4.0` on origin is Track 2's starting condition.

---

## Track 2 — Flathub (branch `store-onboarding-flathub`, after `v0.4.0` exists)

`git checkout main && git pull && git checkout -b store-onboarding-flathub`.

### Task 5: `scripts/flathub-manifest.py`

**Files:**
- Create: `scripts/flathub-manifest.py`
- Create: `tests/unit/test_flathub_manifest.py`
- Test fixture: none on disk — the test builds a small manifest string.

**Interfaces:**
- Produces: `python3 scripts/flathub-manifest.py <tag> [--manifest org.orcshot.Orcshot.yaml] [--repo .]` → the derived manifest on stdout; exit 2 with a message on a missing tag, a missing PyYAML, or a manifest that does not have exactly one module named `orcshot` with exactly one `type: dir` source. Task 6's leaf and Task 7's submission both call it.
- Function for the test: `derive(manifest_text: str, tag: str, commit: str) -> str`.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_flathub_manifest.py
"""scripts/flathub-manifest.py: the Flathub manifest is derived from the repo one by
swapping exactly one source block (spec 2026-09-12 decision 5)."""
import importlib.util
import pathlib

import pytest
import yaml

SCRIPT = pathlib.Path(__file__).resolve().parents[2] / "scripts" / "flathub-manifest.py"
spec = importlib.util.spec_from_file_location("flathub_manifest", SCRIPT)
fm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fm)

MANIFEST = """\
app-id: org.orcshot.Orcshot
runtime: org.gnome.Platform
runtime-version: '50'
finish-args:
  - --share=ipc
modules:
  - name: xapps
    buildsystem: meson
    sources:
      - type: git
        url: https://github.com/linuxmint/xapp.git
        tag: "3.2.2"
        commit: 913b2a2b441ec24daf3aa92e2863cc40e1c43650
  - name: orcshot
    buildsystem: simple
    build-commands:
      - pip3 install --prefix=/app .
    sources:
      - type: dir
        path: .
"""

TAG = "v0.4.0"
COMMIT = "0123456789abcdef0123456789abcdef01234567"


def test_only_the_orcshot_source_changes():
    out = yaml.safe_load(fm.derive(MANIFEST, TAG, COMMIT))
    src = yaml.safe_load(MANIFEST)
    assert out["modules"][0] == src["modules"][0]          # xapps untouched
    orc_out, orc_src = out["modules"][1], src["modules"][1]
    assert orc_out["sources"] == [{
        "type": "git",
        "url": "https://github.com/artificialorctelligence/orcshot.git",
        "tag": TAG,
        "commit": COMMIT,
    }]
    orc_out.pop("sources"); orc_src.pop("sources")
    assert orc_out == orc_src                                # every other key of the module intact
    for key in ("app-id", "runtime", "runtime-version", "finish-args"):
        assert out[key] == src[key]


def test_refuses_a_manifest_without_exactly_one_dir_source():
    two_dirs = MANIFEST + "      - type: dir\n        path: ./again\n"
    with pytest.raises(fm.ManifestShapeError):
        fm.derive(two_dirs, TAG, COMMIT)
    no_orcshot = MANIFEST.replace("name: orcshot", "name: other")
    with pytest.raises(fm.ManifestShapeError):
        fm.derive(no_orcshot, TAG, COMMIT)
```

- [ ] **Step 2: Run it, confirm it fails**

Run: `.venv/bin/python -m pytest tests/unit/test_flathub_manifest.py -v`
Expected: FAIL at import — `scripts/flathub-manifest.py` does not exist. The venv has no PyYAML (checked 2026-09-13): add `"pyyaml>=6.0"` to `[project.optional-dependencies] dev` in `pyproject.toml` and `.venv/bin/pip install -e '.[dev]'`. Dev-only — the runtime app never imports it.

- [ ] **Step 3: Write the script**

```python
#!/usr/bin/env python3
"""Derive the Flathub manifest from the repo manifest.

Flathub builds from a tag+commit of the upstream repo; the repo's own
org.orcshot.Orcshot.yaml builds the working tree (type: dir) so local and CI
builds test what a PR changes. This swaps exactly that one source block and
nothing else (spec 2026-09-12 decision 5). Output goes to stdout.

    scripts/flathub-manifest.py v0.4.0 > /path/to/flathub/org.orcshot.Orcshot.yaml
"""
import argparse
import subprocess
import sys

try:
    import yaml
except ImportError:  # not a project dependency; say so instead of regex-editing YAML
    sys.exit("flathub-manifest.py needs PyYAML (python3-yaml / pip install pyyaml)")

UPSTREAM = "https://github.com/artificialorctelligence/orcshot.git"
MODULE = "orcshot"


class ManifestShapeError(ValueError):
    """The manifest is not the one shape this script knows how to rewrite."""


def derive(manifest_text: str, tag: str, commit: str) -> str:
    doc = yaml.safe_load(manifest_text)
    modules = [m for m in doc.get("modules", []) if isinstance(m, dict) and m.get("name") == MODULE]
    if len(modules) != 1:
        raise ManifestShapeError(f"expected exactly one module named {MODULE!r}, found {len(modules)}")
    dirs = [s for s in modules[0].get("sources", []) if isinstance(s, dict) and s.get("type") == "dir"]
    if len(dirs) != 1:
        raise ManifestShapeError(f"expected exactly one 'type: dir' source in {MODULE!r}, found {len(dirs)}")
    dirs[0].clear()
    dirs[0].update({"type": "git", "url": UPSTREAM, "tag": tag, "commit": commit})
    return yaml.safe_dump(doc, sort_keys=False, allow_unicode=True, width=1000)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("tag")
    ap.add_argument("--manifest", default="org.orcshot.Orcshot.yaml")
    ap.add_argument("--repo", default=".")
    a = ap.parse_args()
    try:
        commit = subprocess.check_output(["git", "-C", a.repo, "rev-list", "-n1", a.tag], text=True).strip()
    except subprocess.CalledProcessError:
        sys.exit(f"tag {a.tag!r} not found in {a.repo} - push/fetch the release tag first")
    with open(a.manifest, encoding="utf-8") as f:
        text = f.read()
    try:
        sys.stdout.write(derive(text, a.tag, commit))
    except ManifestShapeError as e:
        sys.exit(f"{a.manifest}: {e}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

`chmod +x scripts/flathub-manifest.py`.

Note: `yaml.safe_dump` drops the repo manifest's comments. That is acceptable for the Flathub copy — the comments document build decisions for this repo, and the Flathub repo's file points back here — but say so in the script's docstring (add one line: "Comments do not survive; the repo manifest remains the documented one.").

- [ ] **Step 4: Run the tests, then the real thing**

Run: `.venv/bin/python -m pytest tests/unit/test_flathub_manifest.py -v`
Expected: 2 passed.

Then against the real manifest and tag, and lint the result the way Flathub will:

```bash
scripts/flathub-manifest.py v0.4.0 > /tmp/claude-1000/-home-direflail-projects-orcshot/2e5f3efb-7792-45a4-af07-d216aa853059/scratchpad/org.orcshot.Orcshot.yaml
cp flathub-lint-exceptions.json /tmp/claude-1000/-home-direflail-projects-orcshot/2e5f3efb-7792-45a4-af07-d216aa853059/scratchpad/
cd /tmp/claude-1000/-home-direflail-projects-orcshot/2e5f3efb-7792-45a4-af07-d216aa853059/scratchpad && flatpak run --command=flatpak-builder-lint org.flatpak.Builder --user-exceptions flathub-lint-exceptions.json manifest org.orcshot.Orcshot.yaml
```

Expected: exit 0 (the one accepted exception only). Also `diff <(yaml-normalised repo manifest) <(derived)` mentally: only the source block differs — `python3 -c 'import yaml,sys; a=yaml.safe_load(open("org.orcshot.Orcshot.yaml")); b=yaml.safe_load(open(sys.argv[1])); a["modules"][-1]["sources"]=b["modules"][-1]["sources"]; print(a==b)' <derived>` prints `True`.

- [ ] **Step 5: Commit**

```bash
git add scripts/flathub-manifest.py tests/unit/test_flathub_manifest.py pyproject.toml
git commit -m "scripts/flathub-manifest.py: derive the tag-pinned Flathub manifest from the repo one (#198)

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

### Task 6: Apply the flatpak ingredient and reshape it

**Files:**
- Modify: `.orclab/publish/channels.yaml` (the `flatpak:` leaf)
- Modify: `RELEASING.md` (new step after "Commit, tag, push"; renumbering to 15)
- Modify: `BACKLOG.md` (#198 note)

**Interfaces:**
- Consumes: `/orc-package flatpak` — **direflail types it**. Inputs: app id `org.orcshot.Orcshot`, manifest `org.orcshot.Orcshot.yaml`, GitHub user `artificialorctelligence`, upstream `github.com/artificialorctelligence/orcshot`, parent `desktop.python.linux.flatpak`.
- Produces: leaf `desktop.python.linux.flatpak` whose `action:` opens the per-release update PR on `flathub/org.orcshot.Orcshot` using Task 5's script.

- [ ] **Step 1: direflail runs `/orc-package flatpak`**

Its checks: `gh auth status` as `artificialorctelligence`; `gh api user --jq .two_factor_authentication` must print `true` — if it prints `false`, direflail enables 2FA in GitHub settings before Task 7 (the write invitation cannot be accepted without it). The per-app check (appstream API 200) fails today, correctly. Review the diff. As in Task 3, delete the placeholder leaf first if the command refuses to overwrite it.

- [ ] **Step 2: Reshape the leaf's action to use the script**

Replace the written `action:` with:

```yaml
        action: >-
          V=$(git describe --tags --abbrev=0) &&
          scripts/flathub-manifest.py "$V" > "${TMPDIR:-/tmp}/flathub-org.orcshot.Orcshot/org.orcshot.Orcshot.yaml" &&
          cp flathub-lint-exceptions.json "${TMPDIR:-/tmp}/flathub-org.orcshot.Orcshot/" &&
          cd "${TMPDIR:-/tmp}/flathub-org.orcshot.Orcshot" && git checkout -q -B "update-$V" origin/master &&
          git commit -qam "Update to $V" && git push -q -u origin "update-$V" &&
          gh pr create --fill --base master --head "update-$V"
```

Keep the ingredient's `prepare:` (clone-or-pull of `flathub/org.orcshot.Orcshot`), `confirm:`, `metrics:`, `requirements:` and `issues:`. Replace the requirement about the `sed` matching `tag:`/`commit:` lines with: "The Flathub repo's manifest is regenerated whole by `scripts/flathub-manifest.py`; edits made directly in the Flathub repo are overwritten on the next release - make them in this repo's manifest instead." Keep the EGO sentence from the old placeholder as a requirement, reworded to the GNOME-fallback form used in Task 3.

- [ ] **Step 3: The RELEASING.md step**

The ingredient inserted a step after "Commit, tag, push" (now step 10; the snap step is 12 → becomes 13). Edit it to:

```markdown
## 11. Update Flathub

**One-time setup:** the first Flathub submission, reviewed by volunteers over days (BACKLOG
#198, spec 2026-09-12 §4.4): fork `flathub/flathub`, branch from `new-pr`, add the manifest
`scripts/flathub-manifest.py vX.Y.Z` produces plus `flathub-lint-exceptions.json`, open the PR
against `new-pr` titled `Add org.orcshot.Orcshot`, comment `bot, build`, answer the reviewers.
Merge only once extensions.gnome.org lists `orcshot@orcshot.org` (decision 6). After the merge,
accept the write invitation to `flathub/org.orcshot.Orcshot` within a week (2FA required).
Check: `curl -sf https://flathub.org/api/v2/appstream/org.orcshot.Orcshot >/dev/null`.

**Preconditions:** step 10 pushed `vX.Y.Z`; `gh auth status` is `artificialorctelligence`.

**Run:** /orc-publish desktop.python.linux.flatpak

Then, by hand: wait for the bot's test-build comment on the PR, install the build it links
(`flatpak install --user <link>`) on a real machine, run the app, and only then merge the PR.
Publication follows within 1-2 hours unless a permission or AppStream change held it for a
moderator. Confirm: the appstream API above lists the new version.
```

Renumber: 1..15 contiguous; fix every in-text `step N` reference (`grep -n 'step [0-9]' RELEASING.md`).

- [ ] **Step 4: Update #198, commit, PR, merge**

Append to #198: Flathub track started, ingredient applied, the derived-manifest reshape and why (decision 5), the ingredient delta for Orclab #33 (its `sed` assumes the Flathub manifest is hand-maintained with `tag:`/`commit:` lines; a project whose repo manifest builds the working tree needs a derivation step instead).

```bash
git add .orclab/publish/channels.yaml RELEASING.md BACKLOG.md
git commit -m "BACKLOG #198: Flathub leaf and RELEASING step, manifest derived per release (/orc-package flatpak, reshaped)

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
git push -u origin store-onboarding-flathub
gh pr create --title "Flathub onboarding: derived manifest, publish leaf, release step (#198)" --body "$(cat <<'EOF'
Track 2 of docs/superpowers/specs/2026-09-12-store-onboarding-design.md.

- `scripts/flathub-manifest.py <tag>` derives the tag-pinned Flathub manifest from the repo one (one source block differs; tested).
- `desktop.python.linux.flatpak` leaf opens the per-release update PR on flathub/org.orcshot.Orcshot using it.
- RELEASING.md step 11 "Update Flathub" with its one-time setup; steps renumbered to 15.

The submission itself (a PR against flathub/flathub) is opened by direflail after this merges.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

Wait for CI; direflail merges.

### Task 7: The submission PR against `flathub/flathub`

**Files:** none in this repo. Work happens in a scratchpad clone of direflail's fork.

**Interfaces:**
- Consumes: `scripts/flathub-manifest.py` on `main`, `v0.4.0`.
- Produces: an open PR `Add org.orcshot.Orcshot` on `flathub/flathub` (base `new-pr`) with a green `bot, build`.

- [ ] **Step 1: Fork and branch (direflail forks; the clone can be prepared here)**

direflail: on `https://github.com/flathub/flathub`, Fork, **uncheck** "Copy the master branch only". Then:

```bash
S=/tmp/claude-1000/-home-direflail-projects-orcshot/2e5f3efb-7792-45a4-af07-d216aa853059/scratchpad
git clone --branch new-pr https://github.com/artificialorctelligence/flathub.git $S/flathub
cd $S/flathub && git checkout -b org.orcshot.Orcshot
cd /home/direflail/projects/orcshot && git checkout main && git pull
scripts/flathub-manifest.py v0.4.0 > $S/flathub/org.orcshot.Orcshot.yaml
cp flathub-lint-exceptions.json $S/flathub/
cd $S/flathub && flatpak run --command=flatpak-builder-lint org.flatpak.Builder --user-exceptions flathub-lint-exceptions.json manifest org.orcshot.Orcshot.yaml && echo LINT OK
```

Also do one local build of the derived manifest to be sure it builds from the tag, not the tree: `flatpak-builder --force-clean --user --install-deps-from=flathub build-dir org.orcshot.Orcshot.yaml` in `$S/flathub`. Expected: builds; `flatpak-builder --run build-dir org.orcshot.Orcshot.yaml orcshot --help` prints usage.

```bash
git add org.orcshot.Orcshot.yaml flathub-lint-exceptions.json
git commit -m "Add org.orcshot.Orcshot"
git push -u origin org.orcshot.Orcshot
```

- [ ] **Step 2: Draft the PR description; direflail opens the PR**

`gh pr create --repo flathub/flathub --base new-pr --head artificialorctelligence:org.orcshot.Orcshot --title "Add org.orcshot.Orcshot" --body-file $S/flathub-pr.md` — direflail runs it (or pastes the body into the web form). Write `$S/flathub-pr.md`:

```markdown
Orcshot is a screenshot capture and annotation tool for Linux (GTK 3, Python), source at
https://github.com/artificialorctelligence/orcshot, built here from tag v0.4.0. It is already
distributed as a .deb (PPA) and a snap; this is its first Flathub submission.

**Permissions, and why each one is there** (the manifest passes `flatpak-builder-lint` with
one exception, included as `flathub-lint-exceptions.json`):

- `--own-name=org.x.StatusIcon.orcshot` — the one lint exception. On Cinnamon the tray icon is
  an `XApp.StatusIcon`; libxapp can only register it under the `org.x.StatusIcon.*` prefix
  (Cinnamon's status applet discovers icons by that prefix — see `xapp-status-icon.c`).
  Warpinator carries the identical line on Flathub as the linter's existing StatusIcon
  exception; requesting the same treatment. If it is not acceptable the line can go, at the
  cost of no tray icon on Cinnamon.
- `--talk-name=org.gnome.Shell` — on GNOME Wayland, clipboard and window capture call custom
  interfaces exported on that bus name by Orcshot's own GNOME Shell extension. Flatpak filters
  D-Bus by bus name only, so this cannot be narrowed to the extension's interfaces. The
  extension itself is installed through `org.gnome.Shell.Extensions.InstallRemoteExtension`
  from extensions.gnome.org — no filesystem grant into `~/.local/share/gnome-shell`.
- `--filesystem=xdg-pictures:create` — the default save folder (`~/Pictures/Screenshots`).
  Save As and any other location go through the file-chooser portal.
- `--socket=fallback-x11` + `--share=ipc` — X11 sessions (Cinnamon, GNOME on Xorg).

Screenshots in the metainfo were taken on GNOME Shell (Wayland). OARS: no content.

I am the upstream developer and will maintain the Flathub repo.
```

Then comment `bot, build` on the PR (direflail). Watch the bot's result; if the build fails, fix in **this** repo's manifest (never in the Flathub branch alone), cut a `v0.4.1` if a code change is needed, regenerate, and push the branch again.

- [ ] **Step 3: Install the bot's test build on the Mint host and try it**

The bot comments a `flatpak install --user https://dl.flathub.org/build-repo/<n>/org.orcshot.Orcshot.flatpakref` line. Before running it, make sure nothing Orcshot owns the bus (the .deb tray instance steals the name from a Flatpak launch — `project_flatpak_live_test_gotchas` memory): `pkill -f orcshot` on the host. Then install, run, first-run dialog, one capture, Save, tray icon present on Cinnamon. Record results in a VERIFICATION.md scenario "Flathub: test build from the submission PR on the Mint host" (on a small branch to `main`).

- [ ] **Step 4: Answer reviewers**

Each reviewer comment: verify what they ask against the live docs before answering (`verify-before-asserting`), make manifest changes in this repo first, regenerate the Flathub branch. Do not merge; do not ask them to merge before Task 8's gate.

### Task 8: Merge gate, post-merge, and the record

**Files:**
- Modify: `BACKLOG.md` (#198 resolved; #197 partially; #205 if EGO acceptance closes it in the same window)
- Modify: `VERIFICATION.md` (Flathub install scenario result)
- Modify: `src/orcshot/ui/extension_install.py:37` (`EGO_URL`) — only when EGO lists the extension, in a release

**Interfaces:**
- Consumes: EGO listing `orcshot@orcshot.org` (`https://extensions.gnome.org/extension-query/?search=orcshot` returns it); a released tag whose `EGO_URL` points at it.

- [ ] **Step 1: The gate**

Merge the Flathub PR (direflail, or the Flathub reviewers on their approval) **only when** both hold: `curl -sf 'https://extensions.gnome.org/extension-query/?search=orcshot' | grep -q 'orcshot@orcshot.org'`, and the tag the Flathub manifest points at carries the real `EGO_URL`. If EGO lists the extension after `v0.4.0`, that means a `v0.4.1` (or 0.5.0) release with the `EGO_URL` change, then regenerating the Flathub branch for that tag before merge. If reviewers approve first, comment on the PR: "Approved from our side too — holding the merge until the companion GNOME Shell extension is live on extensions.gnome.org, since first-run on GNOME links to it. Will ping when ready."

- [ ] **Step 2: After the merge**

- Accept the write invitation to `flathub/org.orcshot.Orcshot` (direflail, within a week; 2FA).
- Check: `gh api repos/flathub/org.orcshot.Orcshot/collaborators/artificialorctelligence/permission --jq .permission` prints `write` or `admin`.
- Within ~2 h: `curl -sf https://flathub.org/api/v2/appstream/org.orcshot.Orcshot | python3 -c 'import json,sys; print(json.load(sys.stdin)["releases"][0])'` shows the version.
- On the Mint host: `flatpak uninstall --user org.orcshot.Orcshot` (the test build), `flatpak install flathub org.orcshot.Orcshot`, first-run, one capture. Fill the VERIFICATION.md scenario's result.
- Run `/orc-publish --metrics desktop.python.linux.flatpak` once: whatever it prints (or fails with) is #186's first real data point — note it in #186, do not chase it here.

- [ ] **Step 3: Resolve the backlog entries**

- **#198** → heading `(RESOLVED 2026-XX-XX)`; appended paragraph: dates for the held upload, forum grant, 0.4.0 beta release, Flathub PR open/merge, review turnaround; what each ingredient got wrong for Orcshot (CI artifact vs. local pack; review-tools copy step; derived manifest vs. `sed`; anything reviewers asked that the drafts missed) — labelled "input for Orclab #33".
- **#197** → append "snap and flatpak halves answered by RELEASING.md steps 11 and 13's one-time-setup blocks (login expiring 2027-09-11; GitHub 2FA + write access). PPA half (GPG passphrase caching, hardware key) remains open." Heading unchanged (still open).
- **#186** → the metrics data point from Step 2.

```bash
git checkout -b store-onboarding-record
git add BACKLOG.md VERIFICATION.md
git commit -m "Resolve BACKLOG #198: Orcshot is on the Snap Store (beta) and Flathub; #197's store halves answered

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
git push -u origin store-onboarding-record && gh pr create --fill
```

- [ ] **Step 4: Snap `stable` — a separate decision, recorded not taken**

With EGO live and one clean-machine beta install confirmed, the promotion command is `snapcraft release orcshot <revision> stable`. Ask direflail; do not run it. Whatever they decide goes into #198's resolution paragraph.
