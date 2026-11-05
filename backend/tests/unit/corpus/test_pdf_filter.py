"""PDF relevance filter: plan words win over off-topic words, and no PDF is dropped without an LLM or a review."""

from corpus.pdf_filter import decide, rule, sure_drop


def row(title="", file="", anchor="", head=""):
    return {"title": title, "file": file, "anchor": anchor, "head": head}


def test_rules():
    assert rule(row("Detaljplan för förskola vid Kvarnbacken"))[0] is True  # plan word beats "förskol"
    assert rule(row("Taxa för prövning och tillsyn inom miljöbalkens område"))[0] is True  # enskilt avlopp fees
    assert rule(row("Taxa för sotning och brandskyddskontroll"))[0] is False
    assert rule(row("Riktlinjer för flaggning"))[0] is False
    assert rule(row("Minnesanteckningar", head="Samrådsmöte Planprogram för sydöstra stadsdelarna"))[0] is True
    assert rule(row("Bilaga 3", file="3.pdf"))[0] is None


def test_no_drop_without_a_second_judge():
    assert decide(False, "flagg", 0.01, None, None)["keep"] is None  # a rule alone: kept until the LLM answers
    assert decide(None, "", 0.02, None, None)["keep"] is None  # the model alone, too
    assert decide(None, "", 0.02, None, {"keep": True, "why": "plan"})["keep"] is True  # the LLM keeps it
    assert decide(False, "flagg", 0.01, None, {"keep": False})["keep"] is False
    assert decide(True, "detaljplan", 0.01, None, None)["keep"] is True
    assert decide(None, "", 0.95, None, None) == {"keep": True, "by": "model", "why": ""}
    assert decide(True, "detaljplan", 0.9, {"keep": False}, None)["keep"] is False  # a review wins


def test_sure_words_drop_without_the_llm():
    sotning = row("Taxa för sotning och brandskyddskontroll")
    assert sure_drop(sotning, rule(sotning)[1])
    assert decide(False, "sotning", 0.5, None, None, sure=True) == {"keep": False, "by": "sure-rule", "why": "sotning"}
    assert decide(False, "sotning", 0.5, None, {"keep": True}, sure=True)["keep"] is True  # an LLM answer wins
    assert decide(False, "sotning", 0.5, {"keep": True}, None, sure=True)["keep"] is True  # so does a review
    flagg = row("Riktlinjer för flagg")
    assert not sure_drop(flagg, rule(flagg)[1])  # a DROP word the judges did not always confirm: waits for the LLM
    planned = row("Taxa för sotning", head="Gäller även byggnader inom detaljplan för Kvarnbacken")
    assert not sure_drop(planned, rule(planned)[1])  # a plan word on the first page
