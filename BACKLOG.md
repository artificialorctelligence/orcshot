# Backlog

Open items not yet scheduled into a task. Each entry keeps the context that
led to it - not just "what," but "why this matters" - so picking it up later
doesn't require re-deriving the reasoning from scratch.

## #187: Prove (or disprove) whether `fallback-x11` gives real, unrestricted X11 capture under Flatpak

Surfaced directly questioning #185's "Wayland-only" framing (direflail, 2026-08-28): "you're SURE we can't
just use that fallback socket to run it in x11 anyway?" Good pushback - the honest answer right now is
reasoned, not proven, and the reasoning actually points the other way from what #185 assumed.

**The case for it working, not just as a redirect dialog but as real capture**: X11 itself has no
per-client security model at all - Flatpak's own sandbox-permissions docs say outright, "X11 lacks GUI
isolation, making any attempt of sandboxing futile." Once a `fallback-x11` socket is actually live (which
it is on a genuine pure-X11 session - only revoked when Wayland is also present, confirmed earlier for
#185), the connected client should have the exact same unrestricted X11 protocol access an unsandboxed
client would - there's no mechanism for Flatpak to selectively block screen-content reads while allowing
window drawing, because X11 doesn't support that granularity to begin with. If that holds, Orcshot's
existing `X11CaptureBackend` should work completely unmodified through that socket, no portal involved.

**Why this isn't already assumed true**: the original Flatpak rejection in this doc's own Packaging
section uses the word "tendency," not a documented technical wall - reads more like it may have been
ecosystem convention (portable capture libraries often auto-detect Flatpak sandboxing via
`/.flatpak-info` and route to the portal unconditionally as a *design choice*, independent of whether
direct X11 access happens to also work) than something actually verified for this specific case. Worth
being honest that swapping one unverified claim for another isn't progress - this needs a real test.

**The actual test, cheap and already possible on this machine**: a minimal `flatpak-builder` manifest
declaring only `wayland` + `fallback-x11` sockets (nothing else), making one real X11 capture call from
inside the sandbox on this host's own X11 (Mint/Cinnamon) session, and checking whether it succeeds or
hits some sandbox-level restriction. Direct, empirical, no VM needed - Flatpak's already confirmed
available here.

**Why this matters beyond curiosity**: if it works, #185's whole "Wayland-only, X11 users redirected
elsewhere" framing may be unnecessarily narrow - a single Flatpak build might genuinely work on both X11
(via fallback-x11, full native capture) and Wayland (via the portal or #184's redesigned path), using the
same kind of session-type branching `backend_select.py` already does in the `.deb` today, instead of
needing the listing-link/runtime-redirect mitigations #185 currently plans for.

direflail's own sequencing (2026-08-28): after #184 (the Snap-capable Wayland redesign), which is next up.

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

**Hard constraint, stated explicitly (direflail, 2026-08-28): "whatever the plan is, it must include being
compatible with snap, flatpak, software manager, and apt. i don't want any more surprises at distribution
time."** Not a nice-to-have - the design needs to hold up across all four from the start, not get
retrofitted after landing on one and discovering it breaks another (which is exactly what happened with
the original Flatpak rejection, and what #187 is now re-litigating with real evidence instead of
assumption). "Software Manager" here likely means Mint's own `mintinstall`, not GNOME Software
specifically - worth confirming which the whole "surprises" list actually means before designing, since
GNOME Software's own discoverability ceiling (confirmed earlier: won't show a plain apt/PPA package at
all, only Snap/Flatpak) isn't something this redesign can independently fix - it's already covered by
"Snap" and "Flatpak" being separately on the list.

**Direct sequencing from direflail (2026-08-28): this is next, ahead of #187 and #185's own further
design.**

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

**Design progress (2026-08-28), from a real brainstorming session with direflail - most of this is now
verified live, not theorized:**

- **Region-select and clipboard are already solved, today, with zero extension dependency.** Read the
  actual code rather than assumed: `WaylandCaptureBackend` (portal-based pixel grab) +
  `region_select_wayland.py` (Orcshot's own client-side overlay, loupe included - `draw_magnifier`,
  `_show_magnifier`, real and active) is *already* the automatic fallback whenever the Shell extension
  isn't available, already confirmed live against the real portal backend. Same story for
  `WaylandClipboardBackend`. Neither needs redesigning - they're already the portable answer.
- **The `org.gnome.Shell` D-Bus wall is real, confirmed via direct precedent**: a strict-confinement Snap
  trying to call GNOME Shell's own D-Bus interfaces (same class of call Orcshot's bundled extension uses -
  `BUS_NAME = "org.gnome.Shell"`, confirmed in `gnome_clipboard.py`) got denied by AppArmor with no
  interface to fix it - a Snap maintainer's own words: "the trust model of snaps (untrusted and hence
  confined) is not compatible with gnome-shell extensions (trusted, deeply integrated with the desktop,
  unconfined...)." Anything still calling `org.gnome.Shell` directly carries this same risk under strict
  confinement; anything using only the standard portal (`org.freedesktop.portal.Desktop`) shouldn't, since
  portals are the actual sanctioned bridge for confined apps.
- **The XDG portal's `Screenshot` interface has a `target` option (v3: Screen/Window/Area/Active Window)
  that Orcshot's own `wayland_portal.py` already defines constants for but never uses** (only
  `TARGET_SCREEN` is called anywhere). Live-tested `target=Area`: works, renders GNOME's own native
  Screenshot UI (Selection/Screen/Window tabs) - genuinely GNOME's real screenshot tool, not a bare portal
  placeholder, confirmed via a live VirtualBox screenshot of the actual rendered UI.
- **`target=Window` was tested twice.** First attempt showed a black screen - traced to a real crash
  (`xdg-desktop-portal-gnome.service: Main process exited, code=dumped, status=11/SEGV`), but a clean
  retest (session confirmed awake, not idle/locked first) rendered fine with zero portal errors in the
  journal - the crash was session-timeout interference, not a real bug in the feature. Corrected from an
  earlier wrong conclusion that `target=Window` was broken.
- **`target=Window` was rejected anyway, on a real product principle, not a technical one.** Even working,
  it hands the entire window-picking interaction to GNOME's own native Screenshot app - GNOME-branded
  chrome, not Orcshot's. The portal owns that UI end-to-end opaquely; there's no way to get raw window
  data back for Orcshot to render its own picker on top of it. direflail's own words: "i do not want to
  use another screenshot app. that's why we developed orcshot." Recorded as a standing principle -
  [[feedback-no-delegating-to-other-screenshot-apps]] - not just a decision local to this task: Orcshot
  must never hand any piece of its own UX to another screenshot app's own interface, even via a sanctioned,
  portable mechanism like a portal.

**Resulting shape of the design, not yet fully written up as a spec:**

- Region-select, clipboard: unchanged, already extension-free, already proven.
- Window Picker: stays on the third-party `window-calls` extension - not replaced by the portal, per the
  principle above. This is the one piece that keeps the real `org.gnome.Shell` dependency and its
  associated Snap-confinement risk; everything else avoids it.
- **Tray icon/menu - redesigned further (2026-08-28), not just "translate the existing AppIndicator3
  menu."** direflail pushed back hard on settling for AppIndicator3's known icon-alignment limitation,
  correctly identifying that the underlying stack is genuinely legacy tech, not just "proven and safe."
  Verified, not assumed:
  - `libayatana-appindicator` (what Orcshot uses today, the "3" in `AyatanaAppIndicator3`) is **officially
    declared obsolete by its own upstream** - its own GitHub description: "Gtk-based, DBusMenu-based,
    OBSOLETE, please use libayatana-appindicator-glib for new implementations."
  - The real successor, `libayatana-appindicator-glib` (2.0.3, actively released), drops dbusmenu entirely
    in favor of `org.gtk.Menus`/`org.gtk.Actions` (GMenuModel/GActionGroup) - confirmed no dbusmenu
    fallback/compat mode exists.
  - **Orcshot doesn't need that library as a dependency at all** - `Gio.DBusConnection.export_menu_model()`/
    `export_action_group()` are core, official PyGObject/Gio APIs (confirmed against
    api.pygobject.gnome.org's own class docs), already the same `Gio` module used throughout this
    codebase. Publishing a GMenu-based tray menu is achievable with zero new dependencies.
  - **The real gap, confirmed by checking actual source, not assumed**: no GNOME Shell extension anywhere
    renders GMenu-model-published SNI menus. Checked the Ayatana org's own repo list (no GNOME Shell
    extension maintained by them at all - their only confirmed renderer is `qmenumodel`, a Qt5/KDE one);
    checked both real GNOME candidates' actual source directly (`ubuntu-appindicators@ubuntu.com` and
    `status-tray`) - zero GMenu-handling code in either. The SNI spec's own `Menu` property is just an
    untyped D-Bus object path (`<property name="Menu" type="o"/>`, confirmed from
    `notification-item.xml`) - "dbusmenu lives there" has only ever been convention, never something the
    interface itself declares, so a *general* watcher has no standard way to know when to expect GMenu
    instead.
  - **Snap compatibility, confirmed against real policy source, not assumed**: `org.kde.StatusNotifierWatcher`
    (the actual tray-icon registration mechanism, itself implemented by a Shell extension today) is
    explicitly on the sanctioned list for Snap's standard `desktop` interface (`snapd`'s own
    `interfaces/builtin/desktop.go`). This is concrete proof that "a Shell extension is involved" was never
    the disqualifying factor - what got denied before (`org.gnome.Shell` itself, confirmed via the
    Extension Manager AppArmor precedent) is a *different*, unsanctioned name, called in the *opposite
    direction* (Orcshot's confined code reaching out to it). A new design where Orcshot only ever exports
    on its own connection, and an unconfined Shell extension reads *from* Orcshot rather than Orcshot
    calling *into* anything privileged, doesn't hit that wall - Shell extensions are never Snap-confined
    in the first place, regardless of which direction anything points.
  - **Decision: build a new, Orcshot-specific GNOME Shell extension for this, not a general-purpose one.**
    direflail's own call, backed by real technical reasoning, not just scope discipline: scoping narrowly
    sidesteps the SNI `Menu`-property ambiguity above entirely (a general watcher has to guess/negotiate
    protocol for arbitrary apps; an Orcshot-specific one just already knows what to expect from Orcshot)
    and avoids competing for `StatusNotifierWatcher` ownership at all (no need to be a general watcher,
    just needs to find and render Orcshot's own indicator) - the same ownership-race problem that makes
    `status-tray` silently inert against `ubuntu-appindicators` on real Ubuntu/Mint targets, sidestepped by
    construction rather than fixed. Also finally fixes the icon-alignment bug for real, since Orcshot would
    control the entire rendering path end to end - no third-party `dbusMenu.js` hard-coding
    `xAlign: Clutter.ActorAlign.END` to work around.
  - **Core mechanism proven live (2026-08-28), not just reasoned about.** Built a minimal real test: a
    Python script exporting a `Gio.Menu` + `Gio.SimpleActionGroup` over D-Bus on its own well-known name
    (`Gio.DBusConnection.export_menu_model`/`export_action_group`), and a bare `gjs` script (same
    methodology this project already used to verify the tray-menu gettext bug in task #183) consuming it
    via `Gio.DBusMenuModel`/`Gio.DBusActionGroup` - the exact runtime `gnome-shell` itself uses. Real data
    round-tripped correctly: labels, action names, and **the icon attribute** all arrived intact
    (`icon=test-icon-1`, exactly as published). Actions become available via `action-added` signals with
    correct bare names (not the menu's own `group.action` prefixed form - that prefix is a local
    menu-mounting convention, not part of the wire format) after some real async proxy-sync latency - a
    normal D-Bus proxy behavior a real implementation handles by reacting to signals, not a defect.
  - **Still open, and now the actual next real question**: this test used a plain custom bus name
    (`org.orcshot.TrayTest`), not real SNI/`StatusNotifierWatcher` registration for the tray *icon* itself
    - the menu-export mechanism is proven, but how the new extension actually discovers "this is Orcshot's
    indicator, here's where its menu lives" in a real tray-icon context (some form of SNI registration for
    the icon specifically, vs. bypassing SNI entirely via `Gio.bus_watch_name` for Orcshot's own name) is
    still unresolved - the next real prototyping step, not resolvable from documentation alone.
  - **Unrelated, permanent, already-true-today limitation worth remembering regardless of any of this**:
    AppIndicator-family icons have no distinct left-click ("activate") action once a menu is attached - a
    real, documented, upstream protocol limitation (`app.py`'s own comment on `_build_tray_icon`, citing
    https://bugs.launchpad.net/bugs/1910521), not something GMenu vs. dbusmenu changes either way. X11's
    `Gtk.StatusIcon` keeps its own separate left-click-for-instant-capture shortcut specifically because of
    this - deliberately not unified onto one tray mechanism for both platforms, and that reasoning doesn't
    change here.
- Net effect of the whole #184 design as it now stands: the bundled `orcshot-clipboard@orcshot.org`
  extension's role shrinks to *only* whatever Window Picker still needs (via the separate third-party
  `window-calls` extension it already depends on) - region-select, clipboard, and the tray icon/menu all
  move to mechanisms with no `org.gnome.Shell` dependency at all, via the portal and a new, narrowly-scoped,
  Orcshot-specific Shell extension respectively.

Not yet written up as a formal design doc - still mid-brainstorm, but the shape is now real and detailed
enough that formalizing it into `docs/superpowers/specs/` is the natural next step whenever picked up.

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

**Second layer, also decided rather than left open**: add a real runtime X11 check too, not just the
listing-level mitigation - same link, shown as an in-app message rather than a launch failure. Confirmed
technically sound, not a contradiction of the "no display socket at all" problem above: the manifest would
declare `--socket=wayland` **and** `--socket=fallback-x11` together (Flatpak's own docs recommend exactly
this pairing for Wayland-primary apps), and per the sandbox mechanism already found for this task,
`fallback-x11` only gets revoked when Wayland *is* available - on a genuine pure-X11 session it stays
granted, enough to open one bare window and show the "won't work here, get the full version" message
before any real capture code ever engages. No new detection to build: `app.py:117` already computes
`session_type` (`wayland`/`x11`) for its own startup log line - this is a new branch on existing plumbing,
not new capability.

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
