"""AST-based sink-list scanner for the i18n regression guard (i18n
phase 1). Test-only tooling, not shipped runtime code - see
docs/superpowers/specs/2026-08-23-i18n-phase1-gettext-infrastructure-design.md's
"The regression guard" section for why this is sink-list-based (does a
string literal reach a known GTK/Gio text-setting call?) rather than
text-shape-heuristic-based (a heuristic like "capitalized with a
space" would miss short unspaced labels like "OK"/"Cancel").
"""

from __future__ import annotations

import ast
from dataclasses import dataclass

_SINK_METHODS = {
    "set_text", "set_tooltip_text", "set_label", "set_title", "set_markup",
    "set_placeholder_text", "set_body", "format_secondary_text",
    "set_program_name", "set_comments",
    "add_buttons", "add_button", "new_with_label", "new_with_label_from_widget",
    "set_name", "append_text",
}

_SINK_CONSTRUCTORS = {
    "Label", "CheckButton", "Frame", "Button", "Dialog", "FileChooserDialog",
    "MenuItem", "MenuButton", "ColorChooserDialog", "ImageMenuItem", "MessageDialog",
}

_SINK_KWARGS = {"label", "title", "text", "secondary_text"}


@dataclass
class Violation:
    line: int
    message: str


def _line_has_noqa(source_lines: list[str], line: int) -> bool:
    if line - 1 >= len(source_lines):
        return False
    return "# noqa: i18n" in source_lines[line - 1]


def scan_source(source: str, filename: str = "<test>") -> list[Violation]:
    # Only ast.Constant string-literal arguments are ever flagged below
    # (not ast.Call, ast.BinOp, etc.) - this is what makes an
    # already-wrapped _("...") or _("...").format(...) argument
    # naturally pass through unflagged with no separate "is this
    # wrapped" check needed: neither is a bare Constant node.
    tree = ast.parse(source, filename=filename)
    source_lines = source.splitlines()
    violations: list[Violation] = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue

        # Gio.Notification.new("...") - first positional arg.
        if (
            isinstance(node.func, ast.Attribute)
            and node.func.attr == "new"
            and isinstance(node.func.value, ast.Attribute)
            and node.func.value.attr == "Notification"
        ):
            if node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                if not _line_has_noqa(source_lines, node.lineno):
                    violations.append(Violation(node.lineno, "unwrapped Gio.Notification.new(...) title"))
            continue

        # method_call sinks: widget.set_text("...")
        if isinstance(node.func, ast.Attribute) and node.func.attr in _SINK_METHODS:
            for arg in node.args:
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    if not _line_has_noqa(source_lines, node.lineno):
                        violations.append(Violation(node.lineno, f"unwrapped string in .{node.func.attr}(...)"))
            continue

        # constructor kwargs: Gtk.Label(label="...")
        callee_name = None
        if isinstance(node.func, ast.Attribute):
            callee_name = node.func.attr
        elif isinstance(node.func, ast.Name):
            callee_name = node.func.id
        if callee_name in _SINK_CONSTRUCTORS:
            for kw in node.keywords:
                if kw.arg in _SINK_KWARGS and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
                    if not _line_has_noqa(source_lines, node.lineno):
                        violations.append(Violation(node.lineno, f"unwrapped {kw.arg}= on {callee_name}(...)"))

    return violations
