"""Live lookups at a point: the property (fastighet) from the pilot kommun's own map service."""


class PlaceSourceUnavailable(Exception):
    """A live source did not answer: network error, HTTP error or an unreadable payload."""


def property_at(code: str, lon: float, lat: float) -> dict | None:
    """The property at the point in pilot kommun `code`: {"designation" (e.g. "Uppsala Kungsängen 7:8"),
    "geometry" (GeoJSON in WGS84, every part of the property), "source", "fetched" (ISO date)}.

    None when no property covers the point (a street, park or water) or the kommun has no property service.
    Raises PlaceSourceUnavailable when the service fails."""
    raise NotImplementedError
