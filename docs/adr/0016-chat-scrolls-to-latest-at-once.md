# ADR-0016: The chat scrolls to its latest message at once

**Decision:** The chat's automatic scroll to its latest message MUST be instant (`behavior: 'auto'`), never smooth.

**Reason:** Unknown beyond the comment. Found as a comment in `frontend/components/Chat.tsx`, quoted:

> At once, not smoothly: a smooth scroll still under way would read as the reader having scrolled up

**Consequence:** The chat decides whether to follow new text from where the reader is in the conversation (issue #89). A smooth scroll that is still moving when the next streamed text arrives leaves the view short of the end, so the chat would stop following its own answer. Making the scroll smooth again needs another way to tell the reader's scrolling from the chat's own.

**Scope:** `frontend/components/Chat.tsx`, `Chat`'s `scrollToBottom`

**Status:** found

**Date:** 2026-11-12
