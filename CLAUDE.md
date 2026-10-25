# CLAUDE.md

## Hard Constraints

- **Do not make any git-related actions** (no commits, no pushes, no branch operations)
- **Do not create documentation files** unless explicitly requested

---

## Project Overview

Pyrmit is a Swedish legal RAG (Retrieval-Augmented Generation) chat assistant focused on Swedish land law and urban planning regulations (*fastighetsrätt*, *Plan- och bygglagen*). Planning documents (detaljplaner as PDF) are OCR-processed (Mistral), chunked, and embedded into a PostgreSQL+pgvector database alongside chunked Swedish law texts. The chat translates the user's question to English, retrieves relevant law and document chunks, and calls an OpenAI model (directly or via Vercel AI Gateway) to answer **in English**, quoting Swedish source text verbatim. When a question contains both a location and a number of units, a multi-agent feasibility analysis runs instead of plain RAG.

---

## System Topology

```
User (browser)
    |
    | fetch('/api/...') with Authorization: Bearer <JWT> (token kept in localStorage)
    v
Next.js Frontend (frontend/ -- port 3000)
    |
    | next.config.js rewrite: /api/* -> API_PROXY_TARGET (default http://localhost:8000)
    v
FastAPI Backend (backend/ -- port 8000)
    |
    |--- Access-gate middleware (main.py + dev_access.py) -- global password, cookie
    |--- Access gate router (/api/access-gate/unlock)
    |--- Auth router   (/api/auth/*)      -- signup, signin, token, signout, me, password
    |--- Chat router   (/api/chat, /api/chat/stream, /api/sessions/*, /api/history)
    |--- Chunks router (/api/chunks/*)    -- ingest detaljplan PDF/markdown, ingest data folder
    |--- Agents router (/api/analyze)     -- multi-agent feasibility analysis
    |--- DB browser    (/api/db/*)        -- read-only browse/search of law_chunks & document_chunks
    |
    |--- Agents (agents/)
    |       |--- BaseRAGAgent: embed (direct OpenAI) + pgvector cosine search + LLM call
    |       |--- LawAgent -> law_chunks, DocumentAgent -> document_chunks
    |       |--- Orchestrator: runs both in parallel, rule-based feasibility verdict
    |
    |--- Chunking pipeline (chunking/ + ocr/)
    |       |--- PDF -> Mistral OCR -> Markdown
    |       |--- Markdown/TXT -> DetaljplanChunker / LawChunker
    |       |--- OpenAI text-embedding-3-large (3072-dim)
    |       |--- PushDB (psycopg2 on DATABASE_URL) -> document_chunks / law_chunks
    |
    |--- Observability (observability.py) -- optional Langfuse tracing of LLM calls & retrieval
    |
    v
PostgreSQL + pgvector (hosted on Neon; DATABASE_URL in backend/.env)
    Tables: users, accounts, sessions (unused), chat_sessions, chat_messages,
            document_chunks (Vector 3072), law_chunks (Vector 3072)
```

Note: `docker-compose.yml` still defines a local `db` pgvector container (seeded with `backend/db/init.sql`), but the backend talks to whatever `DATABASE_URL` points at — normally Neon, so the local container sits unused.

### Package Map

| Name       | Location          | Type                 | Purpose                                                        |
| ---------- | ----------------- | -------------------- | -------------------------------------------------------------- |
| `backend`  | `backend/`        | Python (FastAPI)     | REST API, auth, chat with RAG, chunk ingestion, DB models      |
| `agents`   | `backend/agents/` | Python               | Multi-agent RAG: LawAgent + DocumentAgent + Orchestrator       |
| `corpus`   | `backend/corpus/` | Python (CLI)         | Offline corpus: Wikidata kommuner, Riksdagen laws, kommun website crawl, text extraction, chunking |
| `localrag` | `backend/localrag/` | Python             | Local retrieval: GPU embeddings, Swedish BM25, hybrid + rerank, kommun gazetteer, eval |
| `agentic`  | `backend/agentic/` | Python              | Tool-calling agent over the local corpus (CHAT_MODE=agent) + feasibility case benchmark |
| `frontend` | `frontend/`       | TypeScript (Next.js) | Chat UI with sidebar, settings, auth page, access-gate page    |

---

## State Ownership

| Concern                        | Owner          | Key File(s)                                                       |
| ------------------------------ | -------------- | ----------------------------------------------------------------- |
| Access gate (global password)  | Backend        | `backend/dev_access.py`, `backend/routers/access_gate.py`, `backend/main.py` |
| User auth (JWT)                | Backend        | `backend/routers/auth.py`, `backend/security.py`, `backend/dependencies.py` |
| Auth token storage             | Frontend       | `frontend/lib/auth.ts` (localStorage, `authFetch`)                |
| Chat session & message history | Backend (DB)   | `backend/routers/chat.py`, `backend/models.py`                    |
| Query translation / parsing    | Backend        | `backend/routers/chat.py`, `backend/agents/parsers.py`            |
| Embedding provider / model     | Backend        | `backend/embeddings.py` (`EMBEDDING_*` env, used by query + ingest; `EMBEDDING_RUNTIME` GPU/ONNX choice) |
| Embedding generation (query)   | Backend        | `backend/agents/base.py` (`_embed`)                               |
| Embedding generation (ingest)  | Backend        | `backend/chunking/ingest_pipeline.py`                             |
| RAG retrieval                  | Backend        | `backend/agents/base.py` (`_retrieve*` methods)                   |
| Feasibility verdict            | Backend        | `backend/agents/orchestrator.py`                                  |
| Document chunking (detaljplan) | Backend        | `backend/chunking/chunk_detaljplan.py`                            |
| Law chunking                   | Backend        | `backend/chunking/chunk_laws.py`                                  |
| DB push (ingestion)            | Backend        | `backend/db/push_db.py`                                           |
| DB models (SQLAlchemy ORM)     | Backend        | `backend/models.py`                                               |
| LLM client / model selection   | Backend        | `backend/llm.py` (`LLM_PROVIDER`), `backend/observability.py`, `backend/agents/base.py` (`LLM_MODEL`) |
| Embedding benchmark            | Backend        | `backend/benchmark/`                                              |
| Chat UI / session switching    | Frontend       | `frontend/components/Chat.tsx`, `frontend/components/Sidebar.tsx` |
| Pipeline inspector / DB browser UI | Frontend   | `frontend/components/PipelineTrace.tsx`, `frontend/components/DatabaseBrowser.tsx` |
| Auth & access-gate pages       | Frontend       | `frontend/app/(protected)/auth/`, `frontend/app/dev-access/`      |

---

## Data Flow

### Document Ingestion (Detaljplan PDF)

```
1. POST /api/chunks/ingest-detaljplan { input_path, output_path?, document_name, document_id, ... }  (auth required)
   or POST /api/chunks/ingest-data-folder { data_dir, markdown_output_dir, ... } for a whole folder
2. backend/chunking/ingest_pipeline.py:
   a. ensure_markdown_source: if PDF -> Mistral OCR -> .md saved to data/ocr_markdown/
   b. DetaljplanChunker splits markdown into semantic chunks
   c. embed_texts_batch: OpenAI text-embedding-3-large (batched, 3072-dim)
   d. PushDB.push_chunks -> document_chunks (psycopg2, DATABASE_URL)
3. Returns { inserted, deleted } counts
```

### Law Ingestion (Static TXT files)

```
1. Run backend/chunking/ingest_laws.py (CLI only, no API endpoint)
2. LawChunker splits law TXT by chapter (kap.) / section (§)
3. Embed with OpenAI text-embedding-3-large
4. PushDB.push_law_chunks -> law_chunks
```

### Offline Corpus + Local Retrieval (`RETRIEVAL_BACKEND=local`)

Everything lives in `backend/data/` (gitignored, ~20 GB with PDFs; only `data/agentic/` (benchmark results) and
`data/eval/` are versioned). The README has the install, data sharing and rebuild guide with times and sizes. Steps, from `backend/`:

```
python -m corpus.municipalities   # Wikidata -> data/corpus/municipalities.json (290 kommuner, websites, ~10k localities)
python -m corpus.laws             # Riksdagen open data -> data/corpus/raw/laws/*.txt (15 consolidated SFS)
python -m corpus.crawl            # kommun websites -> data/corpus/raw/web/<code>/{pages,pdf,manifest.jsonl}
python -m corpus.ocr              # PP-OCRv6 (backend/.venv-ocr, GPU) of PDFs flagged needs_ocr -> raw/web/<code>/ocr/
python -m corpus.extract          # -> data/corpus/documents.jsonl (PyMuPDF text blocks, OCR text when available)
python -m corpus.pdf_filter features|classify|llm|apply   # relevance filter of the crawled PDFs (see below)
python -m corpus.chunk            # -> data/corpus/chunks.jsonl (one chunk per law §, ~1500-char doc chunks)
python -m localrag.index --model st-arctic-l-v2  # embeddings -> data/index/dense/<model>/ (incremental)
python -m localrag.store --model st-arctic-l-v2  # disk store served by the app: SQLite (chunks, FTS5 BM25, places) + vectors.npy
python -m localrag.eval --models st-bge-m3 ... # retrieval eval on localrag/questions.jsonl -> data/eval/ (tagged with the corpus)
python -m corpus.plans            # detaljplan registry + planbestämmelser -> data/corpus/plans.jsonl (needs the store)
python -m corpus.check            # data checks after a rebuild (exit 1 on an error); then agentic.replay, agentic.coverage score
```

- `corpus.plans` (rule-based, ~30 s): a plan = the detaljplan PDFs of a kommun whose file names reduce to the same
  key (role words, dates, versions, agenda numbering removed), named by the plan page that links only them, else by
  "Detaljplan för ..." on the first page; plan pages without PDFs are plans too (listing pages excluded). Status from
  the page URL and the documents (laga kraft date, ANTAGANDE/GRANSKNINGS/SAMRÅDSHANDLING). Provisions = coded lines
  (e1, h1, f2, B, +0.0...) and measure sentences after "PLANBESTÄMMELSER" (looser on plankartor, stricter in
  planbeskrivningar), with law ref, topics (building_area, height, storeys, plot_size, no_building, ...) and numbers.
  Each is tied to its chunk for citation; `corpus.chunk` drops paragraphs repeated across the corpus (standard plan
  wording), so ~2 % fall back to a chunk of the same plankarta (`exact: false`). ~8.2k plans / 260 kommuner, ~1.4k
  with ~15.6k provisions. Which map area carries which code is not extracted (needs the vision model).
- `corpus.ocr` writes the job list (`data/corpus/ocr_jobs.jsonl`) by tier (`TIERS`, `ocr_tier`; a first page larger
  than A3 = a map; plan documents typed "other" count as plans: `PLAN_WORDS` / the current `doc_type` rules, e.g.
  Huddinge's "Bestämmelse0126k-7018", Kalix's "_PK" files), every page: 1 plan maps and provisions (~12.5 h, 5.4k
  PDFs), 2 plan texts (~16 h), 3 other planning types (~4 h), 4 studies attached to plans (~1 h), 5 other (~12 h), ~46 h
  in all (2026-10-24, 0.66 s per tile); `MAX_TIER = 5` (`--max-tier` stops earlier); short documents first within a
  tier; outputs of any PP-OCRv6 setting are kept once their cut lines are joined (`"text_from": "words"`), EasyOCR's
  are redone. Cut lines: a printed line crossing a tile edge is read cut in both tiles; until 2026-10-24 21:00 both
  were kept whole ("gäller bestämm iller bestämmelsen inom", 2x the repeated word pairs); now each tile gives the
  line's words of its core (each engine word carries its line number) and `join_cut_lines` glues a word cut by the
  edge ("byggnads" + "byggnadsarea"); the ~1.4k outputs from before are redone after the unread PDFs of their tier.
  GPU memory: DirectML keeps the buffers of every input shape it has run (recognition batch widths vary), so one
  process grew from ~3 to 7 GB of the 8 GB in 2 h, spilled into shared memory and read ~35 % fewer words per second;
  the worker exits after `RECYCLE_PAGES` (250) pages with `RECYCLE_EXIT` and `corpus.ocr` starts a fresh one (its
  skip test reads only the first bytes of each output), or sooner when the card's used memory (`nvidia-smi`, all
  processes) passes `RECYCLE_GPU_MB` (6.5 GB, after `RECYCLE_MIN_PAGES`): text pages took it to 7.4 GB within 250 pages. MuPDF refuses to decode a whole image over its size limit
  ("Overly large image": a 20674 x 19691 px scan of a 2.6 m Strömstad plankarta, 1 page of the 11k scans) and
  rendered the page blank; `render` then renders it in 2000 px strips. Speed (2026-10-24, same 24 first-night PDFs: 249 -> 152 s, -39 %, 4 % fewer words):
  detection input capped at 1280 px (`DET_SIDE`, `--det-side 0` = whole 2000 px tile: same words and labels on the
  benchmark, 139 vs 140 of 305); recognition cut to its 550 Latin characters (`latin_rec_model`, of 18,710: the
  multilingual model also reads Chinese...; output layer and metadata character list sliced, made once in
  `<venv>/fast/`: ~35x less copied to the CPU per batch, same or better accuracy); `speed_up_rapidocr` (detection
  pre-processing with `cv2.dnn.blobFromImage` instead of float64 numpy, word boxes one matrix product per line:
  -12.5 % on real plans, identical words). One process (`WORKERS = 1`, `--shard i/n` exists): on real plan pages two
  were 34 % slower in total (small benchmark crops had shown +28 %: measure on real pages).
  CUDA (`--cuda`, `backend/.venv-ocr-cuda` with onnxruntime-gpu 1.23 and torch's CUDA 12 / cuDNN 9 DLLs,
  `use_cuda_dlls`): cuDNN re-plans every convolution (~3 s) whenever an input shape changes, so `FixedShapes` pads
  inputs to a few fixed shapes, one session each; then no faster than DirectML (0.55 vs 0.51 s per tile) and its
  float16 models read nothing (overflow): DirectML stays the default and starts `corpus/ocr_engines.py --jobs` in `backend/.venv-ocr`
  (PP-OCRv6 medium on DirectML; text pages at 300 dpi, pages larger than A3 at 200, 40 pages max). Each
  `ocr/<pdf id>.json` holds `pages` (text in reading order, what `corpus.extract` uses) and `words` ([page, x0, y0, x1,
  y1, text, score] in PDF points of the unrotated page, like `get_text("words")`: `view_map_area` finds labels there on
  scans). Resumable (an output of the same engine is skipped). ~10.5k scanned PDFs / 44k pages at ~1.1 s per 2000 px
  tile = ~66 h of GPU (5-35 s per plankarta); then rerun `corpus.extract`, the PDF filter, `corpus.chunk`, `localrag.index`, `localrag.store`,
  `corpus.plans`. It needs the GPU memory the backend's store takes (vectors ~3.9 GB + model): run it with the app
  stopped. The child process gets no `PYTHONHOME` (the .venv interpreter sets it to its own 3.13 base: inherited,
  .venv-ocr's 3.12 loaded the 3.13 stdlib, "SRE module mismatch").

- The crawler parses HTML with the charset httpx found (lxml alone read pages without a declared charset as latin-1:
  "fÃ¶r" in titles and link texts, ~285 documents of Haninge, Göteborg, Sala, Tranås...); `corpus.extract` repairs titles
  crawled before (`common.repair_mojibake`). Their pages were also scored on garbled titles when crawled.
- The crawler honours robots.txt (`robots_parser`: Google's `*` / `$`, which urllib.robotparser ignores), 1 req/s per host,
  caps per kommun, resumes (a kommun whose manifest ends with `{"done": true}` and caps >= the requested ones is skipped).
  Pages are kept on topic keywords (`content_relevance`); links are followed on `link_relevance` (a negative word in a
  long link text, e.g. "... livsmedel" in Surahammar's home card, no longer hides an on-topic section) and from the home
  page also the site index (`_SITE_INDEX`: Webbkarta, A-Ö; Härryda builds its menus in JavaScript); pages at the last
  depth (4) still give their PDF links (all three fixed 2026-10-23, after a first full crawl that day: Härryda and
  Surahammar had 0 pages). PDFs when linked from relevant pages, minus the obvious noise only
  (`off_topic_pdf` on file name + link text: annual reports, alcohol licences, estate notices... unless a plan word;
  each skipped link is recorded in the manifest as `{"type": "skipped_pdf", ...}`, which readers ignore). Everything
  else is judged by `corpus.pdf_filter` after extraction; `corpus.extract` has no topic test any more (until 2026-10-23
  a longer list, incl. avfall / kallelse / budget / förskol, dropped 407 PDFs there on the metadata title, one a
  planuppdrag decision whose template title was "Kallelse", and the crawler skipped 2,176 links unrecorded).
  `corpus.crawl --revisit` re-reads only the pages that linked a kommun's PDFs, its stored pages and sitemaps, and
  adds the PDF links its manifest lacks, for manifests whose done line has `pdf_links` < `PDF_LINKS_VERSION`
  (bump it when the PDF link rules change): ~35k requests for the country instead of ~160k for `--force` (Norrtälje:
  314 vs 1,174 requests, 11 PDFs added, 7 of them plan investigations). One copy per `url_key` (http/https and www. variants) and per content hash (also deduplicated per kommun in
  `corpus.extract`). Caps (defaults): 1000 pages, 3000 PDFs, 40 MB per PDF, 15000 requests (2026-10-23; at 1000 PDFs /
  6000 requests 9 kommuner sat at the cap, at the older 30 PDFs 232 of 286). Göteborg (1480) answered nothing on the
  2026-10-23 crawl and keeps its old 30-PDF crawl. The manifest is written to
  `manifest.jsonl.part` and replaces `manifest.jsonl` at the end, unless the crawl got nothing (site down: the previous
  crawl stays); the done line records caps, `queue_left` and `skipped`. `resolve_root` follows the home redirect (Ängelholm ->
  engelholm.se; 404 home -> host root; http -> https), `parse_sitemap` survives bad bytes (Luleå), the client uses the
  Windows certificate store (`truststore`, Högsby) and HTTP/2 (Malmö's HTTP/1.1 headers break h11), `.stockholm` hosts are
  one site (plans on vaxer.stockholm, permits on bygglov.stockholm). Karlskrona answers 403 to the crawler.
  Wikidata websites that are wrong are fixed in `municipalities.WEBSITE_FIXES` (Gällivare: gellivare.se no longer
  answers, gallivare.se). 11 crawled PDFs end without `%%EOF` (7 unreadable, e.g. Västerås "Ärende" plankartor):
  downloaded again on 2026-10-25, the kommun servers send the same cut file.
  The technical report (section 5.1, `report_technical.design_choices`) lists these choices with their effect: update it
  when a setting changes.
- `corpus.chunk` recognises a chapter only on its own line after a blank line, so wrapped references ("4 kap.
  miljöbalken") don't open chapters; also "10 Kap." (JB) and a bare "14 kap." before its title or its 1 § (FBL), and a
  heading wrapped onto two lines is not glued to the next one (before 2026-10-22: MB 4 kap., JB 7/10/11 kap., FBL 1/14 kap.,
  MPF 4 kap., PBF 7 kap. were filed under the previous chapter; the text and chunk ids did not change); lettered paragraphs (`6 a §`) are separate chunks; transitional provisions dropped.
  Chunk ids include a text hash (not the header): `localrag.index` keeps a digest of each embedded header + text
  (`dense/<model>/digests.json`) and re-embeds in place the chunks whose header changed.
  Scale (since the 2026-10-23 crawl, ~60k PDFs, ~8x the corpus before): `corpus.extract` and `corpus.chunk` write
  documents / chunks as they come (the lists took the 16 GB machine's memory); `localrag.index` reads chunks.jsonl
  twice from disk (count, then batches) and writes into `dense/<model>/vectors.npy` opened as a memmap that grows by
  steps (`VectorStore._reserve`; rows past `len(ids.json)` are unused room; ids.json is saved every 50k chunks, after
  the vectors, so an interrupted run resumes). Before, `np.vstack` + `np.save` of the whole matrix after every batch
  was quadratic. `corpus.plans` still holds the detaljplan texts in RAM (1-2 GB). `tests/test_index.py`.
- PDF relevance filter (`corpus/pdf_filter.py`, 2026-10-23; data in `data/corpus/pdf_filter/`): the big crawl also
  brings kommun administration (miljöbalk fees, HR policies, flag rules, meeting packs...). Rules on title / file name /
  link text (`KEEP` wins over `DROP`; `KEEP_HEAD` on the first page), then a logistic regression on arctic vectors of
  those fields + the first 700 chars (trained on the rule labels, cached vectors) keeps when p >= 0.85. **No PDF is
  dropped on a rule or the model alone** (the user's rule: losing a useful document is worse than keeping noise):
  proposed drops and uncertain PDFs go to MiMo Flash (`llm`, ~$0.0001 each, keeps in doubt), the biggest uncertain ones
  were reviewed by hand (`corpus/pdf_review.jsonl`, versioned, wins over everything). `corpus.extract` skips the
  PDFs whose decision is `keep: false`; PDFs without a decision (new crawl) are kept until `features` + `classify`
  + `llm` + `classify` + `apply` (removes them from documents.jsonl without re-extracting). `llm --check-model N`
  measures the LLM's agreement with the model on a sample. Error that matters = useful documents dropped:
  `eval-sample` prints random drops (not the reviewed ones) to label in `corpus/pdf_filter_eval.jsonl` (versioned),
  `eval` gives the share per decision path with a Wilson interval (2026-10-23: 2/120, both Environmental Code fee
  schedules, which carry the enskilt avlopp permit fee: `taxa ... miljöbalk` moved from DROP to KEEP, 120 PDFs
  come back at the next classify). `tests/test_pdf_filter.py`.
- OCR benchmark (`corpus/ocr_bench.py` + `corpus/ocr_engines.py`, 2026-10-23): `sample` picks plan pages
  (synthetic = text-layer plankartor / planbeskrivningar rendered at 200 dpi and degraded like a scan, reference =
  the text layer with word boxes; real = old scans, crops transcribed by hand in `corpus/ocr_reference.jsonl`,
  versioned, words only), `crops` cuts the real crops, each engine runs from its own environment
  (`ocr_engines.py --engine easyocr|rapid-v6-small|rapid-v6-medium [--gpu]`, large pages in 2000 px tiles), `score`
  -> `data/eval/ocr-<date>.json`: words read (bag of words: a map has no reading order), within 1-2 edits, property
  labels (`\d+:\d+`; also counted when read with "." or ","), words at the right place (synthetic). PP-OCRv6 runs
  through RapidOCR (ONNX) in `backend/.venv-ocr` (gitignored) on **DirectML** (`onnxruntime-directml`; 0.75 s per
  2000 px tile with word boxes, 4.8 s on the CPU): `onnxruntime-gpu` failed on its recognition model (cuDNN errors
  with the CUDA 13 build, an illegal memory access in QuickGelu with the CUDA 12 one). Images in `data/ocr_bench/`.
  Results 2026-10-23 (real map crops / synthetic maps / synthetic text pages, words read exactly): EasyOCR (used
  before) 69 / 45 / 92 %, 0 of 13 property labels (the colon of "3:204" comes out as a point); PP-OCRv6 small
  84 / 49 / 89 %, 6 labels; **medium 87 / 52 / 93 %, 8 labels** (chosen). The synthetic maps' reference is noisy (CAD
  hatch glyphs, split words); words under 12 px are read 16 % of the time, and neither enlarging the image nor
  rendering the scans at 300 dpi helped on maps (300 dpi did help the typewritten page: 84 vs 73 %).
  Speed (2026-10-24, `ocr_engines.py --det-side N`, `-fp16` engines): float16 copies of the models (`fp16_models`,
  onnxconverter-common installed with --no-deps) are no faster on DirectML; detection ~40 % / recognition ~50 % of a
  tile's time; capping the detection input at 1280 px -25 % with no loss on synthetic maps, 960 px -36 % (-9 % of the
  labels), small -32 % (-14 % labels, -5 points on text pages), small + 1280 -50 %. A rented RTX 4090 (~$0.34/h) would
  do the whole backlog for a few dollars (not tried). `tests/test_ocr_bench.py`.
- Corpus snapshots: `CORPUS_DATA_DIR` (relative to `backend/`, default `data`) selects the directory holding
  `corpus/` + `index/`; benchmark results and evals stay in `data/agentic` / `data/eval` (`common.RESULTS_ROOT`).
  `data/small` = the 2026-10-22 corpus (7.8k PDFs, 349k chunks; for demos / the PoC): `CORPUS_DATA_DIR=data/small`
  in `.env` serves it. Its `corpus/raw` is a directory junction to `data/corpus/raw` (same PDFs), so
  `corpus.check --delete-orphan-pdfs` keeps the PDFs any snapshot's documents.jsonl references.
- `LocalRetriever` searches two pools like the chat (laws / kommun documents). The kommun pool is filtered to the
  kommuner named in the question (`gazetteer.detect_kommuner`, fallback `CorpusPlaces` for places missing from
  Wikidata, e.g. "Veda"). Modes (`LOCAL_RAG_MODE`): dense (default), bm25 (Swedish stems + compound 5-grams),
  hybrid (RRF); optional cross-encoder reranker. Defaults (`localrag/service.py`) follow the eval: arctic-l-v2 on
  the Swedish query, no BM25 fusion, no reranker (neither beat dense-sv). On the national corpus (2026-10-24, same 45
  questions, `--allow-missing` counts passages a corpus lacks as misses; `hybrid-sv-stem` = the agent's search) recall@5
  drops 0.94 -> 0.88 (dense-sv) and 0.89 -> 0.83 (hybrid-sv-stem): the 4 kommuner of the questions have 3x more
  passages, no expected passage is missing, municipal recall@5 1.00 -> 0.92 (outranked, ranks 7-12), statutes
  unchanged (0.80). Technical report section 6 (`corpus_table`), Pipeline view. The app serves from the **disk store**
  (`localrag/store.py`, `LOCAL_RAG_STORE=disk` default): chunks + metadata in SQLite, BM25 = FTS5 over pre-stemmed
  text with filter tokens (`zzpoollaw`, `zzk<code>`) so pool/kommun filters are posting-list intersections, vectors
  float16 in a memmap copied block-wise to the GPU (dense search = GPU matmul, ~0.1 s). Rebuild it after
  `localrag.index` (and restart). RAM ~1.7 GB private, mostly torch + the embedding model. `LOCAL_RAG_STORE=memory`
  loads chunks.jsonl in RAM (LocalRetriever; needed for the compound analyzer / reranker; used by the evals). Kommun
  detection is the union of Wikidata names/localities and corpus places ("Veda" is a Wikidata locality in Härnösand
  but the corpus places it in Vallentuna). The backend preloads the store/tools at startup (`main.py`).
- In the chat, the local backend asks the rewrite call for an extra `SV:` line (Swedish search query, no extra
  LLM call) and emits a `local_query` pipeline event (Swedish query + kommun filter). Embedding or BM25 on the
  English query is much worse (Swedish corpus). The feasibility path (orchestrator) still uses pgvector.

### Agentic RAG (`CHAT_MODE=agent`)

`agentic/agent.py` runs a Responses-API tool loop (default `openai/gpt-6-luna` via OpenRouter) with tools from
`agentic/tools.py` (`CorpusTools` over `_DiskCorpus` (SQLite) or `_MemoryCorpus`): `find_kommun`, `search` (hybrid
dense + BM25 "stem"), `grep`, `list_documents`, `read`, `law_section` ("PBL", "9 kap. 4 §"), `plans` / `plan_rules`
(plan registry from `data/corpus/plans.jsonl`, loaded on first use), `view_map_area` (zoomed crop of a text-layer
plankarta around a printed label such as a property number "5:125", plus the codes printed in that area with their
meaning from the registry; search/word coordinates are unrotated, rendering uses `rect * page.rotation_matrix`),
`view_pdf_page` (whole page image sent to the model), plus `answer_ready(mode)`: the agent classifies the question
(`MODES`: verdict / explain / propose / develop, described in `MODES_GUIDE`) and the final answer uses that mode's format
from `ANSWER_FORMAT` (a **Verdict:** line only for feasibility questions; propose = options named in the kommun's plans;
develop = obstacles, ways to make it work, questions for the user); `AgentRun.mode` records it. Latency is almost all model turns, so: exploration turns run at
`AGENT_EXPLORE_EFFORT` (default medium, chosen on the benchmark; low = fast mode), the tool calls of one turn run in parallel, the model calls `answer_ready` when
it has enough, and only the final answer runs at `AGENT_EFFORT` (default medium), **streamed** (`answer_delta`
events); `AGENT_MAX_STEPS` (default 10) forces the answer. `CorpusTools.warm_up()` loads the query embedding model
up front (else the first search takes ~30 s). Tool outputs tag chunks as `[c:<chunk_id>]`; the answer must cite them.
In the chat, `agentic/service.py` runs it in a thread: tool calls stream as `tool_call`/`tool_result` SSE events,
each model turn and tool call is recorded for the inspector ("Explore (agent)" step), and the answer streams as
`response.output_text.delta` with citations numbered on the fly (`CitationNumberer`: one number per source label,
partial `c:` ids and open `[...]` groups held back until complete, repeats merged); the numbered source list
("- [n] label") is appended at the end and a `citations` pipeline event maps each n to its label and cited chunks.
The answer format asks for the law reference in the sentence and `[c:id]` right after the claim, never nested.
`read` also takes the id as printed (`c:<id>`, `[c:<id>]`, `doc pdf:...` / `doc:pdf:...`), a doc_id passed as chunk_id, without its `pdf:` / `page:`
prefix or reduced to its hash (`doc_ids_ending`) (before 2026-10-22, 1,845 benchmark reads failed on the `c:` prefix, 88 % never retried); `law_section` takes
abbreviations (MPF, MBF, LRL...), names without diacritics and '9:4' / '4a §' / '18 c § punkt 1', and points to the
SFS 2025:974 renumbering when a PBL 9 kap. number is missing; `grep` needs a kommun or scope='law' (a regex over every
kommun took 12-28 s) and filters on the index; an image (`view_map_area` / `view_pdf_page`) goes with the next model
call only, then is replaced by a note (`send_images_once` in `agent.py`; the agent is told to write down what it reads); `find_kommun` lists
the kommun named outright first ("Kårsta, Vallentuna": Örebro also has a Kårsta). Document filters (2026-10-24; dev
set on the 2026-10-22 corpus, `bench --label filters` vs `toolfix`, benchmark report 2.12: used in every answer, key
points +0.026 ± 0.015 per case (MiMo) / +0.065 ± 0.028 (Luna, 41 answers re-judged before the OpenRouter credits ran
out), 2.1 fewer tool calls, first token +3 s, 5 % of greps empty vs 1 %; kept; not measured on the national corpus):
`search`, `grep` and `list_documents` take `doc_types` (`tools.DOC_TYPES`; `parse_doc_types` accepts
a string, commas, "översiktsplan") and `title_contains`, applied before ranking (`DiskStore.pool_rowids` in SQL with a
kommun; without one a cached row mask, `local_mask`, ~2 s the first time; FTS joined on chunks; `LocalRetriever` masks);
a document filter leaves the statutes out of grep; `grep(output='documents')` groups the matches per document (most
first); `list_documents` pages by `offset` (max 100). `view_map_area` on a page without text layer looks the label up
in the OCR words (`_ocr_words`, `_label_key`: "5.125" / "5,125" read for "5:125", several words in a row) and lists the
codes the OCR read in the area; not OCRed yet -> no_data. Disk-store queries on kommun
chunks filter `kind IN LOCAL_KINDS` (page, pdf) so SQLite uses the (kind, kommun_code) index (`kind != 'law'` scanned
the table, ~0.7 s per query). Robustness: ids of 8-15 hex characters (the model sometimes truncates) resolve by unique prefix
(`CorpusTools.get_chunk` -> `ids_with_prefix`), unknown ids are dropped (no "?"), and groups are split on ";" (commas
only between ids, so "PBL 9 kap. 3 §, 4 §" stays whole). The frontend turns "[n]" / "[n; m]" into clickable chips
(`linkCitations` in `Chat.tsx`; mixed or nested groups such as "[1; MB 7 kap. 15 § [2]]" become chips followed by the
reference in italics) that open
`components/SourceViewer.tsx`: the cited chunks, and the original document opened at the passage via
`routers/docs.py` (crawled PDF fetched as a blob with the auth header and shown in an iframe at
`#page=N&zoom=scale,left,top&navpanes=0`, passage highlighted; web pages and statutes opened in a new tab with a
`#:~:text=` fragment that Chrome scrolls to and highlights; scanned PDFs: page from the OCR text, no highlight).
The page is found by searching the chunk's 6-word phrases in the PDF (chunks store no page numbers).
The agent branch runs before the rewrite step and returns early.
Gotcha: **PBL 9 kap. was renumbered by SFS 2025:974** (bygglov in/outside a detaljplan now 9 kap. 56/57 §, liten
avvikelse 60-61 §, förhandsbesked 74 §; some sections have a second version in force 2027-01-01). Rulings and the
model's memory use the old numbers (9:30, 9:31 b, 9:17), so the prompt tells the agent to find provisions by wording.
Benchmark: `python -m agentic.bench` (14 feasibility cases in `agentic/cases.jsonl`: evidence recall, LLM-judge
key points, cost, latency, first-token time; RAG vs agent; `--cases-file cases_caselaw.jsonl --store disk` for cases
from any kommun on the full disk store) and `python -m agentic.grounding <results.json>` (claims supported by the
cited sources). Results in `data/agentic/`; report in `../pyrmit_doc/pyrmit_agentic_rag_report.md`.
Real-decision cases: `python -m corpus.caselaw` downloads MÖD precedents 2011- from lagen.nu (robots.txt allows the
case pages; 1 req/s, resumable) to `data/corpus/raw/caselaw/mod.jsonl` (headnote, keywords, statutes, full text,
`relevant` by topic); `python -m agentic.cases_from_caselaw` (one LLM call per ruling, spends credits) turns each into
a case (facts as question without the outcome, verdicts, key points) whose evidence labels are the longest run (>= 5
words) of the quoted statute wording found in the current law chunks (renumbering- and amendment-proof); remittals
that state the decisive test are kept as "unclear" cases, and cases with no current statute (old PBL) are kept with
no evidence label (scored on verdict + key points). Raw drafts are cached and appended one by one in
`data/corpus/raw/caselaw/case_drafts.jsonl` (rebuilding costs nothing; `--regenerate` pays again)
-> `agentic/cases_caselaw.jsonl`. The bench judge gets the text of the chunks the answer cites (a sourced fact is
not "unsupported" because the reference omits it); `--repeats N` reports per-repeat means, `--workers N` runs cases
in parallel; results are written after every case and `--resume <file>` completes an interrupted run.
Plankarta cases (`agentic/cases_from_plans.py`): the other benchmarks never need the map (2 map views in 576
answers), so this set asks about a specific property in a plan whose height / building-area rules differ by zone.
`candidates` (free) picks text-layer plankartor with >= 2 such coded rules and a property label whose surroundings
carry one (scales, legend / title-block areas and unconfirmed tract names filtered) and saves the crops in
`data/agentic/plan_cases/`; `label` (paid, vision, high effort, cached in `labels.jsonl`) reads the crop + code
meanings into a reference (applicable codes, values, a project whose feasibility depends on them) and keeps only
high-confidence ones -> `agentic/cases_plans.jsonl` (evidence = the plankarta `doc_id`; `localrag.eval.matches`
accepts `doc_id`). Check a sample of crops / labels by hand.
Tasks beyond the verdict (the product vision: also explain rules, propose projects, develop ideas): a case's `task`
(default "verdict") selects the judge prompt (`TASK_JUDGE_INSTRUCTIONS`) and the scores (`grade_answer`, shared by the
bench and the Benchmark view): `verdicts` are optional (`verdict_ok` null without them); propose cases carry `anchors`
(places the plans designate, scored by whole-word string match, `min_anchors` needed) and the judge lists the answer's
`proposals` (sourced or not); develop key points are prefixed "Obstacle:" / "Lever:" / "Ask:" (scored per kind); agent rows
get `mode` / `mode_ok`. `agentic/cases_tasks.jsonl` = 10 hand-written seeds (Vallentuna, Norrtälje, Uppsala, Gotland,
verbatim evidence); `python -m agentic.cases_from_corpus` drafts more from corpus documents (guidance pages / ÖP growth
passages / rural + VA passages + statutes) with **MiMo v2.6 Flash** (another model family than the agent), keeps only
points whose quote is found verbatim (`longest_phrase`), drafts cached in `data/agentic/task_drafts.jsonl` ->
`agentic/cases_generated.jsonl`. `--judge-model xiaomi/mimo-v2.6-flash` grades with another family (rows store
`judge_model`); `python -m agentic.rejudge <results.json> --sample 50` re-grades stored answers and prints the
inter-judge agreement; `--leakage` (no LLM) prints each evidence group's rank in a plain search on the question (rank 1-3
= the question gives the answer away). Run embedding steps on the CPU with `CUDA_VISIBLE_DEVICES= EMBEDDING_RUNTIME=onnx`
(ONNX int8 ~0.9 GB instead of torch on the CPU; the disk store falls back to numpy). Tests: `tests/test_bench_tasks.py`.
`cases_from_corpus.REVIEW` = manual corrections of generated cases by id (drop / relabel points, replace propose
anchors), applied on every rebuild: re-review after `--regenerate` (ids change when sources change). On the last allowed
turn the agent is only offered `answer_ready` (`tool_choice=required`), so a run that hits `AGENT_MAX_STEPS` still picks
its mode (before: 5/12 propose runs ended without a mode). Reports: `report.MODES_RUN` (2026-10-19) splits the effort
matrix (older runs, verdict-only prompt) from the mode-prompt runs; `mode_rows` / `task_table` / `regression_table` /
`judge_agreement` feed benchmark-report sections 2.7-2.8 and technical-report section 7.9 (English bodies only;
`PROPOSE_FIX_RUN` separates the propose re-run). `llm.get_openai_client` sets `LLM_TIMEOUT_S` (default 180 s per
response / stream chunk) and 1 retry: the SDK default (600 s, 2 retries) could hold a worker 30 min.

Status of the benchmark-scope work (2026-10-21; numbers in the reports, `data/agentic/bench-2026101[9]*`,
`bench-20261021-*`, `rejudge-*.json`): second judge MiMo agrees with Luna (same verdict 57/60, kappa 0.89, key points
r = 0.90; Luna counts ~2x more unsupported claims); the mode prompt leaves the verdict sets unchanged (14 cases 0.77 ->
0.73 key points, MÖD 0.48 -> 0.49, verdict equal); on the new tasks the agent beats the RAG (key points explain 0.69 vs
0.63, propose 0.53 vs 0.41, develop 0.70 vs 0.47). The propose fix (2026-10-21: `MODES_GUIDE` propose = "the place is
not fixed", work from the ÖP growth passages; last turn forced to `answer_ready`) took mode recognition 0.42 -> 1.00,
key points 0.53 -> 0.62, places named 0.68 -> 0.88, but evidence seen 0.64 -> 0.51 and ~85 s per answer. The manual
review rescored stored rows of 6 generated cases without LLM (rows marked `rescored`). Reports regenerated and copied
to `reports/` on 2026-10-21.
Optimisation round (2026-10-21, benchmark report 2.9, ~$2.9): dev set = the 52 cases of `cases.jsonl` +
`cases_tasks.jsonl` + `cases_generated.jsonl`, `bench --label <name>` tags the result file (`-x-<name>.json`, kept out
of the older report tables; rows store `model`), MiMo Flash judge in the run, then `agentic.rejudge --judge-model
openai/gpt-6-luna` (a gain counts only if both judges see it). Benchmark fixes first: the judge gets every cited chunk
whole (`MAX_JUDGE_SOURCES, MAX_SOURCE_CHARS = 40, 3000`; before, 15 x 1500 cut the sources of a quarter of the answers,
inflating "unsupported"); verdict cases whose question also asks how / what it takes list `modes` (`bench.mode_ok`);
3 incidental reference points dropped in `REVIEW`. Results: per-mode recipes + a site-constraint grep checklist = no
gain, less evidence read (rejected); MiMo v2.6 Flash as the agent = +0.09 key points but ~5x the unsupported claims
(Luna judge), 2.3x slower, 2x cost (rejected); "Completeness" in `ANSWER_FORMAT` (replacing "prefer fewer,
well-sourced points": the agent left facts it had read out of the answer) = +0.03 / +0.05 key points (MiMo / Luna
judge), same latency and cost, unsupported +0.5 for Luna only (adopted, now the default). Not tried: Sol (~20x Luna)
and MiMo Pro. Lesson: exploration instructions do not move the scores; the answer writing does.
Bug round (2026-10-22, `bench --label toolfix`, dev set x 3 repeats, ~$1.6 + $0.2 Luna rejudge): before it, 57 % of the
agent answers lost a `read` (ids written `c:<id>`, 1,845 reads, 88 % never retried), MB 4 kap. and other chapters were
missing, kommun-filtered SQLite queries scanned the table and every image was re-sent each turn. After the fixes
(vs `x-v3`): failed reads 2.96 -> 0.32 per answer, answer time 55-71 s -> 33-45 s, first token 46-57 s -> 22-28 s,
unsupported claims (Luna judge) 1.96 -> 1.45, key points unchanged (MiMo 0.71 -> 0.71, Luna 0.72 -> 0.69). Answers
cite ~1 % of ids miscopied after their first characters: `tools.resolve_cited` maps them to the one shown chunk with the
longest common prefix (>= 8) in the chat numbering and in the judge's sources. Benchmark report section 2.10.
Verification (2026-10-22; technical report 7.10): the bugs above passed the tests and the benchmarks, so four free checks
look at real behaviour. (1) `python -m corpus.check` after every rebuild (sections crawl / documents / laws / index /
plans; exit 1 on an error; `data/corpus/check.json`: every line with its examples (`lines`, shown by the Pipeline
view), a summary (documents per kind:type and per kommun, plan status, documents per plan), compared with the previous
run per kommun; `--only` keeps the other sections of the previous file; `--delete-orphan-pdfs`: PDFs of earlier crawls
no manifest or snapshot references, 1,814 / 5.2 GB deleted on 2026-10-24, 70 % byte-identical copies of kept PDFs;
a WARN lists documents whose text names only other kommuner, "X kommun" / "X stad": 590 of 94k on 2026-10-23, mostly
joint administrations publishing the members' plans and forms on one site, Askersund -> Laxå / Lekeberg, Avesta ->
Fagersta / Norberg, Falun -> Borlänge, Vimmerby -> Hultsfred; they are filed under the site's kommun). It found: statute sections cut on a reference wrapped after "kap." ("enligt 6 kap." + "35 § 4 miljöbalken": PBL 5 kap.
11 a §, MBF 18 §, PBF 3 kap. 2 §; `chunk.rejoin` + sections only go forward in `law_chunks`), identical statute sections
dropped by the corpus-wide chunk dedup (JB 10 kap. 3 a §; law dedup key now includes the section, ids unchanged),
6.5k duplicate pages (Sitevision `?open.12_...`, `.printable`: `crawl._VIEW_PARAMS`, page hash in the crawler and in
`corpus.extract`), Sitevision "org.mozilla.javascript.Undefined@0" lines. (2) Tool health: `ToolResult.error`
(unknown_id / bad_args / not_found / no_data / exception; `run_tool` turns a tool exception into "exception" instead of
ending the run), recorded in the steps and the `tool_result` event; `agentic.health` prints failures per tool after
every bench run (thresholds `THRESHOLDS`); report section 2.10. (3) `python -m agentic.replay` (`--search N`: also times N stored searches; p50 / p95 / max per tool) replays every distinct
stored call (not search / images) on the current corpus: no exception, a read or law_section of something the corpus
has must succeed (`tests/test_replay.py`: 1,500 calls, skipped without the store); it found reads with "doc pdf:...",
a chunk id glued to a doc prefix, a valid doc_id next to a stale chunk_id, a chunk id as doc_id (all handled now).
(4) `python -m agentic.coverage sample|fetch|score`: the other benchmarks are built from the corpus and cannot see a
missing plan; this one fetches live the plans-in-force list of 29 sampled kommuner (`agentic/coverage_sources.jsonl`,
curated) and up to 20 plans each with their PDF links (`agentic/coverage_plans.jsonl`, versioned with its date), and
scores the share found in documents.jsonl by URL. Oct 10 corpus: 24 % of 202 plans with a PDF, 8 % of their PDFs;
16 kommuner unmeasurable (plans only in a map / search application, or 1-2 plans reachable).
Next: a check step on the draft answer (each claim against its cited chunk) to cut unsupported claims; expert review of a sample of generated cases; multi-turn cases (iterating on a project with the user); merge with
the localisation work of the other developer (agent `TOOLS_GUIDE` / `tools.py` are theirs, `ROLE` / `MODES_GUIDE` /
`ANSWER_FORMAT` / bench are ours; their localisation cases can be a `locate` task in the same case format).
`python -m agentic.report [--lang en|fr|both]` (default en: the project language is English) builds the PDF report in English
(`../pyrmit_doc/pyrmit_benchmark_report.pdf`) or French (`../pyrmit_doc/pyrmit_rapport_benchmark.pdf`) from the matrix result files (merged per configuration), via
headless Chrome/Edge, charts as inline SVG; `tr(fr, en)` / `fmt` / `money` follow the module-level `LANG`.
`python -m agentic.report_technical [--lang ...]` builds the detailed technical report (`pyrmit_rapport_technique.pdf` /
`pyrmit_technical_report.pdf`): Swedish planning context, data sources and freshness plan, pipeline with code refs,
retrieval eval (from `data/eval/*.json`), how each benchmark set is built (origin, source documents, who wrote the
reference, the 14 cases listed, example cases) and scored, with the judge prompts; figures read from the data.
Split: the technical report explains, the benchmark report gives conditions + results (overview RAG vs agent, one
table per set: 14 cases, MÖD, plankarta incl. ablations). `load_runs` keys result files by (set, systems, explore,
answer, ablation) from the file name (`FILE`: `-cases_caselaw` / `-cases_plans`, `-no-<tools>`); the conclusions text
is in `build_html` (`summary`, `reading`...), written from the numbers, so update it after new runs. Only the English
text was restructured (2026-10-17); the French bodies are the older layout. Both PDFs get a clickable outline
(`write_pdf`: Chrome `--generate-pdf-document-outline`, exact heading positions; `flatten_outline` drops the h1 entry
so sections are top level). The bench's RAG answer is streamed
(`run_rag` records `first_token_s`).
The key reports (benchmark, technical, hosting PDF + Markdown) are copied into `reports/` (versioned; the generators
write to `../pyrmit_doc/`, so copy them again after regenerating).
Gotcha (Windows): stopping a background shell does not kill its Python children; a "killed" benchmark can keep running
and spending credits. Check with `Get-CimInstance Win32_Process` and `Stop-Process`; for a chained `sh script.sh`, stop
the `sh.exe` first or it starts the next step. Claude Code reaps background shells when RAM runs low (16 GB machine):
run one benchmark process at a time (threads via `--workers` are fine); results are saved per answer, `--resume` /
rerunning `agentic.rejudge` continues. A run that sits a long time before its first case may be stuck at startup
(Hugging Face model check): the result file name is stamped when the cases start.

### Chat Request

The frontend uses `POST /api/chat/stream` (SSE). `POST /api/chat` runs the same logic non-streamed.

```
1. POST /api/chat/stream { messages, session_id? }
2. Access-gate middleware, then get_current_user validates the Bearer JWT
3. Create/lookup ChatSession, save the user message AND an empty assistant message (status "streaming")
   -> the generation runs in a background thread (run_in_background) that is independent of the HTTP
   connection; the SSE response only relays its events, so closing the tab or opening another chat
   doesn't stop or lose the answer
4. LLM call: rewrite the latest message as a standalone English query
   (pulls location / units / project type from the last 5 history messages)
5. parse_query(translated) -> regex extraction of location, units, project_type (no LLM)
6a. If location OR units missing -> general RAG:
      embed once -> top-RAG_TOP_K (default 10) law + document chunks (pgvector or local corpus)
      -> LLM answers in English markdown, Swedish quotes kept verbatim, + Sources list
6b. If both present -> Orchestrator.analyze(location, project_type, units):
      LawAgent and DocumentAgent run in parallel (ThreadPoolExecutor),
      each retrieves top-5 chunks and asks the LLM for structured JSON;
      _determine_feasibility applies fixed rules (max_units_allowed vs units,
      approval_rate thresholds 0.7 / 0.4) -> HIGHLY FEASIBLE / FEASIBLE WITH
      CHALLENGES / NOT FEASIBLE / UNCERTAIN; format_response -> markdown
7. Stream SSE events: session_id, thinking, tool_call/tool_result (agent: + `chunks`, `ms`),
   pipeline, response.output_text.delta, response.completed, done (or error); `relay()` sends a
   `: keep-alive` comment after 10 s idle (`SSE_HEARTBEAT_S`): the Next.js dev rewrite drops a stream idle for
   30 s without closing it for the browser (corpus preload, long agent turns). The frontend aborts after 45 s
   without bytes (`STREAM_STALL_MS`) or a stream cut before `done`, and reloads the session (polled until done)
8. The worker updates that assistant message from the streamed events: partial content every 2 s, then
   final content + `trace` (all pipeline events) + status "done" (or "error")
```

`pipeline` events (`{type: "pipeline", stage, data}`) carry debug data for the frontend pipeline inspector:
`translation` (original/rewritten query), `intent` (parsed fields + route), `retrieval` (per agent: search query,
matched chunks with source, chunk_index, cosine distance, full content), `agent_output` (raw LLM JSON per agent),
`verdict`, and `call` (one per LLM / embedding / pgvector call: name, model, system prompt, input, output, token
usage incl. reasoning tokens and the OpenRouter `cost` in USD, reasoning effort, duration). Calls are captured by a `CallRecorder` (`backend/pipeline_trace.py`) passed to the agents
(`LawAgent(db, client, recorder)`); the streamed answer call is recorded manually in `chat.py`. All events are also
saved in `chat_messages.trace` (JSONB, ~20–60 KB per answer) and returned by `GET /api/sessions/{id}`, so reopened
conversations keep the inspector and clickable sources (only `/api/chat/stream` writes traces). Agents attach their
retrieval trace as `result["retrieval"]`, and `Orchestrator.analyze` returns raw outputs under `agent_outputs`.

Gotchas:
- A location the regex misses (e.g. "for Vallentuna" — only `in/at/i/på/vid` are recognised) silently sends the request down the general-RAG path.
- The units regex doesn't match "apartment(s)", and the translation step turns "lägenheter" into "apartments", so most chat questions never reach the feasibility path.

### Auth Flow

```
1. POST /api/auth/signup -> creates User + Account (credentials, hashed password) -> returns JWT
2. POST /api/auth/signin (JSON) or /api/auth/token (OAuth2 form) -> verifies password -> returns JWT
3. Frontend stores the JWT in localStorage and sends it as Authorization: Bearer
4. get_current_user decodes the JWT (HS256, JWT_SECRET_KEY, sub = "user:<id>")
5. POST /api/auth/signout -> no-op on the server (JWTs are stateless); the frontend just clears the token
```

The `Session` model/table exists but is never written or read.

### Access Gate

When `ACCESS_GATE_PASSWORD` (or `DEV_ACCESS_PASSWORD`) is set, every backend request except `/api/access-gate/unlock` and OPTIONS returns 401 `"Access password required"` unless it carries the `dev_access_granted` cookie or an `x-access-gate-password` header. The frontend's `authFetch` redirects to `/dev-access` on that response.

---

## API Routes

| Method | Path                              | Auth | Purpose                                         |
| ------ | --------------------------------- | ---- | ----------------------------------------------- |
| POST   | `/api/access-gate/unlock`         | No   | Submit access-gate password, set cookie         |
| POST   | `/api/auth/signup`                | No   | Register new user, return JWT                   |
| POST   | `/api/auth/signin`                | No   | Sign in (JSON), return JWT                      |
| POST   | `/api/auth/token`                 | No   | OAuth2 password-form sign in, return JWT        |
| POST   | `/api/auth/signout`               | No   | No-op (client clears token)                     |
| GET    | `/api/auth/me`                    | Yes  | Get current user                                |
| PATCH  | `/api/auth/me`                    | Yes  | Update profile name                             |
| PATCH  | `/api/auth/password`              | Yes  | Change password                                 |
| GET    | `/api/sessions`                   | Yes  | List chat sessions for user                     |
| GET    | `/api/sessions/{session_id}`      | Yes  | Get message history for a session               |
| PATCH  | `/api/sessions/{session_id}`      | Yes  | Rename a session                                |
| DELETE | `/api/sessions/{session_id}`      | Yes  | Delete a session                                |
| DELETE | `/api/sessions`                   | Yes  | Delete all sessions of the user                 |
| GET    | `/api/history`                    | Yes  | All messages of the user                        |
| POST   | `/api/chat`                       | Yes  | Send message, get full response                 |
| POST   | `/api/chat/stream`                | Yes  | Send message, stream response (SSE) — used by UI |
| POST   | `/api/chunks/ingest-detaljplan`   | Yes  | Ingest a detaljplan PDF or markdown file        |
| POST   | `/api/chunks/ingest-data-folder`  | Yes  | Ingest every supported file in a folder         |
| POST   | `/api/analyze`                    | Yes  | Multi-agent feasibility analysis                |
| GET    | `/api/db/overview`                | Yes  | Chunk counts per table and per source (`store`=neon/local) |
| GET    | `/api/db/chunks`                  | Yes  | Paginated chunks (`table`=law/document, `source` (local: kommun code), `doc_type`, `doc_id`, `q` text filter, `store`); local without a kommun: store order, `total` null with a text filter (not counted) |
| GET    | `/api/db/documents`               | Yes  | Local disk store: a kommun's documents (`source`=kommun code, `doc_type`, `q` title filter) by type then title, with chunk counts |
| POST   | `/api/db/search`                  | Yes  | Retrieval top-k on both pools, no LLM (`store`: neon = pgvector, local = localrag) |
| GET    | `/api/docs/locate`                | Yes  | Where to open a cited chunk: PDF page + zoom on the passage, or original URL with `#:~:text=` |
| GET    | `/api/docs/pdf/{chunk_id}`        | Yes  | The chunk's crawled PDF with the passage highlighted (PyMuPDF annotations) |
| GET    | `/api/docs/tool-image`            | Yes  | Image an agent tool call looked at (`tool`=view_map_area/view_pdf_page, `input`=the call's JSON arguments), re-rendered for the inspector |
| GET    | `/api/benchmark/sets`, `/cases`, `/case`, `/image/{id}` | Yes | Benchmark case sets, cases, one case + its past results (from `data/agentic/bench-*.json`), plankarta crop |
| POST   | `/api/benchmark/run`              | Yes  | Run the agent on a case now (chat settings) and grade it; background job (spends credits) |
| GET    | `/api/benchmark/run/{job_id}`     | Yes  | Progress (tool calls) and result of that job (polled: a run outlasts the frontend proxy timeout) |
| GET    | `/api/pipeline`                   | Yes  | Measurements of each corpus-building step (crawl coverage, PDF filter errors, OCR benchmark, checks, retrieval eval, plans, tool latency), read from the files the steps write; cached until one changes |

All routes are additionally behind the access gate when it is enabled.

---

## Database Schema (Key Tables)

| Table              | Key Columns                                                                              |
| ------------------ | ---------------------------------------------------------------------------------------- |
| `users`            | id, name, email, email_verified, image                                                   |
| `accounts`         | id, user_id (FK), provider_id ("credentials"), password (hash)                           |
| `sessions`         | id, user_id (FK), token, expires_at, ip_address, user_agent — **unused**                 |
| `chat_sessions`    | id, user_id (FK), title, created_at, updated_at                                          |
| `chat_messages`    | id, session_id (FK), role, content, trace (JSONB, pipeline events), status (streaming/done/error, assistant only), created_at |
| `document_chunks`  | id, document_id, document_name, chunk_index, content, embedding (3072)                   |
| `law_chunks`       | id, law_name, source_file, chapter, chapter_title, section, chunk_index, content, embedding (3072) |

Tables are created at startup via `Base.metadata.create_all` in `backend/main.py`; since `create_all` never alters existing tables, columns added later (currently `chat_messages.trace` and `status`) are added there with an idempotent `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`. Extra SQL: `backend/db/init.sql`, `backend/db/create_law_chunks.sql`, `backend/db/match_functions.sql`.

---

## Build & Run Commands

### Run the app on this machine (the normal way)

The app configuration (agent chat, local corpus, GPT-6 Luna) is in `backend/.env` with the secrets, so no
command-line overrides are needed. Don't blank `ACCESS_GATE_PASSWORD` or override `.env` values when starting it
for the user. Needs the GPU and `backend/data/` (local store, `corpus/plans.jsonl`).

```bash
# 0. Nothing already running? (a stale backend on :8000 or frontend on :3000 makes the new one fail)
#    PowerShell: Get-CimInstance Win32_Process | ? { $_.CommandLine -match 'uvicorn main:app|next' } | select ProcessId, CommandLine
# 1. Backend (background shell), from backend/ -- use the venv python, not `uv run` (re-syncs the venv)
cd backend && .venv/Scripts/python.exe -m uvicorn main:app --port 8000 > backend.log 2>&1
#    ready when http://localhost:8000/docs answers; the corpus store and embedding model preload in a
#    background thread (~30-60 s) -- the first chat waits for it
# 2. Frontend (background shell), from frontend/
cd frontend && bun run dev                         # hot reload
#    or: bun run build && bun run start            # lighter; rebuild after any frontend change
# 3. http://localhost:3000 -> access-gate password (from backend/.env, the user types it) -> sign in
```

Check: `curl -s localhost:8000/docs -o /dev/null -w "%{http_code}"` -> 200 (or 401 with the gate on: still up).
Logs: `backend.log` (startup errors: missing key, store not found, CUDA). Stopping a background shell does not
kill the Python/Node children on Windows: stop them with `Stop-Process` before restarting.

### Other commands

```bash
# Start all services via Docker (backend still uses DATABASE_URL from backend/.env)
docker-compose up --build
# frontend: http://localhost:3000   backend docs: http://localhost:8000/docs

# Backend only (dev) -- Python 3.13 + uv
cd backend && uv venv && uv pip install -r requirements.txt
uvicorn main:app --reload --port 8000

# Frontend only (dev) -- lockfile is bun.lock
cd frontend && bun install && bun run dev

# Ingest law chunks
cd backend && python chunking/ingest_laws.py

# Local RAG deps (corpus/ + localrag/): torch with CUDA first, then the optional group
cd backend && uv pip install torch --index-url https://download.pytorch.org/whl/cu128 && uv pip install -e ".[local]"

# Tests
cd backend && pytest tests/
```

### Environment Variables

Backend `.env` (see `backend/.env.example`):
```
DATABASE_URL=postgresql://...          # Neon pooled endpoint with pgvector
AI_GATEWAY_API_KEY=                    # Vercel AI Gateway for chat (preferred if set)
OPENAI_API_KEY=                        # Required for embeddings with the default EMBEDDING_PROVIDER=openai; chat fallback
LLM_PROVIDER= / LLM_MODEL=             # Optional chat override: openai | gateway | openrouter (+ OPENROUTER_API_KEY or OPENROUTER_KEY)
LLM_TIMEOUT_S=180                      # max wait per API response / stream chunk (llm.get_openai_client), 1 retry
LLM_REASONING_EFFORT=                  # e.g. high / xhigh for answers (Responses API `reasoning`); rewrites use
                                       # LLM_REWRITE_REASONING_EFFORT (default low) -- observability.create_chat_completion
EMBEDDING_PROVIDER/MODEL/DIM/...       # Optional, see backend/embeddings.py; default openai text-embedding-3-large, 3072
EMBEDDING_RUNTIME=auto                 # local (st) models: torch fp16 on a CUDA GPU, else the model's ONNX int8 export
                                       # (`onnx_file` in localrag/models.toml) on the CPU via onnxruntime | torch | onnx
RETRIEVAL_BACKEND=pgvector             # or "local" (localrag/service.py) + LOCAL_RAG_MODEL / _MODE / _DENSE_QUERY / _RERANKER
RAG_TOP_K=10                           # chunks per pool (laws / documents) given to the answer model
CHAT_MODE=rag                          # or "agent" (agentic/service.py) + AGENT_MODEL / AGENT_EFFORT (final answer,
                                       # medium) / AGENT_EXPLORE_EFFORT (tool turns, medium) / AGENT_MAX_STEPS (10)
HF_HUB_DISABLE_XET=1                   # Hugging Face downloads can hang on Windows without it
MISTRAL_API_KEY=                       # PDF OCR
JWT_SECRET_KEY=                        # Required
ACCESS_TOKEN_EXPIRE_MINUTES=10080      # 7 days (also the default): the token is not refreshed
ACCESS_GATE_PASSWORD=                  # Enables the access gate when set
APP_ENV=development                    # development -> gpt-5.4-nano, production -> gpt-5.4-mini
CORS_ALLOWED_ORIGINS=http://localhost:3000
LANGFUSE_PUBLIC_KEY= / LANGFUSE_SECRET_KEY=   # Optional tracing
# Optional cookie settings: ACCESS_GATE_COOKIE_DOMAIN / _SECURE / _SAMESITE
```

Frontend `.env`:
```
API_PROXY_TARGET=http://localhost:8000   # or NEXT_PUBLIC_API_URL; used by the next.config.js rewrite
```

---

## Key Files Reference

### Backend (Python / FastAPI)

- `backend/main.py` -- App entry: loads .env, creates tables, access-gate middleware, CORS, router registration
- `backend/dev_access.py` -- Access-gate password / cookie helpers
- `backend/security.py` -- JWT encode/decode, password hashing (pwdlib)
- `backend/dependencies.py` -- `get_current_user` (Bearer JWT -> User)
- `backend/llm.py` -- OpenAI vs Vercel AI Gateway client, model-name resolution, Responses API helpers
- `backend/observability.py` -- Langfuse-wrapped `create_chat_completion`, `create_embedding`, `start_observation` (no-ops without Langfuse)
- `backend/pipeline_trace.py` -- `CallRecorder` + `recorded_chat_completion` / `recorded_embedding`: capture prompts, outputs, usage, timings for the pipeline inspector
- `backend/models.py` -- SQLAlchemy ORM models
- `backend/schemas.py` -- Pydantic request/response schemas
- `backend/routers/auth.py` -- Signup, signin, token, signout, me, password
- `backend/routers/access_gate.py` -- Access-gate unlock endpoint
- `backend/routers/chat.py` -- Chat (plain + SSE stream): translate -> parse -> general RAG or orchestrator -> save
- `backend/routers/chunks.py` -- Ingestion endpoints
- `backend/routers/agents.py` -- `/api/analyze`
- `backend/routers/db_browser.py` -- Read-only chunk browser + semantic search (never exposes user/auth tables or
  embeddings). Local disk store (1.9M rows): kommun / type counts from `localrag.store.summary` (cached in
  `store/<model>/summary.json`, written by `localrag.store`; the GROUP BY takes ~30 s), filters on `kommun_code`
  (indexed; the kommun name and a sort over every row took 17-30 s per page)
- `backend/routers/docs.py` -- Open a cited chunk in its original document (PDF page + highlight, or URL text fragment)
- `backend/routers/benchmark.py` -- Benchmark view API: case sets (`SETS`: cases / caselaw / plans / tasks / generated), past results per case
  parsed from the result file names (`RESULT_FILE`; files from before `-explore-` count as explore = answer effort; `-x-<label>`
  runs show the label and model), and in-memory run jobs (`JOBS`, lost on restart)
- `backend/routers/pipeline.py` -- Pipeline view API, written for a reader without the project's context: six steps
  (collect, filter, read/OCR, index, plan registry, search tools), each with what it does, how it is measured, a status,
  key tiles and detail sections (tables with search / "show all", bars, meter, the `corpus.check` lines of that step
  with their examples (`_checks`: crawl / documents + statutes + index / plans; passing ones folded), removed-PDF
  examples), from `data/corpus/check.json`, the manifests' done lines, `data/agentic/coverage-*.json` / `replay-*.json`,
  the PDF filter decisions + labels, `data/eval/ocr-*.json`, the OCR outputs and the latest `localrag.eval` file;
  cached until a source file (or the OCR output count) changes. Separate from the Benchmark view (agent end to end)
- `backend/routers/queryDB.py` -- Legacy standalone `RAG()` retrieval helper, not imported anywhere (chat retrieves via agents)
- `backend/chunking/ingest_pipeline.py` -- OCR, chunk, embed, push
- `backend/chunking/ingest_data_folder.py` -- Folder-level ingestion
- `backend/chunking/chunk_detaljplan.py` / `chunk_laws.py` -- Chunkers
- `backend/chunking/ingest_laws.py` -- CLI to ingest all law TXT files
- `backend/ocr/` -- Mistral OCR helpers
- `backend/db/database.py` -- SQLAlchemy engine + `get_db`
- `backend/db/push_db.py` -- `PushDB`: psycopg2 inserts/deletes for chunk tables
- `backend/prompts/*.yaml` -- Prompt files (chat prompts are currently inline in `chat.py` / agents)
- `backend/embeddings.py` -- `Embedder` (openai / openrouter / local OpenAI-compatible server / in-process sentence-transformers), `get_embedder()` from `EMBEDDING_*` env; vector column dim = `EMBEDDING_DIM`. `st` models run on torch with a GPU, else on `_OnnxEncoder` (onnxruntime + tokenizers, CLS/mean pooling, 1024-token window) when `onnx_file` is set: arctic int8 = 34 ms/query, 0.9 GB, same recall as the GPU (R@5 0.944)
- `backend/chunking/reembed.py` -- Re-embed stored chunks with the configured model (alters the vector dim, stores the model label as column comment; `main.py` logs an error when DB and config disagree). Needs `--yes`; meant for a dedicated Neon branch
- `backend/benchmark/` -- Retrieval-only embedding benchmark: `export_corpus.py` (freeze DB chunks to `data/corpus.jsonl`), `models.toml` (models to compare), `questions.jsonl` (hand-written questions, en+sv, labelled by verbatim excerpts since law chapter/section metadata is unreliable), `generate_questions.py` (synthetic questions via the chat LLM), `run.py` (hit@k / recall@5 / MRR, per-table search like the chat; caches corpus vectors in `cache/`, writes `results/`). Runs spend API credits
- `backend/corpus/` -- `municipalities.py`, `laws.py`, `crawl.py`, `ocr.py`, `extract.py`, `chunk.py` (see "Offline Corpus"),
  `caselaw.py` (MÖD rulings from lagen.nu, for the case benchmark; not part of the searchable corpus),
  `plans.py` (detaljplan registry + planbestämmelser), `check.py` (checks after a rebuild)
- `backend/localrag/` -- `analyzer.py` (Swedish BM25 tokens), `gazetteer.py`, `index.py` (VectorStore), `retriever.py`
  (`LocalRetriever`), `service.py` (chat integration), `eval.py` + `questions.jsonl` (use-case questions with
  verbatim-excerpt / law-section labels), `rewrite_queries.py` (Swedish queries from the chat LLM), `models.toml`
  (local + OpenRouter embedding models). Do not `pip install` packages that depend on torch without the CUDA
  index (easyocr pulled in a CPU torch once)
- `backend/agentic/` -- `tools.py` (CorpusTools + tool schemas), `agent.py` (tool loop), `service.py` (chat
  integration, `CitationNumberer`), `run.py` (CLI), `bench.py` + `cases.jsonl` (case benchmark),
  `cases_from_caselaw.py` (cases from MÖD rulings), `cases_tasks.jsonl` + `cases_from_corpus.py` (explain / propose /
  develop cases), `rejudge.py` (second judge, agreement), `grounding.py`, `health.py` (failed tool calls per tool),
  `replay.py` (stored tool calls replayed on the corpus), `coverage.py` + `coverage_sources.jsonl` / `coverage_plans.jsonl`
  (share of the kommuner's listed plans in the corpus)
- `backend/tests/test_agents.py` -- Agent / parser tests (incl. `TestParseQuery`); `_extract_json` returns {} on bad
  output and the agents then return their fallback result. It stubs `sqlalchemy` in `sys.modules`, so run it in its own pytest
  process: collected together with `test_chat_background.py` the latter fails to import
- `backend/tests/test_chat_background.py` -- the streamed answer is saved when the client disconnects (SQLite + fake
  LLM). Run with `.venv/Scripts/python -m pytest tests/<file>` (not `uv run`, which re-syncs the venv to uv.lock)
- `backend/tests/test_agent_citations.py` -- streamed citation numbering for every delta size
- `backend/tests/test_bench_tasks.py` -- explain / propose / develop scoring (anchors, proposals, points per kind), fake judge
- `backend/tests/test_tools.py` -- agent tools on a fake corpus (ids as the model writes them, section formats, grep
  filters, doc_types / title filters, grep documents output, list_documents pages, view_map_area on a scan through OCR
  words, miscopied citations), law chapter chunking, title repair
- `backend/tests/test_agent_images.py` -- an image goes with the next model call only (fake LLM)
- `backend/tests/test_crawl.py` -- robots.txt wildcards, `url_key` variants, off-topic PDFs, tolerant sitemaps
- `backend/tests/test_pdf_filter.py` -- PDF filter rules, no drop without the LLM or a review
- `backend/tests/test_ocr_bench.py` -- OCR benchmark scoring (near misses, labels, placement), tiles without duplicates
- `backend/tests/test_index.py` -- VectorStore memmap growth, resume after an interrupted run
- `backend/tests/test_health.py` -- tool failure counts per tool
- `backend/tests/test_replay.py` -- stored agent tool calls replayed on the real store (skipped without it, ~2 min)
- Gotcha when editing through a shell heredoc: `\\b` in a Python string can arrive as a backspace character (it broke a
  chunker regex silently); write patch scripts to a file, and scan for control characters after shell edits

### Agents (Multi-Agent RAG)

- `backend/agents/base.py` -- `BaseRAGAgent`: `_embed` (shared embedder, returns None on failure), pgvector retrieval, `_call_llm`, `_extract_json`; defines `OPENAI_CHAT_MODEL` (overridable with `LLM_MODEL`)
- `backend/agents/law_agent.py` -- LawAgent on `law_chunks` -> JSON (max_units_allowed, applicable_laws, conditions, confidence, ...)
- `backend/agents/document_agent.py` -- DocumentAgent on `document_chunks` -> JSON (approval_rate, similar_cases, typical_timeline_months, ...)
- `backend/agents/orchestrator.py` -- Parallel agent execution + rule-based feasibility verdict
- `backend/agents/parsers.py` -- `parse_query` (regex) and `format_response` (markdown)
- `backend/agents/bygglov_ag.py` -- Empty placeholder

### Frontend (TypeScript / Next.js)

- `frontend/next.config.js` -- `/api/*` rewrite to the backend
- `frontend/lib/auth.ts` -- Token storage (localStorage), `authFetch`, access-gate redirect
- `frontend/lib/dev-access.ts`, `frontend/lib/access-gate-server.ts` -- Access-gate cookie helpers
- `frontend/app/(protected)/page.tsx` -- Main page: Sidebar + Chat
- `frontend/app/(protected)/auth/page.tsx` -- Login / signup
- `frontend/app/(protected)/layout.tsx` -- Server-side guard: redirects to `/dev-access` without the access-gate cookie
- `frontend/app/dev-access/` -- Access-gate password page
- `frontend/components/Chat.tsx` -- Message list, SSE stream consumption, session history fetch; a new chat is announced
  to the sidebar on the `session_id` event; opening another chat aborts the local stream only, and history
  messages with status "streaming" are re-fetched every 2 s until done; "Process" timeline (`LiveProgress`): one line
  per step / tool call (tool, its query or arguments, result summary, duration), the last 3 ("Show all" expands), shown
  only until the answer text starts (rebuilt from the saved trace for an answer still generating, `stepsFromTrace`); once finished, "Inspect pipeline" and a clickable "Sources" list (retrieved chunks per source, from `pipeline` events) below the answer
- `frontend/components/PipelineTrace.tsx` -- "Inspect pipeline" panel rendering `pipeline` events (live or from saved `trace`): a totals line (time, tokens, cost) then one collapsible step per stage (Understand, Retrieve, Agents, Verdict, Answer) with a one-line summary, and the stage's API calls nested inside (assigned by call kind/name in `stepOf`). An expanded `view_map_area` / `view_pdf_page` tool call shows the image the agent looked at: traces store no images (tool records carry `tool` + `image`), `ToolImage` re-renders them from the call's arguments via `/api/docs/tool-image` (older traces: tool taken from the call name)
- `frontend/components/DatabaseBrowser.tsx` -- Database view with a Neon / Local corpus toggle: stats, chunk browsing, search
  playground. Local kommun documents: kommun select (documents per kommun), document-type chips, then the kommun's
  documents by type (`DocumentList`, click one for its chunks); without a kommun, chunks in store order. Every local
  chunk (browse and search) links to its original (`SourceLinks`): crawled PDF opened at the passage in the
  `SourceViewer` panel (`autoOpen`, n = 0: no citation number) plus the PDF's URL on the kommun site, web page /
  statute in a new tab at the passage (`openPageAtChunk`); a document's "Open the PDF" lists its chunks beside it.
  `/api/db/chunks` rows carry `url`, local `/api/db/search` matches `chunk_id` / `doc_id` / `kind` / `url`
  (`localrag.service._row`). The 7 "legacy:" PoC documents have no original
- `frontend/lib/corpus.ts` -- document type names / hints and number formatting shared by the Database and Pipeline views
- `frontend/components/ChunkCard.tsx` -- Expandable chunk card (source, chunk index, distance badge, content)
- `frontend/components/SourceViewer.tsx` -- Side panel for a clicked citation [n]: cited chunks + the original document at the passage
- `frontend/components/CitedMarkdown.tsx` -- Answer markdown with [n] citation chips (`linkCitations`), shared by Chat and Benchmark
- `frontend/components/BenchmarkBrowser.tsx` -- Benchmark view (sidebar, above Database): browse the case sets, a case's
  reference (verdicts, key points, evidence, source, map crop) and past results, and "Test with the agent" (run + judge)
- `frontend/components/PipelineBrowser.tsx` -- Pipeline view (sidebar, below Benchmark), progressive: an introduction,
  a strip of the six steps (key number + status, click to open), one card per step (status, tiles; opened: what it does,
  how it is measured, collapsible detail sections), a glossary
- `frontend/components/Sidebar.tsx` -- Session list, new chat, Benchmark / Pipeline / Database / Settings buttons, user info
- `frontend/components/Settings.tsx` -- Profile / password settings

---

## Debugging Principle

> If a bug occurs, you should always be able to answer:
> **"Is this a data/retrieval bug (backend) or a display/UX bug (frontend)?"**

- **Access gate**: 401 "Access password required" -> `backend/dev_access.py`, cookie settings, `frontend/lib/auth.ts`
- **Auth bugs**: 401 "Could not validate credentials" -> expired/missing JWT, `JWT_SECRET_KEY`, `backend/security.py`, `backend/dependencies.py`
- **Wrong answer style** (generic RAG vs feasibility verdict): check the translated query and `parse_query` output (logged in observations as `parsed_location` / `parsed_units`)
- **RAG quality bugs**: open the "Pipeline inspector" on the answer (rewritten query, route, retrieved chunks + distances), or try queries in the Database view's semantic search; also retrieval logs/Langfuse (source, chunk_index, distance, preview) -> `backend/agents/base.py`, chunk sizes, embeddings
- **Law chunk metadata**: `law_chunks.chapter` / `section` drift (e.g. PBL 4 kap. 21 § stored as chapter 7 or 13) and lettered sections (`31 b §`) are merged into neighbours -> `backend/chunking/chunk_laws.py`; don't filter on them
- **No retrieval at all**: `_embed` returns None on failure (e.g. missing key for `EMBEDDING_PROVIDER`) and retrieval silently returns nothing
- **Odd feasibility verdict**: rules in `Orchestrator._determine_feasibility`; non-numeric `max_units_allowed` ("varies") yields UNCERTAIN
- **Ingestion bugs**: `backend/chunking/ingest_pipeline.py`, `backend/db/push_db.py`, `DATABASE_URL`, `MISTRAL_API_KEY`
- **Frontend bugs**: UI not updating, session not switching, redirect loops -> `frontend/components/`, `frontend/lib/auth.ts`

---

## Maintenance

After every successful change, update this CLAUDE.md if there are changes to the structure or to relevant CLAUDE.md sections.
