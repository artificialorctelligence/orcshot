from orcshot.i18n import _


class TestFallbackTranslation:
    def test_returns_the_argument_unchanged_when_no_catalog_is_installed(self):
        assert _("Preferences") == "Preferences"

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
