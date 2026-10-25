"""Acceptance tests for #38: find a place by address on the map. Temporary, folded into tests/unit/ by
refactor-issue. A fake Nominatim (httpx MockTransport) and a fake clock: no network (PCR-0011)."""

from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from dependencies import get_current_user
from place.geocode import MAX_RESULTS, Throttle, search_places
from place.live import PlaceSourceUnavailable
from routers import place as place_router
from tests.unit.place.snapshot import write_snapshot


def nominatim_hit(lat, lon, road, number=None, city="Uppsala", kommun="Uppsala kommun", kind="house"):
    address = {"road": road, "city": city, "municipality": kommun}
    if number:
        address["house_number"] = number
    return {"lat": str(lat), "lon": str(lon), "addresstype": kind, "address": address,
            "display_name": f"{number + ', ' if number else ''}{road}, {city}, {kommun}, Sverige"}


GOTEBORG = nominatim_hit(57.70, 11.97, "Kungsgatan", "47", city="Göteborg", kommun="Göteborgs kommun")
UPPSALA = nominatim_hit(59.8599, 17.6410, "Kungsgatan", "47A")


class FakeNominatim:
    def __init__(self, results=(), status=200):
        self.results, self.status, self.requests = list(results), status, []

    def client(self):
        def handler(request: httpx.Request) -> httpx.Response:
            self.requests.append(request)
            return httpx.Response(self.status, json=self.results)
        return httpx.Client(transport=httpx.MockTransport(handler))


class FakeClock:
    def __init__(self):
        self.now, self.sleeps = 100.0, []

    def clock(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


@pytest.fixture
def store(tmp_path):
    """The fake Uppsala snapshot: its kommun boundary decides which matches are in a pilot kommun."""
    return write_snapshot(tmp_path)


@pytest.fixture
def fast():
    """A throttle on a fake clock: tests never wait."""
    clock = FakeClock()
    return Throttle(clock=clock.clock, sleep=clock.sleep)


# --- searching -------------------------------------------------------------------------------------------------

def test_a_search_returns_matches_with_label_and_point(store, fast):
    """A match has a short label, its point, its kind and its kommun."""
    nominatim = FakeNominatim([UPPSALA])
    [match] = search_places("kungsgatan 47a uppsala", client=nominatim.client(), store=store, throttle=fast)
    assert match["label"] == "Kungsgatan 47A, Uppsala"
    assert (match["lat"], match["lon"]) == (59.8599, 17.641)
    assert match["kind"] == "house"
    assert match["kommun"] == "Uppsala kommun"


def test_matches_in_the_pilot_kommuner_come_first(store, fast):
    """A match in a pilot kommun is listed before one elsewhere."""
    nominatim = FakeNominatim([GOTEBORG, UPPSALA])
    matches = search_places("kungsgatan 47", client=nominatim.client(), store=store, throttle=fast)
    assert [m["in_pilot"] for m in matches] == [True, False]
    assert matches[0]["label"] == "Kungsgatan 47A, Uppsala"


def test_the_search_is_limited_to_sweden(store, fast):
    """Nominatim is asked for Swedish matches only."""
    nominatim = FakeNominatim([UPPSALA])
    search_places("stora torget", client=nominatim.client(), store=store, throttle=fast)
    assert nominatim.requests[0].url.params["countrycodes"] == "se"


def test_at_most_max_results_matches(store, fast):
    """No more than MAX_RESULTS matches are returned."""
    nominatim = FakeNominatim([UPPSALA] * (MAX_RESULTS + 4))
    assert len(search_places("storgatan", client=nominatim.client(), store=store, throttle=fast)) == MAX_RESULTS


def test_no_match_gives_an_empty_list(store, fast):
    """A search with no match returns nothing."""
    nominatim = FakeNominatim([])
    assert search_places("xyzzy plats", client=nominatim.client(), store=store, throttle=fast) == []


def test_the_same_search_is_answered_from_the_cache(store, fast):
    """Asking again (case and spacing aside) does not reach Nominatim a second time."""
    nominatim = FakeNominatim([UPPSALA])
    search_places("Dragarbrunnsgatan 1", client=nominatim.client(), store=store, throttle=fast)
    search_places("  dragarbrunnsgatan   1 ", client=nominatim.client(), store=store, throttle=fast)
    assert len(nominatim.requests) == 1


def test_a_failing_service_is_reported_unavailable(store, fast):
    """Nominatim answering with an error raises PlaceSourceUnavailable."""
    nominatim = FakeNominatim(status=503)
    with pytest.raises(PlaceSourceUnavailable):
        search_places("svartbäcksgatan 3", client=nominatim.client(), store=store, throttle=fast)


# --- the usage policy ------------------------------------------------------------------------------------------

def test_calls_are_spaced_at_least_a_second_apart():
    """Two calls in a row: the second waits until a second has passed."""
    clock = FakeClock()
    throttle = Throttle(clock=clock.clock, sleep=clock.sleep)
    throttle.wait()
    clock.now += 0.25
    throttle.wait()
    assert clock.sleeps == [pytest.approx(0.75)]


def test_a_call_after_a_pause_does_not_wait():
    """A call more than a second after the previous one goes at once."""
    clock = FakeClock()
    throttle = Throttle(clock=clock.clock, sleep=clock.sleep)
    throttle.wait()
    clock.now += 3
    throttle.wait()
    assert clock.sleeps == []


def test_every_search_waits_for_the_throttle(store):
    """Each request to Nominatim goes through the throttle."""
    clock = FakeClock()
    throttle = Throttle(clock=clock.clock, sleep=clock.sleep)
    nominatim = FakeNominatim([UPPSALA])
    search_places("vaksalagatan 10", client=nominatim.client(), store=store, throttle=throttle)
    search_places("vaksalagatan 12", client=nominatim.client(), store=store, throttle=throttle)
    assert clock.sleeps == [pytest.approx(1.0)]


# --- the API ---------------------------------------------------------------------------------------------------

def client_with(search):
    app = FastAPI()
    app.include_router(place_router.router, prefix="/api")
    app.dependency_overrides[place_router.get_place_search] = lambda: search
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id="u1")
    return TestClient(app)


def test_search_endpoint_returns_the_matches():
    """GET /api/place/search returns the matches of the query."""
    match = {"label": "Kungsgatan 47A, Uppsala", "lat": 59.8599, "lon": 17.641, "kind": "house",
             "kommun": "Uppsala kommun", "in_pilot": True}
    response = client_with(lambda q: [match]).get("/api/place/search", params={"q": "kungsgatan 47a"})
    assert response.status_code == 200
    assert response.json() == [match]


def test_search_endpoint_rejects_a_too_short_query():
    """A query under two characters is a 422."""
    assert client_with(lambda q: []).get("/api/place/search", params={"q": "k"}).status_code == 422


def test_search_endpoint_says_when_the_service_is_down():
    """Nominatim down is a 503 with a message."""
    def down(q):
        raise PlaceSourceUnavailable("Nominatim: 503")
    response = client_with(down).get("/api/place/search", params={"q": "kungsgatan"})
    assert response.status_code == 503
    assert "address search" in response.json()["detail"].lower()
