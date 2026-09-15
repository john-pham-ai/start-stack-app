"""Guards for the translation table itself."""

from translations import TRANSLATIONS, t


class TestTranslations:
    def test_every_key_has_both_languages(self):
        for key, entry in TRANSLATIONS.items():
            assert set(entry) == {"en", "ja"}, f"{key} has languages {sorted(entry)}"

    def test_unknown_language_falls_back_to_english(self):
        assert t("fr", "quit") == TRANSLATIONS["quit"]["en"]

    def test_format_placeholders_match_between_languages(self):
        import re

        placeholder = re.compile(r"\{(\w+)\}")
        for key, entry in TRANSLATIONS.items():
            keys = {frozenset(placeholder.findall(text)) for text in entry.values()}
            assert len(keys) == 1, f"{key} has mismatched placeholders: {keys}"
