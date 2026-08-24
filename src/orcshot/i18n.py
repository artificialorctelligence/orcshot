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
_translation = gettext.translation("orcshot", localedir=_LOCALE_DIR, fallback=True)
_ = _translation.gettext
ngettext = _translation.ngettext
