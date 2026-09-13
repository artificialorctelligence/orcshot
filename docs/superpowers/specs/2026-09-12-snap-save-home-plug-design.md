# Snap Save: the `home` plug, and the portal-path guard under snap — design

**Date:** 2026-09-12 · **Backlog:** #212 (blocks the Snap Store half of #198) · **Follows:**
#210 (`2026-09-12-flatpak-save-portal-design.md`), whose portal-path guard this closes for snap.

## Why

`snapcraft.yaml` is `confinement: strict` with one app plug, `audio-playback`. Under strict
confinement a snap may write only its own `$SNAP_USER_DATA`/`$SNAP_USER_COMMON`; a write to
`~/Pictures/Screenshots` (the default output directory) is AppArmor-denied. So *Capture → Save*
in the snap cannot produce a file the user can find. Nobody had pressed Save in the snap (CI
installs it `--dangerous` and checks the app launches; #184/#205 exercised capture). The first
Snap Store user's first Save would lose the capture — the same class of failure #210 fixed for
Flatpak, by a different mechanism (denial, not tmpfs).

## What was verified before this was written

- **The snap's file dialogs already use the portal.** The snapcraft `gnome` extension this app
  uses (`extensions: [gnome]`) sets `GTK_USE_PORTAL=1` in the app environment
  (`canonical/snapcraft`, `snapcraft/extensions/gnome.py:178`, fetched 2026-09-12). With it,
  `Gtk.FileChooserNative` — every file dialog since #210 — goes through
  `org.freedesktop.portal.FileChooser`, and picked paths come back as document-portal paths.
- **Where the document portal is mounted inside a snap.** snapd's `desktop/portal/document.go`
  (`GetDefaultMountPoint`, line 69) resolves it as `<user runtime dir>/doc`, i.e.
  `/run/user/<uid>/doc` — the user's runtime dir, not the snap's. A snap's `XDG_RUNTIME_DIR`
  environment variable is `/run/user/<uid>/snap.<name>`. Therefore #210's
  `settings.is_portal_document_path`, which tests `$XDG_RUNTIME_DIR/doc`, answers **False**
  for every portal path under the snap, and the two rename sites it guards would strand
  `.xdp-<name>-XXXXXX` files exactly as Flatpak did before the fix.
- **`home` covers the default folder.** The `home` interface grants read/write to non-hidden
  files under the real home directory (`~/Pictures/Screenshots`, `~/Screenshots`), and is
  auto-connected on classic systems (not Ubuntu Core) — no store review, no manual
  `snap connect`. After #205 removed `personal-files`, this leaves the snap with no
  review-gated interface.
- **The baseline observation corrected the premise (2026-09-12, Task 4 on the 0.3.0 snap).**
  Save does *not* fail under the snap. snapd sets `HOME=$SNAP_USER_DATA`
  (`/home/<user>/snap/orcshot/<rev>`), so `Path.home()` is the snap's private data dir and
  `default_output_directory()` resolves to `~/snap/orcshot/<rev>/Screenshots` — a real,
  persistent folder no user would look in. The write succeeds there with or without the `home`
  plug. The plug itself works: from `snap run --shell orcshot`, a write to the real
  `~/Pictures/Screenshots` succeeds with `home` connected and is `Permission denied` without
  it. It just guards a path the default never produced. snapd also exports
  `SNAP_REAL_HOME=/home/<user>`; nothing in `src/` read it. Section 4 is the consequence.

## Design

### 1. `snapcraft.yaml` — the `home` plug

Add to the app's `plugs:`:

```yaml
      # BACKLOG #212: Save writes to the configured output directory
      # (~/Pictures/Screenshots by default). home is auto-connected on
      # classic distros, needs no store review, and covers every
      # non-hidden path under the real home. A folder outside home goes
      # through the FileChooser portal instead (settings.
      # output_directory_is_reachable) - no removable-media plug.
      - home
```

Nothing else in the manifest changes.

### 2. `settings.is_portal_document_path` — both mount points

The guard accepts a path under **either** `$XDG_RUNTIME_DIR/doc` (Flatpak: the env var is
the user's runtime dir) **or** `/run/user/<uid>/doc` (snap: the env var is the snap's own
runtime dir, but snapd mounts the portal at the user's). Docstring cites `document.go` for the
snap case. No channel detection — the two prefixes are checked unconditionally, which is also
correct on a plain install (the second is simply never a real path there).

This branch only fires once the portal actually hands back a document-portal path in the first
place; with `home` connected and the save inside the default `~/Pictures/Screenshots`, snapd's
`file-access=read-write` policy makes the portal answer with the *real* path instead, so this
guard (and the "Saved as" dialog it protects) is never reached — see Scenario B below.

### 3. `settings.output_directory_is_reachable` — a denied folder is unreachable

```python
    try:
        directory.mkdir(parents=True, exist_ok=True)
    except PermissionError:
        return False
    if detect_channel() != "flatpak":
        return True
    return os.stat(directory).st_dev != os.stat("/").st_dev
```

`mkdir` moves above the channel check and runs on every channel. Under the snap a configured
folder outside home (or any path a plug does not cover) now yields the Screenshot Save
Location picker once — through the portal, whose document grant is writable regardless of
plugs — instead of a traceback in the log and nothing on screen. On the .deb a read-only
configured folder gets the same picker instead of a crash. Flatpak behaviour is unchanged
(`mkdir` on the tmpfs never raises).

The existing test `test_creates_the_directory_before_checking` asserted that the "deb" branch
does *not* touch disk; that assertion inverts — every channel creates the folder now.

### 4. `settings.real_home()` — the user's home, not the snap's

```python
def real_home() -> Path:
    return Path(os.environ.get("SNAP_REAL_HOME") or Path.home())
```

Used by the two places that name a folder the user is meant to find:
`default_output_directory()` (`settings.py`, the `~/Pictures` probe and its fallback) and
`file_export.orcshot_visible_temp_dir()` (the `~/Orcshot` hand-off folder). The config, cache
and autostart paths keep `Path.home()`/XDG: under the snap those are *supposed* to be the
snap's private dirs. On the .deb and under Flatpak `SNAP_REAL_HOME` is unset and `HOME` is
already the real home, so nothing changes there — no effect on the PPA or Flathub channels.

### 5. The snap ships a desktop file (BACKLOG #215)

Found by Scenario B on the first fixed snap (CI run 34731021927): the portal save dialog
appeared, the app got a `/run/user/1000/doc/<id>/snap-test` path, and the write failed with
`No such file or directory`. Proven chain: the snap has no desktop file → `snap routine
portal-info <pid>` answers `DesktopFile=.` → xdg-desktop-portal grants the document to app id
`.` (journal: `Invalid id .: Name can't start with a period`) → snapd's per-app bind mount
`by-app/snap.orcshot` over `/run/user/1000/doc` inside the snap is empty. So under the snap
*every* portal-picked file (Save As, Open, Insert Image/SVG, Save/Load Objects, the folder
picker) is unusable — and with no desktop file there is no launcher entry either. This is a
Snap Store blocker independent of Save.

Fix, in `snapcraft.yaml`: the `orcshot` part's `override-build` installs the existing
`org.orcshot.Orcshot.desktop` (the Flatpak's, `Exec=orcshot`, `Icon=org.orcshot.Orcshot`) to
`usr/share/applications/` and the icon PNG to
`usr/share/icons/hicolor/128x128/apps/org.orcshot.Orcshot.png` (the same non-square asset the
.deb ships at that size), and `apps.orcshot.desktop:` names that file. snapcraft copies it to
`meta/gui/orcshot.desktop` and rewrites `Exec` to the snap command; snapd registers it as
`/var/lib/snapd/desktop/applications/orcshot_orcshot.desktop`; the gnome extension's
`XDG_DATA_DIRS` makes the hicolor icon resolvable to the app's own icon lookup. Whether Ubuntu
26.04's portal then maps the desktop id back to `snap.orcshot` is the thing Scenario B
re-verifies — it is the hypothesis, stated as one.

### 6. The reachability probe must actually write (BACKLOG #216)

Found by Scenario C: with `output_directory` = `/media/orcshot-test` (exists, owned by the
user, no plug covers it) Save produced a `PermissionError` traceback, not the picker. Proven:
`mkdir(parents=True, exist_ok=True)` on an *existing* folder returns EEXIST before AppArmor's
`path_mkdir` hook runs, so nothing raises; `os.access(W_OK)` is not AppArmor-mediated either
and answers True. Only a real write is denied. The Task 2 reviewer's deferred note ("the denial
test mocks `Path.mkdir` rather than a real denial") was this exact gap.

`output_directory_is_reachable` therefore probes by creating and deleting a temporary file in
the directory (`tempfile.NamedTemporaryFile(dir=directory)`, closed immediately) and treats any
`OSError` from the mkdir or the probe as unreachable — `EACCES`, `EROFS` and a vanished mount
alike, which also retires the Task 2 "only PermissionError" minor. The Flatpak `st_dev` test
stays after it. Tests use a real `chmod 0o500` directory (skipped when running as root), not a
mock.

Also from Scenario B: the "Saved as PNG" dialog was shown *before* the write, so it announced
a save that then failed. It moves after `save_image_to_file` in `_do_save`.

### 7. Nothing else

`ensure_output_directory`, the nine dialog sites, and the never-rename guard from #210 need no
further snap-specific change; sections 2–6 make them correct there.

## Testing

- `real_home`: `SNAP_REAL_HOME` set → that path; unset → `Path.home()`. `default_output_directory`
  under a faked `SNAP_REAL_HOME` never returns a path under the fake `HOME`.
- `is_portal_document_path`: True for `/run/user/<uid>/doc/<id>/x` when `XDG_RUNTIME_DIR` is
  `/run/user/<uid>/snap.orcshot` (the snap case); the existing Flatpak/host cases unchanged.
- `output_directory_is_reachable`: False when `mkdir` raises `PermissionError` (monkeypatched
  `Path.mkdir`), on channel "snap" and "deb"; True on "deb" when it succeeds; the inverted
  disk-touch assertion.
- Snap CI (`snap.yml` verify job): after `snap install --dangerous`, `snap connections orcshot`
  lists `home` as connected — one grep line added to the job, so a future plug regression fails
  CI rather than a user's Save.

## Live verification (VERIFICATION.md Scenario 4)

On the Ubuntu 26.04 VM (snapd present, auto-login, GNOME 50 Wayland; registry memory
`project_orcshot_vm_access.md`), with the CI-built snap installed `--dangerous`. Check the bus
name owner first (`GetConnectionUnixProcessID` + `/proc/<pid>/cgroup` containing `snap.orcshot`)
— the VM has had a .deb and a Flatpak of this app; neither may own `org.orcshot.Orcshot`.

- **Before the fix (the 0.3.0 CI snap):** done 2026-09-12 — *Save* wrote
  `~/snap/orcshot/x4/Screenshots/2026-09-12 19_32_53.png`, no error, real
  `~/Pictures/Screenshots` untouched. #212's "AppArmor-denied" guess was wrong; recorded as
  such when the entry is resolved.
- **A. Default folder.** `home` connected (`snap connections orcshot | grep home`), no
  `output_directory` configured. *Save*: no dialog; file in the **real** `~/Pictures/Screenshots`
  on the VM, and nothing new under `~/snap/orcshot/`. — PASS 2026-09-12 (run 34731021927,
  snap x1, VERIFICATION.md Scenario 4). Toolbar icons render (#214 is a log line only).
- **A2. Launcher entry.** After install, `/var/lib/snapd/desktop/applications/
  orcshot_orcshot.desktop` exists, `snap routine portal-info <pid>` reports that
  desktop file (not `.`), and the app appears in GNOME's app grid with its icon.
- **B. Save As through the portal under snap.** Editor → *Save As…*: the portal dialog appears;
  type `snap-test` (no extension), choose JPEG. With `home` connected and the target inside
  `~/Pictures/Screenshots`, the portal answers snapd's own `file-access=read-write` and hands
  back the *real* path, not a document-portal one — so the write lands directly at
  `~/Pictures/Screenshots/snap-test.jpg`, JPEG, and **no** "Saved as" dialog appears (the
  extension the portal returned already matches the chosen format). The document-portal path —
  and the "Saved as" dialog for a mismatched extension — is exercised instead by Scenario C
  (a folder outside `home`).
- **C. Folder outside home.** `output_directory` = `/media/orcshot-test` (owned by the user,
  no plug covers it). *Save*: the portal folder picker appears once; pick it; file lands there;
  config now a `/run/user/1000/doc/…` path; second *Save* silent.
- **D. Restart.** `snap run orcshot` again after killing it: *Save* silent into the folder
  from C.

## Scope boundaries

- **#207** (autostart under snap) and **#213** (external commands) untouched.
- `removable-media` deliberately not added: section 3 plus the portal covers a USB stick with
  one folder pick, and every plug added is one more thing to justify.
- Cinnamon/X11 under snap not separately verified; the code paths are channel-agnostic and the
  Flatpak run of #210 covered the -gtk portal backend.
