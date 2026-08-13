"""Tests for parse_tesseract_tsv and the search/padding logic ported
from TextObfuscationForm (task #100) - see core/ocr.py's module
docstring.
"""

from orcshot.core.geometry import Rect
from orcshot.core.ocr import (
    SCOPE_LINES,
    SCOPE_WORDS,
    Line,
    OcrResult,
    Word,
    apply_padding,
    find_matches,
    is_valid_regex,
    parse_tesseract_tsv,
)

_SAMPLE_TSV = (
    "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n"
    "1\t1\t0\t0\t0\t0\t0\t0\t200\t100\t-1\t\n"
    "2\t1\t1\t0\t0\t0\t0\t0\t200\t50\t-1\t\n"
    "3\t1\t1\t1\t0\t0\t0\t0\t200\t50\t-1\t\n"
    "4\t1\t1\t1\t1\t0\t0\t0\t200\t20\t-1\t\n"
    "5\t1\t1\t1\t1\t1\t10\t5\t50\t15\t95.5\tHello\n"
    "5\t1\t1\t1\t1\t2\t70\t5\t60\t15\t93.2\tworld\n"
    "4\t1\t1\t1\t2\t0\t0\t30\t200\t20\t-1\t\n"
    "5\t1\t1\t1\t2\t1\t10\t35\t60\t15\t90.1\tSecond\n"
    "5\t1\t1\t1\t2\t2\t80\t35\t40\t15\t88.4\tline\n"
)


class TestParseTesseractTsv:
    def test_groups_words_into_lines(self):
        result = parse_tesseract_tsv(_SAMPLE_TSV)
        assert len(result.lines) == 2
        assert result.lines[0].text == "Hello world"
        assert result.lines[1].text == "Second line"

    def test_word_bounds_are_left_top_right_bottom(self):
        result = parse_tesseract_tsv(_SAMPLE_TSV)
        hello = result.lines[0].words[0]
        assert hello.text == "Hello"
        assert hello.bounds == Rect(10, 5, 60, 20)

    def test_line_bounds_union_its_words(self):
        result = parse_tesseract_tsv(_SAMPLE_TSV)
        assert result.lines[0].bounds == Rect(10, 5, 130, 20)

    def test_has_content(self):
        assert parse_tesseract_tsv(_SAMPLE_TSV).has_content
        assert not parse_tesseract_tsv(
            "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n"
        ).has_content

    def test_skips_non_word_level_and_blank_rows(self):
        tsv = (
            "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n"
            "5\t1\t1\t1\t1\t1\t10\t5\t50\t15\t-1\t\n"  # negative conf, blank text - skipped
            "5\t1\t1\t1\t1\t2\t70\t5\t60\t15\t93.2\tworld\n"
        )
        result = parse_tesseract_tsv(tsv)
        assert len(result.lines) == 1
        assert result.lines[0].text == "world"

    def test_low_confidence_word_is_dropped_even_though_not_the_negative_sentinel(self):
        # A likely misread of non-text image content (an icon, a photo)
        # rather than Tesseract's own "not text" placeholder - see
        # DEFAULT_MIN_CONFIDENCE's docstring.
        tsv = (
            "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n"
            "5\t1\t1\t1\t1\t1\t10\t5\t50\t15\t12.0\tblob\n"
            "5\t1\t1\t1\t1\t2\t70\t5\t60\t15\t93.2\tworld\n"
        )
        result = parse_tesseract_tsv(tsv)
        assert len(result.lines) == 1
        assert result.lines[0].text == "world"

    def test_min_confidence_is_configurable(self):
        tsv = (
            "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n"
            "5\t1\t1\t1\t1\t1\t10\t5\t50\t15\t12.0\tblob\n"
        )
        assert not parse_tesseract_tsv(tsv).has_content
        assert parse_tesseract_tsv(tsv, min_confidence=0).has_content

    def test_stray_unescaped_quote_does_not_swallow_later_rows(self):
        # Confirmed live against a real screenshot: Tesseract's TSV
        # output is a naive tab-split dump with no quoting/escaping,
        # but csv.DictReader's default dialect treats a bare `"` as an
        # open-quote regardless - without quoting=csv.QUOTE_NONE, a
        # single misread `"` character (its own low-confidence "word")
        # silently absorbed every row up to the next `"` anywhere later
        # in the file into one mangled field, dropping real
        # high-confidence words with no error at all.
        tsv = (
            "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n"
            "5\t1\t1\t1\t1\t1\t10\t5\t20\t15\t22.0\t\"\n"
            "5\t1\t2\t1\t1\t1\t50\t5\t60\t15\t96.5\tPeacock\n"
            "5\t1\t3\t1\t1\t1\t120\t5\t40\t15\t70.1\tage\".\n"
        )
        result = parse_tesseract_tsv(tsv)
        all_words = [w.text for line in result.lines for w in line.words]
        assert "Peacock" in all_words


class TestApplyPadding:
    def test_no_padding_or_offset_is_a_no_op(self):
        bounds = Rect(10, 10, 30, 20)
        assert apply_padding(
            bounds, padding_horizontal=0, padding_vertical=0, offset_horizontal=0, offset_vertical=0,
        ) == bounds

    def test_padding_expands_symmetrically(self):
        # width=20, 20% padding -> 2px each side (int(20*20/100/2) == int(2.0) == 2)
        bounds = Rect(10, 10, 30, 20)
        result = apply_padding(
            bounds, padding_horizontal=20, padding_vertical=0, offset_horizontal=0, offset_vertical=0,
        )
        assert result == Rect(8, 10, 32, 20)

    def test_offset_shifts_the_whole_box(self):
        bounds = Rect(10, 10, 30, 20)
        result = apply_padding(
            bounds, padding_horizontal=0, padding_vertical=0, offset_horizontal=5, offset_vertical=-3,
        )
        assert result == Rect(15, 7, 35, 17)


class TestFindMatches:
    def _ocr(self):
        return OcrResult(lines=(
            Line(words=(Word("Hello", Rect(0, 0, 50, 15)), Word("world", Rect(60, 0, 110, 15)))),
            Line(words=(Word("Second", Rect(0, 20, 60, 35)), Word("line", Rect(70, 20, 100, 35)))),
        ))

    def test_below_three_characters_matches_nothing(self):
        assert find_matches(self._ocr(), "wo", use_regex=False, case_sensitive=False, scope=SCOPE_WORDS) == []

    def test_word_scope_matches_individual_words(self):
        matches = find_matches(self._ocr(), "world", use_regex=False, case_sensitive=False, scope=SCOPE_WORDS)
        assert matches == [Rect(60, 0, 110, 15)]

    def test_case_insensitive_by_default(self):
        matches = find_matches(self._ocr(), "WORLD", use_regex=False, case_sensitive=False, scope=SCOPE_WORDS)
        assert len(matches) == 1

    def test_case_sensitive_excludes_mismatched_case(self):
        matches = find_matches(self._ocr(), "WORLD", use_regex=False, case_sensitive=True, scope=SCOPE_WORDS)
        assert matches == []

    def test_line_scope_matches_whole_line_bounds(self):
        matches = find_matches(self._ocr(), "Second line", use_regex=False, case_sensitive=False, scope=SCOPE_LINES)
        assert matches == [Rect(0, 20, 100, 35)]

    def test_regex_scope(self):
        matches = find_matches(self._ocr(), r"^(Hello|Second)$", use_regex=True, case_sensitive=False, scope=SCOPE_WORDS)
        assert len(matches) == 2

    def test_invalid_regex_matches_nothing_rather_than_raising(self):
        matches = find_matches(self._ocr(), "[invalid(", use_regex=True, case_sensitive=False, scope=SCOPE_WORDS)
        assert matches == []

    def test_padding_applied_to_every_match(self):
        matches = find_matches(
            self._ocr(), "world", use_regex=False, case_sensitive=False, scope=SCOPE_WORDS,
            offset_horizontal=10,
        )
        assert matches == [Rect(70, 0, 120, 15)]


class TestIsValidRegex:
    def test_valid_pattern(self):
        assert is_valid_regex(r"\d+")

    def test_invalid_pattern(self):
        assert not is_valid_regex("[invalid(")
