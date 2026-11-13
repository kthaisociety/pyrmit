# Source and chunk schema

The labels every source and chunk in the corpus carries. For the developers of law ingestion, plan ingestion and hybrid search.

## Records

| Record | Holds |
| --- | --- |
| Document | The master copy of the labels that describe the whole source. |
| Chunk | Its document link, plus copies of the labels search filters on: place, law chapter and section, and for plan chunks the plan ID and plan stage. |
| Plan registry | Plans and their provisions (plan codes with their rules). Plan stage is kept here too. |

## Labels

`required` / `optional` per chunk kind. `-` = does not apply.

| Label | Meaning | Law | Plan document | Web page |
| --- | --- | --- | --- | --- |
| Source | The exact address of the original | required | required | required |
| Place | `national` for laws, otherwise the municipality name | required | required | required |
| Fetch date | When the source was downloaded | required | required | required |
| Date in force | When the source took effect | optional | optional | optional |
| Plan ID | Official plan number with the municipality code when known, otherwise the generated ID. The old generated ID is kept as an alias | - | optional | - |
| Plan stage | Where the plan is in its process | - | optional | - |
| Law chapter and section | Chapter and section of the statute | optional | - | - |
| Plan code | A code on the plan map with its rule (registry only) | - | optional | - |
| Content fingerprint | Hash of the content, the one version-style label. It can always be computed, so ingestion should always fill it | optional | optional | optional |

## When labels are filled in

| Step | Labels |
| --- | --- |
| Download | Fetch date |
| Text extraction | Plan ID, plan stage |
| Chunking | Chunk copies of the document's labels |

## Rules

- A chunk missing source, place or fetch date is rejected and reported, never loaded silently.
- A plan without an official number gets the generated ID; the old ID stays as an alias.
- An unknown date stays empty and is never guessed.

## Notes

Decisions that are not part of the schema itself:

- All plans are stored whatever their stage.
- If plan grouping needs the finished search store, plan ID and plan stage are copied onto chunks in a step afterwards.

How things are today (2026-11-13, #106), from `corpus/extract.py`, `chunk.py`, `crawl.py`, `plans.py`, `laws.py`, `localrag/store.py` and `localrag/pg_store.py`.

| Label | Lives today | Missing |
| --- | --- | --- |
| Source | `url` on the document and the chunk | |
| Place | `place` on the document and the chunk: `national` for laws, otherwise the municipality name. `kommun` and `kommun_code` stay beside it, null for laws, for the kommun filters | |
| Fetch date | `fetched_at` (ISO 8601, UTC) on the document and the chunk, with `fetched_at_source`: `recorded` when the crawler (page files, PDF manifest lines) or `corpus.laws` (`index.json`) wrote it at download, `file_mtime` for files downloaded before they did (the raw file's modification time, written once at download) | The legacy Vallentuna documents (no date and no address: their chunks are rejected) |
| Date in force | Plans: `laga_kraft` in the registry, as found in the text | Laws (the "t.o.m. SFS" header is not stored) |
| Plan ID | `plan_id` in the registry, generated from municipality code, name and document IDs; `plan_number` (read from the text) beside it. Copied onto plan documents by `corpus.extract` (the registry's grouping, which needs no store) and onto their chunks | Official number as the ID, the alias |
| Plan stage | `status` in the registry: `in_force`, `adopted`, `review`, `consultation`, `in_progress`, `repealed`, `unknown`. Copied as `plan_stage` with the plan ID | |
| Law chapter and section | On law chunks: `chapter`, `paragraph` (section), and `section` as the combined label (`4 kap. 5 §`). On other chunks `section` holds the heading | |
| Plan code | `provisions` in the registry, each tied to a `chunk_id` | |
| Content fingerprint | `content_sha1`: on the document the SHA-1 of its whitespace-normalised text, on the chunk the same of its lowercased text (the hash inside the chunk ID). `localrag.index` keeps a digest of header plus text | |

Also set today and copied from document to chunk: document link (`doc_id`).

The labels are metadata only: what gets embedded (header plus text) and the chunk ID do not depend on them, so adding them re-embeds nothing. `corpus.chunk` writes a chunk missing source, place or fetch date to `rejected_chunks.jsonl` instead of `chunks.jsonl`; `localrag.store` and `localrag.pg_store` refuse such a row too.

Not covered here: the older `document_chunks` and `law_chunks` tables (current corpus only), a law-version label (possible later addition) and a job that refreshes stale laws.
