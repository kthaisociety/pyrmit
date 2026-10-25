"""Finding a place by address or name for the map's search field: OpenStreetMap's Nominatim, in Sweden only, at most
one request a second (its usage policy), each answer cached. No suggestions while typing: the policy forbids them."""

import threading
import time
from collections.abc import Callable

import httpx

from place.store import PlaceStore

MIN_INTERVAL_S = 1.0  # Nominatim's usage policy: one request a second at most
MAX_RESULTS = 8


class Throttle:
    """At most one call per `interval` seconds, across threads: `wait()` sleeps until the next call may go."""

    def __init__(self, interval: float = MIN_INTERVAL_S, clock: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], None] = time.sleep):
        raise NotImplementedError

    def wait(self) -> None:
        """Return once at least `interval` seconds have passed since the previous call returned."""
        raise NotImplementedError


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
    raise NotImplementedError
