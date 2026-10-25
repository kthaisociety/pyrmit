"""place.geocode: the map's address search against a fake Nominatim, and the throttle on a fake clock."""

import httpx
import pytest

from place import geocode
from place.geocode import MAX_RESULTS, Throttle, search_places
from place.live import PlaceSourceUnavailable


@pytest.fixture(autouse=True)
def empty_cache():
    """Every test searches from an empty cache, whatever an earlier test asked."""
    geocode._cache.clear()


def nominatim_hit(lat, lon, road, number=None, city="Uppsala", kommun="Uppsala kommun", kind="house"):
    address = {"road": road, "city": city, "municipality": kommun}
    if number:
        address["house_number"] = number
    return {"lat": str(lat), "lon": str(lon), "addresstype": kind, "address": address,
            "display_name": f"{number + ', ' if number else ''}{road}, {city}, {kommun}, Sverige"}


GOTEBORG = nominatim_hit(57.70, 11.97, "Kungsgatan", "47", city="Göteborg", kommun="Göteborgs kommun")
UPPSALA = nominatim_hit(59.8599, 17.6410, "Kungsgatan", "47A")


def register_entry(name, lat, lon, city="Uppsala"):
    return {"attributes": {"Name": name, "PostCity": city}, "geometry": {"x": lon, "y": lat}}


class FakeNominatim:
    """Nominatim, and Uppsala's address register beside it (empty unless given entries, or down)."""

    def __init__(self, results=(), status=200, register=(), register_status=200):
        self.results, self.status, self.requests = list(results), status, []
        self.register, self.register_status, self.register_requests = list(register), register_status, []

    def client(self):
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.host == "kartportal.uppsala.se":
                self.register_requests.append(request)
                return httpx.Response(self.register_status, json={"features": self.register})
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


# --- the kommun's address register ------------------------------------------------------------------------------

def test_a_street_address_is_found_in_the_kommuns_register(store, fast):
    """Uppsala's own register gives the entrance, so the pin lands on the house, not on the street."""
    nominatim = FakeNominatim([nominatim_hit(59.86, 17.64, "Kungsgatan", kind="road")],
                              register=[register_entry("Kungsgatan 47A", 59.85979, 17.6412)])
    [match] = search_places("Kungsgatan 47A, Uppsala", client=nominatim.client(), store=store, throttle=fast)
    assert match == {"label": "Kungsgatan 47A, Uppsala", "lat": 59.85979, "lon": 17.6412, "kind": "address",
                     "kommun": "Uppsala kommun", "in_pilot": True}
    assert nominatim.requests == []  # no Nominatim request, no throttle wait
    assert "UPPER(Name) = UPPER('kungsgatan 47a')" in nominatim.register_requests[0].url.params["where"]


def test_a_number_without_letter_also_finds_its_lettered_entrances(store, fast):
    nominatim = FakeNominatim(register=[register_entry("Kungsgatan 47B", 59.8598, 17.6413),
                                        register_entry("Kungsgatan 47", 59.8597, 17.6411)])
    matches = search_places("kungsgatan 47", client=nominatim.client(), store=store, throttle=fast)
    assert [match["label"] for match in matches] == ["Kungsgatan 47, Uppsala", "Kungsgatan 47B, Uppsala"]
    assert "LIKE UPPER('kungsgatan 47_')" in nominatim.register_requests[0].url.params["where"]


def test_the_typed_post_town_picks_among_equal_street_names(store, fast):
    nominatim = FakeNominatim(register=[register_entry("Bokvägen 21", 59.80, 17.80, city="Uppsala"),
                                        register_entry("Bokvägen 21", 59.97, 17.70, city="Storvreta")])
    [match] = search_places("Bokvägen 21, Storvreta", client=nominatim.client(), store=store, throttle=fast)
    assert match["label"] == "Bokvägen 21, Storvreta"


def test_quotes_in_the_query_cannot_break_the_register_query(store, fast):
    nominatim = FakeNominatim()
    search_places("O'Neills väg 3", client=nominatim.client(), store=store, throttle=fast)
    assert "o''neills väg 3" in nominatim.register_requests[0].url.params["where"]


def test_nominatim_answers_when_the_register_has_no_match(store, fast):
    nominatim = FakeNominatim([UPPSALA])
    [match] = search_places("kungsgatan 47a uppsala", client=nominatim.client(), store=store, throttle=fast)
    assert match["kind"] == "house" and len(nominatim.requests) == 1


def test_nominatim_answers_when_the_register_is_down(store, fast):
    nominatim = FakeNominatim([UPPSALA], register_status=503)
    [match] = search_places("kungsgatan 47a uppsala", client=nominatim.client(), store=store, throttle=fast)
    assert match["label"] == "Kungsgatan 47A, Uppsala"


def test_a_place_name_goes_straight_to_nominatim(store, fast):
    nominatim = FakeNominatim([nominatim_hit(59.8977, 17.6355, "Vattholmavägen", kind="church")])
    search_places("Gamla Uppsala kyrka", client=nominatim.client(), store=store, throttle=fast)
    assert nominatim.register_requests == [] and len(nominatim.requests) == 1


def test_a_number_never_finds_a_longer_number(store, fast):
    """The register's LIKE 'rälsvägen 1_' also matches 13: only a letter may follow the number."""
    nominatim = FakeNominatim(register=[register_entry("Rälsvägen 13", 59.87, 17.66),
                                        register_entry("Rälsvägen 1E", 59.86, 17.65)])
    [match] = search_places("Rälsvägen 1, Uppsala", client=nominatim.client(), store=store, throttle=fast)
    assert match["label"] == "Rälsvägen 1E, Uppsala"
