"""
Benchmark embedding models on the frozen corpus (retrieval only, no LLM).

Each question is searched in its own table (law_chunks or document_chunks), like the
chat which retrieves top-5 from each. Reported per model:
  hit@k     share of questions with at least one relevant chunk in the top k
  recall@k  share of a question's expected passages found in the top k (averaged)
  MRR@10    mean of 1/rank of the first relevant chunk

    cd backend
    python -m benchmark.export_corpus                       # once, freezes the chunks
    python -m benchmark.run                                 # every model in models.toml
    python -m benchmark.run --models te3-large or-bge-m3    # a subset
    python -m benchmark.run --lang sv --failures            # Swedish questions, list misses

Corpus embeddings are cached in benchmark/cache/<model>/ (in shards, so an interrupted
run resumes); results are written to benchmark/results/.
"""

import argparse
import hashlib
import json
import time
import tomllib
from datetime import datetime
from pathlib import Path

import numpy as np

from benchmark.common import (
    CACHE_DIR,
    MODELS_PATH,
    QUESTIONS_PATH,
    RESULTS_DIR,
    load_corpus,
    read_jsonl,
    relevant_sets,
)
from embeddings import EmbeddingConfig, Embedder

KS = (1, 3, 5, 10)
SHARD_SIZE = 500


def load_models(names: list[str] | None) -> dict[str, dict]:
    with MODELS_PATH.open("rb") as file:
        models = tomllib.load(file)["models"]
    if names:
        unknown = set(names) - set(models)
        if unknown:
            raise SystemExit(f"Unknown models {sorted(unknown)}; defined: {sorted(models)}")
        return {name: models[name] for name in names}
    return {name: entry for name, entry in models.items() if not entry.get("skip")}


def make_embedder(entry: dict) -> Embedder:
    fields = {key: value for key, value in entry.items() if key not in {"skip", "notes"}}
    return Embedder(EmbeddingConfig(**{"dim": None, **fields}))


def corpus_embeddings(name: str, embedder: Embedder, corpus: list[dict]) -> np.ndarray:
    config = embedder.config
    fingerprint = hashlib.sha256(
        json.dumps([config.provider, config.model, config.document_prefix, [c["id"] for c in corpus]]).encode()
        + "".join(c["content"] for c in corpus).encode()
    ).hexdigest()[:16]
    cache = CACHE_DIR / name / fingerprint
    cache.mkdir(parents=True, exist_ok=True)

    shards = []
    started = time.perf_counter()
    for shard_index, start in enumerate(range(0, len(corpus), SHARD_SIZE)):
        path = cache / f"shard_{shard_index:04d}.npy"
        if not path.exists():
            texts = [chunk["content"] for chunk in corpus[start:start + SHARD_SIZE]]
            np.save(path, np.asarray(embedder.embed_documents(texts), dtype=np.float32))
            print(f"  {name}: {min(start + SHARD_SIZE, len(corpus))}/{len(corpus)} chunks "
                  f"({time.perf_counter() - started:.0f}s)", flush=True)
        shards.append(np.load(path))
    return np.vstack(shards)


def l2_normalize(matrix: np.ndarray) -> np.ndarray:
    return matrix / np.clip(np.linalg.norm(matrix, axis=1, keepdims=True), 1e-12, None)


def evaluate(corpus, corpus_matrix, questions, query_matrix, lang) -> list[dict]:
    tables = np.array([chunk["table"] for chunk in corpus])
    scores = l2_normalize(query_matrix) @ l2_normalize(corpus_matrix).T
    per_question = []
    for row, question in enumerate(questions):
        candidates = np.flatnonzero(tables == question["table"])
        order = candidates[np.argsort(-scores[row, candidates])]
        rank_of = {int(index): rank for rank, index in enumerate(order[:100], start=1)}
        ranks = [min((rank_of.get(i, 10**6) for i in group), default=10**6) for group in question["_relevant"]]
        first = min(ranks)
        per_question.append(
            {
                "id": question["id"],
                "lang": lang,
                "table": question["table"],
                "tags": question.get("tags", []),
                "first_rank": first if first < 10**6 else None,
                "group_ranks": [rank if rank < 10**6 else None for rank in ranks],
                "top": [int(index) for index in order[:5]],
            }
        )
    return per_question


def summarize(rows: list[dict]) -> dict:
    if not rows:
        return {}
    summary = {"n": len(rows)}
    for k in KS:
        summary[f"hit@{k}"] = np.mean([r["first_rank"] is not None and r["first_rank"] <= k for r in rows])
    summary["recall@5"] = np.mean(
        [np.mean([rank is not None and rank <= 5 for rank in r["group_ranks"]]) for r in rows]
    )
    summary["mrr@10"] = np.mean([1 / r["first_rank"] if r["first_rank"] and r["first_rank"] <= 10 else 0 for r in rows])
    return {key: value if key == "n" else float(value) for key, value in summary.items()}


def print_table(results: dict[str, dict[str, dict]]) -> None:
    columns = ["hit@1", "hit@5", "hit@10", "recall@5", "mrr@10"]
    for scope in ("all", "law", "document"):
        print(f"\n## {scope}")
        print(f"{'model':<28}{'lang':<6}{'n':>4}" + "".join(f"{c:>10}" for c in columns))
        for name, by_lang in results.items():
            for lang, scopes in by_lang.items():
                summary = scopes.get(scope)
                if summary:
                    print(f"{name:<28}{lang:<6}{summary['n']:>4}" + "".join(f"{summary[c]:>10.3f}" for c in columns))


def print_failures(name, rows, questions_by_id, corpus, k) -> None:
    misses = [r for r in rows if r["first_rank"] is None or r["first_rank"] > k]
    print(f"\n## {name}: {len(misses)} questions without a relevant chunk in the top {k}")
    for r in misses:
        question = questions_by_id[r["id"]]
        print(f"\n[{r['id']}] ({r['lang']}, first relevant rank: {r['first_rank'] or '>100'})")
        print(f"  Q: {question['question_' + r['lang']]}")
        for index in r["top"][:3]:
            chunk = corpus[index]
            preview = " ".join(chunk["content"].split())[:140]
            print(f"  - {chunk['source']}#{chunk['chunk_index']}: {preview}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark embedding models on the frozen corpus")
    parser.add_argument("--models", nargs="*", help="model names from models.toml (default: all not skipped)")
    parser.add_argument("--questions", nargs="*", type=Path, default=[QUESTIONS_PATH])
    parser.add_argument("--lang", choices=["en", "sv", "both"], default="both",
                        help="en matches the chat, which embeds the English rewrite of the question")
    parser.add_argument("--tag", help="only questions with this tag")
    parser.add_argument("--failures", action="store_true", help="list questions missed at k=5")
    args = parser.parse_args()

    corpus = load_corpus()
    questions = [q for path in args.questions for q in read_jsonl(path)]
    if args.tag:
        questions = [q for q in questions if args.tag in q.get("tags", [])]
    for question in questions:
        question["_relevant"] = relevant_sets(question, corpus)
        empty = [m for m, group in zip(question["relevant"], question["_relevant"]) if not group]
        if empty:
            raise SystemExit(f"Question {question['id']}: no chunk matches {empty}")
    questions_by_id = {q["id"]: q for q in questions}
    langs = ["en", "sv"] if args.lang == "both" else [args.lang]

    results: dict[str, dict[str, dict]] = {}
    details: dict[str, list[dict]] = {}
    for name, entry in load_models(args.models).items():
        print(f"\n# {name} ({entry['provider']}:{entry['model']})", flush=True)
        embedder = make_embedder(entry)
        try:
            corpus_matrix = corpus_embeddings(name, embedder, corpus)
        except Exception as exc:
            print(f"  FAILED: {exc}")
            continue
        results[name] = {}
        details[name] = []
        for lang in langs:
            asked = [q for q in questions if q.get(f"question_{lang}")]
            query_matrix = np.asarray(
                [embedder.embed_query(q[f"question_{lang}"]) for q in asked], dtype=np.float32
            )
            rows = evaluate(corpus, corpus_matrix, asked, query_matrix, lang)
            details[name].extend(rows)
            results[name][lang] = {
                "all": summarize(rows),
                "law": summarize([r for r in rows if r["table"] == "law"]),
                "document": summarize([r for r in rows if r["table"] == "document"]),
            }
            if args.failures:
                print_failures(name, rows, questions_by_id, corpus, k=5)

    print_table(results)

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out = RESULTS_DIR / f"{datetime.now():%Y%m%d-%H%M%S}.json"
    out.write_text(
        json.dumps(
            {
                "questions": [str(path) for path in args.questions],
                "n_questions": len(questions),
                "corpus_size": len(corpus),
                "summary": results,
                "per_question": details,
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    print(f"\nSaved {out}")


if __name__ == "__main__":
    main()
