---
name: brainstorming
description: Grill a raw idea until it dies or holds, then name the station that should take it.
disable-model-invocation: true
---

# brainstorming

This skill ends with a shaped idea and the one station that should take it next, or a dead idea and the reason it died.

The instrument for shaping an idea is trying to kill it. Hunt for where it falls apart, then either adapt it to survive that or conclude it can't be. Treating an idea as sound because the user likes it is the failure this skill exists to prevent, so the grill argues against the user by default and hunts the break rather than the confirmation.

Size is not a factor. A one-line refactor and a brand-new product run the same loop; they differ only in how long they take to exhaust and where they route at the end.

## 1. Grill to kill

Run `/grilling` on the idea. That skill owns the interview mechanics.

Three things this grill does that a plain grill does not:

- **Check, don't ask.** An assumption you can verify is not a question for the user. Read the code, run the thing, search the web for whether it already exists. Evidence kills ideas that argument only bruises. Rank it: the repo first, then `docs/pcr/`, `docs/adr/` and `CONTEXT.md`, then the web, and only for prior art and buy-versus-build.
- **Argue its death.** At least once, make the strongest honest case for not doing this at all: do nothing, buy it instead, delete the code rather than extend it, or live with the problem. Press the case, and do not raise it and move on.
- **Reshape on every break.** A gap that surfaces is the work. Adapt the idea to close it and keep grilling the adapted version. Most of a run is this loop, and the shaped idea it produces is the deliverable.

There is no fixed set of angles. Follow whatever the last answer exposed, and attack where the idea is weakest rather than where it is easiest to discuss.

Completion: **exhausted**, meaning you cannot produce a question whose answer would change the verdict, and no assumption the verdict rests on is still unchecked. Not a topic count, and not the point where the user sounds convinced.

## 2. Verdict

Binary. State it outright, in the user's face, before anything else.

- **Killed.** One line for what killed it, plus what would have to become true to revive it. No route. Stop here.
- **Holds.** One paragraph of concrete functionality: what it does, what changes observably, and what it deliberately does not cover. This is the surviving idea, not the one that walked in.

No hedged third outcome. If it half-holds, the half that holds is the idea and the rest is out of scope. Say so in the paragraph.

## 3. Propose what to document

The grill usually settles something worth keeping. Propose it, and never write silently:

- A rule that constrains future work becomes a **new** ADR in `docs/adr/`, per [`../architect-ticket/RECORD-FORMAT.md`](../architect-ticket/RECORD-FORMAT.md), which you read at runtime. Existing records are not yours to touch; a PCR in the way goes to the route table below.
- A term the grill pinned down or renamed becomes an entry in `CONTEXT.md`.

Propose nothing when the grill settled nothing durable; a killed idea can still be worth an ADR recording why not.

Write only on approval.

## 4. Route

Only if it holds. Name one route and state the reason, so the user can override it:

| The surviving idea | Route |
|---|---|
| Is blocked by a convention recorded in `docs/pcr/` | `/challenge-pcr`, and nothing else happens until that session does |
| Is one change with one test suite and no architecture question | Implement inline, in this session, once the user says go |
| Is one coherent behaviour, and no epic covers it | `/new-ticket` |
| Is a goal that has to be sliced into several tickets | `/map-epic` |
| Is a whole new product, or the repo has no `CONTEXT.md` or epic issues yet | `/project-planning` |

Route to the smallest thing that fits. "This is one file and one test, no ticket earns its keep here" is a complete justification.

Every route except the inline row is user-invoked, so you cannot start it and must not try. Name it and stop; the routed skill runs its own grill on the surviving idea. Inline still waits for the user to say go.
