# Backlog

Open items not yet scheduled into a task. Each entry keeps the context that
led to it - not just "what," but "why this matters" - so picking it up later
doesn't require re-deriving the reasoning from scratch.

## #186: Find out what download/install metrics are actually available, across every channel

direflail's own request (2026-08-28): "find out what metrics we can get about how many downloads we
get. i don't want anything but numbers to make myself feel good." Explicit constraint, not just phrasing
- this is about checking what the existing distribution channels already expose, not about adding any
kind of tracking, telemetry, or analytics to Orcshot itself. No phone-home code, no third-party analytics
script on the wiki, nothing that reports on real users - just reading whatever numbers Launchpad/GitHub
already publish on their own.

**Already confirmed real, no research needed**: GitHub Releases exposes a genuine per-asset download
counter today - `gh release view v0.2.0 --json assets` (used earlier this same session to verify the
`.deb` attached correctly) returned a real `downloadCount` field per asset, currently `0` since the
release just went live. Trivial to check any time with that same command.

**Not yet checked**: whether Launchpad exposes any public download/install statistics for PPA packages
at all - historically a well-known gap/frustration in the Launchpad community (unlike Debian's opt-in
popularity-contest mechanism), but not confirmed one way or the other for this project's own PPA, not
assumed. Also unchecked: whether `apt install` from the PPA is even the kind of thing Launchpad *could*
count (PPA downloads happen from Launchpad's own mirror infrastructure, not a single tracked endpoint the
way a GitHub Release asset is).

Not investigated yet - direflail wants this recorded as a task, not resolved right now.

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

**Confirmed wanted (direflail, 2026-08-28): "we definitely want to do this."** Ready to move past the
thinking-it-over stage whenever picked up - next step is the brainstorming skill's normal process
(questions, approaches, a real design) before any implementation, given the scope here (redesigning a
core capture subsystem) is squarely architectural, not a small bounded change.

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

**Why "Wayland-only" isn't just the simpler option, it's close to the only real option**: direflail asked
directly whether *also* declaring X11 support in the same Flatpak build alongside Wayland would exclude
it from Flathub - confirmed via Flatpak's own sandbox-permissions docs that it's not a store-policy
rejection, it's a sandbox mechanism: "if an application works with Wayland natively, access to the x11
socket and the fallback-x11 socket will be explicitly revoked to force the application to run in a
Wayland window at all times." So a dual-mode manifest would only ever actually exercise its X11 path on
sessions with no Wayland present at all - on any session that can reach Wayland (the exact audience a
Flathub listing is trying to reach), Flatpak strips the X11 socket regardless of what's declared. Not
confirmed either way: whether an X11-only manifest (no Wayland socket declared at all) still forces
screenshot-specific captures through the portal separately from general X11 window access, or whether raw
capture works directly there - unresearched, flagged rather than guessed at.

**Real risk, confirmed rather than assumed: no store-level filtering exists for this.** Checked
specifically whether Flathub/GNOME Software/Mint's Software Manager hide a Wayland-only app from X11
sessions at browse time - found no evidence any such filtering exists. Mint ships Flatpak/Flathub by
default (unlike Ubuntu), so a Wayland-only Orcshot would show up in search on a plain X11 Mint session
exactly the same as anywhere else, install fine, and then most likely fail outright on launch - no
`x11`/`fallback-x11` socket declared at all means no display connection to fall back to, and without any
socket the app can't even draw an error dialog explaining why. Real tension with this project's own "if
it can't work correctly, don't ship it looking like it works" bar (same standard behind the greyed-out
Window Picker item when the Shell extension isn't available).

**direflail's own leaning on this (2026-08-28)**: mitigate at the *listing* level rather than the runtime
level - put a link in the Flathub description pointing X11 users at the full dual-mode version (the
`.deb`/PPA, via the GitHub README) rather than trying to detect-and-explain the failure at runtime. Doesn't
eliminate the failure-on-launch risk for someone who installs anyway without reading the description, but
is a real, cheap piece of the mitigation, decided rather than left open.

Not scoped, not designed, no decision made - direflail wants to think it over.

## #132: RPM-family distros (Fedora, openSUSE) and Arch/AUR - real scope, not yet started

Already referenced in passing in `RELEASING.md` step 7 ("a separate, later effort") with zero detail
anywhere - this entry is the actual sizing, worked through with direflail (2026-08-28) after the Snap/
Flatpak conversation raised the natural follow-up question. Explicitly a "maybe at some point" - not
committed to, not scheduled, just no longer a bare cross-reference to nothing.

**Why this is a genuinely separate track, not a fourth target alongside the existing three**: Mint,
Ubuntu 24.04, and Ubuntu 26.04 all share one `.deb` today precisely because they're all Debian-family -
`RELEASING.md` step 6 says outright that `Architecture: all` with no series-specific build-deps means one
upload covers everything, no per-target packaging work. Fedora breaks that assumption entirely:

- **New packaging format**: an RPM `.spec` file, different tooling (`rpmbuild`/`rpmlint` vs.
  `dpkg-buildpackage`/`lintian`) - though Fedora's `%pyproject_*` macros are a real, mature equivalent to
  Debian's `pybuild` for a `pyproject.toml`+hatchling project like this one, not exotic territory.
- **Real dependency-name research, not assumed**: every line of `debian/control`'s deps needs its actual
  Fedora name found and verified - `python3-gi` → `python3-gobject`, `gir1.2-gtk-3.0` → Fedora's own
  GTK3/typelib split, and down the rest of the list (hatchling, pytest, hypothesis, scipy, numpy, shapely,
  xlib, rsvg, gdkpixbuf, pango, glib). Almost certainly all exist given Fedora's own strong Python
  packaging culture, but "almost certainly" isn't this project's bar for anything else, and shouldn't be
  here either.
- **Its own hosting**: Fedora's PPA-equivalent is COPR - a new one-time setup, parallel to the existing
  Launchpad PPA config.
- **Its own live compat round, not a rerun of the existing one**: Fedora Workstation defaults to
  GNOME/Wayland even more consistently than Ubuntu, so the existing Shell-extension architecture should
  carry over conceptually - but Fedora ships newer GNOME Shell versions faster than Ubuntu LTS does, the
  same axis (GNOME Shell version drift) that already caused real, documented bugs between 24.04 and 26.04
  this project has directly hit. A real Fedora VM and its own logout/login reload-testing cycle
  ([[feedback-extension-reload-caching]]) is needed, not assumed to just work.

**Net assessment**: comparable in scope to the *original* `.deb` packaging effort, not a cheap addition
to what already exists. openSUSE (also RPM-based) and Arch/AUR would each need their own version of this
same research even if the RPM spec itself carries over partially to openSUSE - not free just because
Fedora's done first.

Not scoped, not designed, no decision made - explicitly lower priority than #184/#185.

## #181: Crop-offset origin assumption unverified specifically for non-GNOME Wayland compositors

Narrowed successor to the old #175 (closed for GNOME - see REQUIREMENTS.md's Task #175 entry for the full
resolution). `capture/wayland.py`'s Wayland path reads monitor geometry through GDK's compositor-agnostic
enumeration (`gdk_screen_layout`), not a GNOME-specific API, so in principle a different Wayland compositor
(KWin, a wlroots-based one) could use a different coordinate convention for `bounds.left`/`bounds.top` than
Mutter's proven-always-non-negative guarantee. Not checked, and not urgent: orcshot's Wayland support is
built around a bundled GNOME Shell extension and isn't a supported target on other compositors anyway -
revisit only if that ever changes.
