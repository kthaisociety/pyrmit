"""#58: the agent reads the pinned plans instead of searching for them. A fake corpus, fake agent and fake judge: no real
services (PCR-0011)."""

import json
import sqlite3
from types import SimpleNamespace

import pytest

import agentic.agent as agent
from agentic import tools as tools_module
from agentic.tools import CorpusTools, _DiskCorpus, _MemoryCorpus
from localrag.store import DiskStore
from place import bench_answers
from place.bench_answers import AnswerBench, compare, jobs, prompt, run_bench, scores
from place.context import NO_PIN_HINT, place_context, question_with_place
from place.profile import CorpusUnavailable, build_profile
from place.store import PlaceStore
from tests.test_agent_images import FakeCall
from tests.unit.place.snapshot import LAYERS, PIN, collection, fake_property, no_remains, plan, square, write_snapshot

MAP, DESCRIPTION, OLD, ADDITION, ELSEWHERE = ("pdf:0380:map", "pdf:0380:description", "pdf:0380:old", "pdf:0380:addition",
                                              "pdf:0380:elsewhere")
PAGE = "https://www.uppsala.se/detaljplan/?aktbeteckning="
ATLE, STADSPLAN, TILLAGG, FAR = "0380-P2002/5", "0380-P1990/3", "0380-P2012/9", "0380-P1980/1"
LINKS = {ATLE: [(MAP, "plankarta"), (DESCRIPTION, "planbeskrivning")], STADSPLAN: [(OLD, "plankarta")],
         TILLAGG: [(ADDITION, "plankarta")], FAR: [(ELSEWHERE, "plankarta")]}
TITLES = {MAP: "Plankarta", DESCRIPTION: "Planbeskrivning", OLD: "Stadsplan", ADDITION: "Tillägg", ELSEWHERE: "Annan plan"}


def chunk(doc_id, index, section, text):
    return {"chunk_id": f"{doc_id[-4:]}{index:012d}", "doc_id": doc_id, "chunk_index": index, "section": section,
            "text": text, "header": "", "title": TITLES[doc_id], "kind": "pdf", "doc_type": "detaljplan",
            "kommun": "Uppsala", "kommun_code": "0380", "url": f"https://www.uppsala.se/{doc_id[9:]}.pdf"}


CHUNKS = [chunk(DESCRIPTION, 1, "Planens syfte", "Andra stycket"), chunk(DESCRIPTION, 0, "Bakgrund", "Första stycket"),
          chunk(DESCRIPTION, 2, "Planens syfte", "Tredje stycket"), chunk(MAP, 0, None, "Bestämmelser: e1 300 m²")]
CHUNK_COLUMNS = ("chunk_id", "doc_id", "chunk_index", "section", "text", "header", "title", "kind", "doc_type", "kommun",
                 "kommun_code", "url")


def tools_on(chunks=CHUNKS):
    tools = CorpusTools.__new__(CorpusTools)
    tools.corpus = _MemoryCorpus(chunks)
    return tools


def hosted_tools(chunks=CHUNKS):
    """The tools over the store the hosted corpus reads through: SQL on a chunks table, nothing else."""
    connection = sqlite3.connect(":memory:", check_same_thread=False)
    connection.row_factory = sqlite3.Row
    connection.execute(f"CREATE TABLE chunks ({', '.join(CHUNK_COLUMNS)})")
    connection.executemany(f"INSERT INTO chunks VALUES ({','.join('?' * len(CHUNK_COLUMNS))})",
                           [tuple(row[column] for column in CHUNK_COLUMNS) for row in chunks])
    store = SimpleNamespace(query=lambda sql, params=(): connection.execute(sql, tuple(params)).fetchall(),
                            chunk=lambda chunk_id: next((c for c in chunks if c["chunk_id"] == chunk_id), None),
                            _chunk=DiskStore._chunk)
    tools = CorpusTools.__new__(CorpusTools)
    tools.corpus = _DiskCorpus(store)
    return tools


def documents(doc_ids):
    return {doc_id: {"title": TITLES[doc_id], "url": f"https://www.uppsala.se/{doc_id[9:]}.pdf"} for doc_id in doc_ids}


def snapshot(root, addition_note=None, plan_note=None, links=True):
    """Uppsala's fake snapshot. At the pin: the stadsplan (1990), Atle (2002) and the tillägg (2012)."""
    atle = {**plan(ATLE, "Del av Atle", "20020109"), "Ovrigt": plan_note}
    addition = {**plan(TILLAGG, "Tillägg till stadsplan", "20120601"), "Ovrigt": addition_note}
    layers = {**LAYERS,
              "plans": collection((square(17.635, 59.845, 17.650, 59.855), plan(STADSPLAN, "Stadsplan för Kungsängen", "19900312")),
                                  (square(17.6405, 59.8495, 17.6430, 59.8515), atle),
                                  (square(17.70, 59.90, 17.71, 59.91), plan(FAR, "Annan plan", "19800101"))),
              "plan_additions": collection((square(17.639, 59.849, 17.643, 59.852), addition))}
    store = write_snapshot(root, layers=layers)
    if links:
        rows = [{"key": ref, "ref": ref, "doc_id": doc_id, "level": "link", "review": False, "role": role, "date": "2026-11-05"}
                for ref, linked in LINKS.items() for doc_id, role in linked]
        (root / "0380" / "plan_links.jsonl").write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")
    return PlaceStore(root) if links else store


def profile_at(store, corpus_documents=documents):
    return build_profile(*PIN, store=store, corpus_documents=corpus_documents, property_at=fake_property,
                         plan_registry=lambda code: [], ancient_remains_at=no_remains)


def line_of(text, ref):
    return next(line for line in text.splitlines() if f" {ref} " in line and line.startswith("- "))


def row_of(profile, ref):
    return next(row for row in profile["plans"] if row["ref"] == ref)


# --- the statement of the plans at the pin --------------------------------------------------------------------------

def test_the_statement_gives_every_plan_its_type_date_and_documents(tmp_path):
    """Each plan at the pin is stated with its type, its date and the ids and roles of its documents."""
    text = place_context(profile_at(snapshot(tmp_path)))
    assert "Detaljplan 0380-P2002/5" in text and "Tillägg 0380-P2012/9" in text and "Detaljplan 0380-P1990/3" in text
    atle = line_of(text, ATLE)
    assert "2002-01-09" in atle
    assert f"plankarta {MAP}" in atle and f"planbeskrivning {DESCRIPTION}" in atle


def test_the_statement_says_how_to_read_a_plan(tmp_path):
    """A plan with documents is stated with the call that reads them, plan map first."""
    atle = line_of(place_context(profile_at(snapshot(tmp_path))), ATLE)
    assert f"read_plan(doc_ids=['{MAP}', '{DESCRIPTION}'])" in atle


def test_a_pinned_plan_without_text_is_stated_as_not_read_with_the_kommuns_link(tmp_path):
    """A plan with no document in the corpus is named, stated as not read, with the kommun's link and no read call."""
    def no_documents(doc_ids):
        return {}
    atle = line_of(place_context(profile_at(snapshot(tmp_path), corpus_documents=no_documents)), ATLE)
    assert "Del av Atle" in atle and "text not read" in atle.lower()
    assert f"{PAGE}{ATLE}" in atle and "read_plan" not in atle


def test_a_plan_is_stated_as_not_read_when_the_corpus_cannot_be_reached(tmp_path):
    """A corpus that cannot be reached leaves the plans stated as not read, each with the kommun's link."""
    def down(doc_ids):
        raise CorpusUnavailable("down")
    atle = line_of(place_context(profile_at(snapshot(tmp_path), corpus_documents=down)), ATLE)
    assert "text not read" in atle.lower() and f"{PAGE}{ATLE}" in atle


def test_an_install_without_a_link_table_states_the_plans_as_not_read(tmp_path):
    """Before the link table has reached this install the plans are stated as not read, without a failure."""
    atle = line_of(place_context(profile_at(snapshot(tmp_path, links=False))), ATLE)
    assert "text not read" in atle.lower() and f"{PAGE}{ATLE}" in atle


# --- an amendment and the plan it amends ----------------------------------------------------------------------------

def test_an_amendment_reads_with_the_plan_its_row_names(tmp_path):
    """The row's "Gäller tillsammans med" decides the plan an amendment is read with."""
    profile = profile_at(snapshot(tmp_path, addition_note=f"Gäller tillsammans med {ATLE}"))
    assert [plan_["ref"] for plan_ in row_of(profile, TILLAGG)["read_with"]] == [ATLE]


def test_an_amendment_reads_with_a_named_plan_that_is_not_at_the_pin(tmp_path):
    """The plan an amendment names brings its documents even when its polygon misses the pin."""
    profile = profile_at(snapshot(tmp_path, addition_note=f"Läses tillsammans med {FAR}"))
    read_with = row_of(profile, TILLAGG)["read_with"]
    assert read_with[0]["ref"] == FAR and [d["doc_id"] for d in read_with[0]["corpus_documents"]] == [ELSEWHERE]


def test_an_amendment_that_names_no_plan_reads_with_the_older_plans_at_the_pin(tmp_path):
    """Without a named plan an amendment reads with the older plans at the pin, newest first."""
    profile = profile_at(snapshot(tmp_path))
    assert [plan_["ref"] for plan_ in row_of(profile, TILLAGG)["read_with"]] == [ATLE, STADSPLAN]


def test_a_plan_naming_an_amendment_elsewhere_does_not_bring_it_in(tmp_path):
    """A plan reads only with the plans it names that are also at the pin."""
    profile = profile_at(snapshot(tmp_path, plan_note=f"Gäller tillsammans med {FAR}, {TILLAGG}"))
    assert [plan_["ref"] for plan_ in row_of(profile, ATLE)["read_with"]] == [TILLAGG]


def test_the_statement_reads_an_amendment_together_with_the_plan_it_amends(tmp_path):
    """The amendment's read call carries its own documents, then those of the plan it amends."""
    text = place_context(profile_at(snapshot(tmp_path, addition_note=f"Gäller tillsammans med {ATLE}")))
    addition = line_of(text, TILLAGG)
    assert f"read together with {ATLE}" in addition.lower()
    assert f"read_plan(doc_ids=['{ADDITION}', '{MAP}', '{DESCRIPTION}'])" in addition


def test_a_named_plan_without_text_is_stated_as_not_read_on_the_amendment(tmp_path):
    """A named plan the corpus does not hold is named on the amendment as not read."""
    text = place_context(profile_at(snapshot(tmp_path, addition_note="Gäller tillsammans med 03-89:387")))
    assert "03-89:387" in line_of(text, TILLAGG) and "not read" in line_of(text, TILLAGG).split("03-89:387")[1]


# --- reading a plan's documents -------------------------------------------------------------------------------------

@pytest.mark.parametrize("make_tools", [tools_on, hosted_tools])
def test_read_plan_gives_the_documents_in_reading_order(make_tools):
    """The documents come in the order asked for, each one's chunks in chunk order, however they are stored."""
    result = make_tools().read_plan([MAP, DESCRIPTION])
    order = [result.text.index(words) for words in ("e1 300 m²", "Första stycket", "Andra stycket", "Tredje stycket")]
    assert order == sorted(order)


def test_read_plan_returns_the_chunks_it_shows_with_their_citations():
    """Every chunk shown is citeable: tagged [c:<id>] and among the result's chunk ids."""
    result = tools_on().read_plan([DESCRIPTION])
    assert len(result.chunk_ids) == 3
    assert all(f"[c:{chunk_id}]" in result.text for chunk_id in result.chunk_ids)


def test_read_plan_lists_the_headings_of_a_document():
    """Read whole, each document's headings come first, so a later call can ask for one section."""
    text = tools_on().read_plan([DESCRIPTION]).text
    assert text.index("Planens syfte") < text.index("Första stycket") and "Bakgrund" in text


def test_read_plan_reads_one_section():
    """With a section only the chunks under matching headings come, ignoring case."""
    result = tools_on().read_plan([DESCRIPTION], section="planens SYFTE")
    assert "Andra stycket" in result.text and "Tredje stycket" in result.text and "Första stycket" not in result.text
    assert len(result.chunk_ids) == 2


def test_read_plan_says_which_headings_there_are_when_a_section_is_not_found():
    """A section no heading contains is a not_found error listing the headings."""
    result = tools_on().read_plan([DESCRIPTION], section="Parkering")
    assert result.error == "not_found" and "Planens syfte" in result.text and "Bakgrund" in result.text


def test_read_plan_reads_a_long_document_in_pieces_every_chunk_once(monkeypatch):
    """Past the limit the text ends with the call that continues; following it reads every chunk exactly once."""
    monkeypatch.setattr(tools_module, "PLAN_READ_LIMIT", 40)
    tools = tools_on()
    seen, start = [], 0
    for _ in range(5):
        result = tools.read_plan([MAP, DESCRIPTION], start=start)
        seen += result.chunk_ids
        if "start=" not in result.text:
            break
        start = int(result.text.rsplit("start=", 1)[1].split(")")[0])
    assert sorted(seen) == sorted(row["chunk_id"] for row in CHUNKS)
    assert len(seen) == len(set(seen))


def test_read_plan_shows_a_chunk_longer_than_the_limit(monkeypatch):
    """A chunk over the limit is still shown: a call always moves on."""
    monkeypatch.setattr(tools_module, "PLAN_READ_LIMIT", 5)
    assert len(tools_on().read_plan([DESCRIPTION]).chunk_ids) == 1


def test_read_plan_takes_ids_as_the_model_writes_them():
    """One id, a comma-separated string and ids copied with their "doc " all work."""
    assert len(tools_on().read_plan(DESCRIPTION).chunk_ids) == 3
    assert len(tools_on().read_plan(f"{MAP}, {DESCRIPTION}").chunk_ids) == 4
    assert len(tools_on().read_plan([f"doc {MAP}"]).chunk_ids) == 1


def test_read_plan_names_an_id_it_does_not_hold_and_reads_the_rest():
    """An unknown id among known ones is named and skipped."""
    result = tools_on().read_plan(["pdf:0380:gone", MAP])
    assert "pdf:0380:gone" in result.text and len(result.chunk_ids) == 1 and not result.error


@pytest.mark.parametrize(("arguments", "error"), [({"doc_ids": []}, "bad_args"), ({"doc_ids": ["pdf:0380:gone"]}, "unknown_id"),
                                                  ({"doc_ids": [MAP], "start": 9}, "bad_args")])
def test_read_plan_fails_in_words(arguments, error):
    """No ids, only unknown ids and a start past the end come back as errors the agent can read."""
    assert tools_on().read_plan(**arguments).error == error


def test_read_plan_needs_nothing_but_the_corpus(monkeypatch, tmp_path):
    """No registry, snapshot or crawled file is touched: the hosted corpus is enough."""
    def on_disk(*args, **kwargs):
        raise AssertionError("read_plan went to a local file")
    monkeypatch.setattr(tools_module, "PLANS_PATH", tmp_path / "missing.jsonl")
    monkeypatch.setattr(tools_module, "pdf_path", on_disk)
    monkeypatch.setattr(tools_module, "ocr_path", on_disk)
    assert len(hosted_tools().read_plan([MAP, DESCRIPTION]).chunk_ids) == 4


# --- the agent --------------------------------------------------------------------------------------------------------

class ReadingClient:
    """A fake model: reads the plan, then says it is ready."""

    def __init__(self):
        self.turns = [[FakeCall(name="read_plan", arguments=json.dumps({"doc_ids": [DESCRIPTION]}), call_id="1")],
                      [FakeCall(name="answer_ready", arguments=json.dumps({"mode": "verdict"}), call_id="2")]]
        self.offered = None
        self.responses = SimpleNamespace(create=self.create)

    def create(self, input, stream=False, tools=None, **kwargs):
        usage = SimpleNamespace(input_tokens=1, output_tokens=1, output_tokens_details=None, cost=0)
        if stream:
            return iter([SimpleNamespace(type="response.output_text.delta", delta="Answer."),
                         SimpleNamespace(type="response.completed", response=SimpleNamespace(usage=usage))])
        self.offered = {tool["name"] for tool in tools}
        return SimpleNamespace(output=self.turns.pop(0), output_text="", usage=usage)


def test_the_agent_reads_a_plan_and_can_cite_it(monkeypatch):
    """The model is offered read_plan, its call runs, and what it read counts as seen evidence."""
    client = ReadingClient()
    monkeypatch.setattr(agent, "get_openai_client", lambda: client)
    run = agent.run_agent("Får vi bygga?", tools_on(), model="test/model")
    assert "read_plan" in client.offered and [step["tool"] for step in run.steps] == ["read_plan"]
    assert len(run.seen_chunks) == 3


@pytest.mark.parametrize("words", ["address", "property designation", "aktbeteckning", '"here"', '"my plot"', "offer_pin"])
def test_the_instructions_say_what_counts_as_a_specific_question(words):
    """The agent's instructions name each sign of a question about one specific place, and the way to ask for a pin."""
    assert words in agent.PIN_GUIDE and agent.PIN_GUIDE in agent.SYSTEM_PROMPT


def test_the_instructions_tell_the_agent_to_read_the_pinned_plans_before_searching():
    """With a pin the instructions send the agent to read_plan first and to search only for the rest."""
    guide = agent.PIN_GUIDE.lower()
    assert "read_plan" in guide and "without searching" in guide and "statute" in guide


def test_the_instructions_keep_a_general_question_general():
    """A general question with a pin is answered generally; without one it gets the search tools and an offer to pin."""
    guide = agent.PIN_GUIDE.lower()
    assert "general question" in guide and "without bringing in" in guide and "offer to pin" in guide


def test_the_instructions_cover_a_plan_with_no_text():
    """A plan with no text read: name it, say so, give the link, answer from the statutes."""
    guide = agent.PIN_GUIDE.lower()
    assert "text not read" in guide and "link" in guide and "statutes" in guide


def test_without_a_pin_a_specific_question_gets_a_request_for_a_pin_before_any_search():
    """The no-pin hint asks for the pin before any search, and offers it on a general question."""
    hint = NO_PIN_HINT.lower()
    assert "before any search" in hint and "offer_pin" in hint and "general question" in hint


def test_a_pinned_general_question_is_told_to_stay_general(tmp_path):
    """The pinned block itself leaves room for a general question."""
    sent = question_with_place("Vad är bygglov?", profile_at(snapshot(tmp_path)))
    assert "general question" in sent.lower()


# --- the answer benchmark ---------------------------------------------------------------------------------------------

CASE = {"id": "norby", "kommun": "0380", "pin": {"lat": PIN[0], "lon": PIN[1], "label": "Eksoppsvägen 37, Uppsala"},
        "question": "Kan jag bygga?", "question_address": "Kan jag bygga på Eksoppsvägen 37?",
        "question_general": "Vad är en attefallsåtgärd?", "reference_place": "Norby 114:1.",
        "facts": [{"label": "plan", "any": ["0380-P90/6"]}], "key_points": ["Names the plan."], "locked": "2026-11-05"}
BY_ID = {CASE["id"]: CASE}


def fake_profile(lat, lon):
    return {"point": {"lat": lat, "lon": lon}, "covered": False}


def fake_grade(case, condition, typed, answer, place_text, sources, cases_by_id, model):
    return {"points": [2], "unsupported": 0, "wrong_place": 0, "asks": False, "offers_pin": condition == "general",
            "comment": "", "cost": 0.001, "model": model}


def fake_agent(question, tools, **kwargs):
    return SimpleNamespace(answer="En attefallsåtgärd, 0380-P90/6.", mode="explain", seconds=1.0, first_token_s=0.5,
                           usage={"cost": 0.01}, llm_calls=2, error=None, seen_chunks=[], choices=[], offer_pin=False,
                           steps=[{"tool": "read_plan"}, {"tool": "search"}, {"tool": "grep"}])


def bench():
    return AnswerBench([CASE], run_agent=fake_agent, tools=object(), profile_of=fake_profile,
                       sources_of=lambda answer, seen: "", grade=fake_grade)


def test_the_benchmark_runs_general_questions_with_and_without_the_pin():
    """A case with a general question also runs it with the pin and without."""
    assert {("norby", "general", 0), ("norby", "general_pin", 0)} <= set(jobs([CASE]))
    assert not {job for job in jobs([{**CASE, "question_general": None}]) if job[1].startswith("general")}


def test_the_general_conditions_send_the_general_question():
    """Without a pin the general question follows the hint, with one it follows the place."""
    typed, sent, place = prompt(CASE, "general", BY_ID, fake_profile)
    assert typed == CASE["question_general"] and sent == f"{NO_PIN_HINT}\n\n{typed}" and place is None
    typed, sent, place = prompt(CASE, "general_pin", BY_ID, fake_profile)
    assert typed == CASE["question_general"] and sent.endswith(typed) and place and place in sent


def test_a_named_address_without_a_pin_should_ask_for_the_pin():
    """Naming an address without a pin is a specific question: asking is right, and leaves nothing to grade on points."""
    asked = scores({"condition": "address"}, {"points": [0], "asks": True, "unsupported": 0, "wrong_place": 0})
    assert asked["asks_ok"] is True and asked["points"] is None


@pytest.mark.parametrize("condition", ["general", "general_pin"])
def test_a_general_question_should_not_ask_where(condition):
    """A general question needs no place: asking for one is wrong."""
    grade = {"points": [], "asks": True, "unsupported": 0, "wrong_place": 0}
    assert scores({"condition": condition}, grade)["asks_ok"] is False


def test_the_summary_counts_searches_and_the_offers_to_pin(tmp_path):
    """The summary counts the calls that look for documents, not those that read them, and the offers to pin."""
    result = run_bench([CASE], repeats=1, workers=1, bench=bench(), out_dir=tmp_path)
    assert result["summary"]["pin"]["searches"] == 2.0 and result["summary"]["pin"]["tool_calls"] == 3.0
    assert result["summary"]["general"]["offers_pin"] == 1.0 and result["summary"]["general_pin"]["offers_pin"] == 0.0


def test_the_summary_counts_the_plan_brought_into_a_general_answer(tmp_path):
    """An answer to a pinned general question that names the place's plan shows in its facts."""
    result = run_bench([CASE], conditions=("general_pin",), repeats=1, workers=1, bench=bench(), out_dir=tmp_path)
    assert result["summary"]["general_pin"]["facts"] == 1.0


def test_compare_puts_two_runs_side_by_side():
    """Each condition both runs have gets before and after for its metrics, each run under its own judge."""
    def run(judge, tool_calls):
        rows = [{"condition": "pin", "case": "norby", "tool_calls": tool_calls, "answer": "x",
                 "grades": {judge: {"points": 1.0, "asks": False, "asks_ok": True, "unsupported": 0, "wrong_place": 0}}},
                {"condition": "general", "case": "norby", "tool_calls": 1, "answer": "x", "grades": {}}]
        return {"judge": judge, "rows": rows if judge == "b" else rows[:1]}
    compared = compare(run("a", 9), run("b", 3))
    assert compared["pin"]["tool_calls"] == {"before": 9.0, "after": 3.0}
    assert compared["pin"]["points"] == {"before": 1.0, "after": 1.0}
    assert "general" not in compared


def test_compare_leaves_a_metric_an_older_run_did_not_record_empty():
    """A result file from before a metric existed gives None on its side."""
    before = {"judge": "a", "rows": [{"condition": "pin", "case": "n", "answer": "x", "tool_calls": 1, "grades": {
        "a": {"points": 1.0, "asks": False, "asks_ok": True, "unsupported": 0, "wrong_place": 0}}}]}
    after = {"judge": "a", "rows": [{**before["rows"][0], "tools": ["search"]}]}
    assert compare(before, after)["pin"]["searches"] == {"before": None, "after": 1.0}


def test_the_real_cases_carry_general_questions():
    """The locked cases hold general questions, so the conditions run on the real file."""
    assert sum(bool(case.get("question_general")) for case in bench_answers.load_cases()) >= 3
