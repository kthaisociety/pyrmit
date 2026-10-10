# CLAUDE.md

## Hard Constraints

- **Do not make any git-related actions** (no commits, no pushes, no branch operations)
- **Do not create documentation files** unless explicitly requested

---

## Project Overview

Pyrmit is a Swedish legal RAG (Retrieval-Augmented Generation) chat assistant focused on Swedish land law and urban planning regulations (*fastighetsrätt*, *Plan- och bygglagen*). Planning documents (detaljplaner as PDF) are OCR-processed (Mistral), chunked, and embedded into a PostgreSQL+pgvector database alongside chunked Swedish law texts. The chat translates the user's question to English, retrieves relevant law and document chunks, and calls an OpenAI model (directly or via Vercel AI Gateway) to answer **in English**, quoting Swedish source text verbatim. When a question contains both a location and a number of units, a multi-agent feasibility analysis runs instead of plain RAG.

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
    Tables: users, accounts, sessions (unused), chat_sessions, chat_messages,
            document_chunks (Vector 3072), law_chunks (Vector 3072)
```

Note: `docker-compose.yml` still defines a local `db` pgvector container (seeded with `backend/db/init.sql`), but the backend talks to whatever `DATABASE_URL` points at — normally Neon, so the local container sits unused.

### Package Map

| Name       | Location          | Type                 | Purpose                                                        |
| ---------- | ----------------- | -------------------- | -------------------------------------------------------------- |
| `backend`  | `backend/`        | Python (FastAPI)     | REST API, auth, chat with RAG, chunk ingestion, DB models      |
| `agents`   | `backend/agents/` | Python               | Multi-agent RAG: LawAgent + DocumentAgent + Orchestrator       |
| `corpus`   | `backend/corpus/` | Python (CLI)         | Offline corpus: Wikidata kommuner, Riksdagen laws, kommun website crawl, text extraction, chunking |
| `localrag` | `backend/localrag/` | Python             | Local retrieval: GPU embeddings, Swedish BM25, hybrid + rerank, kommun gazetteer, eval |
| `agentic`  | `backend/agentic/` | Python              | Tool-calling agent over the local corpus (CHAT_MODE=agent) + feasibility case benchmark |
| `frontend` | `frontend/`       | TypeScript (Next.js) | Chat UI with sidebar, settings, auth page, access-gate page    |

---

## State Ownership

| Concern                        | Owner          | Key File(s)                                                       |
| ------------------------------ | -------------- | ----------------------------------------------------------------- |
| Access gate (global password)  | Backend        | `backend/dev_access.py`, `backend/routers/access_gate.py`, `backend/main.py` |
| User auth (JWT)                | Backend        | `backend/routers/auth.py`, `backend/security.py`, `backend/dependencies.py` |
| Auth token storage             | Frontend       | `frontend/lib/auth.ts` (localStorage, `authFetch`)                |
| Chat session & message history | Backend (DB)   | `backend/routers/chat.py`, `backend/models.py`                    |
| Query translation / parsing    | Backend        | `backend/routers/chat.py`, `backend/agents/parsers.py`            |
| Embedding provider / model     | Backend        | `backend/embeddings.py` (`EMBEDDING_*` env, used by query + ingest; `EMBEDDING_RUNTIME` GPU/ONNX choice) |
| Embedding generation (query)   | Backend        | `backend/agents/base.py` (`_embed`)                               |
| Embedding generation (ingest)  | Backend        | `backend/chunking/ingest_pipeline.py`                             |
| RAG retrieval                  | Backend        | `backend/agents/base.py` (`_retrieve*` methods)                   |
| Feasibility verdict            | Backend        | `backend/agents/orchestrator.py`                                  |
| Document chunking (detaljplan) | Backend        | `backend/chunking/chunk_detaljplan.py`                            |
| Law chunking                   | Backend        | `backend/chunking/chunk_laws.py`                                  |
| DB push (ingestion)            | Backend        | `backend/db/push_db.py`                                           |
| DB models (SQLAlchemy ORM)     | Backend        | `backend/models.py`                                               |
| LLM client / model selection   | Backend        | `backend/llm.py` (`LLM_PROVIDER`), `backend/observability.py`, `backend/agents/base.py` (`LLM_MODEL`) |
| Embedding benchmark            | Backend        | `backend/benchmark/`                                              |
| Chat UI / session switching    | Frontend       | `frontend/components/Chat.tsx`, `frontend/components/Sidebar.tsx` |
| Pipeline inspector / DB browser UI | Frontend   | `frontend/components/PipelineTrace.tsx`, `frontend/components/DatabaseBrowser.tsx` |
| Auth & access-gate pages       | Frontend       | `frontend/app/(protected)/auth/`, `frontend/app/dev-access/`      |

---

## Data Flow

### Document Ingestion (Detaljplan PDF)

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

### Law Ingestion (Static TXT files)

```
1. Run backend/chunking/ingest_laws.py (CLI only, no API endpoint)
2. LawChunker splits law TXT by chapter (kap.) / section (§)
3. Embed with OpenAI text-embedding-3-large
4. PushDB.push_law_chunks -> law_chunks
```

### Offline Corpus + Local Retrieval (`RETRIEVAL_BACKEND=local`)

Everything lives in `backend/data/` (gitignored, ~20 GB with PDFs; only `data/agentic/` (benchmark results) and
`data/eval/` are versioned). The README has the install, data sharing and rebuild guide with times and sizes. Steps, from `backend/`:

```
python -m corpus.municipalities   # Wikidata -> data/corpus/municipalities.json (290 kommuner, websites, ~10k localities)
python -m corpus.laws             # Riksdagen open data -> data/corpus/raw/laws/*.txt (15 consolidated SFS)
python -m corpus.crawl            # kommun websites -> data/corpus/raw/web/<code>/{pages,pdf,manifest.jsonl}
python -m corpus.ocr              # optional: local EasyOCR (sv+en, GPU) of PDFs flagged needs_ocr -> raw/web/<code>/ocr/
python -m corpus.extract          # -> data/corpus/documents.jsonl (PyMuPDF text blocks, OCR text when available)
python -m corpus.chunk            # -> data/corpus/chunks.jsonl (one chunk per law §, ~1500-char doc chunks)
python -m localrag.index --model st-arctic-l-v2  # embeddings -> data/index/dense/<model>/ (incremental)
python -m localrag.store --model st-arctic-l-v2  # disk store served by the app: SQLite (chunks, FTS5 BM25, places) + vectors.npy
python -m localrag.eval --models st-bge-m3 ... # retrieval eval on localrag/questions.jsonl -> data/eval/
python -m corpus.plans            # detaljplan registry + planbestämmelser -> data/corpus/plans.jsonl (needs the store)
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
- `corpus.ocr` processes detaljplaner first, short documents first (hours on the GPU for the 769 scanned PDFs);
  then rerun `corpus.extract`, `corpus.chunk`, `localrag.index`, `localrag.store`, `corpus.plans`.

- The crawler honours robots.txt, 1 req/s per host, caps per kommun, resumes (a kommun whose manifest ends with
  `{"done": true}` is skipped). Pages are kept on topic keywords (`content_relevance`), PDFs when linked from relevant pages.
- `corpus.chunk` recognises a chapter only on its own line after a blank line, so wrapped references ("4 kap.
  miljöbalken") don't open chapters; lettered paragraphs (`6 a §`) are separate chunks; transitional provisions dropped.
  Chunk ids include a text hash, so re-chunking never reuses stale vectors.
- `LocalRetriever` searches two pools like the chat (laws / kommun documents). The kommun pool is filtered to the
  kommuner named in the question (`gazetteer.detect_kommuner`, fallback `CorpusPlaces` for places missing from
  Wikidata, e.g. "Veda"). Modes (`LOCAL_RAG_MODE`): dense (default), bm25 (Swedish stems + compound 5-grams),
  hybrid (RRF); optional cross-encoder reranker. Defaults (`localrag/service.py`) follow the eval: arctic-l-v2 on
  the Swedish query, no BM25 fusion, no reranker (neither beat dense-sv). The app serves from the **disk store**
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

### Agentic RAG (`CHAT_MODE=agent`)

`agentic/agent.py` runs a Responses-API tool loop (default `openai/gpt-6-luna` via OpenRouter) with tools from
`agentic/tools.py` (`CorpusTools` over `_DiskCorpus` (SQLite) or `_MemoryCorpus`): `find_kommun`, `search` (hybrid
dense + BM25 "stem"), `grep`, `list_documents`, `read`, `law_section` ("PBL", "9 kap. 4 §"), `plans` / `plan_rules`
(plan registry from `data/corpus/plans.jsonl`, loaded on first use), `view_map_area` (zoomed crop of a text-layer
plankarta around a printed label such as a property number "5:125", plus the codes printed in that area with their
meaning from the registry; search/word coordinates are unrotated, rendering uses `rect * page.rotation_matrix`),
`view_pdf_page` (whole page image sent to the model), plus `answer_ready`. Latency is almost all model turns, so: exploration turns run at
`AGENT_EXPLORE_EFFORT` (default medium, chosen on the benchmark; low = fast mode), the tool calls of one turn run in parallel, the model calls `answer_ready` when
it has enough, and only the final answer runs at `AGENT_EFFORT` (default medium), **streamed** (`answer_delta`
events); `AGENT_MAX_STEPS` (default 10) forces the answer. `CorpusTools.warm_up()` loads the query embedding model
up front (else the first search takes ~30 s). Tool outputs tag chunks as `[c:<chunk_id>]`; the answer must cite them.
In the chat, `agentic/service.py` runs it in a thread: tool calls stream as `tool_call`/`tool_result` SSE events,
each model turn and tool call is recorded for the inspector ("Explore (agent)" step), and the answer streams as
`response.output_text.delta` with citations numbered on the fly (`CitationNumberer`: one number per source label,
partial `c:` ids and open `[...]` groups held back until complete, repeats merged); the numbered source list
("- [n] label") is appended at the end and a `citations` pipeline event maps each n to its label and cited chunks.
The answer format asks for the law reference in the sentence and `[c:id]` right after the claim, never nested.
Robustness: ids of 8-15 hex characters (the model sometimes truncates) resolve by unique prefix
(`CorpusTools.get_chunk` -> `ids_with_prefix`), unknown ids are dropped (no "?"), and groups are split on ";" (commas
only between ids, so "PBL 9 kap. 3 §, 4 §" stays whole). The frontend turns "[n]" / "[n; m]" into clickable chips
(`linkCitations` in `Chat.tsx`; mixed or nested groups such as "[1; MB 7 kap. 15 § [2]]" become chips followed by the
reference in italics) that open
`components/SourceViewer.tsx`: the cited chunks, and the original document opened at the passage via
`routers/docs.py` (crawled PDF fetched as a blob with the auth header and shown in an iframe at
`#page=N&zoom=scale,left,top&navpanes=0`, passage highlighted; web pages and statutes opened in a new tab with a
`#:~:text=` fragment that Chrome scrolls to and highlights; scanned PDFs: page from the OCR text, no highlight).
The page is found by searching the chunk's 6-word phrases in the PDF (chunks store no page numbers).
The agent branch runs before the rewrite step and returns early.
Gotcha: **PBL 9 kap. was renumbered by SFS 2025:974** (bygglov in/outside a detaljplan now 9 kap. 56/57 §, liten
avvikelse 60-61 §, förhandsbesked 74 §; some sections have a second version in force 2027-01-01). Rulings and the
model's memory use the old numbers (9:30, 9:31 b, 9:17), so the prompt tells the agent to find provisions by wording.
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
`python -m agentic.report [--lang en|fr|both]` (default en: the project language is English) builds the PDF report in English
(`../pyrmit_doc/pyrmit_benchmark_report.pdf`) or French (`../pyrmit_doc/pyrmit_rapport_benchmark.pdf`) from the matrix result files (merged per configuration), via
headless Chrome/Edge, charts as inline SVG; `tr(fr, en)` / `fmt` / `money` follow the module-level `LANG`.
`python -m agentic.report_technical [--lang ...]` builds the detailed technical report (`pyrmit_rapport_technique.pdf` /
`pyrmit_technical_report.pdf`): Swedish planning context, data sources and freshness plan, pipeline with code refs,
retrieval eval (from `data/eval/*.json`), agent eval methodology with the judge prompts; figures read from the data.
The key reports (benchmark, technical, hosting PDF + Markdown) are copied into `reports/` (versioned; the generators
write to `../pyrmit_doc/`, so copy them again after regenerating).
Gotcha (Windows): stopping a background shell does not kill its Python children; a "killed" benchmark can keep running
and spending credits. Check with `Get-CimInstance Win32_Process` and `Stop-Process`.

### Chat Request

The frontend uses `POST /api/chat/stream` (SSE). `POST /api/chat` runs the same logic non-streamed.

```
1. POST /api/chat/stream { messages, session_id? }
2. Access-gate middleware, then get_current_user validates the Bearer JWT
3. Create/lookup ChatSession, save the user message AND an empty assistant message (status "streaming")
   -> the generation runs in a background thread (run_in_background) that is independent of the HTTP
   connection; the SSE response only relays its events, so closing the tab or opening another chat
   doesn't stop or lose the answer
4. LLM call: rewrite the latest message as a standalone English query
   (pulls location / units / project type from the last 5 history messages)
5. parse_query(translated) -> regex extraction of location, units, project_type (no LLM)
6a. If location OR units missing -> general RAG:
      embed once -> top-RAG_TOP_K (default 10) law + document chunks (pgvector or local corpus)
      -> LLM answers in English markdown, Swedish quotes kept verbatim, + Sources list
6b. If both present -> Orchestrator.analyze(location, project_type, units):
      LawAgent and DocumentAgent run in parallel (ThreadPoolExecutor),
      each retrieves top-5 chunks and asks the LLM for structured JSON;
      _determine_feasibility applies fixed rules (max_units_allowed vs units,
      approval_rate thresholds 0.7 / 0.4) -> HIGHLY FEASIBLE / FEASIBLE WITH
      CHALLENGES / NOT FEASIBLE / UNCERTAIN; format_response -> markdown
7. Stream SSE events: session_id, thinking, tool_call/tool_result,
   pipeline, response.output_text.delta, response.completed, done (or error)
8. The worker updates that assistant message from the streamed events: partial content every 2 s, then
   final content + `trace` (all pipeline events) + status "done" (or "error")
```

`pipeline` events (`{type: "pipeline", stage, data}`) carry debug data for the frontend pipeline inspector:
`translation` (original/rewritten query), `intent` (parsed fields + route), `retrieval` (per agent: search query,
matched chunks with source, chunk_index, cosine distance, full content), `agent_output` (raw LLM JSON per agent),
`verdict`, and `call` (one per LLM / embedding / pgvector call: name, model, system prompt, input, output, token
usage incl. reasoning tokens and the OpenRouter `cost` in USD, reasoning effort, duration). Calls are captured by a `CallRecorder` (`backend/pipeline_trace.py`) passed to the agents
(`LawAgent(db, client, recorder)`); the streamed answer call is recorded manually in `chat.py`. All events are also
saved in `chat_messages.trace` (JSONB, ~20–60 KB per answer) and returned by `GET /api/sessions/{id}`, so reopened
conversations keep the inspector and clickable sources (only `/api/chat/stream` writes traces). Agents attach their
retrieval trace as `result["retrieval"]`, and `Orchestrator.analyze` returns raw outputs under `agent_outputs`.

Gotchas:
- A location the regex misses (e.g. "for Vallentuna" — only `in/at/i/på/vid` are recognised) silently sends the request down the general-RAG path.
- The units regex doesn't match "apartment(s)", and the translation step turns "lägenheter" into "apartments", so most chat questions never reach the feasibility path.

### Auth Flow

```
1. POST /api/auth/signup -> creates User + Account (credentials, hashed password) -> returns JWT
2. POST /api/auth/signin (JSON) or /api/auth/token (OAuth2 form) -> verifies password -> returns JWT
3. Frontend stores the JWT in localStorage and sends it as Authorization: Bearer
4. get_current_user decodes the JWT (HS256, JWT_SECRET_KEY, sub = "user:<id>")
5. POST /api/auth/signout -> no-op on the server (JWTs are stateless); the frontend just clears the token
```

The `Session` model/table exists but is never written or read.

### Access Gate

When `ACCESS_GATE_PASSWORD` (or `DEV_ACCESS_PASSWORD`) is set, every backend request except `/api/access-gate/unlock` and OPTIONS returns 401 `"Access password required"` unless it carries the `dev_access_granted` cookie or an `x-access-gate-password` header. The frontend's `authFetch` redirects to `/dev-access` on that response.

---

## API Routes

| Method | Path                              | Auth | Purpose                                         |
| ------ | --------------------------------- | ---- | ----------------------------------------------- |
| POST   | `/api/access-gate/unlock`         | No   | Submit access-gate password, set cookie         |
| POST   | `/api/auth/signup`                | No   | Register new user, return JWT                   |
| POST   | `/api/auth/signin`                | No   | Sign in (JSON), return JWT                      |
| POST   | `/api/auth/token`                 | No   | OAuth2 password-form sign in, return JWT        |
| POST   | `/api/auth/signout`               | No   | No-op (client clears token)                     |
| GET    | `/api/auth/me`                    | Yes  | Get current user                                |
| PATCH  | `/api/auth/me`                    | Yes  | Update profile name                             |
| PATCH  | `/api/auth/password`              | Yes  | Change password                                 |
| GET    | `/api/sessions`                   | Yes  | List chat sessions for user                     |
| GET    | `/api/sessions/{session_id}`      | Yes  | Get message history for a session               |
| PATCH  | `/api/sessions/{session_id}`      | Yes  | Rename a session                                |
| DELETE | `/api/sessions/{session_id}`      | Yes  | Delete a session                                |
| DELETE | `/api/sessions`                   | Yes  | Delete all sessions of the user                 |
| GET    | `/api/history`                    | Yes  | All messages of the user                        |
| POST   | `/api/chat`                       | Yes  | Send message, get full response                 |
| POST   | `/api/chat/stream`                | Yes  | Send message, stream response (SSE) — used by UI |
| POST   | `/api/chunks/ingest-detaljplan`   | Yes  | Ingest a detaljplan PDF or markdown file        |
| POST   | `/api/chunks/ingest-data-folder`  | Yes  | Ingest every supported file in a folder         |
| POST   | `/api/analyze`                    | Yes  | Multi-agent feasibility analysis                |
| GET    | `/api/db/overview`                | Yes  | Chunk counts per table and per source (`store`=neon/local) |
| GET    | `/api/db/chunks`                  | Yes  | Paginated chunks (`table`=law/document, `source`, `q` text filter, `store`) |
| POST   | `/api/db/search`                  | Yes  | Retrieval top-k on both pools, no LLM (`store`: neon = pgvector, local = localrag) |
| GET    | `/api/docs/locate`                | Yes  | Where to open a cited chunk: PDF page + zoom on the passage, or original URL with `#:~:text=` |
| GET    | `/api/docs/pdf/{chunk_id}`        | Yes  | The chunk's crawled PDF with the passage highlighted (PyMuPDF annotations) |
| GET    | `/api/benchmark/sets`, `/cases`, `/case`, `/image/{id}` | Yes | Benchmark case sets, cases, one case + its past results (from `data/agentic/bench-*.json`), plankarta crop |
| POST   | `/api/benchmark/run`              | Yes  | Run the agent on a case now (chat settings) and grade it; background job (spends credits) |
| GET    | `/api/benchmark/run/{job_id}`     | Yes  | Progress (tool calls) and result of that job (polled: a run outlasts the frontend proxy timeout) |

All routes are additionally behind the access gate when it is enabled.

---

## Database Schema (Key Tables)

| Table              | Key Columns                                                                              |
| ------------------ | ---------------------------------------------------------------------------------------- |
| `users`            | id, name, email, email_verified, image                                                   |
| `accounts`         | id, user_id (FK), provider_id ("credentials"), password (hash)                           |
| `sessions`         | id, user_id (FK), token, expires_at, ip_address, user_agent — **unused**                 |
| `chat_sessions`    | id, user_id (FK), title, created_at, updated_at                                          |
| `chat_messages`    | id, session_id (FK), role, content, trace (JSONB, pipeline events), status (streaming/done/error, assistant only), created_at |
| `document_chunks`  | id, document_id, document_name, chunk_index, content, embedding (3072)                   |
| `law_chunks`       | id, law_name, source_file, chapter, chapter_title, section, chunk_index, content, embedding (3072) |

Tables are created at startup via `Base.metadata.create_all` in `backend/main.py`; since `create_all` never alters existing tables, columns added later (currently `chat_messages.trace` and `status`) are added there with an idempotent `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`. Extra SQL: `backend/db/init.sql`, `backend/db/create_law_chunks.sql`, `backend/db/match_functions.sql`.

---

## Build & Run Commands

### Run the app on this machine (the normal way)

The app configuration (agent chat, local corpus, GPT-6 Luna) is in `backend/.env` with the secrets, so no
command-line overrides are needed. Don't blank `ACCESS_GATE_PASSWORD` or override `.env` values when starting it
for the user. Needs the GPU and `backend/data/` (local store, `corpus/plans.jsonl`).

```bash
# 0. Nothing already running? (a stale backend on :8000 or frontend on :3000 makes the new one fail)
#    PowerShell: Get-CimInstance Win32_Process | ? { $_.CommandLine -match 'uvicorn main:app|next' } | select ProcessId, CommandLine
# 1. Backend (background shell), from backend/ -- use the venv python, not `uv run` (re-syncs the venv)
cd backend && .venv/Scripts/python.exe -m uvicorn main:app --port 8000 > backend.log 2>&1
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

### Other commands

```bash
# Start all services via Docker (backend still uses DATABASE_URL from backend/.env)
docker-compose up --build
# frontend: http://localhost:3000   backend docs: http://localhost:8000/docs

# Backend only (dev) -- Python 3.13 + uv
cd backend && uv venv && uv pip install -r requirements.txt
uvicorn main:app --reload --port 8000

# Frontend only (dev) -- lockfile is bun.lock
cd frontend && bun install && bun run dev

# Ingest law chunks
cd backend && python chunking/ingest_laws.py

# Local RAG deps (corpus/ + localrag/): torch with CUDA first, then the optional group
cd backend && uv pip install torch --index-url https://download.pytorch.org/whl/cu128 && uv pip install -e ".[local]"

# Tests
cd backend && pytest tests/
```

### Environment Variables

Backend `.env` (see `backend/.env.example`):
```
DATABASE_URL=postgresql://...          # Neon pooled endpoint with pgvector
AI_GATEWAY_API_KEY=                    # Vercel AI Gateway for chat (preferred if set)
OPENAI_API_KEY=                        # Required for embeddings with the default EMBEDDING_PROVIDER=openai; chat fallback
LLM_PROVIDER= / LLM_MODEL=             # Optional chat override: openai | gateway | openrouter (+ OPENROUTER_API_KEY or OPENROUTER_KEY)
LLM_REASONING_EFFORT=                  # e.g. high / xhigh for answers (Responses API `reasoning`); rewrites use
                                       # LLM_REWRITE_REASONING_EFFORT (default low) -- observability.create_chat_completion
EMBEDDING_PROVIDER/MODEL/DIM/...       # Optional, see backend/embeddings.py; default openai text-embedding-3-large, 3072
EMBEDDING_RUNTIME=auto                 # local (st) models: torch fp16 on a CUDA GPU, else the model's ONNX int8 export
                                       # (`onnx_file` in localrag/models.toml) on the CPU via onnxruntime | torch | onnx
RETRIEVAL_BACKEND=pgvector             # or "local" (localrag/service.py) + LOCAL_RAG_MODEL / _MODE / _DENSE_QUERY / _RERANKER
RAG_TOP_K=10                           # chunks per pool (laws / documents) given to the answer model
CHAT_MODE=rag                          # or "agent" (agentic/service.py) + AGENT_MODEL / AGENT_EFFORT (final answer,
                                       # medium) / AGENT_EXPLORE_EFFORT (tool turns, medium) / AGENT_MAX_STEPS (10)
HF_HUB_DISABLE_XET=1                   # Hugging Face downloads can hang on Windows without it
MISTRAL_API_KEY=                       # PDF OCR
JWT_SECRET_KEY=                        # Required
ACCESS_TOKEN_EXPIRE_MINUTES=15         # Default 30 if unset
ACCESS_GATE_PASSWORD=                  # Enables the access gate when set
APP_ENV=development                    # development -> gpt-5.4-nano, production -> gpt-5.4-mini
CORS_ALLOWED_ORIGINS=http://localhost:3000
LANGFUSE_PUBLIC_KEY= / LANGFUSE_SECRET_KEY=   # Optional tracing
# Optional cookie settings: ACCESS_GATE_COOKIE_DOMAIN / _SECURE / _SAMESITE
```

Frontend `.env`:
```
API_PROXY_TARGET=http://localhost:8000   # or NEXT_PUBLIC_API_URL; used by the next.config.js rewrite
```

---

## Key Files Reference

### Backend (Python / FastAPI)

- `backend/main.py` -- App entry: loads .env, creates tables, access-gate middleware, CORS, router registration
- `backend/dev_access.py` -- Access-gate password / cookie helpers
- `backend/security.py` -- JWT encode/decode, password hashing (pwdlib)
- `backend/dependencies.py` -- `get_current_user` (Bearer JWT -> User)
- `backend/llm.py` -- OpenAI vs Vercel AI Gateway client, model-name resolution, Responses API helpers
- `backend/observability.py` -- Langfuse-wrapped `create_chat_completion`, `create_embedding`, `start_observation` (no-ops without Langfuse)
- `backend/pipeline_trace.py` -- `CallRecorder` + `recorded_chat_completion` / `recorded_embedding`: capture prompts, outputs, usage, timings for the pipeline inspector
- `backend/models.py` -- SQLAlchemy ORM models
- `backend/schemas.py` -- Pydantic request/response schemas
- `backend/routers/auth.py` -- Signup, signin, token, signout, me, password
- `backend/routers/access_gate.py` -- Access-gate unlock endpoint
- `backend/routers/chat.py` -- Chat (plain + SSE stream): translate -> parse -> general RAG or orchestrator -> save
- `backend/routers/chunks.py` -- Ingestion endpoints
- `backend/routers/agents.py` -- `/api/analyze`
- `backend/routers/db_browser.py` -- Read-only chunk browser + semantic search (never exposes user/auth tables or embeddings)
- `backend/routers/docs.py` -- Open a cited chunk in its original document (PDF page + highlight, or URL text fragment)
- `backend/routers/benchmark.py` -- Benchmark view API: case sets (`SETS`: cases / caselaw / plans), past results per case
  parsed from the result file names (`RESULT_FILE`), and in-memory run jobs (`JOBS`, lost on restart)
- `backend/routers/queryDB.py` -- Legacy standalone `RAG()` retrieval helper, not imported anywhere (chat retrieves via agents)
- `backend/chunking/ingest_pipeline.py` -- OCR, chunk, embed, push
- `backend/chunking/ingest_data_folder.py` -- Folder-level ingestion
- `backend/chunking/chunk_detaljplan.py` / `chunk_laws.py` -- Chunkers
- `backend/chunking/ingest_laws.py` -- CLI to ingest all law TXT files
- `backend/ocr/` -- Mistral OCR helpers
- `backend/db/database.py` -- SQLAlchemy engine + `get_db`
- `backend/db/push_db.py` -- `PushDB`: psycopg2 inserts/deletes for chunk tables
- `backend/prompts/*.yaml` -- Prompt files (chat prompts are currently inline in `chat.py` / agents)
- `backend/embeddings.py` -- `Embedder` (openai / openrouter / local OpenAI-compatible server / in-process sentence-transformers), `get_embedder()` from `EMBEDDING_*` env; vector column dim = `EMBEDDING_DIM`. `st` models run on torch with a GPU, else on `_OnnxEncoder` (onnxruntime + tokenizers, CLS/mean pooling, 1024-token window) when `onnx_file` is set: arctic int8 = 34 ms/query, 0.9 GB, same recall as the GPU (R@5 0.944)
- `backend/chunking/reembed.py` -- Re-embed stored chunks with the configured model (alters the vector dim, stores the model label as column comment; `main.py` logs an error when DB and config disagree). Needs `--yes`; meant for a dedicated Neon branch
- `backend/benchmark/` -- Retrieval-only embedding benchmark: `export_corpus.py` (freeze DB chunks to `data/corpus.jsonl`), `models.toml` (models to compare), `questions.jsonl` (hand-written questions, en+sv, labelled by verbatim excerpts since law chapter/section metadata is unreliable), `generate_questions.py` (synthetic questions via the chat LLM), `run.py` (hit@k / recall@5 / MRR, per-table search like the chat; caches corpus vectors in `cache/`, writes `results/`). Runs spend API credits
- `backend/corpus/` -- `municipalities.py`, `laws.py`, `crawl.py`, `ocr.py`, `extract.py`, `chunk.py` (see "Offline Corpus"),
  `caselaw.py` (MÖD rulings from lagen.nu, for the case benchmark; not part of the searchable corpus),
  `plans.py` (detaljplan registry + planbestämmelser)
- `backend/localrag/` -- `analyzer.py` (Swedish BM25 tokens), `gazetteer.py`, `index.py` (VectorStore), `retriever.py`
  (`LocalRetriever`), `service.py` (chat integration), `eval.py` + `questions.jsonl` (use-case questions with
  verbatim-excerpt / law-section labels), `rewrite_queries.py` (Swedish queries from the chat LLM), `models.toml`
  (local + OpenRouter embedding models). Do not `pip install` packages that depend on torch without the CUDA
  index (easyocr pulled in a CPU torch once)
- `backend/agentic/` -- `tools.py` (CorpusTools + tool schemas), `agent.py` (tool loop), `service.py` (chat
  integration, `CitationNumberer`), `run.py` (CLI), `bench.py` + `cases.jsonl` (case benchmark),
  `cases_from_caselaw.py` (cases from MÖD rulings), `grounding.py`
- `backend/tests/test_agents.py` -- Agent / parser tests (incl. `TestParseQuery`); 3 `_extract_json` fallback tests
  fail (they expect the old raising behaviour). It stubs `sqlalchemy` in `sys.modules`, so run it in its own pytest
  process: collected together with `test_chat_background.py` the latter fails to import
- `backend/tests/test_chat_background.py` -- the streamed answer is saved when the client disconnects (SQLite + fake
  LLM). Run with `.venv/Scripts/python -m pytest tests/<file>` (not `uv run`, which re-syncs the venv to uv.lock)
- `backend/tests/test_agent_citations.py` -- streamed citation numbering for every delta size

### Agents (Multi-Agent RAG)

- `backend/agents/base.py` -- `BaseRAGAgent`: `_embed` (shared embedder, returns None on failure), pgvector retrieval, `_call_llm`, `_extract_json`; defines `OPENAI_CHAT_MODEL` (overridable with `LLM_MODEL`)
- `backend/agents/law_agent.py` -- LawAgent on `law_chunks` -> JSON (max_units_allowed, applicable_laws, conditions, confidence, ...)
- `backend/agents/document_agent.py` -- DocumentAgent on `document_chunks` -> JSON (approval_rate, similar_cases, typical_timeline_months, ...)
- `backend/agents/orchestrator.py` -- Parallel agent execution + rule-based feasibility verdict
- `backend/agents/parsers.py` -- `parse_query` (regex) and `format_response` (markdown)
- `backend/agents/bygglov_ag.py` -- Empty placeholder

### Frontend (TypeScript / Next.js)

- `frontend/next.config.js` -- `/api/*` rewrite to the backend
- `frontend/lib/auth.ts` -- Token storage (localStorage), `authFetch`, access-gate redirect
- `frontend/lib/dev-access.ts`, `frontend/lib/access-gate-server.ts` -- Access-gate cookie helpers
- `frontend/app/(protected)/page.tsx` -- Main page: Sidebar + Chat
- `frontend/app/(protected)/auth/page.tsx` -- Login / signup
- `frontend/app/(protected)/layout.tsx` -- Server-side guard: redirects to `/dev-access` without the access-gate cookie
- `frontend/app/dev-access/` -- Access-gate password page
- `frontend/components/Chat.tsx` -- Message list, SSE stream consumption, session history fetch; a new chat is announced
  to the sidebar on the `session_id` event; opening another chat aborts the local stream only, and history
  messages with status "streaming" are re-fetched every 2 s until done; live Reasoning/Process steps while streaming; once finished, "Inspect pipeline" and a clickable "Sources" list (retrieved chunks per source, from `pipeline` events) below the answer
- `frontend/components/PipelineTrace.tsx` -- "Inspect pipeline" panel rendering `pipeline` events (live or from saved `trace`): a totals line (time, tokens, cost) then one collapsible step per stage (Understand, Retrieve, Agents, Verdict, Answer) with a one-line summary, and the stage's API calls nested inside (assigned by call kind/name in `stepOf`)
- `frontend/components/DatabaseBrowser.tsx` -- Database view with a Neon / Local corpus toggle: stats, chunk browsing, search playground
- `frontend/components/ChunkCard.tsx` -- Expandable chunk card (source, chunk index, distance badge, content)
- `frontend/components/SourceViewer.tsx` -- Side panel for a clicked citation [n]: cited chunks + the original document at the passage
- `frontend/components/CitedMarkdown.tsx` -- Answer markdown with [n] citation chips (`linkCitations`), shared by Chat and Benchmark
- `frontend/components/BenchmarkBrowser.tsx` -- Benchmark view (sidebar, above Database): browse the case sets, a case's
  reference (verdicts, key points, evidence, source, map crop) and past results, and "Test with the agent" (run + judge)
- `frontend/components/Sidebar.tsx` -- Session list, new chat, Database / Settings buttons, user info
- `frontend/components/Settings.tsx` -- Profile / password settings

---

## Debugging Principle

> If a bug occurs, you should always be able to answer:
> **"Is this a data/retrieval bug (backend) or a display/UX bug (frontend)?"**

- **Access gate**: 401 "Access password required" -> `backend/dev_access.py`, cookie settings, `frontend/lib/auth.ts`
- **Auth bugs**: 401 "Could not validate credentials" -> expired/missing JWT, `JWT_SECRET_KEY`, `backend/security.py`, `backend/dependencies.py`
- **Wrong answer style** (generic RAG vs feasibility verdict): check the translated query and `parse_query` output (logged in observations as `parsed_location` / `parsed_units`)
- **RAG quality bugs**: open the "Pipeline inspector" on the answer (rewritten query, route, retrieved chunks + distances), or try queries in the Database view's semantic search; also retrieval logs/Langfuse (source, chunk_index, distance, preview) -> `backend/agents/base.py`, chunk sizes, embeddings
- **Law chunk metadata**: `law_chunks.chapter` / `section` drift (e.g. PBL 4 kap. 21 § stored as chapter 7 or 13) and lettered sections (`31 b §`) are merged into neighbours -> `backend/chunking/chunk_laws.py`; don't filter on them
- **No retrieval at all**: `_embed` returns None on failure (e.g. missing key for `EMBEDDING_PROVIDER`) and retrieval silently returns nothing
- **Odd feasibility verdict**: rules in `Orchestrator._determine_feasibility`; non-numeric `max_units_allowed` ("varies") yields UNCERTAIN
- **Ingestion bugs**: `backend/chunking/ingest_pipeline.py`, `backend/db/push_db.py`, `DATABASE_URL`, `MISTRAL_API_KEY`
- **Frontend bugs**: UI not updating, session not switching, redirect loops -> `frontend/components/`, `frontend/lib/auth.ts`

---

## Maintenance

After every successful change, update this CLAUDE.md if there are changes to the structure or to relevant CLAUDE.md sections.
