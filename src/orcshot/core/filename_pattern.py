"""Faithful-in-spirit port of FilenameHelper.cs's ${TOKEN} filename
pattern substitution (FillPattern, FilenameHelper.cs:344-441) - task
#95's Output tab "preferred file settings". A subset of Windows' real
token set: date/time components, ${NUM} (the save counter,
settings.consume_filename_counter), and ${title} - not
${domain}/${user}/${hostname}/environment-folder tokens (low value
here, storage location is already its own separate setting) or
${now}/${capturetime} (redundant with the individual date tokens for
this port's simpler no-culture-mode design).
"""

from __future__ import annotations

import re
from datetime import datetime

# Matches quick_save_filename's own pre-existing default format
# (settings.py) - Windows' real default additionally appends
# "-${title}" (ICoreConfiguration.cs:127), dropped here for the same
# reason quick_save_filename already documented: not every capture
# mode has a single associated window title (region/full-screen
# capture don't).
DEFAULT_FILENAME_PATTERN = "${YYYY}-${MM}-${DD} ${hh}_${mm}_${ss}"

_TOKEN_WIDTHS = {"YYYY": 4, "MM": 2, "DD": 2, "hh": 2, "mm": 2, "ss": 2, "NUM": 6}
_TOKEN_RE = re.compile(r"\$\{(\w+)\}")

# Path.GetInvalidFileNameChars() on Windows - broader than Linux
# actually requires (only "/" and NUL are unsafe here), kept this wide
# so a saved file stays safe to move/share to a Windows machine too,
# matching FilenameHelper.cs's own MakeFilenameSafe.
_UNSAFE_CHARS = set('\\/:*?"<>|\0')
_UNSAFE_REPLACEMENT = "_"


def make_filename_safe(text: str) -> str:
    return "".join(_UNSAFE_REPLACEMENT if ch in _UNSAFE_CHARS else ch for ch in text)


def resolve_filename_pattern(pattern: str, when: datetime, counter: int, title: str = "") -> str:
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
        if token not in values:
            return match.group(0)
        value = values[token]
        width = _TOKEN_WIDTHS.get(token)
        return value.zfill(width) if width else value

    return _TOKEN_RE.sub(replace, pattern)
