"""
Fetch the Swedish municipalities (kommuner) and their localities from Wikidata.

The localities (tätorter, småorter, villages) make a gazetteer: a question about
"Veda" or "Lindholmen" can then be mapped to Vallentuna kommun for filtering.

    cd backend && python -m corpus.municipalities
"""

import json
import re
from collections import defaultdict

import httpx

from corpus.common import MUNICIPALITIES_PATH, USER_AGENT

SPARQL_URL = "https://query.wikidata.org/sparql"

_MUNICIPALITIES_QUERY = """
SELECT ?k ?kLabel ?code ?site ?countyLabel WHERE {
  ?k wdt:P31 wd:Q127448 ; wdt:P525 ?code .
  FILTER NOT EXISTS { ?k wdt:P576 ?dissolved }
  OPTIONAL { ?k wdt:P856 ?site }
  OPTIONAL { ?k wdt:P131 ?county . ?county wdt:P31 wd:Q200547 }
  SERVICE wikibase:label { bd:serviceParam wikibase:language "sv". }
}"""

# Populated places located in a municipality: tätort, småort, village, locality, district
_LOCALITIES_QUERY = """
SELECT DISTINCT ?k ?placeLabel WHERE {
  ?k wdt:P31 wd:Q127448 .
  ?place wdt:P131 ?k ; wdt:P31 ?type ; rdfs:label ?placeLabel .
  VALUES ?type { wd:Q12813115 wd:Q14839548 wd:Q532 wd:Q3957 wd:Q123705 wd:Q486972 wd:Q2154459 }
  FILTER(LANG(?placeLabel) = "sv")
}"""


def sparql(query: str) -> list[dict]:
    response = httpx.get(
        SPARQL_URL,
        params={"query": query},
        headers={"Accept": "application/sparql-results+json", "User-Agent": USER_AGENT},
        timeout=180,
    )
    response.raise_for_status()
    return [{key: value["value"] for key, value in row.items()} for row in response.json()["results"]["bindings"]]


def short_name(label: str) -> str:
    """'Vallentuna kommun' -> 'Vallentuna', 'Göteborgs kommun' -> 'Göteborg', 'Region Gotland' -> 'Gotland'."""
    name = re.sub(r"^Region ", "", label)
    name = re.sub(r" (stad|kommun)$", "", name)
    if label.endswith(" kommun") and name.endswith("s") and not name.endswith(("ss", "us", "ås", "äs")):
        name = name[:-1]
    return name


def pick_site(sites: set[str]) -> str | None:
    if not sites:
        return None
    # Prefer https, then the shortest (the main domain rather than a sub-site)
    return sorted(sites, key=lambda site: (not site.startswith("https"), len(site)))[0]


def main() -> None:
    rows = sparql(_MUNICIPALITIES_QUERY)
    by_code: dict[str, dict] = {}
    sites: dict[str, set[str]] = defaultdict(set)
    # Some entities still carry their pre-1997 code (e.g. Skåne 11xx -> 12xx): keep the newest
    current_code: dict[str, str] = {}
    for row in rows:
        if re.fullmatch(r"\d{4}", row["code"]):
            current_code[row["k"]] = max(current_code.get(row["k"], ""), row["code"])
    for row in rows:
        code = row["code"]
        if current_code.get(row["k"]) != code:
            continue
        by_code.setdefault(code, {
            "code": code,
            "wikidata": row["k"].rsplit("/", 1)[-1],
            "name": row["kLabel"],
            "short_name": short_name(row["kLabel"]),
            "county": row.get("countyLabel"),
        })
        if row.get("countyLabel"):
            by_code[code]["county"] = row["countyLabel"]
        if row.get("site"):
            sites[code].add(row["site"].rstrip("/"))

    qid_to_code = {entry["wikidata"]: code for code, entry in by_code.items()}
    localities: dict[str, set[str]] = defaultdict(set)
    for row in sparql(_LOCALITIES_QUERY):
        code = qid_to_code.get(row["k"].rsplit("/", 1)[-1])
        label = row.get("placeLabel", "")
        if code and label and not re.fullmatch(r"Q\d+", label):
            localities[code].add(label)

    municipalities = []
    for code, entry in sorted(by_code.items()):
        entry["website"] = pick_site(sites[code])
        entry["localities"] = sorted(localities[code])
        municipalities.append(entry)

    MUNICIPALITIES_PATH.parent.mkdir(parents=True, exist_ok=True)
    MUNICIPALITIES_PATH.write_text(json.dumps(municipalities, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{len(municipalities)} municipalities, {sum(len(m['localities']) for m in municipalities)} localities, "
          f"{sum(1 for m in municipalities if not m['website'])} without website -> {MUNICIPALITIES_PATH}")


if __name__ == "__main__":
    main()
