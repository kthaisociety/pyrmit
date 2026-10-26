## Input folders

The ingest commands read their input files from two folders inside this one. Git does not track them, so create them yourself:

- `backend/src/chunking/laws/` holds the law `.txt` files for `ingest_laws.py`.
- `backend/src/chunking/data/` holds the detaljplan PDF, Markdown and `.txt` files for `ingest_data_folder.py` and `POST /api/chunks/ingest-data-folder`.

They used to live in `backend/chunking/`. If you have files there, move them: `mv backend/chunking/laws backend/chunking/data backend/src/chunking/`.

## To run (Harj)

# To chunk
```
cd "C:\Documents\KTH AIS\pyrmit\backend"; .\venv\Scripts\Activate.ps1; $env:DATABASE_URL="postgresql://user:password@localhost:5432/pyrmit"; cd chunking; python .\create-chunks.py
```

# To check the sql
```
docker exec -it 329b9b6567f812b9616dd8680e3ef1a96d2ea599aa5a73ab9af6bc03dd510166 bash
psql -U user -d pyrmit
```

# SQL 
