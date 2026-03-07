# CLAUDE.md

## Hard Constraints

- **Do not make any git-related actions** (no commits, no pushes, no branch operations)
- **Do not create documentation files** unless explicitly requested

---

## Project Overview

Pyrmit is a Swedish legal RAG (Retrieval-Augmented Generation) chat assistant focused on Swedish land law and urban planning regulations (*fastighetsrätt*, *Plan- och bygglagen*). Users can upload planning documents (detaljplaner as PDF), which are OCR-processed, chunked, and embedded into a PostgreSQL+pgvector database. The chat interface uses RAG to retrieve relevant law and document chunks before calling OpenAI GPT to answer questions in Swedish legal context.

---

## System Topology

```
User (browser)
    |
    | HTTP (fetch with credentials/cookies)
    v
Next.js Frontend (frontend/ -- port 3000)
    |
    | REST API calls
    v
FastAPI Backend (backend/ -- port 8000)
    |
    |--- Auth router   (/api/auth/*)      -- signup, signin, signout, /me
    |--- Chat router   (/api/chat, /api/sessions/*)  -- RAG chat, session history
    |--- Chunks router (/api/chunks/*)    -- ingest detaljplan PDFs / law txt files
    |
    |--- RAG pipeline (routers/queryDB.py)
    |       |--- pgvector cosine similarity query on document_chunks
    |       |--- pgvector cosine similarity query on law_chunks
    |
    |--- Chunking pipeline (chunking/)
    |       |--- PDF -> Mistral OCR -> Markdown
    |       |--- Markdown/TXT -> DetaljplanChunker / LawChunker
    |       |--- OpenAI text-embedding-3-large (3072-dim)
    |       |--- PushDB (Supabase client) -> document_chunks / law_chunks tables
    |
    v
PostgreSQL + pgvector (db -- port 5432)
    Tables: users, accounts, sessions, chat_sessions, chat_messages,
            document_chunks (Vector 3072), law_chunks (Vector 3072)
```

### Package Map

| Name              | Location             | Type               | Purpose                                                              |
| ----------------- | -------------------- | ------------------ | -------------------------------------------------------------------- |
| `backend`         | `backend/`           | Python (FastAPI)   | REST API, auth, chat with RAG, chunking ingestion, DB models         |
| `frontend`        | `frontend/`          | TypeScript (Next.js) | Chat UI with sidebar session list, auth pages, cookie-based auth   |
| `legal-rag-system`| `legal-rag-system/`  | Python (standalone) | Experimental multi-agent RAG (LawAgent + CaseAgent + Orchestrator) |

---

## State Ownership

| Concern                        | Owner          | Key File(s)                                              |
| ------------------------------ | -------------- | -------------------------------------------------------- |
| User auth & sessions           | Backend        | `backend/routers/auth.py`, `backend/models.py`           |
| Chat session & message history | Backend (DB)   | `backend/routers/chat.py`, `backend/models.py`           |
| Embedding generation           | Backend        | `backend/routers/chat.py` (inline), `backend/chunking/ingest_pipeline.py` |
| RAG retrieval                  | Backend        | `backend/routers/queryDB.py`                             |
| Document chunking (detaljplan) | Backend        | `backend/chunking/chunk_detaljplan.py`                   |
| Law chunking                   | Backend        | `backend/chunking/chunk_laws.py`                         |
| DB push (Supabase)             | Backend        | `backend/db/push_db.py`                                  |
| DB models (SQLAlchemy ORM)     | Backend        | `backend/models.py`                                      |
| Chat UI / session switching    | Frontend       | `frontend/components/Chat.tsx`, `frontend/components/Sidebar.tsx` |
| Auth pages (login/signup)      | Frontend       | `frontend/app/auth/`                                     |
| System prompts                 | Backend        | `backend/prompts/land_law_prompt.yaml`                   |

---

## Data Flow

### Document Ingestion (Detaljplan PDF)

```
1. POST /api/chunks/ingest-detaljplan { input_path, output_path }
2. backend/chunking/ingest_pipeline.py:
   a. ensure_markdown_source: if PDF -> Mistral OCR -> .md file saved to data/ocr_markdown/
   b. DetaljplanChunker splits markdown into semantic chunks
   c. embed_texts_batch: OpenAI text-embedding-3-large (batched, 3072-dim)
   d. PushDB.push_chunks -> Supabase document_chunks table
3. Returns { inserted, deleted } counts
```

### Law Ingestion (Static TXT files)

```
1. Run chunking/ingest_laws.py (or POST /api/chunks/ingest-laws)
2. LawChunker splits law TXT by chapter/section structure
3. Embed with OpenAI text-embedding-3-large
4. PushDB.push_law_chunks -> Supabase law_chunks table
```

### Chat Request (RAG)

```
1. POST /api/chat { messages, session_id? }
2. auth middleware: validate session cookie -> get user
3. Create/lookup ChatSession in DB
4. Generate embedding for last user message (OpenAI text-embedding-3-large)
5. RAG(db, embedding, k=5): cosine distance query on document_chunks
6. (TODO: also query law_chunks for law context)
7. Build system prompt from backend/prompts/land_law_prompt.yaml + retrieved chunks
8. Call OpenAI chat completion (GPT-4o or similar)
9. Save assistant response as ChatMessage in DB
10. Return MessageResponse { role, content, session_id }
```

### Auth Flow

```
1. POST /api/auth/signup -> creates User + Account + Session, sets session cookie
2. POST /api/auth/signin -> verifies password (argon2), creates Session, sets session cookie
3. GET  /api/auth/me     -> validates session cookie -> returns User
4. POST /api/auth/signout -> deletes Session, clears cookie
```

---

## API Routes

| Method | Path                              | Auth | Purpose                                      |
| ------ | --------------------------------- | ---- | -------------------------------------------- |
| POST   | `/api/auth/signup`                | No   | Register new user                            |
| POST   | `/api/auth/signin`                | No   | Sign in, set session cookie                  |
| POST   | `/api/auth/signout`               | Yes  | Sign out, clear cookie                       |
| GET    | `/api/auth/me`                    | Yes  | Get current user                             |
| GET    | `/api/sessions`                   | Yes  | List chat sessions for user                  |
| GET    | `/api/sessions/{session_id}`      | Yes  | Get message history for a session            |
| POST   | `/api/chat`                       | Yes  | Send message, get RAG-powered response       |
| POST   | `/api/chunks/ingest-detaljplan`   | No   | Ingest a detaljplan PDF or markdown file     |
| POST   | `/api/chunks/ingest-laws`         | No   | Ingest law TXT files into law_chunks         |

---

## Database Schema (Key Tables)

| Table              | Key Columns                                                              |
| ------------------ | ------------------------------------------------------------------------ |
| `users`            | id, name, email, email_verified, image                                   |
| `accounts`         | id, user_id (FK), provider_id, password (argon2 hash)                   |
| `sessions`         | id, user_id (FK), token, expires_at                                      |
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

Backend `.env` (backend/.env):
```
DATABASE_URL=postgresql://user:password@db:5432/pyrmit
OPENAI_API_KEY=...
MISTRAL_API_KEY=...       # For PDF OCR
SUPABASE_URL=...          # For PushDB (chunk ingestion)
SUPABASE_KEY=...
```

Frontend `.env` (frontend/.env):
```
NEXT_PUBLIC_API_URL=http://localhost:8000
```

---

## Key Files Reference

### Backend (Python / FastAPI)

- `backend/main.py` -- FastAPI app entry, CORS, router registration
- `backend/models.py` -- SQLAlchemy ORM models (User, Session, ChatSession, ChatMessage, DocumentChunk, LawChunk)
- `backend/schemas.py` -- Pydantic request/response schemas
- `backend/dependencies.py` -- `get_current_user` auth dependency (reads session cookie)
- `backend/routers/auth.py` -- Signup, signin, signout, /me endpoints
- `backend/routers/chat.py` -- Chat endpoint: embed -> RAG -> OpenAI -> save to DB
- `backend/routers/queryDB.py` -- `RAG()` function: pgvector cosine distance retrieval
- `backend/routers/chunks.py` -- Ingestion endpoints for detaljplan and law files
- `backend/chunking/ingest_pipeline.py` -- Core ingestion: OCR, chunk, embed, push
- `backend/chunking/chunk_detaljplan.py` -- Detaljplan-specific chunker
- `backend/chunking/chunk_laws.py` -- Swedish law TXT chunker (chapter/section aware)
- `backend/chunking/ingest_laws.py` -- CLI script to ingest all law TXT files
- `backend/db/database.py` -- SQLAlchemy engine + `get_db` session factory
- `backend/db/push_db.py` -- `PushDB` class: Supabase client for chunk ingestion
- `backend/db/init.sql` -- DB initialisation (pgvector extension, table creation)
- `backend/prompts/land_law_prompt.yaml` -- Swedish land law system prompt for chat

### Frontend (TypeScript / Next.js)

- `frontend/app/page.tsx` -- Main page: auth check, layout with Sidebar + Chat
- `frontend/app/auth/` -- Login / signup pages
- `frontend/components/Chat.tsx` -- Chat message list, input form, session history fetch
- `frontend/components/Sidebar.tsx` -- Session list, new chat button, user info + logout

### Experimental Multi-Agent System

- `legal-rag-system/agents/orchestrator.py` -- Coordinates LawAgent + CaseAgent, feasibility analysis
- `legal-rag-system/agents/law_agent.py` -- RAG agent for statutory law (Ollama/Mistral + pgvector)
- `legal-rag-system/agents/case_agent.py` -- RAG agent for historical permit cases
- `legal-rag-system/utils/pg_vector_store.py` -- pgvector-backed vector store utility

---

## Debugging Principle

> If a bug occurs, you should always be able to answer:
> **"Is this a data/retrieval bug (backend) or a display/UX bug (frontend)?"**

- **Auth bugs**: Session cookie not set/expired, 401s -> investigate `backend/routers/auth.py`, `backend/dependencies.py`
- **RAG quality bugs**: Wrong or irrelevant chunks returned -> investigate `backend/routers/queryDB.py`, embedding model, chunk size
- **Ingestion bugs**: Chunks not appearing in DB -> investigate `backend/chunking/ingest_pipeline.py`, `backend/db/push_db.py`
- **Chat bugs**: Wrong answer, missing context -> investigate `backend/routers/chat.py` prompt construction and RAG call
- **Frontend bugs**: UI not updating, session not switching, auth redirect loop -> investigate `frontend/components/`

---

## Maintenance

After every successful change, update this CLAUDE.md if there are changes to the structure or to relevant CLAUDE.md sections.
