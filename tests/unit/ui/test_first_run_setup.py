"""_default_executable and _finish_gnome_setup are the pieces of
ui/first_run_setup.py that are pure enough to test without GTK - the
rest is dialog glue, not unit tested for the same reason
editor_window.py isn't (see that module's own docstring). The
copy-into-home helpers this file used to cover were deleted by the
2026-09-11 spec: no channel writes into the user's home any more;
ui/extension_install.py (own tests) decides the per-channel redirect.
"""

import sys

from orcshot.ui.first_run_setup import _default_executable


class TestDefaultExecutable:
    def test_prefers_the_installed_console_script_when_on_path(self):
        which = lambda name: "/usr/bin/orcshot" if name == "orcshot" else None
        assert _default_executable(which=which) == "/usr/bin/orcshot"

    def test_falls_back_to_python_dash_m_when_not_installed(self):
        which = lambda name: None
        assert _default_executable(which=which) == f"{sys.executable} -m orcshot.app"


def test_gnome_finish_enables_the_one_extension_and_shows_the_channel_dialog(monkeypatch):
    from orcshot.ui import first_run_setup
    enabled, shown = [], []
    monkeypatch.setattr(first_run_setup, "enable_extension", lambda backend, uuid: enabled.append(uuid))
    monkeypatch.setattr(first_run_setup, "detect_channel", lambda: "snap")
    monkeypatch.setattr(first_run_setup, "show_install_dialog", lambda plan, parent=None: shown.append(plan))
    first_run_setup._finish_gnome_setup(settings_backend=object(), desktop="gnome", parent=None)
    assert enabled == ["orcshot@orcshot.org"]
    assert shown == ["snap-gnome"]


def test_gnome_finish_on_deb_shows_nothing_and_activates_live(monkeypatch):
    from orcshot.ui import first_run_setup
    shown, live = [], []
    monkeypatch.setattr(first_run_setup, "enable_extension", lambda backend, uuid: None)
    monkeypatch.setattr(first_run_setup, "enable_extension_live", lambda uuid: live.append(uuid))
    monkeypatch.setattr(first_run_setup, "detect_channel", lambda: "deb")
    monkeypatch.setattr(first_run_setup, "show_install_dialog", lambda plan, parent=None: shown.append(plan))
    first_run_setup._finish_gnome_setup(settings_backend=object(), desktop="gnome", parent=None)
    assert shown == []
    assert live == ["orcshot@orcshot.org"]


def test_gnome_finish_on_flatpak_never_calls_enable_live(monkeypatch):
    from orcshot.ui import first_run_setup
    live = []
    monkeypatch.setattr(first_run_setup, "enable_extension", lambda backend, uuid: None)
    monkeypatch.setattr(first_run_setup, "enable_extension_live", lambda uuid: live.append(uuid))
    monkeypatch.setattr(first_run_setup, "detect_channel", lambda: "flatpak")
    monkeypatch.setattr(first_run_setup, "show_install_dialog", lambda plan, parent=None: None)
    first_run_setup._finish_gnome_setup(settings_backend=object(), desktop="gnome", parent=None)
    assert live == []
