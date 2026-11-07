"""Unit tests for answer_language: reading the rewrite call's LANG line, and the rule the answer prompts carry."""

from answer_language import (
    LANGUAGE_RULE,
    REWRITE_LANGUAGE_SUFFIX,
    parse_language,
    split_language,
)

REWRITE = "Do I need a building permit for a small shed on my plot?"


def test_a_swedish_lang_line_gives_swedish():
    assert parse_language(f"{REWRITE}\nLANG: sv") == "sv"


def test_an_english_lang_line_gives_english():
    assert parse_language(f"{REWRITE}\nLANG: en") == "en"


def test_the_lang_line_is_read_case_insensitively():
    assert parse_language(f"{REWRITE}\nlang: SV") == "sv"


def test_a_missing_lang_line_gives_english():
    assert parse_language(REWRITE) == "en"


def test_a_lang_line_naming_another_language_gives_english():
    assert parse_language(f"{REWRITE}\nLANG: de") == "en"


def test_an_empty_rewrite_output_gives_english():
    assert parse_language("") == "en"


def test_split_language_removes_only_the_lang_line():
    """The SV search line of the local backend's rewrite stays."""
    output = f"{REWRITE}\nSV: bygglov friggebod tomt\nLANG: sv"
    assert split_language(output) == (f"{REWRITE}\nSV: bygglov friggebod tomt", "sv")


def test_the_rewrite_suffix_asks_for_a_lang_line():
    assert "LANG:" in REWRITE_LANGUAGE_SUFFIX


def test_the_language_rule_asks_for_swedish_quotes_verbatim():
    assert "verbatim" in LANGUAGE_RULE
