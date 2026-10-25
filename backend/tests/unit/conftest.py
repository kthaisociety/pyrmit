import pytest

from tests.unit.place.snapshot import write_snapshot


@pytest.fixture
def store(tmp_path):
    """The fake Uppsala snapshot in a temp folder."""
    return write_snapshot(tmp_path)
