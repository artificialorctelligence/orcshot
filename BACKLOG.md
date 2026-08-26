# Backlog

Open items not yet scheduled into a task. Each entry keeps the context that
led to it - not just "what," but "why this matters" - so picking it up later
doesn't require re-deriving the reasoning from scratch.

## #183: Language picker has no effect, even after a real restart - .mo files never ship in the package

Found live (direflail, 2026-08-25) testing the Preferences language picker built in task #182's own fix
wave, on a real installed `.deb`: picking a language and restarting Orcshot has no visible effect - the app
stays in English regardless of what's selected.

Root-caused, not just reproduced. Ruled out first: `settings.set_language()`/`get_language()` and the
restart timing are both fine - confirmed live that the picker correctly wrote `"language": "ja"` to
`~/.config/orcshot/config.json`, and confirmed the actual running process (`systemctl --user status
orcshot.service`, a fresh PID) started *after* that config write - so this was a genuinely new process
that should have picked the setting up.

The real break: the installed package ships with **no locale files at all**. Confirmed via
`dpkg -L orcshot | grep locale` (empty) and `dpkg-deb -c orcshot_*.deb | grep locale` (empty) -
`/usr/lib/python3/dist-packages/orcshot/resources/` has no `locale/` subdirectory whatsoever, even though
`debian/rules`' `override_dh_auto_build` genuinely does compile every `po/*.po` to a real `.mo` in the
source tree before `dh_auto_build` runs (confirmed those `.mo` files exist on disk under
`src/orcshot/resources/locale/`).

The gap: `pyproject.toml`'s `[tool.hatch.build.targets.wheel]` uses `packages = ["src/orcshot"]` with no
explicit `include`/`artifacts` list. Task #182's own REQUIREMENTS.md write-up assumed this auto-bundles the
compiled `.mo` files "the same way it already bundles icons" - that was never actually verified against a
real installed package, only against `dpkg-buildpackage` succeeding and `pytest` passing, neither of which
inspects the final wheel/deb contents. Hatchling's default wheel build respects `.gitignore` when no
explicit include list is given, and `src/orcshot/resources/locale/` is deliberately gitignored (as a build
artifact, per task #182's own reasoning) - so hatchling silently drops the whole directory from the wheel
even though the files are sitting right there on disk at build time. A direct, self-inflicted conflict
between two decisions made in the same task.

**Fix**: add an explicit `artifacts` (or `force-include`) entry to `pyproject.toml`'s
`[tool.hatch.build.targets.wheel]` for `src/orcshot/resources/locale/**/*.mo` - the standard hatchling
mechanism for a generated file that's intentionally untracked by git but must still ship. Verify this time
against a real `dpkg -L`/`dpkg-deb -c` listing, not just a successful build - that gap is exactly what let
this ship unnoticed in the first place.

**Bundled UX request (direflail, same session):** once this actually works, switching languages in the
Preferences picker should prompt to restart Orcshot (with confirmation), rather than relying on the passive
"Applies after restarting Orcshot" tooltip and the user remembering to restart manually.

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

## #181: Crop-offset origin assumption unverified specifically for non-GNOME Wayland compositors

Narrowed successor to the old #175 (closed for GNOME - see REQUIREMENTS.md's Task #175 entry for the full
resolution). `capture/wayland.py`'s Wayland path reads monitor geometry through GDK's compositor-agnostic
enumeration (`gdk_screen_layout`), not a GNOME-specific API, so in principle a different Wayland compositor
(KWin, a wlroots-based one) could use a different coordinate convention for `bounds.left`/`bounds.top` than
Mutter's proven-always-non-negative guarantee. Not checked, and not urgent: orcshot's Wayland support is
built around a bundled GNOME Shell extension and isn't a supported target on other compositors anyway -
revisit only if that ever changes.
