"""The pinned place as the chat sees it: the place profile written out for the agent, before the user's question,
and a compact copy for the answer's pipeline trace (where the chat session keeps its place, ADR-0004)."""

import re
from collections.abc import Callable

from place.sources import PILOTS

NO_PIN_HINT = ("(No place is pinned on the map. A question about one specific place needs a pin: ask with ask_user and "
               "offer_pin before any search. Answer a general question with the search tools and offer to pin a place "
               "for an exact answer.)")

OPENING = ("[Place pinned by the user on the map. This is the place the question is about: do not ask where it is, "
           "and do not call find_kommun: the kommun and its code are given below. "
           "If the question names a different place than this one, ask the user which one they mean before "
           "answering. A general question, which does not turn on this place, is answered generally.]")
CLOSING = ("[End of the pinned place. The user's question follows. If it names an address, property or place that is "
           "not this pinned one (compare with the property and its addresses above), ask which place the user means "
           "with ask_user, the pinned place and the named one as options, before answering, unless the "
           "conversation has already settled it: then follow the user's choice (for a place other than the pin, "
           "answer without the pin's data) and do not ask again.]")
MAX_ADDRESSES = 8
# The user clicked one of the agent's options (or pinned from its button): asked again, the pinned-place rule made
# the agent repeat its question in 13 of 15 follow-ups (2026-10-25)
ANSWERED = ("[The user's message below is their answer to your question: act on it now and do not ask again. If they "
            "chose a place other than the pinned place, answer for that place and leave the pinned place's data aside.]")
STATUTES = ("[Statute text of the sections the likely permits cite, from the corpus: cite these ids; no need to look "
            "them up again.]")
# "MB 7 kap. 7 §", "MB 7 kap. 21-22 §", "MB 7 kap. 28 a §", "3 kap. 6 § MB": a law, a chapter and its sections
_SECTION_REF = re.compile(r"(?:(?P<before>[A-ZÅÄÖ]{2,4})\s+)?(?P<chapter>\d+)\s*kap\.\s*(?P<first>\d+)(?:\s*(?P<letter>[a-z])\b)?"
                          r"(?:\s*-\s*(?P<last>\d+))?\s*§(?:\s+(?P<after>[A-ZÅÄÖ]{2,4}))?")
PLAN_TYPES = {"plan_addition": "Tillägg", "area_regulations": "Områdesbestämmelser"}  # any other plan: "Detaljplan"
DETALJPLAN = {"inside": "inside a detaljplan", "outside": "outside any detaljplan (the kommun's plan map is complete)",
              "unknown": "no digital detaljplan found, an older plan may apply (ask the kommun)"}
UNAVAILABLE = "not checked (the source could not be reached)"


def _documents(documents: list[dict]) -> str:
    return "; ".join(f"{document['role'] or document['title']} {document['doc_id']}" for document in documents)


def _plan(plan: dict) -> str:
    """One plan at the pin: its type, name and date, then its documents and the call that reads them (with those of the
    plans it is read together with), or that its text is not read and the kommun's link."""
    kind = PLAN_TYPES.get(plan["kind"], "Detaljplan")
    line = f"- {kind} {plan['ref']} \"{plan['name']}\", laga kraft {plan['date'] or 'unknown'}."
    documents = plan.get("corpus_documents") or []
    read_with = plan.get("read_with") or []
    if documents:
        line += f" Documents: {_documents(documents)}."
    else:
        link = plan.get("url") or plan.get("page")
        line += f" Text not read; the kommun's page: {link}." if link else " Text not read; no link to it is known."
    if read_with:
        named = ", ".join(other["ref"] if other["corpus_documents"] else f"{other['ref']} (text not read)"
                          for other in read_with)
        line += f" Read together with {named}"
        line += "." if not any(other["corpus_documents"] for other in read_with) else ""
    doc_ids = [document["doc_id"] for source in (plan, *read_with) for document in source.get("corpus_documents") or []]
    if doc_ids:
        line += f"{':' if read_with and line[-1] != '.' else ''} read_plan(doc_ids={doc_ids})."
    if plan.get("provisions_indexed"):
        line += f" Provisions: plan_rules('{plan['corpus_plan_id']}')."
    return line


def _zone(zone: dict) -> str:
    share = f" ({round(zone['share'] * 100)} % of the property)" if zone.get("share") is not None else ""
    return f"- {zone['ref']}: {zone['name']}{share}"


def _protected(area: dict) -> str:
    decided = f", decided by {area['authority']}" if area.get("authority") else ""
    return f"- {area['type']} \"{area['name']}\"{decided}{', ' + area['date'] if area.get('date') else ''}"


def _section(title: str, rows: list[str], status: str) -> list[str]:
    if status == "unavailable":
        return [f"{title}: {UNAVAILABLE}."]
    return [f"{title}:", *rows] if rows else [f"{title}: none found."]


def _addresses(found: dict | None) -> str:
    """"; addresses on it: Kungsgatan 63A, Kungsgatan 63B" (at most MAX_ADDRESSES), or "" when none are known."""
    addresses = (found or {}).get("addresses") or []
    if not addresses:
        return ""
    more = len(addresses) - MAX_ADDRESSES
    return "; addresses on it: " + ", ".join(addresses[:MAX_ADDRESSES]) + (f" and {more} more" if more > 0 else "")


def permit_sections(profile: dict) -> list[tuple[str, str]]:
    """The statute sections the profile's likely permits cite, as (law, section) for the agent's law_section tool:
    [("MB", "7 kap. 7 §"), ("KML", "2 kap. 12 §"), ...], in card order, each once. A range ("21-22 §") gives each
    section; a chapter without a section ("PBL 9 kap.") is left out."""
    sections = []
    for permit in profile.get("permits") or []:
        for ref in _SECTION_REF.finditer(permit.get("law") or ""):
            law = ref["before"] or ref["after"]
            if not law:
                continue
            last = int(ref["last"]) if ref["last"] and not ref["letter"] else int(ref["first"])
            for number in range(int(ref["first"]), last + 1):
                section = f"{ref['chapter']} kap. {number}{' ' + ref['letter'] if ref['letter'] else ''} §"
                if (law, section) not in sections:
                    sections.append((law, section))
    return sections


def _statutes(profile: dict, law_text: Callable[[str, str], str | None] | None) -> list[str]:
    if law_text is None:
        return []
    texts = [text for law, section in permit_sections(profile) if (text := law_text(law, section))]
    return [STATUTES, *texts] if texts else []


def _permit(permit: dict) -> str:
    kind = "Consideration" if permit["kind"] == "consideration" else "Permit"
    return f"- {kind}: {permit['title']} ({permit['law']}; {permit['authority']}). {permit['reason']}"


def place_context(profile: dict, law_text: Callable[[str, str], str | None] | None = None) -> str:
    """The place profile as a block of English text that goes before the user's question: the pinned point, the
    property and kommun, inside or outside a detaljplan, each plan in force (aktbeteckning, name, laga kraft date),
    the land-use zones, the plans in progress, the protected areas, Natura 2000 sites, national interests and
    ancient remains, the strandskydd note and the likely permits, under the note that it is registry data, not a
    decision. The property line names its addresses when the property lookup found them, and the kommun line its
    code. With `law_text` ((law, section) -> the section's text tagged [c:<chunk id>], or None), the text of the
    sections the permits cite follows (permit_sections): the benchmark of 2026-10-25 found pinned answers spending
    ~10 law_section calls on exactly these. It tells the agent that this
    is the place the question is about (so it does not ask where), and, first and again right before the question, to
    ask which place is meant when the question names a different one: the benchmark of 2026-10-25 found the agent
    answering for the pinned place in 2 of 5 such questions, unable to tell that the named address lay elsewhere. An
    uncovered place says the map does not cover it."""
    point = f"{profile['point']['lat']:.5f}, {profile['point']['lon']:.5f}"
    if not profile["covered"]:
        pilots = ", ".join(pilot["name"] for pilot in PILOTS.values())
        return (f"[Place pinned by the user on the map at {point}. The map does not cover this place yet (pilot "
                f"kommuner: {pilots}), so no registry data is known for it: answer from the question and the corpus.]")
    status = profile["section_status"]
    kommun = f"{profile['kommun']['name']} kommun, kommun code {profile['kommun']['code']}"
    property_line = {
        "found": f"Property: {profile['property']['designation'] if profile['property'] else ''} "
                 f"({kommun}){_addresses(profile['property'])}.",
        "none": f"Property: none at the pin (a street, park or water in {kommun}).",
        "unavailable": f"Property: unknown (the property service did not answer), {kommun}.",
    }[profile["property_status"]]
    lines = [
        OPENING, f"Pin: {point}.", property_line, f"Detaljplan: {DETALJPLAN[profile['detaljplan']]}.",
        *_section("Plans in force (newest first)", [_plan(plan) for plan in profile["plans"]], "ok"),
        *_section("Land-use zones on the property (the kommun's interpreted boundaries)",
                  [_zone(zone) for zone in profile["zones"]], "ok"),
        *_section("Plans in progress (not binding)",
                  [f"- \"{plan['name']}\" ({plan['status']})" for plan in profile["pending_plans"]], "ok"),
        *_section("Protected areas", [_protected(area) for area in profile["protected_areas"]],
                  status["protected_areas"]),
        *_section("Natura 2000 sites", [f"- {site['ref']} \"{site['name']}\"" for site in profile["natura2000"]],
                  status["natura2000"]),
        *_section("National interests (riksintressen)",
                  [f"- {item['type']} \"{item['name']}\" ({item['law']})" for item in profile["national_interests"]],
                  status["national_interests"]),
        *_section("Ancient remains on the property",
                  [f"- {item['ref']} {item['type']} ({item['status']})" for item in profile["ancient_remains"]],
                  status["ancient_remains"]),
        f"Strandskydd: {profile['strandskydd']['reason']} {profile['strandskydd']['note']}",
        *_section("Likely permits (fixed rules from the registers)", [_permit(p) for p in profile["permits"]], "ok"),
        *profile["notes"], *_statutes(profile, law_text), CLOSING,
    ]
    return "\n".join(lines)


def question_with_place(question: str, profile: dict | None,
                        law_text: Callable[[str, str], str | None] | None = None, answered: bool = False) -> str:
    """The question as the agent gets it: after the pinned place's profile (place_context, with the permits' statute
    text when `law_text` is given), or after NO_PIN_HINT when nothing is pinned; with `answered` (the message answers
    the agent's own question) ANSWERED comes last before it. The chat and the answer benchmark
    (place.bench_answers) both send this."""
    parts = [place_context(profile, law_text) if profile else NO_PIN_HINT, *([ANSWERED] if answered else []), question]
    return "\n\n".join(parts)


def _without_geometry(row: dict | None) -> dict | None:
    return {key: value for key, value in row.items() if key != "geometry"} if row else row


def compact_profile(profile: dict) -> dict:
    """The profile without any geometry (the property's and every row's), to keep the pipeline trace small."""
    compact = {}
    for key, value in profile.items():
        if key == "property":
            compact[key] = _without_geometry(value)
        elif isinstance(value, list):
            compact[key] = [_without_geometry(row) if isinstance(row, dict) else row for row in value]
        else:
            compact[key] = value
    return compact
