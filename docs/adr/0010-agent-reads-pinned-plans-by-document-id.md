# ADR-0010: The agent reads pinned plans by document id, from the corpus only

**Decision:** The agent's plan reading (`CorpusTools.read_plan` in `agentic/tools.py`) MUST take the document ids the pinned place's statement gives it and read them from the corpus store; it MUST NOT read the link table, the place snapshots, the plan registry or any other local file.

**Reason:** The pin and its plans are known only in the chat's request, while `CorpusTools` is one object shared by every request. The alternative was a tool bound to the run's pin that takes an aktbeteckning and looks its documents up in `place.plan_links`. It lost because it needs per-run state in the tools and makes every read depend on files on the install's disk, when the hosted corpus already holds the text.

**Consequence:** Which plans apply and which documents they have is settled once, in `place.profile`, and handed over as text in the pinned place's statement (`place.context`). A plan with no linked document cannot be read and is stated as not read. Moving the link table or the snapshots, or where they are read from, does not touch the tool.

**Scope:** `agentic/tools.py`, `CorpusTools.read_plan`; `place/context.py`, the plan lines of `place_context`

**Date:** 2026-11-05
