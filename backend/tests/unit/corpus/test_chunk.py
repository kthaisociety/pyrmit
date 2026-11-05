"""corpus.chunk: statute chapters and sections, including references wrapped after "kap."."""

from corpus.chunk import law_chunks


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
