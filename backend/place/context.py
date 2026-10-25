"""The pinned place as the chat sees it: the place profile written out for the agent, before the user's question,
and a compact copy for the answer's pipeline trace (where the chat session keeps its place, ADR-0004)."""

NO_PIN_HINT = ("(No place is pinned on the map. If the answer depends on one specific property and the place is "
               "unclear, suggest that the user pins it on the map in the chat.)")


def place_context(profile: dict) -> str:
    """The place profile as a block of English text that goes before the user's question: the pinned point, the
    property and kommun, inside or outside a detaljplan, each plan in force (aktbeteckning, name, laga kraft date),
    the land-use zones, the plans in progress, the protected areas, Natura 2000 sites, national interests and
    ancient remains, the strandskydd note and the likely permits, under the note that it is registry data, not a
    decision. It tells the agent that this is the place the question is about (so it does not ask where), and to ask
    which place is meant when the question names a different one. An uncovered place says the map does not cover it."""
    raise NotImplementedError


def compact_profile(profile: dict) -> dict:
    """The profile without any geometry (the property's and every row's), to keep the pipeline trace small."""
    raise NotImplementedError
