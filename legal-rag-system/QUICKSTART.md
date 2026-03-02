# QUICK START GUIDE

## Get Running in 5 Minutes

### 1. Extract the Zip File
```bash
unzip legal-rag-system.zip
cd legal-rag-system
```

### 2. Set Up Python Environment
```bash
# Create virtual environment
python -m venv venv

# Activate it
source venv/bin/activate  # Mac/Linux
# OR
venv\Scripts\activate  # Windows
```

### 3. Install Dependencies
```bash
pip install -r requirements.txt
```

### 4. Add Your OpenAI API Key
```bash
# Copy the template
cp .env.template .env

# Edit .env and add your key
# OPENAI_API_KEY=sk-your-actual-key-here
```

### 5. Ingest Sample Data
```bash
python ingest_data.py
```

This will create vector databases from the sample Palo Alto data included in the project.

### 6. Run the System
```bash
python main.py
```

### 7. Try These Example Queries

```
> Can I build 20 units in Palo Alto?

> What are the requirements for a 25-unit apartment in Palo Alto?

> Is an 18-unit development feasible in Palo Alto?
```

## What's Included

✅ Complete 3-agent RAG system (Orchestrator, Law Agent, Case Agent)
✅ Sample data for Palo Alto, California
✅ 2 law documents (zoning code, density bonus law)
✅ 3 case documents (historical permit applications)
✅ All source code with documentation
✅ Ready to run with minimal setup

## Next Steps

1. **Add your own data**: Put .txt files in `data/laws/` and `data/cases/`
2. **Re-run ingestion**: `python ingest_data.py`
3. **Test new queries**: `python main.py`

## Project Structure
```
legal-rag-system/
├── main.py              # Run this!
├── ingest_data.py       # Run this first!
├── agents/              # The 3 agents
├── utils/               # Helper functions
└── data/                # Add your documents here
    ├── laws/
    └── cases/
```

## Troubleshooting

**"OpenAI API key not found"**
→ Make sure you created `.env` file with your API key

**"Database not found"**
→ Run `python ingest_data.py` first

**"No documents found"**
→ Check that .txt files exist in `data/laws/` and `data/cases/`

## Cost Estimate

Each query costs approximately $0.06 with GPT-4.
- 10 queries = ~$0.60
- 100 queries = ~$6
- 1000 queries = ~$60

## Support

Check README.md for detailed documentation.
