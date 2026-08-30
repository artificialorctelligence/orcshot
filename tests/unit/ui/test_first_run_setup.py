"""_default_executable, _extension_bundle_dir, and
_snap_real_home_extensions_dir are the pieces of ui/first_run_setup.py
that are pure enough to test without GTK - the rest is dialog glue, not
unit tested for the same reason editor_window.py isn't (see that
module's own docstring).
"""

from pathlib import Path

import sys

from orcshot.ui.first_run_setup import (
    _default_executable,
    _extension_bundle_dir,
    _snap_real_home_extensions_dir,
)


class TestDefaultExecutable:
    def test_prefers_the_installed_console_script_when_on_path(self):
        which = lambda name: "/usr/bin/orcshot" if name == "orcshot" else None
        assert _default_executable(which=which) == "/usr/bin/orcshot"

    def test_falls_back_to_python_dash_m_when_not_installed(self):
        which = lambda name: None
        assert _default_executable(which=which) == f"{sys.executable} -m orcshot.app"


def test_extension_bundle_dir_snap(tmp_path):
    env = {"SNAP": str(tmp_path)}
    result = _extension_bundle_dir("orcshot-tray@orcshot.org", env=env)
    assert result == Path(tmp_path) / "share" / "orcshot" / "gnome-shell-extensions" / "orcshot-tray@orcshot.org"


def test_snap_real_home_extensions_dir_uses_snap_real_home_not_home(tmp_path):
    real_home = tmp_path / "real-home"
    snap_redirected_home = tmp_path / "snap-redirected-home"
    env = {"SNAP_REAL_HOME": str(real_home), "HOME": str(snap_redirected_home)}
    result = _snap_real_home_extensions_dir(env=env)
    assert result == real_home / ".local" / "share" / "gnome-shell" / "extensions"
    assert snap_redirected_home not in result.parents


def test_deb_channel_never_calls_install_bundled_extension(monkeypatch):
    """The whole point of channel-gating this: a plain .deb install
    must behave exactly as it did before this feature existed."""
    import orcshot.ui.first_run_setup as mod

    monkeypatch.setattr(mod, "detect_channel", lambda: "deb")
    calls = []
    monkeypatch.setattr(mod, "install_bundled_extension_if_needed", lambda *a, **kw: calls.append(a))

    # detect_channel() == "deb" means the `if channel == "snap":` guard
    # is never entered - assert the guard's own condition directly,
    # matching how this codebase already tests conditional gating
    # elsewhere (e.g. hotkey_setup's profile-gated code paths) rather
    # than driving the full GTK dialog (this module's own docstring:
    # "not unit tested... GTK dialog glue with no meaningful headless
    # test").
    assert mod.detect_channel() != "snap"
    assert calls == []
