"""
Claim-support eval: what is behind the live claim check's numbers (agentic.claim_check, the check the chat runs).

A benchmark run made with the claim check on (agentic.bench, or place.bench_answers run --claim-check) stores every
claim of every answer with the check's verdict (`claim_list`). This module adds a second reader and writes the report:

  recheck  put the stored answers of a result file to the live claim check (again): for a file from before the
           check was in the benchmark, or after the check changed. No agent run, only decision model calls.
  audit    a model of another family reads each claim next to the full text of the chunks it cites and the pinned
           place's data, and says what kind of claim it is, what form it has, and whether the sources back it.
           Stored per claim under `audit`.
  report   the numbers and what is behind them, as Markdown: support per condition with a confidence interval, per
           kind and form of claim, the check against the auditor (false flags, misses), the effect of stretch
           length, per case, the flagged claims to read, and what the numbers suggest doing.

    cd backend/src
    python -m agentic.claim_audit recheck ../data/agentic/place-answers-....json
    python -m agentic.claim_audit audit   ../data/agentic/place-answers-....json
    python -m agentic.claim_audit report  ../data/agentic/place-answers-....json --out ../../reports/claim_support_eval.md

The auditor is a judge, not ground truth: read its shares as a second opinion on the check, and the listed claims
as the material to verify by hand.
"""

import argparse
import json
import os
import random
import re
import threading
from collections import defaultdict
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

AUDIT_MODEL = "xiaomi/mimo-v2.6-flash"  # another family than the agent (GPT-6 Luna) and the decision model (Jev)
KINDS = ("rule", "number", "place", "procedure", "contact", "none")
FORMS = ("statement", "advice", "hedge", "summary")
BACKED = ("yes", "partly", "no")
VERDICTS = ("supported", "unsupported", "uncited")
MAX_SOURCE_CHARS = 6000  # of each cited chunk shown to the auditor
MAX_PLACE_CHARS = 6000
BOOTSTRAP_SAMPLES = 2000
MIN_GROUP = 5  # a group with fewer claims is shown but not used for a recommendation

AUDIT_INSTRUCTIONS = """You audit claims taken from an assistant's answer about Swedish planning and building law.
Each claim comes with the full text of the sources the answer cites for it, and with the place data the assistant was
given about the user's property (if any). Read every claim against its own sources and the place data only: what you
know yourself does not count.

For each claim return:
- kind: what the claim's main factual content is.
    "rule"       a legal rule or permit requirement, with or without a legal reference, and no number
    "number"     a measure, limit, area, height, distance, fee, deadline or date
    "place"      a fact about this particular property or place (its plan, protection, zoning, what is built there)
    "procedure"  what the kommun or an authority requires, offers or how to apply (documents, steps, who decides)
    "contact"    contact details (telephone, e-mail, address, opening hours)
    "none"       no factual content of its own
- form: how the claim is put.
    "statement"  it states the fact plainly
    "advice"     it tells the user what to do (check, contact, apply, confirm), with or without a fact attached
    "hedge"      it says what the assistant could not determine, read or confirm
    "summary"    it is the answer's verdict or sums up points made elsewhere in the answer
- backed: do the claim's sources or the place data state what the claim says?
    "yes"     every specific fact in the claim is stated there (a faithful translation or paraphrase counts)
    "partly"  some of its specific facts are stated there, others are not
    "no"      its specific facts are not stated there, or it has no sources and the place data does not state it
  A claim with kind "none" is "yes" unless it contradicts its sources.
- missing: for "partly" and "no", the specific fact the sources do not state, in at most 20 words; "" for "yes".

Return JSON only: {"claims": [{"n": <claim number>, "kind": "...", "form": "...", "backed": "...", "missing": "..."}]}
with one entry per claim, in order."""


# --- result files ------------------------------------------------------------------------------------------------

def load(path: Path) -> tuple[dict | list, list[dict]]:
    """A result file and its rows: place.bench_answers saves {"rows": [...]}, agentic.bench a list of rows."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return data, data["rows"] if isinstance(data, dict) else data


def save(path: Path, data: dict | list) -> None:
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def group_of(row: dict) -> str:
    """What a row is compared by: the pin benchmark's condition, else the system (rag / agent)."""
    return row.get("condition") or row.get("system") or "all"


def checked(rows: list[dict]) -> list[dict]:
    """The rows whose answer the claim check judged."""
    return [row for row in rows if row.get("claim_check") == "checked" and row.get("claim_list") is not None]


def claims_of(rows: list[dict]) -> list[dict]:
    """Every claim of the checked rows, each with its row's `case`, `group` and `repeat`."""
    return [{**claim, "case": row["case"], "group": group_of(row), "repeat": row.get("repeat", 0)}
            for row in checked(rows) for claim in row["claim_list"]]


def sentences_in(text: str) -> int:
    """Sentences in a claim's text (at least 1): a stretch of several is judged by the check as one claim."""
    return max(1, len(re.findall(r"[.!?;](?=\s|$)", text.strip().rstrip(".!?;") + ".")))


# --- recheck -----------------------------------------------------------------------------------------------------

def recheck(rows: list[dict], claim_support: Callable, tools, *, only_missing: bool = False, workers: int = 4) -> int:
    """Put each stored answer to the live claim check and write its fields into the row (agentic.bench.claim_support:
    `claim_support(run, tools, place)`); a row's `seen` chunks resolve shortened citations and its `place_text` counts
    as a source, as when the answer was made. `only_missing` leaves rows that already have a `claim_list`. Returns
    the number of rows put to the check. A new check drops the row's audit, which was of the old claims."""
    todo = [row for row in rows if row.get("answer") and not (only_missing and row.get("claim_list") is not None)]

    def one(row: dict) -> None:
        run = SimpleNamespace(answer=row["answer"], mode=row.get("mode"), seen_chunks=row.get("seen") or [])
        row.update(claim_support(run, tools, row.get("place_text")))

    with ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(one, todo))
    return len(todo)


# --- audit -------------------------------------------------------------------------------------------------------

def source_kind(chunk: dict) -> str:
    """A cited chunk's kind for the report: "law", or the kommun document's type ("detaljplan", "taxa", ...)."""
    return "law" if chunk.get("kind") == "law" else (chunk.get("doc_type") or chunk.get("kind") or "other")


def audit_input(row: dict, chunk_of: Callable[[str], dict | None], chunk_text: Callable[[dict], str]) -> str:
    """What the auditor reads for one answer: the place data, then each claim with the text of the chunks it cites."""
    parts = [f"Place data the assistant was given:\n{(row.get('place_text') or '(none)')[:MAX_PLACE_CHARS]}"]
    for number, claim in enumerate(row["claim_list"], 1):
        sources = []
        for chunk_id in claim.get("chunk_ids") or []:
            chunk = chunk_of(chunk_id)
            sources.append(f"[{chunk_id}] {chunk_text(chunk)[:MAX_SOURCE_CHARS]}" if chunk
                           else f"[{chunk_id}] (this source could not be read)")
        parts.append(f"Claim {number}: {claim['text']}\nSources of claim {number}:\n"
                     + ("\n\n".join(sources) if sources else "(the answer cites no source for it)"))
    return "\n\n---\n\n".join(parts)


def parse_audit(text: str, wanted: int) -> list[dict | None]:
    """The auditor's reply as one entry per claim, in order; None where it gave none or an unusable one."""
    text = text[text.find("{"):text.rfind("}") + 1]  # some models wrap the JSON in prose or a code fence
    try:
        entries = json.loads(text).get("claims") or []
    except (json.JSONDecodeError, AttributeError):
        return [None] * wanted
    by_number = {entry.get("n"): entry for entry in entries if isinstance(entry, dict)}
    out: list[dict | None] = []
    for number in range(1, wanted + 1):
        entry = by_number.get(number)
        if entry and entry.get("kind") in KINDS and entry.get("form") in FORMS and entry.get("backed") in BACKED:
            out.append({"kind": entry["kind"], "form": entry["form"], "backed": entry["backed"],
                        "missing": str(entry.get("missing") or "")[:300]})
        else:
            out.append(None)
    return out


def ask_auditor(model: str, prompt: str) -> tuple[str, float]:
    """The auditor's reply to one answer's claims, and what the call cost (USD)."""
    from llm import get_openai_client, get_response_output_text

    response = get_openai_client().responses.create(model=model, reasoning={"effort": "medium"},
                                                    instructions=AUDIT_INSTRUCTIONS, input=prompt)
    return get_response_output_text(response).strip(), float(getattr(response.usage, "cost", 0) or 0)


def audit(rows: list[dict], tools, *, model: str = AUDIT_MODEL, ask: Callable[[str, str], tuple[str, float]] = ask_auditor,
          chunk_text: Callable[[dict], str] | None = None, only_missing: bool = True, workers: int = 4,
          on_row: Callable[[], None] | None = None) -> dict:
    """Have the auditor read every claim of the checked rows; each claim gets `audit` = {"kind", "form", "backed",
    "missing", "sources": [kind of each cited chunk], "model"} (absent where the auditor's reply was unusable).
    `only_missing` skips rows whose claims all have one. `on_row` is called after each row (to save).
    Returns {"rows", "claims", "unusable", "cost"}."""
    from agentic.tools import resolve_cited

    if chunk_text is None:
        from localrag.index import chunk_text
    todo = [row for row in checked(rows) if row["claim_list"]
            and not (only_missing and all(claim.get("audit") for claim in row["claim_list"]))]
    stats = {"rows": len(todo), "claims": 0, "unusable": 0, "cost": 0.0}
    lock = threading.Lock()

    def one(row: dict) -> None:
        def chunk_of(chunk_id: str) -> dict | None:
            return resolve_cited(tools.get_chunk, chunk_id, row.get("seen") or [])
        try:
            reply, cost = ask(model, audit_input(row, chunk_of, chunk_text))
        except Exception as exc:  # noqa: BLE001 - a failed call leaves the row unaudited; the report says how many
            reply, cost = f"{type(exc).__name__}", 0.0
        entries = parse_audit(reply, len(row["claim_list"]))
        with lock:
            for claim, entry in zip(row["claim_list"], entries, strict=True):
                stats["claims"] += 1
                if entry is None:
                    stats["unusable"] += 1
                    continue
                kinds = [source_kind(chunk) if (chunk := chunk_of(chunk_id)) else "unreadable"
                         for chunk_id in claim.get("chunk_ids") or []]
                claim["audit"] = {**entry, "sources": kinds, "model": model}
            stats["cost"] += cost
            if on_row:
                on_row()

    with ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(one, todo))
    stats["cost"] = round(stats["cost"], 4)
    return stats


# --- numbers -----------------------------------------------------------------------------------------------------

def shares(claims: list[dict]) -> dict:
    """{"claims", "supported", "unsupported", "uncited"}: the claims and the share per verdict (None without claims)."""
    total = len(claims)
    return {"claims": total, **{verdict: sum(c["verdict"] == verdict for c in claims) / total if total else None
                                for verdict in VERDICTS}}


def support_interval(rows: list[dict], samples: int = BOOTSTRAP_SAMPLES, seed: int = 0) -> tuple[float, float] | None:
    """The 95 % interval of the pooled support share (supported claims / claims), from resampling the answers: an
    answer's claims stand or fall together, so the answer is the unit. None without claims."""
    counts = [(sum(c["verdict"] == "supported" for c in row["claim_list"]), len(row["claim_list"])) for row in checked(rows)]
    if not sum(total for _, total in counts):
        return None
    rng, values = random.Random(seed), []
    for _ in range(samples):
        picked = rng.choices(counts, k=len(counts))
        total = sum(n for _, n in picked)
        if total:
            values.append(sum(s for s, _ in picked) / total)
    values.sort()
    return values[int(0.025 * len(values))], values[min(len(values) - 1, int(0.975 * len(values)))]


def by(claims: list[dict], key: Callable[[dict], str | None]) -> dict[str, list[dict]]:
    """The claims grouped by `key` (claims whose key is None are left out), largest group first."""
    groups: dict[str, list[dict]] = defaultdict(list)
    for claim in claims:
        value = key(claim)
        if value is not None:
            groups[value].append(claim)
    return dict(sorted(groups.items(), key=lambda item: -len(item[1])))


def audited(claims: list[dict]) -> list[dict]:
    return [claim for claim in claims if claim.get("audit")]


def agreement(claims: list[dict]) -> dict:
    """The check against the auditor, over the audited claims that cite a source:

    - "flagged" / "false_flags": claims the check calls unsupported, and those the auditor finds fully backed.
    - "passed" / "misses": claims the check calls supported, and those the auditor finds not backed at all.
    - "table": {check verdict: {auditor "yes" / "partly" / "no": claims}}."""
    cited = [claim for claim in audited(claims) if claim["verdict"] in ("supported", "unsupported")]
    table = {verdict: {backed: sum(c["verdict"] == verdict and c["audit"]["backed"] == backed for c in cited)
                       for backed in BACKED} for verdict in ("supported", "unsupported")}
    return {"claims": len(cited), "table": table,
            "flagged": sum(table["unsupported"].values()), "false_flags": table["unsupported"]["yes"],
            "passed": sum(table["supported"].values()), "misses": table["supported"]["no"]}


def summary(rows: list[dict]) -> dict:
    """The eval's numbers: per group {"answers", "answers_checked", "checks_failed", "answers_clean" (checked answers
    with claims and none flagged), "flags_per_answer", shares(), "interval"}, and over all claims "kinds", "forms",
    "lengths" and "sources" (shares() per kind / form / sentences in the stretch / kind of cited chunk), "agreement"
    and "audited" (claims the auditor read)."""
    claims = claims_of(rows)
    groups = {}
    for group in dict.fromkeys(group_of(row) for row in rows):
        mine = [row for row in rows if group_of(row) == group]
        done = checked(mine)
        with_claims = [row for row in done if row["claim_list"]]
        flags = [sum(c["verdict"] != "supported" for c in row["claim_list"]) for row in with_claims]
        groups[group] = {
            "answers": len(mine), "answers_checked": len(done),
            "checks_failed": sum(row.get("claim_check") == "failed" for row in mine),
            "answers_clean": sum(flag == 0 for flag in flags) / len(flags) if flags else None,
            "flags_per_answer": sum(flags) / len(flags) if flags else None,
            **shares([claim for claim in claims if claim["group"] == group]), "interval": support_interval(mine)}
    read = audited(claims)
    return {
        "groups": groups, "claims": len(claims), "audited": len(read),
        "kinds": {kind: shares(mine) for kind, mine in by(read, lambda c: c["audit"]["kind"]).items()},
        "forms": {form: shares(mine) for form, mine in by(read, lambda c: c["audit"]["form"]).items()},
        "lengths": {length: shares(mine) for length, mine in sorted(by(
            [c for c in claims if c["verdict"] != "uncited"],
            lambda c: {1: "1 sentence", 2: "2 sentences"}.get(sentences_in(c["text"]), "3 or more")).items())},
        "sources": {kind: shares(mine) for kind, mine in by(
            [{**c, "source": kind} for c in read for kind in dict.fromkeys(c["audit"]["sources"])],
            lambda c: c["source"]).items()},
        "agreement": agreement(claims),
    }


# --- report ------------------------------------------------------------------------------------------------------

def pct(value: float | None) -> str:
    return "–" if value is None else f"{value:.0%}"


def clip(text: str, limit: int = 260) -> str:
    text = " ".join(text.split()).replace("|", "\\|")
    return text if len(text) <= limit else text[:limit - 1].rstrip() + "…"


def table(head: list[str], body: list[list[str]]) -> str:
    return "\n".join(["| " + " | ".join(head) + " |", "|" + "---|" * len(head),
                      *("| " + " | ".join(row) + " |" for row in body)])


def shares_row(name: str, numbers: dict) -> list[str]:
    return [name, str(numbers["claims"]), pct(numbers["supported"]), pct(numbers["unsupported"]), pct(numbers["uncited"])]


def recommendations(numbers: dict, claims: list[dict]) -> list[str]:
    """What the numbers suggest doing, each with the figure it rests on. Empty when nothing stands out."""
    out = []
    agree = numbers["agreement"]
    if agree["flagged"] >= MIN_GROUP:
        false_share = agree["false_flags"] / agree["flagged"]
        if false_share >= 0.2:
            out.append(f"**The check flags claims its sources do back.** The auditor finds {agree['false_flags']} of the "
                       f"{agree['flagged']} claims flagged unsupported ({pct(false_share)}) fully backed by their cited "
                       "sources. Read those (section *Flags the auditor disagrees with*) before trusting the unsupported "
                       "share, and see whether the decision model's threshold (`SUPPORTED_AT` in `claim_check.py`) or "
                       "its question wording is too strict.")
    if agree["passed"] >= MIN_GROUP and agree["misses"] / agree["passed"] >= 0.05:
        out.append(f"**The check passes claims its sources do not state.** The auditor finds {agree['misses']} of the "
                   f"{agree['passed']} claims the check calls supported ({pct(agree['misses'] / agree['passed'])}) not "
                   "backed at all. These reach the user unflagged: read them (section *Claims the check passed and the "
                   "auditor did not*).")
    lengths = numbers["lengths"]
    one, more = lengths.get("1 sentence"), [v for k, v in lengths.items() if k != "1 sentence" and v["claims"] >= MIN_GROUP]
    if one and one["claims"] >= MIN_GROUP and more:
        many_claims = sum(v["claims"] for v in more)
        many = sum(v["supported"] * v["claims"] for v in more) / many_claims
        if one["supported"] - many >= 0.1:
            out.append(f"**Judge each sentence on its own.** A stretch of several sentences before one citation is judged "
                       f"as a single claim: {pct(many)} of the {many_claims} multi-sentence stretches are supported, "
                       f"against {pct(one['supported'])} of the {one['claims']} single sentences. One unbacked sentence "
                       "fails the whole stretch. Split the stretch per sentence in `claim_check._stretches`, or have the "
                       "answer format put a citation after each sentence that states a fact.")
    forms = numbers["forms"]
    read = audited(claims)
    flagged = [c for c in read if c["verdict"] != "supported"]
    for form, what, advice in (
        ("advice", "tell the user what to do", ("Leave pure advice out of the check, as generic advice already is, and "
         "judge only the fact attached to it; or have the answer keep the next steps apart from the facts they rest on, "
         "each fact with its own citation.")),
        ("hedge", "say what the assistant could not read or confirm", ("A hedge is not a claim about the sources: leave "
         "it out of the check. Where the hedge is about a plan that was not read, the fix is upstream (the plan's text "
         "in the corpus, or the agent opening it).")),
        ("summary", "are the answer's verdict line or a summary", ("Exempt the verdict line when every fact in it is "
         "cited further down, or have the answer format carry the citations into the verdict line.")),
    ):
        mine = [c for c in flagged if c["audit"]["form"] == form]
        if len(flagged) >= MIN_GROUP and len(mine) / len(flagged) >= 0.15:
            out.append(f"**{len(mine)} of the {len(flagged)} flagged claims ({pct(len(mine) / len(flagged))}) {what}** "
                       f"({pct(forms[form]['supported'])} of all such claims are supported). {advice}")
    contact = numbers["kinds"].get("contact")
    if contact and contact["claims"] >= 3 and contact["supported"] < 0.7:
        out.append(f"**Contact details are flagged** ({pct(contact['supported'])} of {contact['claims']} supported): the "
                   "telephone number or address is not in the chunk the sentence cites. Have the agent cite the page "
                   "the contact details come from, or keep them out of the answer unless a source read states them.")
    factual = {kind: numbers["kinds"][kind] for kind in ("rule", "number", "place", "procedure")
               if kind in numbers["kinds"] and numbers["kinds"][kind]["claims"] >= MIN_GROUP}
    if factual:
        kind, worst = min(factual.items(), key=lambda item: item[1]["supported"])
        genuine = [c for c in read if c["audit"]["kind"] == kind and c["verdict"] == "unsupported"
                   and c["audit"]["backed"] != "yes"]
        if worst["supported"] < 0.8 and genuine:
            out.append(f"**Claims of kind “{kind}” are the weakest facts**: {pct(worst['supported'])} of "
                       f"{worst['claims']} supported, and the auditor agrees on {len(genuine)} of the flags. This is where "
                       "the agent states more than its source says: read the `missing` column of those claims for what "
                       "it adds (a number, a section reference, a condition), and tighten the answer format on it "
                       "(quote the figure, cite the chunk that holds it).")
    groups = {name: g for name, g in numbers["groups"].items() if g["claims"]}
    if len(groups) >= 2:
        best, worst = max(groups.items(), key=lambda i: i[1]["supported"]), min(groups.items(), key=lambda i: i[1]["supported"])
        if best[1]["supported"] - worst[1]["supported"] >= 0.05:
            overlap = (best[1]["interval"] and worst[1]["interval"] and best[1]["interval"][0] <= worst[1]["interval"][1])
            out.append(f"**“{best[0]}” answers are better supported than “{worst[0]}” answers** "
                       f"({pct(best[1]['supported'])} against {pct(worst[1]['supported'])})"
                       + ("; the intervals overlap, so more answers are needed before the difference counts."
                          if overlap else "; the intervals do not overlap."))
    uncited = sum(c["verdict"] == "uncited" for c in claims)
    if claims and uncited / len(claims) >= 0.05:
        out.append(f"**{uncited} claims ({pct(uncited / len(claims))}) state a fact without a citation.** The answer "
                   "format asks for a citation on every rule, number and fee: check which of them repeat a fact cited "
                   "elsewhere in the answer (harmless, see the summary line above) and which are new facts.")
    return out


def report(rows: list[dict], *, title: str, sources: list[str], findings: str = "", meta: dict | None = None) -> str:
    """The eval as Markdown. `findings` (hand-written, optional) is placed right after the headline numbers."""
    claims = claims_of(rows)
    numbers = summary(rows)
    out = [f"# {title}", ""]
    described = ", ".join(f"{key} {value}" for key, value in (meta or {}).items() if value)
    out += [f"Result files: {', '.join(f'`{name}`' for name in sources)}." + (f" {described}." if described else ""), "",
            ("Every factual claim of each answer was put to the chat's live claim check (`agentic/claim_check.py`): a "
            "claim is **supported** when the decision model says the chunks it cites (or the pinned place's data) back "
            "it, **unsupported** when it cites a source that does not, and **uncited** when it states a rule, number, "
            "fee or deadline with no citation. Advice and questions are not claims."), ""]

    out += ["## Headline", ""]
    body = []
    for name, g in numbers["groups"].items():
        interval = "–" if not g["interval"] else f"{g['interval'][0]:.0%}–{g['interval'][1]:.0%}"
        body.append([name, f"{g['answers_checked']} / {g['answers']}", str(g["claims"]), pct(g["supported"]), interval,
                     pct(g["unsupported"]), pct(g["uncited"]), pct(g["answers_clean"]),
                     "–" if g["flags_per_answer"] is None else f"{g['flags_per_answer']:.1f}", str(g["checks_failed"])])
    out += [table(["Condition", "Answers checked", "Claims", "Supported", "95 % interval", "Unsupported", "Uncited",
                   "Answers with no flag", "Flags per answer", "Checks failed"], body), "",
            ("The interval comes from resampling the answers (an answer's claims stand or fall together). “Answers "
            "checked” leaves out answers that were a question back to the user or an error. “Answers with no flag” "
            "is over the answers that make at least one claim."), ""]
    if findings.strip():
        out += ["## Findings", "", findings.strip(), ""]

    tips = recommendations(numbers, claims)
    out += ["## What the numbers suggest", ""]
    out += [f"{i}. {tip}" for i, tip in enumerate(tips, 1)] if tips else ["Nothing stands out at this sample size."]
    out += [""]

    if numbers["audited"]:
        agree = numbers["agreement"]
        out += ["## What kind of claim is supported", "",
                (f"A second model (`{audited(claims)[0]['audit']['model']}`, another family than the agent and the "
                f"decision model) read {numbers['audited']} of the {numbers['claims']} claims next to the full text of "
                "their cited chunks and the place data, and labelled each. The support shares below are still the "
                "live check's."), "",
                table(["Kind of claim", "Claims", "Supported", "Unsupported", "Uncited"],
                      [shares_row(kind, n) for kind, n in numbers["kinds"].items()]), "",
                ("rule = a legal rule or permit requirement; number = a measure, limit, fee, deadline or date; place = a "
                "fact about the property; procedure = what the kommun requires or how to apply; contact = contact "
                "details; none = no factual content of its own."), "",
                table(["Form of claim", "Claims", "Supported", "Unsupported", "Uncited"],
                      [shares_row(form, n) for form, n in numbers["forms"].items()]), "",
                ("statement = states the fact plainly; advice = tells the user what to do, with or without a fact "
                "attached; hedge = says what could not be read or confirmed; summary = the verdict line or a recap."), "",
                table(["Cited source", "Claims", "Supported", "Unsupported", "Uncited"],
                      [shares_row(kind, n) for kind, n in numbers["sources"].items()]), "",
                "A claim citing two kinds of source counts under both.", "",
                "## Is the check right?", "",
                f"Over the {agree['claims']} audited claims that cite a source:", "",
                table(["Check says", "Auditor: backed", "Auditor: partly", "Auditor: not backed"],
                      [[verdict, *(str(agree["table"][verdict][backed]) for backed in BACKED)]
                       for verdict in ("supported", "unsupported")]), "",
                (f"- **False flags**: {agree['false_flags']} of {agree['flagged']} flagged claims are fully backed "
                f"according to the auditor ({pct(agree['false_flags'] / agree['flagged']) if agree['flagged'] else '–'})."),
                (f"- **Misses**: {agree['misses']} of {agree['passed']} passed claims are not backed at all according to "
                f"the auditor ({pct(agree['misses'] / agree['passed']) if agree['passed'] else '–'})."),
                (f"- **Partly backed**: {agree['table']['supported']['partly']} passed and "
                 f"{agree['table']['unsupported']['partly']} flagged claims hold one fact the source states and one it "
                 "does not. The check has to call the whole stretch one way or the other, so the passed ones carry an "
                 "unbacked detail to the user unflagged."), ""]

    out += ["## Does the length of the stretch matter?", "",
            "The check judges everything before a citation on a line as one claim.", "",
            table(["Stretch", "Claims", "Supported", "Unsupported"],
                  [[name, str(n["claims"]), pct(n["supported"]), pct(n["unsupported"])]
                   for name, n in numbers["lengths"].items()]), ""]

    names = list(numbers["groups"])
    cases = list(dict.fromkeys(claim["case"] for claim in claims))
    if cases:
        out += ["## Per case", "", "Supported claims / claims, over the repeats.", ""]
        body = []
        for case in cases:
            cells = []
            for name in names:
                mine = [c for c in claims if c["case"] == case and c["group"] == name]
                cells.append(f"{sum(c['verdict'] == 'supported' for c in mine)} / {len(mine)} ({pct(shares(mine)['supported'])})"
                             if mine else "–")
            body.append([case, *cells])
        out += [table(["Case", *names], body), ""]
    repeats = sorted({claim["repeat"] for claim in claims})
    if len(repeats) > 1:
        out += ["## Per repeat", "", "How much the share moves between runs of the same questions.", "",
                table(["Condition", *(f"repeat {repeat}" for repeat in repeats)],
                      [[name, *(pct(shares([c for c in claims if c["group"] == name and c["repeat"] == repeat])["supported"])
                                for repeat in repeats)] for name in names]), ""]

    def listing(heading: str, note: str, picked: list[dict]) -> list[str]:
        if not picked:
            return []
        rows_ = [[c["case"], c["group"], (c.get("audit") or {}).get("kind", "–"), (c.get("audit") or {}).get("form", "–"),
                  clip(c["text"]), clip((c.get("audit") or {}).get("missing", ""), 160) or "–"] for c in picked]
        return [f"## {heading}", "", note, "", table(["Case", "Condition", "Kind", "Form", "Claim", "What the sources do not state"], rows_), ""]

    def backed(claim: dict) -> str | None:
        return (claim.get("audit") or {}).get("backed")
    unsupported = [c for c in claims if c["verdict"] == "unsupported"]
    out += listing("Flagged and confirmed: claims that cite a source that does not state them",
                   "The check and the auditor agree. These are the claims to fix in the agent.",
                   [c for c in unsupported if backed(c) in ("no", "partly")])
    out += listing("Flags the auditor disagrees with",
                   "The check says unsupported, the auditor finds every fact in the cited sources. Verify by hand: either "
                   "the check is too strict or the auditor too lenient.", [c for c in unsupported if backed(c) == "yes"])
    out += listing("Flagged, not audited", "", [c for c in unsupported if backed(c) is None])
    out += listing("Facts without a citation", "The check found a rule, number, fee or deadline with no source.",
                   [c for c in claims if c["verdict"] == "uncited"])
    out += listing("Claims the check passed and the auditor did not",
                   "The check says supported, the auditor finds none of the facts in the cited sources. These reach the "
                   "user unflagged.", [c for c in claims if c["verdict"] == "supported" and backed(c) == "no"])
    return "\n".join(out).rstrip() + "\n"


# --- command line ------------------------------------------------------------------------------------------------

def main() -> None:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parents[2] / ".env")
    os.environ.setdefault("LLM_PROVIDER", "openrouter")
    parser = argparse.ArgumentParser(description="What is behind the claim check's numbers")
    sub = parser.add_subparsers(dest="command", required=True)
    again = sub.add_parser("recheck")
    again.add_argument("path", type=Path)
    again.add_argument("--only-missing", action="store_true", help="leave answers that already have their claims")
    read = sub.add_parser("audit")
    read.add_argument("path", type=Path)
    read.add_argument("--model", default=AUDIT_MODEL)
    read.add_argument("--all", action="store_true", help="audit again the claims that already have an audit")
    write = sub.add_parser("report")
    write.add_argument("paths", type=Path, nargs="+", help="result files; their rows are pooled")
    write.add_argument("--out", type=Path, required=True)
    write.add_argument("--title", default="Claim support: what the live claim check finds, and what is behind it")
    write.add_argument("--findings", type=Path, help="Markdown placed after the headline (default: <out>.findings.md if there)")
    for command in (again, read):
        command.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()

    if args.command == "report":
        rows, meta = [], {}
        for path in args.paths:
            data, mine = load(path)
            rows += mine
            if isinstance(data, dict):
                meta = {"Run": data.get("date"), "agent": (data.get("agent") or {}).get("model"), "judge": data.get("judge"),
                        "corpus": data.get("corpus")}
        findings = args.findings or args.out.with_suffix(".findings.md")
        text = report(rows, title=args.title, sources=[path.name for path in args.paths], meta=meta,
                      findings=findings.read_text(encoding="utf-8") if findings.exists() else "")
        args.out.write_text(text, encoding="utf-8")
        print(f"{len(claims_of(rows))} claims of {len(checked(rows))} answers -> {args.out}")
        return

    from agentic.service import get_tools

    data, rows = load(args.path)
    tools = get_tools()
    if args.command == "recheck":
        from agentic.bench import claim_support

        done = recheck(rows, claim_support, tools, only_missing=args.only_missing, workers=args.workers)
        save(args.path, data)
        print(f"{done} answers put to the claim check, {len(claims_of(rows))} claims -> {args.path}")
    else:
        stats = audit(rows, tools, model=args.model, only_missing=not args.all, workers=args.workers,
                      on_row=lambda: save(args.path, data))
        save(args.path, data)
        print(f"{stats['claims']} claims of {stats['rows']} answers audited by {args.model} "
              f"({stats['unusable']} unusable replies), ${stats['cost']} -> {args.path}")


if __name__ == "__main__":
    main()
