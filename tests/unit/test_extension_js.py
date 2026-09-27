"""Guards on the bundled GNOME Shell extension's JavaScript.

Nothing else checks it. It ships as source, GNOME Shell loads it inside
the compositor, and a syntax error there does not fail a build - it
fails at login, silently, as an extension that simply never comes up.
CI has no gjs, but the files are plain ES modules and `node --check`
parses them, which is enough to catch the class of mistake that would
otherwise be found by a user (BACKLOG #225).

The constants test is the other half: three strings are duplicated
across the language boundary by necessity (the app owns a bus name, the
extension watches it) and nothing but agreement makes the contract work.
A drift there is invisible until a real GNOME session fails to answer.
"""

import shutil
import subprocess
from pathlib import Path

import pytest

from orcshot.capture.shell_bridge import (
    HEADLESS_ACTIONS_PATH,
    HEADLESS_BUS_NAME,
    HEADLESS_SHELL_OBJECT_PATH,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
EXTENSION_DIR = (
    REPO_ROOT
    / "src" / "orcshot" / "resources" / "gnome-shell-extensions" / "orcshot@orcshot.org"
)
JS_FILES = sorted(EXTENSION_DIR.glob("*.js"))

needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")


def test_the_extension_ships_javascript_at_all():
    """A canary for the glob above: if the files move, every other test
    in this module would pass vacuously."""
    assert {path.name for path in JS_FILES} >= {"extension.js", "capture.js", "windows.js"}


@needs_node
@pytest.mark.parametrize("js_file", JS_FILES, ids=lambda p: p.name)
def test_each_extension_module_parses(js_file, tmp_path):
    """`node --check` on a copy with an .mjs suffix, so node parses it as
    the ES module GJS also treats it as.
    """
    module = tmp_path / f"{js_file.stem}.mjs"
    module.write_bytes(js_file.read_bytes())

    result = subprocess.run(["node", "--check", str(module)], capture_output=True, text=True)

    assert result.returncode == 0, f"{js_file.name} does not parse:\n{result.stderr}"


class TestTheBusNamesAgreeAcrossTheLanguageBoundary:
    """The app owns these names; the extension watches them. Neither side
    can validate the other at build time, so this does it here.
    """

    @pytest.fixture(scope="class")
    def extension_source(self):
        return (EXTENSION_DIR / "extension.js").read_text()

    def test_the_main_bus_name_matches(self, extension_source):
        assert "'org.orcshot.Orcshot'" in extension_source or '"org.orcshot.Orcshot"' in extension_source

    def test_the_headless_bus_name_matches(self, extension_source):
        assert f"'{HEADLESS_BUS_NAME}'" in extension_source

    def test_the_headless_actions_path_matches(self, extension_source):
        assert f"'{HEADLESS_ACTIONS_PATH}'" in extension_source

    def test_the_headless_shell_object_path_matches(self, extension_source):
        assert f"'{HEADLESS_SHELL_OBJECT_PATH}'" in extension_source


def _allowlist(source: str) -> str:
    """The body of the HEADLESS_HANDLERS literal, anchored on its
    declaration - the name appears in prose above it too."""
    start = source.index("const HEADLESS_HANDLERS = {")
    return source[start:source.index("};", start)]


class TestTheHeadlessBusExposesOnlyWhatItShould:
    @pytest.fixture(scope="class")
    def extension_source(self):
        return (EXTENSION_DIR / "extension.js").read_text()

    def test_the_headless_handlers_are_named_one_by_one(self, extension_source):
        """Not a spread. The main bus derives its capabilities from every
        handler that exists, which is right for it; the headless bus must
        not, or a handler added to capture.js later would become
        reachable over it just by existing.
        """
        allowlist = _allowlist(extension_source)

        assert "...Capture.handlers" not in allowlist
        assert "...Windows.handlers" not in allowlist
        assert "...HANDLERS" not in allowlist

    def test_no_interactive_handler_is_on_the_headless_bus(self, extension_source):
        """region-select, window-picker and eyedropper all end in
        pickDestinationAsync, which waits for a click - exactly what a
        headless caller has nobody to provide.
        """
        allowlist = _allowlist(extension_source)

        for interactive in ("region-select", "window-picker", "eyedropper"):
            assert interactive not in allowlist, f"{interactive} must not be reachable headlessly"

    def test_the_headless_capture_handler_is_on_it(self, extension_source):
        assert "capture-rect-headless" in _allowlist(extension_source)

    def test_the_headless_bus_announces_only_its_own_allowlist(self, extension_source):
        """Hello is how the app decides what it may ask for, so the
        headless capability list has to come from the allowlist and not
        from every handler that exists.
        """
        assert "const HEADLESS_CAPABILITIES = Object.keys(HEADLESS_HANDLERS);" in extension_source


def _handler_body(source: str, kind: str) -> str:
    """The body of one handler, anchored on its definition rather than
    on its name - the name also appears in comments, and slicing from
    the first mention picked up prose instead of code (found by this
    test failing on a change that was correct, 2026-09-26).
    """
    start = source.index(f"async '{kind}'(")
    return source[start:source.index("\n  },", start)]


class TestTheCaptureHandlers:
    @pytest.fixture(scope="class")
    def capture_source(self):
        return (EXTENSION_DIR / "capture.js").read_text()

    def test_the_headless_handler_exists(self, capture_source):
        assert "'capture-rect-headless'" in capture_source

    def test_the_headless_handler_never_asks_a_human(self, capture_source):
        """The entire point. pickDestinationAsync opens a popup menu and
        awaits a click; a scripted caller has nobody to click it.
        """
        body = _handler_body(capture_source, "capture-rect-headless")

        assert "pickDestinationAsync" not in body

    def test_the_interactive_handler_still_asks(self, capture_source):
        """capture-rect keeps its destination step - this feature adds a
        sibling, it does not change what already works.
        """
        body = _handler_body(capture_source, "capture-rect")

        assert "pickDestinationAsync" in body


class TestTheExtensionVersionStillTriggersARelogin:
    """GNOME Shell never reloads an extension's JS mid-session, so after
    an upgrade the running copy is the old one until the user logs out.
    gnome_extension_setup.needs_relogin notices by comparing the running
    copy's version-name against the bundled one - which only works while
    the bundled one is ahead of whatever the last release shipped.

    Adding a capability without that being true (BACKLOG #225 adds one)
    would leave an upgrading user with a Shell that silently cannot do
    the new thing and nothing telling them why.
    """

    @staticmethod
    def _metadata():
        import json

        return json.loads((EXTENSION_DIR / "metadata.json").read_text())

    def test_the_bundled_version_is_ahead_of_the_last_release(self):
        import subprocess

        from orcshot.gnome_extension_setup import needs_relogin

        tags = subprocess.run(
            ["git", "tag", "--list", "v*", "--sort=-v:refname"],
            capture_output=True, text=True, cwd=REPO_ROOT,
        ).stdout.split()
        if not tags:
            pytest.skip("no release tags in this checkout")
        last_release = tags[0].lstrip("v")

        assert needs_relogin(last_release, self._metadata()["version-name"]), (
            f"metadata.json version-name {self._metadata()['version-name']!r} is not ahead of the last "
            f"release {last_release!r}, so an upgrading user would never be told to log out"
        )

    def test_the_version_name_matches_the_package_version_or_leads_it(self):
        """They track each other by convention; a bundled version behind
        the package's own would mean the extension shipped stale.
        """
        import tomllib

        from orcshot.gnome_extension_setup import needs_relogin

        pyproject = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text())
        package_version = pyproject["project"]["version"]

        assert not needs_relogin(self._metadata()["version-name"], package_version), (
            "the bundled extension version is behind the package version"
        )
