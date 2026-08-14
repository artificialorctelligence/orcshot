"""Faithful-in-spirit port of FilenameHelper.cs's ${TOKEN} substitution
(FillPattern, FilenameHelper.cs:344-441) - a subset of Windows' real
token set (date/time components, ${NUM}, ${title}), not the full thing
(no ${domain}/${user}/${hostname}/environment-folder tokens - low
value here, storage location is already its own separate setting; no
${now}/${capturetime} - redundant with the individual date tokens for
this port's simpler no-culture-mode design).
"""

from datetime import datetime

from orcshot.core.filename_pattern import (
    DEFAULT_FILENAME_PATTERN,
    make_filename_safe,
    resolve_filename_pattern,
)


class TestResolveFilenamePattern:
    def test_substitutes_date_and_time_tokens_zero_padded(self):
        when = datetime(2026, 3, 5, 9, 7, 2)
        result = resolve_filename_pattern("${YYYY}-${MM}-${DD} ${hh}_${mm}_${ss}", when, counter=1)
        assert result == "2026-03-05 09_07_02"

    def test_year_is_zero_padded_to_four_digits(self):
        when = datetime(999, 1, 1, 0, 0, 0)
        result = resolve_filename_pattern("${YYYY}", when, counter=1)
        assert result == "0999"

    def test_num_token_is_zero_padded_to_six_digits(self):
        when = datetime(2026, 1, 1, 0, 0, 0)
        assert resolve_filename_pattern("${NUM}", when, counter=42) == "000042"

    def test_num_token_not_padded_when_counter_already_wider(self):
        when = datetime(2026, 1, 1, 0, 0, 0)
        assert resolve_filename_pattern("${NUM}", when, counter=1234567) == "1234567"

    def test_title_token_substitutes_given_title(self):
        when = datetime(2026, 1, 1, 0, 0, 0)
        assert resolve_filename_pattern("${title}", when, counter=1, title="My Window") == "My Window"

    def test_title_token_defaults_to_empty_string(self):
        when = datetime(2026, 1, 1, 0, 0, 0)
        assert resolve_filename_pattern("${title}", when, counter=1) == ""

    def test_title_token_is_made_filename_safe(self):
        when = datetime(2026, 1, 1, 0, 0, 0)
        result = resolve_filename_pattern("${title}", when, counter=1, title="a/b:c")
        assert "/" not in result and ":" not in result

    def test_unknown_token_is_left_as_is(self):
        when = datetime(2026, 1, 1, 0, 0, 0)
        assert resolve_filename_pattern("${nonsense}", when, counter=1) == "${nonsense}"

    def test_plain_text_around_tokens_is_preserved(self):
        when = datetime(2026, 3, 5, 9, 7, 2)
        result = resolve_filename_pattern("screenshot-${YYYY}${MM}${DD}-final", when, counter=1)
        assert result == "screenshot-20260305-final"

    def test_default_pattern_matches_the_previous_hardcoded_quick_save_format(self):
        # quick_save_filename's own pre-existing default, now expressed
        # as a pattern instead of a hardcoded strftime call.
        when = datetime(2026, 7, 26, 14, 23, 5)
        assert resolve_filename_pattern(DEFAULT_FILENAME_PATTERN, when, counter=1) == "2026-07-26 14_23_05"


class TestMakeFilenameSafe:
    def test_strips_forward_slash(self):
        assert "/" not in make_filename_safe("a/b")

    def test_strips_windows_reserved_characters_too(self):
        # Faithful to FilenameHelper.cs's own MakeFilenameSafe - strips
        # Path.GetInvalidFileNameChars(), which includes several
        # characters that are perfectly legal on Linux (: * ? " < > |)
        # but not on Windows - kept broad so a saved file stays safe
        # to move/share to a Windows machine too.
        result = make_filename_safe('a:b*c?d"e<f>g|h')
        for char in ':*?"<>|':
            assert char not in result

    def test_replaces_disallowed_characters_with_underscore(self):
        assert make_filename_safe("a/b") == "a_b"

    def test_leaves_a_normal_string_unchanged(self):
        assert make_filename_safe("My Window Title") == "My Window Title"
