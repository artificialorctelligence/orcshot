"""_default_executable is the one piece of ui/first_run_setup.py that's
pure enough to test without GTK - the rest is dialog glue, not unit
tested for the same reason editor_window.py isn't (see that module's
own docstring).
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
