"""Persistent app settings - currently just the screenshot save
directory (configurable from the editor, see ui/editor_window.py) and
a one-time "first-run setup already ran" flag (see
ui/first_run_setup.py). A plain JSON file, same testing approach as
autostart.py's .desktop entry: real file I/O, exercised for real here
against a temp path, never the actual default XDG path.
"""

from datetime import datetime
from pathlib import Path

from orcshot.settings import (
    CONFIG_FILENAME,
    EXTERNAL_EDITOR_AUTO,
    ExternalCommand,
    OutputSettings,
    PrintOptions,
    config_file_path,
    consume_filename_counter,
    default_output_directory,
    get_capture_mouse_cursor,
    get_excluded_destinations,
    get_external_commands,
    get_external_editor_preference,
    get_show_magnifier_while_selecting,
    get_filename_counter,
    get_footer_pattern,
    get_icon_size,
    get_last_update_check,
    get_output_directory,
    get_output_settings,
    get_play_capture_sound,
    get_print_options,
    get_recent_colors,
    get_show_capture_notification,
    get_suppress_save_dialog_at_close,
    get_update_check_interval_days,
    get_use_default_proxy,
    clear_quit_marker,
    is_default_external_commands_seeded,
    is_first_run_setup_done,
    is_quit_marker_set,
    mark_default_external_commands_seeded,
    mark_first_run_setup_done,
    quick_save_filename,
    quit_marker_path,
    set_capture_mouse_cursor,
    set_excluded_destinations,
    set_external_commands,
    set_external_editor_preference,
    set_show_magnifier_while_selecting,
    set_filename_counter,
    set_footer_pattern,
    set_icon_size,
    set_last_update_check,
    set_output_directory,
    set_output_settings,
    set_play_capture_sound,
    set_print_options,
    set_recent_colors,
    set_show_capture_notification,
    set_suppress_save_dialog_at_close,
    set_update_check_interval_days,
    set_use_default_proxy,
    write_quit_marker,
)


class TestConfigFilePath:
    def test_uses_xdg_config_home_when_given(self, tmp_path):
        path = config_file_path(config_home=tmp_path)
        assert path == tmp_path / "orcshot" / CONFIG_FILENAME

    def test_defaults_to_the_real_xdg_config_home_when_not_given(self):
        path = config_file_path()
        assert path.name == CONFIG_FILENAME
        assert path.parent.name == "orcshot"


class TestQuitMarker:
    def test_uses_xdg_config_home_when_given(self, tmp_path):
        path = quit_marker_path(config_home=tmp_path)
        assert path == tmp_path / "orcshot" / "quit.marker"

    def test_not_set_by_default(self, tmp_path):
        path = quit_marker_path(config_home=tmp_path)
        assert not is_quit_marker_set(path)

    def test_write_then_is_set(self, tmp_path):
        path = quit_marker_path(config_home=tmp_path)
        write_quit_marker(path)
        assert is_quit_marker_set(path)

    def test_write_creates_the_config_directory(self, tmp_path):
        path = quit_marker_path(config_home=tmp_path)
        assert not path.parent.exists()
        write_quit_marker(path)
        assert path.exists()

    def test_clear_after_write(self, tmp_path):
        path = quit_marker_path(config_home=tmp_path)
        write_quit_marker(path)
        clear_quit_marker(path)
        assert not is_quit_marker_set(path)

    def test_clear_when_never_written_is_a_no_op(self, tmp_path):
        path = quit_marker_path(config_home=tmp_path)
        clear_quit_marker(path)
        assert not is_quit_marker_set(path)


class TestDefaultOutputDirectory:
    def test_returns_a_path_under_home(self):
        result = default_output_directory()
        assert Path.home() in result.parents


class TestOutputDirectory:
    def test_get_returns_the_default_when_nothing_saved_yet(self, tmp_path):
        path = tmp_path / "config.json"
        assert get_output_directory(path=path) == default_output_directory()

    def test_set_then_get_round_trips(self, tmp_path):
        path = tmp_path / "config.json"
        target = tmp_path / "MyScreenshots"

        set_output_directory(target, path=path)

        assert get_output_directory(path=path) == target

    def test_set_creates_the_config_directory_if_missing(self, tmp_path):
        path = tmp_path / "does" / "not" / "exist" / "config.json"

        set_output_directory(tmp_path / "shots", path=path)

        assert path.exists()

    def test_set_preserves_other_settings_already_present(self, tmp_path):
        path = tmp_path / "config.json"
        mark_first_run_setup_done(path=path)

        set_output_directory(tmp_path / "shots", path=path)

        assert is_first_run_setup_done(path=path) is True


class TestQuickSaveFilename:
    def test_matches_windows_timestamp_pattern(self):
        # Windows' own default OutputFileFilenamePattern is
        # yyyy-MM-dd HH_mm_ss (plus a ${title} suffix we deliberately
        # drop - not every capture mode here has a single associated
        # window title, e.g. region/full-screen capture don't).
        when = datetime(2026, 7, 26, 14, 23, 5)
        assert quick_save_filename(when, counter=1) == "2026-07-26 14_23_05 (001).png"

    def test_different_times_produce_different_filenames(self):
        a = quick_save_filename(datetime(2026, 7, 26, 14, 23, 5), counter=1)
        b = quick_save_filename(datetime(2026, 7, 26, 14, 23, 6), counter=1)
        assert a != b

    def test_different_counters_produce_different_filenames(self):
        when = datetime(2026, 7, 26, 14, 23, 5)
        assert quick_save_filename(when, counter=1) != quick_save_filename(when, counter=2)

    def test_counter_is_zero_padded_to_three_digits(self):
        when = datetime(2026, 7, 26, 14, 23, 5)
        assert quick_save_filename(when, counter=7) == "2026-07-26 14_23_05 (007).png"


class TestCaptureMouseCursor:
    def test_defaults_to_true(self, tmp_path):
        # matches Windows' CaptureMousepointer default (ICoreConfiguration.cs:79-81)
        path = tmp_path / "config.json"
        assert get_capture_mouse_cursor(path=path) is True

    def test_set_false_then_get_round_trips(self, tmp_path):
        path = tmp_path / "config.json"

        set_capture_mouse_cursor(False, path=path)

        assert get_capture_mouse_cursor(path=path) is False

    def test_set_true_then_get_round_trips(self, tmp_path):
        path = tmp_path / "config.json"
        set_capture_mouse_cursor(False, path=path)

        set_capture_mouse_cursor(True, path=path)

        assert get_capture_mouse_cursor(path=path) is True


class TestPlayCaptureSound:
    def test_defaults_to_false(self, tmp_path):
        # deliberate divergence from Windows' own PlayCameraSound default (True) -
        # direflail's explicit call, see get_play_capture_sound's own docstring
        path = tmp_path / "config.json"
        assert get_play_capture_sound(path=path) is False

    def test_set_false_then_get_round_trips(self, tmp_path):
        path = tmp_path / "config.json"

        set_play_capture_sound(False, path=path)

        assert get_play_capture_sound(path=path) is False

    def test_set_true_then_get_round_trips(self, tmp_path):
        path = tmp_path / "config.json"
        set_play_capture_sound(False, path=path)

        set_play_capture_sound(True, path=path)

        assert get_play_capture_sound(path=path) is True


class TestShowCaptureNotification:
    def test_defaults_to_false(self, tmp_path):
        # deliberate divergence from Windows' own ShowTrayNotification default (True) -
        # direflail's explicit call, see get_show_capture_notification's own docstring
        path = tmp_path / "config.json"
        assert get_show_capture_notification(path=path) is False

    def test_set_false_then_get_round_trips(self, tmp_path):
        path = tmp_path / "config.json"

        set_show_capture_notification(False, path=path)

        assert get_show_capture_notification(path=path) is False

    def test_set_true_then_get_round_trips(self, tmp_path):
        path = tmp_path / "config.json"
        set_show_capture_notification(False, path=path)

        set_show_capture_notification(True, path=path)

        assert get_show_capture_notification(path=path) is True


class TestExternalEditorPreference:
    def test_defaults_to_auto(self, tmp_path):
        path = tmp_path / "config.json"
        assert get_external_editor_preference(path=path) == EXTERNAL_EDITOR_AUTO

    def test_set_then_get_round_trips(self, tmp_path):
        path = tmp_path / "config.json"

        set_external_editor_preference("Krita", path=path)

        assert get_external_editor_preference(path=path) == "Krita"

    def test_set_preserves_other_settings_already_present(self, tmp_path):
        path = tmp_path / "config.json"
        set_capture_mouse_cursor(False, path=path)

        set_external_editor_preference("GIMP", path=path)

        assert get_capture_mouse_cursor(path=path) is False
        assert get_external_editor_preference(path=path) == "GIMP"


class TestRecentColors:
    def test_defaults_to_empty(self, tmp_path):
        path = tmp_path / "config.json"
        assert get_recent_colors(path=path) == []

    def test_set_then_get_round_trips_as_tuples(self, tmp_path):
        path = tmp_path / "config.json"
        colors = [(255, 0, 0, 255), (0, 255, 0, 255)]

        set_recent_colors(colors, path=path)

        assert get_recent_colors(path=path) == colors
        assert all(isinstance(c, tuple) for c in get_recent_colors(path=path))

    def test_set_preserves_other_settings_already_present(self, tmp_path):
        path = tmp_path / "config.json"
        set_capture_mouse_cursor(False, path=path)

        set_recent_colors([(1, 2, 3, 255)], path=path)

        assert get_capture_mouse_cursor(path=path) is False


class TestPrintOptions:
    def test_defaults_match_windows(self, tmp_path):
        path = tmp_path / "config.json"
        options = get_print_options(path=path)
        assert options == PrintOptions(
            prompt_options=True, allow_shrink=True, allow_enlarge=False, allow_rotate=False,
            center=True, footer=True, grayscale=False, monochrome=False,
            monochrome_threshold=127, inverted=False,
        )

    def test_set_then_get_round_trips(self, tmp_path):
        path = tmp_path / "config.json"
        options = PrintOptions(
            prompt_options=False, allow_shrink=False, allow_enlarge=True, allow_rotate=True,
            center=False, footer=False, grayscale=True, monochrome=True,
            monochrome_threshold=200, inverted=True,
        )

        set_print_options(options, path=path)

        assert get_print_options(path=path) == options

    def test_set_preserves_other_settings_already_present(self, tmp_path):
        path = tmp_path / "config.json"
        set_capture_mouse_cursor(False, path=path)

        set_print_options(PrintOptions(allow_enlarge=True), path=path)

        assert get_capture_mouse_cursor(path=path) is False

    def test_loading_an_older_config_missing_newer_fields_still_works(self, tmp_path):
        # simulates a config saved by an earlier version of this
        # dataclass that didn't have every current field yet.
        import json

        path = tmp_path / "config.json"
        path.write_text(json.dumps({"print_options": {"allow_shrink": False}}))

        options = get_print_options(path=path)

        assert options.allow_shrink is False
        assert options.center is True  # falls back to the default


class TestOutputSettings:
    def test_defaults_match_windows(self, tmp_path):
        # ICoreConfiguration.cs:126-160, except filename_pattern/
        # filename_pattern_mode - this port's own deliberate departure
        # from Windows' ${TOKEN} default, per direflail's own call
        # (task #127/#128 feedback): standard strftime by default.
        path = tmp_path / "config.json"
        settings = get_output_settings(path=path)
        assert settings == OutputSettings(
            filename_pattern="%Y-%m-%d %H_%M_%S", filename_pattern_mode="strftime",
            primary_format="png", copy_path_to_clipboard=True, reduce_colors=False,
            always_show_quality_dialog=False, jpeg_quality=80,
        )

    def test_set_then_get_round_trips(self, tmp_path):
        path = tmp_path / "config.json"
        settings = OutputSettings(
            filename_pattern="${title}", filename_pattern_mode="strftime", primary_format="jpg",
            copy_path_to_clipboard=False, reduce_colors=True, always_show_quality_dialog=True, jpeg_quality=50,
        )

        set_output_settings(settings, path=path)

        assert get_output_settings(path=path) == settings

    def test_set_preserves_other_settings_already_present(self, tmp_path):
        path = tmp_path / "config.json"
        set_capture_mouse_cursor(False, path=path)

        set_output_settings(OutputSettings(primary_format="jpg"), path=path)

        assert get_capture_mouse_cursor(path=path) is False

    def test_loading_an_older_config_missing_newer_fields_still_works(self, tmp_path):
        import json

        path = tmp_path / "config.json"
        path.write_text(json.dumps({"output_settings": {"primary_format": "jpg"}}))

        settings = get_output_settings(path=path)

        assert settings.primary_format == "jpg"
        assert settings.jpeg_quality == 80


class TestSuppressSaveDialogAtClose:
    def test_defaults_to_false(self, tmp_path):
        path = tmp_path / "config.json"
        assert get_suppress_save_dialog_at_close(path=path) is False

    def test_set_then_get_round_trips(self, tmp_path):
        path = tmp_path / "config.json"

        set_suppress_save_dialog_at_close(True, path=path)

        assert get_suppress_save_dialog_at_close(path=path) is True


class TestIconSize:
    def test_defaults_to_24(self, tmp_path):
        # ui/icons.py's own long-standing ICON_SIZE constant, not
        # Windows' 16 (see get_icon_size's own docstring for why).
        path = tmp_path / "config.json"
        assert get_icon_size(path=path) == 24

    def test_set_then_get_round_trips(self, tmp_path):
        path = tmp_path / "config.json"

        set_icon_size(48, path=path)

        assert get_icon_size(path=path) == 48


class TestUseDefaultProxy:
    def test_defaults_to_true(self, tmp_path):
        # matches Windows' UseProxy default (ICoreConfiguration.cs:215-217)
        path = tmp_path / "config.json"
        assert get_use_default_proxy(path=path) is True

    def test_set_then_get_round_trips(self, tmp_path):
        path = tmp_path / "config.json"

        set_use_default_proxy(False, path=path)

        assert get_use_default_proxy(path=path) is False


class TestUpdateCheckIntervalDays:
    def test_defaults_to_14(self, tmp_path):
        # matches Windows' UpdateCheckInterval default (ICoreConfiguration.cs:233-236)
        path = tmp_path / "config.json"
        assert get_update_check_interval_days(path=path) == 14

    def test_set_then_get_round_trips(self, tmp_path):
        path = tmp_path / "config.json"

        set_update_check_interval_days(7, path=path)

        assert get_update_check_interval_days(path=path) == 7


class TestLastUpdateCheck:
    def test_defaults_to_none(self, tmp_path):
        path = tmp_path / "config.json"
        assert get_last_update_check(path=path) is None

    def test_set_then_get_round_trips(self, tmp_path):
        path = tmp_path / "config.json"
        when = datetime(2026, 3, 5, 9, 7, 2)

        set_last_update_check(when, path=path)

        assert get_last_update_check(path=path) == when


class TestFilenameCounter:
    def test_defaults_to_one(self, tmp_path):
        # matches Windows' OutputFileIncrementingNumber default (ICoreConfiguration.cs:163-165)
        path = tmp_path / "config.json"
        assert get_filename_counter(path=path) == 1

    def test_set_then_get_round_trips(self, tmp_path):
        path = tmp_path / "config.json"

        set_filename_counter(42, path=path)

        assert get_filename_counter(path=path) == 42

    def test_consume_returns_the_current_value(self, tmp_path):
        path = tmp_path / "config.json"
        set_filename_counter(5, path=path)

        assert consume_filename_counter(path=path) == 5

    def test_consume_persists_the_incremented_value(self, tmp_path):
        path = tmp_path / "config.json"
        set_filename_counter(5, path=path)

        consume_filename_counter(path=path)

        assert get_filename_counter(path=path) == 6

    def test_repeated_consume_calls_increment_each_time(self, tmp_path):
        path = tmp_path / "config.json"

        values = [consume_filename_counter(path=path) for _ in range(3)]

        assert values == [1, 2, 3]


class TestFooterPattern:
    def test_defaults_to_the_previously_hardcoded_pattern(self, tmp_path):
        # ui/printing.py's _footer_text hardcoded this exact strftime
        # pattern before this setting existed - a fresh install must
        # keep printing the same footer.
        path = tmp_path / "config.json"
        assert get_footer_pattern(path=path) == "%B %d, %Y %I:%M %p"

    def test_set_then_get_round_trips(self, tmp_path):
        path = tmp_path / "config.json"

        set_footer_pattern("%Y-%m-%d", path=path)

        assert get_footer_pattern(path=path) == "%Y-%m-%d"


class TestExternalCommands:
    def test_defaults_to_empty(self, tmp_path):
        path = tmp_path / "config.json"
        assert get_external_commands(path=path) == []

    def test_set_then_get_round_trips(self, tmp_path):
        path = tmp_path / "config.json"
        commands = [
            ExternalCommand(name="Optimize", commandline="/usr/bin/optipng", argument="{0}", run_in_background=False),
            ExternalCommand(name="Notify", commandline="/usr/bin/notify-send", argument="Screenshot {0}"),
        ]

        set_external_commands(commands, path=path)

        assert get_external_commands(path=path) == commands

    def test_defaults_match_the_dataclass_defaults(self, tmp_path):
        path = tmp_path / "config.json"
        set_external_commands([ExternalCommand(name="Minimal", commandline="/bin/true")], path=path)

        [loaded] = get_external_commands(path=path)

        assert loaded.argument == "{0}"
        assert loaded.run_in_background is True

    def test_set_preserves_other_settings_already_present(self, tmp_path):
        path = tmp_path / "config.json"
        set_capture_mouse_cursor(False, path=path)

        set_external_commands([ExternalCommand(name="X", commandline="/bin/true")], path=path)

        assert get_capture_mouse_cursor(path=path) is False


class TestExcludedDestinations:
    def test_defaults_to_empty(self, tmp_path):
        # matches Windows' ExcludeDestinations - nothing excluded by
        # default, every destination (including future ones) enabled.
        path = tmp_path / "config.json"
        assert get_excluded_destinations(path=path) == set()

    def test_set_then_get_round_trips(self, tmp_path):
        path = tmp_path / "config.json"

        set_excluded_destinations({"print", "external:Optimize"}, path=path)

        assert get_excluded_destinations(path=path) == {"print", "external:Optimize"}

    def test_set_preserves_other_settings_already_present(self, tmp_path):
        path = tmp_path / "config.json"
        set_capture_mouse_cursor(False, path=path)

        set_excluded_destinations({"print"}, path=path)

        assert get_capture_mouse_cursor(path=path) is False


class TestShowMagnifierWhileSelecting:
    def test_defaults_to_true(self, tmp_path):
        # matches Windows' ZoomerEnabled default (ICoreConfiguration.cs:318-320)
        path = tmp_path / "config.json"
        assert get_show_magnifier_while_selecting(path=path) is True

    def test_set_then_get_round_trips(self, tmp_path):
        path = tmp_path / "config.json"

        set_show_magnifier_while_selecting(False, path=path)

        assert get_show_magnifier_while_selecting(path=path) is False


class TestFirstRunSetupFlag:
    def test_defaults_to_false(self, tmp_path):
        path = tmp_path / "config.json"
        assert is_first_run_setup_done(path=path) is False

    def test_mark_then_check_round_trips(self, tmp_path):
        path = tmp_path / "config.json"

        mark_first_run_setup_done(path=path)

        assert is_first_run_setup_done(path=path) is True

    def test_mark_preserves_other_settings_already_present(self, tmp_path):
        path = tmp_path / "config.json"
        set_output_directory(tmp_path / "shots", path=path)

        mark_first_run_setup_done(path=path)

        assert get_output_directory(path=path) == tmp_path / "shots"


class TestDefaultExternalCommandsSeededFlag:
    """Task #166 follow-up: whether the one-time LibreOffice/Krita
    auto-detection has run yet - a separate flag from
    first_run_setup_done, since seeding needs to happen on every very
    first app start (direflail's own explicit call: the user may
    never open Preferences at all) regardless of whether that
    person also says yes/no to the first-run wizard's own unrelated
    autostart/hotkeys offer.
    """

    def test_defaults_to_false(self, tmp_path):
        path = tmp_path / "config.json"
        assert is_default_external_commands_seeded(path=path) is False

    def test_mark_then_check_round_trips(self, tmp_path):
        path = tmp_path / "config.json"

        mark_default_external_commands_seeded(path=path)

        assert is_default_external_commands_seeded(path=path) is True
