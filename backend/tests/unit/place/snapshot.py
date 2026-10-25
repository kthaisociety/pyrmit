"""A small fake snapshot of Uppsala (place.store format), a fake property service and corpus registry, shared by
the place tests. No real services (PCR-0011)."""

import json

from shapely.geometry import shape

from place.sources import NATIONAL_LAYERS, layer_by_id
from place.store import PlaceStore

FETCHED = "2026-10-25"
PROPERTY = [[17.640, 59.850], [17.642, 59.850], [17.642, 59.851], [17.640, 59.851], [17.640, 59.850]]
PIN = (59.8505, 17.641)          # lat, lon inside PROPERTY
STREET = (59.8530, 17.641)       # inside the kommun, no property there
EMPTY_LOT = (59.8800, 17.680)    # a property with no plan
OUTSIDE = (57.70, 11.97)         # Göteborg


def square(west, south, east, north):
    return {"type": "Polygon", "coordinates": [[[west, south], [east, south], [east, north], [west, north],
                                                [west, south]]]}


def collection(*features):
    return {"type": "FeatureCollection", "features": [{"type": "Feature", "geometry": g, "properties": p}
                                                       for g, p in features]}


def plan(ref, name, laga_kraft, url_ref=None):
    return {"Plannamn": name, "Aktbeteckning": ref, "LagaKraftDatum": laga_kraft, "Plantyp": "DP",
            "UrlDokument": f"https://www.uppsala.se/detaljplan/?aktbeteckning={url_ref or ref}",
            "Kommentar": "Tolkad, kan finnas osäkra gränser"}


LAYERS = {
    "plans": collection(
        (square(17.635, 59.845, 17.650, 59.855), plan("0380-P1990/3", "Stadsplan för Kungsängen", "19900312")),
        (square(17.6405, 59.8495, 17.6430, 59.8515), plan("0380-P2002/5", "Del av Atle, Kungsängen 7:8", "20020109")),
        # a neighbour that only touches the property's east edge
        (square(17.64199, 59.850, 17.660, 59.851), plan("0380-P2010/1", "Grannplanen", "20100101")),
    ),
    "plan_additions": collection(
        (square(17.639, 59.849, 17.643, 59.852), plan("0380-P2012/9", "Tillägg till stadsplan för Kungsängen",
                                                      "20120601")),
    ),
    "area_regulations": collection(
        (square(17.639, 59.849, 17.6415, 59.852), {**plan("0380-O2005/1", "Områdesbestämmelser Kungsängen",
                                                          "20050101"), "Plantyp": "OB"}),
    ),
    "plans_pending": collection(
        (square(17.638, 59.849, 17.645, 59.852), {"Name": "Kungsängen 7:8 m.fl.", "DiarieNummer": "PLA 2024-001",
                                                  "Status": "Samråd", "HUVUDSAKLIGT_SYFTE": "Bostäder"}),
    ),
    "zones_kvartersmark": collection(
        (square(17.640, 59.850, 17.6415, 59.851), {"AnvBeteckning": "BCK", "Anvandningstyp": "Kvarter",
                                                   "AnvBestammelse": "Bostäder, Centrumfunktion, Kontor",
                                                   "Kommentar": "Tolkad, kan finnas osäkra gränser"}),
        (square(17.6415, 59.850, 17.642, 59.851), {"AnvBeteckning": "P", "Anvandningstyp": "Kvarter",
                                                   "AnvBestammelse": "Parkering",
                                                   "Kommentar": "Tolkad, kan finnas osäkra gränser"}),
    ),
    "zones_allman_plats": collection(),
    "zones_vatten": collection(),
}


def write_snapshot(root, layers=LAYERS, complete=True, missing=()):
    folder = root / "0380"
    folder.mkdir(parents=True)
    (folder / "kommun.geojson").write_text(json.dumps({"type": "Feature", "geometry": square(17.5, 59.7, 17.9, 60.0),
                                                       "properties": {"code": "0380", "name": "Uppsala"}}))
    manifest = {"kommun": {"code": "0380", "name": "Uppsala", "fetched": FETCHED, "source": "OpenStreetMap",
                           "licence": "ODbL"}, "layers": {}}
    for layer_id, data in layers.items():
        manifest["layers"][layer_id] = {"title": layer_id, "provider": "Uppsala kommun", "licence": "open data",
                                        "count": len(data["features"]), "fetched": FETCHED,
                                        "complete": complete if layer_id == "plans" else False}
        if layer_id not in missing:
            (folder / f"{layer_id}.geojson").write_text(json.dumps(data))
    (folder / "manifest.json").write_text(json.dumps(manifest))
    return PlaceStore(root)


def fake_property(code, lon, lat):
    if 17.640 <= lon <= 17.642 and 59.850 <= lat <= 59.851:
        return {"designation": "Uppsala Kungsängen 7:8", "source": "Uppsala kommun", "fetched": FETCHED,
                "geometry": {"type": "Polygon", "coordinates": [PROPERTY]}}
    if 17.679 <= lon <= 17.681 and 59.879 <= lat <= 59.881:
        return {"designation": "Uppsala Kåbo 1:1", "source": "Uppsala kommun", "fetched": FETCHED,
                "geometry": square(17.679, 59.879, 17.681, 59.881)}
    return None


def registry(code):
    return [{"plan_id": "f41489", "kommun_code": "0380", "name": "Del av Atle, Kungsängen 7:8 - Uppsala kommun",
             "plan_number": None, "provisions": [{"code": "e1", "text": "Största byggnadsarea 300 m²"}]},
            {"plan_id": "a00001", "kommun_code": "0380", "name": "Stadsplan för Kungsängen - Uppsala kommun",
             "plan_number": None, "provisions": []}]


def no_remains(geometry):
    """A fake ancient-remains register with nothing in it."""
    return []


# The national layers and the ancient-remains register around the fake property (#36)
AROUND_PROPERTY = square(17.630, 59.845, 17.650, 59.855)
FAR_AWAY = square(17.80, 59.95, 17.81, 59.96)

NATIONAL = {layer.id: collection() for layer in NATIONAL_LAYERS} | {
    "protected_areas": collection(
        (AROUND_PROPERTY, {"NVRID": "2001234", "NAMN": "Kungsängsängen", "SKYDDSTYP": "Naturreservat",
                           "BESLUTSSTATUS": "Gällande", "BESLUTSMYNDIGHET": "Länsstyrelsen",
                           "PROVNINGSMYNDIGHET_DISPENS": "Länsstyrelsen", "URSPR_BESLUTSDATUM": "1951-03-02"}),
        (FAR_AWAY, {"NVRID": "2009999", "NAMN": "Långt bort", "SKYDDSTYP": "Biotopskyddsområde",
                    "BESLUTSMYNDIGHET": "Kommun"}),
    ),
    "natura2000": collection(
        (AROUND_PROPERTY, {"OMRADESKOD": "SE0210071", "OMRADESNAMN": "Kungsängen", "OMRADESTYP": "SCI",
                           "UPPGIFTSLAMNARE": "Länsstyrelsen i Uppsala län"}),
    ),
    "riks_naturvard": collection(
        (AROUND_PROPERTY, {"NAMN": "Fyrisån", "AMNESOMRAD": "Naturvård", "LAGRUM": "MB 3:6", "RIKSID": "3068",
                           "BESKRIVNIN": "https://geodata.naturvardsverket.se/handlingar/rest/dokument/202397"}),
    ),
    "riks_kulturmiljo": collection(
        (AROUND_PROPERTY, {"NAMN": "Uppsala stad", "ORIGINALID": "C 40",
                           "OBJEKTLANK": "https://www.raa.se/riksintressen/c40"}),
    ),
}

REMAINS = [
    {"properties": {"lamningsnummer": "L1941:2381", "raa_nummer": "Uppsala 123:1", "lamningstyp": "Gravfält",
                    "antikvarisk_bedomning": "Fornlämning",
                    "url": "https://pub.raa.se/visa/objekt/lamning/d4e16ab8"},
     "geometry": square(17.6405, 59.8502, 17.6410, 59.8505)},
    {"properties": {"lamningsnummer": "L1941:3039", "raa_nummer": "Uppsala 586:1", "lamningstyp": "Boplats",
                    "antikvarisk_bedomning": "Möjlig fornlämning",
                    "url": "https://pub.raa.se/visa/objekt/lamning/82572d22"},
     "geometry": square(17.6412, 59.8502, 17.6415, 59.8505)},
    {"properties": {"lamningsnummer": "L1941:4000", "raa_nummer": None, "lamningstyp": "Färdväg",
                    "antikvarisk_bedomning": "Övrig kulturhistorisk lämning",
                    "url": "https://pub.raa.se/visa/objekt/lamning/aa11"},
     "geometry": square(17.6416, 59.8506, 17.6418, 59.8508)},
]


def remains_at(geometry):
    area = shape(geometry)
    return [remain for remain in REMAINS if shape(remain["geometry"]).intersects(area)]


def write_national_snapshot(tmp_path, missing=(), national=NATIONAL):
    store = write_snapshot(tmp_path, layers=LAYERS | national, missing=missing)
    manifest_path = tmp_path / "0380" / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    for layer_id, entry in manifest["layers"].items():
        entry["provider"] = layer_by_id("0380", layer_id).provider
    manifest_path.write_text(json.dumps(manifest))
    return type(store)(tmp_path)
