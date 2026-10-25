"""
The map's place lookups (no LLM, see place/):

- GET /api/place/profile?lat=..&lon=..  -> the place profile of a pinned point (place.profile.build_profile)
- GET /api/place/coverage               -> the pilot kommuner with a snapshot, for the map's first view
- GET /api/place/search?q=..            -> Swedish addresses and place names for the map's search (Nominatim)
"""

from collections.abc import Callable
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

import models
from dependencies import get_current_user
from place import live, profile
from place.store import PlaceStore

router = APIRouter()


def get_place_store() -> PlaceStore:
    """The shared snapshot store (overridden in tests)."""
    return profile.default_store()


def get_property_lookup() -> Callable[[str, float, float], dict | None]:
    """The live property lookup (overridden in tests)."""
    return live.property_at


def get_ancient_remains_lookup() -> Callable[[dict], list[dict]]:
    """The live ancient-remains lookup (overridden in tests)."""
    return live.ancient_remains_at


def get_place_search() -> Callable[[str], list[dict]]:
    """The address search (overridden in tests)."""
    raise NotImplementedError


def get_plan_registry() -> Callable[[str], list[dict]]:
    """The corpus plan registry by kommun code (overridden in tests)."""
    return profile.corpus_plans


@router.get("/place/profile")
def place_profile(lat: Annotated[float, Query(ge=-90, le=90)], lon: Annotated[float, Query(ge=-180, le=180)],
                  store: Annotated[PlaceStore, Depends(get_place_store)],
                  property_at: Annotated[Callable, Depends(get_property_lookup)],
                  plan_registry: Annotated[Callable, Depends(get_plan_registry)],
                  ancient_remains_at: Annotated[Callable, Depends(get_ancient_remains_lookup)],
                  user: Annotated[models.User, Depends(get_current_user)]) -> dict:
    """The place profile of the point (see build_profile). 422 when lat or lon is missing or out of range."""
    try:
        return profile.build_profile(lat, lon, store=store, property_at=property_at, plan_registry=plan_registry,
                                     ancient_remains_at=ancient_remains_at)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/place/coverage")
def place_coverage(store: Annotated[PlaceStore, Depends(get_place_store)],
                   user: Annotated[models.User, Depends(get_current_user)]) -> list[dict]:
    """The pilot kommuner with a snapshot: [{"code", "name", "bbox", "fetched"}]."""
    return store.kommuner()


@router.get("/place/search")
def place_search(q: Annotated[str, Query(min_length=2, max_length=200)],
                 search: Annotated[Callable, Depends(get_place_search)],
                 user: Annotated[models.User, Depends(get_current_user)]) -> list[dict]:
    """Matches for the query (see place.geocode.search_places). 422 for a query under 2 characters, 503 with a
    message when the address service does not answer."""
    raise NotImplementedError
