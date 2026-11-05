"""A fake hosted corpus and plan registry for Uppsala's fake snapshot (tests.unit.place.snapshot), shared by the tests of
place.plan_links and place.profile. A SQLite chunks table instead of a real database (PCR-0011)."""

import json
import sqlite3

from tests.unit.place.snapshot import write_snapshot

PAGE = "https://www.uppsala.se/detaljplaner/{}/"
ATLE = "0380-P2002/5"
STADSPLAN = "0380-P1990/3"
MAP_ID, DESCRIPTION_ID, STADSPLAN_ID = "pdf:0380:map", "pdf:0380:description", "pdf:0380:stadsplan"
CHUNKS = [
    (MAP_ID, 0, "pdf", "detaljplan", "0380", "Plankarta (PDF, 3 MB)", "https://www.uppsala.se/atle/plankarta.pdf", "Karta"),
    (DESCRIPTION_ID, 0, "pdf", "detaljplan", "0380", "Planbeskrivning (PDF)", "https://www.uppsala.se/atle/beskrivning.pdf",
     "Beskrivning"),
    (DESCRIPTION_ID, 1, "pdf", "detaljplan", "0380", "Planbeskrivning (PDF)", "https://www.uppsala.se/atle/beskrivning.pdf",
     "Fortsättning"),
    (STADSPLAN_ID, 0, "pdf", "detaljplan", "0380", "Stadsplan (PDF)", "https://www.uppsala.se/k/stadsplan.pdf", "Karta"),
    ("pdf:0380:lost", 0, "pdf", "detaljplan", "0380", "Inget plan", "https://www.uppsala.se/x/annat.pdf", "Annat"),
    ("page:0380:atle", 0, "page", "detaljplan", "0380", "Atle", PAGE.format("atle"), "Sidan"),
    ("pdf:0182:other", 0, "pdf", "detaljplan", "0182", "Nacka", "https://www.nacka.se/a.pdf", "Nacka"),
]
PLANS = [
    {"plan_id": "a", "kommun_code": "0380", "name": "Atle", "page": {"url": PAGE.format("atle")},
     "documents": [{"doc_id": DESCRIPTION_ID, "role": "planbeskrivning"}, {"doc_id": MAP_ID, "role": "plankarta"}]},
    {"plan_id": "s", "kommun_code": "0380", "name": "Kungsängen", "page": {"url": PAGE.format("kungsangen")},
     "documents": [{"doc_id": STADSPLAN_ID, "role": "plankarta"}]},
    {"plan_id": "g", "kommun_code": "0380", "name": "Grannplanen", "page": {"url": PAGE.format("granne")},
     "documents": [{"doc_id": "pdf:0380:not-loaded", "role": "plankarta"}]},
]


class FakeCorpus:
    """The hosted corpus's read side (PgStore.query) on a SQLite chunks table."""

    def __init__(self, rows=CHUNKS):
        self.connection = sqlite3.connect(":memory:", check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("CREATE TABLE chunks (doc_id, chunk_index, kind, doc_type, kommun_code, title, url, text)")
        self.connection.executemany("INSERT INTO chunks VALUES (?,?,?,?,?,?,?,?)", rows)

    def query(self, sql, params=()):
        return self.connection.execute(sql, tuple(params)).fetchall()


class DownCorpus:
    def query(self, sql, params=()):
        raise OSError("connection refused")


def plans_of(code):
    return [plan for plan in PLANS if plan["kommun_code"] == code]


def hosted_snapshot(root):
    """Uppsala's fake snapshot with plan pages: Atle's and the stadsplan's in the registry with documents, the neighbour's
    without any in the corpus, the tillägg's outside the registry."""
    write_snapshot(root)
    (root / "0380" / "plan_pages.json").write_text(json.dumps(
        {ATLE: PAGE.format("atle"), STADSPLAN: PAGE.format("kungsangen"), "0380-P2010/1": PAGE.format("granne"),
         "0380-P2012/9": PAGE.format("not-in-registry")}), encoding="utf-8")
    return root


def lookup(doc_ids):
    return {row["doc_id"]: {"title": row["title"], "url": row["url"]} for row in FakeCorpus().query(
        f"SELECT DISTINCT doc_id, title, url FROM chunks WHERE doc_id IN ({','.join('?' * len(doc_ids))})", doc_ids)}
