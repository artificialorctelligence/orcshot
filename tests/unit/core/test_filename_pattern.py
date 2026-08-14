"""Two mutually exclusive filename-pattern modes - see
core/filename_pattern.py's own module docstring for why they're
never mixed (a bare "%" prefix next to ordinary text is inherently
self-ambiguous, confirmed live: even a curated "safe" strftime
whitelist still let %d eat the "d" out of an otherwise ordinary word
"done"). One delimiter convention active at a time removes the
ambiguity entirely.
"""

import random
from datetime import datetime

from orcshot.core.filename_pattern import (
    DEFAULT_FILENAME_PATTERN,
    MODE_GREENSHOT,
    MODE_STRFTIME,
    make_filename_safe,
    resolve_filename_pattern,
)


class TestGreenshotMode:
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

    def test_rrr_token_produces_random_alphanumerics_of_matching_length(self):
        when = datetime(2026, 1, 1, 0, 0, 0)
        result = resolve_filename_pattern("${RRRR}", when, counter=1, rng=random.Random(0))
        assert len(result) == 4
        assert result.isalnum()

    def test_rrr_token_length_matches_the_number_of_rs(self):
        when = datetime(2026, 1, 1, 0, 0, 0)
        result = resolve_filename_pattern("${RRRRRRRR}", when, counter=1, rng=random.Random(0))
        assert len(result) == 8

    def test_rrr_token_is_deterministic_given_the_same_rng_seed(self):
        when = datetime(2026, 1, 1, 0, 0, 0)
        a = resolve_filename_pattern("${RRRR}", when, counter=1, rng=random.Random(42))
        b = resolve_filename_pattern("${RRRR}", when, counter=1, rng=random.Random(42))
        assert a == b

    def test_a_percent_character_is_left_completely_literal(self):
        # % is never parsed in Greenshot mode at all - matches real
        # Windows' own behavior exactly (it only ever understands
        # ${...}).
        when = datetime(2026, 1, 1, 0, 0, 0)
        assert resolve_filename_pattern("100%done", when, counter=1) == "100%done"


class TestStrftimeMode:
    def test_strftime_codes_are_substituted(self):
        when = datetime(2026, 3, 5, 9, 7, 2)
        result = resolve_filename_pattern("%Y-%m-%d", when, counter=1, mode=MODE_STRFTIME)
        assert result == "2026-03-05"

    def test_dollar_tokens_are_left_completely_literal(self):
        # ${...} is never parsed in strftime mode at all - modes are
        # mutually exclusive, not composed.
        when = datetime(2026, 3, 5, 9, 7, 2)
        result = resolve_filename_pattern("%Y-${NUM}", when, counter=7, mode=MODE_STRFTIME)
        assert result == "2026-${NUM}"

    def test_double_percent_is_the_standard_escape_for_a_literal_percent(self):
        # Real, full strftime() - this mode is an explicit opt-in, so
        # the standard "%%" escape convention is expected/documented
        # behavior for anyone choosing it, not a silent footgun.
        when = datetime(2026, 3, 5, 9, 7, 2)
        assert resolve_filename_pattern("100%%done", when, counter=1, mode=MODE_STRFTIME) == "100%done"


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
