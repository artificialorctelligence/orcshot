"""Persistent app settings - currently just the screenshot save
directory (configurable from the editor, see ui/editor_window.py) and
a one-time "first-run setup already ran" flag (see
ui/first_run_setup.py). A plain JSON file, same testing approach as
autostart.py's .desktop entry: real file I/O, exercised for real here
against a temp path, never the actual default XDG path.
"""

from datetime import datetime
from pathlib import Path

from greenshot_linux.settings import (
    CONFIG_FILENAME,
    config_file_path,
    default_output_directory,
    get_output_directory,
    is_first_run_setup_done,
    mark_first_run_setup_done,
    quick_save_filename,
    set_output_directory,
)


class TestConfigFilePath:
    def test_uses_xdg_config_home_when_given(self, tmp_path):
        path = config_file_path(config_home=tmp_path)
        assert path == tmp_path / "greenshot-linux" / CONFIG_FILENAME

    def test_defaults_to_the_real_xdg_config_home_when_not_given(self):
        path = config_file_path()
        assert path.name == CONFIG_FILENAME
        assert path.parent.name == "greenshot-linux"


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
        assert quick_save_filename(when) == "2026-07-26 14_23_05.png"

    def test_different_times_produce_different_filenames(self):
        a = quick_save_filename(datetime(2026, 7, 26, 14, 23, 5))
        b = quick_save_filename(datetime(2026, 7, 26, 14, 23, 6))
        assert a != b


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
