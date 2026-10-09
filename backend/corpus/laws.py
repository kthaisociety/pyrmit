"""
Download consolidated Swedish statutes (SFS) as plain text from the Riksdagen open data API.

The texts are current consolidated versions ("t.o.m. SFS ..."), unlike the older copies
in the database, and keep the "N kap." / "N §" layout that corpus.chunk relies on.

    cd backend && python -m corpus.laws
"""

import json

import httpx

from corpus.common import LAWS_DIR, USER_AGENT

# SFS number -> short slug. The first eight are the laws already in the database.
LAWS = {
    "2010:900": "plan_och_bygglag",
    "1998:808": "miljobalken",
    "1970:994": "jordabalken",
    "1970:988": "fastighetsbildningslag",
    "1991:614": "bostadsrattslag",
    "1972:719": "expropriationslag",
    "1973:1149": "anlaggningslag",
    # Added for the use case (permits, sewage, shared facilities, heritage, assessments)
    "2011:338": "plan_och_byggforordning",
    "1998:899": "forordning_miljofarlig_verksamhet_halsoskydd",
    "2006:412": "lag_allmanna_vattentjanster",
    "1973:1150": "lag_forvaltning_samfalligheter",
    "1973:1144": "ledningsrattslag",
    "1988:950": "kulturmiljolag",
    "2017:966": "miljobedomningsforordning",
    "2013:251": "miljoprovningsforordning",
}

API = "https://data.riksdagen.se"


def main() -> None:
    LAWS_DIR.mkdir(parents=True, exist_ok=True)
    index = []
    with httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=120, follow_redirects=True) as client:
        for sfs, slug in LAWS.items():
            year, number = sfs.split(":")
            doc_id = f"sfs-{year}-{number}"
            text = client.get(f"{API}/dokument/{doc_id}.text").text
            title = text.splitlines()[0].strip() if text else slug
            (LAWS_DIR / f"{slug}.txt").write_text(text, encoding="utf-8")
            index.append({"slug": slug, "sfs": sfs, "title": title, "url": f"https://data.riksdagen.se/dokument/{doc_id}.html"})
            print(f"{sfs:<10} {title} ({len(text) // 1000} kB)")
    (LAWS_DIR / "index.json").write_text(json.dumps(index, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
