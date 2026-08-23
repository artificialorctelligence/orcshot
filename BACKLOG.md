# Backlog

Open items not yet scheduled into a task. Each entry keeps the context that
led to it - not just "what," but "why this matters" - so picking it up later
doesn't require re-deriving the reasoning from scratch.

## #177: "Online Help" menu item opens the bare repo instead of the wiki it could now use

Found by a REQUIREMENTS.md sweep (2026-08-23), then re-checked against current code before filing (not
just trusted as still accurate) - and the situation has genuinely changed since it was originally written.
`editor_window.py`'s `_do_open_online_help` (task #95 part 1) still opens
`https://github.com/artificialorctelligence/orcshot` - its own docstring says why: "real help-page
content... doesn't exist yet... tracked separately... since it's content-writing, not code." True when
written. Not true anymore: the wiki now has real content (the "Destinations" page added earlier this same
session), and this exact file already has a working `_WIKI_URL` constant
(`https://github.com/artificialorctelligence/orcshot/wiki`, task #142) - just used by a *different* help
dialog (the tool-shortcuts reference), never wired to this menu item.

Concretely actionable now, not just "someday, once content exists": point `_do_open_online_help` at
`self._WIKI_URL` instead of the bare repo root. A one-line fix, no content-writing blocker left.

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

## #174: "Show magnifier while selecting" preference ignored by the Wayland Shell-native overlay

Found during task #168's audit (2026-08-23). `settings.get_show_magnifier_while_selecting()` is honored by
both `RegionSelectWindow` (X11) and `WaylandRegionSelect` (the portal-fallback path) - but the *preferred*
Wayland path, `extension.js`'s own `RegionSelectOverlay`, never reads it at all: the magnifier always shows
there regardless of the user's preference. Already self-documented as a known gap in `settings.py`'s own
docstring ("a real, documented platform gap, not a silent one") and in the Capture tab's own checkbox
tooltip - but still live, and easy to forget now that the surrounding code (task #168's constant-sharing
fix) has moved on.

direflail's own call: this needs fixing, not just documenting. Likely direction: thread the setting's
value into the D-Bus call that starts `RegionSelectOverlay` (`region_select_gnome_shell.py`'s own call
into the extension), the same kind of channel task #113 already built for destination-picker data - there's
currently no such channel from `settings.json` into that D-Bus call at all, which is the actual gap, not
the overlay code itself.

## #175: Multi-monitor Wayland capture - crop-offset origin assumption never verified against real hardware

Long-standing, not new: found independently by both task #168's code audit and a separate sweep of
`REQUIREMENTS.md` (2026-08-23), which turned up the same concern restated at least five times across
weeks of entries (`## Task #49 ("Add Wayland support") status`'s own "Known, deliberately non-blocking
gaps" section, and referenced again in at least four earlier entries) - always "untested," never closed,
because this project's only Wayland test rig is a single-monitor VM.

`capture/wayland.py`'s `_crop_to_rect` assumes the portal's screenshot image starts at the virtual screen's
own origin (`bounds.left`, `bounds.top`). Checked directly (2026-08-23, not just re-read): the crop
*arithmetic itself* is sound for negative-origin monitors - traced through concrete numbers (a monitor at
x=-1920) and confirmed it maps to the correct pixels, no sign bug. The genuine unknown isn't the math, it's
the *assumption* - whether the portal's actual real-world output on real multi-monitor Wayland hardware
really does start exactly where this code expects. Needs a real multi-monitor Wayland session to close;
nothing in this project's current test setup can settle it.

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
