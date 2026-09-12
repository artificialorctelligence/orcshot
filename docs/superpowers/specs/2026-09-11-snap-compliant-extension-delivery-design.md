# Snap-compliant GNOME Shell extension delivery — design

**Date:** 2026-09-11 · **Backlog:** #205 (this spec), #198 (publish mechanisms, depends on this) ·
**Supersedes:** the copy-into-home extension install from the 2026-08-30 Snap channel design and
the app→`org.gnome.Shell` call direction from the 2026-08-28 Wayland capture redesign.

## Why this exists

Orcshot ships three GNOME Shell extensions. On Snap and Flatpak the app copies them into
`~/.local/share/gnome-shell/extensions` and then calls into them over `org.gnome.Shell`. Both halves
are things the Snap Store forbids, and one of them Flathub scrutinizes.

Everything below is live-verified on 2026-09-11 unless it says otherwise:

- `review-tools` 0.48 (the store's own reviewer) on the CI-built `orcshot_0.3.0_amd64.snap`: **FAIL**
  on exactly two items and nothing else — `personal-files` plug (`allow-installation` constraint:
  the snap could not even be *installed* from the store without a declaration) and the `dbus` slot
  (`deny-connection`). The same snap with only the plug removed: the `dbus` slot is the sole hold.
- A near-identical `personal-files` *write* request (AppImage-Installer, `~/.local/bin` and
  `~/.local/share/applications`) was refused on 2026-09-03/04 as "a trivial confinement escape",
  even for manual connect. No snap has ever been granted write to `gnome-shell/extensions`. Ours
  writes JavaScript that the unconfined Shell executes — the sharper form of that pattern.
- The `dbus` slot hold is routine for an app-owned session name: BusyMax asked 2026-06-23, granted
  2026-06-25, later uploads pass automatically.
- No snapd interface grants `org.gnome.Shell.Extensions` (every builtin interface grepped). snapd's
  classic-confinement review page lists GNOME Shell extensions as *Unsupported*. Extension Manager
  asked in 2023 and was told "I don't think this will ever really be possible". So a snap can
  neither install an extension nor ask GNOME to.
- A stock Ubuntu 26.04 (the VM, GNOME 50.1) has **no** EGO install helper: no Extensions app, no
  Extension Manager, no browser connector (all in `universe`, none seeded), Firefox is a snap.
- Flathub precedent: Extension Manager's manifest has `--talk-name=org.gnome.Shell.Extensions` and
  **no** filesystem grant; it installs via `InstallRemoteExtension`, i.e. GNOME does the install.
- GNOME Shell's `extensionDownloader.js` checks EGO on login for every per-user extension and
  applies upgrades *and downgrades* to EGO's version. Once a UUID is on EGO, EGO owns its version
  regardless of how the copy got there. System-wide (`.deb`) copies are exempt.
- EGO overwrites `metadata.json`'s `version` with its own counter (window-calls' repo says 1.17,
  EGO serves 21). The #191 version comparison on that field is meaningless the moment we publish.
- **The inverted direction is proven under both sandboxes.** A confined app (the #184 strict test
  snap with the real interface set; then the CI-built 0.3.0 Flatpak with its real permissions)
  changed the state of a stateful GAction; an unconfined listener received `org.gtk.Actions.Changed`
  and called a method back into the app, which answered. Zero AppArmor denials. snapd's `dbus.go`
  and `desktop.go` say why: the slot grants receive-from-unconfined on the app's name and path
  (replies implicit), and `desktop` grants exactly one outbound signal, `org.gtk.Actions.Changed`.

## Decisions (with direflail, 2026-09-11)

1. **One merged extension**, `orcshot@orcshot.org`. Three UUIDs = three EGO listings and three
   reviews per update; EGO rejects unrenamed forks anyway.
2. **Capability handshake** (the extension says what it can do) rather than a version compare.
3. **The call-direction inversion is in scope**: one code path for all three channels, one EGO
   review instead of two, and the `.deb` on the VM is the ungated test bed.
4. **Snap: redirect to extensions.gnome.org** with explicit steps (option a). Not the bundled zip +
   command (no precedent anywhere), not "no extension on snap" (the user who installs it still gets
   the full app). This is what every tray-bearing snap has done for the AppIndicator extension.
5. **The snap does nothing for Cinnamon.** Mint blocks snapd by default and ships Flathub.
6. **Flatpak on Cinnamon: redirect to Cinnamon Spices** — Mint's built-in applet store, reachable
   from *Applets → Download*. Spices' 2026-09-08 "self-contained" rule targets external versions of
   a spice itself; its "System dependencies" section explicitly allows depending on
   distro-packaged software. Companion applets (NordVPN, ExpressVPN, KDE Connect, Docker) are
   accepted precedent. Residual risk is contained: rejection leaves Flatpak-on-Mint where it is
   today (no tray), nothing else depends on it.
7. **EGO and Spices are channels in their own right** — accounts, one-time review gates,
   per-release actions, confirmations — and their release steps are *not* gates on the app
   channels, because review lag is unbounded.

## 1. Architecture

One extension is the privileged half of Orcshot on GNOME; whatever needs Shell-process access
lives there and nothing else does.

**One direction of calls: extension → app.** The app never calls `org.gnome.Shell`.

- The app owns `org.orcshot.Orcshot` (it already does; the `dbus` slot) and exports an action group
  at `/org/orcshot/Orcshot` (it already does, for the tray).
- To request something, the app changes the state of one stateful action. GNOME emits
  `org.gtk.Actions.Changed` — the only outbound signal a strict snap is allowed.
- The extension watches that action, does the privileged work, and delivers the result by calling
  a method on the app's exported object.
- On enable, and whenever the app's bus name (re)appears, the extension calls `Hello`.

This is the pattern the tray already uses, applied to everything.

**Delivery per channel** differs only in first-run: `.deb` installs system-wide (unchanged);
Flatpak asks GNOME to install from EGO (or redirects to Spices on Cinnamon); Snap redirects to EGO.
`channel_detect()` decides *how the extension gets installed*, never how it is talked to. The
portal fallbacks remain the "no extension yet" path, unchanged.

## 2. The extension and its D-Bus contract

**Layout** — `src/orcshot/resources/gnome-shell-extensions/orcshot@orcshot.org/`, ES modules:

| File | Contents |
|---|---|
| `extension.js` | enable/disable, name watcher, `Hello`, request dispatch |
| `tray.js` | today's `orcshot-tray` body, unchanged |
| `capture.js` | today's `orcshot-clipboard` body: region select, window picker, eyedropper, capture-rect, clipboard |
| `windows.js` | today's `window-calls` List/Activate logic; GPL-2.0-or-later header and attribution kept (folds into the project's GPL-3.0-or-later) |
| `metadata.json` | `uuid`, `name` "Orcshot", `description`, `shell-version` 45–50, `version-name` (ours), `url`. `version` is EGO's; never read. |
| `locale/`, `icons/`, `*.json` data | as today |

**The extension exposes nothing on D-Bus.** All seven `org.gnome.Shell.Extensions.Orcshot*`
methods and the `API_VERSION` constant go away.

**Rule: signals carry ids, methods carry data.** The app's action group gains one stateful action,
`shell-request`, state type `u` (the latest request id). It is the only outbound signal. The
Cinnamon applet and the tray, which also watch that group, receive a harmless integer.

**App-side interface the extension calls** — `org.orcshot.Orcshot.Shell` at
`/org/orcshot/Orcshot/Shell`:

```
Hello(s version_name, as capabilities)   on enable, and whenever org.orcshot.Orcshot (re)appears
GetRequest(u id) -> a{sv}                 {"kind": s, ...kind-specific params}
Deliver(u id, a{sv} result)               result, or {"ok": false, "error": s}
```

Request kinds map one-to-one onto today's methods; params and results unchanged in content:

| kind | params | result |
|---|---|---|
| `region-select` | `showMagnifier: b` | `ok, destination, pngBytes, x, y, width, height` |
| `window-picker` | — | `ok, destination, title, pngBytes, x, y, width, height` |
| `eyedropper` | — | `ok, r, g, b, a` |
| `capture-rect` | `x, y, width, height` | `ok, destination, pngBytes` |
| `set-clipboard-image` | `pngBytes` (fetched in `GetRequest`, never on the signal) | `ok` |
| `list-windows` | — | `windows` (today's List JSON) |
| `activate-window` | `id: u` | `ok` |
| `ping` | — | `ok` |

**Flow:** app allocates `n`, stores the params, sets `shell-request` to `n` → extension sees
`Changed`, calls `GetRequest(n)`, runs the existing implementation, calls `Deliver(n, …)` → app
resolves the pending request. One extra local round-trip (`GetRequest`) versus today.

**Handshake.** `capabilities` is the list of kinds the extension implements, plus `"tray"`. The
app enables Shell-native features per capability and falls back to the portal path for anything
absent. `version_name` older than the app's own bundled `metadata.json` `version-name` means GNOME
is serving a stale copy (Shell never reloads an extension without logout) — the existing
"log out and back in" notice, same wording.

**Payload size.** PNG bytes ride `Deliver`/`GetRequest` as `ay`, as the tray's icon bytes already
do. The session bus's default maximum message size is 128 MiB (dbus-daemon `max_message_size`;
dbus-broker is comparable); a 4K PNG is single-digit MiB. Recorded so nobody rediscovers it.

## 3. The app side

**One new module, `capture/shell_bridge.py`**, owns the `shell-request` action, the
`org.orcshot.Orcshot.Shell` object, and the pending-request table.

```python
bridge.has("region-select") -> bool        # from the last Hello; False until one arrives
bridge.version_name -> str | None
bridge.request("region-select", showMagnifier=True, timeout=None) -> dict   # blocks until Deliver
```

`request()` spins a nested `GLib.MainLoop` until `Deliver` for its id lands or the timeout fires.
Today `call_sync` blocked the main loop and the reply arrived on a worker thread; `Deliver` is an
incoming call on the app's own connection, which only the main loop can service. Timeouts stay as
they are per kind: infinite for the interactive kinds, short for `ping`, `list-windows`,
`set-clipboard-image`.

**The seven `gnome_*.py` modules keep their classes and callers.** Each `_call("StartRegionSelect",
…)` becomes `bridge.request("region-select", …)`; results unpacked from the dict. `gnome_tray_export.py`
is untouched. Availability probes become `bridge.has(kind)` — a dictionary lookup, no `Ping` at
startup.

**Backend selection is per call, not at startup.** `Hello` arrives asynchronously, so the Wayland
backends consult `bridge.has()` on each use and fall through to the portal path when the
capability is absent. A late `Hello` upgrades the next capture; nothing is cached wrong.

**`_check_shell_extension_health()`** keeps its notification; its condition becomes
`bridge.version_name < bundled version-name`.

**Errors.** `{"ok": false, "error": …}` → the bridge raises what the modules raise today; timeout →
the "unavailable" path callers already handle; unknown-id `Deliver` → logged and dropped.

**Deleted:** every `org.gnome.Shell` call, `enable_extension_live()`, `GetApiVersion`,
`EXPECTED_API_VERSION`, `API_VERSION`. The gsettings `enable_extension()` write stays (works under
every sandbox, proven).

**Skipped on purpose:** app-initiated cancel of an in-flight request; Escape in the overlay already
delivers `ok: false`. Add when something needs it.

## 4. Delivery per channel

**`.deb` / PPA.** `debian/orcshot.install` ships `usr/share/gnome-shell/extensions/orcshot@orcshot.org/`
instead of three directories. Cinnamon applet unchanged. First-run stays a no-op.

**Packing.** `scripts/pack-extension.sh`: `msgfmt` the `.po` files, zip the directory to
`dist/orcshot@orcshot.org.shell-extension.zip` — the layout `gnome-extensions pack` produces,
without needing GNOME Shell on the machine. Used by the EGO upload and by CI.

**Flatpak.**
- Manifest: delete `--filesystem=~/.local/share/gnome-shell/extensions:create`, the
  `bundled-extensions` module and the `bundled-cinnamon-applets` module. Keep
  `--talk-name=org.gnome.Shell`. Narrowing it to `org.gnome.Shell.Extensions` (Extension Manager's
  form) is a verification item, not a decision — #194's failed attempt predates the removal of the
  custom-interface calls that were the reason it could not be narrowed.
- First-run on GNOME: `org.gnome.Shell.Extensions.InstallRemoteExtension("orcshot@orcshot.org")`.
  GNOME shows its own "Install extension?" dialog and installs from EGO. Orcshot explains why
  beforehand and reacts to `successful` / `cancelled`. Then the gsettings enable write, unless
  verification shows GNOME's installer already enabled it.
- First-run on Cinnamon: the Spices redirect (§7).

**Snap.**
- `snapcraft.yaml`: delete the `dot-local-share-gnome-shell` plug and its reference; delete the
  `bundled-extensions` and `bundled-cinnamon-applets` parts. No extension payload at all.
- First-run on GNOME: the EGO redirect (§7) — a button that opens the extension's EGO page through
  the desktop portal, explicit steps, and the one-time connector/Extension Manager note.
- First-run on Cinnamon: nothing.
- After install, GNOME's own EGO update check keeps the extension current.

**Deleted:** `install_bundled_extension_if_needed`, `show_snap_connect_prompt`, all
`_snap_real_home_*` / `_flatpak_home_*` path helpers, `_install_bundled_extensions_for_sandboxed_channel`.
`channel_detect()` stays.

**CI.** `snap.yml`: drop `snap connect`; install the extension on the runner with
`gnome-extensions install` from the packed zip (unconfined, as a user would); keep every headless
Shell assertion; add the two in §6. `flatpak.yml`: unchanged beyond the manifest.

## 5. Publishing pipeline

**Artifacts.** `scripts/pack-extension.sh` (above). `scripts/spices-sync.sh`: copy the applet into a
local checkout of the `cinnamon-spices-applets` fork at
`orcshot@orcshot.org/files/orcshot@orcshot.org/`, bump `metadata.json`'s version, run their
`validate-spice`.

**`channels.yaml`** — two new leaves under new components (neither artifact is the Python app):

- `gnome-shell-extension.js.linux.ego` — `action:` pack, then `gnome-extensions upload --user …
  --password-file ~/.config/orcshot/ego-password --accept-tos dist/….zip`. `requirements:` runs on a
  machine with GNOME Shell ≥ 50 (`gnome-extensions upload` exists there; the Mint host has no
  `gnome-extensions` at all — the 26.04 VM over SSH, or CI); the password file is 0600, outside
  the repo, never printed (`secret-hygiene`). `confirm:` EGO's `extension-query` API lists the UUID.
  `metrics:` the same API's `downloads` field (present, read live).
- `cinnamon-applet.js.linux.spices` — `action:` sync + `gh pr create` on the fork. `confirm:` the
  Spices site's public JSON index lists the UUID at the new version. Metrics: verify at ingredient
  capture whether the index carries downloads.
- `snap` / `flatpak` stay `{}` until #198 captures them; each gains a `requirements:` line naming
  the EGO leaf.

**`RELEASING.md`** — two steps after "Full test suite", so they start early and never gate:
*Upload the extension to EGO (only if it changed)* and *Open the Spices PR (only if the applet
changed)*, each with `**One-time setup:**` (EGO account exists and the first submission is listed;
fork exists and the first Spices PR is merged) and `**Run:** /orc-publish <leaf>`. Steps
renumbered contiguously; the `/orc-release` parser run to prove it (`release-checklist`).

**"Only if it changed."** `version-name` is bumped only when the extension changes — it is the
extension's protocol version, not the app's. The app compares it to what `Hello` reports (§3).
Nothing to keep in sync by hand.

**Review-lag facts to plan around:** EGO had 297 unreviewed submissions on 2026-09-11; a maintainer
wrote in July that small diffs get priority and the GNOME Extensions Matrix channel is where to
ping. Spices: last eight merged PRs ranged from same-day to 18 days. Flathub: a permission change
(our dropped filesystem grant) holds one build for moderation.

**Carried into #198:** snap first release to `beta`; `stable` after the `dbus` declaration is
granted and one real install is confirmed.

## 6. Testing and verification

**Unit (pytest, no bus).** `shell_bridge` with an injected fake connection: request → id → `GetRequest`
→ `Deliver` resolves; timeout raises. The seven `gnome_*` tests swap mocked `_call` for mocked
`bridge.request`. First-run: one test per branch (deb no-op; Flatpak→`InstallRemoteExtension`;
Snap→EGO steps; Flatpak-on-Cinnamon→Spices steps).

**Extension, real headless Shell, in CI (`snap.yml`).** Existing load/no-JS-error assertions stay;
add: a `Hello` arrives at a stub app with the expected capabilities; one `capture-rect` round trip
completes (no interaction needed).

**Live on the VMs, before packaging is touched.**
1. `.deb` on 26.04 Wayland: every capture mode, tray, clipboard, window picker, eyedropper against
   the merged extension. The regression gate for §3.
2. Same on 24.04 (GNOME 46), the oldest supported Shell.
3. Flatpak on 26.04: the `InstallRemoteExtension` flow once the EGO listing exists; until then the
   extension installed by hand and the same feature pass.
4. Snap on 26.04: first-run → EGO redirect → extension installed via Extension Manager as a stock
   user would → `Hello` closes the dialog → same feature pass. `review-tools` reports only the
   `dbus` hold.
5. Mint: no VM exists. Create one for the Spices flow, or defer explicitly with the reason recorded.

**Store-side, as `VERIFICATION.md` scenarios:** `dbus` declaration granted; EGO first submission
listed; Spices PR merged; Flathub manifest lints clean without the filesystem grant.

Every "works" claim in the plan cites a command and its output (`verify-before-asserting`).

## 7. First-run wording, verbatim

All dialogs: title **Orcshot Setup**, buttons **Later** and one action button; they close
themselves when `Hello` arrives. **Later** leaves Orcshot fully usable via the portal path; the
dialog comes back through the editor's existing *Setup…* entry, which re-runs first-run setup
(no new Preferences control - found while implementing).

**Snap on GNOME**

> **One more step for the tray icon and Wayland capture**
>
> Orcshot's tray icon, region selection and window picker on Wayland run inside GNOME Shell as an
> extension. Snap packages aren't allowed to install extensions, so this one comes from GNOME's own
> extension site.
>
> **1.** Click **Open extensions.gnome.org** below.
> **2.** On the Orcshot page, switch the toggle to **ON**.
> **3.** That's it — this window closes by itself when the extension is running.
>
> *If the page says your browser needs the GNOME Shell integration add-on:* install the add-on it
> links to, then on Ubuntu run `sudo apt install gnome-browser-connector` (or install **Extension
> Manager** from the Software app and search for Orcshot there). This is a one-time setup for any
> extension, not just Orcshot's.
>
> Without the extension Orcshot still works — captures use GNOME's screenshot service and there's
> no tray icon.
>
> [ Later ]  [ Open extensions.gnome.org ]

**Flatpak on GNOME**

> **One more step for the tray icon and Wayland capture**
>
> Orcshot's tray icon, region selection and window picker on Wayland run inside GNOME Shell as an
> extension. Click **Install extension** and GNOME will ask you to confirm.
>
> Without it Orcshot still works — captures use GNOME's screenshot service and there's no tray icon.
>
> [ Later ]  [ Install extension ]

**Flatpak on Cinnamon**

> **One more step for the tray icon**
>
> Orcshot's tray icon on Cinnamon is an applet from Mint's applet library.
>
> **1.** Open **System Settings → Applets**.
> **2.** Choose the **Download** tab and search for **Orcshot**.
> **3.** Click the install arrow, then add it to your panel from the **Manage** tab.
>
> This window closes by itself when the applet is running. Without it Orcshot still works; there's
> just no tray icon.
>
> [ Later ]  [ Open the Orcshot applet page ]

**`.deb`:** no dialog. **Snap on Cinnamon:** no dialog.

## Verification items the plan must close (not decisions — facts to check while building)

1. Does GNOME's `InstallRemoteExtension` enable the extension after installing, or only install it?
   Determines whether the Flatpak first-run still needs the gsettings write.
2. Can `--talk-name=org.gnome.Shell` be narrowed to `org.gnome.Shell.Extensions` now?
3. Does GNOME Shell load a newly installed per-user extension live, or only at next login? Changes
   only the dialogs' wording.
4. Which name `InstallRemoteExtension` must be called on (`org.gnome.Shell` vs
   `org.gnome.Shell.Extensions`) on GNOME 46 and 50.
5. Does the Spices JSON index carry download counts (for `metrics:`)?
6. Minimum GNOME Shell version that ships `gnome-extensions upload` (50 has it; 46 unchecked).
7. A Mint VM for the Spices flow — create, or record the deferral.

## Out of scope

- Applying the `snap` and `flatpak` ingredients to this project (`/orc-package`) — #198, after this
  lands. The ingredients themselves are written into Orclab from this day's research; `ego` and
  `spices` ingredients follow once each first submission has actually gone through.
- RPM/Arch (#132). Metrics (#186). Credentials setup beyond what the two new leaves need (#197).
- Cinnamon on Snap (decided: nothing). Any change to the `.deb`'s Cinnamon applet install.
