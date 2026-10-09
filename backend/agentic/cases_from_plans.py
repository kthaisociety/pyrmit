"""
"Plankarta" benchmark: questions about a specific property inside a detaljplan whose rules differ by zone, so the
answer is only on the map (which zone the property is in, which codes apply). The existing benchmarks never need
the map (2 map views in 576 answers): this set measures what map reading brings (verdict, values, cost).

Two phases:

    cd backend
    python -m agentic.cases_from_plans candidates --n 40     # free: pick plans + properties, crop the map around them
                                                            # -> data/agentic/plan_cases/<id>.png + candidates.json
    python -m agentic.cases_from_plans label                # paid (vision, high effort): reference answer per candidate
                                                            # -> agentic/cases_plans.jsonl (only confident labels)
    python -m agentic.bench --cases-file cases_plans.jsonl --store disk ...

The reference is read by GPT-6 Luna from a zoomed crop of the map plus the code definitions extracted from the plan
legend (corpus.plans); only labels the model is confident about are kept, and a sample should be checked by a
person (the crops are saved for that).
"""

import argparse
import base64
import json
import os
import random
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from collections import Counter
from pathlib import Path

import pymupdf

from corpus.common import DATA_DIR, WEB_DIR
from llm import get_openai_client, get_response_output_text, resolve_model_name

OUT_DIR = DATA_DIR.parent / "agentic" / "plan_cases"
CANDIDATES_PATH = OUT_DIR / "candidates.json"
CASES_PATH = Path(__file__).resolve().parent / "cases_plans.jsonl"
DEFAULT_MODEL = "openai/gpt-6-luna"
MARGIN = 250  # points around the property label (as view_map_area size="medium")

PROPERTY = re.compile(r"^\d{1,4}:\d{1,4}$")
CODE_WORD = re.compile(r"^(?:[a-zåäö]\d{1,2})+$")
BLOCK_NAME = re.compile(r"^[A-ZÅÄÖ][A-ZÅÄÖ-]{3,}$")
LEGEND = re.compile(r"^(Planbestäm|Egenskapsbestäm|Användning|Teckenförklar|Grundkart|Genomförande|Upplysning|"
                    r"Administrativ|Illustration|Planområde)", re.I)
SCALES = {"1:100", "1:200", "1:250", "1:400", "1:500", "1:1000", "1:2000", "1:2500", "1:4000", "1:5000", "1:10000",
          "1:20000", "1:1"}
# Upper-case words of the plan vocabulary (zone names, legend and title-block headings), not property tract names
NOT_A_TRACT = {"NATUR", "GATA", "PARK", "TORG", "LOKALGATA", "HUVUDGATA", "PARKERING", "VATTEN", "GENOMFÖRANDETID",
               "PLANBESTÄMMELSER", "EGENSKAPSBESTÄMMELSER", "ILLUSTRATION", "ÖVERSIKTSKARTA", "GRUNDKARTA",
               "FASTIGHETSGRÄNS", "PLANGRÄNS", "SKALA", "TECKENFÖRKLARING", "UPPLYSNINGAR", "ANTAGANDEHANDLING",
               "GRANSKNINGSHANDLING", "SAMRÅDSHANDLING", "DETALJPLAN", "KOMMUN", "KONNEKTIONSLINJE", "GÄST"}


def codes_in(page, clip) -> list[str]:
    codes = []
    for word in (w[4] for w in page.get_text("words", clip=clip)):
        if CODE_WORD.fullmatch(word):
            codes += re.findall(r"[a-zåäö]\d{1,2}", word)
    return list(dict.fromkeys(codes))


def pick_property(page, plan_name: str, decisive: set[str], rng: random.Random):
    """A property label on the map whose surroundings carry at least one decisive (height / building area) code."""
    words = page.get_text("words")
    labels = [w for w in words if PROPERTY.match(w[4])]
    rng.shuffle(labels)
    for x0, y0, x1, y1, label, *_ in labels:
        block, unit = label.split(":")
        if label in SCALES or (block == "1" and int(unit) >= 200 and int(unit) % 100 == 0) or int(unit) % 250 == 0:
            continue  # map scales (1:500, 1:1500...), not properties
        hits = page.search_for(label)
        if len(hits) > 2:  # ambiguous on the sheet
            continue
        clip = pymupdf.Rect(x0 - MARGIN, y0 - MARGIN, x1 + MARGIN, y1 + MARGIN) & page.mediabox
        around = [w[4] for w in page.get_text("words", clip=clip)]
        # The legend and title block are prose; the map around a property is codes, numbers and names
        if sum(1 for w in around if re.fullmatch(r"[a-zåäö]{5,}", w)) > 12 or any(LEGEND.match(w) for w in around):
            continue
        codes = codes_in(page, clip)
        if not set(codes) & decisive:
            continue
        # A tract name only when the plan name confirms it (words split by the PDF give "Stennin", "Geno"...)
        tracts = [w.title() for w in around if BLOCK_NAME.match(w) and w.upper() not in NOT_A_TRACT
                  and w.lower() in plan_name.lower()]
        return label, clip, codes, (tracts[0] if tracts else None)
    return None


def candidates(n: int, seed: int) -> None:
    plans = [json.loads(line) for line in (DATA_DIR / "plans.jsonl").open(encoding="utf-8")]
    rng = random.Random(seed)
    rng.shuffle(plans)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    picked, per_kommun = [], Counter()
    for plan in plans:
        if len(picked) >= n:
            break
        if plan["status"] not in ("in_force", "adopted") or per_kommun[plan["kommun_code"]] >= 2:
            continue
        maps = [d for d in plan["documents"] if d["role"] == "plankarta" and not d["scanned"]
                and d["doc_id"] not in {p["doc_id"] for p in picked}]  # one case per map sheet
        definitions = {r["code"]: r["text"] for r in plan["provisions"] if r.get("code")}
        decisive = {r["code"] for r in plan["provisions"]
                    if r.get("code") and {"height", "building_area"} & set(r["topics"]) and not r["code"].startswith("+")}
        if not maps or len(decisive) < 2:  # one height / area rule for the whole plan: no need for the map
            continue
        match = re.fullmatch(r"pdf:(\d{4}):(\w+)", maps[0]["doc_id"])
        path = WEB_DIR / match.group(1) / "pdf" / f"{match.group(2)}.pdf"
        try:
            with pymupdf.open(path) as pdf:
                page = pdf[0]
                found = pick_property(page, plan["name"], decisive, rng)
                if not found:
                    continue
                label, clip, codes, block = found
                shown = (clip * page.rotation_matrix) & page.rect
                zoom = 1400 / max(shown.width, shown.height)
                case_id = f"plan-{plan['plan_id'][:8]}-{label.replace(':', '-')}"
                page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), clip=shown).save(OUT_DIR / f"{case_id}.png")
        except Exception as exc:  # broken PDFs: skip
            print(f"  skip {plan['name'][:40]}: {exc}")
            continue
        property_name = f"{block} {label}" if block else f"property {label}"
        picked.append({
            "id": case_id, "kommun": [plan["kommun_code"]], "kommun_name": plan["kommun"], "plan_id": plan["plan_id"],
            "plan_name": plan["name"], "doc_id": maps[0]["doc_id"], "property": property_name, "label": label,
            "codes_near": codes, "definitions": {c: definitions[c] for c in codes if c in definitions},
            "decisive_codes": sorted(decisive), "image": f"{case_id}.png",
        })
        per_kommun[plan["kommun_code"]] += 1
        print(f"  {case_id}: {plan['kommun']} – {plan['name'][:50]} – {property_name} – codes {codes}")
    CANDIDATES_PATH.write_text(json.dumps(picked, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{len(picked)} candidates -> {CANDIDATES_PATH}")


LABEL_INSTRUCTIONS = """You prepare a test case for an assistant on Swedish detailed plans (detaljplaner).
You get a zoomed crop of a plankarta around a property label, and the meaning of the codes printed in the crop.
Codes apply to the zone (area outlined by plan boundary lines) in which they are printed; a property can span
several zones (e.g. a buildable zone and land that may not be built on, prickmark, dotted pattern).
1. Decide which codes apply where the main building of the property can stand (and for ancillary buildings if a
   separate zone is visible). Use only what you can see; if the zone boundaries are not readable, say so.
2. Design a realistic residential project for this property (a house, an extension, a garage or outbuilding; on
   land for other uses, a modest building of that use) whose feasibility depends on these zone rules, as asked in
   the input: either WITHIN all the readable limits, or slightly ABOVE one of them (height, building area, storeys).
   Write it as the owner would, in one sentence starting "I want to build": plain words, NO plan codes (e1, h3, p1,
   B...), no "zone", "use area", "marked" or any reference to the map.
Return JSON only:
{"property_in_coded_zone": true|false,   // true only if the property clearly lies in a zone whose codes you can read
 "confidence": "high"|"medium"|"low",
 "applicable_codes": ["h1", ...], "max_height": "<value + unit, or null>", "max_building_area": "<value, or null>",
 "other_rules": ["<code: rule>", ...],
 "project": "<one sentence, e.g. a one-storey house with a ridge height of 6.5 m and 180 m2 building area>",
 "verdicts": ["feasible"|"conditional"|"not_feasible"|"unclear", ...],
 "key_points": ["<3-4 English points an expert answer must make, each naming the code and its value>"],
 "explanation": "<two sentences: which zone the property is in and why>"}"""


def target(candidate: dict) -> str:
    """Half the projects within the limits, half slightly above (stable per case), so 'not feasible' is not a free win."""
    return "WITHIN all" if int(candidate["plan_id"][:2], 16) % 2 == 0 else "slightly ABOVE one of"


def label(model_name: str, effort: str, limit: int) -> None:
    client, model = get_openai_client(), resolve_model_name(model_name)
    picked = json.loads(CANDIDATES_PATH.read_text(encoding="utf-8"))[: limit or None]
    labels_path = OUT_DIR / "labels.jsonl"
    labels = {json.loads(line)["id"]: json.loads(line) for line in labels_path.open(encoding="utf-8")} \
        if labels_path.exists() else {}
    lock = threading.Lock()

    def draft_for(candidate: dict) -> None:  # one vision call, appended at once (cached: re-running costs nothing)
        image = base64.b64encode((OUT_DIR / candidate["image"]).read_bytes()).decode()
        legend = "\n".join(f"{code}: {text}" for code, text in candidate["definitions"].items())
        try:
            response = client.responses.create(
                model=model, reasoning={"effort": effort}, instructions=LABEL_INSTRUCTIONS,
                input=[{"role": "user", "content": [
                    {"type": "input_text", "text": f"Plan: {candidate['plan_name']} ({candidate['kommun_name']}). "
                                                   f"Property label on the map: {candidate['label']}.\nCodes in "
                                                   f"the crop:\n{legend}\nProject to design: "
                                                   f"{target(candidate)} the limits."},
                    {"type": "input_image", "image_url": f"data:image/png;base64,{image}"}]}])
            raw = get_response_output_text(response)
            draft = json.loads(raw[raw.find("{"):raw.rfind("}") + 1])
        except Exception as exc:
            print(f"  {candidate['id']}: error {exc}")
            return
        draft["id"] = candidate["id"]
        draft["_cost"] = float(getattr(response.usage, "cost", 0) or 0)
        with lock:
            labels[candidate["id"]] = draft
            with labels_path.open("a", encoding="utf-8") as file:
                file.write(json.dumps(draft, ensure_ascii=False) + "\n")

    missing = [c for c in picked if c["id"] not in labels]
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(draft_for, missing))
    cost = sum(labels[c["id"]].get("_cost", 0.0) for c in missing if c["id"] in labels)
    cases = []
    for candidate in picked:
        draft = labels.get(candidate["id"])
        if draft is None:
            continue
        print(f"  {candidate['id']}: in zone {draft.get('property_in_coded_zone')}, {draft.get('confidence')} – "
              f"{draft.get('applicable_codes')} – {draft.get('project')}")
        # Kept: high or medium confidence with applicable codes and a decided verdict. The model is cautious
        # ("medium" when a parcel boundary is not fully readable), so a person reviews the kept cases (review page)
        explanation = f"{draft.get('explanation') or ''} {draft.get('project') or ''}".lower()
        leaks = re.search(r"\b[a-zåäö]\d{1,2}\b|\bzone\b|use area|marked", draft.get("project") or "", re.I)
        if (not draft.get("property_in_coded_zone") or draft.get("confidence") not in ("high", "medium")
                or not draft.get("applicable_codes") or not set(draft.get("verdicts") or []) - {"unclear"}
                or "cannot be" in explanation or leaks):
            continue
        verdicts = [v for v in draft.get("verdicts", []) if v in ("feasible", "conditional", "not_feasible", "unclear")]
        if target(candidate).startswith("WITHIN") and "not_feasible" not in verdicts:
            verdicts = ["feasible", "conditional"]  # within the limits: both are right (a permit is still needed)
        project = draft["project"].strip().rstrip(".")
        question = (f"I own {candidate['property']} in {candidate['kommun_name']}, inside the detaljplan "
                    f"\"{candidate['plan_name']}\". {project}. Is that allowed, and what do the plan's rules allow "
                    f"on my property?")
        cases.append({
            "id": candidate["id"], "kommun": candidate["kommun"], "question": question,
            "verdicts": verdicts,
            "key_points": draft["key_points"],
            # the plankarta must have been opened (any chunk of it shown, or a map view of it)
            "evidence": [{"doc_id": candidate["doc_id"]}],
            "map_doc_id": candidate["doc_id"], "applicable_codes": draft.get("applicable_codes"),
            "label_confidence": draft.get("confidence"), "label_explanation": draft.get("explanation"),
            "image": candidate["image"],
            "source": f"{candidate['plan_name']} ({candidate['kommun_name']}), plankarta, around {candidate['label']}",
            "tags": ["plankarta"],
        })
    CASES_PATH.write_text("".join(json.dumps(c, ensure_ascii=False) + "\n" for c in cases), encoding="utf-8")
    write_review_page(cases)
    print(f"{len(cases)} confident cases -> {CASES_PATH} (${cost:.3f} this run); review: {OUT_DIR / 'review.html'}")


def write_review_page(cases: list[dict]) -> None:
    """One page to check the references by eye: the crop, the question, the codes the model applied, its reasons."""
    import html

    blocks = []
    for case in cases:
        points = "".join(f"<li>{html.escape(p)}</li>" for p in case["key_points"])
        blocks.append(
            f"<section><h2>{html.escape(case['id'])} <small>({html.escape(case['label_confidence'] or '')})</small></h2>"
            # images inlined: the page is a single file that can be sent around for review
            f"<img src='data:image/png;base64,{base64.b64encode((OUT_DIR / case['image']).read_bytes()).decode()}'>"
            f"<p><b>Question</b>: {html.escape(case['question'])}</p>"
            f"<p><b>Expected verdicts</b>: {html.escape(', '.join(case['verdicts']))} &nbsp; <b>Codes</b>: "
            f"{html.escape(', '.join(case['applicable_codes'] or []))}</p><ul>{points}</ul>"
            f"<p><i>{html.escape(case['label_explanation'] or '')}</i></p>"
            f"<p>Reference correct? &nbsp;[ ] yes &nbsp;[ ] no &nbsp;[ ] unsure</p></section>")
    (OUT_DIR / "review.html").write_text(
        "<!doctype html><meta charset='utf-8'><title>Plankarta cases – review</title><style>body{font-family:Segoe UI,"
        "Arial;max-width:980px;margin:auto;padding:16px}section{border-bottom:1px solid #ddd;padding:12px 0}"
        "img{max-width:100%;border:1px solid #ccc}small{color:#888}</style><h1>Plankarta cases – review</h1>"
        + "".join(blocks), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Plankarta benchmark cases")
    sub = parser.add_subparsers(dest="command", required=True)
    pick = sub.add_parser("candidates", help="free: pick plans and properties, crop the maps")
    pick.add_argument("--n", type=int, default=40)
    pick.add_argument("--seed", type=int, default=0)
    lab = sub.add_parser("label", help="paid: reference answers with the vision model")
    lab.add_argument("--model", default=DEFAULT_MODEL)
    lab.add_argument("--effort", default="high")
    lab.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()
    os.environ.setdefault("LLM_PROVIDER", "openrouter")
    if args.command == "candidates":
        candidates(args.n, args.seed)
    else:
        label(args.model, args.effort, args.limit)


if __name__ == "__main__":
    main()
