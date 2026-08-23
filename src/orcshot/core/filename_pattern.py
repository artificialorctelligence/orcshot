"""Filename pattern resolution - task #95's Output tab "preferred file
settings", redesigned under task #171 into one unified pattern
language instead of two mutually exclusive ones.

The original design (see git history for the pre-task-#171 version of
this module) picked one delimiter convention at a time - Greenshot's
own ``${TOKEN}`` substitution (FilenameHelper.cs's FillPattern) or
real strftime's ``%`` directives - specifically to avoid a bare "%"
prefix next to ordinary text being ambiguous with itself (confirmed
live: ``strftime("a%screenshot.png")`` silently ate the "s", and even
a curated "safe" whitelist didn't fix it - %d ate the "d" out of an
otherwise ordinary word "done"). That mode setting (``filename_pattern
_mode``, since removed) was a genuine, separately-persisted field from
the pattern *text* itself - and nothing ever migrated an existing
config when the coded default for one changed without the other
(task #127/#128 flipped the default mode to strftime while the
default pattern *text* for anyone who'd never touched it stayed
Greenshot-style until that same commit): a real, live-caught bug
(task #171) where an old config carried mismatched mode+text forever,
saving files literally named "${YYYY}-${MM}-${DD}...".

Unifying removes the field that could drift out of sync with the
pattern text, not just the symptom: ``${TOKEN}`` substitution and
strftime's own ``%`` directives are BOTH always active in the same
pattern now, resolved in that order - ``${...}`` first, then the
result handed to ``datetime.strftime()``. This works safely (without
reopening the exact ambiguity the original two-mode split existed to
prevent) because every *substituted* token value is percent-escaped
before strftime ever sees it - the only new "%" that could reach
strftime from this module's own substitution is inside a value the
user doesn't directly type (a captured window's title, in
particular), and that's exactly what gets escaped. The user's own raw
"%" directives in the pattern text are untouched and behave exactly
as documented, standard strftime always has (including needing "%%"
for a literal percent) - that was already true, and already an
accepted, opt-in tradeoff, before this module ever existed.

Two substitution forms inside ``${...}``:
- ``${TOKEN}`` - a bare token (date/time components, ``${NUM}`` - the
  save counter, ``${RRR...}`` - random alphanumerics, length = number
  of R's, and ``${title}``). An unrecognized token name is left
  completely as literal text, matching FilenameHelper.cs's own
  fallback for a parameter it doesn't understand.
- ``${"affix"?TOKEN}`` - renders nothing at all if TOKEN has no value
  (unset/empty), or the literal ``affix`` text immediately followed by
  TOKEN's value if it does. direflail's own addition, replacing the
  previous strftime-mode-only special case that auto-appended
  " - {title}" whenever a title existed (unconditionally, with no way
  to opt out or reposition it) - real Greenshot's own ${title} has no
  such special-casing at all (FilenameHelper.cs's own `case "title":
  replaceValue = title;`, unconditional), and its real default pattern
  bakes title in as a plain trailing token
  (``${capturetime:d"..."}-${title}``), accepting a dangling "-"
  before the extension on a title-less capture as a result. This
  conditional form gets the best of both: ``${title}`` is a fully
  ordinary, explicit, positionable token like any other (faithful to
  the real app, no resolver-level magic), while the *default* pattern
  below uses ``${" - "?title}`` to avoid that dangling-separator wart
  structurally, via pattern text alone - not a hardcoded special case.
"""

from __future__ import annotations

import random
import re
import string
from datetime import datetime

_TOKEN_WIDTHS = {"YYYY": 4, "MM": 2, "DD": 2, "hh": 2, "mm": 2, "ss": 2, "NUM": 6}
_TOKEN_RE = re.compile(r'\$\{(?:"(?P<affix>[^"]*)"\?(?P<condtoken>\w+)|(?P<token>\w+))\}')
_RANDOM_CHARS = string.digits + string.ascii_uppercase + string.ascii_lowercase

# strftime-syntax by default (task #127/#128 live-verification feedback -
# direflail's own call: standard Linux/Python convention over Windows' own
# ${TOKEN} scheme for a fresh install) plus the title conditional (task
# #171) - matches quick_save_filename's own pre-existing default date/time
# layout, with title included exactly when there is one, no dangling
# separator when there isn't. Windows' real default additionally wraps the
# date/time in its own ${capturetime:d"..."} token rather than plain "%"
# directives; functionally identical output, this module's own syntax.
DEFAULT_FILENAME_PATTERN = '%Y-%m-%d %H_%M_%S${" - "?title}'

# Path.GetInvalidFileNameChars() on Windows - broader than Linux
# actually requires (only "/" and NUL are unsafe here), kept this wide
# so a saved file stays safe to move/share to a Windows machine too,
# matching FilenameHelper.cs's own MakeFilenameSafe.
_UNSAFE_CHARS = set('\\/:*?"<>|\0')
_UNSAFE_REPLACEMENT = "_"


def make_filename_safe(text: str) -> str:
    return "".join(_UNSAFE_REPLACEMENT if ch in _UNSAFE_CHARS else ch for ch in text)


def resolve_filename_pattern(
    pattern: str, when: datetime, counter: int, title: str = "", rng: random.Random = None,
) -> str:
    """``rng`` is injectable (for deterministic tests of ${RRR...}); a
    real, unseeded Random is used otherwise.

    ``${...}`` tokens are substituted first, then the result is passed
    through ``when.strftime()`` for any "%" directives - see this
    module's own docstring for why that order is safe (every
    substituted value is percent-escaped first, so nothing from a
    token's *value* can be misread as a strftime directive; the user's
    own raw "%" text is untouched and reaches strftime exactly as
    written).
    """
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

    def resolve_token(name: str) -> tuple[bool, str] | tuple[bool, None]:
        if name and set(name) == {"R"}:
            return True, "".join(rng.choice(_RANDOM_CHARS) for _ in range(len(name)))
        if name not in values:
            return False, None
        value = values[name]
        width = _TOKEN_WIDTHS.get(name)
        return True, (value.zfill(width) if width else value)

    def replace(match: re.Match) -> str:
        if match.group("condtoken") is not None:
            found, value = resolve_token(match.group("condtoken"))
            if not found:
                return match.group(0)
            if not value:
                return ""
            return (match.group("affix") + value).replace("%", "%%")
        found, value = resolve_token(match.group("token"))
        return value.replace("%", "%%") if found else match.group(0)

    substituted = _TOKEN_RE.sub(replace, pattern)
    return when.strftime(substituted)
