# Sub-issue splitting guide

Read this once you have proposed a split.

## Vertical-slice rule

Each sub-issue must be a **vertical slice**, meaning an end-to-end, demoable change from the user's point of view. A slice delivers a real behaviour the user can see, not a layer of internals.

- Good: "User can sign up with email", which touches whatever it needs to, end-to-end.
- Bad: "Add the database table", "Add the API endpoint", "Add the form". These are horizontal layers, not slices, and none of them is demoable on its own.

If a proposed sub-issue cannot be demoed end-to-end without one of the others shipping first as a hard prerequisite of *the same behaviour*, it is probably a layer, not a slice. Either merge it back into the parent or restructure the split.

## Filling the body

Every sub-issue uses the task ticket shape, the same as the parent. See `ticket-shapes.md`.

Per sub-issue:
- **Goal** describes the slice end-to-end at behaviour level, with no file paths and no code.
- **Expected behaviour** is user-visible outcomes specific to this slice.
- **Out of scope** names the neighbouring slices this one does not deliver.

Parentage and blocking are **not** body sections. They are wired natively via the GitHub API. See *Native wiring* in `ticket-shapes.md`.

## Two-tier coverage check

Before publishing any sub-issues, run a **two-tier coverage check**. Both tiers must pass.

### Tier 1, per-slice coverage

For each sub-issue on its own:
- Every expected-behaviour line in that sub-issue belongs to this slice.
- The sub-issue's own expected behaviour fully covers the slice it claims to deliver, leaving nothing inside the slice unstated.

### Tier 2, systemic coverage

Across the whole set of sub-issues:
- The **union** of all sub-issue expected behaviour covers the **full** expected behaviour of the parent issue.

If Tier 2 fails, either expand an existing sub-issue, add a new sub-issue to absorb the gap, or pull the missing behaviour back into the parent and re-evaluate whether the split still makes sense.
