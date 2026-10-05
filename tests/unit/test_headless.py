"""orcshot --capture-to / --window / --can-capture (BACKLOG #225).

The scripting face of Orcshot: write a PNG to a path the caller names,
print that path, exit 0 - or exit non-zero with one line on stderr saying
why. No menu, no editor, no focus change, no tray process left behind.

Parsing happens in main() before OrcshotApplication exists, so it cannot
use GLib's option parser at all: add_main_option lives on the application
object this path exists to avoid. Hence a plain argparse pass over argv,
tolerant of every flag it does not own.

Everything here is pure - the capture itself is a seam these tests
replace, so none of this needs a display, a bus, or GTK.
"""

import pytest

from orcshot import headless
from orcshot.capture.modes import HeadlessCaptureError


class TestDecidingWhetherThisIsAHeadlessInvocation:
    def test_a_bare_launch_is_not(self):
        assert headless.parse_headless_request(["orcshot"]) is None

    def test_an_ordinary_capture_flag_is_not(self):
        """--capture-region opens the interactive GUI and must keep doing
        exactly that; headless is a separate face, not a reinterpretation
        of the existing flags.
        """
        assert headless.parse_headless_request(["orcshot", "--capture-region"]) is None

    def test_opening_a_file_is_not(self):
        assert headless.parse_headless_request(["orcshot", "/home/me/shot.orcshot"]) is None

    def test_capture_to_is(self):
        request = headless.parse_headless_request(["orcshot", "--capture-to", "/tmp/shot.png"])

        assert request.capture_to == "/tmp/shot.png"
        assert request.window is None
        assert request.can_capture is False

    def test_can_capture_is(self):
        request = headless.parse_headless_request(["orcshot", "--can-capture"])

        assert request.can_capture is True
        assert request.capture_to is None

    def test_a_window_title_comes_through_verbatim(self):
        request = headless.parse_headless_request(
            ["orcshot", "--capture-to", "/tmp/a.png", "--window", "Mozilla Firefox"]
        )

        assert request.window == "Mozilla Firefox"

    def test_unrelated_flags_are_tolerated_not_rejected(self):
        """GLib's own flags still reach the application when this path
        declines, so this parser must never object to one it has not
        heard of.
        """
        request = headless.parse_headless_request(
            ["orcshot", "--gapplication-service", "--capture-to", "/tmp/a.png"]
        )

        assert request.capture_to == "/tmp/a.png"

    def test_help_is_left_to_the_application(self):
        """--help must still print GLib's own option help, so this parser
        must not claim it and exit.
        """
        assert headless.parse_headless_request(["orcshot", "--help"]) is None


class TestProbing:
    def test_a_usable_session_exits_zero_and_says_nothing(self, monkeypatch, capsys):
        monkeypatch.setattr(headless, "_can_capture", lambda: True)

        assert headless.run(headless.parse_headless_request(["orcshot", "--can-capture"])) == 0
        captured = capsys.readouterr()
        assert captured.out == ""
        assert captured.err == ""

    def test_an_unusable_session_exits_non_zero_and_still_says_nothing(self, monkeypatch, capsys):
        """A probe is asked constantly by a backend chooser - it must be
        cheap and silent, not chatty.
        """
        monkeypatch.setattr(headless, "_can_capture", lambda: False)

        assert headless.run(headless.parse_headless_request(["orcshot", "--can-capture"])) != 0
        captured = capsys.readouterr()
        assert captured.out == ""
        assert captured.err == ""


class TestCapturing:
    def test_success_prints_only_the_path_and_exits_zero(self, monkeypatch, capsys):
        """A caller does PATH=$(orcshot --capture-to ...), so stdout
        carries the path and nothing else, ever.
        """
        monkeypatch.setattr(headless, "_capture_and_write", lambda capture_to, window: None)

        status = headless.run(headless.parse_headless_request(["orcshot", "--capture-to", "/tmp/shot.png"]))

        assert status == 0
        assert capsys.readouterr().out == "/tmp/shot.png\n"

    def test_the_window_title_reaches_the_capture(self, monkeypatch):
        seen = {}
        monkeypatch.setattr(
            headless, "_capture_and_write",
            lambda capture_to, window: seen.update(path=capture_to, window=window),
        )

        headless.run(
            headless.parse_headless_request(
                ["orcshot", "--capture-to", "/tmp/a.png", "--window", "Text Editor"]
            )
        )

        assert seen == {"path": "/tmp/a.png", "window": "Text Editor"}

    def test_a_refusal_is_one_line_on_stderr_and_a_non_zero_exit(self, monkeypatch, capsys):
        def refuse(capture_to, window):
            raise HeadlessCaptureError("window 'Mozilla Firefox' is minimised")

        monkeypatch.setattr(headless, "_capture_and_write", refuse)

        status = headless.run(
            headless.parse_headless_request(["orcshot", "--capture-to", "/tmp/a.png", "--window", "Firefox"])
        )
        captured = capsys.readouterr()

        assert status != 0
        assert captured.out == ""
        assert captured.err.strip().splitlines() == ["orcshot: window 'Mozilla Firefox' is minimised"]

    def test_an_unwritable_path_is_reported_not_traced(self, monkeypatch, capsys):
        """A stack trace is not an error message. The caller gets one
        line it can log.
        """
        def explode(capture_to, window):
            raise OSError(13, "Permission denied")

        monkeypatch.setattr(headless, "_capture_and_write", explode)

        status = headless.run(headless.parse_headless_request(["orcshot", "--capture-to", "/root/a.png"]))
        captured = capsys.readouterr()

        assert status != 0
        assert len(captured.err.strip().splitlines()) == 1
        assert "Permission denied" in captured.err

    def test_nothing_is_printed_to_stdout_on_failure(self, monkeypatch, capsys):
        """The path is printed only after the file really exists, or
        `PATH=$(orcshot ...)` would hand a caller a path to nothing.
        """
        monkeypatch.setattr(
            headless, "_capture_and_write",
            lambda capture_to, window: (_ for _ in ()).throw(HeadlessCaptureError("no window matching 'x'")),
        )

        headless.run(headless.parse_headless_request(["orcshot", "--capture-to", "/tmp/a.png"]))

        assert capsys.readouterr().out == ""


class TestUsage:
    @pytest.mark.parametrize("argv", [
        ["orcshot", "--capture-to"],
        ["orcshot", "--capture-to", "--window"],
        ["orcshot", "--can-capture", "--window"],
    ])
    def test_a_flag_missing_its_value_does_not_escape_as_a_bare_exit(self, argv):
        """argparse's own error() calls sys.exit(2) and prints a usage
        dump. That is not this interface's contract: parsing is called
        from main() with nothing around it, so a SystemExit would sail
        straight out of the process with two lines on stderr and the
        wrong status. It has to come back as an ordinary request that
        run() can refuse in one line.
        """
        request = headless.parse_headless_request(argv)

        assert request is not None

    @pytest.mark.parametrize("argv,flag", [
        (["orcshot", "--capture-to"], "--capture-to"),
        # argparse names the flag that expected a value, not the token
        # that looked like one - so this case also names --capture-to.
        (["orcshot", "--capture-to", "--window"], "--capture-to"),
    ])
    def test_a_flag_missing_its_value_is_reported_by_name(self, argv, flag, capsys, monkeypatch):
        """Naming the offending flag is the load-bearing assertion.

        Shape alone is not enough: with the usage check removed, the
        request falls through to a real capture with no destination,
        which also fails with one line and exit 1 - so a test asserting
        only "one line, exit 1" passes either way. It did (rule 5,
        2026-09-27). The capture seam is replaced here so that fallback
        cannot quietly stand in for the real answer.
        """
        monkeypatch.setattr(
            headless, "_capture_and_write",
            lambda capture_to, window: pytest.fail("a malformed command line must never reach a capture"),
        )

        status = headless.run(headless.parse_headless_request(argv))
        captured = capsys.readouterr()

        assert status == 1
        assert captured.out == ""
        assert len(captured.err.strip().splitlines()) == 1
        assert captured.err.startswith("orcshot: ")
        assert flag in captured.err


    def test_a_window_without_a_destination_is_refused(self, capsys):
        """--window alone has nowhere to put the result."""
        status = headless.run(headless.parse_headless_request(["orcshot", "--window", "Firefox", "--can-capture"]))

        assert status != 0
        assert "window" in capsys.readouterr().err.lower()
