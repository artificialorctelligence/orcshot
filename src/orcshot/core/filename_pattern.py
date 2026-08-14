"""Filename pattern resolution - task #95's Output tab "preferred file
settings". Two mutually exclusive modes, chosen explicitly (a dropdown
next to the pattern field, settings.OutputSettings.filename_pattern_mode)
rather than mixed in one pattern - direflail's own call, after live
testing showed why: a bare "%" prefix immediately followed by an
ordinary letter is inherently ambiguous with itself in free text (see
git history/REQUIREMENTS.md for the concrete corruption case -
``strftime("a%screenshot.png")`` silently eats the "s", and even a
curated "safe" whitelist doesn't fix it - %d ate the "d" out of an
otherwise ordinary word "done"). One delimiter convention active at a
time removes the ambiguity entirely, since the mode that ISN'T
selected is simply never parsed at all - its own special characters
are just literal text.

MODE_GREENSHOT: faithful-in-spirit port of FilenameHelper.cs's
${TOKEN} substitution (FillPattern, FilenameHelper.cs:344-441) - a
subset of Windows' real token set (date/time components, ${NUM} - the
save counter, settings.consume_filename_counter -, ${RRR...} - random
alphanumerics, length = number of R's, FilenameHelper.cs:197,319's own
charset -, and ${title}), not the full thing (no ${domain}/${user}/
${hostname}/environment-folder tokens - low value here, storage
location is already its own separate setting; no ${now}/${capturetime}
- redundant with the individual date tokens for this port's simpler
no-culture-mode design). "%" is never parsed in this mode at all - pure
literal text, matching real Windows' own behavior exactly (it only
ever understands ${...}).

MODE_STRFTIME: real Linux/Python users' actual standard convention
(cron, `date`, systemd timestamps all use it) - the genuine, full
datetime.strftime(), not a restricted subset, since this is now an
explicit opt-in and the standard "%%" escapes a literal percent" is
expected, documented behavior for anyone choosing this mode
deliberately, not a silent footgun. ${...} is never parsed in this
mode - pure literal text.
"""

from __future__ import annotations

import random
import re
import string
from datetime import datetime

MODE_GREENSHOT = "greenshot"
MODE_STRFTIME = "strftime"

# Matches quick_save_filename's own pre-existing default format
# (settings.py) - Windows' real default additionally appends
# "-${title}" (ICoreConfiguration.cs:127), dropped here for the same
# reason quick_save_filename already documented: not every capture
# mode has a single associated window title (region/full-screen
# capture don't).
DEFAULT_FILENAME_PATTERN = "${YYYY}-${MM}-${DD} ${hh}_${mm}_${ss}"

_TOKEN_WIDTHS = {"YYYY": 4, "MM": 2, "DD": 2, "hh": 2, "mm": 2, "ss": 2, "NUM": 6}
_TOKEN_RE = re.compile(r"\$\{(\w+)\}")
_RANDOM_CHARS = string.digits + string.ascii_uppercase + string.ascii_lowercase

# Path.GetInvalidFileNameChars() on Windows - broader than Linux
# actually requires (only "/" and NUL are unsafe here), kept this wide
# so a saved file stays safe to move/share to a Windows machine too,
# matching FilenameHelper.cs's own MakeFilenameSafe.
_UNSAFE_CHARS = set('\\/:*?"<>|\0')
_UNSAFE_REPLACEMENT = "_"


def make_filename_safe(text: str) -> str:
    return "".join(_UNSAFE_REPLACEMENT if ch in _UNSAFE_CHARS else ch for ch in text)


def resolve_filename_pattern(
    pattern: str, when: datetime, counter: int, title: str = "",
    rng: random.Random = None, mode: str = MODE_GREENSHOT,
) -> str:
    """``rng`` is injectable (for deterministic tests of ${RRR...});
    a real, unseeded Random is used otherwise. ``counter``/``title``/
    ``rng`` are unused in MODE_STRFTIME - that mode has no equivalent
    concepts, pure standard strftime.
    """
    if mode == MODE_STRFTIME:
        return when.strftime(pattern)

    if rng is None:
        rng = random.Random()

    values = {
        "YYYY": str(when.year),
        "MM": str(when.month),
        "DD": str(when.day),
        "hh": str(when.hour),
        "mm": str(when.minute),
        "ss": str(when.second),
        "NUM": str(counter),
        "title": make_filename_safe(title),
    }

    def replace(match: re.Match) -> str:
        token = match.group(1)
        if token and set(token) == {"R"}:
            return "".join(rng.choice(_RANDOM_CHARS) for _ in range(len(token)))
        if token not in values:
            return match.group(0)
        value = values[token]
        width = _TOKEN_WIDTHS.get(token)
        return value.zfill(width) if width else value

    return _TOKEN_RE.sub(replace, pattern)
