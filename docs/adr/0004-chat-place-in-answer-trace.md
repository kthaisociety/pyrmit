# ADR-0004: The chat's pinned place lives in the answer's trace

**Decision:** The place a question was asked about MUST be stored as the "place" pipeline event of the assistant message's trace, and MUST NOT be stored in new columns of `chat_sessions` or `chat_messages`.

**Scope:** `backend/routers/chat.py`, `backend/place/context.py`, `frontend/components/Chat.tsx`

**Reason:** New `place` columns on `chat_sessions` and `chat_messages` were weighed and lost. The tables live in the team's shared Neon database, and the backend adds missing columns at every startup, so one feature branch would change the schema under everyone's running backends. Every streamed answer already saves a JSONB trace that the history endpoint returns, and that trace is where the inspector reads what an answer was based on.

**Consequence:** A chat session's place is the place of its latest answer that had one; a pin moved without asking a question is not saved. Only `/api/chat/stream` saves traces, so only the streamed chat keeps the place. The frontend restores the chip from the latest "place" event of the history, and the trace stores the profile without geometries to stay small.

**Date:** 2026-10-25
