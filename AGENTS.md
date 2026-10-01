# AGENTS.md

## Hard Constraints

- **Do not make any git-related actions** (no commits, no pushes, no branch operations)
- **Do not create documentation files** unless explicitly requested

---

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
| `agents`   | `backend/agents/` | Python               | Multi-agent RAG: LawAgent + DocumentAgent + Orchestrator     |

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

Migrations/init: `backend/db/init.sql`. Match functions (pgvector): `backend/db/match_functions.sql`.

---

## Build & Run Commands

```bash
# Start all services (db, backend, frontend) via Docker
docker-compose up --build

# Backend only (dev, requires local .env)
cd backend && uvicorn main:app --reload --port 8000

# Frontend only (dev)
cd frontend && npm install && npm run dev

# Ingest law chunks (run once after DB is up)
cd backend && python chunking/ingest_laws.py

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

- `backend/main.py` -- FastAPI app entry, CORS, router registration
- `backend/llm.py` -- OpenAI client and model name resolution, AI Gateway switch (PCR-0003)
- `backend/models.py` -- SQLAlchemy ORM models
- `backend/schemas.py` -- Pydantic request/response schemas
- `backend/security.py` -- JWT creation/decoding, password hashing
- `backend/dependencies.py` -- `get_current_user` auth dependency (reads bearer token)
- `backend/routers/access_gate.py` -- Access gate unlock
- `backend/routers/auth.py` -- Signup, signin, token, signout, /me, profile, password
- `backend/routers/chat.py` -- Chat and streaming chat endpoints, chat session CRUD
- `backend/routers/chunks.py` -- Ingestion endpoints
- `backend/chunking/ingest_pipeline.py` -- Core ingestion: OCR, chunk, embed, push
- `backend/chunking/chunk_detaljplan.py` -- Detaljplan chunker
- `backend/chunking/chunk_laws.py` -- Law TXT chunker (chapter/section aware)
- `backend/chunking/ingest_laws.py` -- CLI script to ingest all law TXT files
- `backend/chunking/embed.py` -- Embedding helpers
- `backend/ocr/` -- Mistral OCR, PDF to Markdown
- `backend/db/database.py` -- SQLAlchemy engine + `get_db` session factory
- `backend/db/push_db.py` -- `PushDB` class: psycopg2 inserts into chunk tables
- `backend/db/init.sql` -- DB initialisation (pgvector extension, table creation)
- `backend/prompts/land_law_prompt.yaml` -- Prompt that rewrites user questions into Swedish legal search terms

### Frontend (TypeScript / Next.js)

- `frontend/app/(protected)/page.tsx` -- Main page: layout with Sidebar + Chat
- `frontend/app/(protected)/auth/page.tsx` -- Login / signup page
- `frontend/app/dev-access/` -- Access gate form
- `frontend/lib/auth.ts` -- Auth helpers, `authFetch`
- `frontend/components/Chat.tsx` -- Chat message list, input form, session history fetch
- `frontend/components/Sidebar.tsx` -- Session list, new chat button, user info + logout
- `frontend/components/Settings.tsx` -- User settings

### Agents (Multi-Agent RAG)

- `backend/agents/base.py` -- `BaseRAGAgent`: shared embedding, pgvector retrieval, LLM call
- `backend/agents/law_agent.py` -- LawAgent on law_chunks
- `backend/agents/document_agent.py` -- DocumentAgent on document_chunks
- `backend/agents/orchestrator.py` -- Combines both into the verdict
- `backend/agents/parsers.py` -- `parse_query`, `format_response`
- `backend/agents/AGENTIC_FLOW.md` -- Detailed agent flow
- `backend/routers/agents.py` -- POST /api/analyze endpoint

### Team Skills

- `.claude/skills/` -- shared Claude Code skills, copied from the committed state of the Custom-skills repo. Update by re-copying from that repo, not by editing here.

---

## Debugging Principle

> If a bug occurs, you should always be able to answer:
> **"Is this a data/retrieval bug (backend) or a display/UX bug (frontend)?"**

- **Auth bugs**: Missing/expired bearer token, 401s -> investigate `backend/routers/auth.py`, `backend/security.py`, `backend/dependencies.py`. Redirects to the access gate -> `backend/routers/access_gate.py`, `frontend/lib/`
- **RAG quality bugs**: Wrong or irrelevant chunks returned -> investigate `backend/agents/base.py`, embedding model, chunk size
- **Ingestion bugs**: Chunks not appearing in DB -> investigate `backend/chunking/ingest_pipeline.py`, `backend/db/push_db.py`
- **Chat bugs**: Wrong answer, missing context -> investigate `backend/routers/chat.py` prompt construction and retrieval call
- **Frontend bugs**: UI not updating, session not switching, auth redirect loop -> investigate `frontend/components/`

---

## Maintenance

After every successful change, update the file that owns what changed: this file for routes, schema, commands, env vars and key files; `CONTEXT.md` for domain terms. Never edit a file in `docs/pcr/` outside a `/challenge-pcr` session.
