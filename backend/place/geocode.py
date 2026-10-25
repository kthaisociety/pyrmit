"""Finding a place by address or name for the map's search field: OpenStreetMap's Nominatim, in Sweden only, at most
one request a second (its usage policy), each answer cached. No suggestions while typing: the policy forbids them."""

import threading
import time
from collections.abc import Callable

import httpx

from place.live import PlaceSourceUnavailable
from place.sources import NOMINATIM, USER_AGENT
from place.store import PlaceStore

MIN_INTERVAL_S = 1.0  # Nominatim's usage policy: one request a second at most
MAX_RESULTS = 8
TIMEOUT_S = 10
CACHE_SIZE = 512
PLACE_KEYS = ("city", "town", "village", "hamlet", "suburb", "municipality")


class Throttle:
    """At most one call per `interval` seconds, across threads: `wait()` sleeps until the next call may go."""

    def __init__(self, interval: float = MIN_INTERVAL_S, clock: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], None] = time.sleep):
        self.interval, self.clock, self.sleep = interval, clock, sleep
        self._last: float | None = None
        self._lock = threading.Lock()

    def wait(self) -> None:
        """Return once at least `interval` seconds have passed since the previous call returned."""
        with self._lock:
            if self._last is not None:
                remaining = self.interval - (self.clock() - self._last)
                if remaining > 0:
                    self.sleep(remaining)
            self._last = self.clock()


_shared_throttle = Throttle()
_cache: dict[str, list[dict]] = {}
_cache_lock = threading.Lock()


def _normalise(query: str) -> str:
    return " ".join(query.lower().split())


def _label(hit: dict) -> str:
    """'Kungsgatan 47A, Uppsala' for an address, 'Gamla Uppsala kyrka, Uppsala' for a named place, else the first
    two parts of Nominatim's display name."""
    address = hit.get("address") or {}
    place = next((address[key] for key in PLACE_KEYS if address.get(key)), None)
    if address.get("house_number"):
        first = f"{address.get('road', '')} {address['house_number']}".strip()
    else:
        first = hit.get("name") or address.get("road")
    if not first:
        return ", ".join(hit.get("display_name", "").split(", ")[:2])
    return ", ".join(dict.fromkeys(part for part in (first, place) if part))


def _match(hit: dict, store: PlaceStore) -> dict:
    lat, lon = float(hit["lat"]), float(hit["lon"])
    return {"label": _label(hit), "lat": lat, "lon": lon, "kind": hit.get("addresstype"),
            "kommun": (hit.get("address") or {}).get("municipality"), "in_pilot": store.kommun_at(lon, lat) is not None}


def _ask_nominatim(client: httpx.Client, query: str) -> list[dict]:
    try:
        response = client.get(f"{NOMINATIM}/search", params={
            "q": query, "countrycodes": "se", "format": "jsonv2", "addressdetails": 1, "limit": MAX_RESULTS,
            "accept-language": "sv"}, headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT_S)
        response.raise_for_status()
        return response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise PlaceSourceUnavailable(f"Nominatim: {exc}") from exc


def search_places(query: str, *, client: httpx.Client | None = None, store: PlaceStore | None = None,
                  throttle: Throttle | None = None) -> list[dict]:
    """Swedish addresses and place names matching `query`: [{"label" (e.g. "Kungsgatan 47A, Uppsala"), "lat", "lon",
    "kind" (Nominatim's addresstype: house, road, place, ...), "kommun" (e.g. "Uppsala kommun", or None),
    "in_pilot" (the point lies in a pilot kommun of `store`)}], at most MAX_RESULTS, matches in the pilot kommuner
    first and otherwise in Nominatim's order. An empty list when nothing matches.

    The same query (case and spacing aside) is answered from a cache; every request to Nominatim waits for
    `throttle` (default: one shared Throttle). `client`, `store` and `throttle` default to a client with the
    project's User-Agent, the snapshot store and the shared throttle. Raises PlaceSourceUnavailable when Nominatim
    does not answer."""
    from place.profile import default_store

    key = _normalise(query)
    with _cache_lock:
        cached = _cache.get(key)
    if cached is not None:
        return cached
    (throttle or _shared_throttle).wait()
    if client is None:
        with httpx.Client(follow_redirects=True) as own:
            hits = _ask_nominatim(own, key)
    else:
        hits = _ask_nominatim(client, key)
    matches, roads_seen = [], set()
    for hit in hits[:MAX_RESULTS]:
        match = _match(hit, store or default_store())
        if hit.get("category") == "highway":  # a street comes once per segment: list it once
            if match["label"] in roads_seen:
                continue
            roads_seen.add(match["label"])
        matches.append(match)
    matches.sort(key=lambda match: not match["in_pilot"])  # stable: Nominatim's order within each group
    with _cache_lock:
        if len(_cache) >= CACHE_SIZE:
            _cache.pop(next(iter(_cache)))
        _cache[key] = matches
    return matches
