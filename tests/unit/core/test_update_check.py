from datetime import datetime, timedelta

from orcshot.core.update_check import is_newer_version, parse_version, should_check_now


class TestParseVersion:
    def test_strips_leading_v(self):
        assert parse_version("v1.2.0") == (1, 2, 0)

    def test_strips_prerelease_suffix_like_windows_own_regex(self):
        # Matches UpdateService.cs's ProcessFeed: Regex.Replace(tag,
        # "[a-zA-Z\-]*", "") strips both letters and hyphens.
        assert parse_version("1.2.0-beta") == (1, 2, 0)

    def test_plain_numeric_tag(self):
        assert parse_version("2.0.1") == (2, 0, 1)

    def test_two_part_version(self):
        assert parse_version("1.5") == (1, 5)


class TestIsNewerVersion:
    def test_newer_patch_is_newer(self):
        assert is_newer_version("1.2.1", "1.2.0")

    def test_older_version_is_not_newer(self):
        assert not is_newer_version("1.1.0", "1.2.0")

    def test_same_version_is_not_newer(self):
        assert not is_newer_version("1.2.0", "1.2.0")

    def test_v_prefix_does_not_affect_comparison(self):
        assert is_newer_version("v1.3.0", "1.2.0")

    def test_newer_major_beats_larger_patch(self):
        assert is_newer_version("2.0.0", "1.99.99")

    def test_differing_part_counts_compare_correctly(self):
        assert is_newer_version("1.2.0.1", "1.2.0")


class TestShouldCheckNow:
    def test_zero_interval_disables_checking_entirely(self):
        assert not should_check_now(None, 0, datetime(2026, 1, 1))

    def test_negative_interval_disables_checking(self):
        assert not should_check_now(None, -1, datetime(2026, 1, 1))

    def test_never_checked_before_checks_immediately(self):
        assert should_check_now(None, 14, datetime(2026, 1, 1))

    def test_checked_recently_does_not_check_again(self):
        last = datetime(2026, 1, 1)
        now = last + timedelta(days=5)
        assert not should_check_now(last, 14, now)

    def test_interval_elapsed_checks_again(self):
        last = datetime(2026, 1, 1)
        now = last + timedelta(days=14)
        assert should_check_now(last, 14, now)

    def test_interval_not_yet_elapsed_by_one_day(self):
        last = datetime(2026, 1, 1)
        now = last + timedelta(days=13)
        assert not should_check_now(last, 14, now)
