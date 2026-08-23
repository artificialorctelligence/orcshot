# Backlog

Open items not yet scheduled into a task. Each entry keeps the context that
led to it - not just "what," but "why this matters" - so picking it up later
doesn't require re-deriving the reasoning from scratch.

## #171: Filename pattern defaults to literal, unresolved `${...}` tokens for pre-existing configs

Live-reported (direflail, 2026-08-23): a real screenshot saved with the literal filename
`${YYYY}-${MM}-${DD} ${hh}_${mm}_${ss}.png`, not an actual timestamp. Confirmed via direflail's own
`~/.config/orcshot/config.json`: `"filename_pattern": "${YYYY}-${MM}-${DD} ${hh}_${mm}_${ss}"` with
`"filename_pattern_mode": "strftime"` - a genuine mismatch. Those `${...}` tokens are the Windows/
Greenshot-style syntax (`core/filename_pattern.py`'s `MODE_GREENSHOT`); strftime mode only understands
`%Y`/`%m`/etc. codes and has no `${...}` concept at all, so `resolve_filename_pattern` passes the whole
string through as inert literal text - matching `filename_pattern.py`'s own already-documented, one-way
hazard ("MODE_GREENSHOT's own `${...}` tokens read literally as strftime text").

Root cause, not yet fixed: `core/filename_pattern.py` documents that `strftime` became the actual
default mode at some point (task #127/#128, "live-verification"), implying an earlier default used
Greenshot-style `${...}` tokens instead. direflail's config (`last_update_check` dated 2026-08-15,
predating this session) still carries that older pattern *text*, but `filename_pattern_mode` alone
apparently got updated/defaulted to `"strftime"` somewhere along the way - the two fields drifted out
of sync for any config that predates the mode-default change, with nothing to migrate the stale text
to match. Likely affects every upgrading user whose config was ever written before task #127/#128, not
just this one install.

Likely direction: a one-time settings migration (same shape as `is_default_external_commands_seeded`'s
own once-only pattern) that detects a `${...}`-shaped `filename_pattern` paired with
`filename_pattern_mode == "strftime"` and either converts the text to real strftime codes or resets it
to `DEFAULT_FILENAME_PATTERN` outright. See also #172 below - likely the same underlying *class* of bug
(a stale pre-existing value from before a later default changed, never migrated), just a different field.

## #172: Primary output format defaulted to TIFF instead of PNG for a pre-existing config

Live-reported (direflail, 2026-08-23): Preferences -> Output tab's "Primary format" was set to TIFF,
not PNG, causing quick-saves to write `.tiff` files. direflail changed it back to PNG manually before
this could be inspected live, so the evidence of *how* it became TIFF is gone - `settings.py`'s
`OutputSettings.primary_format` dataclass default is genuinely `"png"`, and `editor_window.py`'s format
combo box (`_SAVE_AS_FORMATS`, `"png"` first in the list) correctly selects whatever
`get_output_settings().primary_format` returns, so a truly fresh config should not be able to show this
- nothing found in a source read that would produce TIFF out of the box.

Not root-caused (evidence overwritten before investigation) - suspected same class of bug as #171: a
value that was correct under an *older* coded default, now stale relative to a *later* default change,
with no migration path for existing configs. Worth confirming on a genuinely fresh config (no prior
`output_settings` key at all) to rule out a first-run-path bug specifically, and worth checking git
history for whether `primary_format`'s own default value ever changed from something else to `"png"` at
some point, the way `filename_pattern_mode` apparently did for #171.

Aside, found while investigating: `_SAVE_AS_FORMATS` includes `("gif", "GIF")`, but
`file_export.py`'s `_EXTENSION_TO_TYPE` has no `".gif"` entry - picking GIF as the primary format would
silently save as PNG instead (`_EXTENSION_TO_TYPE.get(path.suffix.lower(), "png")`'s own fallback), a
small separate latent bug worth fixing alongside this one if picked up.

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
