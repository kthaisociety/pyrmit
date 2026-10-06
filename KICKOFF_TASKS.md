# Onboarding

## 1. Running it

**Prerequisites:** an OpenAI API key (or Vercel AI Gateway creds — `AI_GATEWAY_API_KEY`), and the project's Neon Postgres connection string. There's no local database to stand up — `DATABASE_URL` in `backend/.env` already points at a pooled Neon endpoint (`*.neon.tech`) with pgvector enabled. Docker Desktop is only needed if you want to run everything via `docker-compose`. For hybrid/local dev: Python 3.11 + `uv`, and Bun (frontend lockfile is `bun.lock`).

**Setup**
```bash
cp backend/.env.example backend/.env   # fill in OPENAI_API_KEY, JWT_SECRET_KEY, ACCESS_GATE_PASSWORD, DATABASE_URL (Neon), etc.
# frontend/.env needs ACCESS_GATE_PASSWORD (must match backend) and API_PROXY_TARGET
```

**Run everything (Docker)**
```bash
docker-compose up --build
# frontend: http://localhost:3000
# backend:  http://localhost:8000/docs
```
Heads up: `docker-compose.yml` still defines a local `db` (pgvector) container and mounts `backend/db/init.sql` into it. That container starts but sits unused — the backend reads `DATABASE_URL` from `backend/.env`, which points at Neon, not at that container. Don't be confused if the local container looks empty; it's not what the app talks to.

**Run locally (hybrid, faster iteration)**
```bash
cd backend
uv venv && source .venv/bin/activate
uv pip install -r requirements.txt
# DATABASE_URL is already set to the Neon connection string in backend/.env — nothing to start locally
uvicorn main:app --reload

cd frontend
bun install
bun run dev
```

# Tasks

Four tasks below, ordered roughly easy → more involved. Pick whichever matches your comfort level/interest, or split into groups and work on one together!

I'd recommend to explore to codebase first, understand the structure and how it's connected.


---

## Task 1 — Fix the location-parsing bug

**Problem:** Before the system can answer a question properly, it tries to pull out a location, a number of units, and a project type from what you typed — using plain regex, not AI. The location part only recognizes the words `in`, `at`, `i`, `på`, `vid` as "a location is coming next." So a question like *"is there a height restriction **for** Vallentuna?"* never gets a location extracted — silently, no error, it just quietly returns nothing.

**What you're building:** Fix the regex to also catch `for` (and maybe other natural phrasings), then prove it works with tests.

**Why it matters:** Whether a location gets found or not decides which of two very different answer styles you get — a plain retrieved-and-answered response, or a structured feasibility verdict with a confidence score and next steps. A missed location silently downgrades the answer with zero visible error.

**Files that might help:**
- `backend/agents/parsers.py` — `parse_query()`, the function with the bug
- `backend/routers/chat.py` — search for `if not location or not units:` to see what changes depending on the result
- `backend/tests/test_agents.py` — `TestParseQuery` class already exists here, easy to copy the pattern and add more cases

**Gotchas:**
- Loosening the regex can create false matches (e.g. "looking **for** information" isn't a location) — write a few should-NOT-match test cases too, not just should-match ones.


**Questions:**
- *"Does it actually matter if we get an answer either way?"* 
- *"Should we handle Swedish grammar too?"* 
- *"Is there a better way to handle this for our case?"*
---

## Task 2 — Make "sign out" actually do something

**Problem:** Click "Sign Out" today and it does log you out — but only because the browser throws away its login token (`clearAccessToken()` in `frontend/lib/auth.ts`) and sends you back to the login page.
 The actual server call behind it, `POST /api/auth/signout` (`backend/routers/auth.py`), does nothing: no arguments, no database check, it just always replies "Signed out successfully" no matter who calls
it or with what token. That old token stays perfectly valid on the server until it naturally expires (30 minutes by default) — if someone had a copy of it, clicking sign-out wouldn't stop them from using i
t. There's already a `Session` table in `models.py` built for exactly this (token, expiry, IP, device info) — it's just never written to, on signin or anywhere else. That's the gap: sign-out currently only
 happens in the browser, never on the server.

**What you're building:** Either make it real — write a session row on login, check it's still valid on every request, actually delete it on sign-out — or, if the group decides it's not worth it, cleanly remove the unused table

**Why it matters:** Right now, if a login token ever leaked, there's no way to shut it down early — it just works until it naturally expires

**Files that might help:**
- `backend/models.py` — the `Session` model (already defined, unused)
- `backend/routers/auth.py` — signup / signin / signout logic
- `backend/dependencies.py` — `get_current_user`, the check every protected page/request goes through
- `backend/security.py` — how the login token is created and checked
- `frontend/components/Settings.tsx` — has a "Danger Zone" section already, a natural home for a "sign out everywhere" button if you go for the stretch goal
- `frontend/lib/auth.ts` — shows how the token is stored/sent from the browser, useful context

**Gotchas:**
- There's already an unrelated `/api/sessions` set of routes in `chat.py` — but those are for **chat history**, not login. Don't confuse the two, and pick a clearly different name/path for anything you add here (e.g. `/api/auth/sessions`).
- `get_current_user` gates literally every protected page in the app — test with a spare/throwaway account, since a mistake here can lock everyone out at once.
- No need to build token refresh — "it expires naturally, and can be manually cut off early" is a perfectly good end state for this session.

**Questions:**
- *"What if we just delete the unused table instead?"*
---

## Task 3 — Build a "Document Library" tool

**Problem:** All our legal and planning text lives as chunks in two database tables. Right now the only way to see what's actually loaded — or to add or remove something — is a raw API call or poking around in Neon directly. There's no simple page for "what do we have, add something new, remove something old."

**What you're building:** A small internal page — call it the **Document Library** (or Data Manager, whatever sticks) — with three pieces:
1. **A list** — every document/law currently loaded, and how many chunks each has.
2. **Add** — a simple form to load a new file in, reusing the ingestion logic that already exists (you're mainly building the missing front door, not the ingestion itself).
3. **Delete** — remove a document by name.

Most of the ingestion logic already exists on the backend; the list and delete pieces don't exist at all yet, and "add" only exists today as a raw API call with no proper form around it.

**Why it matters:** As more real documents get added over time, this becomes the difference between "we can see and manage what's in our system" and "we're guessing based on database queries."

**Files that might help:**
- `backend/routers/chunks.py` — the existing ingest endpoints to build "add" around, and where you'd add new "list"/"delete" endpoints
- `backend/schemas.py` — `ChunkIngestRequest`, including the hardcoded default name mentioned below
- `backend/models.py` — `DocumentChunk` / `LawChunk`, the table shapes you're listing
- `backend/chunking/ingest_pipeline.py` — what actually happens when a document is ingested (context — you shouldn't need to change this)
- somewhere new under `frontend/` — for the actual page/UI

**Gotchas:**
- The ingest API has a **leftover hardcoded default document name** (`"kristineberg_detaljplan"`) from some early testing. If your "add" form doesn't require a name, it'll silently fall back to that default — and since re-ingesting under an existing name deletes the old chunks first, that's a real "oops, deleted the wrong thing" risk. Make the name field required.
- Since we're on Neon, there's likely already real data — be a little careful testing "delete" against it; maybe test against a throwaway document name first.

**Questions:**
- *"Should this replace the existing ingestion scripts?"*
- *"Does this need login?"*
---

## Task 5 — Let people read the actual paragraph an answer came from

**Problem:** Today, when the chat answers a question, it shows a **Sources** list at the bottom — just document/law *names* (like "PBL" or "vallentuna_detaljplan"). It doesn't show the actual paragraph of text that was matched and used to write the answer. So you can't currently check "did it actually say that, or is the bot making it up?"

**What you're building:** Make a source in that list clickable, and show the real retrieved text when you click it — right there in the chat. The system already knows exactly which chunks it used (it has to retrieve them to answer at all); that information is just being thrown away before it reaches the screen.

**Why it matters:** This is the difference between "trust the bot" and "verify what the bot actually read." Exactly the kind of check you'd want before believing an answer about, say, a specific height restriction.

**Files that might help:**
- `backend/agents/base.py` — `_retrieve_debug_rows_from_embedding()` already computes source, chunk content, and a preview for every match; it's currently only written to logs
- `backend/routers/chat.py` — the streaming logic that sends "thinking"/"tool_call"/"tool_result" updates to the frontend as it works, and `_format_sources()` which builds today's name-only source list
- `frontend/components/Chat.tsx` — look at `AssistantTelemetry`, `CollapsibleMetaSection`, and `getToolTraces()` — this is where sources are currently rendered as plain names; you'd extend this to show actual chunk text when clicked

**Gotchas:**
- Right now the streaming updates only send a *count* ("5 chunks found"), not the actual text — someone needs to find where that count gets built and pass the real content through instead (or alongside it).
- Keep this to *displaying* what was retrieved — don't change how retrieval or the answer itself works.

**Questions:**
- *"Is this the same as a database-browsing tool?"*
- *"Shoul we show every retrieved chunk, or just the ones that seem relevant?"*
