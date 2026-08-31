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


def test_deb_channel_never_installs_bundled_extensions(monkeypatch):
    """The whole point of channel-gating this: a plain .deb install
    must behave exactly as it did before this feature existed. Calls
    the real gating helper (_install_bundled_extensions_for_snap)
    rather than asserting a monkeypatch's own return value back at
    itself - the previous version of this test only proved
    detect_channel() != "snap" when detect_channel() had literally
    been replaced with a lambda returning "deb", not that the real
    guard behaves correctly."""
    import orcshot.ui.first_run_setup as mod

    monkeypatch.setattr(mod, "detect_channel", lambda: "deb")
    calls = []
    monkeypatch.setattr(mod, "install_bundled_extension_if_needed", lambda *a, **kw: calls.append(a))

    acted = mod._install_bundled_extensions_for_snap(None)

    assert acted is False
    assert calls == []


def test_snap_channel_installs_each_bundled_extension(monkeypatch, tmp_path):
    import orcshot.ui.first_run_setup as mod

    monkeypatch.setattr(mod, "detect_channel", lambda: "snap")
    monkeypatch.setattr(mod, "_extension_bundle_dir", lambda uuid: tmp_path / "bundled" / uuid)
    monkeypatch.setattr(mod, "_snap_real_home_extensions_dir", lambda: tmp_path / "real-home")
    calls = []
    monkeypatch.setattr(
        mod, "install_bundled_extension_if_needed", lambda uuid, bundled, dest: calls.append(uuid) or True
    )
    prompted = []
    monkeypatch.setattr(mod, "show_snap_connect_prompt", lambda parent: prompted.append(parent))

    acted = mod._install_bundled_extensions_for_snap(None)

    assert acted is True
    assert calls == [mod.WINDOW_CALLS_EXTENSION_UUID, mod.CLIPBOARD_EXTENSION_UUID, mod.TRAY_EXTENSION_UUID]
    assert prompted == []


def test_snap_channel_prompts_when_an_install_fails(monkeypatch, tmp_path):
    import orcshot.ui.first_run_setup as mod

    monkeypatch.setattr(mod, "detect_channel", lambda: "snap")
    monkeypatch.setattr(mod, "_extension_bundle_dir", lambda uuid: tmp_path / "bundled" / uuid)
    monkeypatch.setattr(mod, "_snap_real_home_extensions_dir", lambda: tmp_path / "real-home")
    monkeypatch.setattr(mod, "install_bundled_extension_if_needed", lambda *a, **kw: False)
    prompted = []
    monkeypatch.setattr(mod, "show_snap_connect_prompt", lambda parent: prompted.append(parent))

    acted = mod._install_bundled_extensions_for_snap("sentinel-parent")

    assert acted is True
    assert prompted == ["sentinel-parent"]
