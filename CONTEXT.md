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

**Place chip**:
The pinned place shown above the message input. Tapping it opens the map; clearing it unpins the chat.

**Pilot kommun**:
A kommun the map covers, because its layers have a snapshot (Uppsala for now). Anywhere else the place is "not covered yet".

**Snapshot**:
A dated local copy of a pilot kommun's area layers, fetched with `python -m place.fetch`. The property is looked up live instead.

## Relationships

- A **Detaljplan** goes through **Ingestion**: PDF to **OCR Markdown**, then **Document chunks**, each with an **Embedding**.
- A **Law** goes through **Ingestion** straight from TXT into **Law chunks**, each with an **Embedding**.
- A **User** has one **Account** and many **Chat sessions**. A **Chat session** has many **Chat messages**.
- A user message becomes a **Parsed query**. If location or units are missing, the reply is a **Clarifying prompt**.
- Otherwise the **Law agent** searches **Law chunks** and the **Document agent** searches **Document chunks**, both by **Embedding** similarity.
- The **Orchestrator** combines both agents' results into a **Verdict**, which becomes the **Feasibility analysis** saved as an assistant **Chat message**.
- The **Access gate** sits in front of everything, including sign-in.
- A **Pin** in a **Pilot kommun** gives a **Property** (looked up live) and a **Place profile** (from the **Snapshot**): its **Detaljplaner**, **Land-use zones**, **Plans in progress**, **Protected areas** and **National interests**, plus the **Ancient remains** on it (looked up live). The **Likely permits** follow from that profile. The **Place card** shows all of it.
- A question asked with a **Pin** is answered from its **Place profile**, and the answer keeps that **Pin**: reopening the **Chat session** brings back its **Place chip**.
