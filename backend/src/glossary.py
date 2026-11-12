"""
Swedish domain terms an English answer keeps in Swedish, each with the English explanation it gets on first use
(PCR-0006). A term with no entry stays in Swedish without explanation.
"""

import re

# Term (lower case, as the sources write it) -> one-line English explanation
GLOSSARY: dict[str, str] = {
    "detaljplan": "detailed development plan: the kommun's binding plan for what may be built where",
    "översiktsplan": "comprehensive plan: the kommun's non-binding plan for its whole area",
    "områdesbestämmelser": "area regulations: a lighter binding plan for an area without a detaljplan",
    "plankarta": "plan map: the map of a detaljplan, with its zones and regulations",
    "planbeskrivning": "plan description: the text explaining a detaljplan's purpose and regulations",
    "planbestämmelse": "plan regulation: one binding rule of a detaljplan",
    "planbesked": "planning notice: the kommun's answer on whether it will start a detaljplan",
    "bygglov": "building permit",
    "rivningslov": "demolition permit",
    "marklov": "site works permit, e.g. for changing ground levels or felling trees",
    "förhandsbesked": "advance ruling: whether a building may be placed on a site, before a bygglov is sought",
    "anmälan": "notification: the procedure for minor works that need no bygglov but a start notice",
    "startbesked": "start notice: the kommun's go-ahead before building work may begin",
    "slutbesked": "completion certificate: the kommun's approval before a building may be used",
    "strandskydd": "shoreline protection: a ban on building within (usually) 100 m of a lake, river or sea",
    "dispens": "exemption from a protection rule, such as strandskydd",
    "byggnadsarea": "building area: the footprint a building covers on the ground",
    "bruttoarea": "gross floor area",
    "komplementbyggnad": "ancillary building, such as a garage, shed or guest house",
    "attefallshus": "small dwelling of up to 30 m2 that needs only a notification, not a bygglov",
    "friggebod": "small outbuilding of up to 15 m2 that needs no bygglov",
    "nockhöjd": "ridge height: the height to the top of the roof",
    "byggnadshöjd": "building height, measured to the wall's top as the regulations define it",
    "prickmark": "land that may not be built on (dotted on the plan map)",
    "fastighetsbeteckning": "property designation, e.g. Uppsala Kungsängen 7:8",
    "fastighetsbildning": "property formation: dividing, merging or adjusting properties",
    "avstyckning": "subdivision: forming a new property from part of an existing one",
    "enskilt avlopp": "private sewage system, not connected to the municipal network",
    "riksintresse": "national interest: an area of national importance the decision must not significantly harm",
    "fornlämning": "ancient remain protected by the kulturmiljölag",
    "samråd": "consultation: the stage where a draft plan is shown for comments",
    "granskning": "review: the stage where a revised plan is shown before adoption",
}


def glossary_prompt() -> str:
    """The glossary as a block for an answer prompt: one line per term, "<term>: <explanation>", in GLOSSARY's order,
    under one line telling the model to keep the term in Swedish and explain it on first use in an English answer.
    Returns "" when GLOSSARY is empty."""
    if not GLOSSARY:
        return ""
    lines = [f"{term}: {explanation}" for term, explanation in GLOSSARY.items()]
    return ("Swedish terms: in an English answer, keep these terms in Swedish and give the English explanation on "
            "first use, e.g. \"bygglov (building permit)\"; a Swedish term not listed stays in Swedish without one.\n"
            + "\n".join(lines))


def explained(text: str) -> str:
    """`text` with each glossary term's English explanation in parentheses after its first use, for an English text
    the code writes (PCR-0006). A term already followed by a parenthesis keeps it; matching ignores case and takes
    whole words only, so "strandskyddsdispens" does not match "strandskydd"."""
    firsts = []
    for term in sorted(GLOSSARY, key=len, reverse=True):
        match = re.search(rf"(?<!\w){re.escape(term)}(?!\w)", text, re.IGNORECASE)
        if not match or text[match.end():].startswith(" ("):
            continue
        if any(start < match.end() and match.start() < end for start, end, _ in firsts):
            continue
        firsts.append((match.start(), match.end(), GLOSSARY[term]))
    for _, end, explanation in sorted(firsts, reverse=True):
        text = f"{text[:end]} ({explanation}){text[end:]}"
    return text
