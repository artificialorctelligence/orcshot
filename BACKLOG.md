# Backlog

Open items not yet scheduled into a task. Each entry keeps the context that
led to it - not just "what," but "why this matters" - so picking it up later
doesn't require re-deriving the reasoning from scratch.

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
