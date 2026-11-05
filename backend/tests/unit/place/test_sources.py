"""place.sources: the plans a pilot kommun's plan row says it is read together with. No real services (PCR-0011)."""

import pytest

from place.sources import feature, layer_by_id


@pytest.mark.parametrize(("note", "named"), [
    ("gäller tillsammans med 0380-P99/22 och 03-89:387", ["0380-P99/22", "03-89:387"]),
    ("Gäller tillsammans med ÄDP 0380-P2001/14", ["0380-P2001/14"]),
    ("Gäller tillsammans med 0380-P2012/26, 0380-P2013/9", ["0380-P2012/26", "0380-P2013/9"]),
    ("Gäller tisllsammans med 0380-P2005/1", ["0380-P2005/1"]),      # a typo in the layer
    ("Gäller tillsammans med 00/20086", []),                         # a diary number, not an aktbeteckning
    ("Gäller tillsammans med 00/20086-1", []),                       # nor is the end of a longer number
    ("Inlagd i samband med ÖP-arbete 2005, Kopierad från LMV", []),
    (None, []),
])
def test_a_plan_row_names_the_plans_in_its_note(note, named):
    assert feature(layer_by_id("0380", "plan_additions"), {"Ovrigt": note})["named_plans"] == named


def test_a_note_is_read_when_the_row_also_has_administrative_provisions():
    props = {"AdminBestammelser": "Genomförandetid 5 år", "Ovrigt": "Läses tillsammans med 0380-354"}
    assert feature(layer_by_id("0380", "plan_additions"), props)["named_plans"] == ["0380-354"]
