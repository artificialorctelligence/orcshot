"""gettext wrapper (i18n phase 1, BACKLOG.md's resolved #173 successor
work) - binds _()/ngettext() once at import time. localedir reuses the
existing RESOURCES_DIR convention (package-relative, not the system
/usr/share/locale/) so this resolves identically in a dev checkout and
an installed .deb, same trick already used for icons/
magnifier_constants.json.

No real .mo catalogs ship yet (this phase is infrastructure-only, see
docs/superpowers/specs/2026-08-23-i18n-phase1-gettext-infrastructure-design.md) -
fallback=True means _() always returns its argument unchanged for now,
which is why every existing test's expected UI-text output is
unaffected by the whole sweep this phase does.
"""

from __future__ import annotations

import gettext
from pathlib import Path

_LOCALE_DIR = Path(__file__).parent / "resources" / "locale"


def _load_translation(domain: str, localedir, languages=None) -> gettext.NullTranslations:
    """gettext.translation's own fallback=True only protects against
    find() returning no candidate .mo at all - once a candidate path
    exists on disk but can't actually be opened (permission denied,
    corrupt file, etc.), it propagates that OSError instead of falling
    back, even with fallback=True set. Confirmed live during i18n
    phase 1's own VM verification: a real .mo installed with
    root-only permissions crashed the whole app on every startup,
    instead of the app just silently staying in English the way any
    other catalog problem already does.
    """
    try:
        return gettext.translation(domain, localedir=localedir, languages=languages, fallback=True)
    except OSError:
        return gettext.NullTranslations()


_translation = _load_translation("orcshot", _LOCALE_DIR)
_ = _translation.gettext
ngettext = _translation.ngettext
