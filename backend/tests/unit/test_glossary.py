"""Unit tests for glossary: the Swedish terms an English text keeps, the block the answer prompts carry, and the
explanations `explained` adds to the code's own English texts."""

import glossary


def test_the_glossary_has_the_core_planning_terms():
    terms = {"detaljplan", "bygglov", "strandskydd", "plankarta", "byggnadsarea", "komplementbyggnad"}
    assert terms <= set(glossary.GLOSSARY)


def test_every_glossary_term_has_an_explanation():
    assert glossary.GLOSSARY and all(explanation.strip() for explanation in glossary.GLOSSARY.values())


def test_the_glossary_prompt_lists_each_term_with_its_explanation():
    block = glossary.glossary_prompt()
    assert glossary.GLOSSARY and all(f"{term}: {text}" in block for term, text in glossary.GLOSSARY.items())


def test_an_empty_glossary_gives_no_prompt(monkeypatch):
    monkeypatch.setattr(glossary, "GLOSSARY", {})
    assert glossary.glossary_prompt() == ""


def test_explained_adds_the_explanation_after_a_term(monkeypatch):
    monkeypatch.setattr(glossary, "GLOSSARY", {"bygglov": "building permit"})
    assert glossary.explained("A bygglov is needed.") == "A bygglov (building permit) is needed."


def test_explained_explains_a_term_only_on_its_first_use(monkeypatch):
    monkeypatch.setattr(glossary, "GLOSSARY", {"bygglov": "building permit"})
    assert glossary.explained("bygglov, then bygglov") == "bygglov (building permit), then bygglov"


def test_explained_keeps_a_parenthesis_already_after_the_term(monkeypatch):
    monkeypatch.setattr(glossary, "GLOSSARY", {"bygglov": "building permit"})
    assert glossary.explained("bygglov (permit)") == "bygglov (permit)"


def test_explained_ignores_case(monkeypatch):
    monkeypatch.setattr(glossary, "GLOSSARY", {"bygglov": "building permit"})
    assert glossary.explained("Bygglov") == "Bygglov (building permit)"


def test_explained_matches_whole_words_only(monkeypatch):
    monkeypatch.setattr(glossary, "GLOSSARY", {"strandskydd": "shoreline protection"})
    assert glossary.explained("A strandskyddsdispens") == "A strandskyddsdispens"


def test_explained_prefers_the_longest_overlapping_term(monkeypatch):
    monkeypatch.setattr(glossary, "GLOSSARY", {"avlopp": "sewage", "enskilt avlopp": "private sewage system"})
    assert glossary.explained("An enskilt avlopp") == "An enskilt avlopp (private sewage system)"
