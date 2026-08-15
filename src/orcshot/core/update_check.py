"""Task #103: pure version-comparison and check-timing decisions - no
network, no GTK (see app.py's own update-check wiring for that half).

Faithful port of Windows' own interval-gating (UpdateService.cs's
BackgroundTask: ``checkIsDisabled = TimeSpan.Zero == interval;
nextCheckIsInTheFuture = LastUpdateCheck.Add(interval) >
DateTime.Now``) and its version-string cleanup (ProcessFeed's
``Regex.Replace(tag, "[a-zA-Z\\-]*", "")`` before ``Version.TryParse``)
- adapted to poll GitHub Releases instead of Greenshot's own
self-hosted update-feed.json (no self-hosted website to attach one to;
see REQUIREMENTS.md's task #103 section for the full citation and
what was deliberately simplified, e.g. no separate "don't reshow
within 24h" guard - already covered by the interval gate below).
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta

_NON_NUMERIC = re.compile(r"[a-zA-Z\-]+")


def parse_version(tag: str) -> tuple[int, ...]:
    cleaned = _NON_NUMERIC.sub("", tag)
    return tuple(int(part) for part in cleaned.split("."))


def is_newer_version(candidate: str, current: str) -> bool:
    return parse_version(candidate) > parse_version(current)


def should_check_now(last_check: datetime | None, interval_days: int, now: datetime) -> bool:
    if interval_days <= 0:
        return False
    if last_check is None:
        return True
    return now >= last_check + timedelta(days=interval_days)
