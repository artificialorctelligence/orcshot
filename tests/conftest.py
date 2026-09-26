import os
import tempfile

# orcshot.i18n reads settings.get_language() once, at its own import time, to
# decide which translation catalog to load - same as real app startup. Left
# unset, that read hits the real developer's ~/.config/orcshot/config.json,
# and if it has "language" set (e.g. from live-testing a language picker)
# while a real compiled .mo catalog also happens to sit in the dev tree
# (e.g. from running dpkg-buildpackage locally), every test that imports
# anything from orcshot.ui/app.py silently starts running in whatever
# language is set on the developer's own machine - confirmed live
# (direflail, 2026-08-26): 4 unrelated tests failed asserting on English
# text, actually receiving real Japanese translations.
#
# Setting XDG_CONFIG_HOME here, before any test module is collected, keeps
# the whole suite isolated from local machine state regardless of what's
# set on disk. pytest imports conftest.py before collecting/importing test
# modules, so this module-level assignment runs before orcshot.i18n (or
# anything that imports it) ever does.
os.environ["XDG_CONFIG_HOME"] = tempfile.mkdtemp(prefix="orcshot-test-config-")


import pytest


@pytest.fixture(autouse=True)
def _isolated_config(monkeypatch, tmp_path):
    """A fresh config directory per test, so settings a test writes cannot
    reach the next one.

    The module-level XDG_CONFIG_HOME above isolates the suite from the
    developer's real config, which it must do before collection because
    orcshot.i18n reads get_language() at import time. It does not isolate
    tests from *each other*: settings.py resolves $XDG_CONFIG_HOME on every
    call, so one directory for the whole session means every set_*() call
    persists into every later test.

    That was not theoretical. The Preferences tab tests parametrise over
    both values of each checkbox and leave whichever ran last in place, and
    the overlay contract's cursor-sampling test relies on
    get_capture_mouse_cursor()'s default. In the full suite the order
    happened to work. Under `mutmut run`, whose selection ignores
    test_app.py and therefore collects in a different order, it did not -
    test_the_cursor_is_sampled_at_construction_time[GnomeShellRegionSelect]
    failed on a clean tree and took the whole mutation run's clean-test
    pre-flight with it, so no TCE could be measured at all (2026-09-26,
    BACKLOG #220).

    Fixing it here rather than in the leaky tests is deliberate: every
    settings-writing test routes through this one env var, so this is the
    single place that makes order-independence true for all of them,
    including ones not written yet.
    """
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
