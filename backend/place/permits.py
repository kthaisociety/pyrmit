"""The permits and prövningar a place profile points to, by fixed rules (no model): what the place card lists under
"likely permits". Each comes with its legal basis and the authority that decides it."""

LANSSTYRELSEN = "Länsstyrelsen"

BYGGLOV_REASON = {
    "inside": "Tested against the detaljplan: the project has to follow its provisions (a small deviation can be "
              "accepted).",
    "outside": "No detaljplan: tested against PBL 2 and 8 kap. directly, guided by the översiktsplan. A förhandsbesked "
               "can settle the location first.",
    "unknown": "Tested against the detaljplan if an older one applies here, else against PBL 2 and 8 kap.: ask the "
               "kommun which.",
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


def _permit(title: str, law: str, authority: str, reason: str, kind: str = "permit") -> dict:
    return {"title": title, "law": law, "authority": authority, "reason": reason, "kind": kind}


def _authority(name: str | None, kommun: str) -> str:
    """The register says "Kommun" or "Länsstyrelsen": name the kommun, and default to the länsstyrelse."""
    if name and name.strip().lower() == "kommun":
        return f"{kommun} kommun"
    return (name or LANSSTYRELSEN).strip()


def _bygglov(detaljplan: str, kommun: str) -> dict:
    return _permit("Bygglov (building permit)", "PBL 9 kap.", f"Byggnadsnämnden, {kommun} kommun",
                   BYGGLOV_REASON[detaljplan])


def _protected_area(area: dict, kommun: str) -> dict:
    kind = (area["type"] or "skyddat område").strip()
    return _permit(f"Dispens from the {kind.lower()} regulations of {area['name']}",
                   PROTECTED_AREA_LAW.get(kind.lower(), "MB 7 kap."),
                   _authority(area.get("permit_authority") or area.get("authority"), kommun),
                   f"The property lies in the {kind.lower()} {area['name']}: measures its regulations forbid need "
                   "a dispens.")


def _natura2000(site: dict) -> dict:
    return _permit(f"Natura 2000 tillstånd for {site['name']} ({site['ref']})", "MB 7 kap. 28 a §", LANSSTYRELSEN,
                   "Needed if the measure may significantly affect the site, even from outside it.")


def _ancient_remain(remain: dict) -> dict | None:
    label = f"{remain['ref']} ({remain['type']})"
    if remain["status"] == "Fornlämning":
        return _permit(f"Tillstånd for ingrepp i fornlämning {label}", "KML 2 kap. 12 §", LANSSTYRELSEN,
                       "It is forbidden to disturb, remove, dig out, cover or build on a fornlämning without one.")
    if remain["status"] == "Möjlig fornlämning":
        return _permit(f"Contact the länsstyrelse about {label}: a possible fornlämning", "KML 2 kap.",
                       LANSSTYRELSEN, "The länsstyrelse decides whether it is protected before you build.",
                       kind="consideration")
    return None


def _national_interest(interest: dict, kommun: str) -> dict:
    return _permit(f"{interest['name']}: the prövning must not significantly harm this riksintresse",
                   interest["law"] or "MB 3-4 kap.", f"{kommun} kommun / {LANSSTYRELSEN}",
                   f"{interest['type']}: weighed in the prövning, not a permit of its own.", kind="consideration")


def likely_permits(profile: dict) -> list[dict]:
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
    "fornlamning:<RAÄ number>", "contact:<RAÄ number>", "riksintresse:<name>". An uncovered place has none."""
    if not profile.get("covered"):
        return []
    kommun = profile["kommun"]["name"]
    remains = [_ancient_remain(remain) for remain in profile["ancient_remains"]]
    return ([_bygglov(profile["detaljplan"], kommun)]
            + [_protected_area(area, kommun) for area in profile["protected_areas"]]
            + [_natura2000(site) for site in profile["natura2000"]]
            + [remain for remain in remains if remain]
            + [_national_interest(interest, kommun) for interest in profile["national_interests"]])
