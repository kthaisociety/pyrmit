# Multi-Agent Feasibility Analysis

This package implements a multi-agent RAG pipeline for analysing the feasibility of a development project against Swedish land law and uploaded detaljplan documents.

---

## Architecture

The agents are invoked from **two entry points** — the chat UI and a direct API:

```
Frontend Chat UI                        Direct API
─────────────────                       ──────────
POST /api/chat                     POST /api/analyze
  (ChatRequest)                      (AnalyzeRequest)
        │                                  │
        ▼                                  ▼
   chat.py router                    agents.py router
   parse_query()                     parse_query() if free-text
        │                                  │
        │  location/units missing?         │
        │  → return clarifying prompt      │
        │                                  │
        ├──────────────────────────────────┤
        │         (same from here)         │
        ├──────────────────────────────────┐
        ▼                                  ▼
  LawAgent                          DocumentAgent
  (law_chunks table)                (document_chunks table)
        │                                  │
        │  _retrieve() → top-k cosine      │  _retrieve() → top-k cosine
        │  _call_llm()  → GPT structured   │  _call_llm()  → GPT structured
        ▼                                  ▼
  law_result dict                   document_result dict
        │                                  │
        └──────────────┬───────────────────┘
                       ▼
                  Orchestrator
                       │
        ┌──────────────┴───────────────────┐
        ▼                                  ▼
  format_response()                  AnalyzeResponse JSON
  → plain text in                    → structured JSON in
    MessageResponse                    AnalyzeResponse
```

### Components

| File | Class / Function | Responsibility |
|------|-----------------|----------------|
| `base.py` | `BaseRAGAgent` | Shared embedding, retrieval, LLM call, JSON parsing |
| `law_agent.py` | `LawAgent` | Queries `law_chunks`; interprets statutory regulations |
| `document_agent.py` | `DocumentAgent` | Queries `document_chunks`; analyses detaljplan precedents |
| `orchestrator.py` | `Orchestrator` | Combines both agent results into a feasibility verdict |
| `parsers.py` | `parse_query`, `format_response` | NL query parsing and response formatting |

---

## Data Flow

### 1. Input

The endpoint accepts either a **free-text query** or **structured fields**:

```json
// Free-text
{ "query": "Can I build 20 apartments in Södermalm?" }

// Structured
{ "location": "Södermalm", "project_type": "multi-family residential", "units": 20 }

// Mixed — structured fields override parsed values
{ "query": "...", "location": "Södermalm", "units": 20 }
```

If `query` is provided, `parse_query()` extracts `location`, `units`, and `project_type` via regex. Explicit fields always win.

### 2. LawAgent

Builds a search string from `location + project_type + units` and calls `_retrieve()` against `law_chunks` using pgvector cosine distance (`text-embedding-3-large`, 3072-dim). The top-5 chunks are injected into a structured GPT prompt that asks for a JSON response:

```json
{
  "max_units_allowed": 15,
  "base_zoning": "R2 medium density",
  "applicable_laws": ["PBL 4 kap 5 §", "BBR 3:1"],
  "conditions": ["environmental impact study required"],
  "special_provisions": "density bonus if ≥20% affordable",
  "confidence": 0.85
}
```

### 3. DocumentAgent

Same retrieval pattern against `document_chunks` (OCR-processed detaljplan PDFs). The prompt asks for historical precedent analysis:

```json
{
  "similar_cases": [{ "address": "...", "units": 18, "outcome": "APPROVED", "year": 2022, "conditions": [] }],
  "approval_rate": "72%",
  "common_requirements": ["parking compliance", "noise study"],
  "typical_timeline_months": 14,
  "political_climate": "generally supportive of densification",
  "confidence": 0.75
}
```

### 4. Orchestrator

Combines both results to produce a feasibility verdict:

| Condition | Status |
|-----------|--------|
| Legally allowed AND approval rate ≥ 70 % | `HIGHLY FEASIBLE` |
| Legally allowed AND approval rate ≥ 40 % | `FEASIBLE WITH CHALLENGES` |
| Units exceed legal maximum | `NOT FEASIBLE` |
| Legal limit unknown or data insufficient | `UNCERTAIN` |

Confidence is expressed as an integer percentage, capped by the weakest of the two agent confidence scores.

### 5. Output

```json
{
  "feasibility": "HIGHLY FEASIBLE",
  "confidence": 78,
  "summary": "Project appears viable. Law allows up to 25 units...",
  "law_findings": "Maximum allowed: 25 units\nApplicable laws: PBL 4 kap 5 §",
  "case_findings": "2 similar cases found. Approval rate: 72%",
  "requirements": ["environmental impact study", "parking compliance"],
  "timeline": 14,
  "next_steps": [
    "Schedule pre-application meeting with planning department",
    "Prepare formal application with required documents",
    "Engage community early to build support"
  ]
}
```

---

## BaseRAGAgent

All agents extend `BaseRAGAgent` which provides four shared methods:

```python
_embed(text)              # → list[float]  — OpenAI text-embedding-3-large
_retrieve(query, k=5)     # → list[str]    — pgvector cosine distance on self.model_class
_call_llm(system, user)   # → str          — GPT-3.5-turbo at temperature=0
_extract_json(text)       # → dict         — strips markdown fences then JSON-parses
```

Agents declare their DB table by passing the SQLAlchemy model class to the constructor:

```python
LawAgent      → BaseRAGAgent(db, client, LawChunk,     "Law Agent")
DocumentAgent → BaseRAGAgent(db, client, DocumentChunk, "Document Agent")
```

---

## Calling the API

### Authenticated request (bearer token required)

```bash
# Get a bearer token first
TOKEN=$(curl -s -X POST http://localhost:8000/api/auth/token \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=you@example.com&password=secret" | jq -r '.access_token')

# Run feasibility analysis
curl -X POST http://localhost:8000/api/analyze \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "location": "Södermalm",
    "project_type": "multi-family residential",
    "units": 20
  }'
```

### Free-text query

```bash
curl -X POST http://localhost:8000/api/analyze \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"query": "Can I build 20 apartment units in Södermalm?"}'
```

### Python (inside the FastAPI app)

```python
from sqlalchemy.orm import Session
from openai import OpenAI

from agents.law_agent import LawAgent
from agents.document_agent import DocumentAgent
from agents.orchestrator import Orchestrator

client = OpenAI(api_key="...")

def run_analysis(db: Session, location: str, project_type: str, units: int) -> dict:
    law_agent      = LawAgent(db, client)
    document_agent = DocumentAgent(db, client)
    orchestrator   = Orchestrator(law_agent, document_agent)
    return orchestrator.analyze(location, project_type, units)
```

### Formatting the result for display

```python
from agents.parsers import format_response

result = orchestrator.analyze(...)
print(format_response(result))
```

---

## Adding a New Agent

1. Create `backend/agents/my_agent.py` subclassing `BaseRAGAgent`.
2. Pass the target SQLAlchemy model class to `super().__init__()`.
3. Implement `query(location, project_type, units) -> dict`.
4. Wire into `Orchestrator.__init__` and `Orchestrator.analyze`.

```python
from agents.base import BaseRAGAgent
from models import MyChunk

class MyAgent(BaseRAGAgent):
    def __init__(self, db, openai_client):
        super().__init__(db, openai_client, MyChunk, "My Agent")

    def query(self, location, project_type, units) -> dict:
        docs = self._retrieve(f"{location} {project_type} {units}")
        # ... build prompt, call _call_llm, return _extract_json result
```
