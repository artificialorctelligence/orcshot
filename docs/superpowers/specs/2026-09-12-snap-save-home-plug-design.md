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

### 5. Nothing else

`ensure_output_directory`, the nine dialog sites, and the "Saved as" dialog from #210 need no
snap-specific change; sections 2–4 make them correct there.

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
  on the VM, and nothing new under `~/snap/orcshot/`.
- **B. Save As through the portal under snap.** Editor → *Save As…*: the portal dialog appears;
  type `snap-test` (no extension), choose JPEG: the *Saved as PNG* dialog appears, then
  `~/Pictures/Screenshots/snap-test` exists as PNG and **no** `.xdp-snap-test*` file exists
  anywhere in that folder. This is the section-2 fix; it fails on #210's code as merged.
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
