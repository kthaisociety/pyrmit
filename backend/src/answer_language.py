"""
The language of an answer (PCR-0006): the question's language, Swedish or English, English for any other language.

The model decides it. Every answer prompt carries LANGUAGE_RULE; the chat's rewrite call, which runs before any answer,
also writes the decision as a `LANG:` line (REWRITE_LANGUAGE_SUFFIX), so the answers the code writes itself (the
feasibility template, the clarifying prompt) follow it too. No path hardcodes an answer language.
"""

import re
from typing import Literal

Language = Literal["sv", "en"]

# The rule every answer prompt carries: which language to answer in, and how Swedish sources are quoted in it
LANGUAGE_RULE = """Answer language: write the whole answer, its headings and any question to the user in the language of the user's own message, Swedish or English; a message in any other language is answered in English. Decide it from the user's own words only, never from the place context, the sources or the tool results, which are in English or Swedish whatever the user writes. When the message alone does not settle it (a one-word reply such as "ja", a lone place name or domain term, a sentence mixing both): Swedish if the user's earlier messages were in Swedish, else Swedish if most of its words are Swedish, else English.
Quotes: quote Swedish sources verbatim, in their original Swedish wording; never paraphrase, shorten or translate a quote and leave its original out. In an English answer, follow each Swedish quote with its English translation in parentheses, e.g. "Bygglov krävs för nybyggnad" ("A building permit is required for new construction"). In a Swedish answer, quote in Swedish only."""

# Appended to the chat's rewrite prompt: one more line, "LANG: sv" or "LANG: en", decided by LANGUAGE_RULE's order
REWRITE_LANGUAGE_SUFFIX = (
    "Finally, on a last line of its own, write 'LANG: sv' when the answer must be in Swedish and 'LANG: en' when it "
    "must be in English: the language of the latest user message, Swedish or English (any other language: en). When "
    "that message alone does not settle it (a one-word reply, a lone place name or term, a mixed sentence): sv if the "
    "earlier user messages were in Swedish, else sv if most of its words are Swedish, else en."
)

_LANG_LINE = re.compile(r"\s*\bLANG\s*:\s*([A-Za-z-]*)\s*$", re.IGNORECASE)


def split_language(output: str) -> tuple[str, Language]:
    """Split a rewrite call's output into (the output without its `LANG:` line, the language that line names).

    The line may stand anywhere in the output and its value is read case-insensitively. A missing line, or one naming
    anything but sv or en, gives "en", and the output comes back unchanged apart from that line. Never raises.
    """
    language: Language = "en"
    kept = []
    for line in (output or "").split("\n"):
        match = _LANG_LINE.search(line)
        if not match:
            kept.append(line)
            continue
        value = match.group(1).lower()
        language = "sv" if value == "sv" else "en"
        text_before_lang = line[:match.start()]
        if text_before_lang.strip():
            kept.append(text_before_lang)
    return "\n".join(kept), language


def parse_language(output: str) -> Language:
    """The language a rewrite call's `LANG:` line names: split_language(output)[1]."""
    return split_language(output)[1]
