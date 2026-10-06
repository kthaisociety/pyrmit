---
name: pro-con
description: Weigh the pros and cons of a decision, design, or option set and commit to a recommendation.
disable-model-invocation: true
---

# pro-con

Weigh the pros and cons of whatever the user is deciding, whether that's a design choice, a tool, a yes-or-no call, or a topic they want clarified, and land on a committed recommendation.

Fill `template_output.md` exactly; it owns the output shape so every run looks the same. Read it at runtime, and do not assume its contents from this document.

## Steps

1. **Frame it.** State the decision in one line, stripping any lean out of it, so "should I adopt X?" becomes "X vs not-X". Name the options being weighed; a single subject means adopt it or don't. If it's unclear what's being compared, ask once, then proceed. Completion: a neutrally-worded question plus an explicit option set.
2. **Steelman each option.** Before tagging anything, make the strongest honest case for every option, including the one you expect to lose, spending equal effort on each. Completion: each option has a best-case argument you'd defend.
3. **Weigh each item.** For every option, list pros and cons per the template, tagging each with impact: **[High]** for a dealbreaker or decisive win, **[Med]**, or **[Low]** for a nitpick. Impact is how much the item moves the decision, not how likely it is. Completion: every option has both lists, every item tagged.
4. **Land the verdict.** Recommend one option in one line, justified by where the weight lands, never by item count. A single **[High]** dealbreaker outranks a pile of **[Low]** pros. Completion: a named recommendation whose rationale cites the deciding items.

## Rules

- **No false balance.** Don't invent a con to match every pro. If one option dominates, say so. An honest lopsided list beats a fake-symmetric one.
- **No sycophancy.** A visible user lean is the thing to stress-test, not confirm. Weigh the option they favor exactly as hard as the one they don't.
- **Adapt the depth to the stakes.** A throwaway choice gets a few bullets; an architectural one gets thorough legwork. Same structure either way.
- Render the analysis in chat. Write a file only if the user asks.
