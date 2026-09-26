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

from orcshot.i18n import _
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
        "template",
        [
            "{nope}",      # a named placeholder
            "{1}",         # an index past the single argument
            "{0:>{1}}",    # a nested width referring to a second argument
        ],
    )
    def test_a_placeholder_the_format_call_cannot_satisfy_becomes_a_message(self, monkeypatch, template):
        """BACKLOG #221, fixed 2026-09-26.

        _validate exists to turn a bad Arguments field into a message. It
        runs token.format("") to find out, and used to catch ValueError
        alone - but str.format raises KeyError for a named placeholder and
        IndexError for an out-of-range one, so those escaped the validator
        and an ordinary typo in Preferences -> Destinations -> Arguments
        reached the caller as an unhandled exception instead.

        This test previously asserted the exception, deliberately, so that
        it would fail when the defect was fixed. It has.
        """
        monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/krita")

        assert _validate("Krita", "krita", template, None) is not None

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


class TestValidateMessages:
    """_validate's whole job is to produce *the right message* - the
    caller only ever shows it (show_command_detail_dialog's revalidate
    puts it straight in the dialog's error label). A test that asserts
    "not None" proves the field was rejected and nothing about whether
    the user was told something they can act on, which is how five
    distinct messages could be swapped for each other unnoticed
    (BACKLOG #220, task 9).

    Each message is compared against _() of the same msgid rather than
    against raw English, so the assertion holds under a translated
    locale and still fails if the msgid in the source changes.
    """

    @pytest.fixture(autouse=True)
    def no_existing_commands(self, monkeypatch):
        monkeypatch.setattr("orcshot.ui.external_commands.get_external_commands", lambda: [])

    def test_a_blank_name_says_the_name_is_required(self):
        assert _validate("   ", "/usr/bin/krita", "{0}", None) == _("Name is required.")

    def test_a_duplicate_name_says_the_name_is_taken(self, monkeypatch):
        monkeypatch.setattr(
            "orcshot.ui.external_commands.get_external_commands",
            lambda: [ExternalCommand(name="Krita", commandline="/usr/bin/krita")],
        )

        assert _validate("Krita", "/usr/bin/krita", "{0}", None) == _(
            "A command with this name already exists."
        )

    def test_a_blank_command_says_the_command_is_required(self):
        assert _validate("Krita", "  ", "{0}", None) == _("Command is required.")

    def test_a_pasted_command_line_says_to_split_it(self, monkeypatch):
        """direflail pasted "flatpak run org.kde.krita" whole into the
        program field during task #166's follow-up. The generic "not
        found" below does not tell them what to do about it; this one
        does, and the two must not be swapped."""
        monkeypatch.setattr(shutil, "which", lambda name: None)

        assert _validate("Krita", "flatpak run org.kde.krita", "{0}", None) == _(
            "This looks like a full command line - put just the program name here, and the rest in Arguments."
        )

    def test_a_missing_program_without_a_space_says_it_was_not_found(self, monkeypatch):
        monkeypatch.setattr(shutil, "which", lambda name: None)

        assert _validate("Krita", "definitely-not-a-real-program", "{0}", None) == _(
            "Command not found - check the path, or that it's on your PATH."
        )

    def test_the_program_field_is_what_gets_looked_up_on_path(self, tmp_path, monkeypatch):
        """shutil.which is deliberately *not* faked here: the point is
        that the value looked up is the commandline the user typed. A
        non-executable file is not on $PATH and which() will not find it,
        so this exercises the is_file() fallback for a real absolute
        path - the "I browsed to my own script" case.
        """
        program = tmp_path / "my-editor"
        program.write_text("#!/bin/sh\nexit 0\n")
        monkeypatch.setattr("orcshot.ui.external_commands.get_external_commands", lambda: [])

        assert shutil.which(str(program)) is None
        assert _validate("Mine", str(program), "{0}", None) is None

    def test_an_argument_error_carries_the_reason_the_format_call_gave(self, monkeypatch):
        """"Invalid arguments:" alone does not tell the user which brace
        is wrong; the exception's own text is the actionable half."""
        monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/krita")

        message = _validate("Krita", "krita", "{nope}", None)

        assert message.startswith(_("Invalid arguments: "))
        assert "nope" in message

    def test_a_placeholder_that_indexes_into_the_path_is_rejected(self, monkeypatch):
        """Pins the probe value, which is surprising and worth knowing:
        _validate asks whether the template can be formatted by running
        token.format("") - an *empty* string. So "{0[0]}" fails
        validation with "string index out of range" even though at run
        time build_command_argv substitutes a real path, where it would
        have yielded that path's first character. The empty probe is what
        makes the validator conservative; documented here rather than
        changed (BACKLOG #220's constraint on src/ behaviour).
        """
        monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/krita")

        message = _validate("Krita", "krita", "{0[0]}", None)

        assert message is not None
        assert message.startswith(_("Invalid arguments: "))


class TestSearchMatchesEachFieldOnItsOwn:
    """The existing search tests all use queries that happen to appear in
    more than one field ("krita" is in both the name and
    /snap/bin/krita), so any one of the three comparisons could stop
    working unnoticed. These use a query that appears in exactly one
    field.
    """

    NAME_ONLY = InstalledApp(
        name="Inkscape", source="native", commandline="/usr/bin/vector-draw", argument="--file {0}"
    )
    COMMANDLINE_ONLY = InstalledApp(
        name="Vector Editor", source="native", commandline="/opt/inkview/bin/run", argument="{0}"
    )
    ARGUMENT_ONLY = InstalledApp(
        name="Drawing", source="flatpak", commandline="flatpak", argument="run org.inkscape.Inkscape {0}"
    )

    def test_a_query_matching_only_the_name_still_matches(self):
        """The name is stored with its real capitalisation ("Inkscape",
        from the .desktop file's Name=) and the query is lower-cased, so
        the name has to be lower-cased too."""
        apps = [self.NAME_ONLY, self.COMMANDLINE_ONLY]

        assert search_installed_apps("inkscape", apps) == [self.NAME_ONLY]

    def test_a_query_matching_only_the_commandline_still_matches(self):
        apps = [self.NAME_ONLY, self.COMMANDLINE_ONLY]

        assert search_installed_apps("inkview", apps) == [self.COMMANDLINE_ONLY]

    def test_a_query_matching_only_the_argument_still_matches(self):
        apps = [self.COMMANDLINE_ONLY, self.ARGUMENT_ONLY]

        assert search_installed_apps("org.inkscape", apps) == [self.ARGUMENT_ONLY]


class TestIsNewerIgnoringUnparseableVersions:
    """The reason this wrapper exists at all: Snap and Flatpak version
    strings are free-form. `flatpak list` reports a branch name ("stable")
    or nothing for plenty of apps, and parse_version strips non-numerics
    and then int()s what is left, so those raise ValueError. A wrapper
    that answered True on a ValueError would make the unparseable side
    win the Snap-vs-Flatpak tie-break every time.
    """

    @pytest.mark.parametrize("candidate,current", [("stable", "5.2.0"), ("", "5.2.0"), ("5.2.0", "stable")])
    def test_an_unparseable_version_never_wins(self, candidate, current):
        assert _is_newer_ignoring_bad_versions(candidate, current) is False
