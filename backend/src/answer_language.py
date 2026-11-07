"""
The language of an answer (PCR-0006): the question's language, Swedish or English, English for any other language.

The model decides it. Every answer prompt carries LANGUAGE_RULE; the chat's rewrite call, which runs before any answer,
also writes the decision as a `LANG:` line (REWRITE_LANGUAGE_SUFFIX), so the answers the code writes itself (the
feasibility template, the clarifying prompt) follow it too. No path hardcodes an answer language.
"""

from typing import Literal

Language = Literal["sv", "en"]

# The rule every answer prompt carries: which language to answer in, and how Swedish sources are quoted in it
LANGUAGE_RULE = ""

# Appended to the chat's rewrite prompt: one more line, "LANG: sv" or "LANG: en", decided by LANGUAGE_RULE's order
REWRITE_LANGUAGE_SUFFIX = ""


def split_language(output: str) -> tuple[str, Language]:
    """Split a rewrite call's output into (the output without its `LANG:` line, the language that line names).

    The line may stand anywhere in the output and its value is read case-insensitively. A missing line, or one naming
    anything but sv or en, gives "en", and the output comes back unchanged apart from that line. Never raises.
    """
    raise NotImplementedError


def parse_language(output: str) -> Language:
    """The language a rewrite call's `LANG:` line names: split_language(output)[1]."""
    raise NotImplementedError
