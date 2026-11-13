"""corpus.chunk: statute chapters and sections, and the schema labels a chunk carries (#106)."""

import hashlib
import io
import json
from collections import Counter

from corpus.chunk import chunk_rows, keep_labelled, law_chunks
from corpus.common import stable_id
from localrag.index import chunk_text


def test_law_chapters():
    text = ("Källa: test\n\n"
            "1 kap.\n\n1 § Första kapitlet utan rubrik.\n\n"
            "3 kap. Grundläggande bestämmelser\n\n1 § Tredje kapitlet. Se 18 kap.\n\n"
            "4 kap. Särskilda bestämmelser för hushållning med mark och\n\nvatten för vissa områden\n\n"
            "Områden som i sin helhet är av riksintresse\n\n1 § Fjärde kapitlet.\n\n"
            "10 Kap. Bostadsarrende\n\n1 § Tionde kapitlet.\n\n"
            "14 kap.\n\nFastighetsbestämning\n\n1 § Fjortonde kapitlet.\n")
    chunks = law_chunks({"title": "Testlag", "text": text}, 1500)
    assert [c["section"] for c in chunks] == ["1 kap. 1 §", "3 kap. 1 §", "4 kap. 1 §", "10 kap. 1 §", "14 kap. 1 §"]
    assert chunks[2]["header"].startswith("Testlag, 4 kap. 1 § (4 kap. Särskilda bestämmelser för hushållning med mark "
                                          "och vatten för vissa områden")
    assert "Fastighetsbestämning" in chunks[4]["header"]


def test_law_reference_wrapped_after_kap():
    # "enligt 6 kap." ends a wrapped line: "35 § 4 miljöbalken" / "1 § 2 b." are not new sections (MBF 18 §, PBL 5:11 a)
    text = ("Källa: test\n\n5 kap. Detaljplan\n\n10 § Programmet.\n\n"
            "11 a § Kommunen ska undersöka enligt 6 kap.\n\n1 § 2 b. Kommunen ska avgöra frågan.\n\n"
            "11 b § Om genomförandet. Bestämmelser finns i 9 kap.\n\n12 § Kommunen ska samråda.\n\n"
            "13 § Andra stycket.\n\n1 § 1 och 3 gäller också.\n")
    chunks = law_chunks({"title": "Testlag", "text": text}, 1500)
    assert [c["section"] for c in chunks] == ["5 kap. 10 §", "5 kap. 11 a §", "5 kap. 11 b §", "5 kap. 12 §", "5 kap. 13 §"]
    assert chunks[1]["text"].endswith("enligt 6 kap. 1 § 2 b. Kommunen ska avgöra frågan.")
    assert chunks[4]["text"].endswith("1 § 1 och 3 gäller också.")


# --- schema labels (docs/source-chunk-schema.md, #106) -----------------------------------------------------------

LAW_TEXT = ("Testlag (2000:1)\nKälla: test\n\n1 kap. Inledande bestämmelser\n\n1 § Denna lag gäller mark.\n\n"
            "2 § Kommunen planlägger användningen av mark och vatten.\n")
PAGE_TEXT = ("Altan\n\nEn altan som är högre än 1,8 meter kräver bygglov. Kontakta bygglovsenheten innan du bygger.\n\n"
             "Avgift\n\nAvgiften för ett bygglov för en altan beräknas enligt kommunens taxa, som fullmäktige beslutar "
             "om varje år.")
PDF_TEXT = ("Detaljplan för Kumla-Stensta, Vallentuna kommun\n\nGRANSKNINGSHANDLING\n\nPlanens syfte\n\nSyftet med "
            "detaljplanen är att möjliggöra bostäder i form av friliggande villor med en största byggnadsarea om 200 "
            "kvadratmeter per fastighet.")
LABELS = {
    "law:testlag": {"place": "national", "fetched_at": "2026-10-06T19:30:23+00:00", "fetched_at_source": "file_mtime",
                    "plan_id": None, "plan_stage": None},
    "page:0115:abc": {"place": "Vallentuna", "fetched_at": "2026-10-23T19:16:50+00:00",
                      "fetched_at_source": "recorded", "plan_id": None, "plan_stage": None},
    "pdf:0115:def": {"place": "Vallentuna", "fetched_at": "2026-10-22T14:08:43+00:00",
                     "fetched_at_source": "file_mtime", "plan_id": "0123456789abcdef", "plan_stage": "review"},
}
# chunk_id and the digest of the embedded text (localrag.index.chunk_text) of each chunk, computed on main before the
# labels existed (5b4d9a3). The vectors of the 2.4M embedded chunks are keyed by chunk_id and re-embedded when that
# digest changes: if this test fails, adding or changing a label would re-embed the corpus.
EMBEDDED = [
    ("444d3c9eaf1649f4", "33dcc3763d4321e8"),
    ("ee99cb1fa007dc55", "0b81ecd145d4f79a"),
    ("f59c5e91b7b67fe1", "40dcf18fa3e764d6"),
    ("1d88be1012ec062f", "dcd39b323e43af28"),
    ("facdbe9e613de332", "623df132c640b7f0"),
]


def documents(labelled: bool = True) -> list[dict]:
    rows = [
        {"doc_id": "law:testlag", "kind": "law", "doc_type": "lag", "kommun_code": None, "kommun": None,
         "title": "Testlag (2000:1)", "url": "https://data.riksdagen.se/dokument/sfs-2000-1.html", "text": LAW_TEXT},
        {"doc_id": "page:0115:abc", "kind": "page", "doc_type": "bygglov", "kommun_code": "0115",
         "kommun": "Vallentuna", "title": "Bygglov för altan", "url": "https://www.vallentuna.se/bygglov/altan",
         "text": PAGE_TEXT},
        {"doc_id": "pdf:0115:def", "kind": "pdf", "doc_type": "detaljplan", "kommun_code": "0115",
         "kommun": "Vallentuna", "title": "Detaljplan för Kumla-Stensta, planbeskrivning",
         "url": "https://www.vallentuna.se/dp/kumla_planbeskrivning.pdf", "text": PDF_TEXT},
    ]
    return [{**row, **LABELS[row["doc_id"]]} if labelled else row for row in rows]


def embedded(chunks: list[dict]) -> list[tuple[str, str]]:
    return [(c["chunk_id"], hashlib.sha1(chunk_text(c).encode()).hexdigest()[:16]) for c in chunks]


def test_labels_leave_the_embedded_text_and_the_chunk_id_unchanged():
    labelled = list(chunk_rows(documents(), 1500, Counter()))
    unlabelled = list(chunk_rows(documents(labelled=False), 1500, Counter()))
    assert embedded(labelled) == EMBEDDED
    assert embedded(unlabelled) == EMBEDDED


def test_chunks_carry_copies_of_their_document_labels():
    chunks = list(chunk_rows(documents(), 1500, Counter()))
    for chunk in chunks:
        for label, value in LABELS[chunk["doc_id"]].items():
            assert chunk[label] == value
    law, plan = chunks[0], chunks[-1]
    assert law["place"] == "national" and law["kommun"] is None  # the kommun filters still see no kommun
    assert (plan["plan_id"], plan["plan_stage"]) == ("0123456789abcdef", "review")


def test_content_fingerprint_is_the_digest_inside_the_chunk_id():
    for chunk in chunk_rows(documents(), 1500, Counter()):
        assert chunk["content_sha1"] == hashlib.sha1(" ".join(chunk["text"].split()).lower().encode()).hexdigest()
        assert chunk["chunk_id"] == stable_id(chunk["doc_id"], str(chunk["chunk_index"]), chunk["content_sha1"])


def test_a_chunk_missing_a_required_label_is_rejected_and_reported():
    rows = documents()
    rows[1] = {**rows[1], "fetched_at": None}
    rows[2] = {**rows[2], "url": None, "place": None}
    counts, report = Counter(), io.StringIO()
    kept = list(keep_labelled(chunk_rows(rows, 1500, counts), counts, report))
    assert {c["doc_id"] for c in kept} == {"law:testlag"}
    rejected = [json.loads(line) for line in report.getvalue().splitlines()]
    assert [r["missing"] for r in rejected] == [["fetched_at"], ["fetched_at"], ["url", "place"]]
    assert counts["rejected"] == 3 and counts["missing fetched_at"] == 2 and counts["missing place"] == 1
    assert counts["law"] == 2


def test_a_rejected_chunk_still_hides_its_later_copies():
    # Rejecting before the duplicate check would keep the second copy under a new chunk id, which has no vector
    first, copy = documents()[1], {**documents()[1], "doc_id": "page:0115:copy"}
    rows = [{**first, "place": None}, copy]
    counts = Counter()
    kept = list(keep_labelled(chunk_rows(rows, 1500, counts), counts, io.StringIO()))
    assert kept == [] and counts["duplicates"] == 2 and counts["rejected"] == 2
