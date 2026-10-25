"""
The layers of the place profile: where each comes from and how its attributes map to a profile feature.

A feature is a flat dict: {"layer", "kind", "name", "ref", "type", "date", "status", "authority", "law",
"text", "url", "note"} (missing values are None). Snapshots keep the provider's raw attributes, so the mapping
below can change without fetching again.

Pilot kommuner (PILOTS) list their own layers (Uppsala publishes its plans, land-use zones and properties on an
open ArcGIS service); NATIONAL layers are clipped to each pilot kommun. Checked on 2026-10-25:
- länsstyrelsernas strandskydd services answered 403 from here: strandskydd is "not checked" for now
- RAÄ has no working bulk download (WFS and datauttag down): ancient remains are looked up live (WMS
  GetFeatureInfo)
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

USER_AGENT = "pyrmit/0.1 (+https://github.com/kthaisociety/pyrmit)"

UPPSALA_MAP = "https://kartportal.uppsala.se/mapping/rest/services/iExternaKartan/ByggaBo/MapServer"
NV_WFS = "https://geodata.naturvardsverket.se/naturvardsregistret/wfs"
N2000_WFS = "https://geodata.naturvardsverket.se/n2000/wfs"
RIKSINTRESSEN = "https://gis2.boverket.se/arcgis/rest/services/Riksintressen___Februari_2025_WMS/MapServer"
RAA_WMS = "https://pub.raa.se/visning/lamningar_v1/wms"
NOMINATIM = "https://nominatim.openstreetmap.org"
SWEDEN_TZ = ZoneInfo("Europe/Stockholm")


def today() -> str:
    """Today's date in Sweden (ISO), the date snapshots and live lookups are stamped with."""
    return datetime.now(SWEDEN_TZ).date().isoformat()


@dataclass(frozen=True)
class Layer:
    id: str                 # snapshot file name and key in the manifest
    kind: str               # plan | plan_addition | area_regulations | plan_pending | zone | protected |
                            # natura2000 | national_interest
    title: str
    provider: str
    licence: str
    service: str            # "arcgis" (MapServer layer) or "wfs"
    url: str
    layer_id: int | None = None   # ArcGIS layer
    type_name: str = ""           # WFS feature type
    national: bool = False        # national layer: fetched in the kommun's envelope, kept if it meets the kommun
    complete: bool = False        # plans: every plan in force is in the layer, so no hit = outside detaljplan
    law: str | None = None        # default legal basis (national interests: the layer's paragraph)
    note: str | None = None       # caveat shown with every feature of the layer


def _uppsala(layer_id: int, id: str, kind: str, title: str, **extra) -> Layer:
    return Layer(id=id, kind=kind, title=title, provider="Uppsala kommun", licence="open data (opendata.uppsala.se)",
                 service="arcgis", url=UPPSALA_MAP, layer_id=layer_id, **extra)


def _riks(layer_id: int, id: str, title: str, law: str) -> Layer:
    return Layer(id=f"riks_{id}", kind="national_interest", title=title, provider="Boverket (sammanställning)",
                 licence="free (each agency's data)", service="arcgis", url=RIKSINTRESSEN, layer_id=layer_id,
                 national=True, law=law)


UPPSALA_LAYERS = [
    _uppsala(122, "plans", "plan", "Gällande detaljplaner", complete=True,
             note="The kommun's map of plans in force (old plans have interpreted boundaries)"),
    _uppsala(121, "plan_additions", "plan_addition", "Tillägg till detaljplan"),
    _uppsala(123, "area_regulations", "area_regulations", "Områdesbestämmelser"),
    _uppsala(113, "plans_pending", "plan_pending", "Pågående detaljplaner"),
    _uppsala(131, "zones_kvartersmark", "zone", "Kvartersmark (användning)"),
    _uppsala(128, "zones_allman_plats", "zone", "Allmän plats (användning)"),
    _uppsala(134, "zones_vatten", "zone", "Vattenområde (användning)"),
]

NATIONAL_LAYERS = [
    Layer(id="protected_areas", kind="protected", title="Skyddade områden (naturreservat, biotopskydd, ...)",
          provider="Naturvårdsverket", licence="CC0", service="wfs", url=NV_WFS,
          type_name="Naturvardsregistret_WFS:SkyddadeOmraden", national=True),
    Layer(id="natura2000", kind="natura2000", title="Natura 2000", provider="Naturvårdsverket", licence="CC0",
          service="wfs", url=N2000_WFS, type_name="N2000_WFS:N2000", national=True, law="MB 7 kap. 27-29 b §"),
    # Miljöbalken 3 kap.: areas the agencies designated; 4 kap.: areas named in the law itself
    _riks(12, "naturvard", "Riksintresse naturvård", "MB 3 kap. 6 §"),
    _riks(11, "friluftsliv", "Riksintresse friluftsliv", "MB 3 kap. 6 §"),
    _riks(13, "kulturmiljo", "Riksintresse kulturmiljövård", "MB 3 kap. 6 §"),
    _riks(16, "material", "Riksintresse värdefulla ämnen och material", "MB 3 kap. 7 §"),
    _riks(19, "vindbruk", "Riksintresse vindbruk", "MB 3 kap. 8 §"),
    _riks(150, "flygplats", "Riksintresse flygplats (befintligt markområde)", "MB 3 kap. 8 §"),
    _riks(153, "flygplats_plan", "Riksintresse flygplats (planerat markområde)", "MB 3 kap. 8 §"),
    _riks(155, "flygbuller70", "Flygbuller, maximal ljudnivå 70 dB(A)", "MB 3 kap. 8 §"),
    _riks(156, "flygbuller55", "Flygbuller, FBN 55 dB(A)", "MB 3 kap. 8 §"),
    _riks(9, "rennaring_karn", "Riksintresse rennäring (kärnområde)", "MB 3 kap. 5 §"),
    _riks(10, "rennaring", "Riksintresse rennäring", "MB 3 kap. 5 §"),
    _riks(92, "totalforsvar", "Riksintresse totalförsvar (på land)", "MB 3 kap. 9 §"),
    _riks(94, "totalforsvar_betydelse", "Område av betydelse för totalförsvaret", "MB 3 kap. 9 §"),
    _riks(118, "stopp_hoga", "Stoppområde för höga objekt (totalförsvaret)", "MB 3 kap. 9 §"),
    _riks(126, "civilt_forsvar", "Riksintresse totalförsvarets civila anläggningar", "MB 3 kap. 9 §"),
    _riks(169, "mb4_turism", "Turism och friluftsliv (MB 4 kap.)", "MB 4 kap. 2 §"),
    _riks(165, "mb4_obruten_kust", "Obruten kust", "MB 4 kap. 3 §"),
    _riks(164, "mb4_hogexploaterad_kust", "Högexploaterad kust", "MB 4 kap. 4 §"),
    _riks(170, "mb4_fjall", "Obrutet fjäll", "MB 4 kap. 5 §"),
    _riks(171, "mb4_vattendrag", "Skyddade vattendrag", "MB 4 kap. 6 §"),
    _riks(172, "mb4_nationalstadspark", "Nationalstadspark", "MB 4 kap. 7 §"),
]

# Pilot kommuner: own layers + who answers "which property is this" (until Lantmäteriet's services are approved)
PILOTS = {
    "0380": {"name": "Uppsala", "layers": UPPSALA_LAYERS, "property_service": "uppsala"},
}


def layers_for(code: str) -> list[Layer]:
    return PILOTS[code]["layers"] + NATIONAL_LAYERS


def layer_by_id(code: str, layer_id: str) -> Layer | None:
    return next((layer for layer in layers_for(code) if layer.id == layer_id), None)


def _first(props: dict, *keys: str):
    """First non-empty attribute among keys (case-insensitive): services name the same thing differently."""
    lowered = {k.lower(): v for k, v in props.items()}
    for key in keys:
        value = lowered.get(key.lower())
        if value not in (None, "", " "):
            return value
    return None


def _date(value) -> str | None:
    """'20020109', '2022-09-19' or an ArcGIS epoch in ms -> ISO date."""
    if value in (None, ""):
        return None
    text = str(value).strip()
    if text.isdigit() and len(text) == 8:
        return f"{text[:4]}-{text[4:6]}-{text[6:]}"
    if text.lstrip("-").isdigit() and len(text) >= 10:
        return datetime.fromtimestamp(int(text) / 1000, tz=UTC).date().isoformat()
    return text[:10]


def feature(layer: Layer, props: dict) -> dict:
    """Profile feature from a layer's raw attributes."""
    out = {"layer": layer.id, "kind": layer.kind, "layer_title": layer.title, "name": None, "ref": None,
           "type": None, "date": None, "status": None, "authority": None, "law": layer.law, "text": None,
           "url": None, "note": layer.note}
    if layer.kind in ("plan", "plan_addition", "area_regulations"):
        out.update(name=_first(props, "Plannamn"), ref=_first(props, "Aktbeteckning"),
                   type=_first(props, "Plantyp"), date=_date(_first(props, "LagaKraftDatum")),
                   url=_first(props, "UrlDokument"), text=_first(props, "AdminBestammelser", "Ovrigt"),
                   note=_first(props, "Kommentar") or layer.note)
    elif layer.kind == "plan_pending":
        out.update(name=_first(props, "Name"), ref=_first(props, "DiarieNummer"), status=_first(props, "Status"),
                   text=_first(props, "HUVUDSAKLIGT_SYFTE", "HandelseBeskrivning"))
    elif layer.kind == "zone":
        out.update(name=_first(props, "AnvBestammelse"), ref=_first(props, "AnvBeteckning"),
                   type=_first(props, "Anvandningstyp"), text=_first(props, "PlanBestammelser"),
                   note=_first(props, "Kommentar") or layer.note)
    elif layer.kind == "protected":
        nvrid = _first(props, "NVRID")
        out.update(name=_first(props, "NAMN"), ref=nvrid, type=_first(props, "SKYDDSTYP"),
                   status=_first(props, "BESLUTSSTATUS"), authority=_first(props, "BESLUTSMYNDIGHET"),
                   date=_date(_first(props, "URSPR_BESLUTSDATUM")),
                   url=f"https://skyddadnatur.naturvardsverket.se/sknat/?nvrid={nvrid}" if nvrid else None)
    elif layer.kind == "natura2000":
        code = _first(props, "OMRADESKOD")
        out.update(name=_first(props, "OMRADESNAMN"), ref=code, type=_first(props, "OMRADESTYP"),
                   authority=_first(props, "UPPGIFTSLAMNARE"),
                   url=f"https://natura2000.eea.europa.eu/Natura2000/SDF.aspx?site={code}" if code else None)
    elif layer.kind == "national_interest":
        description = _first(props, "BESKRIVNIN", "BESKRIVNING", "URL", "LANK")
        out.update(name=_first(props, "NAMN", "Namn", "OMRADESNAMN", "BENAMNING", "NAME") or layer.title,
                   ref=_first(props, "RIKSID", "ORGINALID", "OBJEKTID"),
                   type=_first(props, "AMNESOMRAD") or layer.title,
                   law=_first(props, "LAGRUM") or layer.law, date=_date(_first(props, "BESLUTSDAT")),
                   url=description if str(description or "").startswith("http") else None)
    return out
