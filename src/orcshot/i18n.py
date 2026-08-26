"""gettext wrapper (i18n phase 1/2) - binds _()/ngettext() once at
import time. localedir reuses the existing RESOURCES_DIR convention
(package-relative, not the system /usr/share/locale/) so this
resolves identically in a dev checkout and an installed .deb, same
trick already used for icons/magnifier_constants.json.

Language selection: by default (settings.get_language() == ""),
follows the OS locale via gettext's own standard env-var negotiation
($LANGUAGE/$LC_ALL/$LC_MESSAGES/$LANG), matching GTK/GNOME desktop
convention rather than Windows Greenshot's own in-app language
dropdown. A non-empty settings.get_language() overrides that
negotiation with an explicit language code, driven by the Preferences
"Language" picker (phase 2, once real translations existed to pick
between - see editor_window.py's own _build_general_settings_tab).

That override is read once, here, at this module's own import time -
same as every other _()-bound value in this codebase (hundreds of
module-level constants across ui/, all fixed at their own import
time). Changing the Preferences setting therefore only takes effect
on the next app start, not live - a real, accepted limitation given
how pervasively _() is already used at import time throughout this
codebase; making every one of those live-reloadable would be a much
larger redesign than this setting needs.
"""

from __future__ import annotations

import gettext
from pathlib import Path

from orcshot.settings import get_language

_LOCALE_DIR = Path(__file__).parent / "resources" / "locale"


def _resolve_languages() -> list[str] | None:
    """None means "let gettext negotiate from the OS locale env vars,
    same as always" - the languages= value gettext.translation()
    itself defaults to.
    """
    language = get_language()
    return [language] if language else None


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


_translation = _load_translation("orcshot", _LOCALE_DIR, languages=_resolve_languages())
_ = _translation.gettext
ngettext = _translation.ngettext
