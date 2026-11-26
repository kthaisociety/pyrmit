# ADR-0026: A claim check result arrives on the answer's own stream

**Decision:** The chat MUST keep reading an answer's stream until its claim check result has arrived, also after the next question is sent, and each stream MUST write only to its own answer; the chat MUST NOT drop the stream at the start of the check and fetch the result by reloading the session.

**Reason:** The next question can be sent as soon as an answer's text is finished (#137), so the result of its check can arrive while a later answer is streaming. Dropping the stream when the check starts and polling the saved session, as for an answer the reader left, was weighed and lost: the saved text can lag the streamed one by up to two seconds, so the reload could show a cut answer, the result would come up to two seconds late for a check that takes under one, and a reload replaces the whole conversation, the later answer being written included.

**Consequence:** Several streams can be open in one chat at once: the latest, and earlier ones whose answers are still being checked. A stream finds its answer by its place in the conversation, never as "the last message", and opening another chat ends all of them. Sending is held back only while an answer's text is being written, or while an answer the reader came back to is not finished: that one is still followed by reloading, which is why nothing can be sent beside it. A stream cut before its end while another is open must not reload the session at once; its answer waits as a background answer until the other stream has ended.

**Scope:** `frontend/components/Chat.tsx`, `Chat`'s `send`

**Date:** 2026-11-26
