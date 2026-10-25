"""The pinned place as the chat sees it: the place profile written out for the agent, before the user's question,
and a compact copy for the answer's pipeline trace (where the chat session keeps its place, ADR-0004)."""

from place.sources import PILOTS

NO_PIN_HINT = ("(No place is pinned on the map. If the answer depends on one specific property and the place is "
               "unclear, suggest that the user pins it on the map in the chat.)")

OPENING = ("[Place pinned by the user on the map. This is the place the question is about: do not ask where it is. "
           "If the question names a different place than this one, ask the user which one they mean before "
           "answering.]")
CLOSING = "[End of the pinned place. The user's question follows.]"
DETALJPLAN = {"inside": "inside a detaljplan", "outside": "outside any detaljplan (the kommun's plan map is complete)",
              "unknown": "no digital detaljplan found, an older plan may apply (ask the kommun)"}
UNAVAILABLE = "not checked (the source could not be reached)"


def _plan(plan: dict) -> str:
    kind = {"plan_addition": "Tillägg ", "area_regulations": "Områdesbestämmelser "}.get(plan["kind"], "")
    provisions = (f"provisions in the corpus: plan_rules('{plan['corpus_plan_id']}')" if plan.get("provisions_indexed")
                  else "provisions not indexed")
    documents = f"; documents: {plan['url']}" if plan.get("url") else ""
    return f"- {kind}{plan['ref']} \"{plan['name']}\", laga kraft {plan['date'] or 'unknown'} ({provisions}){documents}"


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


def _permit(permit: dict) -> str:
    kind = "Consideration" if permit["kind"] == "consideration" else "Permit"
    return f"- {kind}: {permit['title']} ({permit['law']}; {permit['authority']}). {permit['reason']}"


def place_context(profile: dict) -> str:
    """The place profile as a block of English text that goes before the user's question: the pinned point, the
    property and kommun, inside or outside a detaljplan, each plan in force (aktbeteckning, name, laga kraft date),
    the land-use zones, the plans in progress, the protected areas, Natura 2000 sites, national interests and
    ancient remains, the strandskydd note and the likely permits, under the note that it is registry data, not a
    decision. It tells the agent that this is the place the question is about (so it does not ask where), and to ask
    which place is meant when the question names a different one. An uncovered place says the map does not cover it."""
    point = f"{profile['point']['lat']:.5f}, {profile['point']['lon']:.5f}"
    if not profile["covered"]:
        pilots = ", ".join(pilot["name"] for pilot in PILOTS.values())
        return (f"[Place pinned by the user on the map at {point}. The map does not cover this place yet (pilot "
                f"kommuner: {pilots}), so no registry data is known for it: answer from the question and the corpus.]")
    status = profile["section_status"]
    property_line = {
        "found": f"Property: {profile['property']['designation'] if profile['property'] else ''} "
                 f"({profile['kommun']['name']} kommun).",
        "none": f"Property: none at the pin (a street, park or water in {profile['kommun']['name']} kommun).",
        "unavailable": f"Property: unknown (the property service did not answer), {profile['kommun']['name']} kommun.",
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
        *profile["notes"], CLOSING,
    ]
    return "\n".join(lines)


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
