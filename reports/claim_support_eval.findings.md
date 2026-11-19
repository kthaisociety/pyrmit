**What was run (2026-11-19).** The 15 Uppsala cases of `place/cases_answers.jsonl`, each asked with a map pin and
with the address typed in the question (no pin), 3 repeats each: 90 answers, 623 claims, all checked (no check
failed). The agent (`openai/gpt-6-luna`, `CHAT_MODE=agent`) read the hosted corpus (Neon branch `demo`: 93,298
Uppsala chunks with the documents of every plan in force, plus the 15 statutes). A second model
(`xiaomi/mimo-v2.6-flash`) then read 612 of the claims next to the full text of their sources. Cost: $0.82 for the
answers incl. the live check and the judge, $0.15 for the audit. The pilot (local disk corpus, 1,635 Uppsala chunks,
one repeat) is superseded by this run.

### Read this first: this run replaces a buggy one

A review of the first run (2026-11-18, `place-answers-20261118-185043-claim-support-neon.json`) found two bugs, fixed
before this run:

- **The pin answers lacked their plan texts.** In 24 of the 45 pin answers the place data said "the plan documents
  could not be read": `place.profile.hosted_documents` asked for `RETRIEVAL_BACKEND=local`, which an agent-mode setup
  does not need, and the bench cached the failed profile for all three repeats (the live chat in agent mode had the
  same gap on its map card). Now the agent's corpus counts and a profile whose plans were not read is never cached:
  0 of the 45 pin answers lack their plan texts, and 24 call `read_plan`.
- **The check silently dropped claims.** A citation written with the statute in its own bracket group
  (`[FBL 3 kap. 1 §][c:id]`) left brackets in the claim, which was then skipped (10 % of the address answers' cited
  stretches). Such a label now belongs to the citation group (`claim_check._CITATION_GROUP`): no stretch is skipped.

Against the buggy run the headline barely moves (pin 80 → 79 %, address 65 → 66 %), but its parts do: pin answers now
cite plan texts (25 claims, against 7) and fewer guessed site facts, and the dropped address claims are back.
Key points: pin 0.75 (0.78 before), address 0.43 (0.46); wrong-place answers: pin 2 of 45, address 4 of 45 (8 before).
Same agent, other answers: the ±3 points are within the run-to-run spread.

What the numbers below should be read with:

- **The pin-versus-address gap is partly the mix of sources.** With a pin the place data is a source of every claim,
  and 74 claims cite a chunk the place data handed in (95 % supported). Weighting each condition's shares by the
  other's mix of sources closes about half the gap (pin rates on the address mix: 74 %; address rates on the pin mix:
  74 %).
- **The intervals assume independent answers.** Bootstrapped by case instead (the three repeats of a case are alike):
  pin 73–84 %, address 60–72 %, paired difference +5 to +22 points. 12 of the 15 cases favour the pin (sign test
  p = 0.035); Björklinge, Trevlinge and Norby go the other way. The tables by kind, form, source and case have cells of
  8–30 claims and no intervals: read them as leads.
- **"Supported" means consistent with the cited chunk, not right for the plot.** A real plan of the neighbouring
  property passes; the judge's wrong-place count (above) is the only check of that.
- **The auditor is a weak reference.** It reads the first 6,000 characters of the place data (18 pin answers are
  longer), all claims of an answer in one prompt (39 unusable replies in the first pass, redone in a second), and it
  is the same model as the bench's judge, with no human labels.
- **The check is not consistent with itself.** The same strandskydd fee of 7,340 kr is judged in six claims (Dalby-Säby):
  the three pin claims pass, the three address claims are flagged.
- **Key points skip the answers that ask.** 8 address answers ask the user (3 as a question card, 5 as an answer that
  ends with a question) and carry no key-point score, so the address mean is over 37 answers.

### What the numbers say

- **The pin makes answers better sourced.** With a pin 79 % of the claims are supported, without it 66 %; every
  repeat shows the gap (pin 71 / 80 / 85 %, address 67 / 63 / 67 %). The pin also gives the content: key points 0.75
  against 0.43, place facts named 0.52 against 0.09.
- **Plan texts are now a source with the pin, and the weaker one.** Pin answers cite detaljplan documents in 25
  claims (72 % supported), address answers in 30 (50 %). Without a pin the agent still searches by street name, finds a
  plan *near* the address and applies it to the user's plot: Librobäck (44 %), Dalby-Säby (46 %) and Flogsta (53 %)
  fall furthest. Only 3 of the 45 address answers offer the pin.
- **Statutes hold, kommun pages and plans less so.** Claims citing a law section: 82 % with a pin, 89 % without.
  Kommun bygglov pages 83 % and 71 %, översiktsplan 73 % and 71 % (15 and 7 claims), strandskydd pages 9 of 9 and 4 of 8.
  The weaker sources are where the agent summarises and extends rather than quotes.
- **A flag is rarely a wrong fact; it is usually one unsourced detail.** Of the 126 claims flagged unsupported, the
  auditor finds 38 fully backed (30 %), 69 partly backed and 14 with nothing in their source. The added detail is
  generic procedure the model knows (apply before the work starts, contact the Länsstyrelse early, have sections and
  facades drawn). The other direction is small: of the 451 claims the check passed, 1 has nothing in its source, 108
  carry an unbacked detail unflagged.
- **Advice is the weakest form.** Advice 67 % (pin) and 50 % (address) supported, statements 84 % and 80 %. Contact
  details appear in 8 address claims only.
- **Uncited claims are mostly the opening line.** 46 claims (7 %) state a rule without a citation; 27 of the 90
  answers open with an uncited verdict line whose rule is cited further down. The rest are the conditions of the
  9 kap. 4–5 and 10 § exemptions listed without their section; Trevlinge (tillbyggnad, 10), Falhagen (fasad, 7),
  Kvarnbo and Vålsätra (5 each) hold most of them.
- **Hedges get flagged, mostly without a pin.** Address answers hold 28 hedges ("I could not tie the address to a
  fastighetsbeteckning"), 14 % supported: the check judges a statement of what was *not* found against sources that
  cannot state it. Leaving hedges out moves the address share from 66 % to 69 %, the pin share not at all.
- **Facts worth checking by hand**: the strandskydd fee of 7,340 kr (Dalby-Säby, above).

### How to raise the numbers

Ranked by return for the effort, each to be validated on cases it was not tuned on. Keep the two kinds apart: (a)
changes the answers, (b) only changes the measurement. A (b) change raises the number without a better answer, so
report it in its own row.

**(a) Better answers**

1. **Without a pin, apply a plan to the plot only when a tool ties the address to it.** Otherwise say "a plan near
   X", do not apply its rules to the plot, and offer the pin (`NO_PIN_HINT` in `place/context.py`, `PIN_GUIDE` in
   `agentic/agent.py`): only 3 of the 45 address answers offered one. Keep it an answer with routes, not a question
   card, or the missing-info eval's balance shifts. A next step: a tool that geocodes the typed address and builds
   the place data, used only on a house-level hit (Uppsala's register finds the house; Nominatim does for about 28 %
   of Swedish addresses, so the 15 Uppsala cases will flatter it).
2. **Cite the verdict line and the condition lists.** `ANSWER_FORMAT`: the line after **Bedömning** carries the
   citation of its decisive rule, and a list of conditions cites its section once (PBL 9 kap. 4 §, 5 §, 10 §). Covers
   most of the 46 uncited claims, at little risk.
3. **Take the next steps from sources.** `ANSWER_FORMAT` asks for "who to contact" and, under Completeness, every
   procedural step, which pulls in generic advice: ask for steps a tool result states, cited, contact details only
   from a page that prints them, general advice in one closing line. Riskier: Completeness was adopted for +0.03 to
   +0.05 key points, so it must hold the key points on the other case sets.
4. **Quote plan texts closer.** Detaljplan claims are the weakest source with the pin (72 %): ask the agent to quote
   the provision it applies rather than paraphrase it.

**(b) Measurement only**

5. **Leave hedges out of the check.** Right in principle and it removes false underlines in the chat, but it moves
   the address share from 66 % to 69 % with no change to the answers.
6. **Calibrate the check on hand labels, not on these answers.** Label ~100 claims by hand (or use the 380 refereed
   pairs of 2026-11-12) and measure Jev and the auditor against them, then decide on `SUPPORTED_AT` and the question
   wording; run the recheck twice for its test-retest agreement. Tuning the threshold on these 90 answers would fit
   it to one auditor's taste.
7. **Judge sentences apart only if it helps.** Nothing here shows that splitting stretches raises accuracy; it would
   mainly underline the right sentence in the chat.

### How to tell whether a change works

- Freeze the 15 Uppsala cases as a test set: do not iterate prompts on them.
- Measure each (a) change under the same check version first; then (b) changes on fixed answers with
  `claim_audit recheck`.
- Held out: `agentic.bench` on `cases.jsonl` + `cases_tasks.jsonl` + `cases_generated.jsonl` (other kommuner; claim
  support and key points both), `cases_bilingual.jsonl` for the language, and the missing-info eval
  (`cases_missing_info.jsonl`, both halves at 95 % or more) for changes 1 and 3.
- New place cases, written before the change: about 10 pin and address questions from kommuner without Uppsala's
  address register (Vallentuna, Stockholm on the demo corpus; other plan-layer kommuner on the disk store).
- Compare with a case-clustered bootstrap of the paired difference, over 3 repeats (~$1 a run incl. the audit).
