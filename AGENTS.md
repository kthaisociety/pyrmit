# AGENTS.md

## Project Knowledge

Load these only when the task needs them:

- `max` plugin -- The project skills (`/max:new-ticket` and friends), use these first hand. Enabled by `.claude/settings.json`.
- `CONTEXT.md` -- domain language: what a detaljplan, chunk, verdict etc. mean and how they connect
- `docs/source-chunk-schema.md` -- the labels every source and chunk of the corpus carries (required / optional per kind, where each lives today)
- `docs/pcr/` -- project-wide conventions (stack, model calls, embeddings, answer language). Binding. Read before changing code.
- `docs/adr/` -- decisions scoped to one part of the codebase. Binding inside their scope.

---

## Project Overview

Pyrmit is a Swedish legal RAG (Retrieval-Augmented Generation) chat assistant focused on Swedish land law and urban planning regulations (*fastighetsrätt*, *Plan- och bygglagen*). Planning documents (detaljplaner as PDF) are OCR-processed (Mistral), chunked, and embedded into a PostgreSQL+pgvector database alongside chunked Swedish law texts. The chat translates the user's question to English, retrieves relevant law and document chunks, and calls an OpenAI model (directly or via Vercel AI Gateway) to answer **in the question's language** (Swedish or English, English for any other), quoting Swedish source text verbatim (PCR-0006). When a question contains both a location and a number of units, a multi-agent feasibility analysis runs instead of plain RAG.

---

## System Topology

```
User (browser)
    |
    | fetch('/api/...') with Authorization: Bearer <JWT> (token kept in localStorage)
    v
Next.js Frontend (frontend/ -- port 3000)
    |
    | next.config.js rewrite: /api/* -> API_PROXY_TARGET (default http://localhost:8000)
    v
FastAPI Backend (backend/ -- port 8000)
    |
    |--- Access-gate middleware (main.py + dev_access.py) -- global password, cookie
    |--- Access gate router (/api/access-gate/unlock)
    |--- Auth router   (/api/auth/*)      -- signup, signin, token, signout, me, password
    |--- Chat router   (/api/chat, /api/chat/stream, /api/sessions/*, /api/history)
    |--- Chunks router (/api/chunks/*)    -- ingest detaljplan PDF/markdown, ingest data folder
    |--- Agents router (/api/analyze)     -- multi-agent feasibility analysis
    |--- DB browser    (/api/db/*)        -- read-only browse/search of law_chunks & document_chunks
    |
    |--- Agents (agents/)
    |       |--- BaseRAGAgent: embed (direct OpenAI) + pgvector cosine search + LLM call
    |       |--- LawAgent -> law_chunks, DocumentAgent -> document_chunks
    |       |--- Orchestrator: runs both in parallel, rule-based feasibility verdict
    |
    |--- Chunking pipeline (chunking/ + ocr/)
    |       |--- PDF -> Mistral OCR -> Markdown
    |       |--- Markdown/TXT -> DetaljplanChunker / LawChunker
    |       |--- OpenAI text-embedding-3-large (3072-dim)
    |       |--- PushDB (psycopg2 on DATABASE_URL) -> document_chunks / law_chunks
    |
    |--- Observability (observability.py) -- optional Langfuse tracing of LLM calls & retrieval
    |
    v
PostgreSQL + pgvector (hosted on Neon; DATABASE_URL in backend/.env)
    Tables: users, accounts, sessions (login sessions, ADR-0001), chat_sessions, chat_messages,
            document_chunks (Vector 3072), law_chunks (Vector 3072)
```

Note: `docker-compose.yml` still defines a local `db` pgvector container (seeded with `backend/src/db/init.sql`), but the backend talks to whatever `DATABASE_URL` points at — normally Neon, so the local container sits unused.

---

## Package Map

| Name       | Location          | Type                 | Purpose                                                      |
| ---------- | ----------------- | -------------------- | ------------------------------------------------------------ |
| `backend`  | `backend/`        | Python (FastAPI)     | REST API, auth, chat with RAG, ingestion, DB models          |
| `frontend` | `frontend/`       | TypeScript (Next.js) | Chat UI with sidebar session list, auth page, access gate    |
| `agents`   | `backend/src/agents/` | Python               | Multi-agent RAG: LawAgent + DocumentAgent + Orchestrator     |
| `localrag` | `backend/src/localrag/` | Python             | Local retrieval: GPU embeddings, Swedish BM25, hybrid + rerank, kommun gazetteer, disk store, hosted corpus store, eval |
| `agentic`  | `backend/src/agentic/` | Python              | Tool-calling agent over the corpus (`CHAT_MODE=agent`), case benchmarks, reports |
| `place`    | `backend/src/place/` | Python               | Place lookup for the map pin: snapshots, plan source registry, plan-document links, live property and ancient remains, likely permits, address search, evaluations |
| `corpus`   | `backend/src/corpus/` | Python (CLI)         | Offline corpus: Wikidata kommuner, Riksdagen laws, kommun website crawl, OCR, text extraction, PDF filter, chunking, plan registry, checks |

---

## State Ownership

| Concern                        | Owner          | Key File(s)                                                       |
| ------------------------------ | -------------- | ----------------------------------------------------------------- |
| Access gate (global password)  | Backend        | `backend/src/dev_access.py`, `backend/src/routers/access_gate.py`, `backend/src/main.py` |
| User auth (JWT)                | Backend        | `backend/src/routers/auth.py`, `backend/src/security.py`, `backend/src/dependencies.py` |
| Auth token storage             | Frontend       | `frontend/lib/auth.ts` (localStorage, `authFetch`)                |
| Chat session & message history | Backend (DB)   | `backend/src/routers/chat.py`, `backend/src/models.py`                    |
| Query translation / parsing    | Backend        | `backend/src/routers/chat.py`, `backend/src/agents/parsers.py`            |
| Embedding provider / model     | Backend        | `backend/src/embeddings.py` (`EMBEDDING_*` env, used by query + ingest; `EMBEDDING_RUNTIME` GPU/ONNX choice) |
| Embedding generation (query)   | Backend        | `backend/src/agents/base.py` (`_embed`)                               |
| Embedding generation (ingest)  | Backend        | `backend/src/chunking/ingest_pipeline.py`                             |
| RAG retrieval                  | Backend        | `backend/src/agents/base.py` (`_retrieve*` methods)                   |
| Feasibility verdict            | Backend        | `backend/src/agents/orchestrator.py`                                  |
| Document chunking (detaljplan) | Backend        | `backend/src/chunking/chunk_detaljplan.py`                            |
| Law chunking                   | Backend        | `backend/src/chunking/chunk_laws.py`                                  |
| DB push (ingestion)            | Backend        | `backend/src/db/push_db.py`                                           |
| DB models (SQLAlchemy ORM)     | Backend        | `backend/src/models.py`                                               |
| LLM client / model selection   | Backend        | `backend/src/llm.py` (`LLM_PROVIDER`), `backend/src/observability.py`, `backend/src/agents/base.py` (`LLM_MODEL`) |
| Embedding benchmark            | Backend        | `backend/src/benchmark/`                                              |
| Chat UI / session switching    | Frontend       | `frontend/components/Chat.tsx`, `frontend/components/Sidebar.tsx` |
| Pipeline inspector / DB browser UI | Frontend   | `frontend/components/PipelineTrace.tsx`, `frontend/components/DatabaseBrowser.tsx` |
| Auth & access-gate pages       | Frontend       | `frontend/app/(protected)/auth/`, `frontend/app/dev-access/`      |

---

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
| GET    | `/api/db/sources`                  | What each store of the Database view reads: `neon` = the pgvector tables of `DATABASE_URL`, `local` = the agent's corpus (disk store folder, or corpus database endpoint + chunks + kommuner + models); never a password |
| GET    | `/api/db/overview`                 | Chunk counts per table and per source (`store`=neon/local) |
| GET    | `/api/db/chunks`                   | Paginated chunks (`table`=law/document, `source` (local: kommun code), `doc_type`, `doc_id`, `q`, `store`); local without a kommun: store order, `total` null with a text filter |
| GET    | `/api/db/documents`                | Local store: a kommun's documents (`source`, `doc_type`, `q` title filter, `scanned`) by type then title, with chunk counts and a `scanned` flag |
| POST   | `/api/db/search`                   | Retrieval top-k on both pools, no model call (`store`: neon = pgvector, local = localrag) |
| GET    | `/api/docs/locate`                 | Where to open a cited chunk: PDF page + zoom on the passage, or the original URL with `#:~:text=`; `download=false` answers at once with `needs_download` + `source_host` |
| GET    | `/api/docs/pdf/{chunk_id}`         | The chunk's crawled PDF with the passage highlighted |
| GET    | `/api/docs/tool-image`             | The image an agent tool call looked at (`view_map_area` / `view_pdf_page`), re-rendered for the inspector |
| GET    | `/api/benchmark/sets`, `/cases`, `/case`, `/image/{id}` | Benchmark case sets, cases, one case + its past results (`data/agentic/bench-*.json`), plankarta crop |
| POST   | `/api/benchmark/run`               | Run the agent on a case now (chat settings) and grade it; background job (spends credits) |
| GET    | `/api/benchmark/run/{job_id}`      | Progress and result of that job (polled) |
| GET    | `/api/pipeline`                    | Measures of each corpus-building step (crawl coverage, PDF filter errors, OCR benchmark, checks, retrieval eval, plans, tool latency) read from the files the steps write; cached until one changes. Without a corpus: the national snapshot `data/agentic/pipeline-national.json` |
| GET    | `/api/place/profile?lat=&lon=&language=` | Place profile of a pinned point, its notes and permits in the page language (`sv`/`en`, default `en`, ADR-0013): property (live), plans with their documents, zones, plans in progress, inside / outside detaljplan (no model call, ADR-0003) |
| GET    | `/api/place/coverage`              | Every kommun with a snapshot, pilot or plan-layer (code, name, bbox, fetch date), for the map's first view |
| GET    | `/api/place/review/coverage`       | Every registry kommun and snapshot as a GeoJSON outline: covered, polygons, matched, fetch date, why not (review mode) |
| GET    | `/api/place/review/plans?bbox=`    | The plan polygons in a box of at most 2° by 1°, at most 4,000, with their match level and `truncated`; 422 for a wider or malformed box (ADR-0008) |
| GET    | `/api/place/search?q=`             | Address / place search for the map (the pilot kommun's address register, else Nominatim at 1 request/s); 503 when Nominatim is down |
| GET    | `/api/glossary`                    | The shared glossary, {term: English explanation}, for the page's tooltips; no sign-in (still behind the access gate, ADR-0014) |

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

### Run the app on this machine

The app configuration (agent chat, local corpus, GPT-6 Luna) is in `backend/.env` with the secrets, so no
command-line overrides are needed. Don't blank `ACCESS_GATE_PASSWORD` or override `.env` values when starting it
for the user. Needs the GPU and `backend/data/` (local store, `corpus/plans.jsonl`).

```bash
# 0. Nothing already running? (a stale backend on :8000 or frontend on :3000 makes the new one fail)
#    PowerShell: Get-CimInstance Win32_Process | ? { $_.CommandLine -match 'uvicorn main:app|next' } | select ProcessId, CommandLine
# 1. Backend (background shell), from backend/ -- use the venv python, not `uv run` (re-syncs the venv)
cd backend && .venv/Scripts/python.exe -m uvicorn main:app --app-dir src --port 8000 > backend.log 2>&1
#    ready when http://localhost:8000/docs answers; the corpus store and embedding model preload in a
#    background thread (~30-60 s) -- the first chat waits for it
# 2. Frontend (background shell), from frontend/
cd frontend && bun run dev                         # hot reload
#    or: bun run build && bun run start            # lighter; rebuild after any frontend change
# 3. http://localhost:3000 -> access-gate password (from backend/.env, the user types it) -> sign in
```

Check: `curl -s localhost:8000/docs -o /dev/null -w "%{http_code}"` -> 200 (or 401 with the gate on: still up).
Logs: `backend.log` (startup errors: missing key, store not found, CUDA). Stopping a background shell does not
kill the Python/Node children on Windows: stop them with `Stop-Process` before restarting.

### Environment Variables

Backend (`backend/.env`), names as read by the code:

- `DATABASE_URL`
- `AI_GATEWAY_API_KEY` (if set, model calls go through the Vercel AI Gateway) or `OPENAI_API_KEY`
- `LLM_PROVIDER` (openai | gateway | openrouter, with `OPENROUTER_API_KEY` or `OPENROUTER_KEY`), `LLM_MODEL` -- optional chat override (`backend/src/llm.py`)
- `LLM_TIMEOUT_S` (default 180) -- max wait per API response or stream chunk, one retry
- `LLM_REASONING_EFFORT` (answers), `LLM_REWRITE_REASONING_EFFORT` (query rewrite, default low)
- `EMBEDDING_PROVIDER`, `EMBEDDING_MODEL`, `EMBEDDING_DIM`, `EMBEDDING_QUERY_PREFIX`, `EMBEDDING_DOCUMENT_PREFIX` -- embedding model of the pgvector tables (`backend/src/embeddings.py`; default openai text-embedding-3-large at 3072, PCR-0004); `EMBEDDING_RUNTIME` (auto | torch | onnx) for local models
- `RAG_TOP_K` (default 10) -- chunks per pool (laws / documents) given to the answer model
- `RETRIEVAL_BACKEND` (pgvector | local) + `LOCAL_RAG_MODEL` / `LOCAL_RAG_MODE` / `LOCAL_RAG_DENSE_QUERY` / `LOCAL_RAG_RERANKER` -- the chat's retrieval (`localrag/service.py`)
- `LOCAL_RAG_STORE` (disk | neon | memory, PCR-0005), `CORPUS_DATABASE_URL` (the hosted corpus, Neon branch `demo`), `CORPUS_DATA_DIR` (corpus folder relative to `backend/`, default `data`)
- `CHAT_MODE` (rag | agent) + `AGENT_MODEL`, `AGENT_EFFORT` (final answer, medium), `AGENT_EXPLORE_EFFORT` (tool turns, medium), `AGENT_MAX_STEPS` (10)
- `CLAIM_CHECK_MODEL` (default `AGENT_MODEL`), `CLAIM_CHECK_EFFORT` (low), `CLAIM_CHECK_TIMEOUT_S` (60) -- the live claim check of agent answers (`agentic/claim_check.py`)
- `PDF_CACHE_DIR` (default `data/cache/pdf`) -- crawled PDFs downloaded from their URL when the crawl folder lacks them
- `HF_HUB_DISABLE_XET=1` -- Hugging Face downloads can hang on Windows without it
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
- `backend/src/answer_language.py` -- the answer-language rule every answer prompt carries, and `split_language` for the rewrite's `LANG:` line (PCR-0006, ADR-0011)
- `backend/src/glossary.py` -- Swedish domain terms an English text keeps in Swedish, with their English explanation; `explained` adds them in parentheses to the place card's English texts
- `backend/src/routers/glossary.py` -- `GET /api/glossary`
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
- `backend/src/routers/db_browser.py` -- read-only chunk browser + search over both stores (never user tables or embeddings); local kommun and type counts from `localrag.store.summary`; `/api/db/sources` names the real source of each store
- `backend/src/routers/docs.py` -- opens a cited chunk in its original document (PDF page + highlight, or URL text fragment; the PDF comes from `corpus.pdf_files`); chunks come from the agent's corpus tools
- `backend/src/routers/benchmark.py` -- Benchmark view API: case sets, past results parsed from the result file names, in-memory run jobs (lost on restart)
- `backend/src/routers/place.py` -- `/api/place/*`
- `backend/src/routers/pipeline.py` -- Pipeline view API, written for a reader without the project's context: six steps (collect, filter, read/OCR, index, plan registry, search tools), each with what it does, how it is measured, a status, tiles and detail sections, from `data/corpus/check.json`, the manifests, `data/agentic/coverage-*.json` / `replay-*.json`, the PDF filter decisions, `data/eval/ocr-*.json` and the latest `localrag.eval` file; cached until a source file changes; `python -m routers.pipeline --snapshot` refreshes the national snapshot
- `backend/src/benchmark/` -- the early retrieval-only embedding benchmark on the pgvector tables: `export_corpus.py`, `models.toml`, `questions.jsonl`, `generate_questions.py`, `run.py` (hit@k / recall@5 / MRR; vectors cached in `src/benchmark/cache/`, results in `src/benchmark/results/`). Its frozen corpus `src/benchmark/data/corpus.jsonl` (gitignored) also holds the 7 `legacy:` documents `corpus.extract` keeps
- `reports/` -- the benchmark, technical, hosting and place-evaluation reports (generated into `../pyrmit_doc/` by `agentic.report`, `agentic.report_technical`, `place.report`: copy them here after regenerating) and the hand-written architecture report and status deck (HTML, printed to PDF with headless Chrome)
- `backend/src/place/` -- `sources.py` (layers, attribute mapping, pilot kommuner), `fetch.py` (snapshot CLI), `registry.py` (`plan_sources.json`, built from the survey in `docs/research/`), `plan_layers.py`, `plan_links.py`, `review.py` (review mode, ADR-0008), `store.py` (`PlaceStore`, STRtree per layer), `live.py`, `profile.py` (`build_profile`), `permits.py`, `context.py` (the place as text for the agent), `geocode.py`, `check_sources.py` / `check_search.py` / `bench_answers.py` / `bench.py` / `report.py` (the evaluation, see Place Lookup)
- `backend/src/localrag/` -- `analyzer.py` (Swedish BM25 tokens), `gazetteer.py`, `index.py` (VectorStore), `store.py` (disk store), `retriever.py` (`LocalRetriever`), `service.py` (chat integration), `eval.py` + `questions.jsonl`, `rewrite_queries.py`, `models.toml`, `pg_store.py` (the hosted corpus: loader + `PgStore` / `PgRetriever`). Never `pip install` a package that depends on torch without the CUDA index
- `backend/src/agentic/` -- `tools.py` (CorpusTools + tool schemas), `agent.py` (tool loop), `service.py` (chat integration, `CitationNumberer`), `claim_check.py` (live claim check of a chat answer: `verify_answer`), `run.py` (CLI), `bench.py` + `cases*.jsonl`, `cases_from_caselaw.py`, `cases_from_corpus.py`, `cases_from_plans.py`, `rejudge.py`, `grounding.py`, `health.py`, `replay.py`, `coverage.py`, `report.py` / `report_technical.py` (PDF reports)
- `backend/src/corpus/` -- the offline corpus steps (see Offline Corpus): `common.py` (paths: `BACKEND_DIR` = `backend/`, `DATA_ROOT` from `CORPUS_DATA_DIR`), `municipalities.py`, `laws.py`, `crawl.py`, `ocr.py` + `ocr_engines.py` (run in `backend/.venv-ocr`), `extract.py`, `pdf_filter.py`, `chunk.py`, `plans.py`, `check.py`, `snapshot.py`, `caselaw.py` (MÖD rulings for the case benchmark, not searchable), `pdf_files.py` (where the serving code reads crawled PDFs and OCR outputs: crawl folder, else a cache filled from the PDF's URL)
- `backend/src/db/database.py` -- SQLAlchemy engine + `get_db` session factory
- `backend/src/db/push_db.py` -- `PushDB` class: psycopg2 inserts into chunk tables
- `backend/src/db/init.sql` -- DB initialisation (pgvector extension, table creation)
- `backend/src/prompts/land_law_prompt.yaml` -- Prompt that rewrites user questions into Swedish legal search terms

### Frontend (TypeScript / Next.js)

- `frontend/next.config.js` -- `/api/*` rewrite to the backend
- `frontend/lib/auth.ts` -- Token storage (localStorage), `authFetch`, access-gate redirect
- `frontend/lib/i18n.tsx` -- `LanguageProvider` (page language, remembered in localStorage `pyrmit.language`, glossary fetched once), `useLanguage().t`, `fill` for `{name}` placeholders (ADR-0012)
- `frontend/lib/messages.ts` -- the page's texts, `en` and `sv`, one key per text
- `frontend/components/LanguageSwitch.tsx` -- SV / EN switch, on the access gate, the sign-in page and in the sidebar footer
- `frontend/components/Term.tsx` -- a Swedish domain term, with its glossary explanation as tooltip on the English page (ADR-0014)
- `frontend/lib/dev-access.ts`, `frontend/lib/access-gate-server.ts` -- Access-gate cookie helpers
- `frontend/app/(protected)/page.tsx` -- Main page: Sidebar + Chat
- `frontend/app/(protected)/auth/page.tsx` -- Login / signup
- `frontend/app/(protected)/layout.tsx` -- Server-side guard: redirects to `/dev-access` without the access-gate cookie
- `frontend/app/dev-access/` -- Access-gate password page
- `frontend/components/QuestionCard.tsx` -- The agent's question card (`QuestionCard`, `getQuestionCard`), see Agentic RAG
- `frontend/components/Chat.tsx` -- Message list, SSE stream consumption, session history fetch; a new chat is announced
  to the sidebar on the `session_id` event; opening another chat aborts the local stream only, and history
  messages with status "streaming" are re-fetched every 2 s until done; "Process" timeline (`LiveProgress`): one line
  per step / tool call (tool, its query or arguments, result summary, duration), the last 3 ("Show all" expands), shown
  only until the answer text starts (rebuilt from the saved trace for an answer still generating, `stepsFromTrace`); once finished, "Inspect pipeline" and a clickable "Sources" list (retrieved chunks per source, from `pipeline` events) below the answer
- `frontend/components/PipelineTrace.tsx` -- "Inspect pipeline" panel rendering `pipeline` events (live or from saved `trace`): a totals line (time, tokens, cost) then one collapsible step per stage (Understand, Retrieve, Agents, Verdict, Answer) with a one-line summary, and the stage's API calls nested inside (assigned by call kind/name in `stepOf`). An expanded `view_map_area` / `view_pdf_page` tool call shows the image the agent looked at: traces store no images (tool records carry `tool` + `image`), `ToolImage` re-renders them from the call's arguments via `/api/docs/tool-image` (older traces: tool taken from the call name)
- `frontend/components/DatabaseBrowser.tsx` -- Database view with a store toggle, the buttons named by `/api/db/sources`
  ("pgvector tables" = law_chunks / document_chunks of DATABASE_URL; "Agent corpus · disk / · Neon / · memory" = what
  the agent searches; the source detail in the header and as tooltip, generic labels when the route fails): stats,
  chunk browsing, search playground (store keys `neon` / `local` in the API). Local kommun documents: kommun select (documents and scanned PDFs per kommun), document-type chips,
  "Only scanned PDFs" (OCR) checkbox, then the kommun's documents by type (`DocumentList`, click one for its chunks;
  scans carry an OCR badge); without a kommun, chunks in store order. Every local
  chunk (browse and search) links to its original (`SourceLinks`): crawled PDF opened at the passage in the
  `SourceViewer` panel (`autoOpen`, n = 0: no citation number) plus the PDF's URL on the kommun site, web page /
  statute in a new tab at the passage (`openPageAtChunk`); a document's "Open the PDF" lists its chunks beside it.
  `/api/db/chunks` rows carry `url`, local `/api/db/search` matches `chunk_id` / `doc_id` / `kind` / `url`
  (`localrag.service._row`). The 7 "legacy:" PoC documents have no original
- `frontend/lib/corpus.ts` -- document type names / hints and number formatting shared by the Database and Pipeline views
- `frontend/components/ChunkCard.tsx` -- Expandable chunk card (source, chunk index, distance badge, content)
- `frontend/components/SourceViewer.tsx` -- Side panel for a clicked citation [n]: cited chunks + the original document at the passage.
  No open button for the 7 `legacy:` documents of the early prototype (963 Vallentuna chunks, in every corpus, added
  by hand without file or URL, no crawled twin: kept for their content), a note instead; only the clicked button
  waits (the latest click wins)
- `frontend/components/CitedMarkdown.tsx` -- Answer markdown with [n] citation chips (`linkCitations`), shared by Chat and Benchmark
- `frontend/components/place/` -- `PlacePanel` (map panel beside the chat, opened by the pin button in the message
  bar: full-height map, the card as a glass sheet with a grabber, Apple Maps style; system font; controls styled in
  `globals.css` under `.place-map`; the review mode's switch, fetches and legend, ADR-0009), `PlaceMap` (MapLibre 6 +
  OpenFreeMap Positron, outlines per kind, the review layers, `bottomInset` keeps the view centred above the sheet,
  attribution required by ODbL / OpenMapTiles / OpenFreeMap kept small; draws props and fetches nothing),
  `PlaceCard` (iOS-style grouped sections with icon tiles; "None found" vs "could not be reached"), `PlaceSearch`
  (floating search, Enter only; a match becomes a grey proposed pin with "Pin here"), `PlaceChip` (the chat's pinned
  place above the input), `glass.ts` (the shared glass style); `frontend/lib/place.ts` -- types
  and `fetchPlaceProfile` / `fetchPlaceCoverage`
- `frontend/components/BenchmarkBrowser.tsx` -- Benchmark view (sidebar, above Database): browse the case sets, a case's
  reference (verdicts, key points, evidence, source, map crop) and past results, and "Test with the agent" (run + judge)
- `frontend/components/PipelineBrowser.tsx` -- Pipeline view (sidebar, below Benchmark), progressive: an introduction,
  a strip of the six steps (key number + status, click to open), one card per step (status, tiles; opened: what it does,
  how it is measured, collapsible detail sections), a glossary
- `frontend/components/Sidebar.tsx` -- Session list, new chat, Benchmark / Pipeline / Database / Settings buttons, user info
- `frontend/components/Settings.tsx` -- Profile / password settings
- `frontend/tests/` -- Vitest suite copied from dev: `unit/` mirrors `components/` and `lib/` (reference tests
  `lib/auth.test.ts`, `components/Sidebar.test.tsx`, the rest `it.todo`), `mocks/handlers.ts` is the shared MSW fake
  backend (override with `server.use(...)`), and `setup.ts` fails any test whose request has no handler.
  `tests/acceptance.test.ts` exists only on an issue's branch. The Dockerfile installs with Bun from `bun.lock`
  (PCR-0009; there is no `package-lock.json`)

### Agents (Multi-Agent RAG)

- `backend/src/agents/base.py` -- `BaseRAGAgent`: shared embedding, pgvector retrieval, LLM call
- `backend/src/agents/law_agent.py` -- LawAgent on law_chunks
- `backend/src/agents/document_agent.py` -- DocumentAgent on document_chunks
- `backend/src/agents/orchestrator.py` -- Combines both into the verdict
- `backend/src/agents/parsers.py` -- `parse_query`, `format_response`
- `backend/src/agents/AGENTIC_FLOW.md` -- Detailed agent flow
- `backend/src/routers/agents.py` -- POST /api/analyze endpoint

### Tests

- `backend/tests/unit/agentic/` -- agent tools on fake corpora, citations numbered for every delta size, images sent once, questions back to the user, task scoring, tool health, coverage causes; `test_replay.py` replays stored tool calls on the real disk store and skips without it
- `backend/tests/unit/localrag/` -- VectorStore growth and resume, the hosted corpus's SQL and file sync
- `backend/tests/unit/place/` -- the place module on a fake Uppsala snapshot (`snapshot.py`, `plan_layer.py`, `hosted.py`), no real services
- `backend/tests/unit/conftest.py` also fakes the kommun list of the gazetteer, so no test reads `data/corpus/municipalities.json`
- `backend/tests/unit/corpus/` -- crawler rules (robots.txt wildcards, `url_key`, off-topic PDFs, sitemaps), PDF filter (no drop without the LLM or a review), OCR benchmark scoring, PDF download into the cache, the data folder
- `backend/tests/unit/` -- pytest unit tests, one file per module in `backend/src/`, same folder layout. `backend/tests/test_acceptance.py` is the one temporary exception, it exists only on an issue's branch. No real database or model calls (PCR-0011). Most files hold only a docstring so far. Known failures are marked `xfail` with a linked issue.
- `frontend/tests/unit/` -- Vitest + jsdom + React Testing Library, one `*.test.ts(x)` file per module in `components/` and `lib/` (PCR-0007). `frontend/tests/acceptance.test.ts` is the one temporary exception, it exists only on an issue's branch. `lib/auth.test.ts` and `components/Sidebar.test.tsx` are the reference examples; the rest are `it.todo` placeholders.
- `frontend/tests/mocks/handlers.ts` -- MSW fake backend shared by all frontend tests; override per test with `server.use(...)` (PCR-0008). Unhandled requests fail the test.
- `frontend/tests/setup.ts`, `frontend/vitest.config.mts` -- test setup and Vitest config.
- `backend/pyproject.toml` `[tool.ruff.lint.per-file-ignores]` -- ruff baseline of pre-existing problems. Shrink only (PCR-0012).

### CI

- `.github/workflows/frontend.yml` -- `frontend / lint`, `frontend / test`, `frontend / docker` (builds the image, does not publish)
- `.github/workflows/backend.yml` -- `backend / lint`, `backend / test`, `backend / docker` (builds the image and imports `main` in it, no database needed)
- Both run on every PR into and push to `dev` and `main`, with no path filter. All six are required checks via the "CI green" ruleset (PCR-0010).

### Team Skills

- `.claude/settings.json` -- enables the `max` plugin from the `release` branch of the `Maxastrand04/Custom-skills` marketplace. The skills are not in this repo. Change them in Custom-skills, merge to `release`, then run `/plugin marketplace update custom-skills`.
- `docs/skills-tutorial.md` -- link to the skills tutorial on GitHub Pages, plus setup notes

---

## Document Ingestion (Detaljplan PDF)

```
1. POST /api/chunks/ingest-detaljplan { input_path, output_path?, document_name, document_id, ... }  (auth required)
   or POST /api/chunks/ingest-data-folder { data_dir, markdown_output_dir, ... } for a whole folder
2. backend/chunking/ingest_pipeline.py:
   a. ensure_markdown_source: if PDF -> Mistral OCR -> .md saved to data/ocr_markdown/
   b. DetaljplanChunker splits markdown into semantic chunks
   c. embed_texts_batch: OpenAI text-embedding-3-large (batched, 3072-dim)
   d. PushDB.push_chunks -> document_chunks (psycopg2, DATABASE_URL)
3. Returns { inserted, deleted } counts
```

## Law Ingestion (Static TXT files)

```
1. Run backend/chunking/ingest_laws.py (CLI only, no API endpoint)
2. LawChunker splits law TXT by chapter (kap.) / section (§)
3. Embed with OpenAI text-embedding-3-large
4. PushDB.push_law_chunks -> law_chunks
```

---

## Chat Request

The frontend uses `POST /api/chat/stream` (SSE); `POST /api/chat` runs the same logic without streaming.

1. Access-gate middleware, then `get_current_user` checks the bearer JWT and its login session.
2. The chat session is created or looked up; the user message and an empty assistant message (status `streaming`) are saved. The answer is generated in a background thread independent of the HTTP connection: the response only relays its events, so closing the tab or opening another chat neither stops nor loses the answer.
3. A model call rewrites the latest message as a standalone English query (location, units and project type from the last 5 messages) and decides the answer language on a first `LANG: sv|en` line (`answer_language.split_language`, ADR-0011).
4. `parse_query` extracts location, units and project type by regex.
5. Location or units missing: general RAG, the query embedded once, the top `RAG_TOP_K` law and document chunks, an answer in markdown in the question's language, given the question as the user wrote it, quoting Swedish verbatim (PCR-0006), and a Sources list. Both present: `Orchestrator.analyze` runs LawAgent and DocumentAgent in parallel and applies fixed rules for the verdict; its texts and `format_response` follow the decided language.
6. SSE events: `session_id`, `thinking`, `tool_call` / `tool_result`, `pipeline`, `response.output_text.delta`, `answer_replaced` (agent mode: the answer rewritten by the claim check, whole), `response.completed`, `done` (or `error`). `relay()` sends a `: keep-alive` comment after 10 s idle (`SSE_HEARTBEAT_S`), since the Next.js dev proxy drops a stream idle for 30 s; the frontend aborts after 45 s without bytes (`STREAM_STALL_MS`) and reloads the session.
7. The worker updates the assistant message from the events: partial content every 2 s, then the final content, its `trace` (every pipeline event) and status `done` (or `error`).

`pipeline` events (`{type: "pipeline", stage, data}`) feed the inspector: `translation`, `intent`, `retrieval` (matched chunks with source, distance, content), `agent_output`, `verdict`, and `call` (one per model, embedding or search call: model, prompts, output, token usage incl. reasoning tokens and the OpenRouter cost, duration), captured by a `CallRecorder` passed to the agents. They are saved in `chat_messages.trace` (~20-60 KB per answer), so a reopened conversation keeps its inspector and sources.

Gotchas: a location the regex misses ("for Vallentuna": only in / at / i / på / vid count) silently takes the general RAG path; the units regex misses "apartment(s)", which the rewrite makes of "lägenheter".

---

## Auth Flow

```
1. POST /api/auth/signup -> creates User + Account (credentials, hashed password) and a login session row -> returns JWT
2. POST /api/auth/signin (JSON) or /api/auth/token (OAuth2 form) -> verifies password, adds a login session row -> returns JWT
3. Frontend stores the JWT in localStorage and sends it as Authorization: Bearer
4. get_current_session decodes the JWT (HS256, JWT_SECRET_KEY, sub = "user:<id>", sid = the session row) and checks
   that the row exists and has not expired; get_current_user returns its user
5. POST /api/auth/signout -> deletes the current login's session row, so its token stops working (ADR-0001);
   the frontend clears the token, and only on a 401 if no newer login replaced it
```

`ACCESS_TOKEN_EXPIRE_MINUTES` (default 10080, 7 days) sets both the JWT expiry and the session row's `expires_at`.

## Access Gate

When `ACCESS_GATE_PASSWORD` (or `DEV_ACCESS_PASSWORD`) is set, every backend request except `/api/access-gate/unlock` and OPTIONS returns 401 `"Access password required"` unless it carries the `dev_access_granted` cookie or an `x-access-gate-password` header. The frontend's `authFetch` redirects to `/dev-access` on that response.

---

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

## Local Retrieval and the Hosted Corpus

- Hosted demo for outside testers (2026-10-31, README "Try it without the data"): `LOCAL_RAG_STORE=neon` serves the
  corpus from Postgres (`localrag.pg_store.PgRetriever` / `PgStore`), no local data. Built from `data/demo`
  (`python -m corpus.snapshot --kommuner 0380 0115 0180`) = laws + Uppsala (plan layers, map pin) + Vallentuna
  (benchmark kommun, no plan layer) + Stockholm (thin: its plans are on vaxer.stockholm), 115,127 chunks, 2,635 plans;
  Uppsala is 81 % of it (6,658 documents, 63 % of its chunks in the 4,067 documents of its 2,177 plans:
  `place.plan_documents` fetched every plan in force). Embedded with **bge-m3** (`st-bge-m3`, ~60 chunks/s on the GPU,
  32 min) because arctic is not on OpenRouter and OpenRouter's `baai/bge-m3` gives the same vectors (cosine 0.99999 on
  the 18,440 chunks embedded both ways in October): testers set `LOCAL_RAG_MODEL=or-bge-m3` (queries through
  OpenRouter; `pg_store.same_vectors` checks the model against `corpus_meta`), no torch / sentence-transformers needed
  (checked from a clean venv with the README's install line). Eval on its 34 questions (`data/demo/eval-*.json`, kept
  out of `data/eval`, where `report_technical` would mix it into the October model table): dense-sv R@5 0.88 vs arctic
  0.87, R@1 0.63 vs 0.71; hybrid-sv-stem R@5 0.72 vs 0.77, R@10 0.88 vs 0.85. `python -m localrag.pg_store` loads the
  Neon branch `demo` (schema-only: no production users / chats; its URL is `CORPUS_DATABASE_URL` in `backend/.env`,
  same role and password as production): 665 MB of the free plan's 1 GB (chunks 596, OCR 33, stem frequencies 15, small files 7,
  places 6), ~17 min for the chunks from home (`--skip-chunks` redoes the rest). Serving: views `chunks` / `places`
  carry the disk store's columns and `PgStore.query` turns `?` into `%s` and LIKE into ILIKE, so `_DiskCorpus` and the
  Database view run their SQLite SQL unchanged (made portable: MIN() per document instead of a bare GROUP BY, LIKE
  instead of GLOB, `store.regexp()` = REGEXP or `~*` with `\b` -> `\y`); `DiskRetriever.search` takes its rankings from
  `_rankings`, which `PgRetriever` runs in SQL: dense `ORDER BY embedding <#> q` (exact, same top 8 as the disk store,
  0.05-0.09 s on laws / Vallentuna / Stockholm, 0.5 s on Uppsala's 93k chunks), BM25 approached by sum(IDF x
  ts_rank normalization 1) on the chunks holding a stem found in under 10 % of the chunks (`corpus_terms`; vs FTS5 on
  the 34 questions: top-10 overlap 0.80, 0.17 s mean / 2 s max; plain ts_rank 0.57). The agent's searches then share
  14-16 of 16 results with the disk store; read / law_section / plans / plan_rules / view_map_area give identical
  output. Small files the app reads from disk (gazetteer, plan registry, Uppsala's place snapshot) sit in
  `corpus_files` and `sync_files` writes the missing ones at startup (`main._open_corpus_database`, before serving: the
  map caches its manifests on the first request), never over a file it did not write (`data/neon_sync.json`); OCR
  outputs come per document through `pdf_files.remote_ocr`. PgStore reopens a connection Neon closed (compute
  suspended after 5 idle minutes). The free plan's 100 CU-h a month are shared with production. PDFs come from
  `corpus.pdf_files` (crawl folder, else downloaded from their URL into the cache: 8/8 plankartor and 4/4 cited
  passages worked without the crawl folder, 0.2-34 s the first time; the source viewer first asks `locate` with
  `download=false` and shows "Downloading the PDF from <host>…" when `needs_download`). The Pipeline view shows the
  national corpus's page from `data/agentic/pipeline-national.json` (versioned, ~100 KB) when there is no
  `check.json`, with a banner saying so; refresh it on the corpus machine after a rebuild with
  `python -m routers.pipeline --snapshot` (~2.5 min). The agent's prompt says which kommuner the corpus holds
  (`agent.kommun_scope`: the "all 290 kommuner" line of TOOLS_GUIDE is replaced when the corpus has documents of
  fewer than 250, from `CorpusTools.corpus_kommuner` = the store summary; before, the demo agent answered "290"), and
  `find_kommun` says "no documents in this corpus" for a kommun outside it. The statutes are the same in every
  corpus (national, data/small, demo: 15 laws, 3,651 sections; `corpus.snapshot` always keeps `kind == "law"`). Gotcha: `corpus.plans` gives two plan pages without PDFs and with the same name the same `plan_id` (260
  ids nationally; `plan_rules` gets the first). Gotcha: `pyproject.toml` keeps SQLAlchemy < 2.1 (uv.lock 2.0.46): 2.1 makes `postgresql://` use psycopg 3, which is
  not installed (a clean install failed on it). Testers install with `uv sync --extra corpus` (no torch). End to end
  (2026-11-01, fresh install, `stream_agent`, Kårsta komplementbostadshus question): 24 tool calls, none failed, 59 s,
  first answer text 50 s, $0.0085, 7 sources cited. Testers get a role created in SQL on the `demo` branch (a role
  made in the console joins `neon_superuser`: read / write on every table, and `neondb_owner` carries the production
  password): DML on users / accounts / sessions / chat_sessions / chat_messages + `chat_messages_id_seq`, SELECT on
  the corpus tables and views (checked with a NOLOGIN role in a rolled-back transaction: corpus writes, DROP and
  CREATE refused). `pg_store` drops and recreates the corpus tables: re-run the corpus GRANT after a reload. The
  project's developers get `backend/.env.demo` (the maintainer's `.env` + `LOCAL_RAG_STORE=neon`,
  `LOCAL_RAG_MODEL=or-bge-m3`, `CORPUS_DATABASE_URL`; DATABASE_URL stays the production branch; `.env.*` is
  gitignored, the repo is public) and save it as `backend/.env`. On this machine `.env` holds `CORPUS_DATABASE_URL`
  (unused in disk mode); to try the developers' setup, start the backend with `LOCAL_RAG_STORE=neon
  LOCAL_RAG_MODEL=or-bge-m3 CORPUS_DATA_DIR=data/neon-test` set in the shell (python-dotenv never overrides them).
- `LocalRetriever` searches two pools like the chat (laws / kommun documents). The kommun pool is filtered to the
  kommuner named in the question (`gazetteer.detect_kommuner`, fallback `CorpusPlaces` for places missing from
  Wikidata, e.g. "Veda"). Modes (`LOCAL_RAG_MODE`): dense (default), bm25 (Swedish stems + compound 5-grams),
  hybrid (RRF); optional cross-encoder reranker. Defaults (`localrag/service.py`) follow the eval: arctic-l-v2 on
  the Swedish query, no BM25 fusion, no reranker (neither beat dense-sv). On the national corpus (2026-10-24, same 45
  questions, `--allow-missing` counts passages a corpus lacks as misses; `hybrid-sv-stem` = the agent's search) recall@5
  drops 0.94 -> 0.88 (dense-sv) and 0.89 -> 0.83 (hybrid-sv-stem): the 4 kommuner of the questions have 3x more
  passages, no expected passage is missing, municipal recall@5 1.00 -> 0.92 (outranked, ranks 7-12), statutes
  unchanged (0.80). Technical report section 6 (`corpus_table`), Pipeline view. The app serves from the **disk store**
  (`localrag/store.py`, `LOCAL_RAG_STORE=disk` default): chunks + metadata in SQLite, BM25 = FTS5 over pre-stemmed
  text with filter tokens (`zzpoollaw`, `zzk<code>`) so pool/kommun filters are posting-list intersections, vectors
  float16 in a memmap copied block-wise to the GPU (dense search = GPU matmul, ~0.1 s). Rebuild it after
  `localrag.index` (and restart). RAM ~1.7 GB private, mostly torch + the embedding model. `LOCAL_RAG_STORE=memory`
  loads chunks.jsonl in RAM (LocalRetriever; needed for the compound analyzer / reranker; used by the evals). Kommun
  detection is the union of Wikidata names/localities and corpus places ("Veda" is a Wikidata locality in Härnösand
  but the corpus places it in Vallentuna). The backend preloads the store/tools at startup (`main.py`).
- In the chat, the local backend asks the rewrite call for an extra `SV:` line (Swedish search query, no extra
  LLM call) and emits a `local_query` pipeline event (Swedish query + kommun filter). Embedding or BM25 on the
  English query is much worse (Swedish corpus). The feasibility path (orchestrator) still uses pgvector.

---

## Agentic RAG (`CHAT_MODE=agent`)

**Question card (#91).** When the conclusion turns on facts only the user can give (place, use, a size or height
against a threshold, what is to be built, which of two places), the agent asks instead of guessing: `ask_user` takes
1-3 `questions` (each `question` + 0-4 `options`, none for an open question) and `offer_pin`, and ends the run with
`AgentRun.questions`. The rule is the "Asking instead of guessing" part of `MODES_GUIDE`; `ASK_LANGUAGE_REMINDER` follows
each turn's tool results so the card stays in the user's language. The chat saves the card as the `choices` pipeline
event `{questions, offer_pin}` (an open question too) and skips the claim check; `frontend/components/QuestionCard.tsx`
shows it with an "Other" field per question, one reply message for the whole card, locked once answered (old saved
`{options}` cards still read). A message typed below an open card is sent with `answer_to_question`, so the agent
answers instead of asking again: such a run (`allow_ask=False`) gets `ANSWERED_GUIDE` in place of the asking rule `ASK_GUIDE`, since the rule alone
made it ask again in plain text.
Missing-info eval: `python -m agentic.bench --cases-file cases_missing_info.jsonl --explore-effort medium --repeats 2
--baseline <dev results>` (50 should-ask and 50 should-answer cases, 25 Swedish + 25 English each, asked as the chat
asks with nothing pinned): `grade_asked` judges whether a card asked for every `missing` fact, `follow_up` answers the
scripted `reply` and grades it, and `missing_info_summary` passes at 95% on each half with the should-answer key points
not below the baseline. Results of the merge run: `data/agentic/bench-20261112-153506-agent-medium-explore-medium-cases_missing_info-x-run6.json`
and the dev baseline `data/agentic/missing-info-baseline-dev-medium-20261112.json` (99% / 99%, key points 0.68 vs 0.71;
tuned on these same 100 cases, so a fresh set would show how well the rule generalises).

`agentic/agent.py` runs a Responses-API tool loop (default `openai/gpt-6-luna` via OpenRouter) with tools from
`agentic/tools.py` (`CorpusTools` over `_DiskCorpus` (SQLite) or `_MemoryCorpus`): `find_kommun`, `search` (hybrid
dense + BM25 "stem"), `grep`, `list_documents`, `read`, `law_section` ("PBL", "9 kap. 4 §"), `plans` / `plan_rules`
(plan registry from `data/corpus/plans.jsonl`, loaded on first use), `read_plan` (the documents the pinned place lists, in
reading order, whole or by heading, from the corpus only: ADR-0010; `PIN_GUIDE` says when), `view_map_area` (zoomed crop of a text-layer
plankarta around a printed label such as a property number "5:125", plus the codes printed in that area with their
meaning from the registry; search/word coordinates are unrotated, rendering uses `rect * page.rotation_matrix`),
`view_pdf_page` (whole page image sent to the model), plus `answer_ready(mode)`: the agent classifies the question
(`MODES`: verdict / explain / propose / develop, described in `MODES_GUIDE`) and the final answer uses that mode's format
from `ANSWER_FORMAT` (a **Verdict:** line only for feasibility questions; propose = options named in the kommun's plans;
develop = obstacles, ways to make it work, questions for the user); `AgentRun.mode` records it. Latency is almost all model turns, so: exploration turns run at
`AGENT_EXPLORE_EFFORT` (default medium, chosen on the benchmark; low = fast mode), the tool calls of one turn run in parallel, the model calls `answer_ready` when
it has enough, and only the final answer runs at `AGENT_EFFORT` (default medium), **streamed** (`answer_delta`
events); `AGENT_MAX_STEPS` (default 10) forces the answer. `CorpusTools.warm_up()` loads the query embedding model
up front (else the first search takes ~30 s). Tool outputs tag chunks as `[c:<chunk_id>]`; the answer must cite them.
In the chat, `agentic/service.py` runs it in a thread: tool calls stream as `tool_call`/`tool_result` SSE events,
each model turn and tool call is recorded for the inspector ("Explore (agent)" step), and the answer streams as
`response.output_text.delta` with citations numbered on the fly (`CitationNumberer`: one number per source label,
partial `c:` ids and open `[...]` groups held back until complete, repeats merged); the numbered source list
("- [n] label") is appended at the end and a `citations` pipeline event maps each n to its label and cited chunks.
Then the claim check (`agentic/claim_check.py`, `verify_answer`, issue #82) runs, except on a question back to the user:
a judge lists the answer's factual claims and judges each against the full text of its cited chunks (supported /
unsupported / uncited, with the supporting sentences); unsupported and uncited claims go back once to a rewrite that
may re-cite any chunk the agent read or remove the claim, and the rewritten answer is judged again. The stream says
"Checking the claims" meanwhile (the message stays `streaming`), sends a rewritten answer as `answer_replaced`, and
saves the verdicts as the `claim_check` pipeline event (`{status: checked | failed, claims}`, ADR-0004). The chat marks
the claims still not supported, and says "The claims in this answer could not be checked." when the check failed
(model error, `CLAIM_CHECK_TIMEOUT_S`, a cited chunk that cannot be read). Answers saved before the check show neither.
The source panel a citation chip opens underlines, in each cited chunk, the supporting sentences of every claim that
cites it (`SourceViewer`'s `supporting` prop, ADR-0015, issue #84); an answer without a check result shows no underline.
The answer format asks for the law reference in the sentence and `[c:id]` right after the claim, never nested.
`read` also takes the id as printed (`c:<id>`, `[c:<id>]`, `doc pdf:...` / `doc:pdf:...`), a doc_id passed as chunk_id, without its `pdf:` / `page:`
prefix or reduced to its hash (`doc_ids_ending`) (before 2026-10-22, 1,845 benchmark reads failed on the `c:` prefix, 88 % never retried); `law_section` takes
abbreviations (MPF, MBF, LRL...), names without diacritics and '9:4' / '4a §' / '18 c § punkt 1', and points to the
SFS 2025:974 renumbering when a PBL 9 kap. number is missing; `grep` needs a kommun or scope='law' (a regex over every
kommun took 12-28 s) and filters on the index; an image (`view_map_area` / `view_pdf_page`) goes with the next model
call only, then is replaced by a note (`send_images_once` in `agent.py`; the agent is told to write down what it reads); `find_kommun` lists
the kommun named outright first ("Kårsta, Vallentuna": Örebro also has a Kårsta). Document filters (2026-10-24; dev
set on the 2026-10-22 corpus, `bench --label filters` vs `toolfix`, benchmark report 2.12: used in every answer, key
points +0.026 ± 0.015 per case (MiMo) / +0.065 ± 0.028 (Luna, 41 answers re-judged before the OpenRouter credits ran
out), 2.1 fewer tool calls, first token +3 s, 5 % of greps empty vs 1 %; kept; not measured on the national corpus):
`search`, `grep` and `list_documents` take `doc_types` (`tools.DOC_TYPES`; `parse_doc_types` accepts
a string, commas, "översiktsplan") and `title_contains`, applied before ranking (`DiskStore.pool_rowids` in SQL with a
kommun; without one a cached row mask, `local_mask`, ~2 s the first time; FTS joined on chunks; `LocalRetriever` masks);
a document filter leaves the statutes out of grep; `grep(output='documents')` groups the matches per document (most
first); `list_documents` pages by `offset` (max 100). `view_map_area` on a page without text layer looks the label up
in the OCR words (`_ocr_words`, `_label_key`: "5.125" / "5,125" read for "5:125", several words in a row) and lists the
codes the OCR read in the area; not OCRed yet -> no_data. Disk-store queries on kommun
chunks filter `kind IN LOCAL_KINDS` (page, pdf) so SQLite uses the (kind, kommun_code) index (`kind != 'law'` scanned
the table, ~0.7 s per query). Robustness: ids of 8-15 hex characters (the model sometimes truncates) resolve by unique prefix
(`CorpusTools.get_chunk` -> `ids_with_prefix`), unknown ids are dropped (no "?"), and groups are split on ";" (commas
only between ids, so "PBL 9 kap. 3 §, 4 §" stays whole). The frontend turns "[n]" / "[n; m]" into clickable chips
(`linkCitations` in `Chat.tsx`; mixed or nested groups such as "[1; MB 7 kap. 15 § [2]]" become chips followed by the
reference in italics) that open
`components/SourceViewer.tsx`: the cited chunks, and the original document opened at the passage via
`routers/docs.py` (crawled PDF fetched as a blob with the auth header and shown in an iframe at
`#page=N&zoom=scale,left,top&navpanes=0`, passage highlighted; web pages and statutes opened in a new tab with a
`#:~:text=` fragment that Chrome scrolls to and highlights; scanned PDFs: page from the OCR text, no highlight).
The page is found by searching the chunk's 6-word phrases in the PDF (chunks store no page numbers).
The agent branch runs before the rewrite step and returns early. With a map pin (`request.place`, #37) the worker builds
the place profile (`get_place_profile` dependency), puts `place.context.place_context` before the question ("do not ask
where", "ask which place" when another is named) and emits a `place` pipeline event `{pin, profile}` (profile without
geometries); without a pin the question gets `NO_PIN_HINT`. The chat session's place is the latest `place` event of its
answers' traces (ADR-0004: no new columns on the shared tables); `Chat.tsx` restores the `PlaceChip` from it
(`placeFromHistory`) and keeps the pin and its label in separate state, so a label update never refetches the profile.
Gotcha: **PBL 9 kap. was renumbered by SFS 2025:974** (bygglov in/outside a detaljplan now 9 kap. 56/57 §, liten
avvikelse 60-61 §, förhandsbesked 74 §; some sections have a second version in force 2027-01-01). Rulings and the
model's memory use the old numbers (9:30, 9:31 b, 9:17), so the prompt tells the agent to find provisions by wording.
The reform also changed the exemptions (corpus text, checked 2026-10-25): komplementbyggnad / komplementbostadshus up to
30 m² inside a detaljplan (9 kap. 4 §) and 50 m² outside (5 §) need no bygglov and no anmälan any more (PBF 6 kap. 1 §
lists none), tillbyggnad up to 30 m² below the ridge needs no bygglov (10 §), fasadändring needs bygglov in a plan only
on buildings other than one- / two-dwelling houses facing a public place (15 § 3), and 34-37 § bring the bygglov back
(4.5 m from the boundary without the neighbours' consent, totalförsvar areas, protected values). References written
from memory get this wrong: check them against the law chunks.
Benchmark: `python -m agentic.bench` (14 feasibility cases in `agentic/cases.jsonl`: evidence recall, LLM-judge
key points, cost, latency, first-token time; RAG vs agent; `--cases-file cases_caselaw.jsonl --store disk` for cases
from any kommun on the full disk store) and `python -m agentic.grounding <results.json>` (claims supported by the
cited sources). Results in `data/agentic/`; report in `../pyrmit_doc/pyrmit_agentic_rag_report.md`.
Real-decision cases: `python -m corpus.caselaw` downloads MÖD precedents 2011- from lagen.nu (robots.txt allows the
case pages; 1 req/s, resumable) to `data/corpus/raw/caselaw/mod.jsonl` (headnote, keywords, statutes, full text,
`relevant` by topic); `python -m agentic.cases_from_caselaw` (one LLM call per ruling, spends credits) turns each into
a case (facts as question without the outcome, verdicts, key points) whose evidence labels are the longest run (>= 5
words) of the quoted statute wording found in the current law chunks (renumbering- and amendment-proof); remittals
that state the decisive test are kept as "unclear" cases, and cases with no current statute (old PBL) are kept with
no evidence label (scored on verdict + key points). Raw drafts are cached and appended one by one in
`data/corpus/raw/caselaw/case_drafts.jsonl` (rebuilding costs nothing; `--regenerate` pays again)
-> `agentic/cases_caselaw.jsonl`. The bench judge gets the text of the chunks the answer cites (a sourced fact is
not "unsupported" because the reference omits it); `--repeats N` reports per-repeat means, `--workers N` runs cases
in parallel; results are written after every case and `--resume <file>` completes an interrupted run.
Plankarta cases (`agentic/cases_from_plans.py`): the other benchmarks never need the map (2 map views in 576
answers), so this set asks about a specific property in a plan whose height / building-area rules differ by zone.
`candidates` (free) picks text-layer plankartor with >= 2 such coded rules and a property label whose surroundings
carry one (scales, legend / title-block areas and unconfirmed tract names filtered) and saves the crops in
`data/agentic/plan_cases/`; `label` (paid, vision, high effort, cached in `labels.jsonl`) reads the crop + code
meanings into a reference (applicable codes, values, a project whose feasibility depends on them) and keeps only
high-confidence ones -> `agentic/cases_plans.jsonl` (evidence = the plankarta `doc_id`; `localrag.eval.matches`
accepts `doc_id`). Check a sample of crops / labels by hand.
Tasks beyond the verdict (the product vision: also explain rules, propose projects, develop ideas): a case's `task`
(default "verdict") selects the judge prompt (`TASK_JUDGE_INSTRUCTIONS`) and the scores (`grade_answer`, shared by the
bench and the Benchmark view): `verdicts` are optional (`verdict_ok` null without them); propose cases carry `anchors`
(places the plans designate, scored by whole-word string match, `min_anchors` needed) and the judge lists the answer's
`proposals` (sourced or not); develop key points are prefixed "Obstacle:" / "Lever:" / "Ask:" (scored per kind); agent rows
get `mode` / `mode_ok`. Every row has `lang`, `language_ok` (answer in the case's language) and `quotes_ok` (Swedish quotes verbatim in the cited chunks). `agentic/cases_bilingual.jsonl` = the 24 cases of `cases.jsonl` + `cases_tasks.jsonl` in Swedish and English (`pair`, `lang`) plus 10 `hard` cases (mixed language, "ja" with `history`, other languages, a lone term), reported per language: `bench --cases-file cases_bilingual.jsonl` (bar: `language_ok` and `quotes_ok` >= 0.98 on sv and en, points within 0.05 and verdict_ok within 5 points between them). `agentic/cases_tasks.jsonl` = 10 hand-written seeds (Vallentuna, Norrtälje, Uppsala, Gotland,
verbatim evidence); `python -m agentic.cases_from_corpus` drafts more from corpus documents (guidance pages / ÖP growth
passages / rural + VA passages + statutes) with **MiMo v2.6 Flash** (another model family than the agent), keeps only
points whose quote is found verbatim (`longest_phrase`), drafts cached in `data/agentic/task_drafts.jsonl` ->
`agentic/cases_generated.jsonl`. `--judge-model xiaomi/mimo-v2.6-flash` grades with another family (rows store
`judge_model`); `python -m agentic.rejudge <results.json> --sample 50` re-grades stored answers and prints the
inter-judge agreement; `--leakage` (no LLM) prints each evidence group's rank in a plain search on the question (rank 1-3
= the question gives the answer away). Run embedding steps on the CPU with `CUDA_VISIBLE_DEVICES= EMBEDDING_RUNTIME=onnx`
(ONNX int8 ~0.9 GB instead of torch on the CPU; the disk store falls back to numpy). Tests: `tests/test_bench_tasks.py`.
`cases_from_corpus.REVIEW` = manual corrections of generated cases by id (drop / relabel points, replace propose
anchors), applied on every rebuild: re-review after `--regenerate` (ids change when sources change). On the last allowed
turn the agent is only offered `answer_ready` (`tool_choice=required`), so a run that hits `AGENT_MAX_STEPS` still picks
its mode (before: 5/12 propose runs ended without a mode). Reports: `report.MODES_RUN` (2026-10-19) splits the effort
matrix (older runs, verdict-only prompt) from the mode-prompt runs; `mode_rows` / `task_table` / `regression_table` /
`judge_agreement` feed benchmark-report sections 2.7-2.8 and technical-report section 7.9 (English bodies only;
`PROPOSE_FIX_RUN` separates the propose re-run). `llm.get_openai_client` sets `LLM_TIMEOUT_S` (default 180 s per
response / stream chunk) and 1 retry: the SDK default (600 s, 2 retries) could hold a worker 30 min.

Status of the benchmark-scope work (2026-10-21; numbers in the reports, `data/agentic/bench-2026101[9]*`,
`bench-20261021-*`, `rejudge-*.json`): second judge MiMo agrees with Luna (same verdict 57/60, kappa 0.89, key points
r = 0.90; Luna counts ~2x more unsupported claims); the mode prompt leaves the verdict sets unchanged (14 cases 0.77 ->
0.73 key points, MÖD 0.48 -> 0.49, verdict equal); on the new tasks the agent beats the RAG (key points explain 0.69 vs
0.63, propose 0.53 vs 0.41, develop 0.70 vs 0.47). The propose fix (2026-10-21: `MODES_GUIDE` propose = "the place is
not fixed", work from the ÖP growth passages; last turn forced to `answer_ready`) took mode recognition 0.42 -> 1.00,
key points 0.53 -> 0.62, places named 0.68 -> 0.88, but evidence seen 0.64 -> 0.51 and ~85 s per answer. The manual
review rescored stored rows of 6 generated cases without LLM (rows marked `rescored`). Reports regenerated and copied
to `reports/` on 2026-10-21.
Optimisation round (2026-10-21, benchmark report 2.9, ~$2.9): dev set = the 52 cases of `cases.jsonl` +
`cases_tasks.jsonl` + `cases_generated.jsonl`, `bench --label <name>` tags the result file (`-x-<name>.json`, kept out
of the older report tables; rows store `model`), MiMo Flash judge in the run, then `agentic.rejudge --judge-model
openai/gpt-6-luna` (a gain counts only if both judges see it). Benchmark fixes first: the judge gets every cited chunk
whole (`MAX_JUDGE_SOURCES, MAX_SOURCE_CHARS = 40, 3000`; before, 15 x 1500 cut the sources of a quarter of the answers,
inflating "unsupported"); verdict cases whose question also asks how / what it takes list `modes` (`bench.mode_ok`);
3 incidental reference points dropped in `REVIEW`. Results: per-mode recipes + a site-constraint grep checklist = no
gain, less evidence read (rejected); MiMo v2.6 Flash as the agent = +0.09 key points but ~5x the unsupported claims
(Luna judge), 2.3x slower, 2x cost (rejected); "Completeness" in `ANSWER_FORMAT` (replacing "prefer fewer,
well-sourced points": the agent left facts it had read out of the answer) = +0.03 / +0.05 key points (MiMo / Luna
judge), same latency and cost, unsupported +0.5 for Luna only (adopted, now the default). Not tried: Sol (~20x Luna)
and MiMo Pro. Lesson: exploration instructions do not move the scores; the answer writing does.
Bug round (2026-10-22, `bench --label toolfix`, dev set x 3 repeats, ~$1.6 + $0.2 Luna rejudge): before it, 57 % of the
agent answers lost a `read` (ids written `c:<id>`, 1,845 reads, 88 % never retried), MB 4 kap. and other chapters were
missing, kommun-filtered SQLite queries scanned the table and every image was re-sent each turn. After the fixes
(vs `x-v3`): failed reads 2.96 -> 0.32 per answer, answer time 55-71 s -> 33-45 s, first token 46-57 s -> 22-28 s,
unsupported claims (Luna judge) 1.96 -> 1.45, key points unchanged (MiMo 0.71 -> 0.71, Luna 0.72 -> 0.69). Answers
cite ~1 % of ids miscopied after their first characters: `tools.resolve_cited` maps them to the one shown chunk with the
longest common prefix (>= 8) in the chat numbering and in the judge's sources. Benchmark report section 2.10.
Verification (2026-10-22; technical report 7.10): the bugs above passed the tests and the benchmarks, so four free checks
look at real behaviour. (1) `python -m corpus.check` after every rebuild (sections crawl / documents / laws / index /
plans; exit 1 on an error; `data/corpus/check.json`: every line with its examples (`lines`, shown by the Pipeline
view), a summary (documents per kind:type and per kommun, plan status, documents per plan), compared with the previous
run per kommun; `--only` keeps the other sections of the previous file; `--delete-orphan-pdfs`: PDFs of earlier crawls
no manifest or snapshot references, 1,814 / 5.2 GB deleted on 2026-10-24, 70 % byte-identical copies of kept PDFs;
a WARN lists documents whose text names only other kommuner, "X kommun" / "X stad": 590 of 94k on 2026-10-23, mostly
joint administrations publishing the members' plans and forms on one site, Askersund -> Laxå / Lekeberg, Avesta ->
Fagersta / Norberg, Falun -> Borlänge, Vimmerby -> Hultsfred; they are filed under the site's kommun). It found: statute sections cut on a reference wrapped after "kap." ("enligt 6 kap." + "35 § 4 miljöbalken": PBL 5 kap.
11 a §, MBF 18 §, PBF 3 kap. 2 §; `chunk.rejoin` + sections only go forward in `law_chunks`), identical statute sections
dropped by the corpus-wide chunk dedup (JB 10 kap. 3 a §; law dedup key now includes the section, ids unchanged),
6.5k duplicate pages (Sitevision `?open.12_...`, `.printable`: `crawl._VIEW_PARAMS`, page hash in the crawler and in
`corpus.extract`), Sitevision "org.mozilla.javascript.Undefined@0" lines. (2) Tool health: `ToolResult.error`
(unknown_id / bad_args / not_found / no_data / exception; `run_tool` turns a tool exception into "exception" instead of
ending the run), recorded in the steps and the `tool_result` event; `agentic.health` prints failures per tool after
every bench run (thresholds `THRESHOLDS`); report section 2.10. (3) `python -m agentic.replay` (`--search N`: also times N stored searches; p50 / p95 / max per tool) replays every distinct
stored call (not search / images) on the current corpus: no exception, a read or law_section of something the corpus
has must succeed (`tests/test_replay.py`: 1,500 calls, skipped without the store); it found reads with "doc pdf:...",
a chunk id glued to a doc prefix, a valid doc_id next to a stale chunk_id, a chunk id as doc_id (all handled now).
(4) `python -m agentic.coverage sample|fetch|score`: the other benchmarks are built from the corpus and cannot see a
missing plan; this one fetches live the plans-in-force list of 29 sampled kommuner (`agentic/coverage_sources.jsonl`,
curated) and up to 20 plans each with their PDF links (`agentic/coverage_plans.jsonl`, versioned with its date), and
scores the share found in documents.jsonl by URL, or as a byte copy of a corpus PDF (`kept_copy`: `corpus.extract`
keeps one document per content, under the URL it met first). Reference fetched 2026-10-22: 202 plans in 13 measurable
kommuner. Before the national crawl 24 % of the plans with a PDF, 8 % of their PDFs; after it (2026-10-23; the OCR
makes PDFs readable but adds none) 78 % / 58 % (all PDFs of a plan: 53 %; 76 / 57 / 51 % by URL only). `score` also
records why each missing PDF is missing (`CAUSES`, `missing_cause`, from the kommun's manifest; benchmark report 2.11,
Pipeline view). On that corpus, of 339: 171 on plan pages never crawled while their list page was, one link past
`--max-depth` 4 (Haparanda 103 = 0 %, Norrtälje 59); 164 linked from a crawled page but not taken, because
`take_pdf_link` dropped a neutral-scored link without a `_PDF_HINTS` word and plan attachments are named after the
place or the step (Färgelanda's "1507-280-torsberg-139-mfl.pdf" on the list page, "Lagakraftbevis", "Undersökning om
betydande miljöpåverkan", "Protokollsutdrag": Kinda 100, Örebro 20, Härjedalen 17); 3 downloaded but neither kept nor
a copy; 1 a filter drop. A manifest records a page only when kept, so "never crawled" also covers a plan page fetched
but not kept. Both crawl causes are fixed (crawler rules above, 2026-10-25); re-crawling 10 of the 13 kommuner with
them downloaded 546 of their 560 listed PDFs (301 in the corpus before; Haparanda 0 -> 103 of 103, Färgelanda 2 -> 20,
Kinda 79 -> 178), to be scored after a rebuild. 16 kommuner unmeasurable: 11 of the 29 publish their
plans in force only in a map or search application (the corpus still has 2-157 plans each from their other pages,
not checked whether in force), 4 reach only 1-2 plans, Göteborg's list page was unreachable.
Leads (not done): a national `--force` crawl (the depth fix needs a full crawl; `--revisit` brings the plan-page PDFs
of `PDF_LINKS_VERSION` 3 with ~35k requests); for map-only kommuner, the kommun's plan
layers (WMS / WFS) or Lantmäteriet's digital plans (access and terms not checked), which also give address → plan;
a browser agent driving the map application, used as a crawler: once per map-only kommun (11 of the 29 sampled),
it lists the plans and their document links, which the crawler then downloads (a one-off cost per kommun, not per
question; at answer time it would be slow, costly and fragile).
Next: a check step on the draft answer (each claim against its cited chunk) to cut unsupported claims; expert review of a sample of generated cases; multi-turn cases (iterating on a project with the user); merge with
the localisation work of the other developer (agent `TOOLS_GUIDE` / `tools.py` are theirs, `ROLE` / `MODES_GUIDE` /
`ANSWER_FORMAT` / bench are ours; their localisation cases can be a `locate` task in the same case format).
`python -m agentic.report [--lang en|fr|both]` (default en: the project language is English) builds the PDF report in English
(`../pyrmit_doc/pyrmit_benchmark_report.pdf`) or French (`../pyrmit_doc/pyrmit_rapport_benchmark.pdf`) from the matrix result files (merged per configuration), via
headless Chrome/Edge, charts as inline SVG; `tr(fr, en)` / `fmt` / `money` follow the module-level `LANG`.
`python -m agentic.report_technical [--lang ...]` builds the detailed technical report (`pyrmit_rapport_technique.pdf` /
`pyrmit_technical_report.pdf`): Swedish planning context, data sources and freshness plan, pipeline with code refs,
retrieval eval (from `data/eval/*.json`), how each benchmark set is built (origin, source documents, who wrote the
reference, the 14 cases listed, example cases) and scored, with the judge prompts; figures read from the data.
Split: the technical report explains, the benchmark report gives conditions + results (overview RAG vs agent, one
table per set: 14 cases, MÖD, plankarta incl. ablations). `load_runs` keys result files by (set, systems, explore,
answer, ablation) from the file name (`FILE`: `-cases_caselaw` / `-cases_plans`, `-no-<tools>`); the conclusions text
is in `build_html` (`summary`, `reading`...), written from the numbers, so update it after new runs. Only the English
text was restructured (2026-10-17); the French bodies are the older layout. Both PDFs get a clickable outline
(`write_pdf`: Chrome `--generate-pdf-document-outline`, exact heading positions; `flatten_outline` drops the h1 entry
so sections are top level). The bench's RAG answer is streamed
(`run_rag` records `first_token_s`).
The key reports (benchmark, technical, hosting PDF + Markdown) are copied into `reports/` (versioned; the generators
write to `../pyrmit_doc/`, so copy them again after regenerating). `reports/pyrmit_architecture_report.html` (hand-written,
inline SVG diagrams: current system, target layers, needs and costs, pooling, data stores and releases, workflows,
worktrees) is the source of its PDF: render it with `agentic.report.write_pdf` and copy the PDF next to it.
`reports/pyrmit_status_deck.html` (hand-written 16:9 slides for newcomers: what was built, the embedding model local
vs through a gateway, what hosting needs, the options A OpenRouter + R2 / B all on Neon / C managed cloud, the
workflow, remaining tasks) prints
to `pyrmit_status_deck.pdf` with headless Chrome (`--print-to-pdf`, `@page` 1280 x 720 px); its numbers are copied
from the result files by hand, so update them with the data.
Gotcha (Windows): stopping a background shell does not kill its Python children; a "killed" benchmark can keep running
and spending credits. Check with `Get-CimInstance Win32_Process` and `Stop-Process`; for a chained `sh script.sh`, stop
the `sh.exe` first or it starts the next step. Claude Code reaps background shells when RAM runs low (16 GB machine):
run one benchmark process at a time (threads via `--workers` are fine); results are saved per answer, `--resume` /
rerunning `agentic.rejudge` continues. A run that sits a long time before its first case may be stuck at startup
(Hugging Face model check): the result file name is stamped when the cases start.

---

## Place Lookup (map pin, epic #31)

```
1. python -m place.fetch --kommun 0380  -> data/geo/0380/ (gitignored): kommun.geojson (OSM boundary), one GeoJSON per
   layer (Uppsala's plans / tillägg / områdesbestämmelser / pågående / användning from its ArcGIS service, Naturvårdsverket
   skyddade områden + Natura 2000 WFS, Boverket riksintressen) and manifest.json (fetch date, licence, count,
   "complete" = the plan layer holds every plan in force). ~10 s, 10k features (ADR-0002: snapshots, not per-pin calls)
   python -m place.plan_documents --kommun 0380  -> each plan's page (UrlDokument, 1,413 plans) and its PDFs into the
   crawl folder data/corpus/raw/web/0380/ + data/geo/0380/plan_pages.json (aktbeteckning -> page), 1 request/s. The
   entries go before the manifest's done line, which `corpus.crawl --revisit` needs last (until 2026-10-25 they were
   appended after it, so the revisit skipped Uppsala); a plan whose page a later `crawl --force` dropped from the
   manifest is recorded again. Run it after a crawl of 0380, not during (both rewrite the manifest)
   python -m place.plan_layers [--kommun <code>]  -> data/geo/<code>/ for every kommun in place/plan_sources.json
   (the registry: 180 kommuner with an open ArcGIS or WFS plan layer, built from docs/research/kommun-planlager.csv by
   `python -m place.registry`, hand-edited for base patterns of bare file-name links and licences, ADR-0006): the
   boundary from Nominatim, the whole plan layer clipped to it (a shared server's other kommuner fall out), each
   feature with the raw attributes plus `_plan` {ref, name, date, type, page, documents, dropped_links} normalised at
   write time (ADR-0005: bare file names through the base pattern, HTML anchors unwrapped, UNC / drive / file: paths
   dropped and counted). A kommun that fails, returns no polygon or under half the survey's count (not for shared
   servers) gets no snapshot and a reason, and keeps its boundary; each row is merged into data/geo/plan_coverage.json
   as its kommun finishes and data/geo/plan_coverage.md has one line per kommun of every run so far
   python -m place.plan_links [--kommun <code>]  -> data/geo/<code>/plan_links.jsonl (ADR-0007): every plan polygon of
   every snapshot matched to the store's detaljplan documents (data/corpus/documents.jsonl, read once; missing =
   nothing written), three levels per polygon, first hit wins: link (polygon page / document link = document url;
   a pilot kommun also through plan_pages.json), akt (`normalise_akt`: kommun prefix dropped, "-" / "." as "/", so
   0380-P 2015/12 = P2015-12; found in the title, file name or first 3,000 characters of the same kommun's documents only), name (title = plan name, marked
   review). Unmatched polygons -> data/geo/plan_fetch_list.json by kommun ("no public link" when the links were
   internal paths); data/geo/plan_match_report.md counts levels, unmatched and the store's unclaimed share. The
   run of 2026-11-05 (the 146 of 180 registry kommuner fetched plus Uppsala, the local store only): 258 of 66,569 polygons, that store holds few detaljplan documents per kommun
   python -m place.plan_links --kommun 0380 --hosted  -> the same link table from the hosted corpus's PDFs (the store at
   CORPUS_DATABASE_URL), a polygon also hitting the documents of the registry plan with its page, and a document the
   registry places under a plan page not hit at the akt or name level (a mention); a pilot kommun's additions and area
   regulations are matched too. Writes data/geo/<code>/plan_text_report.md, not the national fetch list or report;
   unreachable = nothing written. The run of 2026-11-05 for Uppsala: 1,268 of 1,417 polygons have documents (1,247
   link, 21 akt; 1,234 of the 1,377 in the plans layer), 148 with a page outside the registry, 1 with no document
2. The chat's map panel (components/place/) -> GET /api/place/profile -> place.profile.build_profile:
   kommun from the snapshot boundaries (a plan-layer kommun: the plans at the point from `_plan`, property
   "not_covered", sections "not_covered", a note when no plan was found since the layer is not known to be complete;
   every plan row carries `document_ids` / `document_match` from the link table, [] / None before a match run, and
   `corpus_documents` (role, title, address, read from the corpus at the pin, at most 8 s) with `text_status`: read,
   none, or unavailable when the corpus cannot be reached, which also adds a note),
   the property live from Uppsala's layer 51 (place.live, cached per point),
   features that contain the pin or cover >= 2 % of the property, plans newest first matched to the corpus registry by
   name, "outside" detaljplan only with a complete plan layer (else "unknown"); the national layers by the same rule;
   ancient remains live from RAÄ (WMS GetFeatureInfo, buffer = half the image over a square whose inscribed circle
   covers the property, then filtered to it; 30 m around the pin without a property); strandskydd "not checked";
   section_status ok / unavailable / not_covered so "none" never hides "not checked"; place.permits.likely_permits by
   fixed rules (bygglov by detaljplan status, dispens per protected area with the register's dispens authority,
   Natura 2000 tillstånd, KML tillstånd per Fornlämning, riksintressen as considerations). No model calls (ADR-0003)
3. The map's search (GET /api/place/search -> place.geocode.search_places): a street and number goes first to the pilot
   kommun's own address register (Uppsala's layer 11, 56k belägenhetsadresser; "Kungsgatan 47" also finds 47A-E, the
   typed post town picks among equal names), anything else or no register hit to Nominatim (1 request/s)
```

Evaluation (2026-10-25, report `reports/place_eval_report.md`, built by `python -m place.report` from the result files
plus the hand-written `place/report_findings.md`):
- `python -m place.check_sources --n 300` (free): each snapshot layer against the provider's own point query (ArcGIS
  identify with tolerance 0, WFS Intersects filter) at seeded points + the draft facit places, and the profile time
  -> `data/agentic/place-sources-*.json`. Not a facit: it checks the copy, not the data.
- `python -m place.check_search --n 150 [--form typed|lower|no_letter]` (free, Nominatim at 1 req/s): register addresses
  searched as typed, scored on distance and same property -> `place-search-*.json`. Since the search uses the same
  register, the typed form alone grades the register against itself: the lower / no_letter forms test typing variants.
- `python -m place.bench_answers run --repeats 3 --workers 4` (paid, ~$0.008 per answer incl. the MiMo judge): the chat
  agent on `place/cases_answers.jsonl` (15 Uppsala places, references locked before the run) under the conditions pin /
  address / vague / conflict, the question built by `place.context.question_with_place` as in the chat; `rejudge
  <file> --judge-model openai/gpt-6-luna` adds the second judge -> `place-answers-*.json`. The address condition counts
  "asks to pin it" without scoring it (the no-pin hint tells the agent to)

Gotchas: Uppsala's streets are properties too (Dragarbrunn 1:2, Kronåsen 1:2), so a pin on a street gets that property and
every plan it crosses; ~5 % of Uppsala's register address points inside plans lie on such a street property.
Naturvårdsverket sends some polygons with a ring outside its shell (15 of 93 protected areas in Uppsala): `PlaceStore`
repairs invalid geometries with `make_valid` on load, else "contains the pin" is wrong (Gula stigen was missed).
Länsstyrelsernas strandskydd services answered 403 during a planned outage (22-27 Oct 2026); the durable source is NGP
Strandskydd (#32). RAÄ has no bulk download (ancient remains must be live). The corpus registry holds no Uppsala plan
provisions (61 plans, none with provisions), so a pinned Uppsala plan always says "provisions not indexed". The
totalförsvar "stoppområde för höga objekt" covers ~86 % of Uppsala's points and is listed on almost every card. OSM
lacks most Swedish house numbers: Nominatim found the house for 28 % of Uppsala's addresses (the rest: the street or
nothing), hence the register first. MapLibre 6 loads its worker from a file next to its own module, which bundlers move:
`PlaceMap.pointAtBundledWorker` emits it with `new URL(..., import.meta.url)`. A `.next` folder from before the repo
moved (KTHAIS -> Projekt) made Turbopack panic ("Next.js package not found"): delete `.next` after moving the repo.

---

## Debugging Principle

> If a bug occurs, you should always be able to answer:
> **"Is this a data/retrieval bug (backend) or a display/UX bug (frontend)?"**

- **Access gate**: 401 "Access password required" -> `backend/src/dev_access.py`, cookie settings, `frontend/lib/auth.ts`
- **Auth bugs**: 401 "Could not validate credentials" -> expired/missing JWT, `JWT_SECRET_KEY`, `backend/src/security.py`, `backend/src/dependencies.py`
- **Wrong answer style** (generic RAG vs feasibility verdict): check the translated query and `parse_query` output (logged in observations as `parsed_location` / `parsed_units`)
- **RAG quality bugs**: open the "Pipeline inspector" on the answer (rewritten query, route, retrieved chunks + distances), or try queries in the Database view's semantic search; also retrieval logs/Langfuse (source, chunk_index, distance, preview) -> `backend/src/agents/base.py`, chunk sizes, embeddings
- **Law chunk metadata**: `law_chunks.chapter` / `section` drift (e.g. PBL 4 kap. 21 § stored as chapter 7 or 13) and lettered sections (`31 b §`) are merged into neighbours -> `backend/src/chunking/chunk_laws.py`; don't filter on them
- **No retrieval at all**: `_embed` returns None on failure (e.g. missing key for `EMBEDDING_PROVIDER`) and retrieval silently returns nothing
- **Odd feasibility verdict**: rules in `Orchestrator._determine_feasibility`; non-numeric `max_units_allowed` ("varies") yields UNCERTAIN
- **Ingestion bugs**: `backend/src/chunking/ingest_pipeline.py`, `backend/src/db/push_db.py`, `DATABASE_URL`, `MISTRAL_API_KEY`
- **Frontend bugs**: UI not updating, session not switching, redirect loops -> `frontend/components/`, `frontend/lib/auth.ts`

---

---

## Maintenance

After every successful change, update the file that owns what changed: this file for routes, schema, commands, env vars and key files; `CONTEXT.md` for domain terms. Never edit a file in `docs/pcr/` outside a `/challenge-pcr` session.
