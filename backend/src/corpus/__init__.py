"""
Offline corpus for the local RAG pipeline: Swedish laws (Riksdagen open data), the
municipalities' own pages and plan documents (crawled from the 290 kommun websites listed
in Wikidata), and the legacy Vallentuna documents already in the database.

Everything lives under backend/data/corpus/ (gitignored):

    municipalities.json   kommuner + their localities (gazetteer)  -> corpus.municipalities
    raw/laws/*.txt        SFS full texts                            -> corpus.laws
    raw/web/<kod>/...     crawled HTML pages and PDFs + manifest    -> corpus.crawl
    documents.jsonl       one text document per law / page / PDF    -> corpus.extract
    chunks.jsonl          retrieval units with metadata             -> corpus.chunk

Run the steps in that order, e.g. `python -m corpus.laws`.
"""
