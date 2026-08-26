from orcshot.i18n import _, ngettext


class TestFallbackTranslation:
    def test_returns_the_argument_unchanged_when_no_catalog_is_installed(self):
        assert _("Preferences") == "Preferences"

    def test_ngettext_picks_the_singular_form_with_no_catalog_installed(self):
        assert ngettext("{} match", "{} matches", 1) == "{} match"

    def test_ngettext_picks_the_plural_form_with_no_catalog_installed(self):
        assert ngettext("{} match", "{} matches", 2) == "{} matches"

    def test_falls_back_when_the_catalog_file_exists_but_cannot_be_read(self, tmp_path):
        import os
        import subprocess

        from orcshot.i18n import _load_translation

        locale_dir = tmp_path / "locale"
        mo_dir = locale_dir / "fr" / "LC_MESSAGES"
        mo_dir.mkdir(parents=True)
        po_path = tmp_path / "orcshot.po"
        po_path.write_text(
            'msgid ""\n'
            'msgstr "Content-Type: text/plain; charset=UTF-8\\n"\n'
            "\n"
            'msgid "Preferences"\n'
            'msgstr "Préférences"\n'
        )
        mo_path = mo_dir / "orcshot.mo"
        subprocess.run(["msgfmt", str(po_path), "-o", str(mo_path)], check=True)
        os.chmod(mo_path, 0o000)

        try:
            translation = _load_translation("orcshot", locale_dir, languages=["fr"])
            assert translation.gettext("Preferences") == "Preferences"
        finally:
            os.chmod(mo_path, 0o644)

    def test_resolve_languages_returns_none_to_follow_system_locale_by_default(self, monkeypatch):
        import orcshot.i18n

        monkeypatch.setattr(orcshot.i18n, "get_language", lambda: "")
        assert orcshot.i18n._resolve_languages() is None

    def test_resolve_languages_honors_a_real_override(self, monkeypatch):
        import orcshot.i18n

        monkeypatch.setattr(orcshot.i18n, "get_language", lambda: "es")
        assert orcshot.i18n._resolve_languages() == ["es"]

    def test_a_real_catalog_actually_substitutes(self, tmp_path):
        import gettext as gettext_module

        locale_dir = tmp_path / "locale"
        mo_dir = locale_dir / "fr" / "LC_MESSAGES"
        mo_dir.mkdir(parents=True)
        po_source = (
            'msgid ""\n'
            'msgstr "Content-Type: text/plain; charset=UTF-8\\n"\n'
            "\n"
            'msgid "Preferences"\n'
            'msgstr "Préférences"\n'
        )
        po_path = tmp_path / "orcshot.po"
        po_path.write_text(po_source)
        import subprocess

        subprocess.run(
            ["msgfmt", str(po_path), "-o", str(mo_dir / "orcshot.mo")], check=True,
        )
        translation = gettext_module.translation(
            "orcshot", localedir=str(locale_dir), languages=["fr"], fallback=True,
        )
        assert translation.gettext("Preferences") == "Préférences"
