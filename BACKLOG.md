# Backlog

Open items not yet scheduled into a task. Each entry keeps the context that
led to it - not just "what," but "why this matters" - so picking it up later
doesn't require re-deriving the reasoning from scratch.

## #165: Non-interactive GPG signing for PPA releases

direflail's own call (2026-08-22): the `debsign`/`debuild` GPG passphrase
prompt is a GUI pinentry popup that doesn't reliably take focus during a
release, and interactive passphrase entry isn't worth the friction for a
zero-profit open source project - there's no commercial stakes that would
justify keeping the private key passphrase-protected against, e.g., another
process on the same machine.

Not started. Likely direction: either a passphrase-less GPG key dedicated to
signing this project's releases, or a `gpg-agent` configuration that caches
the passphrase for a long-enough session that `debsign` never needs to
prompt mid-release. Whichever approach, keep the release doc (`RELEASING.md`)
in sync once this is actually built.

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

## #168: Audit for unintentional X11/Wayland backend divergence

direflail's own request (2026-08-22), prompted by confirming #166
(Snap-confined external commands) affects both platforms identically since
`run_external_command` is genuinely shared code: "honestly that should go
for everything in this project. make a task to audit that."

Scope: a systematic review of every feature that exists on both X11 and
Wayland, checking whether each one actually shares one backend
implementation (correct - the two platforms should never diverge except
where a real, unavoidable platform capability difference forces it, e.g.
Wayland's lack of global screen-coordinate APIs) versus having quietly
grown two separate, potentially-drifting implementations for no real
platform-forced reason. This project has already hit this exact class of
bug more than once:

- Task #143: the five tray capture-mode icons were hand-ported into
  `extension.js` as a second, independent copy of `icons.py`'s own drawing
  logic, "kept in sync by hand" until unified via the shared
  `icon_geometry.json`.
- Task #158: a capture-sound Wayland-vs-X11 timing asymmetry - different
  code paths for when the sound fires, not the same bug as #143 but the
  same *category*: the two platforms disagreeing because they weren't
  actually going through one shared mechanism.
- Task #166: same backend, confirmed *not* diverged this time - a genuine
  platform-sandboxing bug (Snap's `home` interface), not an X11/Wayland
  split - but only confirmed as such because someone actually checked.
- Task #169 (2026-08-22/23): the dialog-blocks-quit fix
  (`_close_open_modal_dialogs`) is shared code, unaffected by platform.
  The editor window placement fixes, on the other hand, turned out to be
  three genuinely separate bugs, two X11-specific (`Gtk.WindowPosition
  .CENTER` handling, a racy `get_position()` read) and one Wayland-specific
  (the compositor overriding `resize()`, fixed with `set_geometry_hints`)
  - a real example of the *opposite* problem #168 is looking for: not
    quiet duplication, but a single code path that behaves correctly on
    one platform and incorrectly on the other, found only through actual
    live testing on both.

Not scoped to fix anything found - a review/inventory pass, producing a
list of genuine divergences (each probably becoming its own follow-up
task) versus a confirmation that a given feature is already correctly
unified. Never started.

## #170: Orphaned `orcshot` processes silently escape systemd's tracking

Found live (direflail, 2026-08-22/23) while chasing task #169 on both X11
and Wayland: whenever the systemd `--user`-tracked instance quits (e.g. via
the tray's Quit action) and a hotkey- or autostart-launched instance takes
over instead, `Gio.Application`'s own single-instance handling makes that
replacement process the real, running application *without systemd ever
knowing it happened*. `systemctl --user status orcshot.service` reports
`inactive`/`dead` (`MainPID=0`) while a genuinely working process sits
outside its cgroup, indistinguishable from the outside except by comparing
`ps aux` against `systemctl ... -p MainPID`.

Concretely lost tonight, both platforms, more than once: no `Restart=
on-failure` coverage for that orphaned process (a crash there just
vanishes silently, nothing respawns it), and its `stderr` never reaches
`journalctl --user -u orcshot.service` - real diagnostic logging added to
chase the editor-placement bug produced zero output for several rounds
before the orphaning itself was identified as the actual cause, not a
logging-pipeline bug.

Not yet fixed. Likely direction: something in `do_activate`'s single-
instance handling (`app.py`) that notices it's *becoming* the primary
instance outside of systemd's own `ExecStart`, and either re-registers
itself with systemd somehow, or - more simply - has `_quit_and_hide_tray_
button` (or the hotkey/autostart entry points) check whether the systemd
unit is running before letting a bare invocation become the primary
instance, so a quit-then-relaunch always ends up back under systemd's
tracking rather than silently drifting out of it. Worth a repro *without*
today's specific circumstances (repeated quit-testing) to confirm how
easily an ordinary user hits this in normal use, not just aggressive same-
session testing.
