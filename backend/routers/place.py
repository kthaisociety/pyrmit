"""
The map's place lookups (no LLM, see place/):

- GET /api/place/profile?lat=..&lon=..  -> the place profile of a pinned point (place.profile.build_profile)
- GET /api/place/coverage               -> the pilot kommuner with a snapshot, for the map's first view
"""

from typing import Callable

from fastapi import APIRouter, Depends, Query

from dependencies import get_current_user
from place.store import PlaceStore
import models

router = APIRouter()


def get_place_store() -> PlaceStore:
    """The shared snapshot store (overridden in tests)."""
    raise NotImplementedError


def get_property_lookup() -> Callable[[str, float, float], dict | None]:
    """The live property lookup (overridden in tests)."""
    raise NotImplementedError


def get_plan_registry() -> Callable[[str], list[dict]]:
    """The corpus plan registry by kommun code (overridden in tests)."""
    raise NotImplementedError


@router.get("/place/profile")
def place_profile(lat: float = Query(..., ge=-90, le=90), lon: float = Query(..., ge=-180, le=180),
                  store: PlaceStore = Depends(get_place_store),
                  property_at: Callable = Depends(get_property_lookup),
                  plan_registry: Callable = Depends(get_plan_registry),
                  user: models.User = Depends(get_current_user)) -> dict:
    """The place profile of the point (see build_profile). 422 when lat or lon is missing or out of range."""
    raise NotImplementedError


@router.get("/place/coverage")
def place_coverage(store: PlaceStore = Depends(get_place_store),
                   user: models.User = Depends(get_current_user)) -> list[dict]:
    """The pilot kommuner with a snapshot: [{"code", "name", "bbox", "fetched"}]."""
    raise NotImplementedError
