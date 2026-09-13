# Snap launcher icon — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the snap's launcher entry show Orcshot's icon on a machine that has only the snap — BACKLOG #217.

**Architecture:** One `sed` on the desktop file copy inside the snap's `override-build`, turning the theme-name `Icon=org.orcshot.Orcshot` into `Icon=${SNAP}/usr/share/icons/hicolor/128x128/apps/org.orcshot.Orcshot.png` — the one form snapd rewrites to a host-readable `/snap/orcshot/current/…` path (`wrappers/desktop.go`, `rewriteIconLine`). A CI assertion proves the registered desktop file carries that path and the file exists; a VM run proves GNOME resolves it without the Flatpak's export masking the result.

**Tech Stack:** snapcraft (core24), snapd desktop-file rewriting, GitHub Actions, Gio/GTK on the VM.

**Spec:** `docs/superpowers/specs/2026-09-12-snap-launcher-icon-design.md` — read it first.

## Global Constraints

- The same PNG, the same path, the same source desktop file: `org.orcshot.Orcshot.desktop` at the repo root is **not** edited (its theme name is right for the Flatpak and the .deb). Only the installed copy inside the snap changes.
- No new plug, no new top-level key. The Snap Store listing icon (`icon:`) is BACKLOG #219 and out of scope.
- No Python changes; no unit tests.
- `BACKLOG.md`/`VERIFICATION.md` entries go through `/orc-todo`, never hand-numbered; #219 exists in the main checkout's `BACKLOG.md` uncommitted.
- From a `.claude/worktrees/` checkout, tests (if ever run) need `PYTHONPATH=src ../../../.venv/bin/python -m pytest`.

---

### Task 1: `Icon=` becomes a `${SNAP}` path, and CI proves snapd keeps it

**Files:**
- Modify: `snapcraft.yaml:89-92` (the `orcshot` part's `override-build`)
- Modify: `.github/workflows/snap.yml:50-51` (after the "Assert the home plug is connected" step)

**Interfaces:** none.

- [ ] **Step 1: Add the `sed` to `override-build`**

In `snapcraft.yaml`, the `orcshot` part's `override-build` currently reads:

```yaml
    override-build: |
      craftctl default
      install -Dm644 org.orcshot.Orcshot.desktop "$CRAFT_PART_INSTALL/usr/share/applications/org.orcshot.Orcshot.desktop"
      install -Dm644 src/orcshot/resources/orcshot.png "$CRAFT_PART_INSTALL/usr/share/icons/hicolor/128x128/apps/org.orcshot.Orcshot.png"
```

Append these lines to that block (same 6-space indentation as the `install` lines):

```yaml
      # BACKLOG #217: snapd keeps a theme-name Icon= verbatim and exports
      # nothing for it, so a snap-only machine shows the placeholder. A
      # ${SNAP} path is the one form snapd rewrites to a host-readable
      # /snap/orcshot/current/... path (wrappers/desktop.go rewriteIconLine).
      # Edited on the installed copy only: the source file's theme name is
      # right for the Flatpak and the .deb.
      sed -i 's|^Icon=.*|Icon=${SNAP}/usr/share/icons/hicolor/128x128/apps/org.orcshot.Orcshot.png|' "$CRAFT_PART_INSTALL/usr/share/applications/org.orcshot.Orcshot.desktop"
```

(`${SNAP}` is inside single quotes, so the shell does not expand it — snapd must see the literal text `${SNAP}`.)

- [ ] **Step 2: Add the CI assertion**

In `.github/workflows/snap.yml`, directly after the "Assert the home plug is connected" step, add:

```yaml
      - name: "Assert the registered desktop file's Icon= is a path inside the snap that exists (BACKLOG #217)"
        run: |
          desktop=/var/lib/snapd/desktop/applications/orcshot_orcshot.desktop
          grep '^Icon=/snap/orcshot/current/' "$desktop"
          test -f "$(sed -n 's/^Icon=//p' "$desktop")"
```

(snapd substitutes `${SNAP}` with `/snap/orcshot/current` when it registers the file; if it ever rejected the line it would drop it and `grep` would fail the job.)

- [ ] **Step 3: Validate locally**

Run: `python3 -c "import yaml; d=yaml.safe_load(open('snapcraft.yaml')); ob=d['parts']['orcshot']['override-build']; print(ob.count('sed -i'), 'Icon=\${SNAP}/usr/share/icons/hicolor/128x128/apps/org.orcshot.Orcshot.png' in ob)"`
Expected: `1 True`.

Run: `python3 -c "import yaml; yaml.safe_load(open('.github/workflows/snap.yml')); print('ok')"`
Expected: `ok`.

Run: `printf 'Icon=org.orcshot.Orcshot\n' | sed 's|^Icon=.*|Icon=${SNAP}/usr/share/icons/hicolor/128x128/apps/org.orcshot.Orcshot.png|'`
Expected: `Icon=${SNAP}/usr/share/icons/hicolor/128x128/apps/org.orcshot.Orcshot.png` (the literal `${SNAP}`).

Run: `git diff --stat` → exactly `snapcraft.yaml` and `.github/workflows/snap.yml`; `git diff org.orcshot.Orcshot.desktop` → empty.

- [ ] **Step 4: Commit**

Stage the two files; subject: `snap: Icon= as a ${SNAP} path so snapd rewrites it - a theme name is kept verbatim and never exported (#217)`; plus the `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>` trailer.

---

### Task 2: Live verification on the Ubuntu 26.04 VM, without the Flatpak masking it

**Files:**
- Modify: `VERIFICATION.md` (append a dated paragraph to Scenario 4, which starts at line 161)
- Modify: `BACKLOG.md` (resolve #217 per `orclab:backlog-discipline`)

**Interfaces:** none — evidence only. A FAIL goes back to Task 1; do not fix in this task.

VM access: registry memory `project_orcshot_vm_access.md` (`ssh -i ~/.ssh/orcshot_dev_vm -p 2222 ubuntu2604@localhost`, passwordless sudo, GUI window on this host found with `wmctrl -l | grep 26.04`, screenshots with `import -window <id>`). VM-side logic in script files `scp`'d over. The Flatpak bundle to reinstall at the end is `/tmp/claude-1000/-home-direflail-projects-orcshot/3bd73e50-4e67-443e-ab36-7b158932a956/scratchpad/bundle2/orcshot-flatpak/orcshot_0.3.0.flatpak`.

- [ ] **Step 1: Push, get the CI snap**

`git push -u origin HEAD`; open a draft PR against `main` (the snap workflow runs on `pull_request`); `gh run list --workflow=snap.yml --branch <branch> --limit 1`; `gh run watch <id> --exit-status` — the verify job's new Icon= assertion must pass; `gh run download <id> -D snap-bundle`; `scp` the `.snap` to the VM; `sudo snap install --dangerous ./orcshot_*.snap`.

- [ ] **Step 2: Scenario E — the registered line and what GNOME resolves**

On the VM:

```bash
grep '^Icon=' /var/lib/snapd/desktop/applications/orcshot_orcshot.desktop
test -f "$(sed -n 's/^Icon=//p' /var/lib/snapd/desktop/applications/orcshot_orcshot.desktop)" && echo "icon file exists"
python3 - <<'PY'
import gi
gi.require_version("Gio", "2.0")
from gi.repository import Gio
icon = Gio.DesktopAppInfo.new("orcshot_orcshot.desktop").get_icon()
print(type(icon).__name__, icon.to_string())
PY
```

Expected: `Icon=/snap/orcshot/current/usr/share/icons/hicolor/128x128/apps/org.orcshot.Orcshot.png`; `icon file exists`; `FileIcon /snap/orcshot/current/usr/share/icons/hicolor/128x128/apps/org.orcshot.Orcshot.png`. (Before this change it was `ThemedIcon org.orcshot.Orcshot`.)

- [ ] **Step 3: Scenario F — seen, with the Flatpak removed**

On the VM: `flatpak uninstall --user -y org.orcshot.Orcshot` (so its exported `org.orcshot.Orcshot.svg` cannot answer for the snap), confirm `ls ~/.local/share/flatpak/exports/share/icons/hicolor/scalable/apps/ 2>/dev/null | grep -c orcshot` is `0`. Then:

1. App grid: in the VM window press Super, type `orc`; screenshot; the Orcshot tile shows the Orcshot mark, not the generic placeholder.
2. Running window: launch the snap inside the session (`systemd-run --user --unit=orcshot-snap -p StandardOutput=file:/tmp/orcshot-snap.log -p StandardError=file:/tmp/orcshot-snap.log snap run orcshot`; stop + reset-failed first if the unit exists), confirm the bus owner's cgroup contains `snap.orcshot`, trigger a capture (`gdbus call --session --dest org.orcshot.Orcshot --object-path /org/orcshot/Orcshot --method org.gtk.Actions.Activate tray-full_screen '@av []' '@a{sv} {}'`), choose *Edit…* in the picker so an editor window is open; press Super to show the overview and screenshot the dock/running-app entry: the Orcshot mark.

Then restore the VM: `flatpak install --user -y <the scp'd orcshot_0.3.0.flatpak>`; `systemctl --user stop orcshot-snap`.

- [ ] **Step 4: Record**

Append to VERIFICATION.md Scenario 4 a paragraph headed `**Re-run 2026-09-12 for #217 (CI run <id>, snap x<rev>):**` with bullets E and F: the commands, their output, the screenshot filenames, PASS/FAIL, and the explicit note that the Flatpak was uninstalled for F and reinstalled after.

- [ ] **Step 5: Resolve #217**

In this worktree's `BACKLOG.md`: `(RESOLVED 2026-09-12)` on #217's title line and a **Resolved for real, not just tracked:** paragraph — the `sed`, the CI assertion, E and F, and that the Flatpak-masking problem the entry described was ruled out by uninstalling it. Do not edit the original text. (#219, the store listing icon, stays open in the main checkout's `BACKLOG.md`.)

- [ ] **Step 6: Commit and hand off**

Stage `VERIFICATION.md` and `BACKLOG.md`; subject: `Resolve BACKLOG #217: snap launcher icon verified on the Ubuntu 26.04 VM without the Flatpak installed`; `Co-Authored-By` trailer; `git push`. Then `superpowers:finishing-a-development-branch`.
