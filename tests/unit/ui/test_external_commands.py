"""build_command_argv/run_external_command/_validate - the pure/
mockable logic behind task #110's ExternalCommand-style destinations.
The two Gtk.Dialog builders (_show_command_detail_dialog,
show_manage_external_commands_dialog) are GTK glue with no meaningful
headless test, same as destination_picker.py/printing.py - verified
live instead (see REQUIREMENTS.md).
"""

import subprocess
import threading

import numpy as np
import pytest

from greenshot_linux.settings import ExternalCommand, set_external_commands
from greenshot_linux.ui.external_commands import _validate, build_command_argv, run_external_command


def solid_image(width=4, height=3, color=(10, 20, 30, 255)):
    image = np.zeros((height, width, 4), dtype=np.uint8)
    image[:, :] = color
    return image


class TestBuildCommandArgv:
    def test_substitutes_the_path_into_the_single_placeholder(self):
        command = ExternalCommand(name="x", commandline="/usr/bin/foo", argument="{0}")
        assert build_command_argv(command, "/tmp/shot.png") == ["/usr/bin/foo", "/tmp/shot.png"]

    def test_substitutes_the_path_into_one_token_among_several(self):
        command = ExternalCommand(name="x", commandline="/usr/bin/foo", argument="-i {0} -q")
        assert build_command_argv(command, "/tmp/shot.png") == ["/usr/bin/foo", "-i", "/tmp/shot.png", "-q"]

    def test_no_placeholder_still_appends_all_literal_tokens(self):
        command = ExternalCommand(name="x", commandline="/usr/bin/foo", argument="--verbose --quiet")
        assert build_command_argv(command, "/tmp/shot.png") == ["/usr/bin/foo", "--verbose", "--quiet"]

    def test_empty_argument_template_yields_just_the_commandline(self):
        command = ExternalCommand(name="x", commandline="/usr/bin/foo", argument="")
        assert build_command_argv(command, "/tmp/shot.png") == ["/usr/bin/foo"]

    def test_a_path_with_spaces_stays_one_argv_item(self):
        # this is the whole point of the design (see the function's own
        # docstring): a path is never re-parsed by a shell tokenizer,
        # so embedded spaces can never split it into multiple args or
        # be used to smuggle in extra flags.
        command = ExternalCommand(name="x", commandline="/usr/bin/foo", argument="{0}")
        argv = build_command_argv(command, "/tmp/my screenshot.png")
        assert argv == ["/usr/bin/foo", "/tmp/my screenshot.png"]

    def test_shell_metacharacters_in_the_path_are_inert(self):
        # no shell ever parses this string - it's a single argv item
        # regardless of what it contains, so there's nothing to inject.
        command = ExternalCommand(name="x", commandline="/usr/bin/foo", argument="{0}")
        dangerous_path = "/tmp/$(rm -rf ~); echo pwned.png"
        argv = build_command_argv(command, dangerous_path)
        assert argv == ["/usr/bin/foo", dangerous_path]


class TestRunExternalCommand:
    def test_foreground_runs_synchronously_with_the_built_argv(self, monkeypatch, tmp_path):
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
        calls = []

        def fake_run(argv, **kwargs):
            calls.append(argv)
            return subprocess.CompletedProcess(argv, returncode=0, stdout="", stderr="")

        monkeypatch.setattr(subprocess, "run", fake_run)
        command = ExternalCommand(name="notify", commandline="/usr/bin/notify-send", run_in_background=False)

        run_external_command(command, solid_image())

        assert len(calls) == 1
        assert calls[0][0] == "/usr/bin/notify-send"
        assert calls[0][1].endswith(".png")

    def test_background_runs_on_a_separate_thread(self, monkeypatch, tmp_path):
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
        calling_thread = threading.current_thread()
        seen_threads = []

        def fake_run(argv, **kwargs):
            seen_threads.append(threading.current_thread())
            return subprocess.CompletedProcess(argv, returncode=0, stdout="", stderr="")

        monkeypatch.setattr(subprocess, "run", fake_run)
        command = ExternalCommand(name="bg", commandline="/usr/bin/true", run_in_background=True)

        run_external_command(command, solid_image())
        for thread in threading.enumerate():
            if thread.name == "external-command-bg":
                thread.join(timeout=5)

        assert len(seen_threads) == 1
        assert seen_threads[0] is not calling_thread

    def test_a_nonzero_exit_code_does_not_raise(self, monkeypatch, tmp_path):
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
        monkeypatch.setattr(
            subprocess, "run",
            lambda argv, **kwargs: subprocess.CompletedProcess(argv, returncode=1, stdout="", stderr="boom"),
        )
        command = ExternalCommand(name="x", commandline="/usr/bin/false", run_in_background=False)

        run_external_command(command, solid_image())  # must not raise

    def test_a_missing_executable_does_not_raise(self, monkeypatch, tmp_path):
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))

        def fake_run(argv, **kwargs):
            raise OSError("No such file or directory")

        monkeypatch.setattr(subprocess, "run", fake_run)
        command = ExternalCommand(name="x", commandline="/usr/bin/does-not-exist", run_in_background=False)

        run_external_command(command, solid_image())  # must not raise


class TestValidate:
    @pytest.fixture(autouse=True)
    def _empty_commands(self, tmp_path, monkeypatch):
        config_path = tmp_path / "config.json"
        monkeypatch.setattr("greenshot_linux.settings.config_file_path", lambda: config_path)
        set_external_commands([])

    def test_empty_name_is_invalid(self):
        assert _validate("", "/bin/true", "{0}", None) is not None

    def test_empty_commandline_is_invalid(self):
        assert _validate("My Command", "", "{0}", None) is not None

    def test_a_commandline_that_does_not_exist_is_invalid(self):
        assert _validate("My Command", "/definitely/not/a/real/path", "{0}", None) is not None

    def test_a_real_absolute_commandline_is_valid(self):
        assert _validate("My Command", "/bin/true", "{0}", None) is None

    def test_a_commandline_resolvable_on_path_is_valid(self):
        assert _validate("My Command", "true", "{0}", None) is None

    def test_unbalanced_quotes_in_arguments_are_invalid(self):
        assert _validate("My Command", "/bin/true", '"unterminated', None) is not None

    def test_duplicate_name_is_invalid(self):
        set_external_commands([ExternalCommand(name="Existing", commandline="/bin/true")])

        assert _validate("Existing", "/bin/true", "{0}", None) is not None

    def test_editing_the_same_command_is_not_a_duplicate_against_itself(self):
        set_external_commands([ExternalCommand(name="Existing", commandline="/bin/true")])

        assert _validate("Existing", "/bin/true", "{0}", "Existing") is None
