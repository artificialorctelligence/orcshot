# Backlog

Open items not yet scheduled into a task. Each entry keeps the context that
led to it - not just "what," but "why this matters" - so picking it up later
doesn't require re-deriving the reasoning from scratch.

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

## #180: Stale pre-migration XDG autostart entry races orcshot.service at boot

Found live (2026-08-23) as a genuine side effect while verifying task #174 on the Wayland VM, not by
inspection - a real, reproducible boot-time instance of task #170's exact symptom (`systemctl status`
showing `inactive`/exited-0 while a real, working, untracked process owns the D-Bus name), but from a
*different* trigger than #170's own fix covers.

Root cause: `~/.config/autostart/orcshot.desktop` (dated well before task #141's systemd-unit migration,
`Exec=/usr/bin/orcshot` - a bare exec, plus a stale dev-checkout icon path) was still present on this VM.
GNOME session's own XDG-autostart mechanism launches it independently of, and racing against,
`orcshot.service`'s own `WantedBy=graphical-session.target` startup - confirmed live: after a real VM
reboot, `orcshot.service` itself exited cleanly within 3ms (the *correct*, safe forwarding behavior for a
second instance losing the race - not a crash), while a separate, systemd-untracked process from the
autostart entry ended up owning `org.orcshot.Orcshot` on the session bus.

Not a flaw in task #170's own fix - that fix wraps the *current* entry points (the Applications-menu
`.desktop` file, the four global hotkeys), and correctly prevents *those* from racing. This is a third,
independent launch path task #170 never touched, left over from before `autostart.py` was rewritten to
manage a systemd unit instead of writing its own XDG autostart file. `autostart.py`'s own docstring
("Unlike the .desktop-writing functions this replaces...") documents *what* replaced the old mechanism but
never mentions cleaning up an old file a previous version had already written - any real install that had
autostart enabled before that migration would carry this exact stale file forward, silently, forever.

Likely direction: `enable_autostart()`/`disable_autostart()` (or a one-time migration step alongside
`maybe_seed_default_external_commands`'s own pattern) should remove `~/.config/autostart/orcshot.desktop`
if it exists, not just leave the systemd unit as the only *new* mechanism. Cleaned up manually on this one
VM to unblock #174's own testing; not fixed in code.

## #175 RESOLVED (2026-08-23): non-GNOME Wayland compositors unverified for the crop-offset origin assumption

Was: "crop-offset origin assumption never verified against real hardware" - the long-standing concern
(restated at least five times across `REQUIREMENTS.md`, `## Task #49` status entry included) that
`capture/wayland.py`'s `_crop_to_rect` assumes the portal's screenshot starts at `bounds.left`/`bounds.top`,
untestable because this project's only Wayland rig was a single-monitor VM.

Closed for GNOME: set up a real 2-monitor Wayland session (VirtualBox `setscreenlayout`, `monitorcount=2`)
and drove Mutter's own `org.gnome.Mutter.DisplayConfig.ApplyMonitorsConfig` directly to attempt a
negative-origin arrangement. It was rejected live - `"Invalid logical monitor position (-1366, 0)"` -
which traces to Mutter's own `meta_verify_logical_monitor_config` (confirmed against upstream Mutter
source): any logical monitor with x<0 or y<0 is refused outright, unconditionally, before any layout is
even applied. Since `ScreenLayout.virtual_bounds` (`capture/backend.py`) is the union of individual
monitor bounds, and Mutter guarantees every individual monitor origin is non-negative, `bounds.left`/
`bounds.top` can never be negative on GNOME either - the exact case `_crop_to_rect`'s old comment worried
about is structurally impossible there, not just untested. Comment updated in `wayland.py` to state this
as a proven guarantee instead of an open question.

Residual, deliberately narrow: orcshot's Wayland capture path goes through GDK's compositor-agnostic
monitor enumeration (`gdk_screen_layout`), not a GNOME-specific API, so in principle a different Wayland
compositor (KWin, a wlroots-based one) could report a different coordinate convention - not checked, and
not urgent, since orcshot's Wayland support is built around a bundled GNOME Shell extension and isn't a
supported target on other compositors anyway.

## #176: Cross-monitor drag continuity (region-select/eyedropper/window-picker) never verified on real Wayland hardware

Found during task #168's audit (2026-08-23), narrower than it first looked once actually read: `ui/
monitor_window.py`'s own docstring already makes a sound claim that ordinary event-to-window routing (motion/
button events going to whichever window is physically under the cursor) is universal windowing behavior, not
something Wayland-specific needing verification - true on every desktop, X11 included. The real open question
is more specific and wasn't previously named this precisely: does an *in-progress drag* (a region-select
rectangle, an eyedropper follow) that starts on one monitor's own top-level `MonitorWindow` correctly
continue once the cursor crosses onto a second monitor's separate window, or does it break/reset at the
boundary? Wayland's per-monitor-TOPLEVEL architecture (necessary here since Wayland forbids absolute window
positioning - see that module's own docstring) makes this a real, monitor-boundary-specific question X11's
single spanning `POPUP` window never has to answer. Only ever tested on this project's single-monitor VM;
needs real multi-monitor Wayland hardware to settle.

## #173: No i18n/translation infrastructure - every string is a hardcoded English literal

Scoping decision from task #93 (2026-08-10), recorded in REQUIREMENTS.md but never carried over into this
file (which didn't exist yet at the time) - resurfaced by direflail's own recollection, 2026-08-23.

Real Windows Greenshot ships 39 translations (`Greenshot/Languages/language-*.xml` - ar-SY, ca-CA, cs-CZ,
da-DK, de-DE, de-x-franconia, el-GR, en-US, es-ES, et-EE, fa-IR, fi-FI, fr-FR, fr-QC, he-IL, hu-HU, id-ID,
it-IT, ja-JP, kab-DZ, ko-KR, lt-LT, lv-LV, nl-NL, nn-NO, pl-PL, pt-BR, pt-PT, ro-RO, ru-RU, sk-SK, sl-SI,
sr-RS, sv-SE, tr-TR, uk-UA, vi-VN, zh-CN, zh-TW), each a `LanguageKey`-driven resource file (~304
`<resource>` entries in `language-en-US.xml` alone). Orcshot has zero i18n infrastructure - every
user-facing string across the whole `ui/` tree is a hardcoded English literal in the Python source, not a
lookup against any resource table.

Not attempted as part of task #93 or since - explicitly scoped out at the time as "not a Preferences-
dialog checkbox; it's a foundational rework (extract ~300+ literals into a resource/gettext layer, wire
every widget construction site to look them up, then translate and maintain N language files) that
touches nearly every file under `ui/`." That characterization still holds; nothing about the size or shape
of the effort has changed since. Likely direction, if picked up: standard Python `gettext`
(`.po`/`.mo` files, `_()` wrapping at each call site) rather than inventing a bespoke resource-table format
the way the real Windows app's own XML scheme does - `gettext` is the established Linux/GTK convention and
would compose naturally with `debian/rules`' existing packaging rather than needing new build tooling.
Scope alone (300+ literals, every `ui/` file, N language files to actually translate and maintain) makes
this a dedicated effort of its own, not something to fold into an unrelated task.
