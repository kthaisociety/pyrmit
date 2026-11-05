# Pyrmit

A legal RAG chat assistant for Swedish land law and urban planning. It answers questions about whether a building project is feasible, using Swedish statutes and uploaded detaljplaner as sources.

## Language

**Detaljplan**:
A Swedish municipal detailed development plan, uploaded as a PDF. It sets what may be built where. Plural is detaljplaner.
_Avoid_: zoning document, plan document, historical document

**Law**:
Swedish statute text ingested from TXT files, mainly fastighetsrätt (land law, including Jordabalken) and Plan- och bygglagen (PBL, the planning and building act).
_Avoid_: regulation, legal source (when only statutes are meant)

**Chunk**:
One retrievable piece of a source, stored with its embedding. Either a law chunk or a document chunk.
_Avoid_: passage, snippet, segment

**Law chunk**:
A chunk of a law, split along chapter and section boundaries. Stored in `law_chunks`.

**Document chunk**:
A chunk of a detaljplan, split from its OCR Markdown. Stored in `document_chunks`.

**Embedding**:
The vector for a chunk or a query, used for cosine similarity search.
_Avoid_: vector (when the model output is meant)

**Ingestion**:
Turning a source file into stored chunks: OCR if needed, chunk, embed, insert.
_Avoid_: upload, import, indexing

**OCR Markdown**:
The Markdown text Mistral OCR produces from a detaljplan PDF. Ingestion chunks this, never the PDF directly.

**Feasibility analysis**:
The answer to "can this project be built here", combining a law reading and a detaljplan reading into a verdict with a confidence score.
_Avoid_: assessment, evaluation

**Verdict**:
The feasibility status the orchestrator returns, always paired with a confidence.

**Law agent**:
The agent that retrieves law chunks and asks the model for a structured reading of the statutes.

**Document agent**:
The agent that retrieves document chunks and asks the model for a structured reading of the detaljplaner.

**Orchestrator**:
Combines the law agent's and document agent's results into the verdict.

**Parsed query**:
The location, number of units and project type extracted from a user's message.

**Clarifying prompt**:
The reply sent instead of an analysis when the parsed query lacks location or units.

**Chat session**:
One conversation thread owned by a user, holding its chat messages.
_Avoid_: session (clashes with the `sessions` table and with auth)

**Chat message**:
One user or assistant turn inside a chat session.

**User**:
A person who signs in. Their password hash lives on a separate account row.

**Account**:
The credentials row for a user, holding the provider and password hash.

**Access gate**:
A shared unlock code that guards the deployed app before sign-in. Passing it sets a cookie, and the frontend sends users back to it on 401 or 403.
_Avoid_: dev access, login

**Pin**:
The point a user puts on the map in the chat: the place the chat is about. Only the user moves it.
_Avoid_: marker, location (when the pinned point is meant)

**Property**:
The fastighet at the pin, named by its fastighetsbeteckning (e.g. Uppsala Kungsängen 7:8). The unit the place card describes.
_Avoid_: lot, parcel, plot

**Place profile**:
What the registers say about the pinned property: the plans in force, tillägg and områdesbestämmelser, the land-use zones, the plans in progress, inside or outside a detaljplan. Built from data alone, without a model.

**Place card**:
The place profile as the user sees it beside the map, with the source and date of every row. Registry data, not a decision.
_Avoid_: site report, place summary

**Land-use zone**:
An area of a detaljplan with one användning (e.g. BCK, GATA, PARK), as the kommun's map draws it. Old plans have interpreted boundaries.
_Avoid_: zoning, delområde (when only the användning is known)

**Plan in progress**:
A detaljplan at samråd or granskning: shown on the place card but not binding.

**Protected area**:
An area protected under miljöbalken 7 kap. (naturreservat, biotopskyddsområde, vattenskyddsområde, ...), with its own regulations; building against them needs a dispens. Natura 2000 sites are listed apart.

**National interest**:
A riksintresse under miljöbalken 3 or 4 kap. (naturvård, kulturmiljövård, totalförsvar, ...). Not a permit: the prövning must not significantly harm it.
_Avoid_: national interest area, interest zone

**Ancient remain**:
A lämning in Riksantikvarieämbetet's register, with its antikvarisk bedömning. A "Fornlämning" is protected by kulturmiljölagen; a "Möjlig fornlämning" is for the länsstyrelse to decide.

**Likely permit**:
A permit or prövning the place card derives by fixed rules from the place profile (bygglov, dispens, tillstånd), with its legal basis and deciding authority. A consideration is listed with them but is not a permit.

**Proposed pin**:
A match of the map's address search, shown as a grey pin until the user confirms it with "Pin here". Only then does the **Pin** move and the place card change.

**Place chip**:
The pinned place shown above the message input. Tapping it opens the map; clearing it unpins the chat.

**Lookup facit**:
The hand-checked answer for one property: its plans, zones, protections, remains and likely permits, and where each was checked. Locked with a date before the lookup ever runs on that property; later corrections are listed, not overwritten.
_Avoid_: ground truth, gold labels

**Pilot kommun**:
A kommun whose every layer has a snapshot: plans, land-use zones, plans in progress and the national layers, with the property looked up live (Uppsala for now).

**Plan source**:
One kommun's open plan layer as the registry (`backend/place/plan_sources.json`) describes it: the service, the layer and the attributes that carry the aktbeteckning, the document links, the plan name, the date and the plan type, plus the base pattern for links that are bare file names and the licence. Built from the survey of all 290 kommuner in `docs/research/`.
_Avoid_: pilot (a plan source has no other layers), endpoint

**Plan-layer kommun**:
A kommun covered by its plan source alone: a pin there gives the kommun and the detaljplaner at the point, with no property, land-use zones or plans in progress.

**Snapshot**:
A dated local copy of a kommun's area layers: every layer of a pilot kommun (`python -m place.fetch`), or the plan layer of a plan-layer kommun (`python -m place.plan_layers`). A kommun with a snapshot is covered; anywhere else the place is "not covered yet".

**Plan-document link**:
A row of the link table (`data/geo/<code>/plan_links.jsonl`): one plan polygon matched to one document of the document store, with the match level that produced it and the date. A plan at the pin carries its matched documents' ids, or says no document is matched yet.
_Avoid_: corpus match (the registry match by name that `corpus_plan_id` records)

**Match level**:
How a polygon found its document, tried in order and stopped at the first hit: link (the polygon's document link is the document's address), akt (the normalised aktbeteckning appears in the document's title, file name or first page of text, same kommun only; further in it is only a mention, such as a plan the document replaces) or name (kommun and plan name agree; marked for review).

**Fetch list**:
The links of every polygon no document matched, grouped by kommun (`data/geo/plan_fetch_list.json`), for the scraper to pick up next. A polygon whose links were internal paths is listed as "no public link" with its aktbeteckning.

**Coverage report**:
One line per plan source, kept up to date across fetch runs: fetched or not and why, the polygons kept against the survey's count, and the shares of plans with an aktbeteckning and with a link.

**Review mode**:
A switch on the map panel, off by default, for checking the plan layers and their documents by eye. Zoomed out it colours every kommun by whether it has plan polygons; zoomed in to about a kommun it draws the polygons in view coloured by **Match level** (link, akt, name, none), and a click on one shows its aktbeteckning, name and match level. Layers the **Coverage report** flags as doubtful are drawn like any other.

## Relationships

- A **Detaljplan** goes through **Ingestion**: PDF to **OCR Markdown**, then **Document chunks**, each with an **Embedding**.
- A **Law** goes through **Ingestion** straight from TXT into **Law chunks**, each with an **Embedding**.
- A **User** has one **Account** and many **Chat sessions**. A **Chat session** has many **Chat messages**.
- A user message becomes a **Parsed query**. If location or units are missing, the reply is a **Clarifying prompt**.
- Otherwise the **Law agent** searches **Law chunks** and the **Document agent** searches **Document chunks**, both by **Embedding** similarity.
- The **Orchestrator** combines both agents' results into a **Verdict**, which becomes the **Feasibility analysis** saved as an assistant **Chat message**.
- The **Access gate** sits in front of everything, including sign-in.
- A **Pin** in a **Pilot kommun** gives a **Property** (looked up live) and a **Place profile** (from the **Snapshot**): its **Detaljplaner**, **Land-use zones**, **Plans in progress**, **Protected areas** and **National interests**, plus the **Ancient remains** on it (looked up live). The **Likely permits** follow from that profile. The **Place card** shows all of it.
- A **Pin** in a **Plan-layer kommun** gives a **Place profile** with the **Detaljplaner** at the point from the kommun's **Snapshot**, each with its aktbeteckning, page and document links and licence, and nothing else. The **Plan source** says how the **Snapshot** was read; the **Coverage report** says how well.
- Every **Detaljplan** polygon in a **Snapshot** is matched to its documents in the document store by **Match level**, giving **Plan-document links** that the **Place profile** carries; the polygons without one go to the **Fetch list**.
- A question asked with a **Pin** is answered from its **Place profile**, and the answer keeps that **Pin**: reopening the **Chat session** brings back its **Place chip**.
