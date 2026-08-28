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

## #184: Explore a Wayland capture path that doesn't depend on the bundled GNOME Shell extension, to open up Snap and Flatpak

Surfaced during a conversation with direflail (2026-08-28) about why Orcshot isn't discoverable via GNOME
Software/App stores on Ubuntu - confirmed live that GNOME Software's browsable catalog doesn't surface
plain apt/PPA packages at all on either 24.04 or 26.04, regardless of caching state, and the only way in
is Snap or Flatpak.

The bundled GNOME Shell extension (`orcshot-clipboard@orcshot.org`) is what currently powers the
Wayland-native fast path: the window picker, the translated tray menu on Wayland, Shell-native region
select. Real research this session (not assumed) found the sandboxing story is more nuanced than first
guessed:

- Flatpak's rejection in this doc's own Packaging section ("avoids Flatpak's sandbox tendency to force
  portal-mediated capture even under X11") is specifically about X11 - doesn't automatically rule out
  Wayland-only Flatpak/Snap builds.
- Snap's strict confinement can get *direct* X11 access via the plain `x11` interface (confirmed against
  Flameshot's real, published `strict`-confinement snapcraft.yaml) - not portal-forced the way Flatpak is.
- The Shell extension itself doesn't strictly require the system-wide `/usr/share/gnome-shell/extensions/`
  path that only `.deb`'s root-privileged postinst can write to - GNOME Shell has always supported a
  per-user path (`~/.local/share/gnome-shell/extensions/<uuid>`, confirmed via GNOME's own admin docs),
  reachable with the ordinary `home`/`--filesystem=home` grants both Flatpak and Snap commonly hand out.
  Not yet proven for Orcshot specifically - would need an actual prototype.

**What this task is actually about**: rather than relying on that per-user-path workaround to keep the
existing Shell-extension architecture alive inside a sandbox, consider whether the Wayland fast path
could be redesigned to not depend on a GNOME Shell extension at all - something portable across
compositors and packaging formats, not just GNOME-Shell-specific machinery smuggled through a permission
grant. Worth weighing against what's actually lost: the Shell extension is also what gets you the
translated tray menu, the Shell-native window picker, and per [[feedback-extension-reload-caching]],
whatever replaces it needs its own answer to "how does a code change actually take effect" that doesn't
require a full logout/login either.

Not scoped, not designed, no decision made - direflail wants to think it over.

## #185: A Wayland-only Flatpak build, alongside the existing dual-mode (X11+Wayland) `.deb`/PPA release

Same conversation as #184 (2026-08-28), a narrower and more incremental alternative to it. Rather than
redesigning the Wayland capture path, ship a *second*, separate build specifically for Flatpak that drops
X11 support entirely, while leaving the current `.deb`/PPA release exactly as it is today (full X11 +
Wayland, direct X11 access, the Shell extension, everything).

**Why this sidesteps the original Flatpak rejection cleanly**: that rejection was specifically about
Flatpak forcing X11 captures through the portal, fighting the direct-X11-access priority. A build with no
X11 support at all has nothing for that objection to apply to - its only capture path would go through
the XDG portal, which is exactly what `WaylandCaptureBackend` already does as Orcshot's own non-extension
Wayland fallback today, sandboxed or not. Not a new cost Flatpak introduces, just the existing fallback
becoming the only path in that specific build.

**Real cost, not hidden**: X11 users (Mint/Cinnamon, X11-session Ubuntu) would need the `.deb`/PPA
instead, same as today - this build wouldn't replace anything, it'd sit alongside it as a second,
narrower distribution channel aimed specifically at Wayland users who want Flathub discoverability. The
Shell-extension-features question from #184 (per-user install path, unproven for Orcshot) applies here
too, if this build wants feature parity rather than portal-only capture.

Not scoped, not designed, no decision made - direflail wants to think it over.

## #181: Crop-offset origin assumption unverified specifically for non-GNOME Wayland compositors

Narrowed successor to the old #175 (closed for GNOME - see REQUIREMENTS.md's Task #175 entry for the full
resolution). `capture/wayland.py`'s Wayland path reads monitor geometry through GDK's compositor-agnostic
enumeration (`gdk_screen_layout`), not a GNOME-specific API, so in principle a different Wayland compositor
(KWin, a wlroots-based one) could use a different coordinate convention for `bounds.left`/`bounds.top` than
Mutter's proven-always-non-negative guarantee. Not checked, and not urgent: orcshot's Wayland support is
built around a bundled GNOME Shell extension and isn't a supported target on other compositors anyway -
revisit only if that ever changes.
