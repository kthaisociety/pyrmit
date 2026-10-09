"""
Freeze the chunks currently in DATABASE_URL into benchmark/data/corpus.jsonl.

Every model is benchmarked on this same file, so results stay comparable even if the
database is re-ingested or re-chunked later (re-export to benchmark a new chunking).

    cd backend && python -m benchmark.export_corpus
"""

import json
import os

from sqlalchemy import create_engine, text

from benchmark.common import CORPUS_PATH

_QUERIES = {
    "law": "SELECT id, law_name, chapter, chapter_title, section, chunk_index, content FROM law_chunks",
    "document": "SELECT id, document_name, NULL, NULL, NULL, chunk_index, content FROM document_chunks",
}


def main() -> None:
    engine = create_engine(os.environ["DATABASE_URL"])
    rows = []
    with engine.connect() as connection:
        for table, query in _QUERIES.items():
            for chunk_id, source, chapter, chapter_title, section, chunk_index, content in connection.execute(
                text(query + " ORDER BY 2, chunk_index, id")
            ):
                rows.append(
                    {
                        "id": chunk_id,
                        "table": table,
                        "source": source,
                        "chapter": chapter,
                        "chapter_title": chapter_title,
                        "section": section,
                        "chunk_index": chunk_index,
                        "content": content or "",
                    }
                )

    CORPUS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with CORPUS_PATH.open("w", encoding="utf-8") as file:
        for row in rows:
            file.write(json.dumps(row, ensure_ascii=False) + "\n")
    counts = {table: sum(row["table"] == table for row in rows) for table in _QUERIES}
    print(f"Wrote {len(rows)} chunks to {CORPUS_PATH} {counts}")


if __name__ == "__main__":
    main()
