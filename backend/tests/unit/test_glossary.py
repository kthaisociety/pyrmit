"""Unit tests for glossary: the Swedish terms an English answer keeps, and the block the answer prompts carry."""

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
