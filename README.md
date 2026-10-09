# Pyrmit - Building Permit Agent

<table>
  <tr>
    <td valign="middle">
      Pyrmit answers questions about Swedish building permits and land-use planning (<i>Plan- och bygglagen</i>, detaljplaner, bygglov, enskilt avlopp...). A tool-calling agent searches a local corpus — 15 consolidated statutes and the planning pages and PDFs of 286 kommun websites — and answers in English, quoting the Swedish sources with clickable citations that open the original document at the passage.
    </td>
    <td valign="middle">
      <img src="frontend/public/pyrmit_middle.jpg" alt="Pyrmit Logo" width="300" />
    </td>
  </tr>
</table>

**Stack**: Next.js (frontend), FastAPI (backend), SQLite + NumPy vectors (local corpus), Neon Postgres (users and chats), OpenRouter (agent model), Snowflake arctic-embed-l-v2 (embeddings, GPU or CPU).

Architecture, data flow and every module are described in [`CLAUDE.md`](CLAUDE.md).

---

## Quick start (with the shared data)

### Requirements

| | Why |
|---|---|
| Python 3.13 + [uv](https://docs.astral.sh/uv/) | Backend |
| [Bun](https://bun.sh/) | Frontend (lockfile is `bun.lock`) |
| 8 GB RAM | Embedding model (0.9–1.7 GB) + store + backend |
| 2 GB disk (+18.4 GB with the PDFs) | Local corpus (see [Data](#data)) |
| NVIDIA GPU (optional) | Faster query embeddings; **required only to rebuild the corpus** |
| `backend/.env` | API keys, Neon `DATABASE_URL`, `JWT_SECRET_KEY`, access-gate password. Ask a maintainer; never commit it. Template: `backend/.env.example` |

### Install

```bash
git clone https://github.com/kthaisociety/pyrmit.git && cd pyrmit/backend
uv venv --python 3.13
uv pip install -r requirements.txt

# torch BEFORE the local extras, so nothing pulls the wrong build
uv pip install torch --index-url https://download.pytorch.org/whl/cu128   # NVIDIA GPU
uv pip install torch --index-url https://download.pytorch.org/whl/cpu     # no GPU (Linux; on Windows/macOS plain `uv pip install torch`)

uv pip install -e ".[local]"     # sentence-transformers, onnxruntime, bm25s, PyMuPDF, crawler deps

cd ../frontend && bun install
```

### Add the data and the config

1. Unpack the data archive into `backend/data/` (paths must match, e.g. `backend/data/index/store/st-arctic-l-v2/corpus.sqlite`).
2. Put `.env` in `backend/`. The local agent setup needs at least:

   ```properties
   CHAT_MODE=agent
   RETRIEVAL_BACKEND=local
   LOCAL_RAG_MODEL=st-arctic-l-v2
   LLM_PROVIDER=openrouter
   OPENROUTER_KEY=...            # agent model (openai/gpt-6-luna by default)
   DATABASE_URL=postgresql://... # Neon: users and chats
   JWT_SECRET_KEY=...
   ACCESS_GATE_PASSWORD=...
   HF_HUB_DISABLE_XET=1          # Hugging Face downloads can hang on Windows without it
   ```

### Run

```bash
# backend (from backend/) — Windows path shown; .venv/bin/python on Linux/macOS
.venv/Scripts/python.exe -m uvicorn main:app --port 8000
# frontend (from frontend/)
bun run dev
```

Open <http://localhost:3000>, enter the access-gate password, then sign up. The first start downloads the embedding model from Hugging Face (2.3 GB on a GPU, 570 MB on a CPU), then preloads the store in about 30–60 s.

> `docker-compose.yml` predates the local corpus (no data mount, no GPU): use the manual setup above.

---

## Embeddings: GPU or CPU, chosen automatically

The query embedding model is `Snowflake/snowflake-arctic-embed-l-v2.0` (568M parameters, 1024 dims, multilingual). `EMBEDDING_RUNTIME` (default `auto`) picks how it runs:

| Hardware | Runtime | Query time | Model RAM | Recall (R@5 / R@10) |
|---|---|---|---|---|
| CUDA GPU | torch fp16 | 23 ms | 1.7 GB | 0.944 / 0.956 |
| CPU only | **ONNX int8** (official export, `onnxruntime`) | 34 ms | 0.9 GB | 0.944 / 0.956 |
| (for reference) CPU with torch fp32 | `EMBEDDING_RUNTIME=torch` | 141 ms | 3.4 GB | 0.944 / 0.956 |

- Force a runtime with `EMBEDDING_RUNTIME=torch` or `EMBEDDING_RUNTIME=onnx`.
- The int8 query vectors are compatible with the index built on the GPU: recall is unchanged on the 45-question eval.
- Measured on an i7-12700H / RTX 4060 Laptop.

**Why this model?** On our eval (45 labelled questions, `backend/localrag/eval.py`), arctic matched the best API models at recall@5 (gemini-embedding-001 0.93, Qwen3-8B 0.91, bge-m3 0.91) with the best R@1 and MRR. It runs locally for free and is not available on OpenRouter. Translating the question to Swedish before searching matters most (bge-m3: 0.63 → 0.91). BM25 fusion and a reranker did not help.

---

## Data

Everything lives in `backend/data/` (not in git, except the benchmark results in `data/agentic/` and the retrieval evals in `data/eval/`).

| Pack | Paths (under `backend/data/`) | Size | Needed for |
|---|---|---|---|
| **Minimum** | `index/store/st-arctic-l-v2/`, `corpus/municipalities.json`, `corpus/plans.jsonl` | **1.5 GB** | The app: search (SQLite + FTS5 BM25 + vectors), kommun detection, plan registry |
| **PDFs** | `corpus/raw/web/*/pdf/`, `corpus/raw/web/*/ocr/` | **18.4 GB** | Opening a cited PDF at the passage; the agent reading plankartor (`view_map_area`, `view_pdf_page`) |
| Rebuild only | `corpus/chunks.jsonl`, `corpus/documents.jsonl`, `index/dense/st-arctic-l-v2/`, `corpus/raw/web/*/pages` + `manifest.jsonl` | 1.8 GB | Re-chunking, incremental re-indexing, resuming the crawl |

Without the PDFs the app works fully, except that PDF sources show the cited chunks only, and the map tools return an error.

**Sending the data**: pack it with `tar` (built into Windows 10+, macOS and Linux), from `backend/`:

```bash
tar -cf pyrmit-data-min.tar data/index/store/st-arctic-l-v2 data/corpus/municipalities.json data/corpus/plans.jsonl
tar -cf pyrmit-data-pdfs.tar data/corpus/raw/web/*/pdf data/corpus/raw/web/*/ocr
# unpack from backend/: tar -xf pyrmit-data-min.tar
```

| Service (free plan) | Limit | Fits |
|---|---|---|
| WeTransfer | 3 GB per 30 days, 10 transfers | Minimum pack only |
| **SwissTransfer** | 50 GB per transfer, kept 15 days, no account | Everything |
| Smash | No size limit (transfers over 2 GB are queued) | Everything |
| Google Drive | 15 GB | Minimum pack only |

---

## Rebuilding the local corpus (GPU machine)

From `backend/`. Each step reads the previous step's output. Times and sizes come from the October 2026 run (i7-12700H, RTX 4060, 286 kommuner).

| # | Command | Time | Output | Why |
|---|---|---|---|---|
| 1 | `python -m corpus.municipalities` | 1 min | `corpus/municipalities.json` (0.25 MB) | 290 kommuner + 10k localities from Wikidata: crawl seeds, and detecting the kommun in a question |
| 2 | `python -m corpus.laws` | 1 min | `corpus/raw/laws/` (2 MB) | 15 consolidated statutes (PBL, PBF, MB...) from Riksdagen open data, always current |
| 3 | `python -m corpus.crawl` | **3–4 h** | `corpus/raw/web/` (18.6 GB) | Planning pages and PDFs (detaljplaner, taxor, översiktsplan) of each kommun. Slow on purpose: robots.txt, 1 request/s per site. Resumable |
| 4 | `python -m corpus.ocr` (optional) | **~18 h** | `raw/web/*/ocr/` (8 MB) | 777 scanned PDFs (mostly old plankartor) have no text layer. EasyOCR on the GPU |
| 5 | `python -m corpus.extract` | ~5 min | `corpus/documents.jsonl` (394 MB) | Text blocks from HTML and PDFs (PyMuPDF; OCR text when available) |
| 6 | `python -m corpus.chunk` | < 1 min | `corpus/chunks.jsonl` (496 MB) | 348k chunks: one per law §, about 1,500 characters for documents, with a context header |
| 7 | `python -m localrag.index --model st-arctic-l-v2` | **1–1.5 h** | `index/dense/st-arctic-l-v2/` (690 MB) | Embeddings (93 chunks/s on the GPU; about 53 h on a CPU). Incremental: only new chunks are embedded |
| 8 | `python -m localrag.store --model st-arctic-l-v2` | ~2 min | `index/store/st-arctic-l-v2/` (1.46 GB) | What the app serves: SQLite (chunks, FTS5 BM25, places) + float16 vectors |
| 9 | `python -m corpus.plans` | ~30 s | `corpus/plans.jsonl` (8.7 MB) | Detaljplan registry + planbestämmelser for the agent's `plans` / `plan_rules` tools |

- **Total: about 5 h, or about 1 day with OCR.** Add 5–15 min for the model download and about 15 min to install CUDA torch on a fresh machine.
- **Incremental runs are fast.** Finished kommuner are skipped (`--force` recrawls them), and chunk ids include a text hash, so step 7 only embeds what changed.
- After OCR, rerun steps 5 to 9. Restart the backend after step 8.
- Rebuild on a GPU, then share the result: re-indexing on a CPU takes about 53 h and OCR takes days.

---

## Benchmarks

| | Command | Cost |
|---|---|---|
| Retrieval eval (45 questions, recall@k / MRR) | `python -m localrag.eval --models st-arctic-l-v2 --setups dense-sv` | free (local models) |
| Agent benchmark (feasibility, case-law and plankarta cases) | `python -m agentic.bench ...` (see `agentic/bench.py`) | **spends API credits** (about $0.01 per answer) |
| Grounding of the answers | `python -m agentic.grounding <results.json>` | API credits |
| PDF reports | `python -m agentic.report`, `python -m agentic.report_technical` | free (reads the result files) |

Cases are in `backend/agentic/cases*.jsonl`. Past results are in `backend/data/agentic/` (versioned, about 50 MB) and can be browsed in the app's **Benchmark** tab.

---

## Cost and hosting (summary)

- **LLM**: about $0.007–0.011 per agent answer (GPT-6 Luna via OpenRouter, medium effort), so about $10 per 1,000 questions. It is the main cost.
- **Hosting**: the simplest setup is one VPS (4 vCPU / 8 GB / 80 GB, about €7–15 per month) with the store and the PDFs on disk, using the ONNX CPU runtime. Neon free tier keeps users and chats, and Vercel or the same VPS serves the frontend.
- **Later, at scale**: corpus on Neon pgvector (about 2.5–3 GB) and PDFs on Cloudflare R2 (about $0.13 per month). This needs the store ported to Postgres.

---

## Project layout

```
pyrmit/
├── backend/
│   ├── main.py            # FastAPI app, access gate, routers, store preload
│   ├── embeddings.py      # embedding providers + GPU/ONNX runtime selection
│   ├── routers/           # auth, chat (SSE), docs (open cited PDFs), benchmark, db browser...
│   ├── agentic/           # tool-calling agent, tools, benchmark, cases, reports
│   ├── localrag/          # disk store, retriever, BM25 analyzer, gazetteer, eval, models.toml
│   ├── corpus/            # pipeline: municipalities, laws, crawl, ocr, extract, chunk, plans, caselaw
│   ├── agents/, chunking/ # earlier pgvector RAG + feasibility agents (RETRIEVAL_BACKEND=pgvector)
│   └── data/              # corpus, index, benchmark results (mostly gitignored)
├── frontend/              # Next.js: chat, sources viewer, pipeline inspector, database & benchmark views
└── CLAUDE.md              # detailed architecture and gotchas
```
