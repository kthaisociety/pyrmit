**What was run.** The 15 Uppsala cases of `place/cases_answers.jsonl`, each asked with a map pin and with the
address typed in the question (no pin), 3 repeats each: 90 answers, 574 claims, all checked (no check failed). The
agent (`openai/gpt-6-luna`) read the hosted corpus (Neon branch `demo`: 93,298 Uppsala chunks with the documents of
every plan in force, plus the 15 statutes). A second model (`xiaomi/mimo-v2.6-flash`) then read 573 of the claims
next to the full text of their sources. Cost: $0.77 for the answers incl. the live check and the judge, $0.12 for the
audit. The pilot (local disk corpus, 1,635 Uppsala chunks, one repeat) is superseded by this run.

### What the numbers say

- **The pin makes answers better sourced, not only better.** With a pin 80 % of the claims are supported
  (75–85 %), without it 65 % (60–71 %): the intervals do not overlap, and every repeat shows the gap (pin 75–86 %,
  address 64–67 %). The pin also gives the content: key points 0.78 against 0.46, place facts named 0.60 against
  0.11, and 27 % of the address answers talk about the wrong place.
- **Without a pin the agent guesses the plan, and that is where support breaks.** Address answers cite plan
  documents (detaljplan, planbeskrivning) on 84 claims, pin answers on 9: with a pin the place data names the plans.
  Searching by street name, the agent finds a plan *near* the address and writes what it says as if it held for the
  user's plot ("En detaljplan för Fjärdingen 12:3 … Om er adress ligger på den fastigheten …", the Fansta 3:1 plan
  for Fanstavägen 1, the Kvarnbo ridhus plan for Kvarnbo 25). The cited plan is real; the link to the plot is not
  in it. Kvarnbo (27 %), Librobäck (53 %) and Slottsgatan (56 %) fall furthest without the pin; Slottsgatan is
  100 % with it.
- **Statutes hold, kommun pages and plans less so.** Claims citing a law section are 91–92 % supported in both
  conditions. Kommun guidance pages (bygglov) 76–81 %, översiktsplan 56–77 %, detaljplan texts ~60 %, strandskydd
  pages 54–73 %. The weaker sources are where the agent summarises and extends rather than quotes.
- **A flag is rarely a wrong fact; it is usually one unsourced detail.** Of the 98 claims flagged unsupported, the
  auditor finds 30 fully backed, 65 partly backed and only 3 with nothing in their source. The typical added detail
  is generic procedure the model knows: "apply before the work starts", "contact the Länsstyrelse early", "an
  architect should draw sections and facades", "the förening should decide first". The other direction is small:
  of 418 claims the check passed, only 2 have nothing in their source, but 95 carry an unbacked detail unflagged.
- **Advice and contact details are the weakest forms.** Advice is 60 % supported (statements 81 %); contact
  details 40 %: the answer cites a page for a fact and adds the kommun's phone number and e-mail, which that page
  does not hold. The auditor finds the number in the cited page for 5 of these flags, so part of it is the check
  being strict.
- **Uncited claims are mostly the answer's opening line and the exemption conditions.** 57 claims (10 %) state a
  rule without a citation; 24 of the 90 answers open with an uncited verdict line ("Ja, ni behöver sannolikt
  bygglov …", "En tillbyggnad på 25 m² kan vara bygglovsbefriad …") whose rule is cited further down. The rest are
  the conditions of the 9 kap. 4–5 and 10 § exemptions (30 m², 65 m², below the ridge, prior additions counted)
  listed as a checklist without their section. Trevlinge (tillbyggnad), Falhagen (fasad) and Kvarnbo (gäststuga)
  hold most of them.
- **Hedges get flagged, mostly without a pin.** 15 of the 20 hedges of address answers are flagged ("I could not
  tie the address to a fastighetsbeteckning"): the check judges a statement of what was *not* found against
  sources that cannot state it. Leaving hedges out moves the address share from 65 % to 69 %, the pin share not at
  all.
- **Facts worth checking by hand**: the strandskydd fee of 7,340 kr (Dalby-Säby, four answers; the auditor backs it
  once and once says the cited page gives only 11,744 kr), "lots of 1/5 of the plot" in Norra Gottsunda villaområde
  (Vålsätra address), and Uppsala's 10-week decision time for a complete bygglov case (Slottsgatan address).

### How to raise the numbers

In order of expected effect, with what each changes. The first three change the answers, the last two the
measurement; report the two kinds apart so a better check is not mistaken for a better agent.

1. **Get the pin before plan-specific facts** (+15 points is the gap). Without a pin, the agent should not state
   what a nearby plan says about the user's plot: it should say which plans lie near the address, that it cannot
   tell which one applies, and offer the pin (`NO_PIN_HINT`, `ASK_GUIDE` in `agentic/agent.py`). Geocoding the
   typed address to a point and building the place data from it (`place.geocode` already does this for the map)
   would give address questions the pin's sources without asking.
2. **Cite the verdict line and the exemption conditions.** Add to `ANSWER_FORMAT`: the opening line carries the
   citation of the rule it rests on, and a list of conditions cites the section once per list (PBL 9 kap. 4 §,
   5 §, 10 §). That alone covers about half of the uncited claims.
3. **Keep the next steps to what a source says.** Ask the answer format for steps taken from the kommun's page
   (cite it) and to leave generic advice ("innan arbetet påbörjas", "anlita en konstruktör") out or as a separate
   uncited line the check skips. For contact details, have the agent cite the page that prints them, or put the
   kommun's Kontaktcenter in the place data so they are backed by it.
4. **Judge each sentence on its own.** 160 claims are partly backed: a stretch of two or more sentences where one
   detail is missing. Splitting the stretch before the check (`claim_check.py`) gives a flag on the sentence that
   lacks support instead of a pass or a flag for the whole stretch, and lets the chat underline the right sentence.
5. **Leave hedges out of the check, and review the threshold.** A hedge is not a claim against a source (as with a
   question card). And 31 % of the flags are fully backed according to the auditor: read the section *Flags the
   auditor disagrees with* and check whether `SUPPORTED_AT` or the question wording is too strict, before tuning the
   agent on the unsupported share.

To see whether a change works, rerun this eval (pin and address, 3 repeats, ~$0.90 incl. the audit): a repeat moves
the share by up to ±6 points, so compare the means over the three repeats, and the intervals.
