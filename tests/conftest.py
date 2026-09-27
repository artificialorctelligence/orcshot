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


# --------------------------------------------------------------------
# GLib sources a test leaves behind
#
# A test that creates a GLib source and does not remove it leaves it
# alive in the process's default main context. In a normal `pytest` run
# that is untidy and nothing more. Under `mutmut run` it is not: mutmut
# executes the whole suite many times inside ONE process, so a leaked
# source - especially a repeating timeout, whose callback returns truthy
# and reschedules itself forever - bleeds into later mutants' runs and
# can abort the process with SIGABRT.
#
# The damage from that is not a loud crash. The mutants lost when the
# run dies leave the scored set silently, which makes TCE go *up*: a
# smaller denominator with the same kills. One such leak was measured
# flattering a file from 96.7% to 99.3% (2026-09-26, BACKLOG #220). A
# measurement that fails by overstating itself is the worst kind, so
# this is a guard rather than a tidiness rule.
#
# Six tests on this branch leaked one source each when this was first
# measured. They are cleaned up here rather than individually rewritten:
# every source goes through these three functions, so this is the one
# place that makes the whole suite safe, including tests not yet
# written. Cleaning up is deliberate, not merely convenient - the leak
# is harmful only because the process is shared, and removing the source
# removes the harm.
# --------------------------------------------------------------------

import gi as _gi

_gi.require_version("Gtk", "3.0")
from gi.repository import GLib as _GLib  # noqa: E402

_GLIB_SOURCE_ADDERS = ("timeout_add", "timeout_add_seconds", "idle_add")
_created_sources: list[int] = []


def _record_source_ids() -> None:
    for _name in _GLIB_SOURCE_ADDERS:
        _real = getattr(_GLib, _name)
        if getattr(_real, "_orcshot_recording", False):
            continue

        def _wrapper(*args, _real=_real, **kwargs):
            source_id = _real(*args, **kwargs)
            _created_sources.append(source_id)
            return source_id

        _wrapper._orcshot_recording = True
        setattr(_GLib, _name, _wrapper)


_record_source_ids()


@pytest.fixture(autouse=True)
def _no_leaked_glib_sources():
    """Remove any GLib source this test created and did not remove."""
    first = len(_created_sources)
    yield
    context = _GLib.MainContext.default()
    for source_id in _created_sources[first:]:
        if context.find_source_by_id(source_id) is not None:
            _GLib.source_remove(source_id)
    del _created_sources[first:]


# --------------------------------------------------------------------
# The ShellBridge singleton
#
# capture/shell_bridge.py keeps one process-global bridge behind
# get_bridge(), which is right for the app - there is one Shell
# connection - and wrong for a suite, because anything a test registers
# on it outlives that test. The listener list is the sharp edge:
# app.py's _check_shell_extension_health and _register_tray_actions both
# subscribe to capability changes, so a test that triggers either leaves
# a listener behind, and a later test asserting on _listeners sees it.
#
# Found the same day the "Capture Window" gating was wired (BACKLOG
# #224): two existing health-check tests began failing in the full suite
# while passing in isolation, which is the signature of exactly this.
# Resetting here rather than making those two assertions looser keeps
# them meaning what they were written to mean.
#
# Constructing a fresh bridge is cheap and touches no bus: ShellBridge()
# only builds a Gio.SimpleAction, and register() - which takes the
# connection - is a separate call the app makes and tests do not.
# --------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _fresh_shell_bridge():
    from orcshot.capture import shell_bridge

    shell_bridge.set_bridge(None)
    yield
    shell_bridge.set_bridge(None)
