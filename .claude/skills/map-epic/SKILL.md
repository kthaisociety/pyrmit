---
name: map-epic
description: Takes a goal, files it as an epic skeleton issue or picks an existing one, then breadth-first grills it and publishes its tasks, research, and prototypes as GitHub sub-issues with native blocking. Re-run to graduate fog.
disable-model-invocation: true
---

# map-epic

Take a goal from the user, file it as an `(N) [epic]` skeleton issue, or let them pick an epic that already exists, and turn its goal into a GitHub-native **map**. The epic issue holds the destination and a running decision log, and its **issues**, native GitHub sub-issues typed `task`, `research`, or `prototype`, are wired together with native blocking. Everything reachable now gets grilled and published in this session; anything not yet specifiable is written down as fog and revisited on a later run.

This skill owns every epic-linked issue end to end. `new-issue` is only for standalone issues with no epic. Invoke the `grilling` skill for interview mechanics throughout.

Read these at runtime. Do not assume their contents from this document:

- **`../new-issue/issue-shapes.md` is the single source of truth** for issue body shape, title format, labels, branch slug, the AI disclaimer, gh preflight, the publish loop, and native wiring. Read it before Step 1.
- `template_epic_issue.md` holds the epic issue body, with Destination, Notes, Decisions so far, and Not yet specified.

---

## Step 1: gh preflight

Run the **gh preflight** from `issue-shapes.md`, including its remediation steps.

---

## Step 2: Load epics and pick or create one

```
gh issue list --state all --limit 500 --json number,title,state
```

Keep the issues whose title starts with a `(N) [epic]` token and parse `N` from each. A `state` of `CLOSED` means the epic is done, and `OPEN` means it is live.

The argument decides the path:

- **A number**, as in `/map-epic 2`. Match it against that list. If it isn't found, list the available epics and ask the user to pick one or describe a new goal.
- **A goal in words**, as in `/map-epic add geological data so the verdict covers ground conditions`. That phrase is the seed of a **new epic**. Go to Step 2b.
- **Nothing.** List every epic with its number, name, and open or closed state, and ask the user to pick one or describe a new goal. If no epics exist, skip the list and ask for the goal.

Do not proceed until an epic is selected or a new goal is in hand. A selected existing epic goes to Step 3.

### Step 2b: Build the skeleton

Runs only for a new goal. The output is one epic issue whose **Destination** is settled, and nothing else.

**Read first.** `CONTEXT.md`, every file in `docs/pcr/`, and the Destination line of each open epic. The destination is written in the project's own domain language, so use its terms.

**Grill the destination**, via the `grilling` skill, until it is one sentence naming an **observable outcome**: what someone can do, or what the system does, once the epic is closed. Not a task list and not an implementation. Two checks belong in this grill:

- **Is it epic-sized?** If the goal fits one issue, say so, point at `/new-issue`, and stop. An epic earns its keep when it needs several issues that only make sense together.
- **Is it already covered?** If an open epic's Destination already contains this goal, offer that epic instead. Mapping into an existing epic beats filing a near-duplicate.

**Number it.** Take `max(N) + 1` over every epic loaded above, open and closed, starting at 1 if none exist. Numbering is append-only. Never reuse a number, including one whose issue was closed.

**Render** `template_epic_issue.md`:

- **Destination** is the settled sentence, verbatim.
- **Notes**, **Decisions so far**, and **Not yet specified** each get the placeholder line `_Not yet charted._`.

**Publish** through the publish loop in `issue-shapes.md`, preview and approval included, with the title `(N) [epic] <short name>`. The epic issue takes no label.

```
gh issue create --title "(N) [epic] <short name>" --body "$(cat ...rendered...)"
```

**Existing epics are immutable.** Never rewrite another epic's Destination. If the user wants one changed, they edit the issue directly.

A freshly filed epic has no sub-issues, so skip Step 3 and go straight to charting mode at Step 4.

---

## Step 3: Detect mode, charting or graduating

Charting or graduating depends on whether the epic issue already has sub-issues:

```
gh api repos/{owner}/{repo}/issues/<epic-issue-number>/sub_issues --jq 'length'
```

- **Zero sub-issues** means **charting mode**, Steps 4 through 8.
- **One or more** means **graduating mode**, Step 9. The epic is already charted, so this run looks for newly-resolved issues and graduates fog.

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
- **fog.** You can sense it's coming but can't state it precisely yet. Don't force it into an issue. Write a loose one-line sketch instead.

Also propose **blocking edges**, meaning which items can't be worked until another closes. Don't ask the user to enumerate dependencies from scratch.

**One-issue sizing** for `task` items: each should be a thin vertical slice, independently demoable as a single GitHub issue. Split anything bigger, and merge anything that always ships together.

### Step 6: Batch confirm gate

Show the user, together:

1. The full item list, each with its type, meaning `task`, `research`, or `prototype`, and a one-line description.
2. The proposed blocking edges, in `X blocked by Y` form.
3. The fog sketch, meaning items not yet filed as issues.

Support natural-language edits, including retyping a fog line into a real issue or the reverse. Ask: **"Publish this batch?"** Do not create anything until the user confirms.

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

Capture the issue's numeric database id, per `issue-shapes.md`.

### Step 8: Publish issues

Epic issues take the `epic:` label scope.

**Research and prototype issues** use the question issue shape. Publish the whole batch directly, with no further per-item discussion, since the question was already agreed at the Step 6 gate.

**Task issues** use the task issue shape and are processed **one at a time**, sequentially. For each:

1. Draft the Goal, the Expected behaviour, the Out of scope, and the Branch slug from what the breadth-first grill already surfaced.
2. Run the publish loop's preview and edit cycle. Spend the discussion on expected behaviour, and keep it user-visible per `issue-shapes.md`.
3. Assign the `(N.M)` id by taking `max(M) + 1` over the `(N.M)` ids already in the epic issue's sub-issue titles, starting at 1 if none exist. This is append-only. Never renumber or delete an existing issue.
4. Judge it against `issue-shapes.md`'s **autopilot criteria** and state the label, `epic:task` or `epic:autopilot`, with one line of reasoning. The user confirms or overrides.
5. Publish with the title `(N.M) [feature] <short title>`. Every task defaults to feature-shaped, so do not ask feature vs bug here.
6. Move to the next task issue.

**Wire every published issue** as a sub-issue of the epic issue, and wire each confirmed blocking edge, per `issue-shapes.md`'s native wiring.

---

## Graduating mode

### Step 9: Detect resolved issues and graduate fog

1. List the epic issue's sub-issues and find any that are **closed** but not yet reflected in its Decisions so far section.

   ```
   gh api repos/{owner}/{repo}/issues/<epic-issue-number>/sub_issues --jq '.[] | {number, title, state, labels: [.labels[].name]}'
   ```

2. For each newly-closed issue, read its closing comment or resolution, and append one line to **Decisions so far**:
   ```
   - [<issue title>](<url>): <one-line gist of the answer or outcome>
   ```
3. With these resolutions in hand, grill the user, via the `grilling` skill, on this question: **"Given this, what from Not yet specified is now specifiable?"** Fan out across the fog section only, not the whole epic again.
4. Whatever graduates goes through Step 8 unchanged, typing, publish flow, `(N.M)` ids, and wiring. Remove graduated lines from **Not yet specified**; anything still too vague stays in the fog.
5. Update the epic issue body with `gh issue edit <epic-issue-number> --body "..."`, carrying the refreshed Decisions so far and Not yet specified sections.

If nothing has closed since the last run, tell the user there's nothing to graduate yet and stop.

---

## Constraints

- **Never resolve `research` or `prototype` issues inline.** They're published open and picked up in their own separate sessions, such as a `/prototype` session. This skill only detects their closure on a later run.
- **GitHub is the only record of project state.** The epic issue's sub-issue list is the task list, and no local file mirrors it.
- **Main thread only.** No subagent dispatch.
