"""Finding a place by address or name for the map's search field. A street address and number is looked up first in the
pilot kommuner's own address registers (Uppsala publishes its belägenhetsadresser): OpenStreetMap lacks most Swedish
house numbers and answers with the street, which lands on the street's own property (the check of 2026-10-25 found
the right property for 40 % of Uppsala's addresses). Anything else goes to OpenStreetMap's Nominatim, in Sweden only, at
most one request a second (its usage policy). Each answer is cached. No suggestions while typing: Nominatim's policy
forbids them."""

import re
import threading
import time
from collections.abc import Callable

import httpx

from place.live import PlaceSourceUnavailable
from place.profile import default_store
from place.sources import NOMINATIM, PILOTS, USER_AGENT
from place.store import PlaceStore

MIN_INTERVAL_S = 1.0  # Nominatim's usage policy: one request a second at most
MAX_RESULTS = 8
TIMEOUT_S = 10
CACHE_SIZE = 512
PLACE_KEYS = ("city", "town", "village", "hamlet", "suburb", "municipality")
# "Kungsgatan 47A, Uppsala", "kungsgatan 47 a uppsala", "Björklinge-Gränby 59": street, number, letter, place
HOUSE_ADDRESS = re.compile(r"^\s*(?P<street>\D*?\S)\s+(?P<number>\d+)\s*(?P<letter>[a-zåäöé](?![a-zåäöé]))?"
                           r"(?:(?:\s*,\s*|\s+)(?P<place>\D.*?))?\s*,?\s*$", re.IGNORECASE)


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


def register_addresses(query: str, store: PlaceStore, client: httpx.Client) -> list[dict]:
    """The house addresses matching `query` in the address registers of the pilot kommuner in `store`, as search
    matches (kind "address"). Without a letter the number also finds its lettered entrances ("Kungsgatan 47" ->
    47A-47E); with a place, the addresses of that post town come first when there are any. [] when the query is not
    a street and number. Raises PlaceSourceUnavailable when a register does not answer."""
    parsed = HOUSE_ADDRESS.match(query)
    if not parsed:
        return []
    typed = f"{parsed['street']} {parsed['number']}{parsed['letter'] or ''}"
    name = typed.replace("'", "''")
    where = f"UPPER(Name) = UPPER('{name}')"
    if not parsed["letter"]:
        where += f" OR UPPER(Name) LIKE UPPER('{name}_')"
    # LIKE's "_" is any character: "Rälsvägen 1_" also finds Rälsvägen 13, so only a letter may follow the number
    entrance = re.compile(rf"{re.escape(typed)}[a-zåäöé]?", re.IGNORECASE)
    matches = []
    for code in (kommun["code"] for kommun in store.kommuner()):
        url = PILOTS.get(code, {}).get("addresses")
        if not url:
            continue
        try:
            response = client.get(f"{url}/query", params={"where": where, "outFields": "Name,PostCity", "outSR": 4326,
                                                          "f": "json"}, headers={"User-Agent": USER_AGENT},
                                  timeout=TIMEOUT_S)
            response.raise_for_status()
            features = response.json()["features"]
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
            raise PlaceSourceUnavailable(f"address register of {code}: {exc}") from exc
        matches += [{"label": f"{f['attributes']['Name']}, {f['attributes'].get('PostCity') or PILOTS[code]['name']}",
                     "lat": f["geometry"]["y"], "lon": f["geometry"]["x"], "kind": "address",
                     "kommun": f"{PILOTS[code]['name']} kommun", "in_pilot": True,
                     "city": (f["attributes"].get("PostCity") or "").lower()}
                    for f in features if f.get("geometry") and entrance.fullmatch(f["attributes"]["Name"] or "")]
    town = (parsed["place"] or "").lower()
    if town and any(match["city"] == town for match in matches):
        matches = [match for match in matches if match["city"] == town]
    matches.sort(key=lambda match: (len(match["label"]), match["label"]))  # the exact number before its letters
    return [{key: value for key, value in match.items() if key != "city"} for match in matches[:MAX_RESULTS]]


def _ask_nominatim(client: httpx.Client, query: str) -> list[dict]:
    try:
        response = client.get(f"{NOMINATIM}/search", params={
            "q": query, "countrycodes": "se", "format": "jsonv2", "addressdetails": 1, "limit": MAX_RESULTS,
            "accept-language": "sv"}, headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT_S)
        response.raise_for_status()
        return response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise PlaceSourceUnavailable(f"Nominatim: {exc}") from exc


def _nominatim_matches(client: httpx.Client, query: str, store: PlaceStore, throttle: Throttle) -> list[dict]:
    throttle.wait()
    matches, roads_seen = [], set()
    for hit in _ask_nominatim(client, query)[:MAX_RESULTS]:
        match = _match(hit, store)
        if hit.get("category") == "highway":  # a street comes once per segment: list it once
            if match["label"] in roads_seen:
                continue
            roads_seen.add(match["label"])
        matches.append(match)
    matches.sort(key=lambda match: not match["in_pilot"])  # stable: Nominatim's order within each group
    return matches


def search_places(query: str, *, client: httpx.Client | None = None, store: PlaceStore | None = None,
                  throttle: Throttle | None = None) -> list[dict]:
    """Swedish addresses and place names matching `query`: [{"label" (e.g. "Kungsgatan 47A, Uppsala"), "lat", "lon",
    "kind" ("address" from a kommun's register, else Nominatim's addresstype: house, road, place, ...), "kommun"
    (e.g. "Uppsala kommun", or None), "in_pilot" (the point lies in a pilot kommun of `store`)}], at most MAX_RESULTS.
    A street and number found in a pilot kommun's address register (register_addresses) gives the register's
    entrances only; otherwise Nominatim's matches, the pilot kommuner first and otherwise in Nominatim's order. An
    empty list when nothing matches.

    The same query (case and spacing aside) is answered from a cache; every request to Nominatim waits for
    `throttle` (default: one shared Throttle). `client`, `store` and `throttle` default to a client with the
    project's User-Agent, the snapshot store and the shared throttle. A register that does not answer is skipped.
    Raises PlaceSourceUnavailable when Nominatim does not answer."""
    key = _normalise(query)
    with _cache_lock:
        cached = _cache.get(key)
    if cached is not None:
        return cached
    store = store or default_store()
    http = client or httpx.Client(follow_redirects=True)
    try:
        try:
            matches = register_addresses(key, store, http)
        except PlaceSourceUnavailable:  # the register is a shortcut: Nominatim still answers
            matches = []
        if not matches:
            matches = _nominatim_matches(http, key, store, throttle or _shared_throttle)
    finally:
        if client is None:
            http.close()
    with _cache_lock:
        if len(_cache) >= CACHE_SIZE:
            _cache.pop(next(iter(_cache)))
        _cache[key] = matches
    return matches
