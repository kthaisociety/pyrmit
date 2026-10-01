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

## Relationships

- A **Detaljplan** goes through **Ingestion**: PDF to **OCR Markdown**, then **Document chunks**, each with an **Embedding**.
- A **Law** goes through **Ingestion** straight from TXT into **Law chunks**, each with an **Embedding**.
- A **User** has one **Account** and many **Chat sessions**. A **Chat session** has many **Chat messages**.
- A user message becomes a **Parsed query**. If location or units are missing, the reply is a **Clarifying prompt**.
- Otherwise the **Law agent** searches **Law chunks** and the **Document agent** searches **Document chunks**, both by **Embedding** similarity.
- The **Orchestrator** combines both agents' results into a **Verdict**, which becomes the **Feasibility analysis** saved as an assistant **Chat message**.
- The **Access gate** sits in front of everything, including sign-in.
