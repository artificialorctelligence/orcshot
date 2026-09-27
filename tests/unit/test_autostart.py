"""remove_legacy_autostart_entry (task #180): cleans up the stale,
pre-task-#141 XDG autostart .desktop entry a previous version of
this app wrote directly (see autostart.py's own module docstring for
why that mechanism was replaced by a systemd --user service). Left
behind on any install that had autostart enabled before that
migration, it races orcshot.service at every boot - see BACKLOG.md's
resolved #180 entry for the full live-reproduced symptom.

TestEnableAutostartMissingSystemctl below covers the final-review
Critical fix (2026-08-31): a channel with no systemd at all (real,
live-reproduced on the Flatpak channel's org.gnome.Platform//50 -
see BACKLOG's #185 resolution) must not raise a bare FileNotFoundError
past enable_autostart/disable_autostart, since neither call site
catches anything but subprocess.CalledProcessError.
"""

import subprocess
from pathlib import Path

import pytest

from orcshot.autostart import (
    disable_autostart, enable_autostart, is_autostart_enabled, remove_legacy_autostart_entry,
)


class _FakeCompletedProcess:
    """Only the two attributes is_autostart_enabled actually reads off a
    real subprocess.CompletedProcess."""

    def __init__(self, returncode: int, stdout: str):
        self.returncode = returncode
        self.stdout = stdout


class _RecordingRun:
    """Stands in for subprocess.run: records every argv/kwargs it was
    handed and returns a canned result. Task 9 (BACKLOG #220): the whole
    argv - the `systemctl` binary name, `--user`, the verb, the unit name -
    and `text=True` were unasserted, so a mutant could rename any of them
    and no test noticed. A wrong verb here silently breaks
    launch-at-login, with nothing shown to the user.
    """

    def __init__(self, result: _FakeCompletedProcess | None = None):
        self.calls: list[tuple] = []
        self._result = result

    def __call__(self, cmd, **kwargs):
        self.calls.append((cmd, kwargs))
        return self._result


class TestRemoveLegacyAutostartEntry:
    def test_removes_an_existing_stale_entry(self, tmp_path: Path):
        autostart_dir = tmp_path / "autostart"
        autostart_dir.mkdir()
        stale_entry = autostart_dir / "orcshot.desktop"
        stale_entry.write_text("[Desktop Entry]\nExec=/usr/bin/orcshot\n")

        remove_legacy_autostart_entry(config_home=tmp_path)

        assert not stale_entry.exists()

    def test_is_a_no_op_when_no_stale_entry_exists(self, tmp_path: Path):
        # Must not raise just because the directory (or file) was
        # never created - the common case on any install that never
        # had the old .desktop-writing mechanism at all.
        remove_legacy_autostart_entry(config_home=tmp_path)

    def test_leaves_other_files_in_the_autostart_directory_alone(self, tmp_path: Path):
        autostart_dir = tmp_path / "autostart"
        autostart_dir.mkdir()
        unrelated_entry = autostart_dir / "some-other-app.desktop"
        unrelated_entry.write_text("[Desktop Entry]\nExec=/usr/bin/some-other-app\n")

        remove_legacy_autostart_entry(config_home=tmp_path)

        assert unrelated_entry.exists()

    def test_defaults_to_xdg_config_home_when_no_directory_is_passed(self, monkeypatch, tmp_path):
        # The real call site (app.py startup) passes nothing, so the
        # $XDG_CONFIG_HOME lookup itself is the production path. HOME is
        # redirected too so that a mis-resolved directory can never reach
        # the developer's own ~/.config.
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
        monkeypatch.setenv("HOME", str(tmp_path / "home"))
        autostart_dir = tmp_path / "xdg" / "autostart"
        autostart_dir.mkdir(parents=True)
        stale_entry = autostart_dir / "orcshot.desktop"
        stale_entry.write_text("[Desktop Entry]\nExec=/usr/bin/orcshot\n")

        remove_legacy_autostart_entry()

        assert not stale_entry.exists()

    def test_falls_back_to_home_dot_config_when_xdg_config_home_is_unset(self, monkeypatch, tmp_path):
        # The other half of line 121: with XDG_CONFIG_HOME absent (a real
        # minimal session), the default must be exactly ~/.config - the
        # spelling the XDG basedir spec mandates and every other app uses.
        monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
        monkeypatch.setenv("HOME", str(tmp_path / "home"))
        autostart_dir = tmp_path / "home" / ".config" / "autostart"
        autostart_dir.mkdir(parents=True)
        stale_entry = autostart_dir / "orcshot.desktop"
        stale_entry.write_text("[Desktop Entry]\nExec=/usr/bin/orcshot\n")

        remove_legacy_autostart_entry()

        assert not stale_entry.exists()


class TestIsAutostartEnabled:
    """The exact `systemctl --user is-enabled orcshot.service` invocation
    and the exact condition its output is judged by. Both were entirely
    unasserted before task 9."""

    def test_asks_systemctl_user_is_enabled_for_the_orcshot_unit(self, monkeypatch):
        run = _RecordingRun(_FakeCompletedProcess(0, "enabled\n"))
        monkeypatch.setattr("orcshot.autostart.subprocess.run", run)

        is_autostart_enabled()

        cmd, kwargs = run.calls[0]
        assert cmd == ["systemctl", "--user", "is-enabled", "orcshot.service"]
        # text=True is what makes result.stdout a str; without it stdout is
        # bytes and the == "enabled" comparison below is always False, so
        # autostart would report "off" even when it is genuinely on.
        assert kwargs == {"capture_output": True, "text": True}

    @pytest.mark.parametrize(
        "returncode, stdout, expected",
        [
            (0, "enabled\n", True),
            # A disabled unit: systemctl exits non-zero AND prints "disabled".
            (1, "disabled\n", False),
            # Exit 0 but not "enabled" - a real systemctl answer for a unit
            # that is `static` or `enabled-runtime`, neither of which means
            # "will start at the next login".
            (0, "static\n", False),
            # "enabled" on a non-zero exit - the inverse half of the same
            # condition; both halves must hold, not either one.
            (1, "enabled\n", False),
        ],
    )
    def test_both_halves_of_the_condition_must_hold(self, monkeypatch, returncode, stdout, expected):
        run = _RecordingRun(_FakeCompletedProcess(returncode, stdout))
        monkeypatch.setattr("orcshot.autostart.subprocess.run", run)

        assert is_autostart_enabled() is expected

    @pytest.mark.parametrize("error", [FileNotFoundError(2, "No such file or directory", "systemctl"), OSError(5, "Input/output error")])
    def test_reports_not_enabled_rather_than_raising_when_systemctl_cannot_run(self, monkeypatch, error):
        # Called unconditionally whenever Preferences opens, so it must
        # never raise - and must answer False, not True: reporting "on"
        # for a unit that cannot even be queried would show the user a
        # ticked checkbox for autostart that does not exist.
        def fake_run(cmd, **kwargs):
            raise error

        monkeypatch.setattr("orcshot.autostart.subprocess.run", fake_run)

        assert is_autostart_enabled() is False


class TestEnableDisableInvocation:
    def test_enable_runs_systemctl_user_enable_now_for_the_orcshot_unit(self, monkeypatch):
        run = _RecordingRun()
        monkeypatch.setattr("orcshot.autostart.subprocess.run", run)

        enable_autostart()

        cmd, kwargs = run.calls[0]
        assert cmd == ["systemctl", "--user", "enable", "--now", "orcshot.service"]
        # --now is what makes the checkbox take effect without a re-login;
        # check=True is what turns a real systemctl failure into the
        # CalledProcessError both call sites catch and report.
        assert kwargs["check"] is True

    def test_disable_runs_systemctl_user_disable_and_does_not_stop_the_running_instance(self, monkeypatch):
        run = _RecordingRun()
        monkeypatch.setattr("orcshot.autostart.subprocess.run", run)

        disable_autostart()

        cmd, kwargs = run.calls[0]
        # Deliberately no --now: see disable_autostart's own docstring -
        # killing the process the user is toggling the checkbox in would be
        # a regression from the old .desktop mechanism.
        assert cmd == ["systemctl", "--user", "disable", "orcshot.service"]
        assert kwargs["check"] is True


class TestMissingSystemctlErrorShape:
    """What _run_systemctl_user's translated CalledProcessError actually
    carries. Both call sites print it, so returncode and cmd are the whole
    of what the user is shown."""

    @pytest.mark.parametrize(
        "error",
        [
            # A strict snap: systemctl exists but is not executable from
            # inside confinement, and PermissionError carries no filename.
            PermissionError(13, "Permission denied"),
            # Flatpak's org.gnome.Platform//50 ships no systemd binaries;
            # the OS error has no filename when raised this way either.
            FileNotFoundError(2, "No such file or directory"),
        ],
    )
    def test_falls_back_to_the_systemctl_name_when_the_os_error_has_no_filename(self, monkeypatch, error):
        def fake_run(cmd, **kwargs):
            raise error

        monkeypatch.setattr("orcshot.autostart.subprocess.run", fake_run)

        with pytest.raises(subprocess.CalledProcessError) as excinfo:
            enable_autostart()

        # 127 is the shell's own "command not found" code - the thing that
        # actually went wrong, not an invented number.
        assert excinfo.value.returncode == 127
        assert excinfo.value.cmd == "systemctl"

    def test_reports_the_real_filename_when_the_os_error_carries_one(self, monkeypatch):
        def fake_run(cmd, **kwargs):
            raise FileNotFoundError(2, "No such file or directory", "/usr/bin/systemctl")

        monkeypatch.setattr("orcshot.autostart.subprocess.run", fake_run)

        with pytest.raises(subprocess.CalledProcessError) as excinfo:
            disable_autostart()

        assert excinfo.value.cmd == "/usr/bin/systemctl"
        assert excinfo.value.returncode == 127


class TestEnableAutostartMissingSystemctl:
    def test_enable_autostart_raises_calledprocesserror_not_filenotfounderror(self, monkeypatch):
        def fake_run(cmd, **kwargs):
            raise FileNotFoundError(2, "No such file or directory", "systemctl")

        monkeypatch.setattr("orcshot.autostart.subprocess.run", fake_run)

        with pytest.raises(subprocess.CalledProcessError):
            enable_autostart()

    def test_disable_autostart_raises_calledprocesserror_not_filenotfounderror(self, monkeypatch):
        def fake_run(cmd, **kwargs):
            raise FileNotFoundError(2, "No such file or directory", "systemctl")

        monkeypatch.setattr("orcshot.autostart.subprocess.run", fake_run)

        with pytest.raises(subprocess.CalledProcessError):
            disable_autostart()
