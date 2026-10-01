---
name: new-ticket
description: Beside the board, for standalone work no epic covers. Grills a ticket down to WHAT, never HOW, publishes it as a GitHub issue, and splits it into sub-issues if it is too big. For epic-linked work, use map-epic.
disable-model-invocation: true
---

# new-ticket

Grill the user into a single, well-scoped GitHub ticket covering **WHAT** changes, meaning user-visible behaviour and scope, and never **HOW**, meaning architecture, files, code, and tests. Publish via `gh`. Optionally split into vertical-slice sub-issues. Hand off to `/architect-ticket` for the HOW, or to `/autopilot-ticket` when the ticket qualifies.

The published body is deliberately thin. The grill is not. Everything the grill surfaces must land as **expected behaviour** or be consciously dropped.

Read the bundled files at runtime. Do not assume their contents from this document:

- **`ticket-shapes.md` is the single source of truth** for body shape, title format, labels, branch slug, the AI disclaimer, gh preflight, the publish loop, and native wiring.
- `subissue-splitting.md` holds the vertical-slice rule and the two-tier coverage check.

Read `ticket-shapes.md` and run its **gh preflight** before any grilling.

---

## Invocation

Two modes:

1. **Cold start.** The user invokes with no extra text. Open with the first grill turn, feature vs bug.
2. **One-liner seed.** The user invokes with a short phrase such as "users can sign up with email". Treat that phrase as **the seed of the grill, not a finished ticket body.** Every grill topic still runs.

If the user's phrase looks epic-linked, meaning it references an epic task, a `(N.M)` id, or an `(N) [epic]` issue, point them at `/map-epic` instead. This skill does not resolve epic refs.

Do **not** synthesise a ticket from prior conversation context.

---

## First grill turn, feature vs bug

The first question is always: **"Is this a feature or a bug?"** Ask once. Do not infer.

The answer picks the **grill agenda** below and the type prefix on the published title. It does **not** change the body shape or the label.

---

## The grill, WHAT only

You are a developer grilling a product owner about product requirements. Invoke the `grilling` skill for the interview mechanics, and work the agenda one topic at a time.

**Feature agenda:**

1. Problem and motivation: the user-visible problem, and why now.
2. Target user or actor: who triggers or benefits.
3. Trigger or entry point: how the user reaches the behaviour.
4. Expected behaviour: the happy path end-to-end, from the user's side.
5. Edge cases and failure modes: missing, invalid, or conflicting inputs, and operations that can't complete.
6. Dependencies on existing functionality: behaviours this relies on or disturbs.
7. Out of scope: what might look related but isn't.

**Bug agenda:**

1. Symptom: what the user sees go wrong.
2. Reproduction steps: the minimal sequence that triggers it.
3. Expected vs actual, at the point of failure.
4. Scope of impact: who hits it, how often, and whether it blocks or annoys.
5. Conditions: user state, surface, and inputs under which it reproduces.
6. First seen or regression: always broken, or a regression from a known-good state.
7. Workarounds known: what users can do today, or "none known".
8. Out of scope: related bugs or refactors this fix won't touch.

**Drive every topic to an outcome.** For each answer, ask *"what can someone do, or stop having to do, once this ships?"* and write that. A topic that leaves neither an expected-behaviour line nor an Out-of-scope line has left nothing in the ticket, so say so and resolve it before moving on. Every bug ticket carries one standing line: the reproduction steps no longer produce the symptom.

**Stay outside the code when you write it down.** "Expired sessions send the user back to login" belongs here. "`refresh_token` raises `AuthError` on an expired token" does not, however true it turns out to be. If you catch yourself reaching for a symbol name to say it precisely, the precision belongs to `architect-ticket`.

**Never settled in this ticket.** These are HOW topics, and they defer to `architect-ticket`:

- File paths, module names, function or class names, function signatures
- Schema design, database tables, API contract shapes
- Test names, test file locations, what any test asserts
- Rollout order, migration strategy, feature flags
- Library, dependency, or tooling choices

**Read whatever you need during the grill.** `grilling`'s explore-before-asking rule applies in full here, **source files included**. The WHAT/HOW line governs what lands in the ticket, not what you're allowed to read. If exploration turns up a HOW decision the ticket seems to need, that's a signal for `architect-ticket`, not a section to add here.

---

## Propose-and-confirm split

When the full WHAT-grill is complete, **you** decide whether this is one ticket or several. Do **not** ask the user upfront which it will be.

**Split** when the expected behaviour spans separable user-visible concerns and each slice is independently demoable end-to-end. **Keep as one** when the behaviours interlock, so no slice ships without the others.

State your recommendation with brief reasoning, either "one ticket, no split" or "N sub-issues". Then **wait for confirmation or pushback** before moving on. If the user pushes back, iterate until they confirm. The sub-issue list itself is proposed under Publishing, once the parent is filed.

For the split path, read `subissue-splitting.md` and follow its vertical-slice rule and two-tier coverage check.

---

## Publishing

Follow `ticket-shapes.md`'s **publish loop** for every ticket, parent and sub alike, and its **native wiring** for parentage and blocking.

Before the first preview of each task ticket, judge it against `ticket-shapes.md`'s **autopilot criteria** and state the label you'd give it, `ticket:task` or `ticket:autopilot`, with one line of reasoning. The user confirms or overrides. Sub-issues are judged one at a time, since a parent that needs the architect can have a sub-issue that doesn't.

For a split, publish **parent first**, so sub-issues have something to attach to:

1. Preview, approve, and publish the parent. Capture its number, URL, and numeric id.
2. **Propose the sub-issue list.** Show every sub-issue as title plus one-line scope, plus the proposed blocking edges in `X blocked by Y` form. Iterate with the user, adding, removing, renaming, re-scoping, and re-wiring, until they approve.
3. Re-run the two-tier coverage check on the approved list.
4. Publish each sub-issue in dependency order, one full publish loop each, wiring it to the parent as it lands.
