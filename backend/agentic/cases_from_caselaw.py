"""
Turn real MÖD rulings (corpus.caselaw) into benchmark cases: the facts become the user's question
(without the outcome or the court's reasoning), the outcome the verdict, the reasons the key points, and the
statutes the court relied on the evidence labels. Rulings cite the numbering of their time (PBL 9 kap. was
renumbered by SFS 2025:974), so a statute is labelled by a verbatim phrase of the provision that must occur in
the current law chunks; the section number is only a fallback.

Spends API credits (one LLM call per ruling, ~$0.002 with GPT-6 Luna):

    cd backend
    python -m corpus.caselaw                                   # download (free)
    python -m agentic.cases_from_caselaw --limit 5             # try a few, then inspect the output
    python -m agentic.cases_from_caselaw                       # all relevant rulings -> agentic/cases_caselaw.jsonl
    python -m agentic.bench --cases-file cases_caselaw.jsonl --store disk --systems agent
"""

import argparse
import json
import os
import re
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from corpus.caselaw import CASELAW_PATH
from corpus.common import MUNICIPALITIES_PATH, read_jsonl, write_jsonl
from localrag.eval import normalize
from llm import get_openai_client, get_response_output_text, resolve_model_name

OUTPUT_PATH = Path(__file__).resolve().parent / "cases_caselaw.jsonl"
DRAFTS_PATH = CASELAW_PATH.parent / "case_drafts.jsonl"  # raw LLM drafts, kept also when rejected
DEFAULT_MODEL = "openai/gpt-6-luna"
MAX_RULING_CHARS = 24000
LEAK = re.compile(r"\b(MÖD|court|domstol|överklag\w*|appeal\w*|ruled|ruling|tribunal)\b", re.I)

# Law names the generator may use -> substring of the law chunk titles
LAWS = {
    "PBL": "Plan- och bygglag", "PBF": "Plan- och byggförordning", "MB": "Miljöbalk", "JB": "Jordabalk",
    "FBL": "Fastighetsbildningslag", "AL": "Anläggningslag", "LAV": "allmänna vattentjänster",
    "FMH": "miljöfarlig verksamhet och hälsoskydd", "KML": "Kulturmiljölag",
}

INSTRUCTIONS = f"""You build test cases for an assistant that tells people whether a building or land project is
feasible in Sweden. You get a ruling of Mark- och miljööverdomstolen (MÖD). Return JSON only:
{{
 "usable": true|false,   // false if the ruling is not about whether a concrete project/measure may go ahead
                         // (pure procedure, fees, sanctions, appeal standing, environmental permits for industry).
                         // A förhandsbesked, bygglov, rivningslov, marklov, strandskyddsdispens, change of use or plan
                         // IS usable whatever the outcome, also when MÖD remitted it after stating the decisive legal
                         // test (then verdicts ["unclear"] or ["conditional","unclear"]).
 "usable_reason": "<one sentence>",
 "kommun": "<kommun name, e.g. Varberg>",
 "question": "<English, 2-5 sentences, written by the applicant before applying: the project and the facts that
               decided the case as the applicant would know them (place type, distances, existing buildings, what the
               detaljplan/översiktsplan says, shoreline, farmland...). Never the outcome, the court's assessment or the
               case number. Do not name the property designation; you may name the kommun and the area.>",
 "outcome": "<one sentence, what MÖD decided>",
 "verdicts": ["feasible"|"conditional"|"not_feasible"|"unclear", ...],  // acceptable verdicts for an assistant
                         // answering the question: permit granted -> ["feasible","conditional"]; refused ->
                         // ["not_feasible"] (add "unclear" only if the facts in the question leave it open)
 "key_points": ["<3-5 English points an expert answer must make, each naming the rule, e.g. 'Outside a detaljplan
                 a new house needs bygglov and a localisation assessment under PBL 2 kap. (PBL 9 kap. 31 §)'>"],
 "statutes": [{{"law": "<one of {', '.join(LAWS)}>", "section": "<as cited in the ruling, e.g. 9 kap. 31 b §>",
                "quote": "<5-12 consecutive words of the provision's own wording, copied exactly as the ruling quotes
                          the statute (not the court's paraphrase), e.g. 'avvikelsen är förenlig med detaljplanens
                          syfte'>"}}]
                         // 1-4 provisions decisive for the outcome (PBL 2010:900, MB 1998:808, ...). Leave out
                         // provisions of the old PBL (1987:10, ÄPBL) and ones the ruling does not quote.
}}"""


def law_chunks(store_path: Path) -> list[tuple[str, str, str]]:
    """(title, section, normalised text) of every law chunk."""
    db = sqlite3.connect(store_path)
    return [(title, section, normalize(text)) for title, section, text in
            db.execute("SELECT title, section, header || ' ' || text FROM chunks WHERE kind = 'law'")]


def normalise_section(section: str) -> str:
    section = re.sub(r"\s+", " ", section.replace("§§", "§")).strip()
    section = re.sub(r"(\d+)\s*([a-z])\s*§", r"\1 \2 §", section)
    section = re.sub(r"\s*(första|andra|tredje|fjärde|femte|sjätte)\s+stycket.*$", "", section)
    return section if section.endswith("§") else section + " §"


def longest_phrase(quote: str, texts: list[str], min_words: int = 5) -> str | None:
    """The longest run of >= min_words consecutive words of the quote found in one of the (normalised) texts:
    amendments often change a word or two of a provision (2025: "tas i anspråk" -> "tas i anspråk eller inreds")."""
    words = quote.split()
    for size in range(len(words), min_words - 1, -1):
        for start in range(len(words) - size + 1):
            phrase = " ".join(words[start:start + size])
            if any(normalize(phrase) in text for text in texts):
                return phrase
    return None


def evidence_for(statutes: list[dict], chunks: list[tuple[str, str, str]]) -> list[dict]:
    """A matcher per statute: its quote when the current text still contains it, else its section number when
    that section exists and is not in the renumbered PBL 9 kap."""
    evidence = []
    for statute in statutes:
        law = LAWS.get(str(statute.get("law", "")).upper())
        if not law:
            continue
        own = [(section, text) for title, section, text in chunks if law.lower() in title.lower()]
        quote = longest_phrase(str(statute.get("quote", "")), [text for _, text in own])
        section = normalise_section(str(statute.get("section", "")))
        if quote:
            matcher = {"law": law, "contains": quote}
        elif not (law == LAWS["PBL"] and section.startswith("9 kap.")) and any(s == section for s, _ in own):
            matcher = {"law": law, "section": section}
        else:
            continue
        if matcher not in evidence:
            evidence.append(matcher)
    return evidence


def kommun_codes(name: str, municipalities: list[dict]) -> list[str]:
    """Wikidata names are genitive ("Stockholms kommun", "Region Gotland"); rulings say "Stockholm", "Gotland"."""
    name = (name or "").lower().removesuffix(" kommun").removeprefix("region ").strip()
    def forms(m: dict) -> set[str]:
        base = m["name"].lower().removesuffix(" kommun").removeprefix("region ")
        return {base, base.removesuffix("s")}
    return [m["code"] for m in municipalities if name in forms(m)][:1]


def generate(client, model: str, ruling: dict, effort: str) -> dict:
    text = ruling["text"][:MAX_RULING_CHARS]
    response = client.responses.create(
        model=model, reasoning={"effort": effort}, instructions=INSTRUCTIONS,
        input=f"{ruling['reference']} ({ruling['case_number']}, {ruling['date']}): {ruling['title']}\n"
              f"Headnote: {ruling['summary']}\nStatutes: {ruling['statutes']}\n\nRuling:\n{text}",
    )
    raw = get_response_output_text(response).strip()
    raw = raw[raw.find("{"):raw.rfind("}") + 1]
    case = json.loads(raw)
    case["_cost"] = float(getattr(response.usage, "cost", 0) or 0)
    return case


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark cases from MÖD rulings")
    parser.add_argument("--limit", type=int, default=0, help="only the first N relevant rulings (newest first)")
    parser.add_argument("--since", type=int, default=2011)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--effort", default="medium")
    parser.add_argument("--store", default="data/index/store/st-arctic-l-v2/corpus.sqlite",
                        help="disk store whose law chunks the evidence labels must match")
    parser.add_argument("--regenerate", action="store_true", help="ignore cached drafts of the selected rulings")
    args = parser.parse_args()
    os.environ.setdefault("LLM_PROVIDER", "openrouter")

    rulings = [r for r in read_jsonl(CASELAW_PATH) if r.get("relevant") and r["date"][:4] >= str(args.since)]
    rulings.sort(key=lambda r: r["date"], reverse=True)
    if args.limit:
        rulings = rulings[:args.limit]
    chunks = law_chunks(Path(args.store))
    municipalities = json.loads(MUNICIPALITIES_PATH.read_text(encoding="utf-8"))
    client, model = get_openai_client(), resolve_model_name(args.model)
    print(f"{len(rulings)} rulings -> cases with {model} ({args.effort})")

    # Drafts are cached per ruling: rerunning (e.g. after changing the evidence matching) costs nothing,
    # --regenerate pays for new drafts
    drafts = {d["ruling"]: d for d in read_jsonl(DRAFTS_PATH)} if DRAFTS_PATH.exists() else {}
    if args.regenerate:
        drafts = {k: v for k, v in drafts.items() if k not in {r["reference"] for r in rulings}}
        write_jsonl(DRAFTS_PATH, drafts.values())
    lock = threading.Lock()

    def build(ruling: dict) -> tuple[dict, dict | None, str]:
        draft = drafts.get(ruling["reference"])
        if draft is None:
            try:
                draft = generate(client, model, ruling, args.effort)
            except Exception as exc:
                return ruling, None, f"error: {exc}"
            draft["ruling"] = ruling["reference"]
            with lock:  # appended at once, so an interrupted run keeps every draft it paid for
                drafts[ruling["reference"]] = draft
                with DRAFTS_PATH.open("a", encoding="utf-8") as file:
                    file.write(json.dumps(draft, ensure_ascii=False) + "\n")
        else:
            draft = {**draft, "_cost": 0.0}
        if not draft.get("usable"):
            return ruling, draft, "not usable"
        if LEAK.search(draft.get("question") or ""):  # the question must not reveal there was a court case
            return ruling, draft, "question mentions the court case"
        # No current statute (old PBL / old plans): the case is kept, scored on verdict and key points only
        evidence = evidence_for(draft.get("statutes") or [], chunks)
        status = "ok" if evidence else "ok, no evidence label"
        return ruling, {
            "id": "mod-" + ruling["id"],
            "kommun": kommun_codes(draft.get("kommun", ""), municipalities),
            "question": draft["question"],
            "verdicts": [v for v in draft.get("verdicts", []) if v in ("feasible", "conditional", "not_feasible", "unclear")],
            "key_points": draft["key_points"],
            "evidence": evidence,
            "outcome": draft.get("outcome"),
            "source": f"{ruling['reference']} ({ruling['case_number']}, {ruling['date']}): {ruling['title']}",
            "url": ruling["url"],
            "tags": ["caselaw", *[k.lower() for k in ruling["keywords"]]],
            "_cost": draft["_cost"],
        }, status

    cases, cost = [], 0.0
    with ThreadPoolExecutor(max_workers=4) as pool:
        for ruling, case, status in pool.map(build, rulings):
            cost += (case or {}).get("_cost", 0.0)
            print(f"  {ruling['reference']:<14} {status[:110]}")
            if status.startswith("ok"):
                cases.append({k: v for k, v in case.items() if k != "_cost"})
    write_jsonl(DRAFTS_PATH, drafts.values())
    written = write_jsonl(OUTPUT_PATH, cases)
    print(f"{written} cases -> {OUTPUT_PATH} (${cost:.3f})")


if __name__ == "__main__":
    main()
