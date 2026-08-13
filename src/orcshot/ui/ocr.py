"""Runs Tesseract OCR as a subprocess - the actual "get OCR results for
this image" step behind task #100's Obfuscate Text. Only tesseract-
specific glue lives here (temp-file handling, subprocess invocation,
availability check); the OCR result data model and all search/padding
logic are pure and live in core/ocr.py instead.

Mirrors Win10OcrProvider.DoOcrAsync(ISurface)'s own scope
(Win10OcrProvider.cs:60-99): OCR runs on the editor's *base* image only
(``SaveBackgroundOnly = true``), not the fully composited image with
existing annotations, so already-obfuscated regions or drawn shapes
never get OCR'd. Deliberately not ported: the grayscale pre-filter and
130x130 minimum-canvas padding Win10OcrProvider applies before handing
the image to the Windows OCR engine (Win10OcrProvider.cs:76-93) - both
are quality/compatibility workarounds specific to that engine, not
something Tesseract has been observed to need; can be added if a real
capture turns out to need it.

Not unit tested - a subprocess call to an external CLI tool, same as
every other "wraps an external CLI tool" function in this codebase
(ui/external_commands.py's run_external_command, ui/editor_window.py's
_find_external_editor_command). Verified live: ran against a real
captured screenshot containing text, confirmed matching words/lines
and bounding boxes.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import numpy as np

from orcshot.core.ocr import OcrResult, parse_tesseract_tsv
from orcshot.ui.file_export import orcshot_cache_dir, save_image_to_file


def tesseract_available(which=shutil.which) -> bool:
    return which("tesseract") is not None


def run_tesseract_ocr(image: np.ndarray, cache_dir: Path = None) -> OcrResult:
    """Runs ``tesseract <tmpfile> stdout tsv`` against ``image`` and
    returns the parsed result. Writes a temp PNG first (reusing
    ui/file_export.py's existing orcshot_cache_dir/save_image_to_file -
    the same pattern already used for handing a captured image to an
    external editor or command) since tesseract is a CLI tool, not a
    library this port links against.
    """
    if cache_dir is None:
        cache_dir = orcshot_cache_dir()
    fd, path_str = tempfile.mkstemp(suffix=".png", prefix="orcshot-ocr-", dir=str(cache_dir))
    os.close(fd)
    path = Path(path_str)
    try:
        save_image_to_file(image, path)
        result = subprocess.run(
            ["tesseract", str(path), "stdout", "tsv"],
            capture_output=True, text=True, timeout=30, check=True,
        )
    finally:
        path.unlink(missing_ok=True)
    return parse_tesseract_tsv(result.stdout)
