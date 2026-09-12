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
UUID (EGO first submission); `https://cinnamon-spices.linuxmint.com/applets/view/orcshot@orcshot.org`
returns 200 (Spices PR merged); `flatpak-builder-lint ... manifest org.orcshot.Orcshot.yaml` is
clean without the filesystem grant.
