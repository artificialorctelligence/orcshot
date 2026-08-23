"""build_command_argv/run_external_command/_validate - the pure/
mockable logic behind task #110's ExternalCommand-style destinations.
show_command_detail_dialog (the Gtk.Dialog builder) is GTK glue with
no meaningful headless test, same as destination_picker.py/
printing.py - verified live instead (see REQUIREMENTS.md).
"""

import os
import shutil
import subprocess
import threading
from pathlib import Path

import numpy as np
import pytest

from orcshot.settings import (
    ExternalCommand,
    get_external_commands,
    is_default_external_commands_seeded,
    set_external_commands,
)
from orcshot.ui.external_commands import (
    InstalledApp,
    _find_best_installed_app,
    _installed_flatpak_apps,
    _installed_native_apps,
    _installed_snap_apps,
    _is_snap_command,
    _parse_desktop_entry,
    _validate,
    build_command_argv,
    default_external_commands,
    list_installed_apps,
    maybe_seed_default_external_commands,
    run_external_command,
    search_installed_apps,
)


def solid_image(width=4, height=3, color=(10, 20, 30, 255)):
    image = np.zeros((height, width, 4), dtype=np.uint8)
    image[:, :] = color
    return image


class TestIsSnapCommand:
    def test_a_snap_bin_wrapper_is_detected(self):
        assert _is_snap_command("/snap/bin/krita") is True

    def test_a_native_binary_is_not_detected(self):
        assert _is_snap_command("/usr/bin/krita") is False

    def test_a_bare_command_name_resolved_via_path_is_detected(self, monkeypatch):
        # a command configured as just "krita" (resolved via $PATH at
        # validation time, see _validate) rather than a full path -
        # shutil.which's own resolution is what the /snap/ check sees.
        monkeypatch.setattr(shutil, "which", lambda name: "/snap/bin/krita" if name == "krita" else None)
        assert _is_snap_command("krita") is True

    def test_survives_the_symlink_snap_bin_entries_actually_are(self, monkeypatch):
        # Real bug, caught live (direflail, task #166): /snap/bin/<name>
        # entries are themselves symlinks to /usr/bin/snap (snapd's
        # generic launcher, which inspects the symlink's own name to
        # pick which snap to run) - os.path.realpath follows that
        # symlink straight past the one signal this needs, resolving
        # to a target that's never under /snap/. Simulates exactly
        # that by making realpath lie about where /snap/bin/krita
        # "really" points, to prove detection doesn't depend on it.
        monkeypatch.setattr(os.path, "realpath", lambda p: "/usr/bin/snap" if p == "/snap/bin/krita" else p)
        assert _is_snap_command("/snap/bin/krita") is True


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

    def test_a_snap_command_gets_the_visible_temp_dir_not_cache(self, monkeypatch, tmp_path):
        # task #166 - a Snap-confined target can't read anything under
        # the hidden ~/.cache, so its handoff file needs to land in
        # orcshot_visible_temp_dir's plain ~/Orcshot instead.
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / ".cache"))
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        calls = []
        monkeypatch.setattr(
            subprocess, "run",
            lambda argv, **kwargs: calls.append(argv) or subprocess.CompletedProcess(argv, returncode=0),
        )
        command = ExternalCommand(name="krita", commandline="/snap/bin/krita", run_in_background=False)

        run_external_command(command, solid_image())

        assert calls[0][1].startswith(str(tmp_path / "Orcshot"))

    def test_a_non_snap_command_still_uses_the_cache_dir(self, monkeypatch, tmp_path):
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / ".cache"))
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        calls = []
        monkeypatch.setattr(
            subprocess, "run",
            lambda argv, **kwargs: calls.append(argv) or subprocess.CompletedProcess(argv, returncode=0),
        )
        command = ExternalCommand(name="gimp", commandline="/usr/bin/gimp", run_in_background=False)

        run_external_command(command, solid_image())

        assert calls[0][1].startswith(str(tmp_path / ".cache" / "orcshot"))

    def test_the_temp_file_is_deleted_after_the_command_completes(self, monkeypatch, tmp_path):
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
        captured_path = []
        monkeypatch.setattr(
            subprocess, "run",
            lambda argv, **kwargs: captured_path.append(argv[1]) or subprocess.CompletedProcess(argv, returncode=0),
        )
        command = ExternalCommand(name="x", commandline="/usr/bin/true", run_in_background=False)

        run_external_command(command, solid_image())

        assert not os.path.exists(captured_path[0])

    def test_the_temp_file_is_deleted_even_if_the_command_fails(self, monkeypatch, tmp_path):
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
        captured_path = []

        def fake_run(argv, **kwargs):
            captured_path.append(argv[1])
            raise OSError("No such file or directory")

        monkeypatch.setattr(subprocess, "run", fake_run)
        command = ExternalCommand(name="x", commandline="/usr/bin/does-not-exist", run_in_background=False)

        run_external_command(command, solid_image())

        assert not os.path.exists(captured_path[0])


class TestValidate:
    @pytest.fixture(autouse=True)
    def _empty_commands(self, tmp_path, monkeypatch):
        config_path = tmp_path / "config.json"
        monkeypatch.setattr("orcshot.settings.config_file_path", lambda: config_path)
        set_external_commands([])

    def test_empty_name_is_invalid(self):
        assert _validate("", "/bin/true", "{0}", None) is not None

    def test_empty_commandline_is_invalid(self):
        assert _validate("My Command", "", "{0}", None) is not None

    def test_a_commandline_that_does_not_exist_is_invalid(self):
        assert _validate("My Command", "/definitely/not/a/real/path", "{0}", None) is not None

    def test_a_commandline_with_a_space_gets_a_specific_hint(self):
        # Live-observed (direflail, task #166 follow-up): a real, easy
        # mistake pasting "flatpak run org.kde.krita" whole into
        # Command, rather than splitting "flatpak" here and "run
        # org.kde.krita {0}" into Arguments - a bare command never
        # contains a space, so this is a reliable, specific signal
        # worth a better message than the generic "not found".
        error = _validate("My Command", "flatpak run org.kde.krita", "{0}", None)
        assert error is not None
        assert "arguments" in error.lower()

    def test_the_generic_not_found_message_still_applies_without_a_space(self):
        error = _validate("My Command", "/definitely/not/a/real/path", "{0}", None)
        assert "arguments" not in error.lower()

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


class TestInstalledSnapApps:
    def test_filters_to_type_app_only(self, monkeypatch):
        # task #166 follow-up ("Find App") - live-confirmed against
        # this dev machine's real /v2/snaps: "base"/"snapd" entries
        # (core22, snapd itself) are infrastructure, never something
        # a user would pick as an external command destination.
        monkeypatch.setattr(
            "orcshot.ui.external_commands._query_snapd",
            lambda path: {
                "result": [
                    {"name": "core22", "type": "base", "title": "Core 22 base snap", "version": "20260410"},
                    {"name": "krita", "type": "app", "title": "Krita", "version": "5.3.3", "apps": [{"name": "krita"}]},
                ]
            },
        )
        assert _installed_snap_apps() == [("krita", "Krita", "5.3.3")]

    def test_falls_back_to_name_when_no_title(self, monkeypatch):
        monkeypatch.setattr(
            "orcshot.ui.external_commands._query_snapd",
            lambda path: {
                "result": [
                    {"name": "hello", "type": "app", "title": "", "version": "2.10", "apps": [{"name": "hello"}]}
                ]
            },
        )
        assert _installed_snap_apps() == [("hello", "hello", "2.10")]

    def test_excludes_content_snaps_with_no_launchable_app(self, monkeypatch):
        # Real, live-confirmed case (direflail, 2026-08-22): "GTK
        # Common Themes" (gtk-common-themes) is a type "app" snap
        # installed by default on Ubuntu/Mint, but it's a *content*
        # snap - it only shares theme assets with other snaps and has
        # no /snap/bin/<name> launcher of its own, so selecting it
        # produced "Command not found" with OK greyed out. snapd's own
        # "apps" field lists the snap's actual runnable commands - a
        # type "app" snap with an empty one has nothing to launch.
        monkeypatch.setattr(
            "orcshot.ui.external_commands._query_snapd",
            lambda path: {
                "result": [
                    {
                        "name": "gtk-common-themes", "type": "app", "title": "GTK Common Themes",
                        "version": "0.1", "apps": [],
                    },
                    {"name": "krita", "type": "app", "title": "Krita", "version": "5.3.3", "apps": [{"name": "krita"}]},
                ]
            },
        )
        assert _installed_snap_apps() == [("krita", "Krita", "5.3.3")]

    def test_returns_empty_list_when_snapd_is_unreachable(self, monkeypatch):
        # no snapd installed/running at all - graceful degradation,
        # not an error the user sees.
        def raise_oserror(path):
            raise OSError("No such file or directory")

        monkeypatch.setattr("orcshot.ui.external_commands._query_snapd", raise_oserror)
        assert _installed_snap_apps() == []


class TestInstalledFlatpakApps:
    def test_parses_tab_separated_name_application_id_and_version(self, monkeypatch):
        monkeypatch.setattr(
            subprocess, "run",
            lambda argv, **kwargs: subprocess.CompletedProcess(
                argv, returncode=0,
                stdout="Krita\torg.kde.krita\t5.2.9\nGIMP\torg.gimp.GIMP\t2.10.38\n", stderr="",
            ),
        )
        assert _installed_flatpak_apps() == [
            ("Krita", "org.kde.krita", "5.2.9"), ("GIMP", "org.gimp.GIMP", "2.10.38"),
        ]

    def test_returns_empty_list_when_flatpak_is_not_installed(self, monkeypatch):
        def raise_filenotfound(argv, **kwargs):
            raise FileNotFoundError("No such file or directory: 'flatpak'")

        monkeypatch.setattr(subprocess, "run", raise_filenotfound)
        assert _installed_flatpak_apps() == []

    def test_returns_empty_list_on_nonzero_exit(self, monkeypatch):
        monkeypatch.setattr(
            subprocess, "run",
            lambda argv, **kwargs: subprocess.CompletedProcess(argv, returncode=1, stdout="", stderr="error"),
        )
        assert _installed_flatpak_apps() == []


class TestParseDesktopEntry:
    def test_returns_name_command_and_argument_for_a_valid_entry(self, tmp_path, monkeypatch):
        monkeypatch.setattr(shutil, "which", lambda cmd: f"/usr/bin/{cmd}" if cmd == "gimp" else None)
        desktop_file = tmp_path / "org.gimp.GIMP.desktop"
        desktop_file.write_text("[Desktop Entry]\nType=Application\nName=GIMP\nExec=gimp %U\n")
        assert _parse_desktop_entry(desktop_file) == ("GIMP", "gimp", "{0}")

    def test_strips_extra_exec_arguments_into_the_argument_field(self, tmp_path, monkeypatch):
        monkeypatch.setattr(shutil, "which", lambda cmd: f"/usr/bin/{cmd}" if cmd == "gimp" else None)
        desktop_file = tmp_path / "gimp.desktop"
        desktop_file.write_text("[Desktop Entry]\nType=Application\nName=GIMP\nExec=gimp -n %U\n")
        assert _parse_desktop_entry(desktop_file) == ("GIMP", "gimp", "-n {0}")

    def test_returns_none_for_nodisplay_entries(self, tmp_path):
        desktop_file = tmp_path / "hidden.desktop"
        desktop_file.write_text("[Desktop Entry]\nType=Application\nName=Hidden\nExec=hidden\nNoDisplay=true\n")
        assert _parse_desktop_entry(desktop_file) is None

    def test_returns_none_for_non_application_types(self, tmp_path):
        desktop_file = tmp_path / "link.desktop"
        desktop_file.write_text("[Desktop Entry]\nType=Link\nName=A Link\nURL=https://example.com\n")
        assert _parse_desktop_entry(desktop_file) is None

    def test_returns_none_when_the_command_is_not_on_path(self, tmp_path, monkeypatch):
        monkeypatch.setattr(shutil, "which", lambda cmd: None)
        desktop_file = tmp_path / "ghost.desktop"
        desktop_file.write_text("[Desktop Entry]\nType=Application\nName=Ghost\nExec=ghost-app-xyz\n")
        assert _parse_desktop_entry(desktop_file) is None

    def test_returns_none_for_malformed_files(self, tmp_path):
        desktop_file = tmp_path / "broken.desktop"
        desktop_file.write_text("not a desktop file at all")
        assert _parse_desktop_entry(desktop_file) is None


class TestInstalledNativeApps:
    def test_reads_desktop_files_from_the_configured_directories(self, tmp_path, monkeypatch):
        user_dir, system_dir = tmp_path / "user", tmp_path / "system"
        user_dir.mkdir()
        system_dir.mkdir()
        (system_dir / "gimp.desktop").write_text("[Desktop Entry]\nType=Application\nName=GIMP\nExec=gimp %U\n")
        monkeypatch.setattr("orcshot.ui.external_commands._DESKTOP_APP_DIRS", (user_dir, system_dir))
        monkeypatch.setattr(shutil, "which", lambda cmd: f"/usr/bin/{cmd}" if cmd == "gimp" else None)
        assert _installed_native_apps() == [("GIMP", "gimp", "{0}")]

    def test_user_directory_entries_win_on_a_filename_collision(self, tmp_path, monkeypatch):
        user_dir, system_dir = tmp_path / "user", tmp_path / "system"
        user_dir.mkdir()
        system_dir.mkdir()
        (user_dir / "gimp.desktop").write_text(
            "[Desktop Entry]\nType=Application\nName=GIMP (user override)\nExec=gimp %U\n"
        )
        (system_dir / "gimp.desktop").write_text("[Desktop Entry]\nType=Application\nName=GIMP\nExec=gimp %U\n")
        monkeypatch.setattr("orcshot.ui.external_commands._DESKTOP_APP_DIRS", (user_dir, system_dir))
        monkeypatch.setattr(shutil, "which", lambda cmd: f"/usr/bin/{cmd}" if cmd == "gimp" else None)
        assert _installed_native_apps() == [("GIMP (user override)", "gimp", "{0}")]

    def test_missing_directories_are_skipped(self, tmp_path, monkeypatch):
        monkeypatch.setattr("orcshot.ui.external_commands._DESKTOP_APP_DIRS", (tmp_path / "does-not-exist",))
        assert _installed_native_apps() == []


class TestListInstalledApps:
    def test_combines_snap_flatpak_and_native_apps_sorted_alphabetically_by_name(self, monkeypatch):
        # direflail's own feedback, 2026-08-22: grouped by source (snap,
        # then flatpak, then native) made the list harder to scan than
        # one plain alphabetical list - the source still shows in each
        # row's own label ("Krita (flatpak)"), just not as a grouping.
        monkeypatch.setattr(
            "orcshot.ui.external_commands._installed_snap_apps", lambda: [("krita", "Krita", "5.3.3")],
        )
        monkeypatch.setattr(
            "orcshot.ui.external_commands._installed_flatpak_apps",
            lambda: [("GIMP", "org.gimp.GIMP", "2.10.38")],
        )
        monkeypatch.setattr(
            "orcshot.ui.external_commands._installed_native_apps",
            lambda: [("Inkscape", "inkscape", "{0}")],
        )
        assert list_installed_apps() == [
            InstalledApp(name="GIMP", source="flatpak", commandline="flatpak", argument="run org.gimp.GIMP {0}"),
            InstalledApp(name="Inkscape", source="native", commandline="inkscape", argument="{0}"),
            InstalledApp(name="Krita", source="snap", commandline="/snap/bin/krita", argument="{0}"),
        ]

    def test_sort_is_case_insensitive(self, monkeypatch):
        monkeypatch.setattr("orcshot.ui.external_commands._installed_snap_apps", lambda: [])
        monkeypatch.setattr("orcshot.ui.external_commands._installed_flatpak_apps", lambda: [])
        monkeypatch.setattr(
            "orcshot.ui.external_commands._installed_native_apps",
            lambda: [("zed", "zed", "{0}"), ("Abricotine", "abricotine", "{0}")],
        )
        assert [app.name for app in list_installed_apps()] == ["Abricotine", "zed"]


class TestSearchInstalledApps:
    _APPS = [
        InstalledApp(name="Krita", source="snap", commandline="/snap/bin/krita", argument="{0}"),
        InstalledApp(name="GIMP", source="flatpak", commandline="flatpak", argument="run org.gimp.GIMP {0}"),
    ]

    def test_empty_query_returns_every_app(self):
        # direflail's own revised spec: an empty search box shows the
        # whole browsable list rather than nothing, so it's obvious
        # what Find App is for - reversed from the original "nothing
        # shown when no letters" after live-testing showed a blank
        # list wasn't obvious.
        assert search_installed_apps("", self._APPS) == self._APPS

    def test_matches_a_snap_app_by_partial_name(self):
        assert search_installed_apps("kr", self._APPS) == [self._APPS[0]]

    def test_matches_a_flatpak_app_by_partial_name(self):
        assert search_installed_apps("gim", self._APPS) == [self._APPS[1]]

    def test_search_is_case_insensitive(self):
        assert search_installed_apps("KRITA", self._APPS) == [self._APPS[0]]

    def test_matches_against_the_flatpak_app_id_too(self):
        # the flatpak app-id ("org.gimp.GIMP") isn't in the display
        # name, but should still be searchable - direflail's own
        # original ask ("i would have... typed 'kr' and it would
        # reduce the list").
        assert search_installed_apps("org.gimp", self._APPS) == [self._APPS[1]]

    def test_no_match_returns_empty(self):
        assert search_installed_apps("nonexistent-app-xyz", self._APPS) == []


class TestFindBestInstalledApp:
    @pytest.fixture(autouse=True)
    def _stub_which(self, monkeypatch):
        # nothing native by default - each test opts in explicitly.
        monkeypatch.setattr(shutil, "which", lambda cmd: None)

    def test_native_wins_outright_even_if_snap_and_flatpak_are_also_present(self, monkeypatch):
        monkeypatch.setattr(shutil, "which", lambda cmd: f"/usr/bin/{cmd}" if cmd == "krita" else None)
        monkeypatch.setattr(
            "orcshot.ui.external_commands._installed_snap_apps", lambda: [("krita", "Krita", "9.9.9")],
        )
        monkeypatch.setattr(
            "orcshot.ui.external_commands._installed_flatpak_apps",
            lambda: [("Krita", "org.kde.krita", "9.9.9")],
        )
        assert _find_best_installed_app(("krita",), "krita", "org.kde.krita") == ("krita", "{0}", "krita")

    def test_returns_none_when_nothing_is_found(self, monkeypatch):
        monkeypatch.setattr("orcshot.ui.external_commands._installed_snap_apps", lambda: [])
        monkeypatch.setattr("orcshot.ui.external_commands._installed_flatpak_apps", lambda: [])
        assert _find_best_installed_app(("krita",), "krita", "org.kde.krita") is None

    def test_snap_only_wins_when_flatpak_is_absent(self, monkeypatch):
        monkeypatch.setattr(
            "orcshot.ui.external_commands._installed_snap_apps", lambda: [("krita", "Krita", "5.3.3")],
        )
        monkeypatch.setattr("orcshot.ui.external_commands._installed_flatpak_apps", lambda: [])
        assert _find_best_installed_app(("krita",), "krita", "org.kde.krita") == (
            "/snap/bin/krita", "{0}", None,
        )

    def test_flatpak_only_wins_when_snap_is_absent(self, monkeypatch):
        monkeypatch.setattr("orcshot.ui.external_commands._installed_snap_apps", lambda: [])
        monkeypatch.setattr(
            "orcshot.ui.external_commands._installed_flatpak_apps",
            lambda: [("Krita", "org.kde.krita", "5.2.9")],
        )
        assert _find_best_installed_app(("krita",), "krita", "org.kde.krita") == (
            "flatpak", "run org.kde.krita {0}", None,
        )

    def test_the_newer_of_snap_and_flatpak_wins_when_both_are_present_flatpak_newer(self, monkeypatch):
        monkeypatch.setattr(
            "orcshot.ui.external_commands._installed_snap_apps", lambda: [("krita", "Krita", "5.2.0")],
        )
        monkeypatch.setattr(
            "orcshot.ui.external_commands._installed_flatpak_apps",
            lambda: [("Krita", "org.kde.krita", "5.3.0")],
        )
        assert _find_best_installed_app(("krita",), "krita", "org.kde.krita") == (
            "flatpak", "run org.kde.krita {0}", None,
        )

    def test_the_newer_of_snap_and_flatpak_wins_when_both_are_present_snap_newer(self, monkeypatch):
        monkeypatch.setattr(
            "orcshot.ui.external_commands._installed_snap_apps", lambda: [("krita", "Krita", "5.3.3")],
        )
        monkeypatch.setattr(
            "orcshot.ui.external_commands._installed_flatpak_apps",
            lambda: [("Krita", "org.kde.krita", "5.2.9")],
        )
        assert _find_best_installed_app(("krita",), "krita", "org.kde.krita") == (
            "/snap/bin/krita", "{0}", None,
        )

    def test_an_empty_snap_or_flatpak_identifier_is_skipped_rather_than_matched(self, monkeypatch):
        # OpenOffice has no Snap or Flatpak package at all (confirmed
        # via a real OpenOffice forum thread during task #166) - the
        # caller passes "" for both, which must never accidentally
        # match a real app that happens to have an empty name/id.
        monkeypatch.setattr(
            "orcshot.ui.external_commands._installed_snap_apps", lambda: [("", "", "1.0.0")],
        )
        monkeypatch.setattr(
            "orcshot.ui.external_commands._installed_flatpak_apps", lambda: [("", "", "1.0.0")],
        )
        assert _find_best_installed_app(("openoffice-binary-xyz",), "", "") is None

    def test_reports_which_native_candidate_matched(self, monkeypatch):
        # LibreOffice's "soffice" vs OpenOffice's "ooffice" need to be
        # distinguishable so the caller can pick the right display
        # name - see default_external_commands below.
        monkeypatch.setattr(shutil, "which", lambda cmd: f"/usr/bin/{cmd}" if cmd == "ooffice" else None)
        result = _find_best_installed_app(("soffice", "ooffice", "openoffice.org"), "libreoffice", "")
        assert result == ("ooffice", "{0}", "ooffice")

    def test_extra_args_are_inserted_before_the_placeholder_for_native(self, monkeypatch):
        monkeypatch.setattr(shutil, "which", lambda cmd: f"/usr/bin/{cmd}" if cmd == "soffice" else None)
        result = _find_best_installed_app(("soffice",), "libreoffice", "", extra_args="--draw")
        assert result == ("soffice", "--draw {0}", "soffice")

    def test_extra_args_are_inserted_before_the_placeholder_for_flatpak(self, monkeypatch):
        monkeypatch.setattr("orcshot.ui.external_commands._installed_snap_apps", lambda: [])
        monkeypatch.setattr(
            "orcshot.ui.external_commands._installed_flatpak_apps",
            lambda: [("LibreOffice", "org.libreoffice.LibreOffice", "24.8.4")],
        )
        result = _find_best_installed_app(
            ("soffice",), "", "org.libreoffice.LibreOffice", extra_args="--draw",
        )
        assert result == ("flatpak", "run org.libreoffice.LibreOffice --draw {0}", None)


class TestDefaultExternalCommands:
    @pytest.fixture(autouse=True)
    def _stub_nothing_found(self, monkeypatch):
        monkeypatch.setattr(shutil, "which", lambda cmd: None)
        monkeypatch.setattr("orcshot.ui.external_commands._installed_snap_apps", lambda: [])
        monkeypatch.setattr("orcshot.ui.external_commands._installed_flatpak_apps", lambda: [])

    def test_nothing_found_yields_an_empty_list(self):
        assert default_external_commands() == []

    def test_libreoffice_found_natively(self, monkeypatch):
        monkeypatch.setattr(shutil, "which", lambda cmd: f"/usr/bin/{cmd}" if cmd == "soffice" else None)
        commands = default_external_commands()
        assert commands == [
            ExternalCommand(name="LibreOffice", commandline="soffice", argument="--draw {0}"),
        ]

    def test_openoffice_found_natively_gets_its_own_display_name(self, monkeypatch):
        monkeypatch.setattr(shutil, "which", lambda cmd: f"/usr/bin/{cmd}" if cmd == "ooffice" else None)
        commands = default_external_commands()
        assert commands == [
            ExternalCommand(name="OpenOffice", commandline="ooffice", argument="--draw {0}"),
        ]

    def test_krita_found_via_snap_only(self, monkeypatch):
        monkeypatch.setattr(
            "orcshot.ui.external_commands._installed_snap_apps", lambda: [("krita", "Krita", "5.3.3")],
        )
        commands = default_external_commands()
        assert commands == [
            ExternalCommand(name="Krita", commandline="/snap/bin/krita", argument="{0}"),
        ]

    def test_gimp_found_via_flatpak_only(self, monkeypatch):
        monkeypatch.setattr(
            "orcshot.ui.external_commands._installed_flatpak_apps",
            lambda: [("GIMP", "org.gimp.GIMP", "2.10.38")],
        )
        commands = default_external_commands()
        assert commands == [
            ExternalCommand(name="GIMP", commandline="flatpak", argument="run org.gimp.GIMP {0}"),
        ]

    def test_all_four_found_natively(self, monkeypatch):
        native = {"soffice", "krita", "gimp"}
        monkeypatch.setattr(shutil, "which", lambda cmd: f"/usr/bin/{cmd}" if cmd in native else None)
        commands = default_external_commands()
        assert [c.name for c in commands] == ["LibreOffice", "Krita", "GIMP"]


class TestMaybeSeedDefaultExternalCommands:
    def test_seeds_newly_detected_commands_on_first_call(self, tmp_path, monkeypatch):
        path = tmp_path / "config.json"
        monkeypatch.setattr(
            "orcshot.ui.external_commands.default_external_commands",
            lambda: [ExternalCommand(name="Krita", commandline="krita")],
        )

        maybe_seed_default_external_commands(path=path)

        assert get_external_commands(path=path) == [ExternalCommand(name="Krita", commandline="krita")]
        assert is_default_external_commands_seeded(path=path) is True

    def test_does_not_run_again_on_a_second_call(self, tmp_path, monkeypatch):
        path = tmp_path / "config.json"
        detected = [ExternalCommand(name="Krita", commandline="krita")]
        monkeypatch.setattr("orcshot.ui.external_commands.default_external_commands", lambda: detected)
        maybe_seed_default_external_commands(path=path)

        # A second real Krita install, or the user deleting the seeded
        # entry, must never bring it back - this only ever runs once,
        # ever (direflail's own explicit call).
        set_external_commands([], path=path)
        maybe_seed_default_external_commands(path=path)

        assert get_external_commands(path=path) == []

    def test_does_not_duplicate_an_existing_same_named_command(self, tmp_path, monkeypatch):
        path = tmp_path / "config.json"
        existing = ExternalCommand(name="LibreOffice", commandline="my-custom-soffice-wrapper")
        set_external_commands([existing], path=path)
        monkeypatch.setattr(
            "orcshot.ui.external_commands.default_external_commands",
            lambda: [ExternalCommand(name="LibreOffice", commandline="soffice")],
        )

        maybe_seed_default_external_commands(path=path)

        assert get_external_commands(path=path) == [existing]

    def test_marks_seeded_even_when_nothing_was_detected(self, tmp_path, monkeypatch):
        path = tmp_path / "config.json"
        monkeypatch.setattr("orcshot.ui.external_commands.default_external_commands", lambda: [])

        maybe_seed_default_external_commands(path=path)

        assert is_default_external_commands_seeded(path=path) is True
        assert get_external_commands(path=path) == []

    def test_preserves_the_users_own_existing_commands(self, tmp_path, monkeypatch):
        path = tmp_path / "config.json"
        own_command = ExternalCommand(name="My Script", commandline="my-script")
        set_external_commands([own_command], path=path)
        monkeypatch.setattr(
            "orcshot.ui.external_commands.default_external_commands",
            lambda: [ExternalCommand(name="Krita", commandline="krita")],
        )

        maybe_seed_default_external_commands(path=path)

        assert get_external_commands(path=path) == [
            own_command, ExternalCommand(name="Krita", commandline="krita"),
        ]
