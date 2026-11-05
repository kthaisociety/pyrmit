# AGENTS.md

## Project Knowledge

Load these only when the task needs them:

- `max` plugin -- The project skills (`/max:new-ticket` and friends), use these first hand. Enabled by `.claude/settings.json`.
- `CONTEXT.md` -- domain language: what a detaljplan, chunk, verdict etc. mean and how they connect
- `docs/pcr/` -- project-wide conventions (stack, model calls, embeddings, answer language). Binding. Read before changing code.
- `docs/adr/` -- decisions scoped to one part of the codebase. Binding inside their scope.

---

## Package Map

| Name       | Location          | Type                 | Purpose                                                      |
| ---------- | ----------------- | -------------------- | ------------------------------------------------------------ |
| `backend`  | `backend/`        | Python (FastAPI)     | REST API, auth, chat with RAG, ingestion, DB models          |
| `frontend` | `frontend/`       | TypeScript (Next.js) | Chat UI with sidebar session list, auth page, access gate    |
| `agents`   | `backend/src/agents/` | Python               | Multi-agent RAG: LawAgent + DocumentAgent + Orchestrator     |
| `corpus`   | `backend/src/corpus/` | Python (CLI)         | Offline corpus: Wikidata kommuner, Riksdagen laws, kommun website crawl, OCR, text extraction, PDF filter, chunking, plan registry, checks |

---

## API Routes

| Method | Path                               | Purpose                                   |
| ------ | ---------------------------------- | ----------------------------------------- |
| POST   | `/api/access-gate/unlock`          | Pass the access gate, set its cookie      |
| POST   | `/api/auth/signup`                 | Register, returns JWT                     |
| POST   | `/api/auth/signin`                 | Sign in, returns JWT                      |
| POST   | `/api/auth/token`                  | OAuth2 password form login, returns JWT   |
| POST   | `/api/auth/signout`                | Revoke the current login session          |
| GET    | `/api/auth/me`                     | Current user                              |
| PATCH  | `/api/auth/me`                     | Update the profile name                   |
| PATCH  | `/api/auth/password`               | Change the password                       |
| GET    | `/api/sessions`                    | List chat sessions                        |
| GET    | `/api/sessions/{session_id}`       | Messages in a chat session                |
| DELETE | `/api/sessions`                    | Delete all chat sessions                  |
| DELETE | `/api/sessions/{session_id}`       | Delete one chat session                   |
| PATCH  | `/api/sessions/{session_id}`       | Rename a chat session                     |
| POST   | `/api/chat`                        | Send message, get response                |
| POST   | `/api/chat/stream`                 | Send message, stream response (SSE), used by the UI |
| GET    | `/api/history`                     | Message history                           |
| POST   | `/api/chunks/ingest-detaljplan`    | Ingest one detaljplan PDF or Markdown     |
| POST   | `/api/chunks/ingest-data-folder`   | Ingest every file in a data folder        |
| POST   | `/api/analyze`                     | Multi-agent feasibility analysis          |

---

## Database Schema (Key Tables)

| Table              | Key Columns                                                              |
| ------------------ | ------------------------------------------------------------------------ |
| `users`            | id, name, email, email_verified, image                                   |
| `accounts`         | id, user_id (FK), provider_id, password (hash)                           |
| `sessions`         | id (= JWT `sid`), user_id (FK), expires_at; token unused (ADR-0001)      |
| `chat_sessions`    | id, user_id (FK), title, updated_at                                      |
| `chat_messages`    | id, session_id (FK), role, content, trace (JSONB, pipeline events), status (streaming / done / error, assistant only), created_at |
| `document_chunks`  | id, document_id, document_name, chunk_index, content, embedding (3072)  |
| `law_chunks`       | id, law_name, source_file, chapter, section, chunk_index, content, embedding (3072) |

Tables are created at startup by `Base.metadata.create_all` in `backend/src/main.py`, which never alters an existing table: columns added later (`chat_messages.trace`, `status`) are added there with an idempotent `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`. Migrations/init: `backend/src/db/init.sql`. Match functions (pgvector): `backend/src/db/match_functions.sql`.

---

## Build & Run Commands

```bash
# Start all services (db, backend, frontend) via Docker
docker-compose up --build

# Backend only (dev, requires local .env). uv installs from uv.lock (PCR-0009)
cd backend && uv sync && uv run uvicorn main:app --app-dir src --reload --port 8000

# Frontend only (dev). Bun installs from bun.lock (PCR-0009)
cd frontend && bun install && bun run dev

# Backend tests and lint (config in backend/pyproject.toml); the corpus extra holds what the corpus tests import
cd backend && uv sync --extra corpus && uv run pytest
cd backend && uv run ruff check

# Frontend tests and lint
cd frontend && bun run test
cd frontend && bun run test:coverage
cd frontend && bun run lint

# Ingest law chunks (run once after DB is up). Input .txt files go in backend/src/chunking/laws/,
# detaljplan files in backend/src/chunking/data/. Neither folder is tracked, create them locally.
cd backend && uv run python src/chunking/ingest_laws.py

# Ingest a detaljplan PDF via API
curl -X POST http://localhost:8000/api/chunks/ingest-detaljplan \
  -H "Content-Type: application/json" \
  -d '{"input_path": "path/to/plan.pdf"}'
```

### Environment Variables

Backend (`backend/.env`), names as read by the code:

- `DATABASE_URL`
- `AI_GATEWAY_API_KEY` (if set, model calls go through the Vercel AI Gateway) or `OPENAI_API_KEY`
- `LLM_PROVIDER` (openai | gateway | openrouter, with `OPENROUTER_API_KEY` or `OPENROUTER_KEY`), `LLM_MODEL` -- optional chat override (`backend/src/llm.py`)
- `LLM_TIMEOUT_S` (default 180) -- max wait per API response or stream chunk, one retry
- `LLM_REASONING_EFFORT` (answers), `LLM_REWRITE_REASONING_EFFORT` (query rewrite, default low)
- `EMBEDDING_PROVIDER`, `EMBEDDING_MODEL`, `EMBEDDING_DIM`, `EMBEDDING_QUERY_PREFIX`, `EMBEDDING_DOCUMENT_PREFIX` -- embedding model of the pgvector tables (`backend/src/embeddings.py`; default openai text-embedding-3-large at 3072, PCR-0004); `EMBEDDING_RUNTIME` (auto | torch | onnx) for local models
- `RAG_TOP_K` (default 10) -- chunks per pool (laws / documents) given to the answer model
- `MISTRAL_API_KEY` -- PDF OCR
- `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY` -- optional, turn on Langfuse tracing of model calls
- `OPENAI_BASE_URL` -- optional override of the OpenAI endpoint
- `JWT_SECRET_KEY`, `ACCESS_TOKEN_EXPIRE_MINUTES`
- `ACCESS_GATE_PASSWORD`, `ACCESS_GATE_COOKIE_DOMAIN`, `ACCESS_GATE_COOKIE_SAMESITE`, `ACCESS_GATE_COOKIE_SECURE`
- `DEV_ACCESS_PASSWORD`, `APP_ENV`, `CORS_ALLOWED_ORIGINS`, `COOKIE_SAMESITE`, `COOKIE_SECURE`

Frontend (`frontend/.env`):

- `NEXT_PUBLIC_API_URL` (e.g. `http://localhost:8000`)
- `API_PROXY_TARGET`

---

## Key Files Reference

### Backend (Python / FastAPI)

- `backend/src/main.py` -- FastAPI app entry, CORS, router registration
- `backend/src/llm.py` -- chat client and model name resolution (OpenAI, AI Gateway, OpenRouter), Responses API helpers, timeout and retry (PCR-0003)
- `backend/src/embeddings.py` -- `Embedder` (openai / openrouter / a local OpenAI-compatible server / in-process sentence-transformers), `get_embedder()` from `EMBEDDING_*`; the vector column dimension is `EMBEDDING_DIM`; `main.py` logs an error when the tables were embedded with another model (PCR-0003, PCR-0004)
- `backend/src/pipeline_trace.py` -- `CallRecorder` + `recorded_chat_completion` / `recorded_embedding`: prompts, outputs, token usage, cost and timings of every call, for the pipeline inspector
- `backend/src/observability.py` -- Langfuse tracing wrappers for chat and embedding calls, no-op when Langfuse is not configured
- `backend/src/models.py` -- SQLAlchemy ORM models
- `backend/src/schemas.py` -- Pydantic request/response schemas
- `backend/src/security.py` -- JWT creation/decoding, password hashing
- `backend/src/dependencies.py` -- `get_current_session` checks the bearer JWT and its login session row, `get_current_user` returns its user
- `backend/src/routers/access_gate.py` -- Access gate unlock
- `backend/src/routers/auth.py` -- Signup, signin, token, signout, /me, profile, password
- `backend/src/routers/chat.py` -- Chat and streaming chat endpoints, chat session CRUD; the streamed answer is generated in a background thread and saved as it goes (see Chat Request)
- `backend/src/routers/chunks.py` -- Ingestion endpoints
- `backend/src/chunking/ingest_pipeline.py` -- Core ingestion: OCR, chunk, embed, push
- `backend/src/chunking/chunk_detaljplan.py` -- Detaljplan chunker
- `backend/src/chunking/chunk_laws.py` -- Law TXT chunker (chapter/section aware)
- `backend/src/chunking/ingest_laws.py` -- CLI script to ingest all law TXT files
- `backend/src/chunking/embed.py` -- Embedding helpers
- `backend/src/chunking/reembed.py` -- re-embeds the stored chunks with the configured model (alters the vector dimension, stores the model label as the column comment). Needs `--yes`; meant for a dedicated Neon branch
- `backend/src/ocr/` -- Mistral OCR, PDF to Markdown
- `backend/src/corpus/` -- the offline corpus steps (see Offline Corpus): `common.py` (paths: `BACKEND_DIR` = `backend/`, `DATA_ROOT` from `CORPUS_DATA_DIR`), `municipalities.py`, `laws.py`, `crawl.py`, `ocr.py` + `ocr_engines.py` (run in `backend/.venv-ocr`), `extract.py`, `pdf_filter.py`, `chunk.py`, `plans.py`, `check.py`, `snapshot.py`, `caselaw.py` (MÖD rulings for the case benchmark, not searchable), `pdf_files.py` (where the serving code reads crawled PDFs and OCR outputs: crawl folder, else a cache filled from the PDF's URL)
- `backend/src/db/database.py` -- SQLAlchemy engine + `get_db` session factory
- `backend/src/db/push_db.py` -- `PushDB` class: psycopg2 inserts into chunk tables
- `backend/src/db/init.sql` -- DB initialisation (pgvector extension, table creation)
- `backend/src/prompts/land_law_prompt.yaml` -- Prompt that rewrites user questions into Swedish legal search terms

### Frontend (TypeScript / Next.js)

- `frontend/app/(protected)/page.tsx` -- Main page: layout with Sidebar + Chat
- `frontend/app/(protected)/auth/page.tsx` -- Login / signup page
- `frontend/app/dev-access/` -- Access gate form
- `frontend/lib/auth.ts` -- Auth helpers, `authFetch`
- `frontend/components/Chat.tsx` -- message list, SSE stream consumption, session history; a new chat is announced to the sidebar on the `session_id` event; opening another chat aborts the local stream only, and history messages with status `streaming` are fetched again every 2 s until done; the "Process" timeline (one line per step or tool call) until the answer text starts; then "Inspect pipeline" and a clickable Sources list
- `frontend/components/PipelineTrace.tsx` -- the "Inspect pipeline" panel: a totals line (time, tokens, cost), then one collapsible step per stage with its API calls
- `frontend/components/ChunkCard.tsx` -- expandable chunk card; `frontend/components/CitedMarkdown.tsx` -- answer markdown with `[n]` citation chips
- `frontend/components/` also holds the map panel (`place/`), the source viewer and the Benchmark, Pipeline and Database views; each needs backend routes that the port of v2 brings piece by piece (epic #61)
- `frontend/components/Sidebar.tsx` -- Session list, new chat button, user info + logout
- `frontend/components/Settings.tsx` -- User settings

### Agents (Multi-Agent RAG)

- `backend/src/agents/base.py` -- `BaseRAGAgent`: shared embedding, pgvector retrieval, LLM call
- `backend/src/agents/law_agent.py` -- LawAgent on law_chunks
- `backend/src/agents/document_agent.py` -- DocumentAgent on document_chunks
- `backend/src/agents/orchestrator.py` -- Combines both into the verdict
- `backend/src/agents/parsers.py` -- `parse_query`, `format_response`
- `backend/src/agents/AGENTIC_FLOW.md` -- Detailed agent flow
- `backend/src/routers/agents.py` -- POST /api/analyze endpoint

### Tests

- `backend/tests/unit/corpus/` -- crawler rules (robots.txt wildcards, `url_key`, off-topic PDFs, sitemaps), PDF filter (no drop without the LLM or a review), OCR benchmark scoring, PDF download into the cache, the data folder
- `backend/tests/unit/` -- pytest unit tests, one file per module in `backend/src/`, same folder layout. `backend/tests/test_acceptance.py` is the one temporary exception, it exists only on an issue's branch. No real database or model calls (PCR-0011). Most files hold only a docstring so far. Known failures are marked `xfail` with a linked issue.
- `frontend/tests/unit/` -- Vitest + jsdom + React Testing Library, one `*.test.ts(x)` file per module in `components/` and `lib/` (PCR-0007). `frontend/tests/acceptance.test.ts` is the one temporary exception, it exists only on an issue's branch. `lib/auth.test.ts` and `components/Sidebar.test.tsx` are the reference examples; the rest are `it.todo` placeholders.
- `frontend/tests/mocks/handlers.ts` -- MSW fake backend shared by all frontend tests; override per test with `server.use(...)` (PCR-0008). Unhandled requests fail the test.
- `frontend/tests/setup.ts`, `frontend/vitest.config.mts` -- test setup and Vitest config.
- `backend/pyproject.toml` `[tool.ruff.lint.per-file-ignores]` -- ruff baseline of pre-existing problems. Shrink only (PCR-0012).

### CI

- `.github/workflows/frontend.yml` -- `frontend / lint`, `frontend / test`, `frontend / docker` (builds the image, does not publish)
- `.github/workflows/backend.yml` -- `backend / lint`, `backend / test`, `backend / docker` (builds the image and checks key imports)
- Both run on every PR into and push to `dev` and `main`, with no path filter. All six are required checks via the "CI green" ruleset (PCR-0010).

### Team Skills

- `.claude/settings.json` -- enables the `max` plugin from the `release` branch of the `Maxastrand04/Custom-skills` marketplace. The skills are not in this repo. Change them in Custom-skills, merge to `release`, then run `/plugin marketplace update custom-skills`.
- `docs/skills-tutorial.md` -- link to the skills tutorial on GitHub Pages, plus setup notes

---

## Chat Request

The frontend uses `POST /api/chat/stream` (SSE); `POST /api/chat` runs the same logic without streaming.

1. Access-gate middleware, then `get_current_user` checks the bearer JWT and its login session.
2. The chat session is created or looked up; the user message and an empty assistant message (status `streaming`) are saved. The answer is generated in a background thread independent of the HTTP connection: the response only relays its events, so closing the tab or opening another chat neither stops nor loses the answer.
3. A model call rewrites the latest message as a standalone English query (location, units and project type from the last 5 messages).
4. `parse_query` extracts location, units and project type by regex.
5. Location or units missing: general RAG, the query embedded once, the top `RAG_TOP_K` law and document chunks, an answer in English markdown quoting Swedish verbatim (PCR-0006) and a Sources list. Both present: `Orchestrator.analyze` runs LawAgent and DocumentAgent in parallel and applies fixed rules for the verdict.
6. SSE events: `session_id`, `thinking`, `tool_call` / `tool_result`, `pipeline`, `response.output_text.delta`, `response.completed`, `done` (or `error`). `relay()` sends a `: keep-alive` comment after 10 s idle (`SSE_HEARTBEAT_S`), since the Next.js dev proxy drops a stream idle for 30 s; the frontend aborts after 45 s without bytes (`STREAM_STALL_MS`) and reloads the session.
7. The worker updates the assistant message from the events: partial content every 2 s, then the final content, its `trace` (every pipeline event) and status `done` (or `error`).

`pipeline` events (`{type: "pipeline", stage, data}`) feed the inspector: `translation`, `intent`, `retrieval` (matched chunks with source, distance, content), `agent_output`, `verdict`, and `call` (one per model, embedding or search call: model, prompts, output, token usage incl. reasoning tokens and the OpenRouter cost, duration), captured by a `CallRecorder` passed to the agents. They are saved in `chat_messages.trace` (~20-60 KB per answer), so a reopened conversation keeps its inspector and sources.

Gotchas: a location the regex misses ("for Vallentuna": only in / at / i / på / vid count) silently takes the general RAG path; the units regex misses "apartment(s)", which the rewrite makes of "lägenheter".

---

## Offline Corpus

Everything lives in `backend/data/` (gitignored, ~20 GB with PDFs; only `data/agentic/` (benchmark results) and
`data/eval/` are versioned). The README has the install, data sharing and rebuild guide with times and sizes. `uv sync --extra corpus` installs the backend in editable mode with `backend/src` on the path, so the commands run from `backend/` (`.venv/Scripts/python -m corpus.crawl` on Windows); the local embedding models need `--extra local` and torch with CUDA. Steps, from `backend/`:

```
python -m corpus.municipalities   # Wikidata -> data/corpus/municipalities.json (290 kommuner, websites, ~10k localities)
python -m corpus.laws             # Riksdagen open data -> data/corpus/raw/laws/*.txt (15 consolidated SFS)
python -m corpus.crawl            # kommun websites -> data/corpus/raw/web/<code>/{pages,pdf,manifest.jsonl}
python -m corpus.ocr              # PP-OCRv6 (backend/.venv-ocr, GPU) of PDFs flagged needs_ocr -> raw/web/<code>/ocr/
python -m corpus.extract          # -> data/corpus/documents.jsonl (PyMuPDF text blocks, OCR text when available)
python -m corpus.pdf_filter features|classify|llm|apply   # relevance filter of the crawled PDFs (see below)
python -m corpus.chunk            # -> data/corpus/chunks.jsonl (one chunk per law §, ~1500-char doc chunks)
python -m localrag.index --model st-arctic-l-v2  # embeddings -> data/index/dense/<model>/ (incremental)
python -m localrag.store --model st-arctic-l-v2  # disk store served by the app: SQLite (chunks, FTS5 BM25, places) + vectors.npy
python -m localrag.eval --models st-bge-m3 ... # retrieval eval on localrag/questions.jsonl -> data/eval/ (tagged with the corpus)
python -m corpus.plans            # detaljplan registry + planbestämmelser -> data/corpus/plans.jsonl (needs the store)
python -m corpus.check            # data checks after a rebuild (exit 1 on an error); then agentic.replay, agentic.coverage score
```

- `corpus.plans` (rule-based, ~30 s): a plan = the detaljplan PDFs of a kommun whose file names reduce to the same
  key (role words, dates, versions, agenda numbering removed), named by the plan page that links only them, else by
  "Detaljplan för ..." on the first page; plan pages without PDFs are plans too (listing pages excluded). Status from
  the page URL and the documents (laga kraft date, ANTAGANDE/GRANSKNINGS/SAMRÅDSHANDLING). Provisions = coded lines
  (e1, h1, f2, B, +0.0...) and measure sentences after "PLANBESTÄMMELSER" (looser on plankartor, stricter in
  planbeskrivningar), with law ref, topics (building_area, height, storeys, plot_size, no_building, ...) and numbers.
  Each is tied to its chunk for citation; `corpus.chunk` drops paragraphs repeated across the corpus (standard plan
  wording), so ~2 % fall back to a chunk of the same plankarta (`exact: false`). ~8.2k plans / 260 kommuner, ~1.4k
  with ~15.6k provisions. Which map area carries which code is not extracted (needs the vision model).
- `corpus.ocr` writes the job list (`data/corpus/ocr_jobs.jsonl`) by tier (`TIERS`, `ocr_tier`; a first page larger
  than A3 = a map; plan documents typed "other" count as plans: `PLAN_WORDS` / the current `doc_type` rules, e.g.
  Huddinge's "Bestämmelse0126k-7018", Kalix's "_PK" files), every page: 1 plan maps and provisions (~12.5 h, 5.4k
  PDFs), 2 plan texts (~16 h), 3 other planning types (~4 h), 4 studies attached to plans (~1 h), 5 other (~12 h), ~46 h
  in all (2026-10-24, 0.66 s per tile); `MAX_TIER = 5` (`--max-tier` stops earlier); short documents first within a
  tier; outputs of any PP-OCRv6 setting are kept once their cut lines are joined (`"text_from": "words"`), EasyOCR's
  are redone. Cut lines: a printed line crossing a tile edge is read cut in both tiles; until 2026-10-24 21:00 both
  were kept whole ("gäller bestämm iller bestämmelsen inom", 2x the repeated word pairs); now each tile gives the
  line's words of its core (each engine word carries its line number) and `join_cut_lines` glues a word cut by the
  edge ("byggnads" + "byggnadsarea"); the ~1.4k outputs from before are redone after the unread PDFs of their tier.
  GPU memory: DirectML keeps the buffers of every input shape it has run (recognition batch widths vary), so one
  process grew from ~3 to 7 GB of the 8 GB in 2 h, spilled into shared memory and read ~35 % fewer words per second;
  the worker exits after `RECYCLE_PAGES` (250) pages with `RECYCLE_EXIT` and `corpus.ocr` starts a fresh one (its
  skip test reads only the first bytes of each output), or sooner when the card's used memory (`nvidia-smi`, all
  processes) passes `RECYCLE_GPU_MB` (6.5 GB, after `RECYCLE_MIN_PAGES`): text pages took it to 7.4 GB within 250 pages. MuPDF refuses to decode a whole image over its size limit
  ("Overly large image": a 20674 x 19691 px scan of a 2.6 m Strömstad plankarta, 1 page of the 11k scans) and
  rendered the page blank; `render` then renders it in 2000 px strips. Speed (2026-10-24, same 24 first-night PDFs: 249 -> 152 s, -39 %, 4 % fewer words):
  detection input capped at 1280 px (`DET_SIDE`, `--det-side 0` = whole 2000 px tile: same words and labels on the
  benchmark, 139 vs 140 of 305); recognition cut to its 550 Latin characters (`latin_rec_model`, of 18,710: the
  multilingual model also reads Chinese...; output layer and metadata character list sliced, made once in
  `<venv>/fast/`: ~35x less copied to the CPU per batch, same or better accuracy); `speed_up_rapidocr` (detection
  pre-processing with `cv2.dnn.blobFromImage` instead of float64 numpy, word boxes one matrix product per line:
  -12.5 % on real plans, identical words). One process (`WORKERS = 1`, `--shard i/n` exists): on real plan pages two
  were 34 % slower in total (small benchmark crops had shown +28 %: measure on real pages).
  CUDA (`--cuda`, `backend/.venv-ocr-cuda` with onnxruntime-gpu 1.23 and torch's CUDA 12 / cuDNN 9 DLLs,
  `use_cuda_dlls`): cuDNN re-plans every convolution (~3 s) whenever an input shape changes, so `FixedShapes` pads
  inputs to a few fixed shapes, one session each; then no faster than DirectML (0.55 vs 0.51 s per tile) and its
  float16 models read nothing (overflow): DirectML stays the default and starts `corpus/ocr_engines.py --jobs` in `backend/.venv-ocr`
  (PP-OCRv6 medium on DirectML; text pages at 300 dpi, pages larger than A3 at 200, 40 pages max). Each
  `ocr/<pdf id>.json` holds `pages` (text in reading order, what `corpus.extract` uses) and `words` ([page, x0, y0, x1,
  y1, text, score] in PDF points of the unrotated page, like `get_text("words")`: `view_map_area` finds labels there on
  scans). Resumable (an output of the same engine is skipped). ~10.5k scanned PDFs / 44k pages at ~1.1 s per 2000 px
  tile = ~66 h of GPU (5-35 s per plankarta); then rerun `corpus.extract`, the PDF filter, `corpus.chunk`, `localrag.index`, `localrag.store`,
  `corpus.plans`. It needs the GPU memory the backend's store takes (vectors ~3.9 GB + model): run it with the app
  stopped. The child process gets no `PYTHONHOME` (the .venv interpreter sets it to its own 3.13 base: inherited,
  .venv-ocr's 3.12 loaded the 3.13 stdlib, "SRE module mismatch").

- The crawler parses HTML with the charset httpx found (lxml alone read pages without a declared charset as latin-1:
  "fÃ¶r" in titles and link texts, ~285 documents of Haninge, Göteborg, Sala, Tranås...); `corpus.extract` repairs titles
  crawled before (`common.repair_mojibake`). Their pages were also scored on garbled titles when crawled.
- The crawler honours robots.txt (`robots_parser`: Google's `*` / `$`, which urllib.robotparser ignores), 1 req/s per host,
  caps per kommun, resumes (a kommun whose manifest ends with `{"done": true}` and caps >= the requested ones is skipped).
  Pages are kept on topic keywords (`content_relevance`); links are followed on `link_relevance` (a negative word in a
  long link text, e.g. "... livsmedel" in Surahammar's home card, no longer hides an on-topic section) and from the home
  page also the site index (`_SITE_INDEX`: Webbkarta, A-Ö; Härryda builds its menus in JavaScript); pages at the last
  depth (4) still give their PDF links (all three fixed 2026-10-23, after a first full crawl that day: Härryda and
  Surahammar had 0 pages). A page about plans (`_PLAN_PAGE` in its path or title: a plan, a list of plans) at the last
  depth still gives the plan pages it links (`_PLAN_PAGE` in their path), one level further, and every PDF it links
  is taken unless `off_topic_pdf` ("Lagakraftbevis", "Protokollsutdrag", "1507-280-torsberg-139-mfl.pdf" have no plan
  word, some a negative one); elsewhere a plan word in the PDF's name or link text outweighs a negative word (both
  2026-10-25, from the coverage benchmark's causes; `PDF_LINKS_VERSION` 3). PDFs when linked from relevant pages, minus the obvious noise only
  (`off_topic_pdf` on file name + link text: annual reports, alcohol licences, estate notices... unless a plan word;
  each skipped link is recorded in the manifest as `{"type": "skipped_pdf", ...}`, which readers ignore). Everything
  else is judged by `corpus.pdf_filter` after extraction; `corpus.extract` has no topic test any more (until 2026-10-23
  a longer list, incl. avfall / kallelse / budget / förskol, dropped 407 PDFs there on the metadata title, one a
  planuppdrag decision whose template title was "Kallelse", and the crawler skipped 2,176 links unrecorded).
  `corpus.crawl --revisit` re-reads only the pages that linked a kommun's PDFs, its stored pages and sitemaps, and
  adds the PDF links its manifest lacks, for manifests whose done line has `pdf_links` < `PDF_LINKS_VERSION`
  (bump it when the PDF link rules change): ~35k requests for the country instead of ~160k for `--force` (Norrtälje:
  314 vs 1,174 requests, 11 PDFs added, 7 of them plan investigations). One copy per `url_key` (http/https and www. variants) and per content hash (also deduplicated per kommun in
  `corpus.extract`). Caps (defaults): 1000 pages, 3000 PDFs, 40 MB per PDF, 15000 requests (2026-10-23; at 1000 PDFs /
  6000 requests 9 kommuner sat at the cap, at the older 30 PDFs 232 of 286). Göteborg (1480) answered nothing on the
  2026-10-23 crawl and keeps its old 30-PDF crawl. The manifest is written to
  `manifest.jsonl.part` and replaces `manifest.jsonl` at the end, unless the crawl got nothing (site down: the previous
  crawl stays); the done line records caps, `queue_left` and `skipped`. `resolve_root` follows the home redirect (Ängelholm ->
  engelholm.se; 404 home -> host root; http -> https), `parse_sitemap` survives bad bytes (Luleå), the client uses the
  Windows certificate store (`truststore`, Högsby) and HTTP/2 (Malmö's HTTP/1.1 headers break h11), `.stockholm` hosts are
  one site (plans on vaxer.stockholm, permits on bygglov.stockholm). Karlskrona answers 403 to the crawler.
  Wikidata websites that are wrong are fixed in `municipalities.WEBSITE_FIXES` (Gällivare: gellivare.se no longer
  answers, gallivare.se). 11 crawled PDFs end without `%%EOF` (7 unreadable, e.g. Västerås "Ärende" plankartor):
  downloaded again on 2026-10-25, the kommun servers send the same cut file.
  The technical report (section 5.1, `report_technical.design_choices`) lists these choices with their effect: update it
  when a setting changes.
- `corpus.chunk` recognises a chapter only on its own line after a blank line, so wrapped references ("4 kap.
  miljöbalken") don't open chapters; also "10 Kap." (JB) and a bare "14 kap." before its title or its 1 § (FBL), and a
  heading wrapped onto two lines is not glued to the next one (before 2026-10-22: MB 4 kap., JB 7/10/11 kap., FBL 1/14 kap.,
  MPF 4 kap., PBF 7 kap. were filed under the previous chapter; the text and chunk ids did not change); lettered paragraphs (`6 a §`) are separate chunks; transitional provisions dropped.
  Chunk ids include a text hash (not the header): `localrag.index` keeps a digest of each embedded header + text
  (`dense/<model>/digests.json`) and re-embeds in place the chunks whose header changed.
  Scale (since the 2026-10-23 crawl, ~60k PDFs, ~8x the corpus before): `corpus.extract` and `corpus.chunk` write
  documents / chunks as they come (the lists took the 16 GB machine's memory); `localrag.index` reads chunks.jsonl
  twice from disk (count, then batches) and writes into `dense/<model>/vectors.npy` opened as a memmap that grows by
  steps (`VectorStore._reserve`; rows past `len(ids.json)` are unused room; ids.json is saved every 50k chunks, after
  the vectors, so an interrupted run resumes). Before, `np.vstack` + `np.save` of the whole matrix after every batch
  was quadratic. `corpus.plans` still holds the detaljplan texts in RAM (1-2 GB). `tests/test_index.py`.
- PDF relevance filter (`corpus/pdf_filter.py`, 2026-10-23; data in `data/corpus/pdf_filter/`): the big crawl also
  brings kommun administration (miljöbalk fees, HR policies, flag rules, meeting packs...). Rules on title / file name /
  link text (`KEEP` wins over `DROP`; `KEEP_HEAD` on the first page), then a logistic regression on arctic vectors of
  those fields + the first 700 chars (trained on the rule labels, cached vectors) keeps when p >= 0.85. **No PDF is
  dropped on a rule or the model alone** (the user's rule: losing a useful document is worse than keeping noise):
  proposed drops and uncertain PDFs go to MiMo Flash (`llm`, ~$0.0001 each, keeps in doubt), except the deterministic
  `SURE_DROP` words (`by: "sure-rule"`, only while the LLM has not answered and the first page has no `KEEP` word):
  the 21 DROP words the judges confirmed on >= 97 % of >= 15 judged PDFs (`agreement` prints the measure; 2026-10-25:
  sotning 130/132, skolskjuts 65/65, socialtjänst 55/55...; DROP as a whole only 2,499 of 3,250), so a rebuild
  without the paid `llm` step still drops those; the biggest uncertain ones
  were reviewed by hand (`corpus/pdf_review.jsonl`, versioned, wins over everything). `corpus.extract` skips the
  PDFs whose decision is `keep: false`; PDFs without a decision (new crawl) are kept until `features` + `classify`
  + `llm` + `classify` + `apply` (removes them from documents.jsonl without re-extracting). `llm --check-model N`
  measures the LLM's agreement with the model on a sample. Error that matters = useful documents dropped:
  `eval-sample` prints random drops (not the reviewed ones) to label in `corpus/pdf_filter_eval.jsonl` (versioned),
  `eval` gives the share per decision path with a Wilson interval (2026-10-23: 2/120, both Environmental Code fee
  schedules, which carry the enskilt avlopp permit fee: `taxa ... miljöbalk` moved from DROP to KEEP, 120 PDFs
  come back at the next classify). `tests/test_pdf_filter.py`.
- OCR benchmark (`corpus/ocr_bench.py` + `corpus/ocr_engines.py`, 2026-10-23): `sample` picks plan pages
  (synthetic = text-layer plankartor / planbeskrivningar rendered at 200 dpi and degraded like a scan, reference =
  the text layer with word boxes; real = old scans, crops transcribed by hand in `corpus/ocr_reference.jsonl`,
  versioned, words only), `crops` cuts the real crops, each engine runs from its own environment
  (`ocr_engines.py --engine easyocr|rapid-v6-small|rapid-v6-medium [--gpu]`, large pages in 2000 px tiles), `score`
  -> `data/eval/ocr-<date>.json`: words read (bag of words: a map has no reading order), within 1-2 edits, property
  labels (`\d+:\d+`; also counted when read with "." or ","), words at the right place (synthetic). PP-OCRv6 runs
  through RapidOCR (ONNX) in `backend/.venv-ocr` (gitignored) on **DirectML** (`onnxruntime-directml`; 0.75 s per
  2000 px tile with word boxes, 4.8 s on the CPU): `onnxruntime-gpu` failed on its recognition model (cuDNN errors
  with the CUDA 13 build, an illegal memory access in QuickGelu with the CUDA 12 one). Images in `data/ocr_bench/`.
  Results 2026-10-23 (real map crops / synthetic maps / synthetic text pages, words read exactly): EasyOCR (used
  before) 69 / 45 / 92 %, 0 of 13 property labels (the colon of "3:204" comes out as a point); PP-OCRv6 small
  84 / 49 / 89 %, 6 labels; **medium 87 / 52 / 93 %, 8 labels** (chosen). The synthetic maps' reference is noisy (CAD
  hatch glyphs, split words); words under 12 px are read 16 % of the time, and neither enlarging the image nor
  rendering the scans at 300 dpi helped on maps (300 dpi did help the typewritten page: 84 vs 73 %).
  Speed (2026-10-24, `ocr_engines.py --det-side N`, `-fp16` engines): float16 copies of the models (`fp16_models`,
  onnxconverter-common installed with --no-deps) are no faster on DirectML; detection ~40 % / recognition ~50 % of a
  tile's time; capping the detection input at 1280 px -25 % with no loss on synthetic maps, 960 px -36 % (-9 % of the
  labels), small -32 % (-14 % labels, -5 points on text pages), small + 1280 -50 %. A rented RTX 4090 (~$0.34/h) would
  do the whole backlog for a few dollars (not tried). `tests/test_ocr_bench.py`.
- Corpus snapshots: `CORPUS_DATA_DIR` (relative to `backend/`, default `data`) selects the directory holding
  `corpus/` + `index/`; benchmark results and evals stay in `data/agentic` / `data/eval` (`common.RESULTS_ROOT`).
  `data/small` = the 2026-10-22 corpus (7.8k PDFs, 349k chunks; for demos / the PoC): `CORPUS_DATA_DIR=data/small`
  in `.env` serves it. Its `corpus/raw` is a directory junction to `data/corpus/raw` (same PDFs), so
  `corpus.check --delete-orphan-pdfs` keeps the PDFs any snapshot's documents.jsonl references.

---

## Debugging Principle

> If a bug occurs, you should always be able to answer:
> **"Is this a data/retrieval bug (backend) or a display/UX bug (frontend)?"**

- **Auth bugs**: Missing/expired bearer token, 401s -> investigate `backend/src/routers/auth.py`, `backend/src/security.py`, `backend/src/dependencies.py`. Redirects to the access gate -> `backend/src/routers/access_gate.py`, `frontend/lib/`
- **RAG quality bugs**: open "Inspect pipeline" on the answer (rewritten query, route, retrieved chunks with distances); then `backend/src/agents/base.py`, the embedding model, chunk sizes. `_embed` returns None on failure (e.g. a missing key for `EMBEDDING_PROVIDER`) and retrieval then silently returns nothing
- **Ingestion bugs**: Chunks not appearing in DB -> investigate `backend/src/chunking/ingest_pipeline.py`, `backend/src/db/push_db.py`
- **Chat bugs**: Wrong answer, missing context -> investigate `backend/src/routers/chat.py` prompt construction and retrieval call
- **Frontend bugs**: UI not updating, session not switching, auth redirect loop -> investigate `frontend/components/`

---

## Maintenance

After every successful change, update the file that owns what changed: this file for routes, schema, commands, env vars and key files; `CONTEXT.md` for domain terms. Never edit a file in `docs/pcr/` outside a `/challenge-pcr` session.
