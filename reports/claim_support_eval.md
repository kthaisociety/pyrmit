# Claim support: what the live claim check finds, and what is behind it

Result files: `place-answers-20261118-185043-claim-support-neon.json`. Run 2026-11-18T18:50:44+01:00, agent openai/gpt-6-luna, judge xiaomi/mimo-v2.6-flash, corpus neon.

Every factual claim of each answer was put to the chat's live claim check (`agentic/claim_check.py`): a claim is **supported** when the decision model says the chunks it cites (or the pinned place's data) back it, **unsupported** when it cites a source that does not, and **uncited** when it states a rule, number, fee or deadline with no citation. Advice and questions are not claims.

## Headline

| Condition | Answers checked | Claims | Supported | 95 % interval | Unsupported | Uncited | Answers with no flag | Flags per answer | Checks failed |
|---|---|---|---|---|---|---|---|---|---|
| pin | 45 / 45 | 290 | 80% | 75%–85% | 13% | 7% | 27% | 1.3 | 0 |
| address | 45 / 45 | 284 | 65% | 60%–71% | 21% | 13% | 12% | 2.4 | 0 |

The interval comes from resampling the answers (an answer's claims stand or fall together). “Answers checked” leaves out answers that were a question back to the user or an error. “Answers with no flag” is over the answers that make at least one claim.

## Findings

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

## What the numbers suggest

1. **The check flags claims its sources do back.** The auditor finds 30 of the 98 claims flagged unsupported (31%) fully backed by their cited sources. Read those (section *Flags the auditor disagrees with*) before trusting the unsupported share, and see whether the decision model's threshold (`SUPPORTED_AT` in `claim_check.py`) or its question wording is too strict.
2. **57 of the 155 flagged claims (37%) tell the user what to do** (60% of all such claims are supported). Leave pure advice out of the check, as generic advice already is, and judge only the fact attached to it; or have the answer keep the next steps apart from the facts they rest on, each fact with its own citation.
3. **Contact details are flagged** (40% of 15 supported): the telephone number or address is not in the chunk the sentence cites. Have the agent cite the page the contact details come from, or keep them out of the answer unless a source read states them.
4. **Claims of kind “procedure” are the weakest facts**: 66% of 90 supported, and the auditor agrees on 24 of the flags. This is where the agent states more than its source says: read the `missing` column of those claims for what it adds (a number, a section reference, a condition), and tighten the answer format on it (quote the figure, cite the chunk that holds it).
5. **“pin” answers are better supported than “address” answers** (80% against 65%); the intervals do not overlap.
6. **57 claims (10%) state a fact without a citation.** The answer format asks for a citation on every rule, number and fee: check which of them repeat a fact cited elsewhere in the answer (harmless, see the summary line above) and which are new facts.

## What kind of claim is supported

A second model (`xiaomi/mimo-v2.6-flash`, another family than the agent and the decision model) read 573 of the 574 claims next to the full text of their cited chunks and the place data, and labelled each. The support shares below are still the live check's.

| Kind of claim | Claims | Supported | Unsupported | Uncited |
|---|---|---|---|---|
| rule | 361 | 78% | 9% | 13% |
| procedure | 90 | 66% | 32% | 2% |
| place | 80 | 70% | 24% | 6% |
| number | 19 | 74% | 26% | 0% |
| contact | 15 | 40% | 60% | 0% |
| none | 8 | 25% | 25% | 50% |

rule = a legal rule or permit requirement; number = a measure, limit, fee, deadline or date; place = a fact about the property; procedure = what the kommun requires or how to apply; contact = contact details; none = no factual content of its own.

| Form of claim | Claims | Supported | Unsupported | Uncited |
|---|---|---|---|---|
| statement | 388 | 81% | 12% | 8% |
| advice | 144 | 60% | 30% | 10% |
| hedge | 33 | 48% | 24% | 27% |
| summary | 8 | 25% | 25% | 50% |

statement = states the fact plainly; advice = tells the user what to do, with or without a fact attached; hedge = says what could not be read or confirmed; summary = the verdict line or a recap.

| Cited source | Claims | Supported | Unsupported | Uncited |
|---|---|---|---|---|
| law | 302 | 91% | 9% | 0% |
| bygglov | 125 | 76% | 24% | 0% |
| detaljplan | 55 | 58% | 42% | 0% |
| oversiktsplan | 33 | 67% | 33% | 0% |
| strandskydd | 26 | 65% | 35% | 0% |
| other | 6 | 67% | 33% | 0% |
| avlopp | 4 | 75% | 25% | 0% |

A claim citing two kinds of source counts under both.

## Is the check right?

Over the 516 audited claims that cite a source:

| Check says | Auditor: backed | Auditor: partly | Auditor: not backed |
|---|---|---|---|
| supported | 321 | 95 | 2 |
| unsupported | 30 | 65 | 3 |

- **False flags**: 30 of 98 flagged claims are fully backed according to the auditor (31%).
- **Misses**: 2 of 418 passed claims are not backed at all according to the auditor (0%).
- **Partly backed**: 95 passed and 65 flagged claims hold one fact the source states and one it does not. The check has to call the whole stretch one way or the other, so the passed ones carry an unbacked detail to the user unflagged.

## Does the length of the stretch matter?

The check judges everything before a citation on a line as one claim.

| Stretch | Claims | Supported | Unsupported |
|---|---|---|---|
| 1 sentence | 76 | 86% | 14% |
| 2 sentences | 192 | 74% | 26% |
| 3 or more | 249 | 85% | 15% |

## Per case

Supported claims / claims, over the repeats.

| Case | pin | address |
|---|---|---|
| kvarnbo-gaststuga | 16 / 21 (76%) | 3 / 11 (27%) |
| kungsangsgard-nytt-hus | 23 / 26 (88%) | 14 / 20 (70%) |
| slottsgatan-kallare | 24 / 24 (100%) | 15 / 27 (56%) |
| kungsgatan-pabyggnad | 10 / 11 (91%) | 14 / 19 (74%) |
| bjorklinge-avstyckning | 22 / 25 (88%) | 7 / 10 (70%) |
| dalbysaby-bastu | 8 / 14 (57%) | 15 / 22 (68%) |
| fansta-flerbostadshus | 21 / 27 (78%) | 17 / 26 (65%) |
| valsatra-carport | 12 / 19 (63%) | 11 / 17 (65%) |
| gottsunda-inglasning | 16 / 18 (89%) | 21 / 22 (95%) |
| falhagen-fasad | 11 / 18 (61%) | 11 / 19 (58%) |
| flogsta-restaurang | 13 / 16 (81%) | 11 / 19 (58%) |
| librobak-bostader | 10 / 10 (100%) | 8 / 15 (53%) |
| norby-attefall | 13 / 16 (81%) | 20 / 28 (71%) |
| trevlinge-tillbyggnad | 12 / 20 (60%) | 13 / 23 (57%) |
| slassbo-nytt-hus | 22 / 25 (88%) | 6 / 6 (100%) |

## Per repeat

How much the share moves between runs of the same questions.

| Condition | repeat 0 | repeat 1 | repeat 2 |
|---|---|---|---|
| pin | 86% | 75% | 81% |
| address | 66% | 64% | 67% |

## Flagged and confirmed: claims that cite a source that does not state them

The check and the auditor agree. These are the claims to fix in the agent.

| Case | Condition | Kind | Form | Claim | What the sources do not state |
|---|---|---|---|---|---|
| kungsangsgard-nytt-hus | address | place | statement | Uppsala kommuns översiktsplan beskriver Kungsängens gård som ett område med bland annat biogasanläggning och vattenrening och säger att den pågående markanvändningen bör fortsätta. Den pekar också ut hänsyn till det närbelägna naturreservatet och landskapets… | Källan nämner vattenrening men inte biogasanläggning |
| kungsangsgard-nytt-hus | address | place | statement | Kommunens planeringsstrategi anger att Kungsängens gård kan fortsätta expandera med verksamheter som har omgivningspåverkan – inte bostäder. Översiktsplanen är vägledande, inte en bindande detaljplan, men den talar tydligt emot en ny bostad här | Källan säger inte att översiktsplanen är vägledande eller att den talar emot bostäder |
| kvarnbo-gaststuga | address | place | advice | Kontrollera med Uppsala kommun om just fastigheten Kvarnbo 25 ligger inom detaljplan eller något skyddat område. Kommunens detaljplan för Kvarnbo som jag hittade gäller ett område för ridhus och lager; kartan bekräftar inte att den omfattar din tomt | sources do not state that the map fails to confirm the plan covers the user's plot |
| slottsgatan-kallare | address | rule | statement | Om arbetet väsentligt påverkar husets bärande delar krävs anmälan enligt PBF 6 kap. 1 §. Börja inte innan kommunen har gett startbesked. Schakt under befintliga grundmurar kräver därför projektering av en konstruktör och sannolikt geoteknisk kompetens | sources do not state that excavation under existing foundation walls requires a constructor's design and geotechnical competence |
| slottsgatan-kallare | address | procedure | advice | Be Uppsala kommun bekräfta fastighetsbeteckningen, vilken detaljplan och plankartzon som gäller för huset samt om byggnaden har skyddsbestämmelser. Kommunen hänvisar till bygglovsvägledarna för sådan vägledning | sources do not say the kommun confirms property designation, applicable plan, zone or protection provisions |
| slottsgatan-kallare | address | number | advice | Stäm av med kommunen om ni behöver **anmälan, bygglov eller marklov**, och om dispens enligt vattenskyddsföreskrifterna behövs. Uppsala anger att ett komplett lovärende normalt beslutas inom 10 veckor och ett startbesked för anmälan normalt inom 4 veckor | sources do not mention dispens under water protection regulations |
| bjorklinge-avstyckning | pin | procedure | advice | Om beskedet är positivt, ansök om avstyckning hos Lantmäterimyndigheten i Uppsala kommun. Därefter behövs bygglov för huset. Kommunens blankett och ansökningsväg finns på dess sida om lantmäteriförrättning | sources do not state the order between förhandsbesked, avstyckning and bygglov |
| kungsgatan-pabyggnad | address | procedure | advice | Låt en arkitekt ta fram förslag med sektioner, fasader och uppgifter om höjd och area; kommunen anger att ritningar och kontrollplan hör till ansökan och att en kontrollansvarig kan behövas för mer komplicerade projekt | source does not say an architect should prepare sections, facades, height and area data |
| dalbysaby-bastu | address | number | statement | Uppsala kommun anger att strandskyddet vanligtvis omfattar 100 meter från strandkanten, men på vissa platser 300 meter. Jag kan inte fastställa exakt strandskyddsgräns eller detaljplan för platsen utifrån “Dalby-Säby 62” | Source does not state that the exact strandskyddsgräns and detaljplan cannot be determined from 'Dalby-Säby 62' |
| dalbysaby-bastu | address | procedure | advice | Om platsen är strandskyddad: sök dispens hos Uppsala kommun innan du bygger. Ansökan ska bland annat beskriva bastuns placering och utformning, platsens nuvarande användning och hur påverkan på växt- och djurliv samt allmänhetens tillgång begränsas. Bifoga si… | Sources do not state applying before building, nor attaching situationsplan, översiktskarta and photos |
| dalbysaby-bastu | address | rule | advice | Kontrollera separat om bygglov krävs och om platsen omfattas av annat skydd. I statligt skyddade områden kan länsstyrelsen besluta om strandskyddsdispens | Source does not say to check separately whether bygglov is required or other protection applies |
| fansta-flerbostadshus | address | procedure | advice | Stäm av om den aktuella zonen medger flerbostadshus innan ni tar fram ett fullständigt förslag. Om planen inte medger användningen kan en planändring behövas; kommunens bygglovssida säger att handläggaren kan diskutera alternativa lösningar om förslaget inte… | No source states a planändring may be needed if plan forbids the use |
| gottsunda-inglasning | pin | rule | statement | Om inglasningen påverkar exempelvis brandskydd, ventilation eller bärande konstruktion kan en anmälan också behövas | källan nämner inte brandskydd, ventilation, bärande konstruktion eller anmälan i sådana fall |
| falhagen-fasad | pin | rule | statement | Fastigheten ligger inom detaljplan och åtgärden gäller en byggnad med bostäder. PBL kräver bygglov för fasadändring på en sådan byggnad när ändringen görs på en fasad som vetter mot allmän plats. Att ändra färgen och fönstrens utseende talar för att det är en… | exemption for one/two-dwelling houses; that colour and window changes count as a fasadändring |
| falhagen-fasad | pin | procedure | advice | Ansök om bygglov hos Uppsala kommun innan arbetet påbörjas. Kommunens bygglovsvägledning kan hjälpa er att stämma av vad ansökan behöver innehålla | that the application must be submitted before work begins |
| gottsunda-inglasning | address | rule | advice | Föreningen bör dessutom fatta beslut om en gemensam utformning och ordna föreningens godkännande innan arbetet beställs. Kommunens ritningsunderlag anger som exempel att utseendet ska likna befintliga inglasningar i samma hus | Source does not mention a förening decision or its approval before ordering work |
| valsatra-carport | address | procedure | advice | Om carporten inte uppfyller undantagsvillkoren, eller omfattas av krav på bygglov på grund av placering eller särskilda planbestämmelser, ansök hos Uppsala kommun. Börja inte en lov- eller anmälningspliktig åtgärd innan kommunen har gett startbesked | that the application is to be made to Uppsala kommun |
| flogsta-restaurang | pin | procedure | advice | Beskriv befintlig och planerad användning samt eventuella ändringar av planlösning, fasad, ventilation och brandskydd. Om bygglov behövs anger kommunens ansökningsunderlag att ändrad användning kan tas upp i ansökan | Source lists application items but does not state that changed use can be included in the application |
| kungsangsgard-nytt-hus | address | place | statement | Uppsala kommuns översiktsplan beskriver Kungsängens gård som ett verksamhetsområde med bland annat biogasanläggning och vattenrening, och anger att den pågående markanvändningen bör fortsätta. Det är en tydlig negativ signal för bostäder, men översiktsplanen… | Ingen källa säger att planen är en negativ signal för bostäder eller att den inte avgör bygglovet |
| kungsangsgard-nytt-hus | pin | place | summary | Fastigheten är stor och den tänkta byggplatsen är inte angiven. Skydden och översiktsplanens inriktning gör att läget och husets koppling till gårdens verksamhet kan vara avgörande; översiktsplanen pekar i nuläget tydligare mot fortsatt verksamhetsanvändning… | that location and link to the yard's operations may be decisive; clearer to commercial use than new housing |
| kvarnbo-gaststuga | address | place | hedge | Uppsala-planen jag hittade för Kvarnbo gäller ett område omedelbart norr om Kvarnbo gård och avser en ridanläggning. Det går därför inte att slå fast att den omfattar just din tomt utifrån uppgiften ”Kvarnbo 25” | Source does not state the plan area lies immediately north of Kvarnbo gård |
| kungsgatan-pabyggnad | pin | rule | statement | En påbyggnad är normalt en tillbyggnad. PBL 9 kap. 9 § säger: ”Det krävs bygglov för tillbyggnad.” Det begränsade undantaget för vissa tillbyggnader gäller bara när tillbyggnaden inte överstiger byggnadens taknock; det verkar därför inte passa om ni höjer hus… | that a påbyggnad counts as tillbyggnad; exemption also requires area at most 30 m² |
| slottsgatan-kallare | address | place | statement | En detaljplan för Fjärdingen 12:3 vid Övre Slottsgatan beskriver att man hittat lämningar från det medeltida Uppsala på fastigheten och att grundläggning ska ske ovanför kulturlager utan att bryta igenom dem. Om er adress ligger på den fastigheten är detta en… | that the finding constitutes a significant limitation for excavation under the house |
| slottsgatan-kallare | address | rule | statement | Den lokala planbeskrivningen pekar på både lera och sand/grus, samt risk för uttorkning av lerlager och sättningar vid bortledning av vatten. Om utgrävningen kräver bortledning av grundvatten räknas det som vattenverksamhet; tillstånd eller anmälan kan krävas… | plan risk of drying out of clay layers and settlement when water is diverted |
| slottsgatan-kallare | address | procedure | advice | Kontakta kommunens bygglovsenhet och Länsstyrelsen tidigt, innan ni låser utformningen. Uppsala kommun anger att även åtgärder utan bygglov eller anmälan måste uppfylla varsamhetskravet och övriga tekniska krav | advice to contact the bygglovsenhet and Länsstyrelsen early |
| kungsgatan-pabyggnad | address | rule | statement | Uppsala kommun anger också att platsens detaljplan, byggnadens eller områdets särskilda värden och tidigare bygglov behöver kontrolleras. En påbyggnad kan dessutom kräva anmälan om den påverkar exempelvis bärande konstruktion eller brandskydd | särskilda värden, tidigare bygglov och anmälan vid bärande konstruktion eller brandskydd |
| dalbysaby-bastu | pin | rule | statement | Dispens kräver ett särskilt skäl. Ett skäl kan vara att platsen redan är ianspråktagen som etablerad tomtplats och saknar betydelse för strandskyddets syften. En vanlig privat bastu är däremot inte i sig en vattenberoende anläggning. Kommunen anger också att… | that an ordinary private sauna is not in itself a water-dependent facility |
| dalbysaby-bastu | pin | procedure | advice | Kontrollera separat med bygglovsenheten om bastun uppfyller bygglovsundantaget. Uppsala publicerar en avgift på 7 340 kr för vissa mindre strandskyddsärenden, exempelvis komplementbyggnad inom en tidigare beslutad tomtplats, men underlaget visar inte vilken a… | the advice to check with the building permit unit whether the sauna meets the exemption |
| bjorklinge-avstyckning | pin | rule | advice | Den utpekade lämningen Björklinge 348 och riksintresset för kulturmiljö gör placering och utformning särskilt viktiga. Riksintresset ska skyddas mot åtgärder som kan påtagligt skada kulturmiljön (MB 3 kap. 6 §). För lämningen bör läget och eventuella markarbe… | sources do not say to check the remains' position with kommun and Länsstyrelsen |
| bjorklinge-avstyckning | pin | procedure | advice | Be Uppsala kommun om förhandsbesked för ett hus på en tydligt markerad plats. Redovisa tänkt tillfart och VA-lösning; kommunen anger att VA-förutsättningarna ska vara säkerställda i förväg | sources do not say the intended access (tillfart) must be presented |
| fansta-flerbostadshus | pin | place | statement | Uppsala kommuns översiktsplan anger att Lövstalöt bör få endast en mindre utveckling av bostäder under planperioden och att större expansion kräver programstudier med ett helhetsgrepp. Den nämner också pågående planläggning vid Fansta för cirka 130 bostäder.… | Fansta-planläggning 130 bostäder och att översiktsplanen är vägledande, inte byggrätt |
| fansta-flerbostadshus | pin | procedure | advice | Ta fram en tidig skiss med ungefärligt antal bostäder, höjd och placering samt trafik, parkering, dagvatten och vatten/avlopp. Be kommunen och Uppsala Vatten bedöma kapacitet och anslutningsmöjlighet. Översiktsplanens uppgift om VA-kapacitet gäller orterna sa… | översiktsplanens uppgift om VA-kapacitet och att den gäller orterna sammantaget |
| dalbysaby-bastu | address | procedure | advice | Be Uppsala kommun kontrollera strandskyddet, eventuell utvidgning, detaljplan och om platsen redan ingår i en beslutad tomtplats. Kommunen handlägger normalt dispens; om området också har statligt områdesskydd kan Länsstyrelsen besluta | att Länsstyrelsen besluter när området även har statligt områdesskydd |
| fansta-flerbostadshus | address | rule | statement | Om fastigheten ligger i Fansta 3:1 behöver också planens förutsättningar för dagvatten, begränsad infiltration, kommunalt VA och radonsäker grundläggning beaktas. Planbeskrivningen anger att geotekniska förhållanden och radon ska undersökas för ny bebyggelse… | geoteknik, radon och radonsäker grundläggning anges för 504/504B och Fansta 2:2, ej Fansta 3:1 |
| valsatra-carport | address | contact | statement | Uppsala kommuns bygglovsvägledning nås på | source contains no contact details for bygglovsvägledning |
| falhagen-fasad | address | contact | advice | Om bygglov krävs, ansök innan arbetet påbörjas. Uppsala kommun anger telefon 018-727 00 00 och e-post bygglov-kontaktcenter@uppsala.se för bygglovsvägledning | Source gives phone and e-mail but does not state to apply before work begins |
| falhagen-fasad | pin | contact | statement | Kommunen behöver också bedöma om färg- och fönsterändringarna följer detaljplanen och varsamhetskraven. Uppsala bygglovsvägledning nås på 018-727 00 00 eller bygglov-kontaktcenter@uppsala.se | that the kommun must assess compliance with the detaljplan and the care requirements |
| norby-attefall | pin | rule | statement | Om något villkor för lovbefrielse inte uppfylls, eller en särskild bygglovsregel gäller, behöver du söka bygglov innan du bygger. Bygglov får inte påbörjas innan startbesked när åtgärden kräver lov eller anmälan. PBL 10 kap. 3 § | källan 10 kap. 3 § säger inte att uppfyllda lovbefrielsevillkor avgör om bygglov krävs |
| librobak-bostader | address | contact | advice | Om bostäder inte ryms inom den bestämmelse som gäller för just er fastighet, fråga kommunen om **planbesked** för att pröva en ändring av detaljplanen. Uppsala kommuns Kontaktcenter kan hjälpa er till stadsbyggnadsförvaltningen: 018-727 00 00 eller stadsbyggn… | Source does not mention planbesked as means to test a detail plan change |
| trevlinge-tillbyggnad | pin | procedure | advice | Be Uppsala kommuns bygglovsvägledning att kontrollera planens bestämmelser och om huset eller området omfattas av skydd. Kommunen hänvisar till Bygglovhjälpen och kan vägleda före ansökan | source only offers general vägledning and Bygglovhjälpen, not checking plan provisions or skydd |
| trevlinge-tillbyggnad | address | procedure | advice | Kontrollera med Uppsala kommun om fastigheten eller huset har särskilda plan- eller kulturmiljöbestämmelser, och om tidigare tillbyggnader räknas in i 30 m²-gränsen. Kommunens vägledning säger att lovbehovet beror bland annat på vad som redan byggts på tomten… | Källan nämner inte 30 m²-gränsen eller kulturmiljöbestämmelser |
| slassbo-nytt-hus | pin | rule | statement | Uppsala kommuns översiktsplan öppnar för enstaka småhus på landsbygden: ”Ny bostadsbebyggelse bör tillkomma i form av enstaka friliggande småhus”. Den ska samtidigt anpassas till befintligt bebyggelsemönster och landskap. Utanför kommunalt VA-område kräver ko… | att ny bostadsbebyggelse 'bör tillkomma i form av enstaka friliggande småhus' sägs inte i källan |
| slassbo-nytt-hus | pin | procedure | statement | Om huset ska ha WC och fastigheten behöver enskilt avlopp krävs tillstånd från Uppsala kommun. Kommunen uppger att väntan innan handläggning kan vara 10–20 veckor; platsens markförhållanden och brunnar påverkar vilken lösning som fungerar | att brunnar på platsen påverkar vilken avloppslösning som fungerar |
| norby-attefall | address | place | advice | Be Uppsala kommun bekräfta fastighetsbeteckning, detaljplan och om området är särskilt värdefullt. Kommunens planmaterial innehåller en detaljplan för Tryffelvägen, del av Norby 31:52, och plankartan visar också Eksoppsvägen; materialet räcker dock inte för a… | Eksoppsvägen i plankartan och kopplingen av adressnummer 37 till tomt och planzon |
| norby-attefall | address | rule | advice | Kontrollera tidigare byggnader på tomten och mät placering mot tomtgräns: de påverkar både den sammanlagda arean och om bygglov krävs. Uppsala kommun hänvisar till sin Bygglovhjälpen och sitt digitala bygglovsarkiv för dessa kontroller | att tidigare byggnader påverkar den sammanlagda arean; Bygglovhjälpen nämns inte |
| norby-attefall | address | number | summary | Det avgörande som återstår är om tomten omfattas av detaljplan och hur mycket av 45/65 m²-ramen som redan förbrukats. Uppsala kommun anger att det nya bygglovsregelverket gäller från 1 december 2025 | att 45 respektive 65 m² utgör gränsen för sammanlagd byggnadsarea |
| kvarnbo-gaststuga | pin | rule | statement | En byggnad med en självständig bostad räknas i stället som ett komplementbostadshus; även den omfattas av storleksvillkoret i paragrafen | sources define komplementbostadshus but do not state it is subject to the 9 kap. 5 § size conditions |
| kungsangsgard-nytt-hus | address | rule | statement | Om platsen ligger utanför detaljplan krävs bygglov och marken måste vara lämplig för bostad. Bygglov kan inte ges om åtgärden förutsätter detaljplanering eller strider mot andra tillämpliga regler. PBL 9 kap. 57 § | att bygglov krävs utanför detaljplan och att marken måste vara lämplig för bostad |
| slottsgatan-kallare | address | place | statement | Uppsala kommuns planmaterial för Övre Slottsgatan beskriver området som kulturhistoriskt värdefullt och anger att medeltida kulturlager kan finnas. Ett planmaterial för ett område vid gatan redovisar också lera och sand/grus, samt behov av särskild uppmärksam… | sources do not mention medieval cultural layers, clay, sand/gravel or foundation concerns |
| slottsgatan-kallare | address | place | advice | Låt en konstruktör och geotekniker utreda grundläggning, schaktstöd, grundvatten och risk för sättningar eller påverkan på grannhus. Kommunens planmaterial för området betonar geotekniska förutsättningar och vibrationer, men den exakta marken under ert hus må… | sources do not mention geotechnical conditions, vibrations or examining soil under the house |
| kungsgatan-pabyggnad | address | rule | statement | PBL anger: ”Det krävs bygglov för tillbyggnad.” En påbyggnad med en våning behöver därför prövas av kommunen | that kommunen prövar, and that a single added floor counts as tillbyggnad |
| dalbysaby-bastu | pin | rule | statement | Dispens kräver särskilda skäl. En etablerad tomtplats där marken redan är ianspråktagen kan tala för dispens; däremot behöver en privat bastu inte i sig ligga vid vattnet. Kommunen ska också beakta fri passage längs stranden och anger att det bör vara minst 1… | source does not say a private bastu need not be located by the water |
| dalbysaby-bastu | pin | procedure | advice | Om dispens behövs: ansök hos kommunen och visa bastuns exakta placering, avstånd till strand och hur fri passage och naturvärden bevaras. Avgiften är 7 340 kr för vissa mindre åtgärder, exempelvis en komplementbyggnad inom tidigare beslutad tomtplats; större… | cited source gives only 11 744 kr fee; no 7 340 kr fee, application step or documents to show |
| kungsangsgard-nytt-hus | pin | rule | statement | Det kan möjligen prövas om bostaden behövs för jordbrukets drift och placeras i direkt anslutning till brukningscentrum, men kommunens översiktsplan säger att markanvändningen kring Kungsängens gård bör fortsätta som idag | sources do not say a dwelling may be tested for farm operation or placement at brukningscentrum |
| valsatra-carport | pin | rule | statement | Även om carporten uppfyller undantaget måste detaljplanen följas i den här situationen: planavvikelseundantaget för en komplementbyggnad gäller när den kompletterar ett en- eller tvåbostadshus | sources do not state that this property is not a one- or two-dwelling house |
| valsatra-carport | pin | rule | statement | Fastigheten berörs också av riksintresse för totalförsvaret, men den särskilda bygglovsregeln där gäller inte carportar. Hänsyn till riksintresset ska ändå tas i prövningen | sources do not identify a special bygglovsregel for the riksintresse or say it excludes carports |
| valsatra-carport | pin | procedure | statement | Om lov behövs, kontakta Uppsala kommuns stadsbyggnadsförvaltning. Kommunens underlag för komplementbyggnader anger situationsplan, planritningar, fasadritningar och sektionsritningar som handlingar för en bygglovsansökan | cited source gives no contact details or instruction to contact stadsbyggnadsförvaltningen |
| valsatra-carport | address | place | statement | Uppsala har en gällande detaljplan med namnet **Norra Gottsunda villaområde med mera**. I den anges för vissa områden att högst en femtedel av tomten får bebyggas och att högst ett uthus eller en annan gårdsbyggnad får uppföras utöver huvudbyggnaden. Det bero… | that at most one fifth of the plot may be built on and at most one outhus beyond the main building |
| fansta-flerbostadshus | address | procedure | advice | Om Dp 504 C gäller och fastigheten ligger i en zon med dessa bestämmelser, fråga Uppsala kommun om de kan pröva en ny eller ändrad detaljplan för flerbostadshus. Kommunen beslutar vad som får byggas inom detaljplanerade områden | Att kommunen kan pröva ny eller ändrad detaljplan sägs inte |
| fansta-flerbostadshus | address | procedure | statement | Om kommunen går vidare med planläggning behöver projektets omfattning och utformning prövas där. Därefter krävs bygglov; Uppsala kommuns ansökningsunderlag räknar bland annat upp situationsplan, sektioner, markplaneringsplan, fasad- och planritningar samt tek… | Att omfattning prövas i planläggningen och att bygglov krävs efteråt |
| fansta-flerbostadshus | address | procedure | hedge | Jag har inte kunnat knyta gatunumret till en fastighetsbeteckning eller läsa av dess exakta läge på plankartan. Därför är bedömningen av Dp 504 C villkorad; fastighetsbeteckningen behövs för att slå fast om planen och bestämmelsen om friliggande hus gäller ju… | Källan säger inte att bygglovsvägledare kontrollerar fastighetsbeteckning och plan |
| gottsunda-inglasning | pin | procedure | advice | Stäm av med Uppsala kommuns bygglovsvägledare om lovplikten. Om ni söker bygglov för inglasning ska ansökan enligt kommunen innehålla situationsplan, fasadritningar och detaljritningar/produktblad | Sources do not state to consult the bygglovsvägledare about lovplikt |
| flogsta-restaurang | address | procedure | advice | Be Uppsala kommuns stadsbyggnadsförvaltning bekräfta vilken planbestämmelse och vilket tidigare bygglov som gäller för lokalen. Kommunens kontaktcenter kan nås på | Source does not say kommunen confirms which plan provision and prior permit applies |
| librobak-bostader | address | rule | advice | Om den gällande planen inte tillåter bostäder, fråga kommunen om en planändring eller ny detaljplan kan prövas. En detaljplan är det som avgör markens tillåtna användning där planen gäller | source does not state kommunen can be asked for planändring, nor that detaljplan decides allowed land use |
| norby-attefall | pin | rule | statement | Uppsala kommun framhåller att även åtgärder utan bygglov kan omfattas av krav i detaljplanen och övriga regler. Fastigheten berörs också av riksintresset Uppsala flottiljflygplats; åtgärder får inte påtagligt motverka totalförsvarets intressen. För ett lågt a… | That significance for a low atefallshus must be judged from its design and placement is not in the sources |
| norby-attefall | address | place | hedge | Jag kan inte säkert knyta adressen **Eksoppsvägen 37** till en fastighetsbeteckning i underlaget. Uppsala kommuns plankarta visar fastigheten **114:21** vid Eksoppsvägen utanför gränsen för detaljplanen *Tryffelvägen, del av Norby 31:52*, men kartan visar int… | 114:21, Eksoppsvägen and its position outside the plan boundary do not appear in the plankarta text |
| norby-attefall | address | procedure | hedge | Fastighetsbeteckningen, rätt detaljplan för just nummer 37, tidigare komplementbyggnader och tänkt placering och storlek är inte fastställda här. Därför går det inte att ge ett slutligt ja för den specifika tomten ännu. Uppsala kommun framhåller också att pla… | Sources do not state that property designation and applicable plan remain unestablished |
| trevlinge-tillbyggnad | address | place | advice | Kontrollera fastighetens detaljplan, skyddsbestämmelser och avstånd till gräns innan du börjar. Uppsala har en detaljplan för del av Trevlinge 1:5 i Gåvsta, men underlaget jag hittat visar inte om den gäller just din fastighet | Source does not name the plan 'Trevlinge 1:5' or its applicability to this property |

## Flags the auditor disagrees with

The check says unsupported, the auditor finds every fact in the cited sources. Verify by hand: either the check is too strict or the auditor too lenient.

| Case | Condition | Kind | Form | Claim | What the sources do not state |
|---|---|---|---|---|---|
| kungsangsgard-nytt-hus | pin | rule | statement | Fastigheten ligger utanför detaljplan. Ett nytt bostadshus kräver bygglov, och bygglov utanför detaljplan kan ges bara om bland annat kraven på lokalisering och lämplighet uppfylls och åtgärden inte förutsätter planläggning. PBL 9 kap. 3 och 57 §§ | – |
| slottsgatan-kallare | address | number | advice | För kvarteret Ubbo anger planbeskrivningen att området ligger inom yttre vattenskyddsområde och nära det inre. Där anges att markarbeten djupare än en meter över högsta grundvattennivån kräver ansökan om dispens från vattenskyddsföreskrifterna. Planen anger o… | – |
| slottsgatan-kallare | address | place | statement | Kommunens planunderlag för kvarterets byggprojekt lyfter bland annat behov av spont vid källarschakt och risk för påverkan på närliggande känsliga byggnader och grundvatten. Det underlaget gäller planens projekt, inte ert hus, men visar varför grundläggning,… | – |
| bjorklinge-avstyckning | address | rule | statement | Kommunens översiktsplan anger att ny bostadsbebyggelse på landsbygden bör tillkomma som enstaka hus som passar in i befintliga eller naturliga bebyggelsegrupper. Den säger också att VA-förutsättningarna ska vara säkerställda i förväg om platsen ligger utanför… | – |
| bjorklinge-avstyckning | address | none | hedge | Det visar inte i sig vad som gäller på just er fastighet | – |
| bjorklinge-avstyckning | address | procedure | statement | Uppsala kommun anger att karta och normalt även bygglov eller förhandsbesked bör bifogas till förrättningsansökan; kostnaden beror på arbetstiden och tas ut även om ansökan inte går att genomföra eller återtas | – |
| fansta-flerbostadshus | pin | rule | statement | Nybyggnad kräver bygglov, och bygglov utanför detaljplan förutsätter bland annat att åtgärden inte kräver planläggning enligt PBL 4 kap. 2 § och uppfyller lämplighetskraven i PBL 2 och 8 kap | – |
| fansta-flerbostadshus | address | contact | advice | Be Uppsala kommun bekräfta fastighetsbeteckning och vilken detaljplan och zon som gäller för **Fanstavägen 1**. Kommunens planinformation anger Kontaktcenter på 018-727 00 00 och stadsbyggnadsforvaltningen@uppsala.se | – |
| valsatra-carport | pin | place | hedge | Detaljplanens text har inte kunnat läsas, och underlaget fastställer inte carportens mått, placering eller om befintliga byggnader redan använder den lovbefriade arean. Uppsala kommun uppmärksammar också att tomtgräns, riksintresse, detaljplan och tidigare by… | – |
| falhagen-fasad | address | rule | statement | Oavsett lovplikt ska arbetet utföras varsamt med hänsyn till byggnadens karaktär och värden. PBL 8 kap. 17 § | – |
| flogsta-restaurang | pin | contact | advice | Be Uppsala kommuns bygglovsvägledare kontrollera att restaurang är förenlig med planens bestämmelser för just lokalen och om ändrad användning kräver bygglov. Kommunens bygglovskontakt är 018-727 00 00 och bygglov-kontaktcenter@uppsala.se | – |
| flogsta-restaurang | address | contact | advice | Be Uppsala kommun kontrollera fastighetens detaljplan och bygglovshistorik för Köpenhamnsgatan 2. Kommunens sida för stadsplanen anger Kontaktcenter på 018-727 00 00 och stadsbyggnadsförvaltningen@uppsala.se | – |
| kungsangsgard-nytt-hus | address | procedure | statement | Redovisa VA-lösning i ansökan om platsen saknar kommunalt vatten och avlopp. Ett positivt förhandsbesked är bindande i två år efter att det vunnit laga kraft; bygglov behöver sökas inom den tiden för att använda beskedet | – |
| kvarnbo-gaststuga | pin | contact | advice | Be Uppsala kommuns bygglovsvägledning bedöma om bygglov ändå krävs enligt reglerna för särskilt värdefulla områden: 018-727 00 00 eller bygglov-kontaktcenter@uppsala.se | – |
| fansta-flerbostadshus | pin | rule | advice | Om kommunen bedömer att detaljplan krävs, låt projektet prövas genom den pågående detaljplanen eller begär besked om rätt planprocess. Om planläggning inte krävs kan ni undersöka förhandsbesked för lokaliseringen innan ni lägger resurser på en full bygglovsan… | – |
| fansta-flerbostadshus | pin | rule | advice | Parallellt: inhämta de gällande vattenskyddsföreskrifterna från ansvarig myndighet, klarlägg strandskydd och stäm av totalförsvarets intressen. Bygglovspliktiga arbeten får inte börja innan byggnadsnämnden lämnat startbesked | – |
| valsatra-carport | address | procedure | advice | Om carporten inte uppfyller villkoren för bygglovsbefrielse, sök bygglov. Uppsala anger att en garageansökan normalt ska innehålla situationsplan, planritningar, fasadritningar och sektionsritningar | – |
| falhagen-fasad | address | rule | statement | Även vid bygglovsbefriade åtgärder ska ändringen utföras varsamt och ta hänsyn till byggnadens karaktärsdrag och värden. PBL 8 kap. 17 § | – |
| librobak-bostader | address | procedure | advice | Be Uppsala kommun bekräfta vilken fastighetsbeteckning adressen Ullforsgatan 5E ligger på och exakt vilka detaljplaner och planbestämmelser som gäller där. Planhandlingarna jag hittade visar Kv Ullfors och Librobäck 18:1, 18:3 och 18:4, men kopplar inte uttry… | – |
| flogsta-restaurang | address | place | hedge | Underlaget visar att stadsplanen för Flogsta–Ekeby gäller för stora delar av Ekeby, men inte vilken zon eller fastighet just Köpenhamnsgatan 2 tillhör | – |
| dalbysaby-bastu | pin | place | statement | Platsunderlaget markerar Ekoln som riksintresse för turism och friluftsliv. De intressena ska särskilt beaktas vid prövningen | – |
| dalbysaby-bastu | address | number | advice | Kontrollera separat bygglovsreglerna för bastuns storlek och placering. Uppsala kommun anger en avgift på 7 340 kr för en mindre åtgärd, exempelvis en komplementbyggnad inom tidigare beslutad tomtplats; avgiften tas ut även om dispensen avslås | – |
| fansta-flerbostadshus | pin | rule | statement | Platsen ska vara lämplig med hänsyn till bland annat hälsa och säkerhet, mark- och vattenförhållanden, trafik, vatten och avlopp, avfall, buller samt risk för översvämning och erosion | – |
| falhagen-fasad | address | rule | statement | Även vid lovpliktiga arbeten ska ändringen utföras varsamt och ta hänsyn till byggnadens karaktär och värden | – |
| flogsta-restaurang | address | place | statement | Uppsala kommun listar **Stadsplan för Flogsta**, aktbeteckning **0380-331**, men planbestämmelserna för den aktuella lokalen framgår inte av det material jag kunnat läsa | – |
| librobak-bostader | address | contact | advice | Kontrollera fastigheten mot detaljplanens plankarta och bestämmelser. Uppsala kommuns bygglovsvägledare kan hjälpa till att stämma av frågan före ansökan: 018-727 00 00 eller bygglov-kontaktcenter@uppsala.se | – |
| librobak-bostader | address | none | hedge | Jag har inte kunnat fastställa fastighetsbeteckningen eller vilken zon på plankartan tomten ligger i. Det är avgörande för ett säkert ja eller nej | – |
| norby-attefall | address | rule | statement | Sedan **1 december 2025** gäller nya bygglovsregler. En byggnad som uppfyller undantaget kräver normalt inte anmälan enbart för själva nybyggnaden; anmälan kan däremot krävas för exempelvis vissa installationer eller arbeten som påverkar konstruktion, brandsk… | – |
| norby-attefall | address | procedure | advice | Kontrollera fastighetsbeteckningen och vilken detaljplan som faktiskt gäller för nummer 37. Kartan och beskrivningen för den närliggande Tryffelvägen-planen visar området, men bekräftar inte ensamma vilken plan som gäller för adressen. Planbeskrivningen anger… | – |
| slassbo-nytt-hus | pin | rule | statement | Om den aktuella marken är brukningsvärd jordbruksmark får den tas i anspråk för bebyggelse bara om förutsättningarna i miljöbalken är uppfyllda. MB 3 kap. 4 § | – |

## Facts without a citation

The check found a rule, number, fee or deadline with no source.

| Case | Condition | Kind | Form | Claim | What the sources do not state |
|---|---|---|---|---|---|
| kvarnbo-gaststuga | pin | rule | advice | Kontrollera att byggnaden verkligen kompletterar ett befintligt hus, ryms inom 65 m² sammanlagt och placeras inom den avgränsade tomten | no source cited for the kompletterar, 65 m² and tomten conditions |
| kvarnbo-gaststuga | address | rule | statement | En gäststuga på 25 m² kan vara bygglovsbefriad, men det beror bland annat på att den verkligen är en komplementbyggnad eller ett komplementbostadshus och på byggnadens placering och tomtens övriga byggnader | no source states exemption conditions for a 25 m² guest cabin or placement considerations |
| kvarnbo-gaststuga | address | rule | statement | Om alla villkor för undantaget är uppfyllda behövs normalt inte bygglov | no source states that meeting all exemption conditions means no building permit is normally needed |
| kvarnbo-gaststuga | address | rule | advice | Om något villkor faller bort, fråga kommunen om bygglov innan du börjar bygga | no source advises asking the kommun about a building permit if an exemption condition fails |
| kungsgatan-pabyggnad | address | rule | hedge | – En extra våning kräver i praktiken bygglov, men jag kan inte avgöra om den får byggas på just huset utan att fastställa fastighetens detaljplan och planbestämmelser | no source states an extra floor requires bygglov or that the plan must be checked |
| dalbysaby-bastu | pin | rule | statement | Om bastun hamnar inom strandskyddat område kan dispens behövas, och placeringen nära sjön gör den frågan särskilt viktig | Sources do not state the property is near a lake |
| dalbysaby-bastu | address | rule | statement | – en bastu vid sjön kan bli möjlig, men om platsen ligger inom strandskyddet behöver du normalt dispens först; utanför en redan beslutad tomtplats kan dispens vara svår att få | No source given; dispens requirement and difficulty of obtaining dispens outside a decided tomtplats uncited |
| fansta-flerbostadshus | address | rule | hedge | Ett flerbostadshus kräver bygglov, men jag kan inte säkert koppla adressen Fanstavägen 1 till en fastighetsbeteckning och rätt zon på plankartan | No source states flerbostadshus requires bygglov, or links address to property and zone |
| falhagen-fasad | address | rule | statement | Ja, räkna med att ni behöver bygglov för färgbyte och fönsterändring på gatufasaden, om huset ligger inom detaljplan och fasaden vetter mot allmän plats | No source given for the permit requirement and conditions |
| flogsta-restaurang | address | rule | advice | Om användningen inte redan är godkänd som restaurang: stäm av med bygglovsenheten och sök bygglov för ändrad användning innan verksamheten startar | No source or place data states the bygglov requirement or this step |
| norby-attefall | pin | rule | advice | Kontrollera att det finns ett en- eller tvåbostadshus som huset ska komplettera, att sammanlagd byggnadsarea för komplementbyggnader ryms inom gränsen och att placeringen klarar avståndet till fastighetsgräns | the conditions it tells the user to check are cited to no source here |
| trevlinge-tillbyggnad | pin | rule | statement | En tillbyggnad på 25 m² kan vara bygglovsfri, men bara om den uppfyller villkoren nedan och det inte finns särskilda plan- eller värdeskyddsbestämmelser för fastigheten | No source given; place data does not state the 25 m² exemption conditions |
| trevlinge-tillbyggnad | pin | rule | advice | Kontrollera att 25 m² avser bruttoarea/öppenarea och att tidigare tillbyggnader inte gör att byggnadens sammanlagda tillbyggnadsarea överstiger 30 m² | No source given for the 30 m² combined-area limit |
| trevlinge-tillbyggnad | address | rule | statement | En tillbyggnad på 25 kvm av själva bostadshuset kan vara bygglovsfri, men det beror bland annat på hur arean räknas, tidigare tillbyggnader och var den placeras | inga källor anger villkoren för bygglovsfrihet, areanräkning, tidigare tillbyggnader eller placering |
| trevlinge-tillbyggnad | address | procedure | advice | Kontrollera med Uppsala kommun vilken detaljplan eller vilka områdesbestämmelser som gäller för fastigheten och vilka bygglov som redan finns där. Kommunen anger att platsens regler och vad som tidigare byggts påverkar bedömningen | ingen källa stödjer att kommunen anger att regler och tidigare byggande påverkar bedömningen |
| trevlinge-tillbyggnad | address | rule | statement | Även utan bygglov kan anmälan behövas, till exempel om arbetet påverkar bärande konstruktion, brandskydd eller ventilation | inga källor stödjer krav på anmälan vid bärande konstruktion, brandskydd eller ventilation |
| trevlinge-tillbyggnad | address | none | hedge | Det går inte att avgöra säkert från adressen ensam om den särskilda 30-kvm-regeln gäller utan bygglov på just fastigheten | – |
| kvarnbo-gaststuga | pin | none | hedge | Uppsala kommuns tillgängliga reservatsunderlag gav inte besked om den exakta reservatsföreskrift som träffar den föreslagna platsen | – |
| kvarnbo-gaststuga | address | rule | statement | En gäststuga på 25 m² kan normalt byggas utan bygglov, men det beror på att den uppfyller villkoren för bygglovsbefrielse och inte träffas av särskilda skyddsregler | No source states bygglovsbefrielse conditions for a 25 m² guest cottage |
| slottsgatan-kallare | address | place | hedge | Jag hittar en plan för Fjärdingen 12:3 vid Övre Slottsgatan, men kan inte säkert fastställa från underlaget att just adressen 26B ligger på den fastigheten | source for the plan's existence; no source and no place data on address 26B |
| fansta-flerbostadshus | address | place | summary | Det exakta projektets skala är också avgörande: planbeskrivningen för Fansta 3:1 talar om små flerbostadshus, inte om ett större lägenhetshus | källa för att planbeskrivningen för Fansta 3:1 talar om små flerbostadshus, inte lägenhetshus |
| valsatra-carport | pin | rule | advice | Kontrollera om carporten uppfyller samtliga villkor för bygglovsbefrielse i PBL 9 kap. 4 § | no source given for the exemption conditions in PBL 9 kap. 4 § |
| valsatra-carport | pin | rule | statement | Carportens mått, höjd och befintliga komplementbyggnader avgör också om bygglovsundantaget kan användas | no source given that these factors decide eligibility for the exemption |
| valsatra-carport | address | rule | statement | Även carportens area, nockhöjd och befintliga komplementbyggnaders sammanlagda area påverkar om bygglov krävs | no source cited; PBL 9 kap. 4 § states these conditions |
| falhagen-fasad | address | rule | statement | — Ja, ni behöver sannolikt bygglov för att byta fasadfärg och fönster på fasaden mot gatan | No source given; no place data on property's plan or building type |
| falhagen-fasad | pin | rule | statement | Ja, ni behöver sannolikt bygglov för fasadfärgsbyte och fönsterbyte på den fasad som vetter mot gatan | that the work is paint and window replacement on a street-facing facade |
| falhagen-fasad | pin | rule | statement | Den avgörande förutsättningen är att byggnaden är ett flerbostadshus och att fasaden vetter mot allmän plats | no source states these are the decisive prerequisites for the permit |
| librobak-bostader | address | place | statement | Uppsala kommuns planmaterial för Kv Ullfors/Hållnäs anger industri och andra verksamheter, inte bostäder; därför ser det inte ut som att ni kan få bygglov för nya bostäder enligt gällande plan | No source cited for the plan designation of Kv Ullfors/Hållnäs or the bygglov conclusion |
| librobak-bostader | address | rule | statement | Bygglov för bostäder blir aktuellt först när den gällande planen medger bostadsändamålet, eller efter en planändring som gör det möjligt | No sources cited for this permit condition |
| flogsta-restaurang | address | rule | advice | Sök bygglov om restaurangen innebär en väsentligt annan användning; gör anmälan för sådana tekniska ändringar som omfattas av anmälningsplikten | ingen källa för kravet på bygglov respektive anmälan |
| flogsta-restaurang | address | rule | statement | Om planen bara medger bostäder kan det krävas en planändring för att få restaurangverksamhet på platsen | ingen källa anger att planändring kan krävas |
| trevlinge-tillbyggnad | pin | rule | statement | — En tillbyggnad på 25 m² kan vara bygglovsbefriad, men bara om den uppfyller villkoren nedan | no source given for 25 m² possibly being exempt and its conditions |
| trevlinge-tillbyggnad | pin | rule | summary | Därför räcker det inte att den nya delen är 25 m²: tidigare tillbyggnader och hur arean mäts kan ändra svaret | no source cited for prior additions counting and area measurement affecting the result |
| trevlinge-tillbyggnad | pin | rule | advice | Kontrollera om huset redan har tillbyggnader som ska räknas in, och att 25 m² avser bruttoarea/öppenarea enligt lagens regel | no source cited for counting existing additions and bruttoarea/öppenarea measurement |
| trevlinge-tillbyggnad | address | place | hedge | En tillbyggnad på 25 m² kan vara bygglovsfri, men jag kan inte bekräfta det för just Trevlingevägen 47 utan att kontrollera fastighetens läge och förutsättningar | Ingen källa eller platsdata om Trevlingevägen 47 eller om 25 m² |
| trevlinge-tillbyggnad | address | none | summary | Det avgörande är den rättsliga arean för tillbyggnaden, tidigare tillbyggnader, avståndet till gräns samt om fastigheten eller byggnaden har särskilt skydd | – |
| kvarnbo-gaststuga | pin | rule | statement | En gäststuga på 25 m² kan vara bygglovsbefriad eftersom fastigheten ligger utanför detaljplan, men det betyder inte att den får byggas utan hänsyn till reservatsföreskrifter och fornlämningar | no source states a 25 m² guest cottage can be exempt from bygglov; place data only gives location facts |
| kungsangsgard-nytt-hus | address | rule | statement | Uppsala kommuns översiktsplan är vägledande, medan detaljplanen och prövningen av den exakta placeringen avgör ärendet | ingen källa anger att översiktsplanen är vägledande och detaljplanen avgör |
| kvarnbo-gaststuga | address | rule | statement | En gäststuga på 25 m² kan normalt byggas utan bygglov, men läget på tomten, vad som redan finns där och eventuella särskilda områdesregler avgör | No source states the 25 m² exemption from building permit or the factors deciding it |
| kvarnbo-gaststuga | address | rule | advice | Kontrollera hur mycket byggnadsarea som redan finns på tomten och att gäststugan är mindre än huset den kompletterar | No source states any building-area limit or that the cabin must be smaller than the house |
| slottsgatan-kallare | address | procedure | advice | Innan markarbete börjar, kontakta Länsstyrelsen i Uppsala län om fornlämningstillstånd | no sources; contacting Länsstyrelsen about ancient monument permit not stated |
| kungsgatan-pabyggnad | address | rule | hedge | – en extra våning kräver normalt bygglov, och det går inte att fastställa från underlaget om detaljplanen för just huset på Kungsgatan 63B tillåter höjningen | no source given for the bygglov rule or for the plan's stance on Kungsgatan 63B |
| dalbysaby-bastu | address | rule | statement | Eftersom bastun ska stå nere vid sjön är strandskyddsdispens sannolikt den avgörande frågan; bygglovsfrihet innebär inte att du slipper dispens | No source states that bygglovsfrihet still requires strandskyddsdispens, or that this is the decisive question |
| valsatra-carport | pin | rule | statement | Carportens storlek, höjd, placering och hur mycket annan komplementbebyggelse som redan finns på tomten avgör om undantaget kan användas | no source states which factors determine whether the exemption applies |
| valsatra-carport | address | rule | statement | Om något villkor inte uppfylls kan bygglov krävas | no source cited; sources do not state that unmet conditions trigger bygglov |
| fansta-flerbostadshus | address | place | hedge | Ett flerbostadshus verkar inte rymmas inom den detaljplan som omfattar delar av Fanstavägen i Lövstalöt | Ingen källa angiven för att flerbostadshus inte ryms inom planen |
| falhagen-fasad | pin | rule | statement | Ja—om byggnaden är ett flerbostadshus och gatan är allmän plats krävs bygglov för fasadändringen mot gatan | No source cited; place data does not state building is a flerbostadshus or that the street is an allmän plats |
| falhagen-fasad | pin | rule | statement | Att byta fasadfärg innebär en fasadändring; även fönsterbyte kan göra det om fasadens utseende ändras | No source cited for colour change or window replacement counting as fasadändring |
| falhagen-fasad | address | rule | statement | — Ja, ni behöver sannolikt bygglov för att byta färg och fönster på gatufasaden | no source given for permit requirement for colour and window changes |
| falhagen-fasad | address | none | summary | Därför är bedömningen villkorad av att gatufasaden vetter mot allmän plats och att fastigheten ligger inom detaljplan | – |
| flogsta-restaurang | pin | rule | advice | Om restaurang innebär en väsentligt ändrad användning, sök bygglov innan ombyggnad eller användningsändringen | No source given for restaurant use requiring bygglov before rebuilding |
| flogsta-restaurang | address | rule | statement | Om planen tillåter restaurangverksamhet och lokalen redan har godkänd användning för den, kan bygglov för ändrad användning eventuellt inte behövas | No source states when bygglov for changed use may be dispensed with |
| trevlinge-tillbyggnad | pin | rule | statement | En tillbyggnad på 25 m² kan vara bygglovsbefriad, men bara om lagens villkor är uppfyllda och ingen särskild lovplikt gäller för platsen eller byggnaden | Ingen källa angiven; underlaget anger inte att 25 m² kan vara bygglovsbefriad |
| trevlinge-tillbyggnad | pin | rule | advice | Räkna in eventuella tidigare lovbefriade tillbyggnader och kontrollera att de 25 m² avser lagens area, samt att tillbyggnaden inte går över taknocken | Ingen källa angiven; underlaget anger inte detta om beräkning av 25 m² |
| norby-attefall | address | rule | statement | — ett attefallshus kan normalt uppföras utan bygglov om det uppfyller mått- och placeringskraven och fastigheten inte omfattas av ett undantag som kräver lov | no source given and place data does not state this rule |
| trevlinge-tillbyggnad | address | rule | hedge | En tillbyggnad på 25 m² behöver normalt inte bygglov om den uppfyller villkoren nedan, men jag kan inte bekräfta att samtliga gäller för just Trevlingevägen 47 | No source states the 25 m² exemption or its applicability to this address |
| trevlinge-tillbyggnad | address | rule | advice | Kontrollera att 25 m² räknas enligt lagens areabegrepp och att tidigare tillbyggnader inte gör att totalsumman överstiger 30 m² | No source cited; area calculation and aggregation rule not stated here |

## Claims the check passed and the auditor did not

The check says supported, the auditor finds none of the facts in the cited sources. These reach the user unflagged.

| Case | Condition | Kind | Form | Claim | What the sources do not state |
|---|---|---|---|---|---|
| kungsangsgard-nytt-hus | pin | rule | statement | Natura 2000-tillstånd krävs om åtgärden kan påverka områdets miljö på ett betydande sätt | the Natura 2000 permit rule; cited sections concern riksintressen, not Natura 2000 |
| kvarnbo-gaststuga | address | procedure | advice | Skicka fastighetsbeteckningen eller en kartnål, så kan jag kontrollera platsens plan mer exakt | Source does not say a fastighetsbeteckning or map pin enables checking the site's plan |
