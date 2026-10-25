## Summary

_Uppsala, 2026-10-25. Epic #31: a pinned place gets a place card and the chat answers from the same place profile._

**The pin doubles answer quality.** Over 15 Uppsala places, 3 repeats, with two judges from different model
families:
- Answers with a pin cover 0.79-0.82 of the reference key points; with only the address in the question, 0.39.
- With a pin the answers name 54 % of the place facts (property, plan, protected areas); without it, 3 %.
- Without a pin the agent could almost never find the plan of an address: in 84-96 % of the answers it asked the
  user to pin the place instead.

**The lookup.**
- At 330 points the snapshots agree with the providers' own point queries on every layer at 328 points. The two
  differences are explained below; one of them was a bug, now fixed.
- A whole place profile takes 0.3 s at the median and 0.7 s at p90, with no failures.

**The address search.** It was the weakest part. Nominatim found the house for 28 % of Uppsala's register addresses
and otherwise the street or nothing, so 40 % landed on the right property. With Uppsala's own address register
searched first (fix in this round), the right property is found:
- for 100 % of the addresses typed as in the register or in lower case;
- for 95 % when the entrance letter is left out.

**Fixed in this round.**
- Invalid provider polygons: 29 of 10,461 features, 15 of the 93 protected areas. They made the lookup miss
  naturreservat Gula stigen at a point inside it. The store now repairs them on load.
- The address search goes to the register first.
- A register search for "Rälsvägen 1" returned Rälsvägen 13. Only a letter may now follow the typed number.

**What the numbers do not show.** No reference here was checked by a person yet. The lookup is compared with its own
providers, not with a hand-made facit (#39). The answer references were written by Claude from the place profiles and
the current law text, and locked before the agent ran. One kommun, one agent model, LLM judges.

## How it was measured

| Level | What | Reference | Cost |
|---|---|---|---|
| Lookup | 300 seeded points (half inside plans) + the 30 draft facit places | each provider's own point query: ArcGIS identify (tolerance 0) for Uppsala and Boverket, an OGC Intersects filter for Naturvårdsverket's WFS | free |
| Address search | 150 seeded addresses of Uppsala's address register (56,150 entrances) | the register's own point, and the property under it (Uppsala's property layer) | free |
| Answers | 15 Uppsala places × 4 conditions × 3 repeats, the chat's agent and settings | key points and place facts written before the run and locked (`place/cases_answers.jsonl`, committed before the run) | see section 3 |

The answer conditions:
- **pin**: the question goes with the pinned place's profile, exactly as the chat sends it (`question_with_place`).
- **address**: the same question names the address and nothing is pinned.
- **vague**: the question names no place; the agent should ask.
- **conflict**: the pin is on one place and the question names another; the agent should ask which.

The places cover the hard cases (outside detaljplan, several plans, plan in progress, naturreservat, Natura 2000,
fornlämningar, near water, industrial zone, old stadsplaner). The questions are typical of what users ask: attefallshus,
carport, tillbyggnad, påbyggnad, facade, balcony glazing, change of use, avstyckning, new house, multi-family house,
sauna by the lake, cellar.

## Findings

### The lookup

- **Invalid polygons, fixed.** Naturvårdsverket sends some areas with a ring outside the shell it belongs to. Shapely
  then answers "does it contain the pin" wrongly, and the lookup missed naturreservat Gula stigen at a point the
  provider places inside it.
  - 29 snapshot features were invalid, among them 15 of the 93 protected areas in Uppsala.
  - `PlaceStore` now repairs invalid geometries with `make_valid` when it loads them.
  - With the repair, Kungsängens gård gets the naturreservat Årike Fyris too.
- **A finished plan in progress, harmless.** The snapshot has one "pågående" plan, an upphävande with status
  Avslutat, that the provider's identify no longer returns at that point. The profile already leaves finished stages
  out.
- **Everything else agrees.** Plans, tillägg, områdesbestämmelser, the three land-use layers, Natura 2000 and every
  riksintresse layer have precision and recall 100 % against their sources.
- **Speed.** A profile, including the live property and ancient-remains lookups, takes 0.3 s at the median and 1.8 s at
  most. None of the 330 profiles failed.

### The address search

- **Nominatim alone** (before): 76 % of the addresses found anything. Only 28 % were matched to the house (kind
  house / building / place), and those were always on the right property (42 of 42, median 9 m). The rest came back as
  the street, e.g. "Karin Boyegatan, Uppsala", which lands on another property, or not at all. Rural addresses
  ("Risby 39, Björklinge") were mostly not found.
- **Register first** (after): every typed address was found at its entrance, on the right property.
  - Typed with a comma or in lower case: 100 %.
  - Without the entrance letter: 95 %. The search lists 47A-47E, and the first may stand on the neighbouring property.
  - Because the search now uses the very register the check samples, the typed form only shows that the lookup and
    parsing work. The lower-case and no-letter forms test typing variants. Misspelled street names were not tested.
- **About 5 % of the register's address points inside plans lie on a street property** (Tuna Backar 1:2, Kungsängen
  1:2, Luthagen 1:2, ...). A pin there gets the street and every plan it crosses, the known gap noted in the epic.

### The answers

- **Pin against address.** The agent's corpus has no address-to-property link, so without the pin it cannot place an
  address. It says so and asks to pin (the no-pin hint tells it to), which is honest but leaves the answer generic.
- **No place at all.** It asked where in 71 % (MiMo) to 100 % (Luna) of the answers. The judges disagree on answers
  that give general rules first and ask at the end.
- **Conflict, fixed.** With the pin on one place and the question naming another, v1 asked which was meant in only
  60 % of the answers. The judge comments show why: it saw the property designation but not its addresses, so it could
  not tell that "Övre Slottsgatan 26B" lay elsewhere, and it answered with the pinned place's plan. v2 gives the
  property's addresses (from Uppsala's register) and repeats the rule right before the question: **100 %**, in 2.4 s,
  under both judges.
- **Speed.** A pinned answer took 71 s (first token 62 s) in v1, with 7.6 model calls and 28 tool calls; 10 of the
  tool calls were law_section lookups of the very sections the permits cite. v3 puts those sections' text and the
  kommun code in the place context:
  - law_section calls fell from 9.6 to 6.1 per answer and tool calls from 27 to 25;
  - the model calls stayed at 7.4 and the time at 52-54 s (v2 and v3 ran on a less loaded machine than v1, so the
    v1 → v2 time gain is mostly load, not the fix);
  - key points moved 0.84 → 0.82 (MiMo) and 0.84 → 0.80 (Luna), within the run-to-run noise.

  Fewer lookups do not shorten the answer: the turns do. The agent still called find_kommun in every answer.

| Pinned answers | v1 | v2 | v3 |
|---|---|---|---|
| Key points (MiMo / Luna) | 0.79 / 0.82 | 0.84 / 0.84 | 0.82 / 0.80 |
| law_section calls | 10.0 | 9.6 | 6.1 |
| Model calls | 7.6 | 7.4 | 7.4 |
| Seconds (first token) | 71 (62) | 52 (43) | 54 (45) |
| Conflict: asks which place | 60 % | 100 % | 100 % |

The v2 and v3 numbers are on the same 15 cases the fixes were made for: they are optimistic.

**Fewer turns (v4, same day).** v4 tells the agent outright not to call find_kommun for a pinned place, then varies the
exploration effort and the step cap. All runs are pinned answers, 15 cases × 3 repeats, two judges:

| Pinned answers | v4 (medium, 10 steps) | v4-low (low, 10 steps) | v4-low-6 (low, 6 steps) |
|---|---|---|---|
| Key points (MiMo / Luna) | 0.84 / 0.84 | 0.82 / 0.79 | 0.74 / 0.72 |
| Place facts named | 56 % | 59 % | 49 % |
| Seconds (first token) | 43 (34) | 24 (18) | 23 (16) |
| Model calls / tool calls | 7.2 / 23 | 6.2 / 7 | 5.7 / 8 |
| Cost per answer | $0.009 | $0.003 | $0.003 |

- The find_kommun instruction alone took the pinned answer from 54 s to 43 s at the same quality (v3 → v4).
- Low exploration halves the time and costs a third, for 0.02-0.04 less on key points. That is a product choice:
  a fast mode for pinned questions, or the default.
- The 6-step cap loses 0.10 and saves almost nothing on top of low: rejected.

### Data gaps that limit the answers

- **No Uppsala plan provisions in the corpus.** The registry holds 61 Uppsala plans and none with provisions, so a
  pinned plan always says "provisions not indexed". The agent can name the plan and the zone but cannot read its
  building rules (height, building area, prickmark). That is the next limit on answer quality in Uppsala.
- **The totalförsvar "stoppområde för höga objekt" sits on 86 % of the points**, so nearly every card and every pinned
  answer lists it. It only matters for tall objects. The card should show it only for tall projects, or in a less
  prominent "other" group.
- **Strandskydd is still "not checked".** #32 found the 403 was a planned Länsstyrelsen outage. The decisions belong in
  NGP Strandskydd; the 100 m zone can only be computed as "possible".
- **The reform SFS 2025:974 changed the exemptions.** Komplementbyggnader and komplementbostadshus are now free of lov
  up to 30 m² inside a plan and 50 m² outside, with no anmälan. Tillbyggnader up to 30 m² below the ridge need no
  bygglov. Both the reference writer (from memory) and the model's memory hold the old rules; the references here were
  checked against the law text in the corpus.

## Recommendations

1. **Index Uppsala's plan provisions** (the plan documents linked from the kommun's layer, or NGP Detaljplan's 262
   Uppsala plans). This is the largest gap in answer quality: the agent names the plan but cannot read what it allows.
2. **Choose the exploration effort for pinned questions.** Low is twice as fast for 0.02-0.04 less (v4-low). A lower
   step cap is not worth it.
3. **Show the totalförsvar stop area only for tall projects.**
4. **Decide on the street-property rule** (a property mostly zoned GATA / allmän plats counts as street).
5. **A person reviews the references**: the #39 facit (30 drafted places) and a sample of the 56 answer key points.
6. **Then more kommuner:** Norrtälje from NGP once the consumer account is approved (the held-out test kommun), and
   Vallentuna from the kommun's own plans.

## Reproduce

```bash
cd backend
python -m place.check_sources --kommun 0380 --n 300
python -m place.check_search --kommun 0380 --n 150 --form typed   # and --form lower, --form no_letter
python -m place.bench_answers run --repeats 3 --workers 4 --label pin-v1
python -m place.bench_answers rejudge data/agentic/place-answers-<time>-pin-v1.json --judge-model openai/gpt-6-luna
python -m place.report --sources ... --search nominatim=... register=... --answers ...
```
