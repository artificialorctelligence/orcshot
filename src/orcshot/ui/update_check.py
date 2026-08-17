"""Task #103: the network half of the update checker -
core/update_check.py holds the pure version-comparison/timing logic;
this fetches GitHub's own "latest release" info. No GTK dependency,
but real I/O with no fake/injectable backend (a failed background
check is meant to fail silently, not be mockable-and-asserted-on), so
this lives in ui/ rather than core/ - same placement rationale as
ui/orcshot_file.py's own module docstring ("no X11 connection or live
window needed" - just not the zero-I/O bar core/ otherwise holds to).

Polls GitHub Releases instead of a self-hosted update-feed.json the
way real Windows' own UpdateService.cs does (getgreenshot.org/
update-feed.json - Orcshot has no equivalent website to host one on).
``releases/latest`` conveniently already excludes prereleases/drafts
on its own, so there's no separate beta-channel distinction to make
here the way UpdateService.cs's IsBetaUpdateAvailable does - matching
this port's own dropped "Check for unstable updates" Expert setting
(REQUIREMENTS.md, task #93 follow-up).
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request

GITHUB_REPO = "artificialorctelligence/orcshot"
_RELEASES_LATEST_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
# GitHub's API 403s any request with no User-Agent header at all.
_USER_AGENT = "orcshot-update-check"


def fetch_latest_release() -> tuple[str, str] | None:
    """Returns (tag_name, html_url) for the latest published release,
    or None on any failure - no release published for this repo yet
    (404, expected until this project's first tagged release),
    network down, rate-limited, malformed response, etc. Matches
    UpdateService.cs's own UpdateCheck ("if (updateFeed == null)
    return;") - a failed check is silently skipped here too, not
    surfaced as an error (app.py's manual "Check for Updates..." path
    handles telling the user about a failure itself, since silence on
    a menu click the user explicitly triggered would look broken).
    """
    request = urllib.request.Request(
        _RELEASES_LATEST_URL,
        headers={"User-Agent": _USER_AGENT, "Accept": "application/vnd.github+json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            data = json.load(response)
        return data["tag_name"], data["html_url"]
    except (urllib.error.URLError, TimeoutError, KeyError, ValueError, OSError):
        return None
