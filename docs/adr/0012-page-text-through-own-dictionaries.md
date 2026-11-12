# ADR-0012: Page text comes from the app's own dictionaries

**Decision:** Every user-visible text of the page MUST come from `useLanguage().t` (`frontend/lib/i18n.tsx`), with its Swedish and English wording in `frontend/lib/messages.ts`; the frontend MUST NOT add an i18n library or put the language in the URL.

**Reason:** next-intl was weighed and lost: it brings language routing and server-side message loading, and the page has two languages, no language in its URLs and only client components, so a library would add a dependency and a routing layer for what two typed dictionaries and one context do. Typing `sv` as a record of `en`'s keys makes a missing Swedish text a type error.

**Consequence:** A new text adds one key to both dictionaries and is read with `t`. A string literal shown to the user in a component outside the developer tools (benchmark, database and pipeline browsers, pipeline trace) is a breach. Texts the backend writes (the place card's notes and permits) are not in these dictionaries; see ADR-0013.

**Scope:** `frontend/app/`, `frontend/components/`, `frontend/lib/i18n.tsx`, `frontend/lib/messages.ts`

**Date:** 2026-11-07
