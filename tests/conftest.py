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
