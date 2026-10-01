---
name: project-planning
description: First station on the board. Grills a repo to mutual understanding, proposes vertical-slice epics, then writes CONTEXT.md and files an epic skeleton issue per epic. For slicing one epic into tickets, use map-epic.
disable-model-invocation: true
---

# project-planning

A roadmap-level planning session inside an existing git repo. Everything runs in this session: conversation, `gh` calls, and file edits. No subagent dispatch.

**GitHub is the only record of project state.** This skill writes no plan file and tracks no status markers. An epic exists because its `(N) [epic]` issue exists, and it is done because that issue is closed.

---

## Input

The skill is invoked with an optional one-sentence project seed. If none was provided and no `CONTEXT.md` and no epic issues exist, ask the user for one before grilling. If either already exists, skip this step.

---

## Git-repo guard

Before doing anything else, run:

```
git rev-parse --is-inside-work-tree
```

If the command fails (non-zero exit), print exactly:

> `project-planning must be run inside a git repository. Exiting, no files written.`

Then **stop immediately. Write nothing.**

---

## gh preflight

Run the **gh preflight** from `../new-ticket/ticket-shapes.md`, a skill-relative path, including its remediation steps. Do not proceed until it passes or the `--repo` fallback is captured. This skill files issues, so `gh` is a hard requirement, not a nicety.

---

## Load existing epics

Read the current epic list from GitHub:

```
gh issue list --state all --limit 500 --json number,title,state
```

Keep the issues whose title starts with a `(N) [epic]` token, and parse `N` from each. A `state` of `CLOSED` means the epic is done, and `OPEN` means it is live. This list is the project's status.

---

## Adaptive grill

Invoke the `grilling` skill for the interview mechanics; this section supplies only the agenda and its termination condition.

**Read first.** Before asking anything, read `CONTEXT.md` at the project root if it exists, every file in `docs/pcr/` if it exists, plus the epic list loaded above and the Destination line in each open epic's body. Summarize your current understanding back to the user in two to four sentences: what the project is, who it's for, what's already planned, and what's already done (closed epics). Be explicit about what you do and do not yet know.

**Ask only on gaps.** Do not run a fixed N-question script. Ask only where understanding is genuinely absent or unclear; if `CONTEXT.md` and the epic issues already answer an area, do not re-ask it.

Areas to cover (ask only where gaps remain):

1. **Problem statement.** What is this project solving?
2. **Primary user or consumer.** Who uses it?
3. **Success criteria.** One observable behavior that defines done.
4. **Scope boundaries.** What is explicitly out of scope?
5. **Domain language.** 3-6 nouns that recur in code and UI.
6. **Project conventions.** The choices every ticket will have to live inside: language and stack, the libraries a file may import, naming, comment convention, object-oriented or not, test runner and layout. Read the repo before asking; an existing codebase already answers most of these, and a `docs/pcr/` that exists answers them all. Recommend an answer for each gap and let the user correct it. Each one settled becomes a PCR under Write artifacts.

**Termination.** Stop the grill once you can fill in all six areas. Announce:

> `Understanding captured. Proposing epic breakdown.`

Proceed directly to Epic breakdown.

---

## Epic breakdown

Propose an epic breakdown as a numbered list. Each epic must have:

- An epic number `(N)`, as in `Epic 1`
- A one-sentence **epic goal**, meaning the observable outcome at the end of the epic

Epics are **vertical slices**. Each delivers working, demonstrable functionality end-to-end, not a horizontal layer. Don't make "Epic 1 = backend" and "Epic 2 = frontend".

**Numbering is append-only.** Take `max(N) + 1` over the epic issues already loaded, starting at 1 if none exist. Never renumber or reuse a number, including one whose issue was closed.

**Existing epics are immutable, open and closed alike.** Do not re-propose them, and do not rewrite their goals; `map-epic` and the tickets under them depend on that goal holding still. Propose only new epics. If the user wants an existing epic's goal changed, tell them to edit the issue directly.

After proposing the breakdown, ask:

> `Does this epic breakdown look right? Confirm to write, or tell me what to change.`

**Wait for explicit user confirmation before writing anything.** This is the confirm gate. No file is written and no issue is filed before it.

---

## Write artifacts

On confirmation, do all three of the following, in order. Never create files outside this list.

### CONTEXT.md

If `CONTEXT.md` does not exist, create it at the project root with two sections. **Language** holds one entry per domain term: a `**Term**:` line, the definition, then an `_Avoid_:` line naming the synonyms the project doesn't use. **Relationships** is a bullet list of how those terms connect, each bullet bolding the terms it links.

If `CONTEXT.md` already exists, update it in place: add or revise Language entries and Relationships bullets to reflect the current domain understanding. Match the existing style exactly.

**Out of scope lives here**, as a short `## Out of scope` section listing each exclusion and why. It is prose about the project's boundaries rather than trackable state, so it belongs beside the language, not in an issue.

### PCRs

One file per convention settled in area 6, written to `docs/pcr/NNNN-slug.md` per `../architect-ticket/RECORD-FORMAT.md`, a skill-relative path, which you read at runtime. Its PCR tests decide what gets a file: the convention has to bind the whole project and be phrasable as MUST or MUST NOT. Take the next free number. **Never edit a PCR that already exists**; that takes a `/challenge-pcr` session. A convention the grill re-confirmed unchanged writes nothing.

### Epic skeleton issues

File one issue per **new** epic, in ascending `N` order. Nothing is filed for an epic that already has an issue.

Render `../map-epic/template_epic_issue.md`, a skill-relative path:

- **Destination** is the epic goal, verbatim as confirmed at the gate.
- **Notes**, **Decisions so far**, and **Not yet specified** each get the placeholder line `_Not yet charted. Run /map-epic on this epic._`

The skeleton stops there. Task breakdown, fog, and decisions are `map-epic`'s job, and this skill does not guess at them.

```
gh issue create --title "(N) [epic] <epic name>" --body "$(cat ...rendered...)"
```

Preview every rendered title and body in chat before the first `gh issue create` call, and publish only on explicit approval, per `ticket-shapes.md`'s publish loop.

Output the `CONTEXT.md` path, every PCR written, and every epic issue URL after writing.

---

## Constraints

- No git init and no `gh repo create`. This skill assumes an existing git repo, enforced by the guard above.
- No artifact scaffolding, meaning no README, no `.gitignore`, no agent instruction file, and no license file. Those belong to a scaffolding skill.
- A leftover `project_plan.md` or similar status file from an older run is not updated. Say it's there and offer to delete it.
- No per-task slicing. The epic issue is a skeleton. Do not break epics into sub-issues here, and defer that entirely to `map-epic`.
- Main thread only. No subagent dispatch.
