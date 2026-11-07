"""
Swedish domain terms an English answer keeps in Swedish, each with the English explanation it gets on first use
(PCR-0006). A term with no entry stays in Swedish without explanation.
"""

# Term (lower case, as the sources write it) -> one-line English explanation
GLOSSARY: dict[str, str] = {}


def glossary_prompt() -> str:
    """The glossary as a block for an answer prompt: one line per term, "<term>: <explanation>", in GLOSSARY's order,
    under one line telling the model to keep the term in Swedish and explain it on first use in an English answer.
    Returns "" when GLOSSARY is empty."""
    raise NotImplementedError
