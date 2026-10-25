import pytest

from place.profile import build_profile
from tests.unit.place.snapshot import (
    fake_property,
    registry,
    remains_at,
    write_national_snapshot,
    write_snapshot,
)


@pytest.fixture
def store(tmp_path):
    """The fake Uppsala snapshot in a temp folder."""
    return write_snapshot(tmp_path)


@pytest.fixture
def profile_of(tmp_path):
    """The place profile of the fake Kungsängen 7:8 (national layers and remains included)."""
    store = write_national_snapshot(tmp_path)

    def build(lat, lon):
        return build_profile(lat, lon, store=store, property_at=fake_property, plan_registry=registry,
                             ancient_remains_at=remains_at)
    return build
