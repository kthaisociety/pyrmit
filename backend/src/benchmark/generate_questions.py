"""
Generate synthetic benchmark questions from random corpus chunks with the chat LLM.

Each sampled chunk becomes a question labelled with a verbatim excerpt of that chunk.
Cheap and broad, but biased: the LLM sees the passage, so its wording leaks into the
question. Use it to widen coverage next to the hand-written questions.jsonl, and review
the output (drop questions that several passages could answer).

    cd backend && python -m benchmark.generate_questions --per-source 8
    python -m benchmark.run --questions benchmark/questions.jsonl benchmark/questions.synthetic.jsonl
"""

import argparse
import json
import random

from agents.base import OPENAI_CHAT_MODEL
from benchmark.common import BENCHMARK_DIR, load_corpus, normalize
from llm import get_response_output_text, resolve_model_name
from observability import create_chat_completion, get_openai_client

_INSTRUCTIONS = """You write evaluation questions for a retrieval system over Swedish land law and Vallentuna planning documents.
Given one passage, write the short question a property developer, architect or resident would type that this passage answers.
- One single question, at most 20 words. No multi-part questions.
- Never mention chapter, section or paragraph numbers, document titles, section headings or file names.
- Do not reuse the passage's distinctive wording: paraphrase, as a real user who has not read it would.
- It must be answerable from this passage, and specific enough that few other passages would answer it.
- For planning documents, name the place (e.g. Kristineberg, Mörby, Kumla) when the passage is about one.
Reply with JSON only: {"usable": true|false, "question_en": "...", "question_sv": "..."}.
Set usable=false when the passage is a heading, a figure caption, a table of contents, a list of names or too fragmentary."""


def pick_excerpt(content: str, length: int = 70) -> str | None:
    """A verbatim span from the body (after the "Lag:/Section:" header) that identifies the chunk."""
    body = " ".join(content.split("\n\n", 1)[-1].split())
    if len(body) < 2 * length:
        return None
    start = len(body) // 3
    start = body.find(" ", start) + 1
    return body[start:start + length].rsplit(" ", 1)[0]


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate synthetic benchmark questions")
    parser.add_argument("--per-source", type=int, default=8, help="chunks sampled per law/document")
    parser.add_argument("--min-chars", type=int, default=350)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--model", default=OPENAI_CHAT_MODEL)
    parser.add_argument("--out", default=str(BENCHMARK_DIR / "questions.synthetic.jsonl"))
    args = parser.parse_args()

    corpus = load_corpus()
    rng = random.Random(args.seed)
    client = get_openai_client()
    by_source: dict[str, list[dict]] = {}
    for chunk in corpus:
        if len(chunk["content"]) >= args.min_chars:
            by_source.setdefault(chunk["source"], []).append(chunk)

    written = 0
    with open(args.out, "w", encoding="utf-8") as out:
        for source, chunks in sorted(by_source.items()):
            for chunk in rng.sample(chunks, min(args.per_source, len(chunks))):
                excerpt = pick_excerpt(chunk["content"])
                # The label must point at this chunk only (or its duplicates)
                if not excerpt or sum(normalize(excerpt) in c["_normalized"] for c in corpus) > 2:
                    continue
                response = create_chat_completion(
                    client,
                    model=resolve_model_name(args.model),
                    instructions=_INSTRUCTIONS,
                    input=f"Source: {source}\n\n{chunk['content']}",
                )
                try:
                    generated = json.loads(get_response_output_text(response).strip().strip("`").removeprefix("json"))
                except json.JSONDecodeError:
                    continue
                if not generated.get("usable"):
                    continue
                question = {
                    "id": f"syn-{source}-{chunk['chunk_index']}",
                    "table": chunk["table"],
                    "question_en": generated["question_en"],
                    "question_sv": generated["question_sv"],
                    "relevant": [{"source": source, "contains": excerpt}],
                    "tags": ["synthetic", source],
                }
                out.write(json.dumps(question, ensure_ascii=False) + "\n")
                written += 1
                print(f"[{question['id']}] {question['question_en']}", flush=True)
    print(f"\nWrote {written} questions to {args.out}")


if __name__ == "__main__":
    main()
