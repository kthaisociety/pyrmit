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

# Backend tests and lint (config in backend/pyproject.toml)
cd backend && uv run pytest
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
