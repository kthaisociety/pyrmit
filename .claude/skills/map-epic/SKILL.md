---
name: map-epic
description: Breadth-first grills one epic skeleton issue and publishes its tasks, research, and prototypes as GitHub sub-issues with native blocking. Re-run to graduate fog.
disable-model-invocation: true
---

# map-epic

Let the user pick one of the repo's `(N) [epic]` issues, filed as a skeleton by `project-planning`, and turn its goal into a GitHub-native **map**. The epic issue holds the destination and a running decision log, and its **tickets**, native GitHub sub-issues typed `task`, `research`, or `prototype`, are wired together with native blocking. Everything reachable now gets grilled and published in this session; anything not yet specifiable is written down as fog and revisited on a later run.

This skill owns every epic-linked ticket end to end. `new-ticket` is only for standalone tickets with no epic. Invoke the `grilling` skill for interview mechanics throughout.

Read these at runtime. Do not assume their contents from this document:

- **`../new-ticket/ticket-shapes.md` is the single source of truth** for ticket body shape, title format, labels, branch slug, the AI disclaimer, gh preflight, the publish loop, and native wiring. Read it before Step 1.
- `template_epic_issue.md` holds the epic issue body, with Destination, Notes, Decisions so far, and Not yet specified.

---

## Step 1: gh preflight

Run the **gh preflight** from `ticket-shapes.md`, including its remediation steps.

---

## Step 2: Load epics and select one

```
gh issue list --state all --limit 500 --json number,title,state
```

Keep the issues whose title starts with a `(N) [epic]` token and parse `N` from each. If none exist, stop and tell the user to run `/project-planning` first.

**If an epic number `N` was passed as an argument**, as in `/map-epic 2`, match it against that list. If it isn't found, list the available epics and ask the user to pick.

**If no argument was passed**, list every epic with its number, name, and open or closed state, then ask the user to pick one.

Do not proceed until an epic is selected.

---

## Step 3: Detect mode, charting or graduating

Charting or graduating depends on whether the epic issue already has sub-issues:

```
gh api repos/{owner}/{repo}/issues/<epic-issue-number>/sub_issues --jq 'length'
```

- **Zero sub-issues** means **charting mode**, Steps 4 through 8.
- **One or more** means **graduating mode**, Step 9. The epic is already charted, so this run looks for newly-resolved tickets and graduates fog.

---

## Charting mode

### Step 4: Read the destination

Read the epic issue body with `gh issue view <epic-issue-number> --json body`. Extract and display its **Destination** line, which is the epic goal.

### Step 5: Breadth-first grill

Grill the user, via the `grilling` skill, across the **whole epic scope at once**. Fan out, and don't go deep on any one item yet.

For each item that surfaces, classify it:

- **`task`.** A deliverable, ready to be spec'd now, meaning its goal and expected behaviour are already clear enough to state.
- **`research`.** An open question blocking a later task, such as an unknown API, a library choice, or an unclear fact, that a separate session should resolve.
- **`prototype`.** Needs a cheap concrete artifact, such as a UI sketch or a behaviour stub, before it can be spec'd, via a separate `/prototype` session.
- **fog.** You can sense it's coming but can't state it precisely yet. Don't force it into a ticket. Write a loose one-line sketch instead.

Also propose **blocking edges**, meaning which items can't be worked until another closes. Don't ask the user to enumerate dependencies from scratch.

**One-issue sizing** for `task` items: each should be a thin vertical slice, independently demoable as a single GitHub issue. Split anything bigger, and merge anything that always ships together.

### Step 6: Batch confirm gate

Show the user, together:

1. The full item list, each with its type, meaning `task`, `research`, or `prototype`, and a one-line description.
2. The proposed blocking edges, in `X blocked by Y` form.
3. The fog sketch, meaning items not yet ticketed.

Support natural-language edits, including retyping a fog line into a real ticket or the reverse. Ask: **"Publish this batch?"** Do not create anything until the user confirms.

### Step 7: Fill in the epic issue

The issue already exists. Re-render `template_epic_issue.md` over its skeleton body and edit it in place:

- **Destination** is the epic goal, carried over **verbatim** from the skeleton body. Never rewrite it.
- **Notes** are domain pointers or standing preferences relevant to this epic. Keep it short; empty is fine.
- **Decisions so far** is empty on first charting.
- **Not yet specified** is the confirmed fog sketch, one line per item.

Every section apart from Destination replaces its `_Not yet charted..._` placeholder line.

```
gh issue edit <epic-issue-number> --body "$(cat ...rendered...)"
```

Capture the issue's numeric database id, per `ticket-shapes.md`.

### Step 8: Publish tickets

Epic tickets take the `epic:` label scope.

**Research and prototype tickets** use the question ticket shape. Publish the whole batch directly, with no further per-item discussion, since the question was already agreed at the Step 6 gate.

**Task tickets** use the task ticket shape and are processed **one at a time**, sequentially. For each:

1. Draft the Goal, the Expected behaviour, the Out of scope, and the Branch slug from what the breadth-first grill already surfaced.
2. Run the publish loop's preview and edit cycle. Spend the discussion on expected behaviour, and keep it user-visible per `ticket-shapes.md`.
3. Assign the `(N.M)` id by taking `max(M) + 1` over the `(N.M)` ids already in the epic issue's sub-issue titles, starting at 1 if none exist. This is append-only. Never renumber or delete an existing ticket.
4. Judge it against `ticket-shapes.md`'s **autopilot criteria** and state the label, `epic:task` or `epic:autopilot`, with one line of reasoning. The user confirms or overrides.
5. Publish with the title `(N.M) [feature] <short title>`. Every task defaults to feature-shaped, so do not ask feature vs bug here.
6. Move to the next task ticket.

**Wire every published ticket** as a sub-issue of the epic issue, and wire each confirmed blocking edge, per `ticket-shapes.md`'s native wiring.

---

## Graduating mode

### Step 9: Detect resolved tickets and graduate fog

1. List the epic issue's sub-issues and find any that are **closed** but not yet reflected in its Decisions so far section.

   ```
   gh api repos/{owner}/{repo}/issues/<epic-issue-number>/sub_issues --jq '.[] | {number, title, state, labels: [.labels[].name]}'
   ```

2. For each newly-closed ticket, read its closing comment or resolution, and append one line to **Decisions so far**:
   ```
   - [<ticket title>](<url>): <one-line gist of the answer or outcome>
   ```
3. With these resolutions in hand, grill the user, via the `grilling` skill, on this question: **"Given this, what from Not yet specified is now specifiable?"** Fan out across the fog section only, not the whole epic again.
4. Whatever graduates goes through Step 8 unchanged, typing, publish flow, `(N.M)` ids, and wiring. Remove graduated lines from **Not yet specified**; anything still too vague stays in the fog.
5. Update the epic issue body with `gh issue edit <epic-issue-number> --body "..."`, carrying the refreshed Decisions so far and Not yet specified sections.

If nothing has closed since the last run, tell the user there's nothing to graduate yet and stop.

---

## Constraints

- **Never resolve `research` or `prototype` tickets inline.** They're published open and picked up in their own separate sessions, such as a `/prototype` session. This skill only detects their closure on a later run.
- **GitHub is the only record of project state.** The epic issue's sub-issue list is the task list, and no local file mirrors it.
- **Main thread only.** No subagent dispatch.
