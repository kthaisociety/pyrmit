# AGENTS.md

## Project Knowledge

Load these only when the task needs them:

- `.claude/skills` -- The project skills, use these first hand. 
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
| POST   | `/api/auth/signout`                | Client-side signout, no server revocation |
| GET    | `/api/auth/me`                     | Current user                              |
| GET    | `/api/sessions`                    | List chat sessions                        |
| GET    | `/api/sessions/{session_id}`       | Messages in a chat session                |
| DELETE | `/api/sessions`                    | Delete all chat sessions                  |
| DELETE | `/api/sessions/{session_id}`       | Delete one chat session                   |
| POST   | `/api/chat`                        | Send message, get response                |
| POST   | `/api/chat/stream`                 | Send message, stream response             |
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
| `sessions`         | id, user_id (FK), token, expires_at (not used by auth, see ADR-0001)     |
| `chat_sessions`    | id, user_id (FK), title, updated_at                                      |
| `chat_messages`    | id, session_id (FK), role, content, created_at                           |
| `document_chunks`  | id, document_id, document_name, chunk_index, content, embedding (3072)  |
| `law_chunks`       | id, law_name, source_file, chapter, section, chunk_index, content, embedding (3072) |

Migrations/init: `backend/src/db/init.sql`. Match functions (pgvector): `backend/src/db/match_functions.sql`.

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

# Ingest law chunks (run once after DB is up)
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
- `MISTRAL_API_KEY` -- PDF OCR
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
- `backend/src/llm.py` -- OpenAI client and model name resolution, AI Gateway switch (PCR-0003)
- `backend/src/models.py` -- SQLAlchemy ORM models
- `backend/src/schemas.py` -- Pydantic request/response schemas
- `backend/src/security.py` -- JWT creation/decoding, password hashing
- `backend/src/dependencies.py` -- `get_current_user` auth dependency (reads bearer token)
- `backend/src/routers/access_gate.py` -- Access gate unlock
- `backend/src/routers/auth.py` -- Signup, signin, token, signout, /me, profile, password
- `backend/src/routers/chat.py` -- Chat and streaming chat endpoints, chat session CRUD
- `backend/src/routers/chunks.py` -- Ingestion endpoints
- `backend/src/chunking/ingest_pipeline.py` -- Core ingestion: OCR, chunk, embed, push
- `backend/src/chunking/chunk_detaljplan.py` -- Detaljplan chunker
- `backend/src/chunking/chunk_laws.py` -- Law TXT chunker (chapter/section aware)
- `backend/src/chunking/ingest_laws.py` -- CLI script to ingest all law TXT files
- `backend/src/chunking/embed.py` -- Embedding helpers
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
- `frontend/components/Chat.tsx` -- Chat message list, input form, session history fetch
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

- `backend/tests/unit/` -- pytest unit tests, one file per module in `backend/src/`, same folder layout. No real database or model calls (PCR-0011). Most files hold only a docstring so far. Known failures are marked `xfail` with a linked issue.
- `frontend/tests/unit/` -- Vitest + jsdom + React Testing Library, one `*.test.ts(x)` file per module in `components/` and `lib/` (PCR-0007). `lib/auth.test.ts` and `components/Sidebar.test.tsx` are the reference examples; the rest are `it.todo` placeholders.
- `frontend/tests/mocks/handlers.ts` -- MSW fake backend shared by all frontend tests; override per test with `server.use(...)` (PCR-0008). Unhandled requests fail the test.
- `frontend/tests/setup.ts`, `frontend/vitest.config.mts` -- test setup and Vitest config.
- `backend/pyproject.toml` `[tool.ruff.lint.per-file-ignores]` -- ruff baseline of pre-existing problems. Shrink only (PCR-0012).

### CI

- `.github/workflows/frontend.yml` -- `frontend / lint`, `frontend / test`, `frontend / docker` (builds the image, does not publish)
- `.github/workflows/backend.yml` -- `backend / lint`, `backend / test`, `backend / docker` (builds the image and checks key imports)
- Both run on every PR into and push to `dev` and `main`, with no path filter. All six are required checks via the "CI green" ruleset (PCR-0010).

### Team Skills

- `.claude/skills/` -- shared Claude Code skills, copied from the committed state of the Custom-skills repo. Update by re-copying from that repo, not by editing here.
- `docs/skills-tutorial.html` -- team tutorial for the skills: board, git flow, prompts per skill

---

## Debugging Principle

> If a bug occurs, you should always be able to answer:
> **"Is this a data/retrieval bug (backend) or a display/UX bug (frontend)?"**

- **Auth bugs**: Missing/expired bearer token, 401s -> investigate `backend/src/routers/auth.py`, `backend/src/security.py`, `backend/src/dependencies.py`. Redirects to the access gate -> `backend/src/routers/access_gate.py`, `frontend/lib/`
- **RAG quality bugs**: Wrong or irrelevant chunks returned -> investigate `backend/src/agents/base.py`, embedding model, chunk size
- **Ingestion bugs**: Chunks not appearing in DB -> investigate `backend/src/chunking/ingest_pipeline.py`, `backend/src/db/push_db.py`
- **Chat bugs**: Wrong answer, missing context -> investigate `backend/src/routers/chat.py` prompt construction and retrieval call
- **Frontend bugs**: UI not updating, session not switching, auth redirect loop -> investigate `frontend/components/`

---

## Maintenance

After every successful change, update the file that owns what changed: this file for routes, schema, commands, env vars and key files; `CONTEXT.md` for domain terms. Never edit a file in `docs/pcr/` outside a `/challenge-pcr` session.
