# Claim support: what the live claim check finds, and what is behind it

Result files: `place-answers-20261119-153240-claim-support-neon-fixed.json`. Run 2026-11-19T15:32:40+01:00, agent openai/gpt-6-luna, judge xiaomi/mimo-v2.6-flash, corpus neon.

Every factual claim of each answer was put to the chat's live claim check (`agentic/claim_check.py`): a claim is **supported** when the decision model says the chunks it cites (or the pinned place's data) back it, **unsupported** when it cites a source that does not, and **uncited** when it states a rule, number, fee or deadline with no citation. Advice and questions are not claims.

## Headline

| Condition | Answers checked | Claims | Supported | 95 % interval | Unsupported | Uncited | Answers with no flag | Flags per answer | Checks failed |
|---|---|---|---|---|---|---|---|---|---|
| address | 45 / 45 | 301 | 66% | 60%–71% | 24% | 10% | 7% | 2.5 | 0 |
| pin | 45 / 45 | 322 | 79% | 72%–85% | 17% | 5% | 27% | 1.5 | 0 |

The interval comes from resampling the answers (an answer's claims stand or fall together). “Answers checked” leaves out answers that were a question back to the user or an error. “Answers with no flag” is over the answers that make at least one claim.

## Findings

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

## What the numbers suggest

1. **The check flags claims its sources do back.** The auditor finds 38 of the 121 claims flagged unsupported (31%) fully backed by their cited sources. Read those (section *Flags the auditor disagrees with*) before trusting the unsupported share, and see whether the decision model's threshold (`SUPPORTED_AT` in `claim_check.py`) or its question wording is too strict.
2. **Judge each sentence on its own.** A stretch of several sentences before one citation is judged as a single claim: 76% of the 466 multi-sentence stretches are supported, against 89% of the 111 single sentences. One unbacked sentence fails the whole stretch. Split the stretch per sentence in `claim_check._stretches`, or have the answer format put a citation after each sentence that states a fact.
3. **56 of the 164 flagged claims (34%) tell the user what to do** (59% of all such claims are supported). Leave pure advice out of the check, as generic advice already is, and judge only the fact attached to it; or have the answer keep the next steps apart from the facts they rest on, each fact with its own citation.
4. **30 of the 164 flagged claims (18%) say what the assistant could not read or confirm** (32% of all such claims are supported). A hedge is not a claim about the sources: leave it out of the check. Where the hedge is about a plan that was not read, the fix is upstream (the plan's text in the corpus, or the agent opening it).
5. **Contact details are flagged** (31% of 16 supported): the telephone number or address is not in the chunk the sentence cites. Have the agent cite the page the contact details come from, or keep them out of the answer unless a source read states them.
6. **Claims of kind “place” are the weakest facts**: 68% of 91 supported, and the auditor agrees on 21 of the flags. This is where the agent states more than its source says: read the `missing` column of those claims for what it adds (a number, a section reference, a condition), and tighten the answer format on it (quote the figure, cite the chunk that holds it).
7. **“pin” answers are better supported than “address” answers** (79% against 66%); the intervals do not overlap.
8. **46 claims (7%) state a fact without a citation.** The answer format asks for a citation on every rule, number and fee: check which of them repeat a fact cited elsewhere in the answer (harmless, see the summary line above) and which are new facts.

## What kind of claim is supported

A second model (`xiaomi/mimo-v2.6-flash`, another family than the agent and the decision model) read 612 of the 623 claims next to the full text of their cited chunks and the place data, and labelled each. The support shares below are still the live check's.

| Kind of claim | Claims | Supported | Unsupported | Uncited |
|---|---|---|---|---|
| rule | 386 | 76% | 15% | 9% |
| place | 91 | 68% | 27% | 4% |
| procedure | 85 | 69% | 28% | 2% |
| number | 27 | 89% | 11% | 0% |
| contact | 16 | 31% | 69% | 0% |
| none | 7 | 57% | 29% | 14% |

rule = a legal rule or permit requirement; number = a measure, limit, fee, deadline or date; place = a fact about the property; procedure = what the kommun requires or how to apply; contact = contact details; none = no factual content of its own.

| Form of claim | Claims | Supported | Unsupported | Uncited |
|---|---|---|---|---|
| statement | 427 | 82% | 13% | 5% |
| advice | 136 | 59% | 33% | 8% |
| hedge | 44 | 32% | 45% | 23% |
| summary | 5 | 60% | 20% | 20% |

statement = states the fact plainly; advice = tells the user what to do, with or without a fact attached; hedge = says what could not be read or confirmed; summary = the verdict line or a recap.

| Cited source | Claims | Supported | Unsupported | Uncited |
|---|---|---|---|---|
| law | 352 | 85% | 15% | 0% |
| bygglov | 112 | 76% | 24% | 0% |
| detaljplan | 81 | 59% | 41% | 0% |
| oversiktsplan | 34 | 82% | 18% | 0% |
| strandskydd | 31 | 74% | 26% | 0% |
| other | 5 | 60% | 40% | 0% |
| avlopp | 2 | 100% | 0% | 0% |

A claim citing two kinds of source counts under both.

## Is the check right?

Over the 569 audited claims that cite a source:

| Check says | Auditor: backed | Auditor: partly | Auditor: not backed |
|---|---|---|---|
| supported | 339 | 108 | 1 |
| unsupported | 38 | 69 | 14 |

- **False flags**: 38 of 121 flagged claims are fully backed according to the auditor (31%).
- **Misses**: 1 of 448 passed claims are not backed at all according to the auditor (0%).
- **Partly backed**: 108 passed and 69 flagged claims hold one fact the source states and one it does not. The check has to call the whole stretch one way or the other, so the passed ones carry an unbacked detail to the user unflagged.

## Does the length of the stretch matter?

The check judges everything before a citation on a line as one claim.

| Stretch | Claims | Supported | Unsupported |
|---|---|---|---|
| 1 sentence | 111 | 89% | 11% |
| 2 sentences | 246 | 74% | 26% |
| 3 or more | 220 | 78% | 22% |

## Per case

Supported claims / claims, over the repeats.

| Case | address | pin |
|---|---|---|
| kungsangsgard-nytt-hus | 15 / 18 (83%) | 19 / 22 (86%) |
| kvarnbo-gaststuga | 12 / 20 (60%) | 18 / 24 (75%) |
| slottsgatan-kallare | 18 / 29 (62%) | 20 / 32 (62%) |
| kungsgatan-pabyggnad | 11 / 20 (55%) | 14 / 21 (67%) |
| bjorklinge-avstyckning | 7 / 7 (100%) | 15 / 18 (83%) |
| dalbysaby-bastu | 11 / 24 (46%) | 21 / 21 (100%) |
| fansta-flerbostadshus | 17 / 27 (63%) | 21 / 24 (88%) |
| valsatra-carport | 15 / 23 (65%) | 15 / 18 (83%) |
| gottsunda-inglasning | 16 / 19 (84%) | 21 / 24 (88%) |
| falhagen-fasad | 16 / 22 (73%) | 14 / 18 (78%) |
| flogsta-restaurang | 8 / 15 (53%) | 8 / 10 (80%) |
| librobak-bostader | 7 / 16 (44%) | 15 / 18 (83%) |
| norby-attefall | 17 / 23 (74%) | 16 / 24 (67%) |
| trevlinge-tillbyggnad | 17 / 24 (71%) | 14 / 23 (61%) |
| slassbo-nytt-hus | 11 / 14 (79%) | 22 / 25 (88%) |

## Per repeat

How much the share moves between runs of the same questions.

| Condition | repeat 0 | repeat 1 | repeat 2 |
|---|---|---|---|
| address | 67% | 63% | 67% |
| pin | 71% | 80% | 85% |

## Flagged and confirmed: claims that cite a source that does not state them

The check and the auditor agree. These are the claims to fix in the agent.

| Case | Condition | Kind | Form | Claim | What the sources do not state |
|---|---|---|---|---|---|
| kungsangsgard-nytt-hus | address | procedure | statement | Uppsala kommun anger att förhandsbesked ofta används för ett nytt enbostadshus utanför detaljplan. Om området saknar kommunalt VA ska en egen VA-lösning redovisas i ansökan | Sources do not mention any requirement to redovisa egen VA-lösning om kommunalt VA saknas |
| kvarnbo-gaststuga | pin | number | statement | Fastigheten ligger utanför detaljplan. Då krävs normalt bygglov för nybyggnad, men PBL 9 kap. 5 § undantar en komplementbyggnad eller ett komplementbostadshus om den bland annat är högst 50 m², mindre än byggnaden den kompletterar, högst 4,5 meter i taknocksh… | PBL 9 kap. 5 § komplementbyggnad limits (50 m², 4,5 m, 65 m²) absent from cited source |
| kvarnbo-gaststuga | pin | rule | statement | Gäststugan måste alltså komplettera en befintlig byggnad och vara mindre än den. Att den är 25 m² uppfyller inte ensamt villkoren | requirement that a komplementbyggnad complement and be smaller than an existing building |
| slottsgatan-kallare | pin | rule | statement | Om källaren innebär ett väsentligen annat användningssätt eller en ytterligare bostad kan bygglov också krävas | Cited provision covers anmälan, not bygglov for other use or extra dwelling (PBL 9 kap. 15 § does) |
| kvarnbo-gaststuga | address | place | statement | Uppsala har en gällande detaljplan som heter **Kvarnbo**. Där anges användningarna lager och ridanläggning, men sökningen har inte visat att adressen Kvarnbo 25 ligger inom planområdet. Om planen gäller just tomten kan användningsbestämmelserna därför hindra… | that the plan is in force and that the address was not shown to lie within the plan area |
| slottsgatan-kallare | address | place | hedge | Jag kan inte säkert fastställa från underlaget vilken detaljplan som gäller för just Övre Slottsgatan 26B. En kommunal planbeskrivning för **Dp 29J, del av kvarteret Rosenberg, Fjärdingen 12:3**, gäller ett område vid Övre Slottsgatan och beskriver gathusen s… | medeltida lämningar och krav att grundläggning ske ovan kulturlager; om fastigheten omfattas av planen |
| slottsgatan-kallare | address | procedure | advice | Skicka in handlingarna och invänta erforderliga beslut och startbesked innan ni börjar. Uppsala kommun tar emot ansökningar och anmälningar via e-tjänst eller blankett | cited source does not state awaiting decisions and startbesked before starting work |
| kungsgatan-pabyggnad | pin | rule | statement | Detaljplanen medger bostäder, men en extra våning måste rymmas inom den högsta våningshöjd som gäller för just husets del av fastigheten | Plan sets 'högsta antal våningar' (max number of storeys), not 'högsta våningshöjd'; per-house applicability not stated |
| kungsgatan-pabyggnad | pin | rule | statement | Plankartan anger en bestämmelse om **högsta antal våningar**. Planbeskrivningen säger att bebyggelsen i området varierar mellan två och sex våningar och att planen anpassades till den befintliga bebyggelsen; den förutsätter alltså inte generellt att hus kan h… | Planbeskrivning source does not state two-to-six storeys or adaptation to existing buildings; only plankarta mentions storey count |
| kungsgatan-pabyggnad | pin | procedure | advice | Låt en arkitekt ta fram en enkel sektion/fasadritning med befintlig och föreslagen höjd. Sök bygglov innan arbetet påbörjas | no source states an architect must produce section or elevation drawings |
| kungsgatan-pabyggnad | address | rule | statement | Ändringen måste också utföras varsamt med hänsyn till husets karaktär och värden. Om byggnaden är särskilt värdefull får den inte förvanskas | Source does not state a particularly valuable building may not be disfigured |
| kungsgatan-pabyggnad | address | contact | hedge | Jag har inte kunnat knyta adressen till en fastighetsbeteckning eller läsa den detaljplan som gäller för just huset. Det är den avgörande kontrollen för om en extra våning ryms. Uppsala kommuns bygglovsvägledning kan kontaktas på 018-727 00 00 eller bygglov-k… | Source gives no phone number, e-mail address or statement about the address/plan link |
| dalbysaby-bastu | address | rule | statement | Inom strandskyddsområde får nya byggnader inte uppföras utan dispens. Strandskyddet är normalt 100 meter från strandlinjen och kan vara utvidgat till 300 meter | dispenskravet (7 kap. 18 c §) står inte i källorna |
| dalbysaby-bastu | address | rule | statement | Uppsala kommun kräver strandskyddsdispens för nya byggnader i strandskyddat område, även byggnader som inte kräver bygglov. Kommunen anger att en mindre åtgärd, exempelvis en komplementbyggnad inom tidigare beslutad tomtplats, har en fast dispensavgift på 7 3… | att fast avgiften 7 340 kronor för mindre omfattande åtgärder anges inte i källorna |
| dalbysaby-bastu | address | rule | statement | Om bastun är en komplementbyggnad utanför detaljplan kan den under vissa villkor vara bygglovsbefriad: högst 50 m² byggnadsarea, högst 4,5 meters nockhöjd, mindre än byggnaden den kompletterar, placerad inom tomten och inom en sammanlagd area på högst 65 m² f… | att strandskyddsdispens krävs oavsett bygglovsfrihet står inte i PBL 9 kap. 5 § |
| dalbysaby-bastu | address | procedure | advice | Om platsen ligger inom strandskyddat område: sök dispens innan byggstart och redovisa varför platsen uppfyller ett särskilt skäl. Kommunen anger att en avgift tas ut även om dispensen avslås | att avgiften betalas även vid avslag och att dispens söks före byggstart står inte i källorna |
| fansta-flerbostadshus | pin | rule | advice | begär ett planbesked och beskriv byggnadens ungefärliga antal bostäder, höjd, placering, trafiklösning och VA-lösning. PBL 5 kap. 2 § säger att kommunen på begäran ska redovisa sin avsikt att inleda planläggning | statute does not list which details to submit with a planbesked request |
| valsatra-carport | pin | procedure | advice | Markera den tänkta placeringen på en situationsplan och kontrollera om den ligger inom ett område där plankartan tillåter byggnad. Planbeskrivningen säger att de utpekade byggrätterna för komplementbyggnader placerats särskilt på gårdarna | Planbeskrivningen says building rights are mainly placed outside the yards, not especially on them |
| fansta-flerbostadshus | address | place | advice | Ta fram fastighetsbeteckningen och be Uppsala kommun bekräfta vilken detaljplan och vilken zon som gäller för fastigheten. Planerna **Fansta 2:2** och **Fansta 3:1** finns i kommunens planmaterial, men adressen räcker inte för att jag ska kunna placera fastig… | sources do not state that an address alone is insufficient to place the property in the plan |
| valsatra-carport | address | procedure | advice | Om något villkor inte uppfylls, eller om planen kräver lov, sök bygglov innan arbetet börjar. Uppsala kommuns bygglovshjälp kan vägleda om vad som gäller för platsen | Källorna anger inte att bygglov ska sökas innan arbetet påbörjas |
| falhagen-fasad | pin | rule | statement | Bedömningen förutsätter att byggnaden är ett flerbostadshus och att fasaden vetter mot allmän plats. Om ni byter till fönster med oförändrat utseende kan kommunen behöva bedöma om åtgärden ändå räknas som en fasadändring. Uppsala kommun framhåller också att s… | source does not say unchanged-appearance window replacement may still need kommun assessment as a facade change |
| flogsta-restaurang | address | rule | statement | Plankartan skiljer mellan områden för bostäder och centrum (BC) och centrum (C). Vilken bestämmelse som gäller beror på var lokalen ligger på kartan | Source shows BC but no C zone; only states unspecified areas get the plan-wide provision |
| librobak-bostader | pin | rule | summary | Eftersom planens genomförandetid har gått ut finns en begränsad möjlighet att pröva en annan användning som ett lämpligt komplement till området och den planerade användningen. Det är ingen generell rätt till bostäder, och planens industrisyfte gör att bostäd… | Source states only the 61 § conditions; says nothing about dwellings or a general right to housing |
| librobak-bostader | address | place | hedge | Uppsala kommuns planmaterial visar kvarteret Ullfors i Librobäck, men underlaget jag hittat räcker inte för att säkert knyta adressen **Ullforsgatan 5E** till en viss fastighet och planzon | att underlaget inte räcker för att knyta adressen Ullforsgatan 5E till fastighet och planzon |
| trevlinge-tillbyggnad | address | procedure | advice | Kontrollera tidigare tillbyggnader i kommunens bygglovsarkiv och mät arean enligt reglerna. Uppsala kommun rekommenderar också att kontrollera detaljplan, avstånd till gräns och järnväg samt om byggnaden eller området är särskilt värdefullt | källan säger inte att arean ska mätas enligt reglerna |
| slassbo-nytt-hus | pin | rule | statement | Uppsala kommuns översiktsplan säger att ny bostadsbebyggelse på landsbygden bör tillkomma som enstaka friliggande småhus på lämpliga platser, exempelvis som tillskott till befintliga bebyggelsegrupper. Kommunen väger också in påverkan på grannar, landskapsbil… | Sources do not mention landskapsbild, natur- och kulturvärden, trafik or samhällsservice as weighed factors |
| slassbo-nytt-hus | pin | procedure | advice | Redovisa en möjlig VA-lösning och en karta över den. Uppsala kommun anger att den som bygger där kommunalt VA saknas ska bifoga en egen VA-lösning till ansökan om förhandsbesked. Kommunens översiktsplan anger också att VA-förutsättningarna ska vara säkerställ… | No source says to attach an own VA solution and a map to the förhandsbesked application |
| kungsangsgard-nytt-hus | pin | place | statement | Uppsala kommuns översiktsplan säger att ny bostadsbebyggelse på Uppsalaslätten i övrigt endast kan tillkomma som kompletterande boende med koppling till jordbruksverksamhet. Verksamheten ska motivera ett ytterligare bostadshus, och huset ska ligga direkt inti… | that new housing on Uppsalaslätten only may be supplementary dwellings that the business motivates |
| kungsangsgard-nytt-hus | pin | procedure | advice | Redovisa särskilt varför bostaden behövs för jordbrukets drift, var brukningscentrum ligger och hur huset placeras i förhållande till det. Om platsen saknar kommunalt VA ska en egen VA-lösning redovisas i ansökan om förhandsbesked | that a non-municipal VA solution must be submitted with the förhandsbesked application |
| kungsangsgard-nytt-hus | address | rule | statement | Översiktsplanens inriktning är vägledande, inte i sig ett bygglovsbeslut. Kommunens jordbruksmarksriktlinje undantar Kungsängens gård från det tillfälliga stoppet för vissa kommunala planeringsinitiativ, men det innebär inte att ett enskilt bostadshus är godt… | Källan anger inte att översiktsplanens inriktning bara är vägledande eller att enskilt bostadshus inte godtas |
| kvarnbo-gaststuga | pin | rule | statement | Om stugan ska vara en självständig bostad snarare än en gäststuga som kompletterar huset kan den räknas som ett **komplementbostadshus**. Eftersom platsen ligger inom eller nära ett riksintresse för totalförsvarets anläggningar kan bygglov då krävas för nybyg… | source does not state that a self-contained dwelling counts as a komplementbostadshus |
| slottsgatan-kallare | address | place | statement | Uppsala kommuns planmaterial för Övre Slottsgatan beskriver området som del av den äldre stadskärnan där kulturlager kan förekomma. Det visar att arkeologin behöver kontrolleras för er fastighet, men fastighetens exakta plan och fornlämningsstatus har inte ku… | källan säger inte att fastighetens exakta plan och fornlämningsstatus inte gick att fastställa |
| slottsgatan-kallare | address | procedure | advice | om anmälan, marklov och startbesked. Skicka gärna en enkel skiss och beskriv om källaren ska rymma förråd eller ytterligare bostad. Uppsala kommun har också en digital bygglovshjälp | källan nämner varken digital bygglovshjälp, skiss, marklov eller startbesked |
| kungsgatan-pabyggnad | address | contact | advice | Sök bygglov hos Uppsala kommun innan arbetet påbörjas. Kommunens bygglovsvägledare nås på 018-727 00 00 eller bygglov-kontaktcenter@uppsala.se | source does not state one must apply for bygglov before starting work |
| dalbysaby-bastu | address | procedure | advice | Om platsen omfattas av strandskydd: sök dispens hos kommunen **innan** du bygger. Beskriv bastuns placering och storlek, befintlig bebyggelse och tomtplats samt hur fri passage och naturvärden påverkas | sources do not list what the application must describe (placement, size, existing buildings, fri passage, naturvärden) |
| dalbysaby-bastu | address | number | statement | Kommunens publicerade avgift är 7 340 kr för en mindre åtgärd, till exempel en komplementbyggnad inom en tidigare beslutad tomtplats. Kommunen behöver bedöma vilken avgift som gäller för din placering | cited source states 11 744 kr for larger measures, not 7 340 kr, and does not say kommunen must assess which fee applies |
| fansta-flerbostadshus | pin | procedure | advice | Redovisa en fungerande VA-lösning. Uppsala kommun anger att VA ska redovisas i ansökan om förhandsbesked när området saknar kommunal VA-lösning | source does not mention presenting a VA solution in a förhandsbesked application |
| fansta-flerbostadshus | address | place | statement | I Lövstalöt finns en detaljplan för Fansta 3:1 som syftar till bostäder i bland annat grupphus och “ett mindre antal lägenheter i flerbostadshus”. Det visar att flerbostadshus kan rymmas i den planen, men inte att Fanstavägen 1 ligger inom den eller i en zon… | Source does not mention Lövstalöt or whether Fanstavägen 1 lies within the plan |
| fansta-flerbostadshus | address | rule | statement | Om byggrätten inte medger projektet kan en ändring eller ny detaljplan behövas. Kommunen ska pröva detaljplan när ett nytt byggnadsverk kan få betydande omgivningspåverkan eller när det finns stor efterfrågan på mark för bebyggande | Cited provision does not mention large demand for land for construction |
| valsatra-carport | pin | place | statement | Planbeskrivningen säger att byggrätterna för komplementbyggnader ligger på anvisade platser, huvudsakligen utanför gårdarna. Där bostadsrum har fönster ska den anvisade byggrätten ligga minst 10 meter från fasaden | planbeskrivningen: komplementbyggnaders byggrätter, placering och 10 meters avstånd till fasad |
| valsatra-carport | address | procedure | advice | Mät carportens byggnadsarea, nockhöjd och avstånd till tomtgränsen. Uppsala kommun har en digital bygglovshjälp för att reda ut lovfrågan på platsen | source gives no digital bygglovshjälp tool nor advice to measure area and height |
| valsatra-carport | address | contact | statement | Jag har inte kunnat fastställa Linrepevägen 8:s fastighetsbeteckning, tillämpliga detaljplan eller plankartans regler för just tomten. Storlek, höjd, placering och befintliga komplementbyggnader avgör därför om carporten kan byggas utan bygglov. Uppsala kommu… | source gives no phone number or e-mail, nor property designation or detail plan |
| gottsunda-inglasning | pin | place | hedge | De detaljplaner som gäller för fastigheten har lästs; jag har inte hittat någon särskild bestämmelse där som specifikt reglerar balkonginglasning. Det avgörande lovkravet ovan beror ändå på vilken sida av huset som berörs. Planbeskrivningen för del av Stenham… | Sources do not state planbeskrivningen says plankartan is bindande, nor that no balkonginglasningsbestämmelse was found |
| falhagen-fasad | address | procedure | hedge | Jag har inte kunnat fastställa vilken detaljplan eller vilka kulturmiljöbestämmelser som gäller för just Torkelsgatan 2A. Därför kan jag inte bekräfta den exakta lovplikten eller bedöma om fönsterförslaget innebär en ändring av fasadens karaktär. Uppsala komm… | no source states which detaljplan or cultural heritage rules apply to Torkelsgatan 2A |
| flogsta-restaurang | address | place | hedge | Jag har inte kunnat knyta adressen till en fastighetsbeteckning och den detaljplan som gäller just där. Uppsala kommun beskriver att åtgärder i planlagda områden ska följa detaljplanens regler | Sources do not state the assistant could not link the address to a fastighetsbeteckning |
| flogsta-restaurang | address | rule | advice | Om bygglov krävs, invänta beslut innan ni börjar använda lokalen som restaurang. Uppsala hänvisar också till sin Bygglovhjälpen för vägledning om lov och vilka handlingar som behövs | Source does not say to await the decision before starting restaurant use |
| norby-attefall | pin | rule | statement | Den registrerade fastigheten har många adresser. Fastighetsgränsen är inte nödvändigtvis samma sak som den relevanta **tomten** enligt PBL; areagränsen och befintliga komplementbyggnader behöver bedömas för den aktuella tomten | att fastighetsgräns och tomt är olika, och att arealgräns och befintliga komplementbyggnader bedöms per tomt |
| norby-attefall | pin | rule | statement | Om samtliga villkor för lovbefrielse är uppfyllda krävs normalt inte bygglov. En ny fristående byggnad omfattas inte i sig av anmälningsfallen i PBF 6 kap. 1 §, men installation av exempelvis vatten eller avlopp kan kräva anmälan. Börja inte med en åtgärd som… | villkoren för lovbefrielse i 9 kap. 4 § nämns inte i dessa källor |
| librobak-bostader | address | place | statement | Jag hittar en gällande detaljplan för Librobäck, **Kvarteren Harg och Hållnäs med flera**, laga kraft 2005. I plankartan anges användningen **”Industri, kontor, odling och bilservice”** för mark betecknad JKLG; bostäder finns inte med bland dessa användningar | that the plan attained legal force in 2005 |
| librobak-bostader | address | rule | statement | Inom detaljplan ska bygglovsåtgärden inte strida mot planen. En avvikelse kan godtas bara under de begränsade förutsättningarna i PBL 9 kap. 60 §; att ändra markanvändningen från industri till bostäder framstår inte som en liten avvikelse | that changing land use from industrial to residential would not be a small deviation |
| norby-attefall | address | rule | statement | Uppsala kommun betonar att även åtgärder utan bygglov ska följa övriga krav i plan- och bygglagstiftningen och att andra tillstånd kan behövas | cited source does not mention following other requirements or needing other permits |
| norby-attefall | address | place | hedge | Kontrollera på kommunens karta vilken fastighetsbeteckning och detaljplan som gäller för adressen. Jag hittade detaljplanen **Tryffelvägen, del av Norby 31:52**; kartan visar Eksoppsvägen i närheten, men underlaget räcker inte för att säkert avgöra om just nu… | that the map shows Eksoppsvägen nearby and which plan covers number 37 |
| trevlinge-tillbyggnad | pin | rule | statement | Undantaget gäller inte om byggnaden eller området omfattas av de särskilda värdeskydd som anges i PBL 9 kap. 37 §. Detaljplanen anger bostäder på fastigheten och innehåller bland annat regler om högst en fjärdedel bebyggd tomtyta samt höjd och utformning | the PBL 9 kap. 37 § special value protection rule is not in the cited plan documents |
| trevlinge-tillbyggnad | pin | rule | statement | Även en bygglovsbefriad tillbyggnad kan kräva anmälan om den väsentligt påverkar bärande konstruktion eller brandskydd. Då måste du invänta startbesked innan arbetet börjar | no cited provision states startbesked must be awaited for an anmälan-liable measure |
| trevlinge-tillbyggnad | pin | rule | hedge | Jag kan inte avgöra här om huset har tidigare tillbyggnader eller omfattas av särskilt värdeskydd. Planens särskilda egenskapskoder vid själva huset behöver också kontrolleras mot plankartan; reglerna om planavvikelse för vissa tillbyggnader finns i PBL 10 ka… | no source states the assistant cannot determine prior extensions, special value protection or plot codes |
| kvarnbo-gaststuga | address | place | statement | Kommunens planregister innehåller en detaljplan med namnet **Kvarnbo**, men den gäller ett område omedelbart norr om Kvarnbo gård och har ridhus och stall som syfte; underlaget visar inte om den omfattar just din tomt | Sources don't state the plan lies immediately north of Kvarnbo gård or its presence in planregister |
| kvarnbo-gaststuga | address | rule | advice | Kontrollera fastighetens detaljplan, avståndet till gränsen, stugans nockhöjd och hur stor den sammanlagda ytan av befintliga och planerade komplementbyggnader blir. Även utan bygglov kan andra krav eller tillstånd gälla, exempelvis strandskyddsdispens eller… | Cited sources don't mention checking nockhöjd or combined complementary building area |
| slottsgatan-kallare | pin | place | statement | Fastigheten ligger inom detaljplan 0380-541, där området är avsett för bostäder. Planbeskrivningen säger att bevarande är stadsplanens huvudändamål och att ny bebyggelse ska ansluta till befintlig bebyggelse i utformning och material. Källare nämns inte särsk… | that bevarande is the plan's main purpose and that new buildings must match existing in form and material; basements not mentioned |
| slottsgatan-kallare | pin | rule | advice | PBL kräver varsamhet vid ändring av byggnad. Om huset eller miljön är särskilt värdefull får den inte förvanskas. Planens uttalade bevarandeinriktning gör att grundläggning, fasader, trappor, fönster och andra karaktärsdrag bör utredas och redovisas noga | that the plan expressly sets preservation as its purpose and that foundation, facades, stairs, windows must be examined and documented |
| slottsgatan-kallare | pin | rule | advice | Fastigheten ligger enligt registeruppgifterna i vattenskyddsområdet Uppsala- och Vattholmaåsarna. Vattenskyddsföreskrifterna kan begränsa schaktning och medföra krav på dispens. Uppsala kommuns handlingsplan anger som åtgärdsriktlinje att schaktning ska ske m… | handlingsplan's 1 metre and 3 metre excavation limits above groundwater in outer/inner protection zones |
| kungsgatan-pabyggnad | pin | place | statement | Planbeskrivningen säger att bebyggelsen i planområdet varierar mellan två och sex våningar och att planen inte avsåg några större förändringar. De tillägg som särskilt nämns är förråd i en våning och balkonger, inte en ny våning på bostadshusen | att bebyggelsen varierar 2-6 våningar och att förråd/balkonger nämns, ej ny våning |
| slottsgatan-kallare | address | procedure | advice | Börja med en konstruktör som kan bedöma grundläggning, schaktordning, tillfällig stagning och risken för sättningar på huset och närliggande byggnader. Uppsala kommuns exempel på kontrollplan pekar särskilt ut bärförmåga, provisorisk stagning och kontroll mot… | no source says to engage a constructor assessing excavation order and settlement risk |
| slottsgatan-kallare | address | rule | advice | Ta fram en geoteknisk och hydrogeologisk bedömning innan ni bestämmer källarens djup. Om grundvatten behöver pumpas bort, utred tillstånd eller anmälan innan arbetet planeras vidare | that a geotechnical and hydrogeological assessment should come before deciding basement depth |
| slottsgatan-kallare | address | place | statement | Kontrollera den exakta detaljplanen och plankartans zon för huset. En plan för kvarteret Ubbo, som ligger vid Övre Slottsgatan, innehåller exempelvis en bestämmelse om lägsta schaktningsnivå på +13,7 meter i angivna delar, och medger helt nedgrävd källare bar… | source gives 13,8/16,5/14,9 and places kvarteret Ubbo at Odinslund, not +13,7 and Övre Slottsgatan |
| slottsgatan-kallare | address | procedure | advice | Stäm av med länsstyrelsen om fornlämningar och eventuell påverkan på grundvatten innan ni låser metod och tidplan | no source says to consult länsstyrelsen about groundwater impact |
| bjorklinge-avstyckning | pin | rule | statement | Lantmäterimyndigheten prövar om den nya fastigheten blir varaktigt lämplig för bostadsändamål, med lämplig utformning, tillgång till väg och möjlighet till godtagbart vatten och avlopp. FBL 3 kap. 1 § | Source does not name Lantmäterimyndigheten as the authority making this assessment |
| dalbysaby-bastu | address | rule | statement | Kommunen prövar dispens. Ett möjligt särskilt skäl är att platsen redan är ianspråktagen, exempelvis som en etablerad tomtplats; det räcker inte i sig att du äger marken. En privat bastu är normalt inte en anläggning som måste ligga vid vattnet för sin funkti… | sources do not say a private sauna normally need not be by the water, or that owning land is not enough |
| dalbysaby-bastu | address | place | hedge | Jag kunde inte bekräfta vilken detaljplan eller exakt strandskyddsgräns som gäller för just Dalby-Säby 62. Kommunens planmaterial nämner strandskydd mot Dalbyviken, men det räcker inte för att avgöra om din plats omfattas | source does not mention Dalby-Säby 62 or strandskydd mot Dalbyviken |
| dalbysaby-bastu | address | contact | advice | Den avgörande frågan är om bastun skulle stå inom en redan ianspråktagen tomtplats eller på allemansrättsligt tillgänglig mark nära stranden. Uppsala kommuns miljöförvaltning kan hjälpa till att kontrollera platsen; kontaktuppgifterna finns på kommunens sida… | source does not state this is the decisive question, nor that miljöförvaltningen checks the site |
| fansta-flerbostadshus | pin | rule | advice | När detaljplanen vunnit laga kraft, sök bygglov enligt planens bestämmelser. Om kommunen bedömer att detaljplan inte krävs, prövas i stället bygglovet direkt mot lagens krav utanför detaljplan | att bygglov söks enligt planens bestämmelser när detaljplanen vunnit laga kraft |
| fansta-flerbostadshus | address | place | statement | planbeskrivningen anger gruppbyggda småhus eller enfamiljshus, och plankartan anger friliggande hus. Ett flerbostadshus skulle då inte framstå som planenligt | sources do not state planbeskrivning limits development to single-family houses or that a multi-dwelling house would not be plan-aligned |
| fansta-flerbostadshus | address | place | statement | planbeskrivningen öppnar för små flerbostadshus med 2–4 lägenheter. Den anger högst två våningar i övriga kvarter och att högst en femtedel av tomten får bebyggas; exakt byggrätt beror på plankartans bestämmelser för platsen | planbeskrivning does not state that small multi-dwelling houses comprise 2–4 apartments |
| fansta-flerbostadshus | address | rule | advice | Stäm av ett skissförslag med Uppsala kommuns bygglovsvägledning innan ansökan. Om förslaget inte ryms i gällande plan, diskutera planbesked och eventuell ny detaljplan; PBL kräver detaljplan i vissa fall när ett byggnadsverk kan få betydande påverkan eller nä… | cited source does not state that Uppsala kommun offers pre-application guidance or planbesked discussions |
| fansta-flerbostadshus | address | contact | hedge | Jag kan inte knyta Fanstavägen 1 till rätt fastighetsgräns och planzon i det tillgängliga underlaget. Skicka fastighetsbeteckningen, så går det att jämföra förslaget med rätt plankarta. Uppsala kommun anger normalt en handläggningstid på 10 veckor från komple… | sources do not address whether Fanstavägen 1 can be matched to a fastighetsgräns and planzon |
| flogsta-restaurang | address | contact | advice | Om restaurang innebär en väsentligt annan användning, sök bygglov innan lokalen tas i bruk för restaurang. Kommunens Kontaktcenter kan koppla dig till stadsbyggnadsförvaltningen: 018-727 00 00 eller stadsbyggnadsforvaltningen@uppsala.se | No source states to apply for bygglov before the premises are used as restaurant |
| librobak-bostader | address | procedure | advice | Stäm av med Uppsala kommuns bygglovshandläggning och sök bygglov om projektet innebär nybyggnad | Sources do not mention checking with Uppsala kommun's bygglovshandläggning |
| librobak-bostader | address | none | hedge | Jag har inte kunnat koppla adressen till en fastighet eller läsa den plan som gäller för platsen. Därför går det inte att bedöma tillåtet antal bostäder, byggrätt eller andra platsbundna begränsningar ännu. Uppsala kommuns bygglovssida: https://www.uppsala.se… | That the address could not be linked to a property or applicable plan |
| librobak-bostader | pin | rule | statement | Detaljplanens genomförandetid har gått ut. Det öppnar för en begränsad möjlighet till bygglov för annan användning enligt PBL 9 kap. 61 §, men bara om användningen är ett lämpligt komplement till området och den planerade användningen. Bostäder är inte självk… | källorna anger inte om bostäder utgör ett lämpligt komplement i detta industriområde |
| librobak-bostader | pin | procedure | advice | Om kommunen går vidare behöver projektet också hantera geoteknik, vattenskyddsföreskrifter och eventuell påverkan på riksintresset. Kommunens planinformation anger Kontaktcenter på 018-727 00 00 och stadsbyggnadsforvaltningen@uppsala.se | källan anger inte att projektet behöver hantera geoteknik |
| trevlinge-tillbyggnad | pin | rule | advice | Om villkoren är uppfyllda behövs normalt inte bygglov enligt den bestämmelsen. Kontrollera med byggnadsnämnden i Uppsala om åtgärden ändå kräver anmälan eller startbesked innan arbetet börjar; åtgärder som omfattas av anmälningskrav får inte påbörjas före sta… | source does not say no bygglov is needed or that work may not start before startbesked |
| norby-attefall | address | place | statement | Kontrollera fastighetsbeteckningen och den exakta detaljplanen för adressen med Uppsala kommun. Kommunens planmaterial innehåller en detaljplan för Tryffelvägen, del av Norby 31:52, och en plankarta där Eksoppsvägen förekommer, men underlaget jag hittat fasts… | sources do not show Eksoppsvägen in the plankarta or that number 37 is excluded |
| norby-attefall | address | procedure | advice | Kontrollera bygghöjd, placering, befintliga komplementbyggnader och planbestämmelser innan du bestämmer utformningen. Om åtgärden kräver anmälan får den inte påbörjas innan startbesked; PBL 10 kap. 3 § anger att startbesked krävs för åtgärder som omfattas av… | advice to check height, placement and existing complement buildings is not in the sources |
| slassbo-nytt-hus | address | place | hedge | Kommunens plankarta visar en detaljplan i närheten av Stora Slässbo, men den visar inte säkert vilken planzon adress nr 22 tillhör. Därför går det inte att slå fast vad som får byggas på just er fastighet | sources are only a plan legend; they mention neither Stora Slässbo, adress nr 22 nor any planzon |

## Flags the auditor disagrees with

The check says unsupported, the auditor finds every fact in the cited sources. Verify by hand: either the check is too strict or the auditor too lenient.

| Case | Condition | Kind | Form | Claim | What the sources do not state |
|---|---|---|---|---|---|
| kungsangsgard-nytt-hus | address | rule | hedge | Det saknas fastighetsbeteckning och platsens exakta planstatus. Om huset är tänkt som ett fristående privat boende snarare än ett bostadshus som behövs för jordbrukets drift, kan kommunens inriktning för Uppsalaslätten bli ett tydligt hinder | – |
| kvarnbo-gaststuga | pin | none | hedge | Jag kan inte avgöra från uppgifterna om stugan skulle ligga inom tomten enligt PBL:s mening, om den ryms inom den sammanlagda areagränsen eller om den planerade platsen berör en fornlämning. Strandskyddet är inte kontrollerat för platsen. Uppsala kommun anger… | – |
| slottsgatan-kallare | pin | rule | statement | Om källaren kräver att grundvatten leds bort kan arbetet vara vattenverksamhet. Tillstånd krävs som huvudregel; undantag gäller bara om det är uppenbart att varken allmänna eller enskilda intressen skadas av påverkan på vattenförhållandena. MB 11 kap. 9 och 1… | – |
| slottsgatan-kallare | pin | rule | statement | I ett detaljplanerat område krävs marklov om schaktning ändrar markens höjdläge mer än 0,5 meter, med de undantag som anges i lagen. PBL 9 kap. 47 § | – |
| slottsgatan-kallare | pin | rule | advice | Låt en konstruktör och geotekniker ta fram ett förslag som visar schakt, förstärkning av befintlig grund, grundvattenhantering och hur grannbyggnader skyddas. PBL kräver att bygg-, rivnings- och markåtgärder planeras och utförs med aktsamhet | – |
| slottsgatan-kallare | pin | rule | advice | Håll schakten och eventuella ändringar av marknivån så begränsade som möjligt. Om grundvatten behöver pumpas, utred vattenverksamhetsfrågan innan ni väljer utförande | – |
| slottsgatan-kallare | pin | rule | advice | Ta tidigt kontakt med Länsstyrelsen om fornlämningen och med kommunen om plan, lov/anmälan och vattenskyddsföreskrifterna. Arbeta inte i fornlämningen utan erforderligt tillstånd | – |
| slottsgatan-kallare | pin | rule | advice | Be Uppsala kommuns bygglovsenhet om en bedömning av om projektet kräver bygglov, marklov eller anmälan. Beskriv schaktens djup och utbredning, om källaren ska användas som bostadsyta och om fasaden eller marknivån ändras. Om åtgärden kräver lov eller anmälan… | – |
| slottsgatan-kallare | pin | procedure | advice | Be Länsstyrelsen pröva behovet av tillstånd för ingrepp i fornlämningen och ta reda på vilka arkeologiska underlag som behövs | – |
| slottsgatan-kallare | address | place | statement | Planbeskrivningen för Dp 29J varnar för uttorkning av lerjord och därav följande sättningar i närområdet, och pekar på vikten av lokalt omhändertagande av vatten och skyddsåtgärder | – |
| kungsgatan-pabyggnad | pin | rule | statement | Jag kan inte säkert utläsa från kartunderlaget vilket våningsantal som gäller för just ert hus eller hur många våningar huset redan har. Det är avgörande: om en våning till överskrider planens gräns blir åtgärden planstridig. Bygglov krävs för en tillbyggnad,… | – |
| bjorklinge-avstyckning | pin | rule | statement | Fastigheten ligger enligt kartuppgifterna utanför detaljplan. Avstyckningen prövas ändå självständigt: varje ny fastighet ska vara varaktigt lämpad för sitt ändamål, ha lämplig utformning och tillgång till behövliga vägar samt, för bebyggelse, kunna få godtag… | – |
| dalbysaby-bastu | address | contact | advice | Be Uppsala kommun kontrollera fastigheten och den tänkta bastuplatsen mot strandskyddsgränsen och eventuell befintlig tomtplatsavgränsning. Uppsala kommun hänvisar strandskyddsfrågor till miljöförvaltningen | – |
| flogsta-restaurang | pin | rule | advice | Stäm av planbestämmelserna för lokalens exakta läge och eventuell påverkan av köksventilation, imkanal, skyltning eller fasadändringar. Om bygglov krävs ska användningen följa detaljplanen; fasadändringar kan också vara lovpliktiga. PBL 9 kap. 15 och 56 §§ | – |
| librobak-bostader | address | procedure | advice | Ta fram fastighetsbeteckningen för Ullforsgatan 5E och be Uppsala kommun bekräfta vilken detaljplan och vilken zon som gäller för just fastigheten. Kommunens sida för en Librobäcksplan anger stadsbyggnadsförvaltningens kontaktväg | – |
| norby-attefall | pin | rule | statement | Om villkoren för undantaget är uppfyllda krävs normalt varken bygglov eller anmälan för själva nybyggnaden. Anmälan krävs dock för vissa andra arbeten, exempelvis installation av vatten eller avlopp | – |
| norby-attefall | pin | rule | advice | Bygg inte innan kommunen har lämnat startbesked när åtgärden kräver lov eller anmälan | – |
| trevlinge-tillbyggnad | pin | rule | statement | Om villkoren för bygglovsbefrielse inte är uppfyllda behöver ni söka bygglov. Bygglovspliktiga åtgärder får inte påbörjas innan startbesked | – |
| slassbo-nytt-hus | pin | rule | statement | Om byggplatsen är brukningsvärd jordbruksmark är det en särskild begränsning: sådan mark får tas i anspråk för bebyggelse bara om ett väsentligt samhällsintresse kräver det och behovet inte kan lösas på annan mark. Det är inte fastställt här om den tänkta byg… | – |
| kungsangsgard-nytt-hus | pin | procedure | advice | Om huset är tänkt som bostad för någon som behövs i jordbruksdriften: sök först **förhandsbesked** för lokaliseringen. Uppsala kommun anger att förhandsbesked ofta används för enbostadshus utanför detaljplan; därefter söks bygglov för husets utformning | – |
| kungsgatan-pabyggnad | pin | rule | statement | En påbyggnad som ökar byggnadens volym är en tillbyggnad. Bygglov krävs enligt PBL 9 kap. 9 §; undantaget för vissa mindre tillbyggnader har bland annat villkoret att tillbyggnaden inte överstiger byggnadens taknock | – |
| kungsgatan-pabyggnad | address | rule | statement | En påbyggnad är en tillbyggnad; PBL 9 kap. 9 § säger: ”Det krävs bygglov för tillbyggnad.” | – |
| kungsgatan-pabyggnad | address | place | hedge | Uppsala har en detaljplan för del av kvarteret Bredablick vid Kungsgatan, men jag har inte kunnat bekräfta att adressen 63B ligger inom den eller vilken fastighetsbeteckning adressen motsvarar. Planbeskrivningen nämner Dragarbrunn 5:6 och en del av 5:5 | – |
| dalbysaby-bastu | address | place | hedge | Jag har inte kunnat knyta adressen *Dalby-Säby 62* säkert till en fastighetsbeteckning eller avgöra om bastuplatsen ligger inom strandskydd, en tidigare beslutad tomtplats eller en detaljplan. Planen jag hittade gäller ett område cirka 500 meter nordväst om D… | – |
| fansta-flerbostadshus | address | contact | hedge | Underlaget visar inte säkert vilken fastighet eller planzon adressen avser. Därför går det inte att ge ett bestämt besked om byggrätt, byggnadsstorlek eller om en planändring krävs. Uppsala kommuns Kontaktcenter kan hjälpa till att hitta en handläggare på sta… | – |
| valsatra-carport | address | rule | statement | Om villkoren för undantag inte är uppfyllda krävs bygglov för nybyggnad | – |
| gottsunda-inglasning | pin | rule | advice | Hantera också föreningens interna beslut och tekniska granskning. Om en bostadsrättshavare själv gör en väsentlig förändring av lägenheten eller påverkar brandskyddet kräver bostadsrättslagen styrelsens tillstånd | – |
| gottsunda-inglasning | address | contact | hedge | Jag kan inte med underlaget fastställa fastighetens detaljplan, om balkongerna vetter mot allmän plats eller om byggnaden har särskilt skyddsvärde. Därför går det inte att ge ett säkert ja eller nej om bygglov för just August Södermans väg 100. Uppsala kommun… | – |
| librobak-bostader | address | rule | advice | Om tomten ligger i JKLG-området är nästa möjliga väg att fråga kommunen om den är beredd att pröva ändrad markanvändning genom detaljplan. PBL anger att detaljplan ska användas för vissa nya eller förändrade bebyggelsesituationer, bland annat när samordning e… | – |
| librobak-bostader | address | contact | advice | Kontakta Uppsala kommuns Kontaktcenter på **018-727 00 00** eller stadsbyggnadsförvaltningen på **stadsbyggnadsforvaltningen@uppsala.se** och be om planbesked eller besked om gällande plan | – |
| slassbo-nytt-hus | address | place | statement | Översiktsplanen nämner strandskydd i delar av Järlåsa och ett utökat byggnadsförbud på 30 meter vid väg 72. Det behöver kontrolleras om något av detta berör tomten | – |
| slassbo-nytt-hus | address | procedure | statement | Redovisa VA-lösning i förhandsbeskedet om kommunalt VA saknas | – |
| kungsgatan-pabyggnad | pin | rule | hedge | Jag kan inte avgöra om just huset redan ligger vid planens våningsgräns utan att veta dess nuvarande våningsantal och stämma av byggnadens läge mot plankartans exakta zon. Fastigheten ligger också i vattenskyddsområde; om arbetena innebär en åtgärd som område… | – |
| kungsgatan-pabyggnad | address | rule | statement | En påbyggnad med en våning kräver bygglov. PBL 9 kap. 9 § säger: ”Det krävs bygglov för tillbyggnad.” | – |
| dalbysaby-bastu | address | number | advice | Om platsen omfattas av strandskydd, sök dispens innan du bygger. Kommunens angivna avgift för en mindre åtgärd, exempelvis en komplementbyggnad inom tidigare beslutad tomtplats, är 7 340 kronor | – |
| gottsunda-inglasning | address | contact | advice | Jag har inte kunnat verifiera den exakta detaljplanen eller om de berörda balkongerna vetter mot allmän plats. Be kommunens bygglovsvägledning kontrollera fastigheten och fasaderna: 018-727 00 00 eller bygglov-kontaktcenter@uppsala.se | – |
| falhagen-fasad | pin | rule | statement | PBL 9 kap. 15 § kräver bygglov när en fasadändring görs på en byggnad inom detaljplan och fasaden vetter mot allmän plats | – |
| norby-attefall | pin | procedure | hedge | Underlaget visar inte om huset ska vara en bostad eller en komplementbyggnad, vilken befintlig byggnad det ska komplettera, vilka byggnader som redan räknas in på tomten eller den tänkta placeringen. Strandskyddet är inte kontrollerat i platsunderlaget. Uppsa… | – |

## Flagged, not audited



| Case | Condition | Kind | Form | Claim | What the sources do not state |
|---|---|---|---|---|---|
| kvarnbo-gaststuga | address | – | – | Kontrollera om **Kvarnbo 25** ligger inom Kvarnbo-planen och vilket skydd som gäller. Planens karta visar dess geografiska avgränsning och zoner, men adressen har inte kunnat kopplas säkert till en viss zon | – |
| kvarnbo-gaststuga | address | – | – | Kontrollera hur stor den sammanlagda byggnadsarean för befintliga komplementbyggnader redan är och stäm av villkoren med Uppsala kommuns Bygglovhjälpen innan du beställer eller börjar bygga. Kommunens vägledning hänvisar dit för besked om lov eller anmälan | – |
| gottsunda-inglasning | address | – | – | Ta fram en gemensam lösning för fasadens utseende och brandskydd innan ansökan. Om lov redan har beviljats för en lösning kan ändringar ofta kräva ett nytt lov | – |
| flogsta-restaurang | address | – | – | Be Uppsala kommuns bygglovsvägledning kontrollera detaljplanen och tidigare lov för lokalen, och fråga om ändrad användning kräver bygglov. Kommunen anger telefon | – |
| norby-attefall | pin | – | – | Stäm av projektet med Uppsala kommuns Bygglovhjälpen innan byggstart. Kommunen hänvisar också till att en anmälan kan behövas för vissa installationer, exempelvis vatten eller avlopp | – |

## Facts without a citation

The check found a rule, number, fee or deadline with no source.

| Case | Condition | Kind | Form | Claim | What the sources do not state |
|---|---|---|---|---|---|
| kvarnbo-gaststuga | pin | rule | statement | En gäststuga på 25 m² kan vara bygglovsbefriad på den här fastigheten, men bara om den uppfyller villkoren för en komplementbyggnad – och naturreservatet och fornlämningarna gör att lovbefrielse inte räcker för att börja bygga | conditions under which a 25 m² cabin is bygglovsbefriad as komplementbyggnad |
| kvarnbo-gaststuga | address | rule | hedge | – En gäststuga på 25 m² kan vara bygglovsbefriad, men jag kan inte säkert fastställa från adressen | no source states a 25 m² guest cottage may be exempt from building permission |
| slottsgatan-kallare | address | rule | advice | Börja inte gräva innan lov eller anmälan, startbesked och eventuella beslut enligt miljöbalken är klara | no source cited for requirement to await lov, anmälan, startbesked and miljöbalk decisions |
| slottsgatan-kallare | address | rule | advice | Om fornlämning kan beröras: kontakta Länsstyrelsen före projekteringens slut och innan markarbeten | no source cited; contact before end of projektering and before markarbeten not stated |
| kungsgatan-pabyggnad | address | rule | hedge | — en extra våning kan bara godkännas om den stämmer med detaljplanen för fastigheten och uppfyller kraven på byggnaden; jag kan inte fastställa vilken detaljplan som gäller för just Kungsgatan 63B i underlaget | No source given; no place data states which detaljplan applies or its requirements |
| bjorklinge-avstyckning | pin | procedure | statement | Lantmäteriet prövar om den nya fastigheten uppfyller fastighetsbildningslagens villkor | no source or place data states Lantmäteri­et examines FBL conditions |
| valsatra-carport | address | rule | hedge | Oklart – men en carport kan ofta byggas utan bygglov om den uppfyller villkoren och detaljplanen för fastigheten tillåter placeringen | Ingen källa och ingen platsdata stöder påståendet om carports bygglovsfrihet |
| falhagen-fasad | pin | rule | statement | – Ja, bygglov krävs sannolikt för att måla om fasaden och byta fönster mot gatan | sources only list bygglov generally; nothing states painting facade and replacing street-facing windows specifically requires it |
| falhagen-fasad | address | rule | statement | – att fasaden vetter mot gatan innebär inte i sig att bygglov krävs, men bygglov kan krävas om huset eller området är särskilt värdefullt eller omfattas av skyddsbestämmelser | No source given; sources elsewhere do not state that a street-facing facade is itself irrelevant to permit requirements |
| flogsta-restaurang | address | place | hedge | Detaljplanen för kvarteret Hindsgavl medger restaurang som centrumverksamhet i vissa bottenvåningar, men jag kan inte säkert slå fast att just Köpenhamnsgatan 2 ligger i den aktuella planens zon | No source given; planbeskrivningen not cited to show restaurant allowed or which zone covers the address |
| norby-attefall | pin | rule | statement | – ett attefallshus kan vara bygglovsbefriat på den här fastigheten, men bara om det uppfyller villkoren nedan och faktiskt kompletterar en byggnad på den tomt där det placeras | ingen källa för att attefallshus kan vara bygglovsbefriat eller kravet att komplettera en byggnad på tomten |
| norby-attefall | pin | none | advice | Kontrollera med Uppsala kommun vilken tomt byggnaden skulle stå på och om den byggnad som ska kompletteras samt tidigare komplementbyggnader innebär att 45 m²-gränsen redan är helt eller delvis utnyttjad | – |
| trevlinge-tillbyggnad | pin | rule | statement | — En tillbyggnad på 25 m² behöver sannolikt inte bygglov, om den uppfyller villkoren nedan och inget särskilt skydd för byggnaden eller området utlöser lovplikt | no source states the conditions under which a 25 m² extension is exempt from bygglov |
| trevlinge-tillbyggnad | address | rule | statement | En tillbyggnad på 25 m² kan normalt göras utan bygglov enligt reglerna som gäller sedan 1 december 2025, men vissa plats- och utformningsvillkor kan ändå göra bygglov eller anmälan nödvändig | ingen källa för 25 m²-regeln, datumet 1 december 2025 och plats-/utformningsvillkoren |
| trevlinge-tillbyggnad | address | – | – | Om villkoren ovan är uppfyllda behövs normalt inget bygglov för 25 m². | – |
| kvarnbo-gaststuga | address | rule | statement | En gäststuga på 25 m² kan normalt byggas utan bygglov, men det beror på byggnadens placering, stugans höjd och hur mycket komplementbyggnad som redan finns på tomten | Ingen källa: ingen källa anger att 25 m² normalt kräver bygglov eller vad detta beror på |
| slottsgatan-kallare | pin | place | hedge | Den pinnade informationen anger bostadsområde B, men plankartans avläsning kring beteckningen S:4 verkar visa en annan planzon | no source; place data states zone B, nothing states the plankarta shows another zone |
| kungsgatan-pabyggnad | address | place | hedge | – en extra våning kräver normalt bygglov, men jag kan inte avgöra om den får plats inom den detaljplan som gäller för just Kungsgatan 63B | No source states an extra storey normally requires bygglov or that plan applicability is undetermined |
| valsatra-carport | pin | rule | statement | Om villkoren för bygglovsbefrielse inte är uppfyllda behöver du söka bygglov | – |
| valsatra-carport | address | place | hedge | – en carport kan vara bygglovsfri, men jag kan inte bekräfta exakt vilken detaljplan som gäller för Linrepevägen 8 eller var på tomten den kan placeras | no source states which detaljplan applies to Linrepevägen 8 or where a carport may be placed |
| falhagen-fasad | pin | rule | statement | Ja, ni behöver sannolikt bygglov för att byta fasadfärg och för fönsterbyte som ändrar fasadens yttre karaktär, eftersom det gäller ett flerbostadshus i detaljplan och fasaden vetter mot gatan | no source given; place data does not state the building is a flerbostadshus or that its facade faces a street |
| falhagen-fasad | address | rule | advice | Räkna med att ni behöver bygglov för fasadfärgsbytet och för fönsterbytet om det förändrar fasadens yttre karaktär — särskilt eftersom fasaden vetter mot gatan | no source states that paint or window changes require bygglov on this property |
| falhagen-fasad | address | rule | statement | Exakt lovplikt beror på detaljplanen och om byggnaden eller området är särskilt värdefullt | no source states that the exact permit duty depends on the detaljplan and special value |
| falhagen-fasad | address | rule | advice | Skicka in en bygglovsansökan till Uppsala kommun om fasaden vetter mot gatan inom detaljplan, eller om byggnaden/området har särskilt skyddsvärde | no source states when a bygglovsansökan to Uppsala kommun must be submitted |
| librobak-bostader | address | rule | summary | Bedömning: Oklart – men om tomten omfattas av detaljplanen för kvarteren Harg och Hållnäs med flera är nya bostäder inte tillåtna enligt planens angivna markanvändning. | No source given; whether the property is covered by the plan and that dwellings are disallowed |
| norby-attefall | address | rule | hedge | — ett attefallshus i Uppsala kan i princip uppföras utan bygglov, men jag kan inte säkert fastställa vilken detaljplan som gäller just Eksoppsvägen 37 eller om tomten uppfyller villkoren | source for attefallshus without bygglov; no source for applicable plan or plot conditions |
| trevlinge-tillbyggnad | pin | rule | statement | En tillbyggnad på 25 m² kan vara bygglovsbefriad, men bara om villkoren nedan är uppfyllda | no source given for when a 25 m² extension is exempt from building permit |
| trevlinge-tillbyggnad | pin | rule | advice | Kontrollera att 25 m² avser bruttoarea/öppenarea och räkna in tidigare tillbyggnader | no source states the gross/open area definition and prior extensions must be counted |
| trevlinge-tillbyggnad | pin | procedure | advice | Kontrollera med byggnadsnämnden i Uppsala om huset eller platsen omfattas av särskilt värdeskydd enligt PBL 9 kap. 37 § | no source states the kommun must confirm PBL 9 kap. 37 § special value protection |
| trevlinge-tillbyggnad | address | rule | statement | — En tillbyggnad på 25 m² behöver normalt inte bygglov om den uppfyller villkoren nedan, men plats- och byggnadsspecifika undantag kan ändå göra att lov krävs | No source given for the 25 m² exemption or its exceptions |
| trevlinge-tillbyggnad | address | rule | advice | Kontrollera om tidigare tillbyggnader på huset gör att den sammanlagda arean överstiger 30 m² och att den planerade delen inte blir högre än husets taknock | No source given for the 30 m² total area and taknock conditions |
| kvarnbo-gaststuga | pin | – | – | Kontrollera att 25 m² avser **byggnadsarea** och räkna in befintliga komplementbyggnader på tomten mot 65 m²-gränsen | – |
| kvarnbo-gaststuga | address | rule | statement | En gäststuga på 25 m² kan vara bygglovsbefriad, men ytan ensam avgör inte saken | No source given; other conditions (height, distance, existing area) unstated |
| kungsgatan-pabyggnad | address | rule | statement | Om planen inte medger den extra våningen kan påbyggnaden inte bedömas som genomförbar enligt nuvarande plan utan att kommunen först prövar en planändring | no source given for needing a plan change before assessment |
| dalbysaby-bastu | address | rule | statement | – men en bastu nere vid sjön kan kräva strandskyddsdispens även om den är liten och inte kräver bygglov | no source is cited for this permit requirement |
| fansta-flerbostadshus | address | rule | hedge | — nybyggnad kräver bygglov, men det går inte att avgöra från adressen ensam vilken planbestämmelse som gäller för just fastigheten | no source states that nybyggnad requires bygglov or that an address alone cannot determine the applicable plan rule |
| fansta-flerbostadshus | address | rule | statement | Planerna kring Fanstavägen skiljer sig åt; ett större flerbostadshus kan därför kräva en ny detaljplan | no source states the plans differ or that a larger multi-dwelling house may require a new detailed plan |
| valsatra-carport | address | – | – | Kontrollera detaljplanen för fastigheten och räkna in befintliga friggebodar, garage och andra komplementbyggnader i den sammanlagda ytan | – |
| valsatra-carport | address | rule | advice | Om den inte klarar villkoren för bygglovsbefrielse, sök bygglov innan byggstart | no source for applying for the permit before construction starts |
| gottsunda-inglasning | pin | rule | statement | Ni kan sannolikt glasa in balkongerna, men bygglov behövs för de balkonger på flerbostadshuset som vetter mot allmän plats, och föreningen behöver samordna utformningen | No sources; coordination requirement and permit claim unstated anywhere given |
| falhagen-fasad | address | rule | statement | Troligen behövs bygglov för att måla om fasaden och byta fönstren mot Torkelsgatan, eftersom det är ett flerbostadshus och arbetet gäller en fasad mot gatan | Ingen källa; källor anger inte bygglovskrav för denna fasad eller egenskaper om huset |
| flogsta-restaurang | pin | rule | advice | Om användningen ändras väsentligt, sök bygglov innan ni börjar använda lokalen som restaurang | no source states that bygglov must precede use of the premises as a restaurant |
| flogsta-restaurang | address | rule | statement | Om lokalen exempelvis är godkänd för bostad eller annan användning kan restaurang därför kräva bygglov | No source states when a restaurant use requires bygglov |
| norby-attefall | address | rule | hedge | Ett attefallshus kan vara bygglovsbefriat, men jag kan inte bekräfta från kommunens underlag vilken detaljplan och vilka planbestämmelser som gäller just Eksoppsvägen 37 | no source states an attefallshus can be bygglovsbefriat |
| trevlinge-tillbyggnad | address | rule | statement | En tillbyggnad på 25 m² kan vara bygglovsbefriad, men bara om arean och övriga villkor i PBL är uppfyllda och inget särskilt undantag kräver lov | ingen källa anger att 25 m²-tillbyggnad kan vara bygglovsbefriad under villkor |
| trevlinge-tillbyggnad | address | rule | advice | Kontrollera att 25 m² avser bruttoarea/öppenarea och räkna med tidigare tillbyggnader som omfattas av 30 m²-gränsen | källa som säger att 25 m² får räknas som bruttoarea/öppenarea och att tidigare tillbyggnader ska tas med |

## Claims the check passed and the auditor did not

The check says supported, the auditor finds none of the facts in the cited sources. These reach the user unflagged.

| Case | Condition | Kind | Form | Claim | What the sources do not state |
|---|---|---|---|---|---|
| dalbysaby-bastu | pin | rule | advice | Kontrollera separat med bygglovsenheten om bastun kräver bygglov utifrån storlek, höjd och om den kompletterar en befintlig byggnad. Även om bygglov inte krävs kan strandskyddsdispens fortfarande behövas | Sources do not tell the user to contact the bygglovsenheten or that strandskydd dispens may still be needed |
