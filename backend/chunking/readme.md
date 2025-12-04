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
