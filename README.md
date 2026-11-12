# Pyrmit - Building Permit Agent

<table>
  <tr>
    <td valign="middle">
      Pyrmit answers questions about Swedish building permits and land-use planning (<i>Plan- och bygglagen</i>, detaljplaner, bygglov, enskilt avlopp...). A tool-calling agent searches a local corpus — 15 consolidated statutes and the planning pages and PDFs of 286 kommun websites — and answers in English, quoting the Swedish sources with clickable citations that open the original document at the passage.
    </td>
    <td valign="middle">
      <img src="frontend/public/pyrmit_middle.jpg" alt="Pyrmit Logo" width="300" />
    </td>
  </tr>
</table>

**Stack**: Next.js (frontend), FastAPI (backend), SQLite + NumPy vectors (local corpus), Neon Postgres (users and chats), OpenRouter (agent model), Snowflake arctic-embed-l-v2 (embeddings, GPU or CPU).

Architecture, data flow and every module are described in [`AGENTS.md`](AGENTS.md); the domain terms in [`CONTEXT.md`](CONTEXT.md), the project-wide conventions in [`docs/pcr/`](docs/pcr/) and the decisions of each part in [`docs/adr/`](docs/adr/).

**Reports** ([`reports/`](reports/)):
- [Benchmark report](reports/pyrmit_benchmark_report.pdf): agent vs RAG, effort settings, cost and latency on the case benchmarks.
- [Technical report](reports/pyrmit_technical_report.pdf): Swedish planning context, data sources, pipeline and evaluation method.
- Hosting report ([PDF](reports/pyrmit_hosting_report.pdf) / [Markdown](reports/pyrmit_hosting_report.md)): embedding model choice, CPU (ONNX) benchmark, database and storage options, hosting costs.

---

## Try it without the data (corpus hosted on Neon)

The Neon `demo` branch holds a corpus of three kommuner and the statutes: Uppsala (with the map: plan layers, property lookup), Vallentuna, Stockholm (few plans) and the 15 laws. The app queries it directly and embeds the questions through OpenRouter: no GPU, no model and no corpus to download. Only questions about these three kommuner find their documents.

Requirements: Python 3.13 + [uv](https://docs.astral.sh/uv/), [Bun](https://bun.sh/), and the `.env.demo` a maintainer sends you (database URLs, OpenRouter key), saved as `backend/.env`. Never commit it: the repository is public.

```bash
git clone https://github.com/kthaisociety/pyrmit.git && cd pyrmit/backend
uv sync --extra corpus     # every package from uv.lock, no torch
cd ../frontend && bun install
```

`backend/.env`:

```properties
CHAT_MODE=agent
RETRIEVAL_BACKEND=local
LOCAL_RAG_STORE=neon
LOCAL_RAG_MODEL=or-bge-m3              # questions embedded through OpenRouter, same vectors as the stored ones
LLM_PROVIDER=openrouter
OPENROUTER_KEY=...                     # agent model + query embeddings, about $0.01 per answer
DATABASE_URL=postgresql://...          # Neon demo branch: users, chats and the corpus
CORPUS_DATABASE_URL=postgresql://...   # the same URL
JWT_SECRET_KEY=...                     # any long random string
```

Run the backend and the frontend as in [Run](#run) below, open <http://localhost:3000> and sign up. At startup the backend writes the few files it reads from disk (gazetteer, plan registry, Uppsala's map layers, about 25 MB) into `backend/data/`; a cited PDF is downloaded from the kommun's site the first time it is opened, then kept in `backend/data/cache/pdf/`.

### The PDFs, and keeping the corpus fresh

The database holds the text of every document, so searching and reading never depend on the kommun websites. The PDF files are not in it (Uppsala's alone weigh 9.5 GB), and two parts of the app need them: opening a cited passage in its PDF, and the agent's map tools, which look at a plankarta. There are two ways to serve them:

| | How | How robust |
|---|---|---|
| **Today: from the kommun websites** | The backend downloads a PDF from its original URL the first time it is needed and keeps it in `backend/data/cache/pdf/`. Scanned plankartor also need the words the OCR read on them, which the kommun sites don't have: they come from the database. | Free and nothing to upload, but it relies on the sites. A link dies when a kommun reorganises its website; a file replaced at the same URL may no longer match the indexed text (wrong page, wrong highlight, wrong position on the map); a site can be down or slow (up to ~30 s for a 40 MB plan). The agent then keeps the text and loses only the PDF view. On 2026-10-31, 65 PDFs drawn at random all answered with the crawled file. |
| **Next: our own copies in object storage** | The crawl already downloads every PDF: upload them to a bucket, Cloudflare R2 (about $3.5 a month for the 244 GB of the national crawl, no egress fees) or Neon Object Storage (5 GB free per project, enough for the demo's 2.1 GB of plankartor), and read them from there, with the kommun site as a last resort. | Robust: the file served is the one that was indexed, whatever the websites do. |

Either way the corpus ages: kommuner adopt new plans and revise their översiktsplan. Re-run `python -m corpus.crawl --revisit` from time to time (it re-reads only the pages that list PDFs), then rebuild the snapshot and reload the database (`CLAUDE.md`, "Hosted demo").

---

## Quick start (with the shared data)

### Requirements

| | Why |
|---|---|
| Python 3.13 + [uv](https://docs.astral.sh/uv/) | Backend |
| [Bun](https://bun.sh/) | Frontend (lockfile is `bun.lock`) |
| 8 GB RAM | Embedding model (0.9–1.7 GB) + store + backend |
| 2 GB disk (+18.4 GB with the PDFs) | Local corpus (see [Data](#data)) |
| NVIDIA GPU (optional) | Faster query embeddings; **required only to rebuild the corpus** |
| `backend/.env` | API keys, Neon `DATABASE_URL`, `JWT_SECRET_KEY`, access-gate password. Ask a maintainer; never commit it. Template: `backend/.env.example` |

### Install

```bash
git clone https://github.com/kthaisociety/pyrmit.git && cd pyrmit/backend
uv sync --extra corpus     # the backend from uv.lock, editable: `python -m corpus.crawl` etc. run from backend/

# torch BEFORE the local models, so nothing pulls the wrong build
uv pip install torch --index-url https://download.pytorch.org/whl/cu128   # NVIDIA GPU
uv pip install torch --index-url https://download.pytorch.org/whl/cpu     # no GPU (Linux; on Windows/macOS plain `uv pip install torch`)

uv pip install -e ".[corpus,local]"   # + sentence-transformers and onnxruntime for the local embedding models

cd ../frontend && bun install
```

### Add the data and the config

1. Download and unpack the data into `backend/data/`: see [Get the data](#get-the-data) below.
2. Put `.env` in `backend/`. The local agent setup needs at least:

   ```properties
   CHAT_MODE=agent
   RETRIEVAL_BACKEND=local
   LOCAL_RAG_MODEL=st-arctic-l-v2
   LLM_PROVIDER=openrouter
   OPENROUTER_KEY=...            # agent model (openai/gpt-6-luna by default)
   DATABASE_URL=postgresql://... # Neon: users and chats
   JWT_SECRET_KEY=...
   ACCESS_GATE_PASSWORD=...
   HF_HUB_DISABLE_XET=1          # Hugging Face downloads can hang on Windows without it
   ```

### Run

```bash
# backend (from backend/) — Windows path shown; .venv/bin/python on Linux/macOS
.venv/Scripts/python.exe -m uvicorn main:app --app-dir src --port 8000
# frontend (from frontend/)
bun run dev
```

Tests: `cd frontend && bun run test` (Vitest with a fake backend, no server needed) and `cd backend && uv run pytest` (no database, model or corpus needed, PCR-0011); lint with `uv run ruff check` and `bun run lint`. CI runs all of them on every PR into `dev` or `main` (PCR-0010).

Map (the place card beside the chat): `cd backend && python -m place.fetch --kommun 0380` copies Uppsala's plans, land-use zones, protected areas and national interests into `backend/data/geo/` (about 10 s, open data); restart the backend afterwards. Without it the map says every place is "not covered yet".

Other kommuner: `python -m place.plan_layers` copies the plan layer of every kommun in `backend/src/place/plan_sources.json` (180 kommuner with an open ArcGIS or WFS layer, from the survey in `docs/research/kommun-planlager.md`) into `backend/data/geo/<code>/` and writes `backend/data/geo/plan_coverage.md`, one line per kommun: fetched or not and why, polygons against the survey's count, share with an aktbeteckning and with a document link. `--kommun 0182` takes some of them. A pin there gives the kommun and the plans at the point, no property or zones. `python -m place.registry` rebuilds the registry from the survey, keeping the base patterns and licences edited into it by hand.

Plan documents: `python -m place.plan_links` matches every plan polygon of every snapshot to the document store's detaljplan documents (`data/corpus/documents.jsonl`; by link, by aktbeteckning in the title, file name or first page of text, or by name for review) into `backend/data/geo/<code>/plan_links.jsonl`, lists the unmatched polygons' links in `backend/data/geo/plan_fetch_list.json` for the scraper and writes `backend/data/geo/plan_match_report.md`. Restart the backend afterwards: the place card's plans then carry their document ids.

Plan text in the hosted corpus: `python -m place.plan_links --kommun 0380 --hosted` matches Uppsala's plan polygons against the PDFs of the corpus database at `CORPUS_DATABASE_URL`, through the plan registry's plan pages, and writes the link table and `backend/data/geo/0380/plan_text_report.md`: the share of polygons with text and why the others have none. A pin then lists each plan's documents with their role on the place card. Whichever run last wrote a kommun's table decides its links, so a later run without `--hosted` replaces them.

Polygons in the corpus database: `python -m localrag.pg_store --files` adds or replaces the place snapshots of every fetched kommun (`backend/data/geo/<code>/`, gzip, about 90 MB for 147 kommuner) in the corpus database at `CORPUS_DATABASE_URL`, without touching the chunks or the plan registry; `--kommun 0380` takes some of them. It stops before writing, saying how much it needed, when the database would pass `--limit-mb` (1000, the free plan). A backend starting with `LOCAL_RAG_STORE=neon` and no snapshots writes them to disk from there, so the map and the place lookup work on an install without local data; a snapshot the install fetched itself is never overwritten.

Review mode: the "Review" button on the map panel colours every kommun by whether it has plan polygons (from `backend/data/geo/plan_coverage.json`, the rows behind the coverage report) and, zoomed in, draws the polygons in view by match level. It reads the snapshots and link tables above, so run those first and restart the backend.

Lookup benchmark (no model calls): `python -m place.bench candidates --kommun 0380` proposes places covering the hard cases (`place/cases_draft_0380.jsonl`); check each by hand, fill in its `expected` layers and `checked`, set `locked` to the date and move it to `place/cases.jsonl`; then `python -m place.bench run --label <name>` scores the lookup per layer (`data/agentic/place-bench-*.json`) and `python -m place.bench compare <a> <b>` compares two runs.

Place evaluation (report: `reports/place_eval_report.md`):
- `python -m place.check_sources --n 300` (free) checks the snapshots against each provider's own point query.
- `python -m place.check_search --n 150 --form typed|lower|no_letter` (free) searches Uppsala's register addresses through the map search.
- `python -m place.bench_answers run --repeats 3` (paid, about $1 for 120 answers) has the chat agent answer the locked cases in `place/cases_answers.jsonl` with and without a pin, and their general questions the same way. `rejudge <file> --judge-model openai/gpt-6-luna` adds a second judge; `compare <before.json> <after.json>` puts two runs side by side (tool calls, searches, points, cost).
- `python -m place.report --sources … --search name=… --answers … [--compare name=…]` builds the report from the result files and `place/report_findings.md`.

Open <http://localhost:3000>, enter the access-gate password, then sign up. The first start downloads the embedding model from Hugging Face (2.3 GB on a GPU, 570 MB on a CPU), then preloads the store in about 30–60 s.

> `docker-compose.yml` predates the local corpus (no data mount, no GPU): use the manual setup above.

---

## Embeddings: GPU or CPU, chosen automatically

The query embedding model is `Snowflake/snowflake-arctic-embed-l-v2.0` (568M parameters, 1024 dims, multilingual). `EMBEDDING_RUNTIME` (default `auto`) picks how it runs:

| Hardware | Runtime | Query time | Model RAM | Recall (R@5 / R@10) |
|---|---|---|---|---|
| CUDA GPU | torch fp16 | 23 ms | 1.7 GB | 0.944 / 0.956 |
| CPU only | **ONNX int8** (official export, `onnxruntime`) | 34 ms | 0.9 GB | 0.944 / 0.956 |
| (for reference) CPU with torch fp32 | `EMBEDDING_RUNTIME=torch` | 141 ms | 3.4 GB | 0.944 / 0.956 |

- Force a runtime with `EMBEDDING_RUNTIME=torch` or `EMBEDDING_RUNTIME=onnx`.
- The int8 query vectors are compatible with the index built on the GPU: recall is unchanged on the 45-question eval.
- Measured on an i7-12700H / RTX 4060 Laptop.

**Why this model?** On our eval (45 labelled questions, `backend/src/localrag/eval.py`), arctic matched the best API models at recall@5 (gemini-embedding-001 0.93, Qwen3-8B 0.91, bge-m3 0.91) with the best R@1 and MRR. It runs locally for free and is not available on OpenRouter. Translating the question to Swedish before searching matters most (bge-m3: 0.63 → 0.91). BM25 fusion and a reranker did not help.

---

## Data

Everything lives in `backend/data/` (not in git, except the benchmark results in `data/agentic/` and the retrieval evals in `data/eval/`).

| Pack | Paths (under `backend/data/`) | Size | Needed for |
|---|---|---|---|
| **Minimum** | `index/store/st-arctic-l-v2/`, `corpus/municipalities.json`, `corpus/plans.jsonl` | **1.5 GB** | The app: search (SQLite + FTS5 BM25 + vectors), kommun detection, plan registry |
| **PDFs** | `corpus/raw/web/*/pdf/`, `corpus/raw/web/*/ocr/` | **18.4 GB** | Opening a cited PDF at the passage; the agent reading plankartor (`view_map_area`, `view_pdf_page`) |
| Rebuild only | `corpus/chunks.jsonl`, `corpus/documents.jsonl`, `index/dense/st-arctic-l-v2/`, `corpus/raw/laws/`, `corpus/raw/web/*/pages` + `manifest.jsonl` | 1.8 GB | Re-chunking, incremental re-indexing, resuming the crawl |

Without the PDFs the app works fully, except that PDF sources show the cited chunks only, and the map tools return an error.

### Get the data

**Download**: <https://www.swisstransfer.com/dl/01a12498-77b3-7256-8eba-ccead24ab77a>

The link was created on October 10, 2026. It is active until October 25, 2026 and can be extended once, up to November 9, 2026, with at most 250 downloads. Once it expires, ask a maintainer for a new link (see [Sharing a new snapshot](#sharing-a-new-snapshot)), or rebuild the corpus (next section).

| File | Size | Contents | Get it if |
|---|---|---|---|
| `pyrmit-data-min.tar.gz` | 0.9 GB (1.5 GB unpacked) | Minimum pack | Always |
| `pyrmit-data-pdfs.tar` | 18.8 GB | PDFs pack (7,798 PDFs + OCR text) | You want PDF sources and the map tools |
| `pyrmit-data-rebuild.tar.gz` | 0.9 GB (1.8 GB unpacked) | Rebuild pack | You will re-chunk, re-index or recrawl |

**This snapshot and the current code.** The code reads the October 10 snapshot as is. The snapshot predates the corpus
fixes of October 22: statute chapters filed under the previous chapter (miljöbalken 4 kap., jordabalken 7, 10 and 11 kap.,
fastighetsbildningslagen 1 and 14 kap., miljöprövningsförordningen 4 kap., plan- och byggförordningen 7 kap.: 125 sections
that `law_section` could not find) and about 285 garbled document titles ("fÃ¶r"). With the Rebuild pack, apply the
chapter fix in about 5 minutes from `backend/`: `python -m corpus.chunk`, `python -m localrag.index --model st-arctic-l-v2`,
`python -m localrag.store --model st-arctic-l-v2`. The titles also need `python -m corpus.extract` first, which needs the
PDFs pack.

Download the files one by one. "Download all" makes a single 19 GB zip that you would have to unzip first. Then unpack them **from `backend/`**: the archives contain `data/...` paths. `tar` is built into Windows 10+, macOS and Linux.

```bash
cd pyrmit/backend
tar -xzf ~/Downloads/pyrmit-data-min.tar.gz        # required
tar -xf  ~/Downloads/pyrmit-data-pdfs.tar          # optional, 18.8 GB
tar -xzf ~/Downloads/pyrmit-data-rebuild.tar.gz    # optional
ls data/index/store/st-arctic-l-v2                 # -> corpus.sqlite  meta.json  vectors.npy
```

In PowerShell, use `$HOME\Downloads\pyrmit-data-min.tar.gz`. Plan for twice the size on disk while unpacking; the archives can be deleted afterwards.

Optional integrity check: `sha256sum <file>` (Linux/macOS) or `Get-FileHash <file>` (PowerShell) should match:

| File | SHA-256 |
|---|---|
| `pyrmit-data-min.tar.gz` | `b64c12af2df865220bbb588b44a356e3410ee724cde8c9ad7a281156e5b51537` |
| `pyrmit-data-pdfs.tar` | `6f5e773914c85bdc689e065b04e8dc8f43f5ce60d69d88a9a9c06e446b9a1484` |
| `pyrmit-data-rebuild.tar.gz` | `6a1bb28e60f8625879c9b81a4858adc662bcf85d4ad4607be4cb68b087d57ef6` |

### Sharing a new snapshot

After a rebuild, run from `backend/` (about 10 min):

```bash
tar -czf pyrmit-data-min.tar.gz data/index/store/st-arctic-l-v2 data/corpus/municipalities.json data/corpus/plans.jsonl
tar -cf  pyrmit-data-pdfs.tar data/corpus/raw/web/*/pdf data/corpus/raw/web/*/ocr
tar -czf pyrmit-data-rebuild.tar.gz data/corpus/chunks.jsonl data/corpus/documents.jsonl data/index/dense/st-arctic-l-v2 data/corpus/raw/laws data/corpus/raw/web/*/pages data/corpus/raw/web/*/manifest.jsonl
sha256sum pyrmit-data-*.tar*
```

Then upload the three files in one [SwissTransfer](https://www.swisstransfer.com) transfer: "Link" mode, 30 days, 250 downloads. Uploading 19 GB takes about 40 min to 1 h at 8 MB/s; keep the tab open. Finally, update the link, the dates and the checksums above.

| Service (free plan) | Limit | Fits |
|---|---|---|
| **SwissTransfer** | 50 GB per transfer, 15 days (+15 on request), 250 downloads, no account | Everything |
| Smash | No size limit (transfers over 2 GB are queued) | Everything |
| WeTransfer | 3 GB per 30 days, 10 transfers | Minimum pack only |
| Google Drive | 15 GB | Minimum pack only |

---

## Rebuilding the local corpus (GPU machine)

From `backend/`. Each step reads the previous step's output. Times and sizes come from the October 2026 run (i7-12700H, RTX 4060, 286 kommuner).

| # | Command | Time | Output | Why |
|---|---|---|---|---|
| 1 | `python -m corpus.municipalities` | 1 min | `corpus/municipalities.json` (0.25 MB) | 290 kommuner + 10k localities from Wikidata: crawl seeds, and detecting the kommun in a question |
| 2 | `python -m corpus.laws` | 1 min | `corpus/raw/laws/` (2 MB) | 15 consolidated statutes (PBL, PBF, MB...) from Riksdagen open data, always current |
| 3 | `python -m corpus.crawl` | **3–4 h** | `corpus/raw/web/` (18.6 GB) | Planning pages and PDFs (detaljplaner, taxor, översiktsplan) of each kommun. Slow on purpose: robots.txt, 1 request/s per site. Resumable |
| 4 | `python -m corpus.ocr` (optional) | **~18 h** | `raw/web/*/ocr/` (8 MB) | 777 scanned PDFs (mostly old plankartor) have no text layer. EasyOCR on the GPU |
| 5 | `python -m corpus.extract` | ~5 min | `corpus/documents.jsonl` (394 MB) | Text blocks from HTML and PDFs (PyMuPDF; OCR text when available). Stops if crawled PDFs are missing (`--allow-missing-pdfs` to drop them) |
| 6 | `python -m corpus.chunk` | < 1 min | `corpus/chunks.jsonl` (496 MB) | 348k chunks: one per law §, about 1,500 characters for documents, with a context header |
| 7 | `python -m localrag.index --model st-arctic-l-v2` | **1–1.5 h** | `index/dense/st-arctic-l-v2/` (690 MB) | Embeddings (93 chunks/s on the GPU; about 53 h on a CPU). Incremental: only new chunks are embedded |
| 8 | `python -m localrag.store --model st-arctic-l-v2` | ~2 min | `index/store/st-arctic-l-v2/` (1.46 GB) | What the app serves: SQLite (chunks, FTS5 BM25, places) + float16 vectors |
| 9 | `python -m corpus.plans` | ~30 s | `corpus/plans.jsonl` (8.7 MB) | Detaljplan registry + planbestämmelser for the agent's `plans` / `plan_rules` tools |

- **Total: about 5 h, or about 1 day with OCR.** Add 5–15 min for the model download and about 15 min to install CUDA torch on a fresh machine.
- **Incremental runs are fast.** Finished kommuner are skipped (`--force` recrawls them), and chunk ids include a text hash, so step 7 only embeds what changed.
- After OCR, rerun steps 5 to 9. Restart the backend after step 8.
- Rebuild on a GPU, then share the result: re-indexing on a CPU takes about 53 h and OCR takes days.

---

## Benchmarks

| | Command | Cost |
|---|---|---|
| Retrieval eval (45 questions, recall@k / MRR) | `python -m localrag.eval --models st-arctic-l-v2 --setups dense-sv` | free (local models) |
| Agent benchmark (feasibility, case-law and plankarta cases) | `python -m agentic.bench ...` (see `agentic/bench.py`) | **spends API credits** (about $0.01 per answer) |
| Grounding of the answers | `python -m agentic.grounding <results.json>` | API credits |
| PDF reports | `python -m agentic.report`, `python -m agentic.report_technical` | free (reads the result files) |

Cases are in `backend/src/agentic/cases*.jsonl`. Past results are in `backend/data/agentic/` (versioned, about 50 MB) and can be browsed in the app's **Benchmark** tab. The PDF reports regenerate into `../pyrmit_doc/`; copy the ones worth sharing into `reports/`.

---

## Cost and hosting (summary)

- **LLM**: about $0.007–0.011 per agent answer (GPT-6 Luna via OpenRouter, medium effort), so about $10 per 1,000 questions. It is the main cost.
- **Hosting**: the simplest setup is one VPS (4 vCPU / 8 GB / 80 GB, about €7–15 per month) with the store and the PDFs on disk, using the ONNX CPU runtime. Neon free tier keeps users and chats, and Vercel or the same VPS serves the frontend.
- **Later, at scale**: corpus on Neon pgvector (about 2.5–3 GB) and PDFs on Cloudflare R2 (about $0.13 per month). This needs the store ported to Postgres.

---

## Project layout

```
pyrmit/
├── backend/
│   ├── src/
│   │   ├── main.py            # FastAPI app, access gate, routers, store preload
│   │   ├── embeddings.py      # embedding providers + GPU/ONNX runtime selection
│   │   ├── routers/           # auth, chat (SSE), docs (open cited PDFs), benchmark, db browser, pipeline, place
│   │   ├── agentic/           # tool-calling agent, tools, benchmark, cases, reports
│   │   ├── localrag/          # disk store, retriever, BM25 analyzer, gazetteer, eval, models.toml
│   │   ├── corpus/            # pipeline: municipalities, laws, crawl, ocr, extract, chunk, plans, caselaw
│   │   ├── place/             # map pin: snapshots, plan layers, plan-document links, live lookups
│   │   └── agents/, chunking/ # earlier pgvector RAG + feasibility agents (RETRIEVAL_BACKEND=pgvector)
│   ├── tests/unit/            # pytest, mirrors src/ (no database, model or corpus)
│   ├── data/                  # corpus, index, benchmark results (mostly gitignored)
│   ├── pyproject.toml, uv.lock
├── frontend/                  # Next.js: chat, sources viewer, pipeline inspector, database, benchmark, map
├── docs/                      # pcr/ (project conventions), adr/ (decisions per part), research/
├── reports/                   # benchmark, technical and hosting reports (PDF / Markdown)
├── AGENTS.md                  # architecture, data flow, gotchas (CLAUDE.md points to it)
└── CONTEXT.md                 # domain terms
```
