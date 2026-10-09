"""
Post-hoc groundedness of benchmark answers: a judge checks each factual claim of an answer
against the full text of the sources the answer cites ([c:<chunk_id>]), instead of against the
short reference key points (which penalises correct details the reference doesn't mention).

    cd backend && LLM_PROVIDER=openrouter python -m agentic.grounding data/agentic/bench-....json
"""

import argparse
import json
import os
import re
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from agentic.agent import DEFAULT_MODEL
from llm import get_openai_client, get_response_output_text, resolve_model_name
from localrag.index import chunk_text
from localrag.store import DiskStore, store_dir

STORE_MODEL = "st-arctic-l-v2"

INSTRUCTIONS = """You check whether an answer is grounded in its cited sources.
List the specific factual claims of the answer (rules, numbers, deadlines, fees, document facts, legal references);
ignore generic advice. For each, decide if the cited sources support it.
Return JSON only: {"claims": <int>, "supported": <int>, "unsupported_examples": ["<short claim>", ...up to 3]}."""


def main() -> None:
    parser = argparse.ArgumentParser(description="Groundedness of benchmark answers against cited sources")
    parser.add_argument("results", type=Path, nargs="+")
    args = parser.parse_args()
    os.environ.setdefault("LLM_PROVIDER", "openrouter")
    client = get_openai_client()
    model = resolve_model_name(DEFAULT_MODEL)
    # Chunks read on demand from the disk store's SQLite (chunks.jsonl in RAM is several GB)
    db = sqlite3.connect(store_dir(STORE_MODEL) / "corpus.sqlite", check_same_thread=False)
    db.row_factory = sqlite3.Row
    lock = threading.Lock()

    class Chunks:
        def __contains__(self, chunk_id: str) -> bool:
            return self[chunk_id] is not None

        def __getitem__(self, chunk_id: str) -> dict | None:
            with lock:  # one connection shared by the grading threads
                row = db.execute("SELECT * FROM chunks WHERE chunk_id = ?", (chunk_id,)).fetchone()
                if row is None and len(chunk_id) < 16:  # truncated id: unique prefix, as CorpusTools.get_chunk
                    rows = db.execute("SELECT * FROM chunks WHERE chunk_id >= ? AND chunk_id < ? LIMIT 2",
                                      (chunk_id, chunk_id + "g")).fetchall()
                    row = rows[0] if len(rows) == 1 else None
            return DiskStore._chunk(row) if row else None

    chunks = Chunks()

    for path in args.results:
        rows = json.loads(path.read_text(encoding="utf-8"))

        def grade_row(row: dict) -> None:
            if not row.get("answer"):
                return
            cited = list(dict.fromkeys(re.findall(r"c:([0-9a-f]{8,16})(?![0-9a-f])", row["answer"])))
            sources = "\n\n".join(f"[c:{cid}]\n{chunk_text(chunks[cid])}" for cid in cited if cid in chunks)
            response = client.responses.create(
                model=model, reasoning={"effort": "medium"}, instructions=INSTRUCTIONS,
                input=f"Cited sources:\n\n{sources or '(none)'}\n\nAnswer:\n{row['answer']}",
            )
            text = get_response_output_text(response).strip().strip("`").removeprefix("json").strip()
            try:
                grade = json.loads(text)
                row["grounded"] = grade["supported"] / max(grade["claims"], 1)
                row["claims"] = grade["claims"]
                row["unsupported_examples"] = grade.get("unsupported_examples", [])
            except (json.JSONDecodeError, KeyError):
                row["grounded"] = None
            row["cited_sources"] = len(cited)
            print(f"  {row['case']:<26} {row['system']:<6} cited {len(cited):>2}  claims {row.get('claims', '?'):>3}  "
                  f"grounded {row['grounded'] if row['grounded'] is None else round(row['grounded'], 2)}", flush=True)

        with ThreadPoolExecutor(max_workers=8) as pool:  # independent judge calls
            list(pool.map(grade_row, rows))
        path.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
        for system in sorted({row["system"] for row in rows}):
            values = [row["grounded"] for row in rows if row["system"] == system and row.get("grounded") is not None]
            if values:
                print(f"{path.name} {system}: grounded {sum(values) / len(values):.2f} over {len(values)} answers")


if __name__ == "__main__":
    main()
