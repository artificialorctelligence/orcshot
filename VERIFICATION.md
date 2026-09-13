# Orcshot verification script

Live scenarios that no unit test can stand in for: they need a real desktop session, a real
sandbox, or a real store. Each scenario names the command that produces its evidence and the
date and machine it last passed on. VMs are in the registry memory (`project_orcshot_vm_access.md`):
Ubuntu 26.04 (GNOME 50, SSH port 2222) and Ubuntu2404 (GNOME 46, port 2223). Entries are added
with `/orc-todo add verification` (Orclab) and numbered by the same allocator as `BACKLOG.md`.

## Scenario 1: Extension delivery (spec 2026-09-11): the extension calls the app, on every channel

Scenarios for docs/superpowers/specs/2026-09-11-snap-compliant-extension-delivery-design.md §6.
Results are from 2026-09-11/12 on the real VMs; each line names the command that produced it.

**A. .deb on Ubuntu 26.04 (GNOME Shell 50.1, Wayland).** Install the branch .deb, reboot
(auto-login), then:
- `journalctl --user -b -o cat | grep -i "orcshot\|JS ERROR"` shows `orcshot: extension enabled` and
  no `JS ERROR`; `gnome-extensions info orcshot@orcshot.org` is `State: ACTIVE`, path
  `/usr/share/gnome-shell/extensions/orcshot@orcshot.org`. — PASS 2026-09-11.
- `gdbus introspect --session --dest org.orcshot.Orcshot --object-path /org/orcshot/Orcshot/Shell`
  lists `Hello`, `GetRequest`, `Deliver`. — PASS.
- `gdbus call ... org.gtk.Actions.Activate tray-full_screen [] {}` → the Shell-side destination
  menu appears (with the app's live destination list, external commands included); choosing
  *Edit…* opens the editor with the 1366×768 capture. — PASS (session screenshots `vm-menu.png`,
  `vm-editor.png`).
- Same, choosing *Copy to Clipboard*: request 4 (`set-clipboard-image`) issued and delivered
  within 2.5 s, no `handler ... threw` line in the Shell log. Reading the clipboard back needs a
  focused Wayland client, which SSH cannot be — a limit of the method, not a failure. — PASS.
- `tray-region` → the region overlay dims the screen; Escape cancels and delivers `ok:false`. —
  PASS (`vm-region.png`).
- Tray icon present in the top bar. — PASS.

**B. .deb on Ubuntu 24.04 (GNOME Shell 46.0, Wayland).** Same steps; the session must be
"Ubuntu" (Wayland), checked with `loginctl show-session <id> -p Type`. Extension ACTIVE, no JS
errors, `tray-full_screen` → Shell menu → *Edit…* → editor. — PASS 2026-09-12
(`vm2404-menu.png`, `vm2404-editor2.png`).

**C. Snap on 26.04 (the CI-built snap from the branch).**
- `review-tools.snap-review <snap>` lists exactly one error:
  `declaration-snap-v2:slots_connection:dbus-orcshot:dbus` (human review required). — PASS
  2026-09-11 (the `personal-files` hold is gone).
- Launch inside the graphical session (`systemd-run --user --setenv=WAYLAND_DISPLAY=wayland-0
  ... snap run orcshot`): before #206 the GUI crashed in `do_startup` (pre-existing on main).
  With `extensions: [gnome]` (#206): the first-run window appears - the snap's first window
  ever (`vm-snap-session.png`) - and in a fresh session with the extension loaded the tray icon
  shows and `tray-full_screen` → Shell menu → *Edit…* opens the editor with the capture,
  strictly confined (`vm-snap-editor.png`). — PASS 2026-09-11.
- Clicking *Enable* in first-run crashed on `systemctl` (PermissionError) - BACKLOG #207; the
  autostart offer is now .deb-only. Re-check on the next build: no checkbox on Snap.
- The `snap-gnome` install dialog (§7 text) is exercised on a session whose Shell has not
  loaded the extension; the no-op rule hides it when Hello already arrived.

**D. Flatpak on 26.04 (the CI-built bundle from the branch).**
- `flatpak info --show-permissions org.orcshot.Orcshot`: no `filesystems=` line at all; Session
  Bus Policy `org.gnome.Shell=talk`. — PASS 2026-09-11.
- Launch in the session → standard first-run → *Enable* → the `flatpak-gnome` dialog with the §7
  text. — PASS (`vm-flatpak-install.png`).
- `InstallRemoteExtension("orcshot@orcshot.org")` from inside the sandbox on
  `org.gnome.Shell`: reaches GNOME's installer, which answers
  `org.gnome.Shell.Extensions.Error.InfoDownloadFailed: Unexpected response: Not Found` — the
  correct pre-listing result (spec verification item 4: this is the name to call). On
  `org.gnome.Shell.Extensions`: `ServiceUnknown` — the talk-name cannot be narrowed (item 2). —
  PASS 2026-09-11.
- Re-test after EGO lists the UUID: GNOME's own dialog, install, Hello closes Orcshot's dialog.
- Found and fixed live: Hello arrives before first-run builds the dialog, so the dialog must be
  a no-op when `bridge.capabilities` is already non-empty; and Enter must activate the action
  button, not *Later*.

**E. Spec verification items 1 and 3 (GNOME's loading behaviour).**
- Item 3: with no copy known to the running Shell, `gnome-extensions install` + `enable` does
  NOT load a new per-user extension (`Extension "orcshot@orcshot.org" does not exist` until
  re-login) — the Shell scans directories at login only. `InstallRemoteExtension` (what
  Extension Manager and the browser connector use) loads live. So the Snap dialog's "closes by
  itself when the extension is running" holds for the EGO route; a hand-unzipped copy needs a
  re-login. — RECORDED 2026-09-12.
- Item 1 (does `InstallRemoteExtension` also enable): answered from GNOME Shell's
  `extensionDownloader.js` (install → enable); re-confirm live once listed.
- GNOME quirk worth knowing: a failed `InstallRemoteExtension` for a UUID that is *already
  loaded* marks that extension `State: ERROR` until re-login (`logExtensionError`). The no-op
  rule above is what keeps the Flatpak from tripping this on a machine that also has the .deb.

**F. CI (every push).** `snap / verify` and `flatpak / verify` install the packed extension as a
user would, run a real headless Shell, and run `scripts/ci-shell-roundtrip.py` inside the
sandbox: Hello with the expected capabilities, then one `list-windows` round trip. Both green
on PR #23 (runs 34668147421, 34668147446). `snap / verify` additionally launches the real GUI
under the headless Shell (#206).

**Store-side, checked by URL, not automated:** `snap info orcshot` shows a channel map (dbus
declaration granted); `https://extensions.gnome.org/extension-query/?search=orcshot` lists the
UUID (EGO first submission); `flatpak-builder-lint ... manifest org.orcshot.Orcshot.yaml` is
clean without the filesystem grant.

## Scenario 2: XApp status icon on Cinnamon (spec 2026-09-12)

Scenarios for docs/superpowers/specs/2026-09-12-xapp-status-icon-design.md, all on the Mint host
(Cinnamon 6.x, X11), 2026-09-12.

- Dev checkout (`.venv/bin/python -m orcshot.app`, the .deb code path): the process owns both
  `org.orcshot.Orcshot` and `org.x.StatusIcon.orcshot` (`gdbus ... ListNames`); the icon sits
  among the status icons; right-click shows the app's menu with per-item icons and no About /
  Remove (`real-menu.png` in the session scratchpad); Quit removes icon and process. — PASS.
- Menu-in-capture, dev checkout: direflail chose *Capture Full Screen → Save* from the icon's
  menu; the saved 4480×1440 PNG cropped at the menu's screen position shows the desktop and
  panel, no menu (`user-saved-menu-region.png`). — PASS. This is in-process code identical on
  every channel (ui/xapp_tray.py's proxy).
- Flatpak (CI bundle from run 34679321587, `flatpak install --user`):
  `flatpak info --show-permissions` lists `shared=ipc`, `org.x.StatusIcon.orcshot=own`,
  `org.x.StatusIconMonitor.*=talk`; `gi.require_version("XApp","1.0")` succeeds inside the
  sandbox (after `-Dlibdir=lib`; before it the typelib sat in /app/lib64 and failed);
  `running_on_cinnamon()` is True inside the sandbox (after switching to XDG_CURRENT_DESKTOP;
  the GSettings-schema check answered False); one instance owns both bus names (`:1.1096`);
  Cinnamon's log: `Adding XAppStatusIcon: orcshot (:1.1096/org/x/StatusIcon/Icon)`; direflail
  sees the icon and its menu. — PASS. *Save* from that menu wrote nothing: BACKLOG #210
  (pre-existing Flatpak gap, not this feature's).
- Left-click → region capture: verified on the prototype (`xapp_proto3.py`) by direflail;
  the shipped code path is the same `activate` handler. Not separately re-run on the shipped
  build. — RECORDED, not re-verified.
- Not verified: Cinnamon on Wayland (no session at hand); xapp-status is D-Bus, same code path.
- Two stale Flatpak instances survived a `kill` of the wrong PIDs during this pass; use
  `flatpak kill org.orcshot.Orcshot`, then confirm both names have one owner with
  `gdbus ... GetNameOwner` before judging anything.

## Scenario 3: Flatpak Save through the file-chooser portal (spec 2026-09-12)

Scenarios for docs/superpowers/specs/2026-09-12-flatpak-save-portal-design.md, 2026-09-12, on
the CI bundle from PR #25 (run 34717483024, `flatpak install --user --reinstall`). The bus
name owner was checked before every scenario (`GetConnectionUnixProcessID` + `/proc/<pid>/root/
.flatpak-info`): the first attempt on the Mint host had been answered by the installed .deb tray
app, which owns `org.orcshot.Orcshot` and silently takes over a Flatpak launch - quit it
(`tray-quit`) before testing the Flatpak. Captures triggered with `gdbus ... Activate
tray-full_screen`, the picker driven with xdotool.

- **C. Out of the box (Mint host, Cinnamon/X11).** No `output_directory` in the Flatpak's
  config, host has `~/Pictures`. *Save*: no dialog; `~/Pictures/Screenshots/2026-09-12
  15_25_16.png` on the host (4480x1440 PNG); the Flatpak's own `filename_counter` advanced. —
  PASS.
- **A. Folder outside the grant (Mint host).** `output_directory` = `~/Screenshots`. *Save*:
  the *Screenshot Save Location* dialog appeared once, owned by `xdg-desktop-portal-gtk` (PID
  4582, a host process), showing the real home; picked `~/Screenshots`; file landed there; config
  now `/run/user/1000/doc/7c103d25/Screenshots`. Second *Save*: no dialog, second file. — PASS.
- **B. Restart persistence (Mint host).** `flatpak kill`, relaunch (new PID), *Save*: no dialog,
  third file; `/run/user/1000/doc/7c103d25/Screenshots` still mounted. — PASS.
- **D. Save As with the format choice (Mint host).** The portal save dialog shows *Save as
  type:* with PNG/JPEG/BMP/TIFF/GIF/Orcshot. Typed `~/Screenshots/portal-test.jpg` + JPEG →
  real JPEG on the host (`file`). Typed `portal-noext` + JPEG → the *Saved as PNG* info dialog,
  then `~/Screenshots/portal-noext`, a PNG. — PASS. **First run of this scenario failed** and
  found the never-rename rule (spec §2): `with_suffix(".jpg")` on the portal path left
  `~/Screenshots/.xdp-portal-test.jpg-VWhcUm` - complete, never finalized. Fixed in d1452c2,
  re-verified on the second bundle. The -gtk portal ignores `set_current_folder` on a doc path
  (opens Home); the -gnome one honours it (opened `Home/Screenshots`).
- **E. Insert Image through the portal (Mint host).** `~/Downloads/orcshot-insert-test.jpg`
  (outside Pictures) picked in the portal dialog (PID 4582); the image appeared on the canvas. —
  PASS.
- **F. Ubuntu 26.04 / GNOME 50 / Wayland VM.** Bundle installed; launched via `systemd-run
  --user` (inherits `WAYLAND_DISPLAY`; startup line says `session_type=wayland`; extension
  ACTIVE, Shell-native picker). `output_directory` = `~/Screenshots`: *Save* → GNOME's portal
  folder picker once → `~/Screenshots/2026-09-12 15_48_52.png`; config now
  `/run/user/1000/doc/e4453c62/Screenshots`; second *Save* → no dialog, `15_49_57.png`. — PASS.
- Not verified: Save Objects under the portal (same guard as D, not separately run); Cinnamon
  on Wayland.

## Scenario 4: Snap Save: home plug and the portal-path guard under snap (spec 2026-09-12)

Scenarios for docs/superpowers/specs/2026-09-12-snap-save-home-plug-design.md, 2026-09-12, on
the Ubuntu 26.04 / GNOME 50 / Wayland VM (snapd 2.76.3, xdg-desktop-portal 1.21.1+ds-1ubuntu3,
xdg-desktop-portal-gnome 50.0). The snap launched inside the graphical session with `systemd-run
--user --unit=orcshot-snap ... snap run orcshot`; before every scenario the bus name owner was
checked (`GetConnectionUnixProcessID org.orcshot.Orcshot` + `/proc/<pid>/cgroup` containing
`snap.orcshot`). Captures triggered with `gdbus ... Activate tray-full_screen`, the Shell-native
picker and the dialogs driven with xdotool from the host.

- **Baseline (0.3.0 snap, rev x4, no `home` plug).** *Save*: no dialog, no error, and the file
  went to `~/snap/orcshot/x4/Screenshots/2026-09-12 19_32_53.png` - the real
  `~/Pictures/Screenshots` untouched. Not #212's "AppArmor-denied / PermissionError": under the
  snap `HOME=$SNAP_USER_DATA`, so `Path.home()` *is* `~/snap/orcshot/<rev>` and the write
  succeeds there. — the bug, observed.
- **Home plug alone (CI run 34728131086, rev x1, `home` connected).** Identical result:
  `~/snap/orcshot/x1/Screenshots/2026-09-12 19_39_35.png`. `snap run --shell` proved the plug
  itself works (`touch` in the real `~/Pictures/Screenshots` ok with it connected, `Permission
  denied` with it disconnected) - the plug was necessary, not sufficient. That finding added
  `settings.real_home()` (reads `SNAP_REAL_HOME`).
- **A. Default folder (CI run 34731021927, commit 113d005, rev x1, `snap connections orcshot |
  grep home` → `home  orcshot:home  :home  -`).** No `output_directory` in the snap's config.
  *Save*: no dialog; `~/Pictures/Screenshots/2026-09-12 20_48_15.png` (1366x768 PNG, `file`);
  `find ~/snap/orcshot -name Screenshots` → nothing; log clean apart from the #214
  `libpixbufloader_svg.so` line, which appeared only on the first launch after install
  (before `~/snap/orcshot/common/.cache/gdk-pixbuf-loaders.cache` existed) and not on the
  relaunch. The editor's toolbar and tool-palette icons all render. — PASS.
- **B. Save As through the portal under snap.** Capture → *Edit…* → Ctrl+S: the GNOME portal
  save dialog appeared (GTK4/libadwaita, opened at Home/Pictures/Screenshots, *Save as type* under
  the options button with PNG/JPEG/BMP/TIFF/GIF/Orcshot). Typed `snap-test`, chose JPEG, Save:
  the *Saved as PNG* dialog appeared - and then the write failed: log `GLib.GError:
  g-file-error-quark: Failed to open "/run/user/1000/doc/5501d0c5/snap-test" for writing: No
  such file or directory`; `~/Pictures/Screenshots/snap-test` does not exist, no `.xdp-*` file
  either (the two-prefix guard is not what failed - the doc path never became reachable). —
  FAIL. Cause, proven on the VM: the snap ships no desktop file (`/snap/orcshot/x1/meta/gui/`
  empty), so `snap routine portal-info <pid>` reports `DesktopFile=.`; Ubuntu 26.04's
  xdg-desktop-portal (patch `xdp-app-info-snap-Use-the-desktop-ID-as-app-ID`, upstream PR
  #1764) takes the desktop id as the app id, so `Documents.Info 5501d0c5` shows the grant as
  `{'.': [read, write, grant-permissions]}` and xdg-document-portal logs `Invalid id .: Name
  can't start with a period`; snapd bind-mounts `/run/user/1000/doc/by-app/snap.orcshot` over
  `/run/user/1000/doc` inside the snap (the app's mountinfo), and that view is empty. Same
  portal, same VM, the Flatpak's grant (Scenario 3 F) is under `org.orcshot.Orcshot` and works.
  Tracked as BACKLOG #215.
- **C. Folder outside home.** `output_directory` = `/media/orcshot-test` (existing, owned by
  the user, no plug), snap relaunched, *Save*: **no** portal picker; log traceback from
  `_quick_save` → `save_image_to_file`: `Failed to open "/media/orcshot-test/2026-09-12
  20_57_30.png" for writing: Permission denied`; the folder stayed empty, the capture was lost
  silently (`filename_counter` advanced to 3). — FAIL. Cause, proven with `snap run --shell`:
  `output_directory_is_reachable` probes with `mkdir(parents=True, exist_ok=True)`, and on a
  folder that already exists the kernel answers EEXIST before AppArmor's mkdir hook runs -
  `Path.mkdir` raises nothing, `os.access(W_OK)` says True, only `open(..., "w")` raises
  `PermissionError`. The guard catches the never-existed case only. Tracked as BACKLOG #216.
  Even with that fixed, the picker's grant would have hit B's `.` app id (#215).
- **D. Restart.** Not run - it depends on C's grant.
- Left on the VM: snap rev x1 (commit 113d005) installed and stopped, `/media/orcshot-test`
  present and empty, the snap's config still `"output_directory": "/media/orcshot-test"`.

**Re-run 2026-09-12 after #215/#216 (CI run 34732589935, commit 70d0c40, snap x2):** the CI
verify job's new assertion passed (`snap connections orcshot | grep -E '^home +orcshot:home +:home'`
→ `home  orcshot:home  :home  -`). Installed over x1 with `sudo snap install --dangerous` so the
snap data (config, first-run flag) carried over; `snap connections orcshot | grep -w home` →
`home  orcshot:home  :home  -`. Same launch/owner/capture procedure as above; `output_directory`
deleted from the config before A2/B and set to `/media/orcshot-test` again for C.

- **A2. Launcher entry and portal identity.** `/snap/orcshot/x2/meta/gui/orcshot.desktop` exists
  and `ls /var/lib/snapd/desktop/applications/ | grep orcshot` → `orcshot_orcshot.desktop`
  (snapcraft names it `<snap>_<app>.desktop`, not the `orcshot_org.orcshot.Orcshot.desktop` the
  spec guessed; `X-SnapInstanceName=orcshot`, `Exec=/snap/bin/orcshot`, `Icon=org.orcshot.Orcshot`).
  Launched (pid 14526, cgroup `snap.orcshot.orcshot-…scope`, `session_type=wayland`); `snap
  routine portal-info 14526` → `DesktopFile=orcshot_orcshot.desktop` - not `.`. Super, `orc` in
  the search: three "Orcshot" tiles (the .deb's `/usr/share/applications/orcshot.desktop`, the
  Flatpak's export and the snap's), all with the Orcshot icon. — PASS for the entry and the
  portal identity. The icon is **not** the snap's own: `Gtk.IconTheme.get_default()
  .lookup_icon("org.orcshot.Orcshot")` in the host session resolves to the *Flatpak's*
  `~/.local/share/flatpak/exports/share/icons/hicolor/scalable/apps/org.orcshot.Orcshot.svg`,
  and with the flatpak paths removed from the search path the lookup returns `None`;
  `/var/lib/snapd/desktop/icons/` is empty (snapd rewrites `Icon=` only for `${SNAP}/` paths).
  A snap-only machine gets the placeholder icon. Tracked as BACKLOG #217.
- **B. Save As through the portal under snap.** Capture → *Edit…* (toolbar and tool-palette
  icons render) → Ctrl+S: the GNOME portal save dialog, opened at Home this time; navigated to
  Pictures/Screenshots, typed `snap-test`, *Save as type* → JPEG, Save. Checked **before**
  touching anything else: `~/Pictures/Screenshots/snap-test.jpg` (`file`: JPEG image data,
  1366x768), `ls -A ~/Pictures/Screenshots | grep xdp` empty, `find ~/Pictures -name '.xdp-*'`
  empty, no traceback. No *Saved as PNG* dialog and no `snap-test` PNG - and that is right, not
  a miss: the portal handed the snap the **real** path `…/Screenshots/snap-test`, not a
  `/run/user/1000/doc/…` one - no new document id appeared and `by-app/snap.orcshot/` stayed
  empty - because xdg-document-portal asks `snap routine file-access orcshot <path>` and, with
  `home` connected and the app id now valid, the answer for that path is `read-write` (verified
  on the VM; `/media/orcshot-test` answers `hidden`). A real path is not a portal document path,
  so the normal branch appended `.jpg` for the chosen type. The first run's doc path and its
  `.`-grant are gone with #215; the doc-path branch and the two-prefix guard are exercised by C.
  — PASS (the regression this scenario guards - a stranded `.xdp-*` or a failed write - is
  absent). New log line when the portal dialog opens: `GLib-GIO-WARNING: Error creating IO
  channel for /proc/self/mountinfo: Permission denied` (GIO's mount monitor under confinement;
  matching `open /proc/<pid>/mounts` and `/etc/fstab` AppArmor denials), cosmetic.
- **C. Folder outside home.** `/media/orcshot-test` (existing, chowned, no plug) configured,
  snap relaunched (pid 16040), *Save*: the portal **folder picker appeared** (the #216 real-write
  probe: AppArmor logged `operation="mknod" … name="/media/orcshot-test/.orcshot-probe-…"
  denied_mask="c"` twice - the shared guard and the picker's own initial-folder check - where
  the first run's `mkdir` probe raised nothing); Ctrl+L, `/media/orcshot-test/`, *Select*: no
  dialog after it, `/media/orcshot-test/2026-09-12 21_33_19.png` (988075 bytes), config now
  `"output_directory": "/run/user/1000/doc/752c00e7/orcshot-test"` - a document path under a
  valid `snap.orcshot` grant this time. Second capture → *Save*: silent, `2026-09-12
  21_33_53.png`, no new denials. — PASS.
- **D. Restart.** `launch.sh` again (unit stopped and restarted, pid 16532), capture → *Save*:
  silent, third file `/media/orcshot-test/2026-09-12 21_34_31.png`, config unchanged, log
  clean. — PASS.
- The `libpixbufloader_svg.so` line (#214) again appeared only on the first launch of x2 and not
  on the C/D relaunches.
- Left on the VM: snap rev x2 (commit 70d0c40) installed and stopped; `/media/orcshot-test`
  with the three C/D files; `~/Pictures/Screenshots/snap-test.jpg`; the snap's config with
  `output_directory` deleted.
