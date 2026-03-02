# Legal RAG System for Land Development

A multi-agent Retrieval-Augmented Generation (RAG) system for analyzing legal and regulatory requirements for land development projects.

## Project Overview

This system uses three specialized agents:
1. **Orchestrator** - Coordinates the analysis and synthesizes results
2. **Law Agent** - RAG agent that searches legal/regulatory documents
3. **Case Agent** - RAG agent that analyzes historical permit cases

## Features

- Natural language query interface
- Vector-based document retrieval
- Structured legal analysis
- Historical precedent analysis
- Confidence scoring
- Actionable recommendations

## Installation

### Prerequisites

- Python 3.8 or higher
- Google API key (for Gemini)

### Setup Steps

1. **Clone or extract this project**

2. **Create a virtual environment**
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

4. **Get your Google API key**
   - Visit: https://makersuite.google.com/app/apikey
   - Create a new API key
   - Enable the Generative Language API

5. **Set up environment variables**
   ```bash
   cp .env.template .env
   ```
   Then edit `.env` and add your Google API key:
   ```
   GOOGLE_API_KEY=your-actual-api-key-here
   ```

## Usage

### Step 1: Prepare Your Data

Add documents to the data directories:
- `data/laws/` - Add legal documents (zoning codes, statutes) as .txt files
- `data/cases/` - Add historical case documents (permit applications, decisions) as .txt files

Sample data files are included to get you started.

### Step 2: Ingest Data into Vector Databases

```bash
python ingest_data.py
```

This will:
- Process all documents in `data/laws/` and `data/cases/`
- Create vector embeddings
- Store them in `vector_dbs/` directory

### Step 3: Run the System

```bash
python main.py
```

### Example Queries

```
> Can I build 20 units in Palo Alto?

> What are the requirements for a 25-unit apartment in Palo Alto?

> Is an 18-unit development feasible in Palo Alto?
```

## Project Structure

```
legal-rag-system/
├── README.md                 # This file
├── requirements.txt          # Python dependencies
├── .env.template            # Environment variable template
├── main.py                  # Main entry point
├── ingest_data.py          # Data ingestion script
├── agents/
│   ├── __init__.py
│   ├── orchestrator.py     # Orchestrator agent
│   ├── law_agent.py        # Law RAG agent
│   └── case_agent.py       # Case RAG agent
├── utils/
│   ├── __init__.py
│   ├── vector_store.py     # Vector database utilities
│   └── parsers.py          # Query parsing utilities
├── data/
│   ├── laws/               # Legal documents (add your .txt files here)
│   └── cases/              # Case documents (add your .txt files here)
└── vector_dbs/             # Generated vector databases (created by ingest_data.py)
```

## How It Works

### Architecture

```
┌─────────────────────────────────────────┐
│         ORCHESTRATOR                     │
│         (Coordinator)                    │
│                                          │
│  - Parses user query                    │
│  - Calls specialist agents              │
│  - Synthesizes results                  │
└─────────────────────────────────────────┘
              │
              ├──────────────┬──────────────┐
              ▼              ▼              
    ┌─────────────┐  ┌─────────────┐
    │ LAW AGENT   │  │ CASE AGENT  │
    │ (RAG)       │  │ (RAG)       │
    └─────────────┘  └─────────────┘
         │                  │
         ▼                  ▼
    ┌─────────┐      ┌─────────┐
    │Vector DB│      │Vector DB│
    │ (Laws)  │      │ (Cases) │
    └─────────┘      └─────────┘
```

### Process Flow

1. User enters a natural language query
2. Orchestrator parses the query (location, project type, units)
3. Orchestrator calls Law Agent and Case Agent in parallel
4. Each RAG agent:
   - Searches its vector database
   - Retrieves relevant documents
   - Uses LLM to interpret and structure findings
5. Orchestrator combines results using decision logic
6. System returns structured analysis with recommendations

## Sample Data

The project includes sample data for Palo Alto, California:

**Laws:**
- Palo Alto Municipal Code (R-2 zoning)
- California Density Bonus Law

**Cases:**
- 456 Oak Street (22-unit apartment - APPROVED)
- 789 Elm Avenue (18-unit condo - APPROVED)

## Extending the System

### Add More Jurisdictions

1. Add legal documents to `data/laws/`
2. Add historical cases to `data/cases/`
3. Re-run `python ingest_data.py`

### Add More Agents

Create new agent files in `agents/` directory:
- Environmental agent (CEQA/NEPA)
- Building code agent
- Utilities agent

Then integrate them into the orchestrator.

### Improve Query Parsing

The current parser uses regex. For better accuracy:
- Use an LLM-based parser
- Add geocoding for address resolution
- Extract more detailed requirements

### Add a Web Interface

Create a Flask or FastAPI frontend:
```python
from flask import Flask, request, jsonify
from main import run_analysis

app = Flask(__name__)

@app.route('/analyze', methods=['POST'])
def analyze():
    query = request.json['query']
    result = run_analysis(query)
    return jsonify(result)
```

## Cost Estimates

Per query (using Gemini 1.5 Pro):
- Law Agent: ~$0.00375 (input) + ~$0.015 (output)
- Case Agent: ~$0.00375 (input) + ~$0.015 (output)
- Embedding searches: ~$0.0001
- **Total: ~$0.04 per analysis**

At 1000 queries/month: ~$40/month

Note: Gemini pricing is significantly more affordable than GPT-4. Check current rates at https://ai.google.dev/pricing

## Troubleshooting

### Error: "Database not found"
- Run `python ingest_data.py` first to create vector databases

### Error: "No documents found"
- Make sure .txt files exist in `data/laws/` and `data/cases/`
- Check file permissions

### Error: "Google API error" or "GOOGLE_API_KEY not found"
- Verify your API key in `.env` file
- Ensure the key is valid at https://makersuite.google.com/app/apikey
- Check that the Generative Language API is enabled for your project
- Verify you have billing enabled on your Google Cloud project

### Poor results
- Add more relevant documents to your data directories
- Increase `k` parameter in similarity search (agents/*.py)
- Adjust chunk sizes in `utils/vector_store.py`

## License

MIT License - Feel free to modify and use for your projects.

## Contributing

This is a starter template. Contributions welcome:
- Add more document types (PDF, DOCX support)
- Improve parsing accuracy
- Add more sample data
- Create additional agent types
- Build web interface

## Support

For questions about ReGen Villages integration, contact the project team.

For technical issues with this code, please review the troubleshooting section above.

## Acknowledgments

Built for ReGen Villages project by James Ehrlich at Stanford University.
