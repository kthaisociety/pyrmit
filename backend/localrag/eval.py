"""
Evaluate local retrieval setups on use-case questions (localrag/questions.jsonl).

A question lists the passages a good answer needs as matcher groups; each group is
searched in its pool (statutes -> "law", kommun pages/documents -> "local"), like the chat
which shows top-5 of each. Metrics per setup:
  recall@k    share of a question's groups found in the top k of their pool (averaged)
  complete@5  share of questions with every group in the top 5
  mrr         mean reciprocal rank of each group's first relevant chunk (top 20)
  kommun      share of questions whose kommun the gazetteer detected

Matcher keys (all must hold): kind (law|page|pdf), doc_type, kommun_code, law (title
substring), section ("9 kap. 4 §"), title (substring), contains (verbatim excerpt(s),
case/space-insensitive); {"any": [...]} for alternatives.

    cd backend
    python -m localrag.eval --models st-bge-m3 st-qwen3-0.6b
    python -m localrag.eval --models st-bge-m3 --setups hybrid --rerank --failures
"""

import argparse
import json
import re
import time
from datetime import datetime
from pathlib import Path

import numpy as np

from corpus.common import read_jsonl
from localrag.gazetteer import detect_kommuner
from localrag.index import INDEX_DIR, load_chunks
from localrag.retriever import LocalRetriever

QUESTIONS_PATH = Path(__file__).resolve().parent / "questions.jsonl"
RESULTS_DIR = INDEX_DIR.parent / "eval"
RERANKER = "BAAI/bge-reranker-v2-m3"

# name -> (mode, dense_lang, bm25 analyzer, query used for BM25)
SETUPS = {
    "dense-en": ("dense", "en", None, None),
    "dense-sv": ("dense", "sv", None, None),
    "dense-both": ("dense", "both", None, None),
    "bm25-en": ("bm25", "en", "compound", "en"),
    "bm25-sv-stem": ("bm25", "en", "stem", "sv"),
    "bm25-sv": ("bm25", "en", "compound", "sv"),
    "hybrid": ("hybrid", "en", "compound", "sv"),
    "hybrid-both": ("hybrid", "both", "compound", "sv"),
    "hybrid-sv": ("hybrid", "sv", "compound", "sv"),
}


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip().lower()


def matches(chunk: dict, matcher: dict) -> bool:
    if "any" in matcher:
        return any(matches(chunk, alternative) for alternative in matcher["any"])
    for key in ("kind", "doc_type", "kommun_code", "section", "doc_id"):
        if key in matcher and chunk.get(key) != matcher[key]:
            return False
    if "law" in matcher and (chunk["kind"] != "law" or matcher["law"].lower() not in chunk["title"].lower()):
        return False
    if "title" in matcher and matcher["title"].lower() not in (chunk.get("title") or "").lower():
        return False
    excerpts = matcher.get("contains", [])
    excerpts = [excerpts] if isinstance(excerpts, str) else excerpts
    text = chunk.setdefault("_normalized", normalize(chunk["header"] + " " + chunk["text"]))
    return all(normalize(excerpt) in text for excerpt in excerpts)


def is_law_matcher(matcher: dict) -> bool:
    if "any" in matcher:
        return is_law_matcher(matcher["any"][0])
    return matcher.get("kind") == "law" or "law" in matcher or "section" in matcher


def prepare(questions: list[dict], chunks: list[dict]) -> None:
    problems = []
    for question in questions:
        question["_groups"] = []
        for matcher in question["relevant"]:
            ids = {c["chunk_id"] for c in chunks if matches(c, matcher)}
            if not ids:
                problems.append(f"{question['id']}: nothing matches {matcher}")
            question["_groups"].append(("law" if is_law_matcher(matcher) else "local", ids))
    if problems:
        raise SystemExit("Unmatched labels:\n  " + "\n  ".join(problems))


def evaluate(retriever: LocalRetriever, questions: list[dict], setup: str, rerank: bool,
             query_field: str = "query_sv") -> list[dict]:
    mode, dense_lang, _, bm25_query = SETUPS[setup]
    rows = []
    for question in questions:
        swedish = question.get(query_field) or question["query_sv"]
        query_sv = swedish if bm25_query == "sv" or dense_lang in ("sv", "both") else None
        if mode == "bm25" and bm25_query == "en":
            query_sv = question["question"]
        result = retriever.search(question["question"], query_sv=query_sv, k=20, mode=mode,
                                  kommuner=question.get("kommun_codes", "auto"), dense_lang=dense_lang,
                                  rerank=rerank, bm25_mode=SETUPS[setup][2])
        ranks = []
        for pool, ids in question["_groups"]:
            ranked = [hit.chunk["chunk_id"] for hit in result[pool]]
            ranks.append(next((i + 1 for i, chunk_id in enumerate(ranked) if chunk_id in ids), None))
        rows.append({
            "id": question["id"],
            "ranks": ranks,
            "kommun_ok": set(question.get("kommun", [])) <= set(result["kommuner"]),
            "top_local": [h.chunk["chunk_id"] for h in result["local"][:3]],
            "top_law": [h.chunk["chunk_id"] for h in result["law"][:3]],
        })
    return rows


def summarize(rows: list[dict]) -> dict:
    def found(rank, k):
        return rank is not None and rank <= k

    return {
        "recall@1": float(np.mean([np.mean([found(r, 1) for r in row["ranks"]]) for row in rows])),
        "recall@5": float(np.mean([np.mean([found(r, 5) for r in row["ranks"]]) for row in rows])),
        "recall@10": float(np.mean([np.mean([found(r, 10) for r in row["ranks"]]) for row in rows])),
        "complete@5": float(np.mean([all(found(r, 5) for r in row["ranks"]) for row in rows])),
        "mrr": float(np.mean([np.mean([1 / r if r else 0 for r in row["ranks"]]) for row in rows])),
        "kommun": float(np.mean([row["kommun_ok"] for row in rows])),
    }


def print_by_tag(questions: list[dict], rows: list[dict]) -> None:
    by_tag: dict[str, list[float]] = {}
    for question, row in zip(questions, rows):
        recall = np.mean([rank is not None and rank <= 5 for rank in row["ranks"]])
        for tag in question.get("tags", []):
            by_tag.setdefault(tag, []).append(recall)
    print("    " + "  ".join(f"{tag} {np.mean(values):.2f} (n={len(values)})" for tag, values in sorted(by_tag.items())))


def print_failures(questions: list[dict], rows: list[dict], by_id: dict[str, dict]) -> None:
    for question, row in zip(questions, rows):
        for (pool, _), matcher, rank in zip(question["_groups"], question["relevant"], row["ranks"]):
            if not rank or rank > 5:
                print(f"    MISS [{question['id']}] rank={rank} {json.dumps(matcher, ensure_ascii=False)[:120]}")
                for chunk_id in row["top_law" if pool == "law" else "top_local"][:2]:
                    print(f"       got: {by_id[chunk_id]['header'][:110]}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate local retrieval setups")
    parser.add_argument("--models", nargs="+", default=["st-bge-m3"])
    parser.add_argument("--setups", nargs="+", default=list(SETUPS))
    parser.add_argument("--rerank", action="store_true", help=f"also run each setup reranked by {RERANKER}")
    parser.add_argument("--questions", type=Path, default=QUESTIONS_PATH)
    parser.add_argument("--tag", help="only questions with this tag")
    parser.add_argument("--failures", action="store_true", help="print groups missed at k=5")
    parser.add_argument("--by-tag", action="store_true", help="print recall@5 per question tag")
    parser.add_argument("--query-field", default="query_sv",
                        help="Swedish query to use: query_sv (hand-written) or query_sv_llm (localrag.rewrite_queries)")
    args = parser.parse_args()

    questions = list(read_jsonl(args.questions))
    if args.tag:
        questions = [q for q in questions if args.tag in q.get("tags", [])]
    kommuner = sorted({code for q in questions for code in q.get("kommun", [])})
    chunks = load_chunks(kommuner)
    by_id = {c["chunk_id"]: c for c in chunks}
    prepare(questions, chunks)
    detected = np.mean([set(q.get("kommun", [])) <= set(detect_kommuner(q["question"])) for q in questions])
    print(f"{len(questions)} questions, {len(chunks)} chunks (laws + kommuner {kommuner}); "
          f"the Wikidata gazetteer alone finds the kommun in {detected:.0%} of questions")

    bm25_modes = tuple(sorted({SETUPS[s][2] for s in args.setups} - {None}))
    dense_needed = any(SETUPS[s][0] != "bm25" for s in args.setups)
    results, details = {}, {}
    for model_index, model in enumerate(args.models if dense_needed else [None]):
        started = time.perf_counter()
        retriever = LocalRetriever(chunks, model=model, bm25_modes=bm25_modes,
                                   reranker=RERANKER if args.rerank else None)
        print(f"# {model or 'bm25 only'} ready in {time.perf_counter() - started:.0f}s", flush=True)
        for setup in args.setups:
            if SETUPS[setup][0] == "bm25" and model_index > 0:
                continue  # BM25 doesn't depend on the embedding model
            if SETUPS[setup][0] != "bm25" and model is None:
                continue
            for rerank in ([False, True] if args.rerank else [False]):
                name = f"{model if SETUPS[setup][0] != 'bm25' else '-'} | {setup}{' +rerank' if rerank else ''}"
                rows = evaluate(retriever, questions, setup, rerank, args.query_field)
                results[name] = summary = summarize(rows)
                details[name] = rows
                print(f"  {name:<48} R@1 {summary['recall@1']:.3f}  R@5 {summary['recall@5']:.3f}  "
                      f"R@10 {summary['recall@10']:.3f}  complete@5 {summary['complete@5']:.3f}  "
                      f"MRR {summary['mrr']:.3f}", flush=True)
                if args.by_tag:
                    print_by_tag(questions, rows)
                if args.failures:
                    print_failures(questions, rows, by_id)
        del retriever

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out = RESULTS_DIR / f"{datetime.now():%Y%m%d-%H%M%S}.json"
    out.write_text(json.dumps({"summary": results, "details": details}, indent=1), encoding="utf-8")
    print(f"\nSaved {out}")


if __name__ == "__main__":
    main()
