# Backlog

Open items not yet scheduled into a task. Each entry keeps the context that
led to it - not just "what," but "why this matters" - so picking it up later
doesn't require re-deriving the reasoning from scratch.

## #204: Running the test suite rewrites `po/orcshot.pot`, dirtying the working tree on every run (RESOLVED 2026-09-07)

Hit twice during the `0.3.0` release (2026-09-07), both times mid-release when a clean tree actually
mattered. `tests/unit/test_extract_pot.py` regenerates `po/orcshot.pot` in place as a side effect of
running, and that file is deliberately committed (see `.gitignore`'s own note - `TRANSLATING.md`
points contributors at it as the template to translate from). So `pytest tests/ -q`, the very first
command `RELEASING.md` step 2 tells you to run, leaves `git status` dirty every single time.

The diff it produces is pure noise: a new `POT-Creation-Date` line plus source line-number churn.
Verified both times by comparing the msgid sets before and after - 366 msgids each way, identical
sets, so nothing translatable ever actually changes. It just looks like a real modification until
someone checks, and during a release it competes for attention with genuine uncommitted work. On
this release it had to be reverted twice by hand, once before the release commit and once after the
post-release fixes, purely to keep step 8's `git add` honest.

**Concrete consequence, not hypothetical**: step 8 commits an explicit file list, so the churn never
gets committed by accident - but anyone running `git commit -a`, or eyeballing `git status` to decide
whether a tree is clean, gets a false positive. It also means a release can never verify "tree is
clean" straight after step 2 without a manual `git checkout -- po/orcshot.pot` first, which is
nowhere in the checklist.

**Scope boundary**: the test itself is doing something legitimate - checking the extraction script
produces what is committed. The bug is that it verifies by *overwriting the real file* instead of
extracting to a temp path and comparing. Fixing it means changing the test, not the extraction script
or the decision to commit the `.pot`, and there is no reason the fix should change what
`scripts/extract_pot.sh` does for a human running it deliberately.

**Resolved 2026-09-07.** `scripts/extract_pot.sh` now takes an optional output path
(`out="${1:-po/orcshot.pot}"`), so a human running it bare behaves exactly as before - verified
live, it still writes the committed file and prints `Wrote po/orcshot.pot`. The test passes
`tmp_path` instead, and the suite no longer touches the repo: a full `pytest tests/ -q` run
(1208 passed, 3 skipped) now leaves `git status` showing nothing for `po/orcshot.pot`.

**The seam was used to make the test worth having.** As the scope note above predicted, the old
test only asserted the script exited 0 and produced a non-empty file - a tautology that would pass
just as happily with a stale template. Since extraction now goes to a temp path anyway, comparing
against the committed file was nearly free, and `test_the_committed_pot_is_up_to_date` now fails if
the two disagree in either direction. Confirmed it can actually fail rather than assuming so:
mutating `msgid "Eyedropper"` in the committed `.pot` produced
`AssertionError: po/orcshot.pot is out of date - re-run scripts/extract_pot.sh. Strings in the
source but not the template: ['Eyedropper']`. A third test asserts directly that running the
script does not modify the committed file, which is this entry's own bug expressed as a check.

**One correctness detail worth recording**, because the obvious shortcut is wrong: the comparison
parses full msgids rather than using `grep '^msgid'`. This file has 25 multi-line msgids, which
begin as a bare `msgid ""` with the text on continuation lines - a grep-based comparison collapses
every one of them into the same empty string and would miss any change inside them entirely. (The
ad-hoc "366 msgids, identical either way" checks run by hand during the `0.3.0` release had exactly
this weakness; their conclusion happened to be right because the diffs visibly contained nothing but
`POT-Creation-Date` and `#:` line references, but the check alone did not prove it.) msgids only,
not whole files - the creation date and source line references change on every extraction and mean
nothing to a translator.

## #203: On a machine sitting at the login screen, the postinst starts Orcshot as the `gdm` greeter user (RESOLVED 2026-09-07)

Found on the Ubuntu 24.04 VM during `RELEASING.md` step 7 of the `0.3.0` release (2026-09-07). The
VM was booted but nobody had logged in - GDM was showing its user list. Installing the `.deb` there
printed the usual `Orcshot is installed and starting now.` and, checked immediately afterwards,
`ps aux` showed:

```
gdm  2666  /usr/bin/python3 /usr/bin/orcshot
```

Orcshot running as the **`gdm`** system user, in the greeter's own session. Meanwhile the real
account's own unit was correctly `enabled` but `inactive`, exactly as it should be with no graphical
session yet - so the intended behavior works; it just also fires for the greeter.

**Mechanism**, read straight out of the built package's `postinst`: it loops over users that have a
live session bus socket, and for each one runs `runuser -u "$user" -- env
DBUS_SESSION_BUS_ADDRESS=... XDG_RUNTIME_DIR=... systemctl --user enable --now orcshot.service`
whenever the debconf answer `orcshot/enable-autostart` is `true`. The GDM greeter is a real user
with a real session bus, so it matches that loop like any other. There is no filter for system or
greeter accounts.

**Concrete consequence**: a screenshot-and-annotation tool with tray, hotkey and D-Bus surfaces gets
started in the display-manager's own session on any machine where the package is installed while
sitting at the login screen - which is the normal state for an unattended install, an install over
SSH, or any automated provisioning. It also means `orcshot.service` becomes `enabled` for the `gdm`
user persistently, not just for this boot. Nothing observed misbehaved as a result, and nothing here
suggests a capture actually occurred, so this is untidy and wrong rather than known-harmful.

**Scope boundary**: not new in `0.3.0`. `git log` shows `debian/postinst` unchanged since the task
#141 follow-up that introduced the debconf question, well before `v0.2.0`, so every release carrying
that postinst behaves this way. It was simply never noticed, because previous install-tests happened
on VMs that were already logged in. Not a `0.3.0` blocker and not treated as one. The likely fix is
a guard in that loop - skip accounts below the normal `UID_MIN` (1000), or explicitly skip `gdm`/
`lightdm`/`sddm` - but that is a real change to the install path and wants its own testing on a
logged-in machine, at the login screen, and with multiple users logged in at once.

**Resolved 2026-09-07, and the fix was wider than this entry first described.** Reading the scripts
together showed the same user-selection loop lives in **two** maintainer scripts, not one:
`debian/orcshot.postinst` (which decides whose session to enable in) and `debian/orcshot.config`
(which decides whether to *ask* the debconf question at all). Fixing only the postinst would have
been a band-aid - `orcshot.config` would have gone on asking based on the greeter's session while
the postinst declined to act on it. Both now carry the same guard:

```sh
uid_min=$(awk '$1 == "UID_MIN" { print $2; exit }' /etc/login.defs 2>/dev/null || true)
[ -n "$uid_min" ] || uid_min=1000
...
    [ "$uid" -ge "$uid_min" ] 2>/dev/null || continue
```

`UID_MIN` is read from the system rather than hardcoded, with 1000 as the documented fallback. The
`2>/dev/null` is deliberate: a non-numeric uid makes `[ -ge ]` fail rather than abort - the
`|| continue` absorbs it even under `set -e`, verified directly - but without redirection it would
print "Illegal number" into the middle of an apt install.

**A second, separate defect was found in the same loop and fixed with it**: postinst had
`[ -S "$bus" ] || break`, so a single user with no session bus socket abandoned the search for every
user after them. Changed to `continue`. The trailing `break` after the first graphical session was
deliberately left alone - `orcshot.config`'s own comment documents "only the first graphical session
found is asked about" as a considered decision about fast user switching, and it was only ever a
problem because a greeter could be the session it stopped at.

**Verified live on the Ubuntu 24.04 VM**, under the exact conditions that produced the bug: `gdm` is
uid **120** against a `UID_MIN` of 1000, and `loginctl list-users` lists **gdm first**, holding the
only graphical session - so the old loop matched it and stopped there. The old install had indeed
left the unit persistently enabled at
`/var/lib/gdm3/.config/systemd/user/graphical-session.target.wants/orcshot.service`.

- **At the login screen, nobody logged in**: postinst now prints its "Open it from your Applications
  menu" fallback instead of "starting now"; no orcshot process runs as gdm; `is-enabled` for gdm
  reports `disabled`.
- **Logged in as a real user**: from a deliberately cleared baseline (`disabled`/`inactive`), the
  install prints "Orcshot is installed and starting now.", and the unit comes back `enabled` and
  `active` with `/usr/bin/python3 /usr/bin/orcshot` running as `vboxuser` - and still nothing as gdm.

**Not separately tested, stated as reasoning rather than evidence**: the greeter and a logged-in user
holding graphical sessions *simultaneously*. On this single-seat VM gdm's session disappears once a
user logs in, so the state could not be produced. The argument that it is covered is that the guard
excludes gdm at any position in the list, making ordering irrelevant - which is exactly the property
the first scenario above tests directly. A multi-seat or fast-user-switching machine would confirm it
properly if one is ever available.

`tests/unit/test_maintainer_script_session_selection.py` guards the fix with 7 assertions, written
failing first. They are static assertions on shell source, for the same reason
`test_orcshot_user_service.py` gives: `debian/` is packaging metadata, and neither script can run
standalone because both source `/usr/share/debconf/confmodule`, which re-execs outside a real dpkg
run. The live install above is the behavioral evidence; the tests exist so the guard is not silently
dropped later.

## #202: A `.deb` upgrade on the Mint host surfaced an unexplained "save this screenshot" prompt (RESOLVED 2026-09-07 - working as designed)

Reported live by direflail during the `0.3.0` release (2026-09-07), immediately after running
`sudo apt install ./orcshot_0.3.0-1_all.deb` on the Mint/Cinnamon host at `RELEASING.md` step 7:
"why did it have me save a screenshot?" No capture had been requested by hand.

**What the evidence actually shows, and where it stops.** The install itself was clean and did
nothing screenshot-shaped: `1 upgraded`, `Unpacking orcshot (0.3.0-1) over (0.2.0-1)`, `Setting up
orcshot (0.3.0-1)`, then the postinst's own `Orcshot is installed and starting now.` - that last
line is the hand-written debconf/`runuser ... systemctl --user enable --now orcshot.service` path
in `debian/postinst`, not a capture. The host journal for `orcshot.service` shows a single clean
start at `Sep 07 21:11:33` with `session_type=x11 desktop=X-Cinnamon -> x11 (X11-native capture
path)`, no errors, no restart loop, and PID 115046 still alive afterwards. By the time this was
investigated no Orcshot window remained open (`wmctrl -l` empty), so the dialog itself was never
captured.

**The one strong clue** is what the same action looks like on the 26.04 VM minutes later: a
`tray-full_screen` capture there pops Orcshot's own destination picker - Copy to Clipboard / Save /
Save As... / Edit... / Print / krita. "Save" and "Save As..." live in that picker, so what direflail
saw is almost certainly the post-capture destination picker rather than any install-time prompt,
which reframes the question from "why did apt ask me to save" to **"what triggered a capture on the
host at that moment"**. That part is genuinely unknown. Plausible mechanisms, none of them checked
yet and none to be treated as the answer: the service restart tearing down a 0.2.0 process that had
a capture still pending, a hotkey/`repeat_region` path firing during the restart, or something
unrelated to the upgrade entirely that merely coincided with it.

**Why this is worth an entry rather than a shrug**: a package upgrade that appears to demand a save
from the user is indistinguishable, from the user's side, from data loss risk - and this is the
exact upgrade path every PPA user will take. `0.3.0` shipped anyway (direflail's call, 2026-09-07,
"we'll talk about the random save later"), so this is not a release blocker, just an unexplained
behavior on the most common install path with no reproduction recorded yet. First real step is
reproducing it: upgrade over a running instance on the X11 host with a capture deliberately pending,
and again with none, and watch for the picker.

**Root-caused the same day, and the answer is that nothing is broken.** The guess above was wrong in
its specifics - it was not the destination picker, and no capture was triggered. `debian/orcshot.preinst`
(read late; the earlier investigation had only checked `postinst` and `prerm`) deliberately calls into
any already-running instance over D-Bus **before dpkg replaces a single file**:

```sh
gdbus call --session --dest org.orcshot.Orcshot --object-path /org/orcshot/Orcshot \
    --method org.gtk.Actions.Activate 'prepare-for-upgrade' '[]' '{}'
```

`OrcshotApplication.prepare_for_upgrade` (`src/orcshot/app.py`) handles it by closing every unmodified
editor and calling `prompt_save_for_restart(_("New install incoming - save your work"))` on every
editor that `is_modified`. That message *is* the prompt direflail saw. It exists so an open editor's
unsaved work doesn't silently vanish when the package's files are swapped underneath the process -
the task #151 follow-up.

**The host journal confirms every step of it**, which is why this closed without needing a
reproduction: `21:11:21` the `sudo apt install` is logged; `21:11:23` dbus-daemon logs
`org.freedesktop.hostname1` being activated by **pid 19281, `comm="/usr/bin/python3 /usr/bin/orcshot
--capture-region"`** - a long-lived instance originally launched by the `Print` hotkey
(`custom7`), and hostname1 activation is what a GTK file chooser does as it builds its places
sidebar; `21:11:32` `~/Pictures/Screenshots/screenshot.png` is written (745x397, an older
conversation screenshot with a red annotation box - real unsaved work, saved back to its own
existing path, which is why the name doesn't match the configured
`%Y-%m-%d %H_%M_%S` pattern); `21:11:33` the postinst's `systemctl --user enable --now` starts a
fresh instance as pid 115046, which could only take the single-instance D-Bus name because 19281
had already quit.

**One real defect did fall out of it**: `app.py` named the wrong maintainer script in five places -
"debian/orcshot.postinst calls this", "postinst does NOT wait for this to finish", and so on - when
the caller is `debian/orcshot.preinst`. Both files exist and both are real, so the comments sent a
reader to the wrong one, and the distinction is the entire mechanism: preinst runs *before* dpkg
unpacks anything, postinst only after every file is already replaced. Corrected, with that ordering
requirement now stated explicitly in the docstring.

**Worth knowing for future releases**: any `.deb` upgrade on a machine with an Orcshot editor holding
unsaved work will prompt. That is intended, but it does mean an unattended or scripted upgrade can
leave a modal dialog waiting in a user's session - `prepare_for_upgrade`'s own docstring already
reasons about exactly this and deliberately does not block the maintainer script on it.

## #201: The `0.1.1` and `0.2.0` PPA source uploads each shipped the project's entire `.git` directory (RESOLVED going forward 2026-09-07)

Found at `RELEASING.md` step 6 of the `0.3.0` release (2026-09-07), inspecting the built source
tarball before `dput` rather than after. `debian/source/options` supplied only `tar-ignore =
"<pattern>"` entries and never a bare `-I`/`tar-ignore`, and dpkg-source(1) is explicit that its
default exclusion set - "control files and directories of the most common revision control systems,
backup and swap files and Libtool build output directories" - is added **only when -I appears with
no pattern**. So those defaults were never on. The file's own header comment asserted the opposite
("dpkg-source's own default -I exclusions (VCS dirs, backups, swap files, Libtool build output)
don't cover Python's own local dev/build artifacts"), which is presumably why it went unnoticed
through two releases: the file read as though the VCS case was already handled.

Measured from the actual tarballs still on disk, not inferred: `orcshot_0.1.1-3.tar.xz` carries 1415
`.git/` entries at 10.8 MB, `orcshot_0.2.0-1.tar.xz` carries 1882 at 14.8 MB, and `0.3.0-1` as first
built carried 3061 at 22.6 MB. Both of the first two were uploaded to
`ppa:artificialorctelligence/orcshot` and are public. `0.3.0` was caught before upload.

**What this is and isn't.** It is not a credential exposure - checked rather than assumed at the
time: no credential-shaped filenames anywhere under the packed `.claude/`, a presence-only scan of
`.claude/` for GitHub/AWS/Slack/private-key patterns returned zero matches, and `.claude/settings.json`
holds a single plugin toggle. The `.git` directory is the same history already public on GitHub, so
what leaked was redundancy, not information. What it actually cost is a source package roughly 20x
larger than the project (1.02 MB once fixed), Launchpad build inputs full of irrelevant history, and
- new in `0.3.0` - 1330 `.claude/` entries that by then included whole stale git worktrees carrying a
built `orcshot_0.2.0-1_all.deb`, a `.whl`, and duplicate copies of the entire source tree. Shipping a
prebuilt `.deb` inside a source package is exactly what lintian's `source-contains-prebuilt-*` family
exists to catch, and step 5 never would have: it lints the binary `.deb`, not the source package.

**Resolved for real, not just tracked**: `debian/source/options` now begins with a valueless
`tar-ignore` (the long form - a bare `-I` is rejected outright there with "short option not allowed
in debian/source/options", which fails open and silently leaves the defaults off, confirmed live by
trying it), plus explicit `tar-ignore` entries for `.claude`, `.hypothesis` and `.orclab`, none of
which any VCS default list knows about. Verified by rebuilding from the options file alone with no
command-line flags: `.git`, `.claude`, `.hypothesis`, `.orclab` and `.venv` all at zero entries, zero
`.deb`/`.whl`/`.so`/`.exe` files, all 82 `src/**/*.py` still present, 22.6 MB down to 1.02 MB, and no
dpkg-source warning. The stale comment that caused the misreading was corrected in the same edit.

**Still open, deliberately not fixed here**: the two already-public uploads stay as they are.
Launchpad does not allow re-uploading an existing version, the content is duplicated from a public
repo anyway, and superseding them would mean burning version numbers to republish history that is
already on GitHub. Worth knowing about rather than acting on.

## #200: Aikido only scans what a session hand-feeds it - the repo has never been connected for real, continuous scanning (RESOLVED 2026-09-07)

Found while running `RELEASING.md` step 3 for the `0.3.0` release (2026-09-07). Step 3's prose has
claimed since the `0.1.1` release that "Aikido's own local scan (`aikido_full_scan`, run on the
changed files) covers SAST and secrets" - but that is a description of a thing a session does by
hand, not a mechanism the project owns. Nothing in the repo, in CI, or in the release checklist's
own command block ever actually invokes it, so whether any given release got an Aikido scan at all
has depended entirely on whether whoever ran the release happened to do it.

The concrete blocker, confirmed live on this machine rather than assumed: there is no Aikido CLI
installed and none available to install here (`which aikido`, `which aikido-local-scanner`, `pip
list`, and `docker images` all come back empty). The only working interface is the MCP tool
`aikido_full_scan`, which takes **file contents inline in the tool call** rather than paths, capped
at 50 files per request. That makes its cost scale with source size instead of with a command:
Orcshot's shipped tree is 82 `.py` files totalling 1,052,354 bytes - roughly 260k tokens, larger
than a single context window, so a whole-tree scan needs about nine batched calls and forces a
context compaction in the middle of the release. Even narrowing to source files changed since the
previous release tag was 21 files / 611,272 bytes for `0.3.0`, because `editor_window.py` alone is
315 KB across 6,182 lines. A release step that expensive and that fragile will get skipped, which
is exactly the ad-hoc situation step 3 was written to end.

The real fix is to stop scanning from inside a session at all: connect the repository to Aikido so
it scans server-side on every push, the same shape `.github/workflows/*.yml` already gives us for
build/test/lint and that step 9 already checks before publishing. That scans the entire repo on
every commit rather than a hand-picked subset once per release, costs nothing per release, and
turns step 3's Aikido half into a result to read instead of a job to run. Requires a one-time
account-side repo connection on Aikido (direflail's own account, web UI - same class of one-time
per-account setup as `#197`'s publishing setup, and not something to do unilaterally).

**Scope boundary**: this is about coverage *continuity*, not a known unscanned vulnerability. Semgrep's
half of step 3 (`semgrep ci`) does run for real on every release and covers SAST plus Supply Chain
across the whole tree, so the gap Aikido is meant to close is specifically **secrets detection** and a
second SAST opinion - not the project's only scanning. Requested by direflail during the `0.3.0`
release ("if it's going in the repo it gets scanned") after this constraint was surfaced; `0.3.0`
itself was scanned via the MCP tool over its changed files as the interim measure.

**Resolved by removing the requirement, not by meeting it** (direflail, 2026-09-07). Pricing the fix
killed it: Aikido's free tier genuinely does scan a connected repo server-side every 3 days
(SCA, SAST, secrets, container/IaC, license - 10 repos, 2 users), so continuous scanning was never
the blocker. The blocker is *reading* it. Aikido's **Public REST API begins at the Basic tier,
$300/month** (confirmed live against aikido.dev/pricing, 2026-09-07), and the MCP tools go through
that API - which is exactly why `aikido_issues_list` answers "This action is only available for
paying customers" on this account, the same response recorded on 2026-08-23. So the only free way to
read Aikido's results is a human opening its web dashboard, and the only automated way costs $300 a
month to duplicate SAST/SCA coverage `semgrep ci` already provides for free across the whole tree.

`RELEASING.md` step 3 now names `semgrep ci` as the whole of its tooling and states outright why
Aikido is no longer listed.

**The gap this leaves open, deliberately and on the record**: **secrets detection is now covered by
nothing.** Aikido's unique contribution over Semgrep was secrets, not SAST, so dropping it does not
merely remove redundancy - it removes the only scanner that was ever nominally looking for committed
credentials. Free options exist and were put to direflail at the time: a `gitleaks` or `trufflehog`
step in the existing CI workflows (automated, blocking, no account, no paid tier, machine-readable
output), or the free Aikido repo connection with a manual dashboard check at release time. Neither
was adopted - the decision was to drop Aikido and accept Semgrep as the whole gate. Worth revisiting
if this project ever starts handling real credentials in-repo; nothing about that reasoning changes
if it does.

## #199: Every GitHub Actions `uses:` line is a mutable tag, not a pinned commit SHA

Surfaced by `semgrep ci` during the `0.3.0` release (2026-09-07), running `RELEASING.md` step 3's
security check for the first time since all three CI workflows came into existence. 15 findings,
all HIGH impact, all the same rule (`yaml.github-actions.security.github-actions-mutable-action-tag`):
`.github/workflows/apt.yml` (4), `.github/workflows/flatpak.yml` (5), `.github/workflows/snap.yml` (6).
They are new only in the sense that the workflows themselves are new - every one of them has been
written this way since it was added, so this is the finding's first opportunity to fire, not a
regression.

Four distinct actions are involved: `actions/checkout@v4`, `actions/upload-artifact@v4`,
`actions/download-artifact@v4` (14 of the 15, all GitHub first-party) and `canonical/action-build@v1`
(1, Canonical's snapcraft builder - the only third-party one). The concrete consequence is not
hypothetical and the rule cites real precedent: a git tag is mutable, so whoever controls the action's
repo can silently repoint `v4` at different code, and that code then runs inside our CI with whatever
secrets that job holds. The `tj-actions/changed-files` compromise (March 2025) is exactly this
mechanism playing out - a tag repointed to code that dumped runner memory into public build logs.
The fix is mechanical: replace each tag with the full 40-character commit SHA it currently resolves
to, keeping the human-readable tag as a trailing comment, and let Dependabot bump them.

**Scope boundary, stated explicitly because it's what kept this from blocking the `0.3.0` release**:
this is a CI-supply-chain finding, not a defect in any shipped artifact. Nothing a compromised action
could reach ends up inside the `.deb` a user installs from the PPA - `RELEASING.md` step 6 uploads a
*source* package that Launchpad's own build farm compiles independently of GitHub Actions entirely,
and the `.deb` attached to the GitHub Release in step 10 is built locally in step 4, not by CI. What
a compromise here would actually get is the CI runner's own environment and whatever repo-scoped
token that job carries - real, and worth fixing, but not a path to users' machines. Accepted as
understood-not-blocking by direflail (2026-09-07) under step 3's own "flagged and understood, not
necessarily a blocker" standard, with this entry as the record.

## #198: Build the real Snap Store and Flathub publish mechanisms - neither channel has ever been onboarded

Raised 2026-09-07 while finishing Orclab's own v11 work on the apt/snap/flatpak pipeline. This
entry exists because #197 below explicitly said it should ("probably folds naturally into actually
building Snap's and Flatpak's real publish mechanisms - no existing entry tracks that yet, it
would need its own, separate from this one") and then nobody created it. The gap sat untracked for
a day and was only noticed when direflail asked what else was open. Two channels shipping in CI
with no path to a user is not a small thing to lose track of.

**Confirmed live, 2026-09-07 - not assumed from memory:**
- `snap info orcshot` -> `error: no snap found for "orcshot"`. The name has never been registered
  in the Snap Store.
- `https://flathub.org/api/v2/appstream/org.orcshot.Orcshot` -> 404, and
  `https://github.com/flathub/org.orcshot.Orcshot` -> 404. Never submitted.

So these are not channels missing an *action*. They have never been **onboarded** - a one-time,
account-gated, externally-reviewed step, which is a different kind of work from writing a publish
command.

**What actually exists today:** `.github/workflows/snap.yml` builds the snap and installs it with
`--dangerous` (no store round-trip), and `.github/workflows/flatpak.yml` builds the bundle and
validates the metainfo against Flathub's own linter. Both prove the artifact is good. Neither
pushes it anywhere, and there is no manual push either.
`.orclab/publish/channels.yaml` carries `snap: {}` and `flatpak: {}` deliberately for exactly this
reason; as of Orclab v0.11.0 those now report `(known channel, not yet actionable)` in a
`/orc-publish` dry run rather than reading as a misconfiguration.

**The two channels are genuinely different work, not one task done twice:**
- **Snap**: a one-time `snapcraft register orcshot` against an Ubuntu One account, then a
  per-release `snapcraft upload` with a channel release. Store review may apply depending on the
  confinement and interfaces requested - `snapcraft.yaml` already connects `personal-files`, which
  CI currently sidesteps with a manual `snap connect` against a local install precisely because
  that path needs no Canonical review. Whether it needs one for a real store upload is unchecked.
- **Flatpak**: the first submission is a pull request to `flathub/flathub` reviewed by other
  people over days - not a command that completes inside a release, and never something to open as
  a side effect of one. After acceptance, each release is a PR against the app's own
  `flathub/org.orcshot.Orcshot` repo bumping the manifest's source ref. Only that second half is
  automatable.

**Already done, and worth not re-deriving:** #194 (RESOLVED 2026-09-04) made the Flatpak manifest
submission-ready, including the definitive finding that `--talk-name=org.gnome.Shell` cannot be
narrowed - clipboard and window-calls capture both call custom interfaces on that same bus name,
and Flatpak filters by bus name only. That is ready to explain to a Flathub reviewer on its own
terms. The manifest has been submission-ready since then; nothing has been submitted.

**Scope boundary.** This is about *publishing to* these channels. It is not #186 (what download
metrics each channel exposes - that is downstream, and unmeasurable until something is actually
published), not #132 (RPM-family and Arch, a different packaging effort entirely), and not #197
(getting credentials/signing set up per machine). #197 and this entry interlock rather than
overlap: #197 asks "how do I get set up to publish at all," this asks "what is the publish action
even made of." Doing this one will answer much of #197 as a side effect, which is exactly why #197
predicted it would fold in.

**One structural consequence to plan for, not discover late:** `RELEASING.md` has no snap or
flatpak publish steps at all today - both channels appear only in step 9's "confirm CI is green."
Whatever gets built here needs real numbered steps inserted in dependency order, which is
`release-checklist` work. Orclab v0.11.0 added a `**One-time setup:**` marker for precisely this
shape: the registration and the Flathub submission are one-time and account-gated, and
`/orc-release` will run only such a block's check, never its setup commands, unless asked
directly. That marker was designed against this case; this is where it first earns its keep.

**Next step, when picked up:** research each channel's real, current mechanism live before writing
anything down - Snapcraft's store auth and upload flow, and Flathub's current submission process,
both of which have changed before and neither of which should be reconstructed from memory
(`currency-discipline`). Then decide per channel what is a real `channels.yaml` action, what is a
`RELEASING.md` step, and what is one-time setup. Do it in a session centred on Orcshot: this is a
real, irreversible, externally-visible publication, and Orclab's own `CLAUDE.md` puts that
squarely outside a session centred on the framework.

**Update 2026-09-11 - Snap half started, then blocked on a code change: see #205.** `snapcraft
login` and `snapcraft register orcshot` are done (checks: `snapcraft whoami`, `snapcraft names`;
`snap info orcshot` stays "no snap found" until a revision is released, so it is the confirmation
test, not the registration test). Live research of current store policy then showed the first
upload would be held for human review twice: the `dbus` slot (routine, ~2 days) and the
`personal-files` write to `~/.local/share/gnome-shell/extensions` (plausibly never granted - a
near-identical write request was refused two weeks earlier as a confinement escape). Decision:
distribute the extensions via extensions.gnome.org and drop the plug, which is Orcshot code work
and must land before this entry's `/orc-package snap` step is applied. #205 holds the full
research list and the spec. No `snap` ingredient exists yet in either Orclab location; capturing
one is the step after #205.

## #197: A real setup step for apt/snap/flatpak publishing - credentials/signing, tailored per channel and per machine

*(Renumbered from #196 to #197 on 2026-09-07, when merging main into BACKLOG #189's branch: both
branches independently took #196 for unrelated findings. This entry moved because the other one -
the tray right-click bug below - is referenced by number in shipped code (`extension.js`,
`debian/orcshot.user.service`, `tests/unit/test_orcshot_user_service.py`) while this one was
referenced only inside `BACKLOG.md` itself. Numbers stay permanent from here; commits dated before
this that say "BACKLOG #196: real setup step... publishing credentials" mean this entry.)*

Raised by direflail (2026-09-06/07) while dogfooding Orclab's new `/orc-publish` command against
Orcshot's real config for the first time. Populating `.orclab/publish/channels.yaml` surfaced that
none of the three real channels actually have a documented, repeatable "how do I get set up to
publish to this at all" step - what exists today is scattered and incomplete:

- **PPA (apt)**: `RELEASING.md` step 6 documents the `~/.dput.cf` entry and assumes a GPG key
  already registered to the Launchpad account, but says nothing about *getting* one set up, and
  the real operational friction found today - `debsign` prompting for a passphrase on stdin, which
  `/orc-publish`'s subprocess can't satisfy (a real, confirmed hang risk, see BACKLOG #11 in
  Orclab) - has no setup guidance at all. The fix worked out today: unlock `gpg-agent` yourself
  first (`echo test | gpg --clearsign > /dev/null`) so it caches the passphrase, and raise
  `gpg-agent.conf`'s `default-cache-ttl`/`max-cache-ttl` so it stays warm for a real release
  session. Written into `.orclab/publish/channels.yaml`'s `ppa.noble` leaf as a `requirement:` (now
  visible in `/orc-publish`'s dry-run output, per Orclab's own recent fix surfacing
  requirements/issues there) - but that's a config note, not a setup *guide* someone new to this
  machine could follow start to finish.
- **Snap**: has no real publish mechanism at all yet - confirmed live, 2026-09-06 (CI in
  `.github/workflows/snap.yml` only builds and installs `--dangerous`, no `snapcraft
  login`/`snapcraft upload`/`snapcraft push` anywhere, manual or automated). Whatever gets built
  there will need its own credential story - `snapcraft login`/store credentials are a completely
  different mechanism from GPG, not just "the same problem again."
- **Flatpak**: same - no real Flathub submission process exists yet, confirmed the same way
  (`.github/workflows/flatpak.yml` only builds and validates against Flathub's linter). Flathub's
  own submission/auth model is different again from both PPA and Snap. (Not the same thing as
  `#186`, which is about *download metrics* per channel, not *publishing* to them - noted here
  only because both surfaced from the same kind of "what actually exists today" check.)

**Why "tailored to whatever the user is running" matters, not just "write one guide"**: direflail
was explicit about this. A GPG passphrase-caching setup depends on which agent/pinentry is actually
installed and how (gnome-keyring integration vs. plain `gpg-agent`, a hardware key like a
YubiKey/Nitrokey instead of a passphrase entirely - real alternative discussed today, more secure
*and* more convenient, but real hardware to provision, not something to assume everyone has).
Snap's and Flatpak's own setup will have their own real per-machine variables once researched. A
single hardcoded guide would go stale or misfire the moment it's run somewhere different from
where it was written.

**Scope, deliberately not decided yet**: whether this becomes one combined "get Orcshot's publish
setup working" walkthrough or three separate per-channel ones; whether it lives as prose in
`RELEASING.md`, as its own new doc, or as `requirement:`/`issue:` notes directly in
`.orclab/publish/channels.yaml` once Snap/Flatpak have real leaves to attach them to (the PPA note
already proves that last pattern works); how "tailored to whatever's running" actually gets
detected/adapted at guide-writing or guide-running time rather than just listing options and
leaving the reader to pick.

**Why this belongs here, not purely in Orclab**: the *mechanism* for showing a requirement/issue is
already generic (Orclab's `/orc-publish`, v7). What's missing is real, Orcshot-specific setup
content for real Orcshot channels - the same "wrap what's real, populate one project at a time"
split this whole framework has used everywhere else.

**Next step, when picked up**: probably folds naturally into actually building Snap's and
Flatpak's real publish mechanisms (no existing entry tracks that yet - it would need its own,
separate from this one) rather than being tackled standalone - credential setup is part of "what
does a real publish for this channel even require," not a separate concern from it. Research each
channel's real, current credential/signing mechanism first (not assumed from memory) before
writing anything down.

**Update 2026-09-07 — the entry this one predicted now exists: #198.** This entry's own next step
said the work "would need its own, separate from this one" and then nothing created it, so it went
untracked in both repos for a day. #198 covers building the real Snap Store and Flathub publish
mechanisms; read the two together, since credential setup and "what is the publish action even
made of" turn out to be the same investigation from two directions.

## #196: `OrcshotTrayButton`'s own right-click menu doesn't open on GNOME Shell/Wayland (RESOLVED 2026-09-05)

Found live during BACKLOG #189's tray-modernization work (2026-09-05), while verifying the new
real left-click fix on the Ubuntu 26.04 GNOME Shell 50.1 VM. Real, reproducible, and confirmed
**not** caused by that work: right-click on the tray icon never opens its own popup menu, even in
a fully vanilla build of `orcshot-tray@orcshot.org`'s `OrcshotTrayButton` with every bit of the
new left-click code stripped back out.

Isolated cleanly, not guessed:
- Right-click works fine elsewhere in the exact same live session - the real desktop context menu
  (via Nautilus) and GNOME's own Quick Settings panel button both open correctly on a right-click
  from the same `xdotool` method. Not an input-relay/xdotool problem.
- A debug listener on `this.menu`'s own `'open-state-changed'` signal, added to the vanilla
  (no-left-click-code) build, never fires at all for a right-click on this specific button - the
  base `PanelMenu.Button` class's own `Clutter.ClickGesture` "recognize" handler (which
  unconditionally calls `this.menu?.toggle()` for any click, confirmed against real upstream
  GNOME Shell source) isn't even recognizing the click on this actor.

Real, suspicious correlate found in the journal, not yet confirmed as the root cause: on every
single real test session tonight, `orcshot.service` (the autostart unit) fails its first launch
attempt with `cannot open display`, then a scheduled systemd restart succeeds
(`journalctl --user`: "orcshot.service: Scheduled restart job, restart counter is at 1" - every
time, no exceptions). This means `org.orcshot.Orcshot`'s D-Bus bus name genuinely
appears/vanishes/reappears once during every real login, which is exactly the kind of double
construction/teardown a button-lifecycle bug would come from - a real (if separately-timed) `JS
ERROR: Object ... OrcshotTrayButton ..., has been already disposed` was also seen once in the same
journal, from an earlier test session's logout.

**What this needs**: root-cause why the `cannot open display` race happens on first launch at all
(likely a systemd unit ordering issue - the autostart unit probably needs to wait on the graphical
session/display being fully ready, not just the user session starting), then re-verify whether
fixing that race also fixes the tray button's own right-click. If it doesn't, the button's own
`enable()`/bus-watch lifecycle in `orcshot-tray@orcshot.org/extension.js` needs its own real
audit for double-construction or stale-reference bugs across an appear→vanish→appear cycle.

**Consequence if left unfixed**: GNOME/Wayland users can't reach the tray's own menu (Capture
Full Screen, Window Picker, Open File, Preferences, Quit) at all via right-click - only the
left-click default (Capture Region) works. Real, user-visible, but not new: this predates
BACKLOG #189's work entirely (confirmed live in a build with none of that work's code present).

**RESOLVED.** The systemd race this entry already suspected was the real root cause -
`debian/orcshot.user.service` had `PartOf=` and `WantedBy=graphical-session.target` but no
`After=`, so neither ordered a *start* against the target. Adding `After=graphical-session.target`
fixed it: `NRestarts=1` on every boot before the fix (matching this entry's own "cannot open
display... every time" description), `NRestarts=0` across 3 clean reboots after, on the real
Ubuntu 26.04 VM this ticket was originally found on. Live-verified afterward: right-click now
opens the menu, confirmed both by direct observation and by a stage-level `captured-event` log
showing the real `BUTTON_PRESS button=3` reaching `PanelMenu.Button`'s own `ClickGesture`
correctly.

A second, separate bug turned up immediately once the menu could actually open: every item in it
showed disabled/greyed regardless of its real state, persisting across repeated opens (not just
the first one). Root-caused via direct GJS reproduction against the real D-Bus service:
`Gio.DBusActionGroup`'s initial sync with the server is asynchronous with no public "ready"
signal - neither `'action-added'` nor `'action-enabled-changed'` fires for the initial batch, and
`get_action_enabled()` silently returns `false` for everything until a non-deterministic amount of
time passes (measured live: sometimes under 200ms, sometimes still not ready past 300ms in
otherwise-identical conditions). `extension.js`'s `_rebuild()` read `get_action_enabled()`
synchronously at construction time, permanently latching every item as disabled since nothing ever
triggered a fresh read afterward. Fixed by re-reading and re-applying sensitivity for every item
when the menu actually opens (`this.menu`'s own `'open-state-changed'` signal) rather than only
once at construction - live-verified on the same VM: items show correctly enabled now.

Two real, live-VM-testing gotchas hit along the way, worth remembering: (1) a stale, pre-#189
copy of this same extension sitting in `~/.local/share/gnome-shell/extensions/` on the test VM
silently shadowed every edit made to the real system copy for most of this investigation - GNOME
Shell logs "already installed... will not be loaded" for the shadowed one, easy to miss; (2)
newly-added *system* extension directories aren't picked up by an already-running GNOME Shell
without a session restart, even though the files are already on disk.

## #195: Flatpak channel ships with no capture-complete sound at all - GSound gap was never actually tracked (RESOLVED 2026-09-01)

Found during the flatpak-channel final review's fix round (2026-08-31): `org.orcshot.Orcshot.yaml`'s
`gnome-shell-schema` module comment (added fix round 1) claims the GSound deferral is "deferred,
tracked as a real gap, not silently dropped" - but nowhere in this file ever mentioned GSound before
this entry. The only record anywhere was that one YAML comment.

**Real, permanent user-visible consequence, not cosmetic:** `gir1.2-gsound-1.0`'s `GSound-1.0.typelib`
has no equivalent in `org.gnome.Platform//50` or `org.gnome.Sdk//50` (confirmed live, fix round 1).
`capture/capture_feedback.py` guards the import (`except ValueError`) so this degrades gracefully -
`play_capture_sound()` becomes a silent no-op instead of crashing every launch. (Correcting this
entry's own earlier claim here: `settings.get_play_capture_sound()` defaults to `False`, not on -
direflail's own explicit call, made for an unrelated timing reason, documented in that function's own
docstring - so this gap only ever bit someone who specifically opted in, on this one channel.)

**Resolved for real, not just tracked**: `capture/capture_feedback.py` no longer uses GSound at all -
rewritten to play a bundled sound file (`resources/camera-shutter.oga`, the real freedesktop theme
file GSound's own `"camera-shutter"` event ID already resolved to on a standard install - see
THIRD_PARTY_NOTICES.md for the licensing) via GStreamer instead. GStreamer's Python bindings and the
`playbin`/`vorbisdec` elements this needs are already part of `org.gnome.Platform//50`'s own base
runtime (confirmed live via `gst-inspect-1.0` - no new Flatpak module needed), and real Ubuntu packages
for apt/Snap (`gir1.2-gstreamer-1.0` + `gstreamer1.0-plugins-base`). One channel-specific manifest
change was needed on top: Flatpak's `--socket=pulseaudio` (added to `org.orcshot.Orcshot.yaml`) and
Snap's `audio-playback` plug (added to `snapcraft.yaml`) - neither channel had real audio-sink access
granted before this, a gap that only surfaced because this fix added a genuine live playback
verification pass, not just a decode/crash check.

Verified live, not assumed: real audible playback confirmed on three separate real machines (this
project's own Mint dev host, a real Ubuntu 24.04.4 LTS VM, a real Ubuntu 26.04/GNOME 50 VM), and
inside a real confined Flatpak build specifically (`GstPulseSinkClock` connecting, a real `EOS`
reached, and - the strongest signal - direflail directly heard the sound play from the sandboxed app).
`capture_feedback.py`'s own module docstring has the full story.

## #194: The Flatpak manifest isn't Flathub-submission-ready as-is (RESOLVED 2026-09-04)

Found during the flatpak-channel final review's fix round (2026-08-31). Three real gaps; the
vendored-deps fix and the real AppStream metainfo file both landed on `main` via #16/#17 - full
write-up in their own PR history, not repeated here.

The third gap - `--talk-name=org.gnome.Shell` being broader than a Flathub reviewer might expect
- is **not actually narrowable**, confirmed definitively 2026-09-04: two other real, shipping
features (`capture/gnome_clipboard.py`, `capture/gnome_window_calls.py`) call their own custom
interfaces on this exact same bus name, not just the `EnableExtension` call BACKLOG originally
focused on. Flatpak's `--talk-name` filters by bus name only, not object path or interface, so
there's no manifest-level grant narrower than `org.gnome.Shell` itself that all three features
actually need - narrowing it would silently break clipboard support and window-calls capture, not
just fail to help. Full reasoning in the manifest's own `--talk-name` comment. This is the correct,
minimal grant for real reasons, not an unnarrowed placeholder - ready to explain to a Flathub
reviewer on exactly these terms if asked.

## #193: GitHub Actions `ubuntu-24.04` runners hit `dconf-CRITICAL: Permission denied` on a real, unconfined `gnome-shell` too (RESOLVED 2026-09-04)

Found as a side effect of BACKLOG #185's Flatpak CI hard tier (task #4's own real live testing,
2026-08-31). The runner's `dconf-CRITICAL **: unable to create file '/run/user/<uid>/dconf/user':
Permission denied` warning, first seen from inside a Flatpak-confined process, turned out to also hit
the real, completely unconfined `gnome-shell --headless` process itself on this exact runner image -
confirmed by pulling the actual job log and finding the identical error at that process's own startup,
not just the Flatpak-confined one. Originally recorded as *not* affecting anything this project
tested, since `enable_extension_live()`'s direct D-Bus activation bypasses `dconf` entirely.

**That turned out to be wrong** (PR #18, 2026-09-04): `flatpak.yml`'s own final persistence check
(`gsettings get org.gnome.shell enabled-extensions`, reading the real host dconf directly) failed
with this exact warning on a PR that touched nothing but `BACKLOG.md` - then passed clean on an
immediate re-run of the identical code, confirming the warning's real-world effect is genuinely
intermittent, not the harmless no-op it was first assumed to be.

**Real root cause**: `systemctl start user@<uid>.service` (this job's own way of getting a user D-Bus
session bus without a real login) brings up the session bus but, unlike a real login opened via
`pam_systemd`, does not create `/run/user/<uid>/dconf/` - `dconf-service` creates that subdirectory
itself, lazily, on first use, and loses that race against this exact runner's timing often enough to
matter. `snap.yml`'s own equivalent persistence check never showed this flakiness not because it
solved the race, but because it reads back through the same confined settings backend it wrote
through instead of host dconf directly - never actually exposed to it.

**Fix, confirmed live**: `flatpak.yml` now creates `/run/user/<uid>/dconf/` explicitly, right after
the session bus appears and before anything tries to write through it - removes the race instead of
hoping to win it. Confirmed with three separate, consecutive `flatpak / verify` re-runs on the same
PR (#19), all green - deliberately more than the single green run that got this issue
mischaracterized as harmless in the first place.

## #192: Snap channel - gnome_shell_present() crash, and whether the tray extension actually works under strict confinement (RESOLVED 2026-08-30)

Started as a real crash risk (`Gio.SettingsSchemaSource.get_default()` returning `None` under strict
confinement, causing an unhandled `AttributeError` in `gnome_shell_present()`), confirmed live via a
diagnostic CI probe on PR #9. Two separable questions followed: (1) the crash fix itself, and (2) the
larger question direflail explicitly asked to be tackled next - does the Wayland tray extension
actually *function* under Snap at all, not just fail gracefully. Both are now resolved, PR #10, each
finding confirmed live in real CI, not guessed:

1. **The crash**: fixed - `gnome_shell_present()` now treats `get_default()` returning `None` as
   "schema not found" (`False`), same as apt/.deb's own already-correct behavior.
2. **The schema itself was genuinely unresolvable under confinement**, not just returning `False` on
   a real check: `gnome-shell-common`'s schema wasn't staged in `snapcraft.yaml` at all, and even once
   staged, Snapcraft's staging never runs the `.deb`'s own postinst/dpkg-trigger machinery, so the raw
   XML never got compiled into `gschemas.compiled` - fixed with an explicit `glib-compile-schemas`
   step (same class of gap as this file's existing BLAS/LAPACK workaround).
3. **Even correctly staged and compiled, nothing made it discoverable at runtime**: this snap uses no
   desktop-integration extension (`extensions: [gnome]` was deliberately set aside in Task 3 for a
   minimal manual-plugs approach), so nothing sets `XDG_DATA_DIRS`/`GSETTINGS_SCHEMA_DIR` the way a
   `desktop-launch` wrapper would - fixed by setting `GSETTINGS_SCHEMA_DIR` explicitly, same pattern
   already used for `PYTHONPATH`/`GI_TYPELIB_PATH`.
4. **The confined write itself (`enable_extension()`) silently fell back to GLib's keyfile backend**
   and failed outright, because the dconf GSettingsBackend GIO module (`dconf-gsettings-backend`'s
   `libdconfsettings.so`) was never staged either - fixed by staging it and adding `GIO_EXTRA_MODULES`.
5. **CI itself broke `snap run` entirely** once a session D-Bus bus existed
   (`... is not a snap cgroup for tag snap.orcshot.orcshot`) - a documented, `core24`-specific snapd
   bug (https://bugs.launchpad.net/snapd/+bug/2075560): a bare `dbus-daemon --session` has no real
   `systemd --user` behind it, and `snap run` needs `org.freedesktop.systemd1.Manager` on that bus to
   create its own confinement scope. Fixed by starting the real `systemd --user` instance instead.
6. **The deeper functional question**: `gnome_extension_setup.enable_extension_live()` (the direct
   `org.gnome.Shell.Extensions.EnableExtension` D-Bus call that normally makes the extension activate
   *this session*, not just on next login) is confirmed AppArmor-blocked under Snap's strict
   confinement (`AccessDenied`, live-tested) - no interface this snap plugs grants that call, and none
   safely could. **This turned out not to matter**: live-tested against the real, representative
   scenario (GNOME Shell already running, matching how the first-run dialog is actually ever used),
   the already-running Shell picks up `enable_extension()`'s persisted gsettings write on its own,
   with no live D-Bus call at all - confirmed via the same headless-Shell-load check the apt channel's
   own CI already relies on. `extensions: [gnome]` was not needed after all.

**Net result**: the Wayland tray extension genuinely functions under the Snap channel end-to-end -
schema resolves, the real production write persists, GNOME Shell loads it. All of this is now a
permanent, non-throwaway part of `.github/workflows/snap.yml`'s verify job, exercising Orcshot's own
real production code (`enable_extension`, `install_bundled_extension_if_needed`) through actual strict
confinement, not a stand-in.

## #191: Snap channel - deferred findings from the final review (RESOLVED 2026-08-30)

Final whole-branch review of `docs/superpowers/plans/2026-08-30-snap-channel.md` (2026-08-30, PR #9)
flagged several real, non-blocking findings. All fixed:

- **`version: git` resolved to `0+git.<sha>` in CI.** Replaced with `adopt-info: orcshot` +
  `craftctl set version=...` reading `pyproject.toml` directly - one source of truth, mirrors how
  `debian/changelog` already drives the apt channel's version, no dependency on the checkout's tag
  history. Verified locally: packs as `orcshot_0.2.0_amd64.snap`, matching `pyproject.toml` exactly.
- **Bundled extensions could never be upgraded once installed under Snap.**
  `install_bundled_extension_if_needed` now compares `metadata.json`'s own `version` field and
  replaces `dest` when the bundled copy is genuinely newer (missing treated as `0`, so
  `orcshot-tray@orcshot.org`'s own historically-versionless metadata - now given `"version": 1` -
  becomes upgradeable too). Also copies to a temp sibling and swaps it in, so an interrupted copy
  never corrupts or half-writes an existing install. TDD, full test coverage, feeds the same design
  into the Flatpak channel's own future brainstorm.
- **`RELEASING.md`'s CI-check step only mentioned `apt.yml`.** Now checks both `apt.yml` and
  `snap.yml`, matching what a real release push actually triggers.
- **The `test_deb_channel_never_calls_install_bundled_extension` test was tautological** (asserted a
  monkeypatch's own return value back at itself). The snap-path gating logic is now extracted into
  `_install_bundled_extensions_for_snap()`, a real function tests can call directly - the deb-channel
  no-op, the snap-channel install-all-three, and the prompt-on-failure path are each now genuinely
  exercised.
- **The blunt global `os.path.exists` monkeypatch** in `test_channel_detect.py` is gone -
  `detect_channel()` now takes an injectable `path_exists` parameter, matching the `env` injection
  pattern it already used.
- **Neither `apt.yml` nor `snap.yml` declared a `permissions:` block** - see `#190`, fixed for both
  files together.

Left as genuinely non-actionable: the CI check script writing into the live GNOME Shell extensions
directory rather than a `.ci/` subdirectory - harmless residue on an ephemeral, destroyed-after-the-job
CI runner, not worth the complexity of a separate directory.

## #190: apt CI workflow hardening (RESOLVED 2026-08-30)

Final whole-branch review of `docs/superpowers/plans/2026-08-29-apt-ci-automation.md` (2026-08-29)
flagged several Minor, non-blocking hardening items. All fixed, applied to both `apt.yml` and
`snap.yml` together (the same gaps existed in both):

- **`permissions: contents: read`** added at the top level of both workflows - makes the
  already-default repo setting explicit at the file level, not dependent on a setting someone could
  change later.
- **`concurrency:` group + `cancel-in-progress: true`** added to both - repeated pushes to the same
  PR branch now cancel the superseded run instead of all running in parallel.
- **`timeout-minutes: 20`** added to every job in both workflows - bounds a hung step (e.g.
  `gnome-shell` never logging its startup line) instead of burning the default 6-hour job timeout.
- **A clarifying comment on what the headless-Shell check actually proves** - added to both
  `apt.yml` and `snap.yml`'s equivalent check: it proves the extension loads, initializes, and its
  D-Bus name-watcher wires up correctly; it does not exercise menu construction or rendering.

Reviewed and deliberately left as-is:
- **The test suite running twice in `build`** (explicit `pytest` step + `dpkg-buildpackage`'s own
  `override_dh_auto_test`) - catches a real, distinct signal (PyPI-resolved dev deps vs. the distro's
  `python3-pytest`), not pure waste.
- **Mixed merge styles in `main`'s history** - already settled in practice via this session's own
  squash-merge convention for the two most recent large PRs; no code change needed.

## #187: Prove (or disprove) whether `fallback-x11` gives real, unrestricted X11 capture under Flatpak (RESOLVED 2026-08-30)

**Proven true, for real, not just reasoned about.** A throwaway `flatpak-builder` spike (`org.freedesktop.Platform`/`Sdk` 24.08, `finish-args` declaring
*only* `--socket=wayland` and `--socket=fallback-x11` - no portal, no D-Bus, no filesystem access at
all, confirmed by reading the exported metadata directly) made a real X11 protocol call (raw
`python-xlib`, `root.get_image()` on this host's own Mint/Cinnamon X11 session - the identical
protocol-level operation `X11CaptureBackend` performs via GDK, just without pulling in the whole GTK3
stack for a spike) from inside the confined sandbox:

```
root window geometry: 4480x1440
captured 25804800 bytes
unique byte values in first 10000 bytes: 40
SPIKE RESULT: REAL CAPTURE - varied pixel data returned through fallback-x11
```

Real, varied screen pixel data, not a black/blocked response - `fallback-x11` genuinely grants
unrestricted native X11 capture on a pure-X11 session, exactly as the reasoning below predicted. The
exported metadata does list `sockets=x11;wayland;fallback-x11` together - this is `fallback-x11`'s own
correct, documented representation (a conditional x11 grant, active only when Wayland isn't the session
type), not a broader permission that crept in; the manifest itself only ever declared the two intended
sockets. Spike code discarded per its own classification - nothing kept, this entry is the record.

**What this means for #185**: its "Wayland-only, X11 users redirected elsewhere" framing is
unnecessarily narrow, confirmed now rather than assumed - a single Flatpak build can genuinely support
both X11 (via `fallback-x11`, full native `X11CaptureBackend`, no portal) and Wayland (via the portal
or `#184`'s now-proven extension-install path). Worth folding into `#185`'s own design pass before
building it, not treated as a separate follow-up.

**Follow-up raised directly by direflail after the above (2026-08-30): does the same reasoning hold for
Wayland's own portal-based capture path, and does `#184`'s Flatpak-filesystem-grant question (the
`channel_detect.py` extension-install mechanism) hold too? IN PROGRESS, not yet fully answered:**

1. **`--filesystem=~/.local/share/gnome-shell/extensions:create` - CONFIRMED WORKING.** Same throwaway-spike
   method as above (`org.gnome.Platform`/`Sdk` 49 this time). A confined process wrote and read back real
   content with no separate runtime "connect" step - simpler than Snap's `personal-files`, which needs
   `snap connect` after install. `channel_detect.install_bundled_extension_if_needed`'s own mechanism
   should transfer to Flatpak cleanly on this specific point.

2. **Portal `Screenshot` (`org.freedesktop.portal.Screenshot`) - genuinely inconclusive on this dev
   machine, root-caused rather than left as a guess.** First attempt (unconfined AND confined, on this
   machine's own Mint/Cinnamon desktop) failed with `response_code=2`, traced via the real portal log to
   `Failed to show access dialog: Timeout was reached` - confirmed via `xdg-desktop-portal`'s own
   `.portal` files that `xdg-desktop-portal-xapp` (Cinnamon's backend) implements `Screenshot` but *not*
   `org.freedesktop.impl.portal.Access` (the consent-dialog interface), and `xdg-desktop-portal-gtk`
   (which does implement `Access`) is `UseIn=gnome` only - a real Cinnamon-specific portal gap, not a
   Flatpak-confinement finding.
   - Retested **unconfined** on the project's own real Ubuntu 26.04/GNOME Shell 50.1 VM
     (`XDG_CURRENT_DESKTOP=ubuntu:GNOME`, genuine Wayland session): **succeeded cleanly**,
     `response_code=0`, a real 92800-byte PNG (1366x768) written to `~/Pictures/` and read back - no
     Access-dialog timeout at all. Consistent with `wayland_portal.py`'s own docstring
     ("confirmed live that calling the portal from an unsandboxed process didn't show one here").
   - **Confined-on-GNOME test run for real (2026-08-31), root-caused, not left as a bare failure.**
     `org.orcshot.SpikePortalGnome` (zero `finish-args` - strictest possible test) built and run on the
     real GNOME Wayland VM, both over SSH and from a genuinely focused terminal window (GUI mode +
     `xdotool`, to rule out "no focused app" as an artifact of SSH specifically) - both failed
     identically, `response_code=2`. The real portal log gives the exact reason, confirmed as a known,
     documented class of issue via a real upstream GitHub issue
     (flatpak/xdg-desktop-portal#1338, GNOME Shell's own `accessDialog.js`):
     ```
     Failed to show access dialog: GDBus.Error:org.freedesktop.DBus.Error.AccessDenied:
     Only the focused app is allowed to show a system access dialog
     ```
     This is **not a Flatpak-confinement wall** - it's a real, deliberate GNOME Shell security policy:
     the *requesting app itself* must be the currently-focused window. The spike script is a headless
     CLI process with no GUI window of its own at all, so it can never satisfy this check regardless of
     confinement - the terminal that launched it is a different application from GNOME Shell's window
     tracker's point of view. A real GUI app (which Orcshot genuinely is) satisfies this naturally the
     moment a user triggers a capture from within its own actual window - this was never exercised by
     the spike's own design, not a property of Flatpak.
   - **Closed completely (2026-08-31): a real GTK window spike, proven, not just reasoned about.**
     Built `org.orcshot.SpikePortalGtk` - a genuine `Gtk.Window`, shown and given 2 real seconds to be
     mapped/focused by the window manager before firing the same `Screenshot` call from inside its own
     GTK main loop. First attempt still failed identically (`response_code=2`), *despite* the window
     self-reporting `is_active()=True has_toplevel_focus=True` via GTK's own API - proving client-side
     focus alone isn't what GNOME Shell's check actually looks at. Root cause found, not guessed: the
     build had "No appstream data" (flagged in its own build log) - no `.desktop` file at all, so GNOME
     Shell's `_windowTracker` had no way to associate the window with a recognized "app" entry in the
     first place, independent of genuine X11/Wayland-level keyboard focus. Added a minimal
     `.desktop` file (`Name=Orcshot Portal Spike`, installed to `/app/share/applications/`) and
     rebuilt - **the real Access dialog appeared** ("Allow Orcshot Portal Spike to Take Screenshots?"),
     was approved, and the call succeeded cleanly:
     ```
     response_code=0
     RESULT: SUCCESS, uri=file:///run/user/1000/doc/1c3e7475/Screenshot-1.png
     RESULT: read 195685 bytes, PNG_magic=True
     ```
     Real PNG, returned through the document-portal FUSE mount exactly as `wayland_portal.py`'s own
     code comment already predicted a sandboxed caller would get (not a direct `~/Pictures` path).
     **Net result: the Screenshot portal genuinely works under real Flatpak strict confinement on real
     GNOME Wayland, end to end - real Access dialog, real user consent, real image data.** The one
     requirement it surfaced (a proper `.desktop` file with a real `Name=`) is not a workaround or a
     special case - it's standard Flatpak packaging convention any real, published Orcshot build would
     already have. Spike code and app uninstalled, nothing kept per its own classification - this
     entry is the record.

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

## #179: "Reuse Editor" setting (task #111) - assigned a number, never built (RESOLVED 2026-09-05)

direflail confirmed it's wanted (2026-09-04) after a full walkthrough of the real behavior. Built:
a Preferences checkbox ("Reuse editor window for new captures," Capture tab), a new
`EditorWindow.reset_for_capture` method, and `destination_picker._should_reuse_editor`'s pure
gating logic (unit tested - `tests/unit/ui/test_destination_picker.py`) wired into `_open_editor`,
the one real construction site every capture path already shared. Scoped to captures only, matching
real Windows' own scope for this setting (`EditorDestination.cs:96`) - File > Open still always
opens a new window, deliberately unchanged.

Live-verified, all four branches: capture-then-save-then-capture-again reuses the same window and
genuinely replaces its content (confirmed via differing image dimensions before/after); capturing
again *without* saving does not reuse (opens a new window, the unsaved-changes gate holding);
disabling the setting restores the always-new-window default even with an eligible unmodified
editor open. Full write-up in `REQUIREMENTS.md`'s own Expert-tab section.

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

## #189: Audit the X11 tray path for the same "deprecated tech" problem that motivated #184

direflail (2026-08-29), right after #184's Wayland redesign landed: "add a task to check the x11 side to
make sure it's using modern packaging/techniques." Direct follow-through on the same standing concern
that started #184 in the first place - direflail's own words from that earlier conversation: "you've
explicitly told me we can't put the app on Snap the way it is. combine that with the technologies being
17 years deprecated in cases, and i'm thinking nobody's going to want to install this app... find out if
[modern GNOME tech] can be used to make the version of this app... that will work properly and be
accepted by snap, flatpak, and apt." #184 answered that for Wayland (`AyatanaAppIndicator3` → GMenu/GAction
over D-Bus). The X11 side was never audited against the same standard.

**What's already known, not yet acted on**: `app.py`'s `_build_tray_icon` X11 branch uses `Gtk.StatusIcon`
- confirmed still in place after #184's redesign (X11's branch was deliberately left untouched, out of
that plan's scope). `Gtk.StatusIcon` has been deprecated since GTK 3.14 (2014) with **no direct GTK4
replacement at all** - GTK4 removed the API entirely, pushing every app toward exactly the
StatusNotifierItem/AppIndicator-style mechanisms #184 just finished moving Orcshot's Wayland side *away*
from. Worth checking directly (not assuming either "it's fine, GTK3 still supports it" or "it's exactly
the same problem #184 just solved") whether this specific deprecation actually causes any of the same
real, concrete problems #184 found for Wayland - Snap/Flatpak packaging friction, distro-level removal
plans, or actual runtime breakage on any of this project's three real test targets - or whether it's a
harmless "deprecated but still fully functional and unlikely to be removed" situation, which
`Gtk.StatusIcon` genuinely might be, given GTK3 itself (not just this one API) is the thing actually aging
out project-wide.

**Scope check needed before this becomes a plan**: is this really about `Gtk.StatusIcon` specifically, or
a broader "is anything else in this app's X11 path resting on similarly old GTK3/legacy APIs" audit?
direflail's request as given is general ("make sure it's using modern packaging/techniques"), not scoped
to the tray icon alone - worth a clarifying pass before writing an implementation plan, same as #184 got
before its own plan was written.

**RESOLVED 2026-09-05.** `Gtk.StatusIcon` (deprecated, XEmbed-based) is gone entirely. Real finding that
reframed this ticket: GNOME Shell hasn't hosted XEmbed tray icons since 3.26, regardless of session type
- GNOME-X11 users very likely got an invisible tray icon before this fix, not a deprecated-but-working one.
Both real supported desktops now get a native, non-deprecated tray via the same D-Bus export
(`Gio.Menu`/`org.gtk.Actions`) #184 already built for Wayland:

- **GNOME** (Ubuntu 24.04/26.04, X11 and Wayland both) - the existing `orcshot-tray@orcshot.org` Shell
  extension, now reachable on X11 too, with real left-click-to-capture added (previously Wayland's tray was
  menu-only). Left-click required real iterative debugging on an actual Ubuntu 26.04 GNOME Wayland VM to
  find a working interception mechanism (several real GNOME 45+ Clutter API techniques were tried before
  landing on the real fix: manual click-target picking via `global.stage`'s `captured-event` signal and
  `get_actor_at_pos()`, since GNOME 45+'s `PanelMenu.Button` uses a `Clutter.ClickGesture` action that
  claims raw button events before signal-based approaches see them). Live-verified end to end on two real
  VMs, one per session type - Wayland on Ubuntu 26.04, X11 on Ubuntu 24.04 (26.04 has no X11 GNOME session
  at all to test against: confirmed live, and via [OMG! Ubuntu](https://www.omgubuntu.co.uk/2025/05/gnome-dropping-x11-support-ubuntu-impact)
  and [UbuntuHandbook](https://ubuntuhandbook.org/index.php/2025/06/ubuntu-2510-remove-xorg/), that Ubuntu
  removed "Ubuntu on Xorg" as a selectable GDM session starting with 25.10, before 26.04 - 24.04 is the
  last LTS that still offers it, and the correct real target for this project's own support matrix).
  Left-click produces a real region-select overlay on both; on the 24.04/X11 VM specifically, direflail
  confirmed live that right-click also opens the tray's own menu correctly. (Right-click's own
  menu-opening behavior on GNOME/Wayland was verified working at the time this bullet was first written,
  but is tracked separately as BACKLOG #196 now that it's been found not to open at all in a vanilla
  build with none of this ticket's code present on that session type - see the note below.)
- **Cinnamon** (Mint, X11 today) - a brand-new native Cinnamon Spices applet (`orcshot-tray@orcshot.org`,
  in `resources/cinnamon-applets/`), consuming the exact same D-Bus export. Two real bugs were found and
  fixed during live verification on the real local Cinnamon dev host: an icon-rendering bug
  (`set_applet_icon_symbolic_name` doesn't work for Orcshot's full-color icon, fixed to `set_applet_icon_name`),
  and a menu-population bug (`PopupIconMenuItem`'s icon parameter doesn't accept `Gio.Icon` objects;
  fixed by using plain `PopupMenuItem` with `item._icon.set_gicon(...)` and tracking only the applet's
  own menu items for cleanup). Live-verified end to end: left-click produces a full-screen capture overlay;
  right-click shows Cinnamon's built-in entries plus all 8 real Orcshot menu items.
- **Cinnamon-on-Wayland**: shipped session-agnostic (no X11/Wayland branching in the applet code) since
  Cinnamon 6.8/Mint 23's Wayland support is architecturally expected to work the same way - but genuinely
  **not verified**, since Mint 23 hasn't shipped yet (still in Alpha). Revisit once it has.

Packaging: all three real channels (`.deb`, Snap, Flatpak) now package the new Cinnamon applet the same
way the GNOME extensions were already packaged. Verified via a real `.deb` build and `dpkg -c` confirming
both new files land at the right path.

XFCE/KDE/MATE remain explicitly out of scope, matching this project's existing precedent elsewhere.

**Note:** A separate, real, pre-existing bug was found during this work - `OrcshotTrayButton`'s own
right-click menu doesn't open at all on GNOME Shell/Wayland. This is unrelated to any changes in this
ticket (reproduces in a fully vanilla build) and is tracked separately as BACKLOG #196.

**Diagnostic logging:** the `orcshot-tray-diag` `log()` calls are kept in `extension.js`, commented out
in place rather than deleted. The "tray menu inert until a full reboot" failure recorded above (and in
`REQUIREMENTS.md`) is still open and nobody knows whether it will recur, so reproducing it should be an
uncomment-and-reinstall, not a git dig. The two click probes (`button-press-event`/`touch-event`) are the
deliberate exception - this ticket live-confirmed neither signal ever reaches the tray actor at all, so
keeping them would preserve probes already proven to log nothing; one commented line inside the stage
`captured-event` handler that superseded them covers click visibility instead. Nothing depends on these
lines any more: all three CI verify jobs used to wait for the `orcshot-tray-diag` marker as proof the
Shell had loaded the extension, and that grep silently became a 60-second timeout the moment this
ticket removed the logging. They now watch one permanent, intentional marker instead -
`log('orcshot-tray: extension enabled')` at the top of `enable()`, which fires whether or not Orcshot
itself is running. A `gnome-extensions info` state check was tried first and rejected on real
evidence: on the headless CI runner it printed nothing at all - no output, no error text, exit
status swallowed - so the check that actually works in this environment won.

Full design: `docs/superpowers/specs/2026-09-05-tray-modernization-design.md`. Full plan:
`docs/superpowers/plans/2026-09-05-tray-modernization.md`.

## #184: Explore a Wayland capture path that doesn't depend on the bundled GNOME Shell extension, to open up Snap and Flatpak (RESOLVED 2026-08-30)

**The one remaining open caveat from this entry's own final review (below - "extension-install-from-
sandbox step... still an open prototype") is now closed.** The real, non-throwaway Snap channel plan
(PR #9, hardened by `#192`'s own investigation in PR #10) built and live-verified exactly that: a
confined Snap process installing `orcshot-tray@orcshot.org`'s files into the real per-user extensions
path (`channel_detect.install_bundled_extension_if_needed`), its `enable_extension()` write reaching
real, persistent dconf storage, and GNOME Shell loading the extension from that write - all confirmed
live in real CI, not reasoned about. See `#192`'s own entry above for the full trail. The redesign
itself was already live-verified (Task 7, below); this closes the one caveat left after that.

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

**RESOLVED (2026-08-28/29) - the Snap-compatibility question that motivated this entry is now answered,
live, not just reasoned about.** Formalized as
`docs/superpowers/specs/2026-08-28-wayland-capture-redesign-design.md` and implemented via
`docs/superpowers/plans/2026-08-28-wayland-tray-redesign.md` (7 tasks, subagent-driven-development, all
merged to `worktree-wayland-tray-redesign`): a new `orcshot-tray@orcshot.org` extension (GMenu/GAction
over D-Bus, exported on Orcshot's own already-owned connection) replaces `AyatanaAppIndicator3` entirely
on Wayland; region-select, clipboard, and Window Picker were unaffected per the design's own scope.

- **The actual proof point, done for real**: a throwaway `snapcraft.yaml` (`confinement: strict`,
  `base: core24`, `extensions: [gnome]`, a `dbus` slot for `org.orcshot.Orcshot`) built and installed on
  both a Linux Mint host (`snapcraft pack --destructive-mode` doesn't work cross-distro - built via a real
  LXD-managed build instead) and the Ubuntu 26.04 Wayland VM. On the VM, under real strict AppArmor
  confinement: `gnome_tray_export.export_tray_menu()`'s `export_menu_model()` call succeeded with **zero**
  `apparmor="DENIED"` lines anywhere near `TrayMenu`/`org.gtk.Menus`/`export_menu` - confirmed not just by
  absence of denials but by a live `gdbus call` against the confined process's own exported object
  returning real, correct menu data (label, action, icon bytes all intact). The standard `desktop`
  interface plus one `dbus` slot declaration is all a real Snap package would need - no special AppArmor
  carve-out required. This is the exact mechanism (a confined process registering objects on its own
  already-owned D-Bus connection, never calling *out* to an unsanctioned bus name like `org.gnome.Shell`)
  the whole redesign was architected around, now proven under real confinement, not just read from
  `snapd`'s AppArmor policy source.
- **Expected, not a new problem**: the (out-of-scope, unchanged) clipboard extension's own
  `Ping()`-to-`org.gnome.Shell` availability check *was* denied under confinement in the same test run -
  exactly the disqualifying pattern this whole redesign exists to route around for the tray, just not yet
  applied to clipboard/region-select (tracked separately, not part of this entry's own scope).
- **Real bugs live-caught during Task 7 verification, neither Tasks 1-6 nor their reviews caught**: (1)
  the Wayland tray menu was missing icons on Open File/Preferences/Quit, a direct violation of task #146's
  existing "every icon in the wayland version must look like the x11 version" rule - fixed
  (`stock_icon_gicon()`, hand-drawn Adwaita-lookalike geometry, same as the X11 builder already used).
  (2) The panel button's own icon reused the "region" capture-mode glyph instead of Orcshot's real logo -
  a deliberate, plan-documented tradeoff direflail asked to change once actually seen live ("please don't
  change the branding on the app without talking to me first" - now a standing memory). Fixed via
  `Gio.ThemedIcon.new('orcshot')`, no new D-Bus export needed. (3) A real, root-caused bug where the
  exported `Gio.Menu` was built as a dead local variable with nothing keeping it alive -
  `g_dbus_connection_export_menu_model`'s own docs say "the data is owned by the caller of the method,"
  and every known-good example of this API (including this project's own earlier prototype) keeps it
  alive as a persistent reference. Fixed by storing it on `self._tray_menu`.
- **Open, unresolved risk, not papered over**: after the above fixes, the tray menu still failed to
  populate/respond to clicks following a plain reinstall+logout/login cycle - only a full VM *reboot*
  fixed it. Diagnostic logging (temporarily left in `extension.js`, tagged `orcshot-tray-diag`) proved
  `items-changed` never fired and the button was inert to `button-press-event`/`touch-event` entirely on
  the broken boot, while a clean reboot showed the complete correct sequence. Matches the general class of
  issue already documented in `REQUIREMENTS.md` and the `feedback-extension-reload-caching` memory
  (extension-reload cycling causing session-level corruption reaching beyond the reloaded code itself),
  but this is the first time it's been severe enough that logout/login alone wasn't sufficient - full
  reboot was needed. direflail's own read: "we didn't have this issue before. i'm guessing we'll see it
  again." **Not closed out as solved** - if this recurs on a genuinely fresh boot (not a session that's
  been through many reinstalls/logouts like today's testing), it needs real investigation, not another
  reboot-and-move-on.
- **A second, separate gap found and only partly fixed**: the new extension's UUID
  (`orcshot-tray@orcshot.org`) was missing from `gnome_extension_setup.py`/`first_run_setup.py`'s
  enable-on-first-run wizard entirely - fixed for *fresh* installs. Still open: an **existing** install
  upgrading from before this redesign already has `is_first_run_setup_done() = true`, so the wizard won't
  re-show and the new extension has no path to get enabled short of a Preferences action or a new
  upgrade-specific consent flow - deliberately not invented as part of this work, since
  `gnome_extension_setup.py`'s own docstring is explicit that enabling must only ever happen from the
  user's own confirmation click, never as a side effect of an upgrade. Real UX gap for anyone upgrading an
  existing Orcshot install to this version on GNOME Wayland - worth its own follow-up task before this
  ships as a real release.
- Also found and fixed inline (not part of the original 7-task plan): `debian/control` still required
  `gir1.2-ayatanaappindicator3-0.1` even though nothing imports `AyatanaAppIndicator3` anymore.

**One thing this result does NOT prove, caught by the final whole-branch review**: Task 7's Snap test
covered only `export_menu_model()` surviving confinement - it never exercised actually *installing* the
`orcshot-tray@orcshot.org` extension's files from inside a Snap or Flatpak sandbox at all (the throwaway
snap only shipped the app, not the extension). The "not yet proven for Orcshot specifically - would need
an actual prototype" caveat on the per-user extension-install path (this entry's own text, above) is still
exactly as unproven as it was before this branch. #185 and the real Snap package need that prototype
before either can be considered genuinely unblocked - it is not automatically covered by this result.

**Next step**: this branch (Tasks 1-7 complete, live-verified) is ready for final whole-branch review and
merge. #185 (Flatpak) and the real, non-throwaway Snap package are meaningfully closer given this result
(the actual D-Bus/AppArmor mechanism is proven), but NOT fully unblocked - the extension-install-from-
sandbox step above is still an open prototype, alongside the upgrade-path gap (#188) and the not-yet-
closed reboot-vs-logout finding.

## #185: A Wayland-only Flatpak build, alongside the existing dual-mode (X11+Wayland) `.deb`/PPA release (RESOLVED 2026-08-31)

Originally scoped (2026-08-28) as a *Wayland-only* second build: drop X11 support entirely for
Flatpak, redirect X11 users to the `.deb`/PPA at the listing level, and add an in-app runtime warning
dialog for anyone who installed it anyway on a pure-X11 session. That framing is superseded entirely -
not just refined - by what was actually designed and shipped.

**What shipped instead, and why it could**: `#187`'s own live proof (below) settled the question this
entry's original framing was working around - `fallback-x11` genuinely gives real, unrestricted X11
capture under Flatpak, with no portal involved, contrary to the original "Flatpak forces X11 through
the portal" rejection this entry was originally sidestepping. That made the Wayland-only design
unnecessary: a single manifest (`org.orcshot.Orcshot.yaml`) declares `--socket=wayland` **and**
`--socket=fallback-x11` together and gets full, direct capture on both - Flatpak's own
Wayland-present-revokes-X11-socket mechanism (real, confirmed during the original spike) turns out not
to matter, because the fallback socket being revoked on Wayland sessions is exactly correct: those
sessions use the Wayland path, X11 sessions keep the fallback socket and get real X11 access. No
listing-level redirect, no runtime warning dialog, no split "Wayland users get Flathub, X11 users get
the PPA" story - one build, one manifest, feature parity with the `.deb`/PPA release on the same host
this project's other channels already run on.

**Also resolved along the way**, each with its own BACKLOG entry: `#187` (fallback-x11 proof),
`#192`'s Snap-channel precedent for the Shell-extension/schema/confinement questions this design also
had to answer for Flatpak, and this same fix round's own final-review pass (9 commits,
`f9a48e8..8c5a743` plus this fix round) - including a real Critical bug (autostart silently aborting
first-run setup on this channel, fixed by hiding the autostart checkbox outright here since there's no
systemd access to offer it against at all) and a live attempt to narrow the `--talk-name` D-Bus grant
this design needs for the tray extension to activate immediately, reverted after live-testing showed
it genuinely doesn't work on a real GNOME Shell (see `#194` below). See
`.superpowers/sdd/2026-08-31-flatpak-channel/` for the full design spec, plan, and final review.

**Still open, tracked separately now rather than under this entry**: `#194` (Flathub submission
readiness - `--share=network` during build, appstream metadata) and `#195` (the Flatpak channel's own
GSound gap - no capture-complete sound on this channel).

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

## #205: Spec the Snap-compliant GNOME Shell extension delivery (extensions.gnome.org instead of a personal-files home write) - and research every open gap before designing, so this does not become another refactor found on the way in

Raised 2026-09-11 while starting #198's Snap half for real. `snapcraft login` and
`snapcraft register orcshot` were done that night (name registered public, account
`artificialorctelligence`, login expires 2027-09-11, checkable with `snapcraft names` and
`snapcraft whoami`). Live research of the store's current review policy then showed that the
first upload of the snap as it stands would be held for human review on two counts, and that one
of them may never be granted. direflail's instruction on creating this entry: spec the change out,
and first research everything still unknown about it - "I've had enough of walking into unexpected
situations causing refactors, let's put this to bed." So this entry is deliberately the research
list as much as the change, and the spec it produces must not leave any item below undecided.

**What is proven (live, 2026-09-11), not remembered:**
- Any use of the `personal-files` interface needs an approved snap declaration before a revision
  can be released to any channel (snapcraft.io's own interface reference). Our plug
  `dot-local-share-gnome-shell` writes to `$HOME/.local/share/gnome-shell/extensions`.
- On 2026-09-03/04 the store refused AppImage-Installer's `personal-files` *write* access to
  `~/.local/bin` and `~/.local/share/applications` as "a trivial confinement escape" - refused
  even for manual connect, after 8 days, and the developer deleted the snap
  (forum.snapcraft.io/t/52903). Orcshot's plug is that pattern in a sharper form: a confined
  process writing JavaScript into the directory the *unconfined* GNOME Shell loads and executes.
  No snap was found that has ever been granted write to `gnome-shell/extensions`.
- The `dbus` slot for `org.orcshot.Orcshot` also triggers "human review required due to
  'deny-connection' constraint", but that one is routine for an app-owned session name: BusyMax
  asked 2026-06-23, granted 2026-06-25, later uploads pass automatically (forum t/51941).
- The store checks only what the snap *declares*, never whether features work. A degraded snap
  passes review exactly as easily as a full one.
- Under strict confinement, Orcshot cannot *call* `org.gnome.Shell` at all (AppArmor, #184,
  live-tested), so today the `personal-files` write only ever buys Snap users the tray extension
  (Shell-to-app direction, proven in #184). `orcshot-clipboard` and `window-calls` get copied and
  enabled but never answer; the app already falls back to the portal-based
  `WaylandCaptureBackend`/`WaylandClipboardBackend`.
- Read from the code, not live-tested: Snap first-run (`ui/first_run_setup.py`) also copies the
  Cinnamon applet to `$SNAP_REAL_HOME/.local/share/cinnamon/applets`, a path the plug does not
  grant. Under confinement that copy fails on every desktop including GNOME, `all_installed`
  goes False, and `show_snap_connect_prompt` shows on every launch - a prompt whose `snap connect`
  cannot fix it. CI never sees this because `snap.yml` only exercises the GNOME path. Not tracked
  separately: the change this entry specs deletes that code path outright.

**The change to spec (alternative chosen 2026-09-11 over petitioning for the declaration):**
distribute the three GNOME Shell extensions through extensions.gnome.org. The snap then writes
nothing into the home directory: Snap first-run tells the user the Orcshot extension is needed
and sends them to install it, then detects it via the `org.gnome.shell enabled-extensions`
GSettings read that `snap.yml` already proves works under confinement (#192). The
`personal-files` plug, `show_snap_connect_prompt`, the copy-into-home path, and the
`snap connect` step in `snap.yml` all go. The only store gate left is the routine `dbus` slot.
This complies by construction rather than by petition, and costs the user no more friction than
today's design, which already requires a manual `snap connect` that never auto-connects.

**Research list - every one of these is a gap as of 2026-09-11, and the spec must close each
with a live-verified answer or an explicit decision, never an assumption:**
1. Run the store's own reviewer locally before anything else: `snap install review-tools`, then
   `review-tools.snap-review` on the snap CI already built (run 34188615922, `dd63e61`). That is
   the exact store verdict on the current `snapcraft.yaml`, on paper, and it may list things
   beyond the two above. It becomes the pre-upload check in the snap ingredient (#198).
2. extensions.gnome.org's current submission process and policies: per-extension listing, review
   on every update (not just the first), current turnaround (unverified - said "days" once, may be
   weeks), UUID/naming rules, required `metadata.json` fields (`shell-version` ranges,
   `session-modes`), and anything that would reject code that imports from
   `resource:///org/gnome/shell/` the way `orcshot-clipboard` imports GrabHelper.
3. `window-calls@domandoman.xyz` is our patched fork of ickyicky/window-calls, which is itself on
   EGO. Decide: upstream the four fixes (is upstream maintained?), or publish a renamed fork under
   a new UUID (EGO rejects duplicate UUIDs; GPL-2.0-or-later terms carry). Either way the app's
   `WINDOW_CALLS_EXTENSION_UUID` may change.
4. How a stock Ubuntu 24.04/26.04 user actually installs from EGO today. The in-browser install
   needs the browser connector Ubuntu no longer ships; `gnome-extensions install` takes a local
   zip; Extension Manager is a Flatpak. The snap cannot download anything itself. Which path do we
   send the user down, from inside strict confinement, and does `xdg-open` to the EGO URL through
   the `desktop` interface's OpenURI portal work there (assumed, not tested)?
5. The version handshake. Extension updates will arrive through GNOME's own EGO update mechanism
   on its own schedule, decoupled from app releases. Which side declares compatibility, how a
   mismatch is detected and surfaced, and whether a user-dir EGO copy shadowing a `.deb`'s
   system-wide copy (user copies win in GNOME Shell) can produce a mismatch on the *deb* channel
   too. The existing `metadata.json` `version` field (#191) is the raw material.
6. Whether the same change should apply to Flatpak in the same pass. The manifest today grants
   `--filesystem=~/.local/share/gnome-shell/extensions:create` for the same copy-into-home
   design; Flathub reviewers scrutinize home filesystem grants the same way. If the EGO route
   drops that override too, it simplifies #198's Flathub half and must be decided now, not found
   during that submission.
7. Whether the `.deb` keeps bundling the extensions system-wide (presumably yes - nothing forces a
   change) and what the first-run dialog says on each channel once the three diverge.
8. Cinnamon: snapd is blocked by default on Linux Mint, so a Snap-on-Cinnamon user is close to
   nonexistent. Decide whether the snap's first-run drops the Cinnamon applet install entirely,
   and whether Cinnamon Spices is ever worth a listing. The `.deb` is unaffected.
9. The one thing the EGO route does not fix: `orcshot-clipboard` and `window-calls` still cannot
   be *called* from a strict snap. #184 proved the inversion for the tray (Orcshot exports on its
   own `dbus` slot, the unconfined extension reaches in). Whether the same inversion works for
   request/response features - the extension subscribing to signals the confined app emits on its
   own connection and calling results back - is a hypothesis from that precedent, never tested.
   The spec must decide whether that is in this change's scope or explicitly deferred with its
   own entry; it must not be left implied.
10. Release strategy: the store has `stable`/`candidate`/`beta`/`edge`. Releasing to `edge` or
    `beta` first gets the `dbus` declaration granted and the pipeline exercised without the public
    `stable` listing. Review holds apply to every channel. Also the one-time store listing (icon,
    screenshots, category) lives in the snapcraft.io dashboard, not `snapcraft.yaml`, and the snap
    is amd64-only because CI builds one architecture - both to be stated in RELEASING.md's
    one-time setup, not discovered at release time.

**Scope boundary:** this is a code and design change to Orcshot's extension delivery and Snap
first-run, and it must land *before* `/orc-package snap` is applied - the `personal-files` plug
in `snapcraft.yaml` on the first upload would hold that upload regardless of anything decided
afterwards. #198 stays the entry for the publish mechanism itself (ingredient, `channels.yaml`
leaf, RELEASING.md steps); it now depends on this one for Snap. #186 (metrics) and #197
(credentials) are unchanged. Deliverable: a spec under `docs/superpowers/specs/` via
`superpowers:brainstorming`, with the ten items above each answered in it, then a plan.

**Update 2026-09-11 (later the same day) - research done, scope widened by two decisions.**
Items 1, 2, 3, 4, 5, 6 and 9 are closed with live evidence (notes carried into the spec):
`review-tools` on the CI-built 0.3.0 snap fails on exactly the two predicted holds and on
nothing else, and with only the plug removed the `dbus` slot is the sole hold; a stock Ubuntu
26.04 has no EGO install helper at all (no Extensions app, no Extension Manager, no browser
connector - all in universe, none seeded), so "send the user to EGO" does not work as written;
the sanctioned paths differ per channel - Flatpak calls `org.gnome.Shell.Extensions.InstallRemoteExtension`
(already permitted by our `--talk-name=org.gnome.Shell`; exactly how Extension Manager on
Flathub does it, with no filesystem grant), Snap bundles a packed zip and the user runs
`gnome-extensions install` once, since no snapd interface grants `org.gnome.Shell.Extensions`;
GNOME Shell's own `extensionDownloader.js` forces any per-user copy of an EGO-listed UUID to
EGO's version on login (upgrade *and* downgrade), so EGO owns the version once published; EGO
overwrites `metadata.json`'s `version` with its own counter, which breaks #191's comparison the
moment we publish. And item 9 is proven, not hypothesised: on the VM, inside the #184 strict
test snap (same interface set as the real one), a stateful GAction state change reached an
unconfined listener as `org.gtk.Actions.Changed` and the listener's method call back into the
confined app was answered - zero AppArmor denials. snapd's own `dbus.go`/`desktop.go` confirm
why: the slot grants receive-from-unconfined on the app's name and path, and `desktop` grants
exactly that one signal outbound.

Decisions taken with direflail: **one merged extension** (`orcshot@orcshot.org`; three UUIDs
would mean three EGO listings and three reviews per update, and EGO rejects unrenamed forks
anyway); **capability handshake** - the extension calls the app on enable with what it can do,
rather than a version compare; **the inversion is in scope** (one code path across all three
channels, one EGO review instead of two, and the `.deb` on the VM is the ungated test bed for
it); **the snap does nothing for Cinnamon** (Mint blocks snapd by default and ships Flathub, so
Mint = PPA or Flatpak); and **EGO is a fourth channel in its own right**, not a snap detail:
its own account, one-time first-submission review, per-release `gnome-extensions upload`
(verified present on GNOME 50; absent on the Mint host, so it runs where GNOME Shell lives),
its own confirmation via the `extension-info` API, and an `ego` ingredient captured for Orclab
alongside `snap` and `flatpak`. Its RELEASING.md step is deliberately not a gate on the app
channels - review lag is unbounded, so the app must tolerate one release of extension skew,
which is what the capability handshake buys. Items 7, 8 and 10 are settled by those decisions.

**Update 2026-09-12 — implemented, not yet resolved.** Tasks 1–8 of
`docs/superpowers/plans/2026-09-11-snap-compliant-extension-delivery.md` are on branch
`snap-compliant-extension-delivery` (PR #23): one extension, inverted direction, per-channel
first-run, packaging without the plug/grant, the two publishing leaves and RELEASING.md steps 3-4.
Live-verified on 26.04 (GNOME 50) and 24.04 (GNOME 46) - `VERIFICATION.md` Scenario 1 has every
command and result. Three things the verification pass found and fixed on the way: the snap's GUI
had never launched at all (#206, pre-existing, fixed on the branch); the install dialog must be a
no-op when Hello already arrived; and `/orc-publish` had been crashing on this project's
`channels.yaml` since 8f52377 (an unknown `filename_template:` key - now a comment). Spec
verification items 2, 3 and 4 are answered by test (see VERIFICATION.md E and D); items 1 and 5
wait for the listings. Open until the EGO first submission and the Spices PR are accepted (plan
Task 9), which is when the Snap and Flatpak first-run redirects point at something real; #198
then proceeds with `/orc-package snap` and `flatpak`.

**Update 2026-09-12 — EGO first submission uploaded.** direflail created the extensions.gnome.org
account `artificialorctelligence` and ran `gnome-extensions upload --accept-tos` on the 26.04 VM
(GNOME 50; the command does not exist on the Mint host). "Orcshot (0.4.0)" now sits in EGO's
public review queue (`https://extensions.gnome.org/review/`, 298 entries at the time) and is not
yet in `extension-query` results, which is the expected pre-approval state. Nothing to do but
wait; a reviewer ping is possible on the GNOME Extensions Matrix channel if it stalls.

**Update 2026-09-12 — Spices withdrawn from this entry's scope.** Putting the Cinnamon applet on a
real Cinnamon panel for the Spices screenshot showed the mandatory About/Remove items every
applet carries; direflail does not want them, so the applet is being replaced by an app-owned
`XApp.StatusIcon` (#208, researched: no apt or Flathub rule in the way, Warpinator is the
precedent). The Spices leaf, RELEASING.md step, sync script and the Flatpak-on-Cinnamon dialog
are removed from the branch; RELEASING.md is back to 13 steps. Task 9 is now EGO only, and the
upload is done. #205 resolves when EGO accepts the extension and the Flatpak install flow is
re-tested against the real listing.

## #206: The snap's GUI has never launched: gdk-pixbuf has no loaders.cache under confinement, so Gtk.Window.set_default_icon_from_file crashes do_startup (RESOLVED 2026-09-12)

Found 2026-09-11 during BACKLOG #205's live verification (plan Task 7, step 3), the first time
anyone launched the Orcshot snap as a GUI app rather than `orcshot --help`. Under strict
confinement `do_startup` dies on its second line:

    gi.repository.GLib.GError: gdk-pixbuf-error-quark: Couldn't recognize the image file format
    for file "/snap/orcshot/x1/lib/python3.12/site-packages/orcshot/resources/orcshot.png" (3)

Confirmed pre-existing, not introduced by #205: the `main`-branch snap (CI run 34188615922,
dd63e61) crashes identically when launched the same way (`systemd-run --user ... snap run
orcshot` inside the 26.04 VM's graphical session). It has always been this way; CI's
`verify-snap` job runs `orcshot --help`, which exits before `do_startup`, and every other check
in that job is a Python snippet under `snap run --shell`. So the store-declaration work (#198,
#205) was being done for a snap whose main window has never opened. The tray icon still
appears for a second before the crash because the bus name is owned before the icon load.

**Root cause, read inside the confined shell, not assumed:** the PNG loader *is* staged
(`$SNAP/usr/lib/x86_64-linux-gnu/gdk-pixbuf-2.0/2.10.0/loaders/` is populated) but there is no
`loaders.cache` beside it and neither `GDK_PIXBUF_MODULE_FILE` nor `GDK_PIXBUF_MODULEDIR` is
set, so gdk-pixbuf consults its compiled-in default path under the core24 base, which has no
loaders at all. Same class of gap as #192's `GSETTINGS_SCHEMA_DIR` / `GIO_EXTRA_MODULES` findings:
a dpkg trigger (`gdk-pixbuf-query-loaders` via libgdk-pixbuf-2.0-0's postinst) that a real apt
install runs and snapcraft's staging never does, plus an environment variable the `gnome`
snapcraft extension would have set and this hand-rolled snapcraft.yaml does not.

**Fix (this branch, since #205's snap verification is blocked on it):** run
`gdk-pixbuf-query-loaders` in `override-prime` to write `loaders.cache` with `$SNAP`-relative
paths, and set `GDK_PIXBUF_MODULE_FILE` in the app's `environment:`. Verified by the same
launch method once CI rebuilds the snap. `verify-snap` also gains a real GUI launch so this
class of crash cannot hide behind `--help` again.

**Scope boundary:** snap only. The Flatpak uses the GNOME runtime, which carries its own loader
cache; the .deb installs via apt, whose trigger runs. Neither is affected.

**Correction, same session, after testing the fix in place:** the root cause is one layer
lower than the loader cache. A `loaders.cache` generated inside the sandbox and passed via
`GDK_PIXBUF_MODULE_FILE` changed nothing, and `PixbufLoader.new_with_type("png")` decoded the
file fine - so the loaders were never the problem. gdk-pixbuf 2.42 detects a file's format
through GIO's `g_content_type_guess`, which inside the snap answered `application/octet-stream`
for a real PNG: `XDG_DATA_DIRS` is empty there, the core24 base has no `/usr/share/mime`, and
the staged `shared-mime-info` carries only `packages/freedesktop.org.xml` because
`update-mime-database` is a dpkg trigger staging never runs (#192's pattern exactly). Injecting a
compiled mime database into the sandbox's private /tmp and setting `XDG_DATA_DIRS` to it made
`set_default_icon_from_file` succeed on the spot. The fix is therefore `update-mime-database`
in `override-prime` plus `XDG_DATA_DIRS: $SNAP/usr/share:/usr/share` in the app environment.

**Resolved for real, not just tracked (2026-09-12):** the mime-database fix alone was one crash
deep - the next launch died in GTK's Wayland backend on missing XKB data. The real fix was the one
#192 had set aside: `extensions: [gnome]` on the app in `snapcraft.yaml`. Its `desktop-launch`
wrapper and the gnome-46-2404 platform snap supply gdk-pixbuf loaders, XKB, mime, themes and every
environment variable that had been hand-patched in. Verified three ways: (1) CI run 34671292380's
new "Launch the real GUI under the headless Shell" step passes - the app owns its bus name and
logs no traceback; (2) on the 26.04 VM the snap's first-run window appeared (the snap's first
window ever), and in a fresh session with the extension loaded a `tray-full_screen` capture went
through the Shell menu into the editor, strictly confined; (3) `review-tools` on that build still
lists only the `dbus` slot. The gnome extension's plugs are all auto-connect; nothing new for the
store. The one leftover is a harmless log line about our staged librsvg's SVG loader versus the
platform's - cleaned up when the duplicated stage-packages are pruned, not urgent.

## #207: Autostart-on-login has no working mechanism under the snap: systemctl --user is not executable inside strict confinement

Found 2026-09-11 on the snap's first-ever GUI launch (the #206 fix made that possible; plan Task
7 for #205). First-run offered "Start automatically at login" checked by default, and clicking
Enable raised `PermissionError: [Errno 13] Permission denied: 'systemctl'` out of
`autostart.enable_autostart` -> `_run_systemctl_user`, leaving the dialog stuck. The autostart
feature is implemented as a systemd user unit shipped by the .deb and toggled with
`systemctl --user`; a strict snap can execute neither (no systemd access, and the unit is not
installed anyway) - the same reason BACKLOG #185 hid the checkbox on Flatpak.

**Fixed now:** the checkbox is hidden on every channel but the .deb (first-run and the
Preferences checkbox both key on `detect_channel() == "deb"`), and `_run_systemctl_user` reports
`PermissionError` the way it reports "not installed" instead of letting it escape a GTK
callback. Snap users get no autostart offer rather than a crash.

**Still open - the real feature:** snapd has its own autostart mechanism (a desktop file under
`$SNAP_USER_DATA/.config/autostart` plus `autostart: <file>.desktop` on the app in
`snapcraft.yaml`, honoured by snapd's own user-session-autostart at login). That is the
channel-native way to offer "start at login" on Snap, and Flatpak's equivalent is the
Background/Autostart portal (`org.freedesktop.portal.Background.RequestBackground`). Neither is
built; both are the deferred half of #185's ruling, now with two channels waiting on it. Not
part of #205.

## #208: Replace the Cinnamon applet with an XApp.StatusIcon owned by the app - no About/Remove, no Spices submission, native on Mint

Decided by direflail 2026-09-12, after the Cinnamon applet sat on a real Cinnamon panel for the
first time (the Mint host, during #205's Spices submission prep). Two things were found there,
both real:

1. Every Cinnamon *applet* carries **About…** and **Remove '<name>'** in its right-click menu -
   Cinnamon adds them, and Mint's own review rules call them mandatory. None of direflail's other
   tray icons have them, because those are *status icons* (XApp / StatusNotifier) displayed by
   Cinnamon's built-in `xapp-status` applet, not applets. The 2026-08-28 tray redesign chose an
   applet for Cinnamon and nobody showed direflail this consequence before the decision; it was
   discovered on their panel instead. That is a process failure worth naming
   (`feedback_show_final_output_before_shipping`): a UI-visible change needs to be *seen* before
   it is decided, not described.
2. The applet also had two latent bugs, both fixed the same night on the #205 branch and both
   confirming it had never really been exercised: #196's "every item greyed" bug (never ported
   from the GNOME tray), and captures started from the menu getting the menu itself baked in
   (the applet fired the action before Cinnamon's menu had faded out).

**The replacement, researched live 2026-09-12 (`currency-discipline`), no memory involved:**
`XApp.StatusIcon` from libxapp - Mint's own, current tray library (3.2.x), the mechanism Mint's
applications use. The icon belongs to the app process; Cinnamon's stock `xapp-status` applet
displays it, so it gets the same plain menu as every other tray icon, nothing appended. Nothing
to install on any channel, so the Spices submission and everything built for it go away.

- **apt/PPA:** `gir1.2-xapp-1.0` is in Ubuntu noble (2.8.2) and resolute (3.2.2), Mint has 3.2.3.
  One Depends line. The GI API on the Mint host exposes `primary-menu`/`secondary-menu` (plain
  Gtk menus - `Gtk.Menu.new_from_model` on the menu model the app already exports for the GNOME
  tray, with the app's action group inserted) and an `activate` signal for the left-click
  region capture.
- **Flatpak:** precedent is Warpinator (`flathub/org.x.Warpinator`, Mint's own app, GNOME runtime
  49): `--own-name=org.x.StatusIcon.warpinator`, `--talk-name=org.x.StatusIconMonitor.*`, and
  libxapp built as a module from `github.com/linuxmint/xapp` tag 3.2.2 with
  `-Dapp-lib-only=true` (a build mode Mint added for exactly this). We copy that module and the
  two lines with `orcshot`. The bus name is deterministic - read from libxapp's
  `xapp-status-icon.c`: `org.x.StatusIcon.<prgname>` unless `name` is set to a valid 4-part
  `org.x.StatusIcon.*` name - so `org.x.StatusIcon.orcshot`, no guessing.
- **Snap:** unaffected (Cinnamon-on-Snap is out of scope by direflail's decision).
- **GNOME:** unaffected; the Shell extension stays the tray there. XApp is used only when the
  desktop is Cinnamon, chosen the same way first-run already tells the desktops apart.
- **Cinnamon on Wayland:** xapp-status works over D-Bus, session-agnostic.

**The one thing not proven by execution:** that the libxapp module builds inside *our* manifest
(GNOME runtime 50; Warpinator's is 49). It goes in CI before this is called done.

**Scope:** implement `XApp.StatusIcon` for Cinnamon in the app; add the Depends and the Flatpak
module + two finish-args; delete `src/orcshot/resources/cinnamon-applets/`, its
`debian/orcshot.install` lines, and the Cinnamon branch of first-run's install redirect. The
Spices pieces (channels.yaml leaf, RELEASING.md step, `scripts/spices-sync.sh`, the
`flatpak-cinnamon` dialog) are removed from the #205 branch before it lands, so this entry
starts from a clean base. direflail's Spices fork
(`artificialorctelligence/cinnamon-spices-applets`) can be deleted.
