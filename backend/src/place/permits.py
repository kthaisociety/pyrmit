"""The permits and prövningar a place profile points to, by fixed rules (no model): what the place card lists under
"likely permits". Each comes with its legal basis and the authority that decides it."""

from answer_language import Language
from glossary import explained

LANSSTYRELSEN = "Länsstyrelsen"

# The titles and reasons per page language (#75); English ones get their glossary explanations in _permit
TEXTS: dict[str, dict] = {
    "en": {
        "bygglov_title": "Bygglov",
        "bygglov_reason": {
            "inside": "Tested against the detaljplan: the project has to follow its provisions (a small deviation can "
                      "be accepted).",
            "outside": "No detaljplan: tested against PBL 2 and 8 kap. directly, guided by the översiktsplan. A "
                       "förhandsbesked can settle the location first.",
            "unknown": "Tested against the detaljplan if an older one applies here, else against PBL 2 and 8 kap.: "
                       "ask the kommun which.",
        },
        "dispens_title": "Dispens from the {kind} regulations of {name}",
        "dispens_reason": "The property lies in the {kind} {name}: measures its regulations forbid need a dispens.",
        "natura_title": "Natura 2000 tillstånd for {name} ({ref})",
        "natura_reason": "Needed if the measure may significantly affect the site, even from outside it.",
        "remain_title": "Tillstånd for ingrepp i fornlämning {label}",
        "remain_reason": "It is forbidden to disturb, remove, dig out, cover or build on a fornlämning without one.",
        "contact_title": "Contact the länsstyrelse about {label}: a possible fornlämning",
        "contact_reason": "The länsstyrelse decides whether it is protected before you build.",
        "interest_title": "{name}: the prövning must not significantly harm this riksintresse",
        "interest_reason": "{type}: weighed in the prövning, not a permit of its own.",
    },
    "sv": {
        "bygglov_title": "Bygglov",
        "bygglov_reason": {
            "inside": "Prövas mot detaljplanen: projektet måste följa dess bestämmelser (en liten avvikelse kan "
                      "godtas).",
            "outside": "Ingen detaljplan: prövas direkt mot PBL 2 och 8 kap., med översiktsplanen som vägledning. Ett "
                       "förhandsbesked kan avgöra lokaliseringen först.",
            "unknown": "Prövas mot detaljplanen om en äldre plan gäller här, annars mot PBL 2 och 8 kap.: fråga "
                       "kommunen vilket.",
        },
        "dispens_title": "Dispens från föreskrifterna för {kind} {name}",
        "dispens_reason": "Fastigheten ligger i {kind} {name}: åtgärder som föreskrifterna förbjuder kräver dispens.",
        "natura_title": "Natura 2000-tillstånd för {name} ({ref})",
        "natura_reason": "Krävs om åtgärden kan påverka området på ett betydande sätt, även utifrån.",
        "remain_title": "Tillstånd för ingrepp i fornlämning {label}",
        "remain_reason": "Det är förbjudet att rubba, ta bort, gräva ut, täcka över eller bebygga en fornlämning "
                         "utan tillstånd.",
        "contact_title": "Kontakta länsstyrelsen om {label}: en möjlig fornlämning",
        "contact_reason": "Länsstyrelsen avgör om den är skyddad innan du bygger.",
        "interest_title": "{name}: prövningen får inte påtagligt skada detta riksintresse",
        "interest_reason": "{type}: vägs in i prövningen, inget eget tillstånd.",
    },
}

# Where each kind of protected area takes its dispens from (miljöbalken 7 kap.)
PROTECTED_AREA_LAW = {
    "nationalpark": "MB 7 kap. 2-3 §",
    "naturreservat": "MB 7 kap. 7 §",
    "kulturreservat": "MB 7 kap. 9 §",
    "naturminne": "MB 7 kap. 10 §",
    "biotopskyddsområde": "MB 7 kap. 11 §",
    "djur- och växtskyddsområde": "MB 7 kap. 12 §",
    "vattenskyddsområde": "MB 7 kap. 21-22 §",
}


def _permit(key: str, title: str, law: str, authority: str, reason: str, language: Language,
            kind: str = "permit") -> dict:
    if language == "en":
        title, reason = explained(title), explained(reason)
    return {"key": key, "title": title, "law": law, "authority": authority, "reason": reason, "kind": kind}


def _authority(name: str | None, kommun: str) -> str:
    """The register says "Kommun" or "Länsstyrelsen": name the kommun, and default to the länsstyrelse."""
    if name and name.strip().lower() == "kommun":
        return f"{kommun} kommun"
    return (name or LANSSTYRELSEN).strip()


def _bygglov(detaljplan: str, kommun: str, language: Language) -> dict:
    texts = TEXTS[language]
    return _permit("bygglov", texts["bygglov_title"], "PBL 9 kap.", f"Byggnadsnämnden, {kommun} kommun",
                   texts["bygglov_reason"][detaljplan], language)


def _protected_area(area: dict, kommun: str, language: Language) -> dict:
    texts = TEXTS[language]
    kind = (area["type"] or "skyddat område").strip()
    return _permit(f"dispens:{area['ref']}", texts["dispens_title"].format(kind=kind.lower(), name=area["name"]),
                   PROTECTED_AREA_LAW.get(kind.lower(), "MB 7 kap."),
                   _authority(area.get("permit_authority") or area.get("authority"), kommun),
                   texts["dispens_reason"].format(kind=kind.lower(), name=area["name"]), language)


def _natura2000(site: dict, language: Language) -> dict:
    texts = TEXTS[language]
    return _permit(f"natura2000:{site['ref']}", texts["natura_title"].format(name=site["name"], ref=site["ref"]),
                   "MB 7 kap. 28 a §", LANSSTYRELSEN, texts["natura_reason"], language)


def _ancient_remain(remain: dict, language: Language) -> dict | None:
    texts = TEXTS[language]
    label = f"{remain['ref']} ({remain['type']})"
    if remain["status"] == "Fornlämning":
        return _permit(f"fornlamning:{remain['ref']}", texts["remain_title"].format(label=label), "KML 2 kap. 12 §",
                       LANSSTYRELSEN, texts["remain_reason"], language)
    if remain["status"] == "Möjlig fornlämning":
        return _permit(f"contact:{remain['ref']}", texts["contact_title"].format(label=label), "KML 2 kap.",
                       LANSSTYRELSEN, texts["contact_reason"], language, kind="consideration")
    return None


def _national_interest(interest: dict, kommun: str, language: Language) -> dict:
    texts = TEXTS[language]
    return _permit(f"riksintresse:{interest['name']}", texts["interest_title"].format(name=interest["name"]),
                   interest["law"] or "MB 3-4 kap.", f"{kommun} kommun / {LANSSTYRELSEN}",
                   texts["interest_reason"].format(type=interest["type"]), language, kind="consideration")


def likely_permits(profile: dict, language: Language = "en") -> list[dict]:
    """The likely permits of a place profile (see place.profile.build_profile), in this order:

    - bygglov, always for a covered place: tested against the detaljplan when inside one, against PBL 2 and 8 kap.
      when outside, and "ask the kommun" when unknown; decided by the kommun's byggnadsnämnd
    - one dispens per protected area (naturreservat, biotopskyddsområde, vattenskyddsområde, ...) from its
      regulations, decided by the authority the register names for dispens (else the deciding authority)
    - one Natura 2000 tillstånd per site, needed if the measure may significantly affect it (länsstyrelsen)
    - one tillstånd for ingrepp i fornlämning per remain assessed as "Fornlämning" (länsstyrelsen); a "Möjlig
      fornlämning" asks the user to contact the länsstyrelse instead
    - one consideration per national interest: the prövning must not significantly harm it (not a permit)

    Returns [{"key", "title", "law", "authority", "reason", "kind"}], kind "permit" or "consideration". The key is
    stable across runs, for the benchmark: "bygglov", "dispens:<NVRID>", "natura2000:<site code>",
    "fornlamning:<RAÄ number>", "contact:<RAÄ number>", "riksintresse:<name>". An uncovered place has none.

    `language` ("sv" or "en") is the language of each title and reason; key, law, authority and kind are the same in
    both. In English a Swedish domain term keeps its Swedish form with its glossary.GLOSSARY explanation in
    parentheses on first use in each text ("Bygglov (building permit)"); in Swedish there is none ("Bygglov")."""
    if not profile.get("covered"):
        return []
    kommun = profile["kommun"]["name"]
    remains = [_ancient_remain(remain, language) for remain in profile["ancient_remains"]]
    return ([_bygglov(profile["detaljplan"], kommun, language)]
            + [_protected_area(area, kommun, language) for area in profile["protected_areas"]]
            + [_natura2000(site, language) for site in profile["natura2000"]]
            + [remain for remain in remains if remain]
            + [_national_interest(interest, kommun, language) for interest in profile["national_interests"]])
