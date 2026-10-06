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
| Embedding generation (query)   | Backend        | `backend/agents/base.py` (`_embed`)                               |
| Embedding generation (ingest)  | Backend        | `backend/chunking/ingest_pipeline.py`                             |
| RAG retrieval                  | Backend        | `backend/agents/base.py` (`_retrieve*` methods)                   |
| Feasibility verdict            | Backend        | `backend/agents/orchestrator.py`                                  |
| Document chunking (detaljplan) | Backend        | `backend/chunking/chunk_detaljplan.py`                            |
| Law chunking                   | Backend        | `backend/chunking/chunk_laws.py`                                  |
| DB push (ingestion)            | Backend        | `backend/db/push_db.py`                                           |
| DB models (SQLAlchemy ORM)     | Backend        | `backend/models.py`                                               |
| LLM client / model selection   | Backend        | `backend/llm.py`, `backend/observability.py`, `backend/agents/base.py` |
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

### Chat Request

The frontend uses `POST /api/chat/stream` (SSE). `POST /api/chat` runs the same logic non-streamed.

```
1. POST /api/chat/stream { messages, session_id? }
2. Access-gate middleware, then get_current_user validates the Bearer JWT
3. Create/lookup ChatSession, save user message
4. LLM call: rewrite the latest message as a standalone English query
   (pulls location / units / project type from the last 5 history messages)
5. parse_query(translated) -> regex extraction of location, units, project_type (no LLM)
6a. If location OR units missing -> general RAG:
      embed once -> top-5 law_chunks + top-5 document_chunks (cosine)
      -> LLM answers in English markdown, Swedish quotes kept verbatim, + Sources list
6b. If both present -> Orchestrator.analyze(location, project_type, units):
      LawAgent and DocumentAgent run in parallel (ThreadPoolExecutor),
      each retrieves top-5 chunks and asks the LLM for structured JSON;
      _determine_feasibility applies fixed rules (max_units_allowed vs units,
      approval_rate thresholds 0.7 / 0.4) -> HIGHLY FEASIBLE / FEASIBLE WITH
      CHALLENGES / NOT FEASIBLE / UNCERTAIN; format_response -> markdown
7. Stream SSE events: session_id, thinking, tool_call/tool_result,
   pipeline, response.output_text.delta, response.completed, done (or error)
8. Save assistant message to chat_messages (content + `trace` = all pipeline events)
```

`pipeline` events (`{type: "pipeline", stage, data}`) carry debug data for the frontend pipeline inspector:
`translation` (original/rewritten query), `intent` (parsed fields + route), `retrieval` (per agent: search query,
matched chunks with source, chunk_index, cosine distance, full content), `agent_output` (raw LLM JSON per agent),
`verdict`, and `call` (one per LLM / embedding / pgvector call: name, model, system prompt, input, output, token
usage, duration). Calls are captured by a `CallRecorder` (`backend/pipeline_trace.py`) passed to the agents
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
| GET    | `/api/db/overview`                | Yes  | Chunk counts per table and per source           |
| GET    | `/api/db/chunks`                  | Yes  | Paginated chunks (`table`=law/document, `source`, `q` ILIKE filter) |
| POST   | `/api/db/search`                  | Yes  | Embedding + cosine top-k on both tables, no LLM |

All routes are additionally behind the access gate when it is enabled.

---

## Database Schema (Key Tables)

| Table              | Key Columns                                                                              |
| ------------------ | ---------------------------------------------------------------------------------------- |
| `users`            | id, name, email, email_verified, image                                                   |
| `accounts`         | id, user_id (FK), provider_id ("credentials"), password (hash)                           |
| `sessions`         | id, user_id (FK), token, expires_at, ip_address, user_agent — **unused**                 |
| `chat_sessions`    | id, user_id (FK), title, created_at, updated_at                                          |
| `chat_messages`    | id, session_id (FK), role, content, trace (JSONB, pipeline events), created_at           |
| `document_chunks`  | id, document_id, document_name, chunk_index, content, embedding (3072)                   |
| `law_chunks`       | id, law_name, source_file, chapter, chapter_title, section, chunk_index, content, embedding (3072) |

Tables are created at startup via `Base.metadata.create_all` in `backend/main.py`; since `create_all` never alters existing tables, columns added later (currently `chat_messages.trace`) are added there with an idempotent `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`. Extra SQL: `backend/db/init.sql`, `backend/db/create_law_chunks.sql`, `backend/db/match_functions.sql`.

---

## Build & Run Commands

```bash
# Start all services via Docker (backend still uses DATABASE_URL from backend/.env)
docker-compose up --build
# frontend: http://localhost:3000   backend docs: http://localhost:8000/docs

# Backend only (dev) -- Python 3.11 + uv
cd backend && uv venv && uv pip install -r requirements.txt
uvicorn main:app --reload --port 8000

# Frontend only (dev) -- lockfile is bun.lock
cd frontend && bun install && bun run dev

# Ingest law chunks
cd backend && python chunking/ingest_laws.py

# Tests
cd backend && pytest tests/
```

### Environment Variables

Backend `.env` (see `backend/.env.example`):
```
DATABASE_URL=postgresql://...          # Neon pooled endpoint with pgvector
AI_GATEWAY_API_KEY=                    # Vercel AI Gateway for chat (preferred if set)
OPENAI_API_KEY=                        # Required for embeddings (always direct OpenAI); chat fallback
MISTRAL_API_KEY=                       # PDF OCR
JWT_SECRET_KEY=                        # Required
ACCESS_TOKEN_EXPIRE_MINUTES=15         # Default 30 if unset
ACCESS_GATE_PASSWORD=                  # Enables the access gate when set
APP_ENV=development                    # development -> gpt-5.4-nano, production -> gpt-5.4-mini
CORS_ALLOWED_ORIGINS=http://localhost:3000
LANGFUSE_PUBLIC_KEY= / LANGFUSE_SECRET_KEY=   # Optional tracing
# Optional cookie settings: ACCESS_GATE_COOKIE_DOMAIN / _SECURE / _SAMESITE
```
The `SUPABASE_*` variables in `.env.example` are leftovers; no code reads them.

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
- `backend/routers/queryDB.py` -- Legacy standalone `RAG()` retrieval helper, not imported anywhere (chat retrieves via agents)
- `backend/chunking/ingest_pipeline.py` -- OCR, chunk, embed, push
- `backend/chunking/ingest_data_folder.py` -- Folder-level ingestion
- `backend/chunking/chunk_detaljplan.py` / `chunk_laws.py` -- Chunkers
- `backend/chunking/ingest_laws.py` -- CLI to ingest all law TXT files
- `backend/ocr/` -- Mistral OCR helpers
- `backend/db/database.py` -- SQLAlchemy engine + `get_db`
- `backend/db/push_db.py` -- `PushDB`: psycopg2 inserts/deletes for chunk tables
- `backend/prompts/*.yaml` -- Prompt files (chat prompts are currently inline in `chat.py` / agents)
- `backend/tests/test_agents.py` -- Agent / parser tests (incl. `TestParseQuery`)

### Agents (Multi-Agent RAG)

- `backend/agents/base.py` -- `BaseRAGAgent`: `_embed` (direct OpenAI, returns None on failure), pgvector retrieval, `_call_llm`, `_extract_json`; defines `OPENAI_CHAT_MODEL` / `OPENAI_EMBEDDING_MODEL`
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
- `frontend/components/Chat.tsx` -- Message list, SSE stream consumption, session history fetch; live Reasoning/Process steps while streaming; once finished, "Inspect pipeline" and a clickable "Sources" list (retrieved chunks per source, from `pipeline` events) below the answer
- `frontend/components/PipelineTrace.tsx` -- "Inspect pipeline" panel rendering `pipeline` events (live or from saved `trace`): expandable API calls with prompts/outputs, query rewrite, intent, retrieval, agent JSON, verdict
- `frontend/components/DatabaseBrowser.tsx` -- Database view: table stats, chunk browsing, semantic search playground
- `frontend/components/ChunkCard.tsx` -- Expandable chunk card (source, chunk index, distance badge, content)
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
- **No retrieval at all**: `_embed` returns None on failure (e.g. missing `OPENAI_API_KEY`) and retrieval silently returns nothing
- **Odd feasibility verdict**: rules in `Orchestrator._determine_feasibility`; non-numeric `max_units_allowed` ("varies") yields UNCERTAIN
- **Ingestion bugs**: `backend/chunking/ingest_pipeline.py`, `backend/db/push_db.py`, `DATABASE_URL`, `MISTRAL_API_KEY`
- **Frontend bugs**: UI not updating, session not switching, redirect loops -> `frontend/components/`, `frontend/lib/auth.ts`

---

## Maintenance

After every successful change, update this CLAUDE.md if there are changes to the structure or to relevant CLAUDE.md sections.
