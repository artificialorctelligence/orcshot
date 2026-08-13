"""OCR result data model - faithful port of OcrInformation/Line/Word
(Greenshot.Base/Interfaces/Ocr/OcrInformation.cs, Line.cs, Word.cs),
plus a parser for Tesseract OCR's ``--tsv`` output (task #100's
"Obfuscate Text").

Real Greenshot gets these from Windows.Media.Ocr (Win10OcrProvider.cs)
- an OS-level OCR engine with no Linux equivalent, so this port uses
Tesseract (``tesseract-ocr``, GPL-compatible, packaged for every
mainstream distro) instead. Windows.Media.Ocr's OcrEngine groups words
into lines itself before Win10OcrProvider.CreateOcrInformation
(Win10OcrProvider.cs:157-183) ever sees them; parse_tesseract_tsv does
that same grouping here, keyed by Tesseract's own (block_num, par_num,
line_num) - the finest granularity its TSV output exposes above the
word level.

Only this module (pure, no subprocess/file I/O) is unit tested -
ui/ocr.py's run_tesseract_ocr, which actually shells out, isn't, same
as every other "wraps an external CLI tool" function in this codebase
(see ui/external_commands.py's module docstring).
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass

from orcshot.core.geometry import Rect

SCOPE_WORDS = "words"
SCOPE_LINES = "lines"


@dataclass(frozen=True)
class Word:
    text: str
    bounds: Rect


@dataclass(frozen=True)
class Line:
    """A group of Words - faithful port of Line (Line.cs), whose own
    ``Text``/``CalculatedBounds`` (Line.cs:47-77) this mirrors as
    properties instead of precomputed fields, since this port's Word
    tuples are immutable (no in-place Offset to invalidate a cache).
    """

    words: tuple[Word, ...]

    @property
    def text(self) -> str:
        return " ".join(w.text for w in self.words)

    @property
    def bounds(self) -> Rect:
        lefts = [w.bounds.left for w in self.words]
        tops = [w.bounds.top for w in self.words]
        rights = [w.bounds.right for w in self.words]
        bottoms = [w.bounds.bottom for w in self.words]
        return Rect(min(lefts), min(tops), max(rights), max(bottoms))


@dataclass(frozen=True)
class OcrResult:
    lines: tuple[Line, ...] = ()

    @property
    def has_content(self) -> bool:
        return len(self.lines) > 0


def parse_tesseract_tsv(tsv_text: str) -> OcrResult:
    """Groups Tesseract's word-level (``level == 5``) TSV rows into
    Line objects, in first-seen order. Rows with blank text or
    negative confidence (Tesseract's own marker for a non-text
    detection at a given level, e.g. an empty line placeholder) are
    skipped, matching what OcrInformation.HasContent/Line.Text expect
    to see - only rows the engine actually recognized as words.
    """
    reader = csv.DictReader(io.StringIO(tsv_text), delimiter="\t")
    words_by_key: dict[tuple, list[Word]] = {}
    order: list[tuple] = []
    for row in reader:
        if row.get("level") != "5":
            continue
        text = (row.get("text") or "").strip()
        if not text:
            continue
        try:
            if float(row.get("conf", "-1")) < 0:
                continue
            left, top = int(row["left"]), int(row["top"])
            width, height = int(row["width"]), int(row["height"])
        except (KeyError, ValueError):
            continue

        key = (row.get("block_num"), row.get("par_num"), row.get("line_num"))
        word = Word(text=text, bounds=Rect(left, top, left + width, top + height))
        if key not in words_by_key:
            words_by_key[key] = []
            order.append(key)
        words_by_key[key].append(word)

    return OcrResult(lines=tuple(Line(words=tuple(words_by_key[k])) for k in order))


def is_valid_regex(pattern: str) -> bool:
    """Faithful port of TextObfuscationForm.IsValidRegex
    (TextObfuscationForm.cs:229-239) - tries the pattern against an
    empty string just to force compilation errors to surface.
    """
    try:
        re.compile(pattern)
        return True
    except re.error:
        return False


def _is_match(text: str, search_text: str, *, use_regex: bool, case_sensitive: bool) -> bool:
    """Faithful port of TextObfuscationForm.IsMatch
    (TextObfuscationForm.cs:280-297)."""
    if not text:
        return False
    if use_regex:
        try:
            flags = 0 if case_sensitive else re.IGNORECASE
            return re.search(search_text, text, flags) is not None
        except re.error:
            return False
    if case_sensitive:
        return search_text in text
    return search_text.lower() in text.lower()


def apply_padding(
    bounds: Rect, *, padding_horizontal: int, padding_vertical: int, offset_horizontal: int, offset_vertical: int,
) -> Rect:
    """Faithful port of TextObfuscationForm.ApplyPadding
    (TextObfuscationForm.cs:255-269) - padding is a percentage of the
    match's own width/height, split evenly on both sides; offset is a
    flat pixel shift applied after.
    """
    width_padding = int(bounds.width * padding_horizontal / 100.0 / 2)
    height_padding = int(bounds.height * padding_vertical / 100.0 / 2)
    return Rect(
        bounds.left - width_padding + offset_horizontal,
        bounds.top - height_padding + offset_vertical,
        bounds.right + width_padding + offset_horizontal,
        bounds.bottom + height_padding + offset_vertical,
    )


def find_matches(
    ocr: OcrResult, search_text: str, *, use_regex: bool, case_sensitive: bool, scope: str,
    padding_horizontal: int = 0, padding_vertical: int = 0, offset_horizontal: int = 0, offset_vertical: int = 0,
) -> list[Rect]:
    """Faithful port of TextObfuscationForm.SearchWords/SearchLines
    (TextObfuscationForm.cs:241-253) plus the minimum-3-characters gate
    UpdatePreview applies before searching at all
    (TextObfuscationForm.cs:180-183) - an empty/too-short search
    matches nothing rather than everything.
    """
    if len(search_text) < 3:
        return []

    def pad(bounds: Rect) -> Rect:
        return apply_padding(
            bounds, padding_horizontal=padding_horizontal, padding_vertical=padding_vertical,
            offset_horizontal=offset_horizontal, offset_vertical=offset_vertical,
        )

    matches: list[Rect] = []
    if scope == SCOPE_WORDS:
        for line in ocr.lines:
            for word in line.words:
                if _is_match(word.text, search_text, use_regex=use_regex, case_sensitive=case_sensitive):
                    matches.append(pad(word.bounds))
    else:
        for line in ocr.lines:
            if _is_match(line.text, search_text, use_regex=use_regex, case_sensitive=case_sensitive):
                matches.append(pad(line.bounds))
    return matches
