# ADR-0011: The source panel gets supporting sentences beside the citation

**Decision:** `SourceViewer` MUST receive the claim check's supporting sentences as its own `supporting` prop (chunk_id to sentences), and `Citation` / `CitedChunk` MUST NOT carry them.

**Reason:** `Citation` is what the backend sends in the `citations` pipeline event, and the supporting sentences come from a different event (`claim_check`), derived in the chat. Adding `supporting` to `CitedChunk` was weighed and lost: it would mix a frontend-derived field into the backend's shape, and the Benchmark and Database views, which build their own `Citation`s without a check, would have to reason about a field that is never theirs.

**Consequence:** Whoever opens the panel with underlining (today only `Chat.tsx`) derives the map from the answer's `claim_check` event and passes it beside the citation. The Benchmark and Database views keep passing a `Citation` alone and show no underline. A change that wants underlining elsewhere passes `supporting` too, rather than widening `Citation`.

**Scope:** `frontend/components/SourceViewer.tsx`, `SourceViewer` and `Citation`

**Date:** 2026-11-12
