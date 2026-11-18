"""Plan dates of the detaljplan registry (#121): every date a registry build stores is YYYY-MM-DD or empty, whatever
form the plan's documents wrote it in. No network, no database (PCR-0011)."""

import json
from datetime import UTC, datetime

import pytest

from corpus import check, plans


def head(*texts: str) -> dict:
    """The registry entry of a plan whose one document holds the given text."""
    document = {"doc_id": "pdf:0115:a", "kommun_code": "0115", "kommun": "Vallentuna", "url": "https://k.se/a.pdf",
                "title": "Detaljplan för Ekbacken", "pages": 3, "needs_ocr": False, "text": "\n".join(texts)}
    return plans.plan_head("0115", "Ekbacken", [document], None, [])


# --- the date reader ------------------------------------------------------------------------------------------------

def test_reader_passes_an_iso_date_through():
    assert plans.read_date("2019-05-02") == "2019-05-02"


@pytest.mark.parametrize("text", ["5 mars 2010", "5 mar 2010", "05 mars 2010"])
def test_reader_reads_a_swedish_month_name_in_full_or_abbreviated(text):
    assert plans.read_date(text) == "2010-03-05"


@pytest.mark.parametrize("text, expected", [("14 dec 2004", "2004-12-14"), ("3 sept 2011", "2011-09-03"),
                                            ("9 oktober 1999", "1999-10-09"), ("1 maj 2015", "2015-05-01")])
def test_reader_reads_other_month_spellings(text, expected):
    assert plans.read_date(text) == expected


@pytest.mark.parametrize("text", ["2010.03.05", "2010/03/05", "2010-03-05", "05.03.2010", "05/03/2010", "05-03-2010"])
def test_reader_reads_three_numbers_with_any_separator_the_month_in_the_middle(text):
    assert plans.read_date(text) == "2010-03-05"


@pytest.mark.parametrize("text", ["31 februari 2001", "2019-13-45", "2019-02-30", "5 marsh 2010", "5 March 2010",
                                  "5 mars 9100", "45.13.2010"])
def test_reader_gives_nothing_for_a_date_that_does_not_exist(text):
    assert plans.read_date(text) is None


def test_reader_accepts_years_from_1700_to_the_current_year_only():
    this_year = datetime.now(UTC).year
    assert plans.read_date("1700-01-01") == "1700-01-01"
    assert plans.read_date("1699-12-31") is None
    assert plans.read_date(f"{this_year}-01-01") == f"{this_year}-01-01"
    assert plans.read_date(f"{this_year + 1}-01-01") is None


def test_reader_tolerates_a_line_break_inside_the_date():
    assert plans.read_date("28\napril 2001") == "2001-04-28"


@pytest.mark.parametrize("text", ["20100305", "5/3 -10", "5.3.10", "", "ingen"])
def test_reader_does_not_read_digit_only_dates_or_two_digit_years(text):
    assert plans.read_date(text) is None


# --- the registry build ---------------------------------------------------------------------------------------------

def test_registry_stores_a_laga_kraft_date_written_with_a_month_name_as_iso():
    assert head("Detaljplanen vann laga kraft den 28 april 2001.")["laga_kraft"] == "2001-04-28"


def test_registry_stores_a_laga_kraft_date_written_with_dots_as_iso():
    assert head("Laga kraft: 05.03.2010")["laga_kraft"] == "2010-03-05"


def test_registry_reads_a_laga_kraft_date_cut_by_a_line_break():
    assert head("Laga kraft 28\napril 2001")["laga_kraft"] == "2001-04-28"


def test_registry_stores_an_adoption_date_in_any_form_as_iso():
    assert head("Antagen av kommunfullmäktige 14 dec 2004")["adopted"] == "2004-12-14"
    assert head("Antagandebeslut 2004/12/14")["adopted"] == "2004-12-14"


def test_registry_finds_the_adoption_date_after_antaget():
    assert head("Detaljplanen antaget 2004-12-14")["adopted"] == "2004-12-14"


def test_registry_stores_nothing_for_a_date_that_does_not_exist_and_keeps_the_status():
    entry = head("Laga kraft 31 februari 2001", "Antagen 2019-13-45")
    assert (entry["laga_kraft"], entry["adopted"], entry["status"]) == (None, None, "in_force")


def test_registry_takes_the_first_date_when_the_documents_hold_several():
    assert head("Antagen 5 mars 2010", "Antagen 2012-01-01")["adopted"] == "2010-03-05"


# --- the data check -------------------------------------------------------------------------------------------------

def _plans_file(tmp_path, monkeypatch, dates: list[tuple[str | None, str | None]]):
    rows = [{"name": f"plan {i}", "kommun": "Vallentuna", "documents": [{"doc_id": "d"}], "provisions": [],
             "status": "in_force", "laga_kraft": laga, "adopted": adopted} for i, (laga, adopted) in enumerate(dates)]
    (tmp_path / "plans.jsonl").write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    monkeypatch.setattr(check, "DATA_DIR", tmp_path)
    monkeypatch.setattr(check, "CHECK_PATH", tmp_path / "check.json")


@pytest.mark.parametrize("laga, adopted", [("5 mars 2010", None), (None, "05.03.2010"), ("2019-5-2", None)])
def test_check_reports_only_the_plans_whose_date_is_not_iso(tmp_path, monkeypatch, laga, adopted):
    """The plans with an ISO or an empty date pass; the one with another form is the single error."""
    _plans_file(tmp_path, monkeypatch, [("2019-05-02", None), (None, "2004-12-14"), (None, None), (laga, adopted)])
    report = check.Report()
    check.check_plans(report)
    errors = [line for line in report.lines if line["level"] == "ERROR"]
    assert len(errors) == 1 and "date" in errors[0]["message"]
    assert errors[0]["count"] == 1


def test_check_exits_with_failure_on_a_plan_date_that_is_not_iso(tmp_path, monkeypatch):
    _plans_file(tmp_path, monkeypatch, [("5 mars 2010", None)])
    monkeypatch.setattr("sys.argv", ["corpus.check", "--only", "plans"])
    with pytest.raises(SystemExit) as exit_info:
        check.main()
    assert exit_info.value.code == 1
