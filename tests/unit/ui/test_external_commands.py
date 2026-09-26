"""ui/external_commands.py's pure logic.

The file is at 59.9% coverage and 72% mutation score with 133 surviving
mutants (BACKLOG #220) - the worst of both in one place - and one of its
functions is a security boundary, so this gets more than smoke tests.

build_command_argv is that boundary. Its docstring's claim is strong and
specific: splitting the argument template into tokens *before*
substitution makes it "injection-proof by construction", because each
argv item goes straight to execve() and is never reinterpreted. Windows'
original needed a regex denylist of shell metacharacters to get the same
property. A claim like that is worth holding down with hostile input
rather than trusting, so TestBuildCommandArgv feeds it the characters an
attacker would reach for and asserts the path always arrives as exactly
one argv item.

Nothing here runs a real process, touches snapd, or reads the real
desktop-entry directories.
"""

import shutil

import pytest

from orcshot.settings import ExternalCommand
from orcshot.ui.external_commands import (
    InstalledApp,
    _is_newer_ignoring_bad_versions,
    _is_snap_command,
    _validate,
    build_command_argv,
    search_installed_apps,
)


def _command(argument: str = "{0}", commandline: str = "/usr/bin/krita") -> ExternalCommand:
    return ExternalCommand(name="Krita", commandline=commandline, argument=argument)


class TestBuildCommandArgv:
    """The injection boundary. Every case here is a real filename an
    attacker (or an ordinary user with an odd folder name) could produce.
    """

    def test_the_program_is_always_the_first_argv_item(self):
        assert build_command_argv(_command(), "/tmp/shot.png")[0] == "/usr/bin/krita"

    def test_the_placeholder_becomes_the_path(self):
        assert build_command_argv(_command("{0}"), "/tmp/shot.png") == ["/usr/bin/krita", "/tmp/shot.png"]

    def test_a_path_containing_a_space_stays_one_argument(self):
        argv = build_command_argv(_command("{0}"), "/home/me/My Screenshots/shot.png")

        assert argv[1:] == ["/home/me/My Screenshots/shot.png"]

    @pytest.mark.parametrize(
        "hostile",
        [
            "/tmp/a;rm -rf ~.png",
            "/tmp/a|tee evil.png",
            "/tmp/a&&whoami.png",
            "/tmp/a$(id).png",
            "/tmp/a`id`.png",
            "/tmp/a'quote.png",
            '/tmp/a"quote.png',
            "/tmp/a\nnewline.png",
            "/tmp/a>redirect.png",
            "/tmp/a*glob.png",
            "/tmp/../../etc/passwd.png",
            "/tmp/a$HOME.png",
        ],
    )
    def test_shell_metacharacters_in_the_path_never_split_the_argument(self, hostile):
        """The whole point of tokenising before substituting: whatever
        the path contains, it is one argv item, so execve() can never
        read it back as syntax.
        """
        argv = build_command_argv(_command("{0}"), hostile)

        assert argv == ["/usr/bin/krita", hostile]

    def test_a_multi_token_template_keeps_its_tokens_separate(self):
        argv = build_command_argv(_command("--new-image {0} --fullscreen"), "/tmp/shot.png")

        assert argv == ["/usr/bin/krita", "--new-image", "/tmp/shot.png", "--fullscreen"]

    def test_a_quoted_template_token_is_one_argument(self):
        argv = build_command_argv(_command('--comment "a screenshot" {0}'), "/tmp/shot.png")

        assert argv == ["/usr/bin/krita", "--comment", "a screenshot", "/tmp/shot.png"]

    def test_every_placeholder_in_the_template_gets_the_path(self):
        argv = build_command_argv(_command("{0} --backup {0}"), "/tmp/shot.png")

        assert argv == ["/usr/bin/krita", "/tmp/shot.png", "--backup", "/tmp/shot.png"]

    def test_an_empty_template_runs_the_program_with_no_arguments(self):
        assert build_command_argv(_command(""), "/tmp/shot.png") == ["/usr/bin/krita"]

    def test_a_template_token_without_a_placeholder_is_passed_through(self):
        argv = build_command_argv(_command("--headless"), "/tmp/shot.png")

        assert argv == ["/usr/bin/krita", "--headless"]


class TestIsSnapCommand:
    def test_a_snap_wrapper_path_is_recognised(self, monkeypatch):
        monkeypatch.setattr(shutil, "which", lambda name: None)

        assert _is_snap_command("/snap/bin/krita") is True

    def test_a_native_path_is_not(self, monkeypatch):
        monkeypatch.setattr(shutil, "which", lambda name: None)

        assert _is_snap_command("/usr/bin/krita") is False

    def test_a_bare_name_is_resolved_through_path_first(self, monkeypatch):
        monkeypatch.setattr(shutil, "which", lambda name: "/snap/bin/krita" if name == "krita" else None)

        assert _is_snap_command("krita") is True

    def test_a_bare_name_resolving_outside_snap_is_not_a_snap(self, monkeypatch):
        monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/gimp")

        assert _is_snap_command("gimp") is False

    def test_a_dotted_path_is_normalised_before_the_prefix_check(self, monkeypatch):
        """abspath's job here - see the function's docstring on why it is
        abspath and not realpath.
        """
        monkeypatch.setattr(shutil, "which", lambda name: None)

        assert _is_snap_command("/snap/bin/./krita") is True
        assert _is_snap_command("/snap/bin/../../usr/bin/krita") is False


class TestValidate:
    @pytest.fixture(autouse=True)
    def no_existing_commands(self, monkeypatch):
        monkeypatch.setattr("orcshot.ui.external_commands.get_external_commands", lambda: [])

    def test_a_blank_name_is_rejected(self):
        assert _validate("   ", "/usr/bin/krita", "{0}", None) is not None

    def test_a_duplicate_name_is_rejected(self, monkeypatch):
        monkeypatch.setattr(
            "orcshot.ui.external_commands.get_external_commands",
            lambda: [ExternalCommand(name="Krita", commandline="/usr/bin/krita")],
        )

        assert _validate("Krita", "/usr/bin/krita", "{0}", None) is not None

    def test_renaming_a_command_to_its_own_existing_name_is_allowed(self, monkeypatch):
        """existing_name exempts the entry being edited from the
        uniqueness check, or editing a command without renaming it would
        report a clash with itself.
        """
        monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/krita")
        monkeypatch.setattr(
            "orcshot.ui.external_commands.get_external_commands",
            lambda: [ExternalCommand(name="Krita", commandline="/usr/bin/krita")],
        )

        assert _validate("Krita", "krita", "{0}", "Krita") is None

    def test_a_blank_command_is_rejected(self):
        assert _validate("Krita", "  ", "{0}", None) is not None

    def test_a_whole_command_line_pasted_into_the_program_field_gets_its_own_message(self, monkeypatch):
        """direflail pasted "flatpak run org.kde.krita" whole into this
        field during task #166's follow-up; a generic "not found" would
        not have told them what to do about it. The specific message is
        keyed off the space, so this test asserts the two messages differ
        rather than matching translated text.
        """
        monkeypatch.setattr(shutil, "which", lambda name: None)

        with_space = _validate("Krita", "flatpak run org.kde.krita", "{0}", None)
        without_space = _validate("Krita", "definitely-not-a-real-program", "{0}", None)

        assert with_space is not None
        assert without_space is not None
        assert with_space != without_space

    def test_an_unparseable_argument_template_is_rejected(self, monkeypatch):
        monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/krita")

        assert _validate("Krita", "krita", '--comment "unclosed', None) is not None

    @pytest.mark.parametrize(
        "template,error",
        [
            ("{nope}", KeyError),       # a named placeholder
            ("{1}", IndexError),        # an index past the single argument
            ("{0:>{1}}", IndexError),   # a nested width referring to a second argument
        ],
    )
    def test_a_placeholder_the_validator_does_not_catch_escapes_as_an_exception(
        self, monkeypatch, template, error
    ):
        """BACKLOG #221 - a real defect, pinned as observed rather than
        fixed here.

        _validate exists to turn a bad Arguments field into a message.
        It runs token.format("") to find out, but catches only
        ValueError, and str.format raises KeyError for a named
        placeholder and IndexError for an out-of-range one. Those escape
        the validator, so an ordinary typo in Preferences -> Destinations
        -> a command's Arguments field reaches the caller as an unhandled
        exception instead of the message the user should see.

        Asserting the exception rather than a return value is deliberate:
        this test should FAIL when the defect is fixed, which is what
        makes it a reminder rather than a blessing of the bug.
        """
        monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/krita")

        with pytest.raises(error):
            _validate("Krita", "krita", template, None)

    @pytest.mark.parametrize("template", ["{0", "{0!z}"])
    def test_a_malformed_template_the_validator_does_catch_becomes_a_message(self, monkeypatch, template):
        """The ValueError half, which works as intended - an unclosed
        brace and an unknown conversion specifier both come back as text.
        """
        monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/krita")

        assert _validate("Krita", "krita", template, None) is not None

    def test_valid_fields_produce_no_error(self, monkeypatch):
        monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/krita")

        assert _validate("Krita", "krita", "{0}", None) is None

    def test_a_real_file_path_is_accepted_even_when_not_on_path(self, monkeypatch, tmp_path):
        monkeypatch.setattr(shutil, "which", lambda name: None)
        program = tmp_path / "my-editor"
        program.write_text("#!/bin/sh\n")

        assert _validate("Mine", str(program), "{0}", None) is None


class TestSearchInstalledApps:
    APPS = [
        InstalledApp(name="Krita", source="snap", commandline="/snap/bin/krita", argument="{0}"),
        InstalledApp(name="GIMP", source="flatpak", commandline="/usr/bin/flatpak", argument="run org.gimp.GIMP {0}"),
        InstalledApp(name="Text Editor", source="native", commandline="/usr/bin/gedit", argument="{0}"),
    ]

    def test_an_empty_query_returns_every_app(self):
        """direflail's revised spec after live-testing: a blank list did
        not make it obvious what Find App was for.
        """
        assert search_installed_apps("", self.APPS) == self.APPS

    def test_a_whitespace_only_query_returns_every_app(self):
        assert search_installed_apps("   ", self.APPS) == self.APPS

    def test_the_search_is_case_insensitive(self):
        assert search_installed_apps("krita", self.APPS) == [self.APPS[0]]
        assert search_installed_apps("KRITA", self.APPS) == [self.APPS[0]]

    def test_it_matches_a_substring_of_the_name(self):
        assert search_installed_apps("edit", self.APPS) == [self.APPS[2]]

    def test_it_matches_the_argument_so_a_flatpak_app_id_is_findable(self):
        """A Flatpak app's own id lives in the argument, not the
        commandline, which is /usr/bin/flatpak for all of them.
        """
        assert search_installed_apps("org.gimp", self.APPS) == [self.APPS[1]]

    def test_it_matches_the_commandline(self):
        assert search_installed_apps("/snap/bin", self.APPS) == [self.APPS[0]]

    def test_no_match_returns_nothing(self):
        assert search_installed_apps("inkscape", self.APPS) == []

    def test_the_caller_s_list_is_not_returned_by_reference_for_an_empty_query(self):
        result = search_installed_apps("", self.APPS)

        result.append(InstalledApp(name="X", source="native", commandline="x", argument=""))

        assert len(self.APPS) == 3


class TestIsNewerIgnoringBadVersions:
    @pytest.mark.parametrize(
        "candidate,current,expected",
        [
            ("5.2.0", "5.1.0", True),
            ("5.1.0", "5.2.0", False),
            ("5.1.0", "5.1.0", False),
            ("5.10.0", "5.9.0", True),
        ],
    )
    def test_it_compares_ordinary_versions(self, candidate, current, expected):
        assert _is_newer_ignoring_bad_versions(candidate, current) is expected
