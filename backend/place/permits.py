"""The permits and prövningar a place profile points to, by fixed rules (no model): what the place card lists under
"likely permits". Each comes with its legal basis and the authority that decides it."""


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

    Returns [{"title", "law", "authority", "reason", "kind"}], kind "permit" or "consideration". An uncovered place
    has none."""
    raise NotImplementedError
