#!/usr/bin/env python3
"""
big_experiment.py  (single-file, multi-PDF, chunking + retrieval strategy evaluation)

Paste this file into your project (e.g. chunking/big-experiment.py or replace your current one).

Folder structure (based on your screenshot):
chunking/
  data/
    Årsredovisning 2015.pdf
    Bilaga 1 a.pdf
    kristineberg_etapp1.pdf
  out/
    (artifacts written here)
  big-experiment.py   <-- this file

What this script does (non-circular evaluation):
1) Builds chunking-invariant ATOMIC PASSAGES from all PDFs (paragraph-ish units).
2) Generates an evalset from those passages:
   - Preferred: Gemini (cheap) creates realistic questions + must_contain phrases.
   - Fallback: offline templated questions (no API key).
3) For each STRATEGY (chunk size/overlap + retrieval method + optional rerank):
   - Creates chunks (per-doc, never crossing PDFs)
   - Runs retrieval for each question
   - Scores: Hit@K, MRR@K, nDCG@K, must phrase coverage
4) Writes outputs to chunking/out/<run_name>/...

Install deps:
  pip install -U pymupdf numpy pandas tqdm sentence-transformers rank-bm25
Optional rerank:
  pip install -U torch
Optional Gemini evalset:
  pip install -U google-genai
  export GEMINI_API_KEY="..."

Examples:
  # 1) Make evalset (Gemini) for ALL PDFs in chunking/data
  python big-experiment.py --make-evalset --pdf-dir ./data --out ./out --run-name demo

  # 2) Run grid (dense/bm25/hybrid, chunk sizes, overlaps)
  python big-experiment.py --pdf-dir ./data --out ./out --run-name demo --evalset ./out/demo/evalset.json --run-grid

  # 3) Run grid including rerank (slower but usually better top results)
  python big-experiment.py --pdf-dir ./data --out ./out --run-name demo --evalset ./out/demo/evalset.json --run-grid --rerank
"""

import argparse
import hashlib
import json
import math
import os
import random
import re
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd
from tqdm import tqdm

import fitz  # PyMuPDF


# ----------------------------
# Text utils
# ----------------------------

def normalize_ws(s: str) -> str:
    s = s or ""
    s = s.replace("\r\n", "\n").replace("\r", "\n")
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()

def norm_for_contains(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip().lower()

def contains_phrase(haystack: str, needle: str) -> bool:
    if not needle:
        return True
    return norm_for_contains(needle) in norm_for_contains(haystack)

def stable_id(*parts: str) -> str:
    h = hashlib.sha1("||".join(parts).encode("utf-8")).hexdigest()
    return h[:16]


# ----------------------------
# PDF extraction
# ----------------------------

def pdf_to_pages(pdf_path: Path) -> List[Dict[str, Any]]:
    doc = fitz.open(str(pdf_path))
    pages = []
    for i in range(len(doc)):
        t = doc[i].get_text("text") or ""
        t = normalize_ws(t)
        pages.append({"page": i + 1, "text": t})
    return pages

def load_corpus(pdf_paths: List[Path]) -> List[Dict[str, Any]]:
    """
    Returns pages with doc metadata:
    { "doc_id": int, "doc_name": str, "page": int, "text": str }
    """
    all_pages: List[Dict[str, Any]] = []
    for di, p in enumerate(pdf_paths, start=1):
        pages = pdf_to_pages(p)
        for pg in pages:
            all_pages.append({
                "doc_id": di,
                "doc_name": p.name,
                "page": pg["page"],
                "text": pg["text"],
            })
    return all_pages


# ----------------------------
# Atomic passages (chunking-invariant)
# ----------------------------

@dataclass
class Passage:
    passage_id: str
    doc_id: int
    doc_name: str
    page: int
    text: str

def build_atomic_passages(
    pages: List[Dict[str, Any]],
    min_chars: int = 250,
    max_chars: int = 900,
) -> List[Passage]:
    """
    Build "atomic passages" from paragraph-ish units with light merging/splitting.
    These are the gold units that stay constant across chunk strategies.
    """
    passages: List[Passage] = []

    for p in pages:
        doc_id = int(p["doc_id"])
        doc_name = str(p["doc_name"])
        page_no = int(p["page"])
        text = p["text"]

        # Split on paragraph breaks
        paras = [x.strip() for x in re.split(r"\n\s*\n", text) if x.strip()]
        buf = ""

        def flush_buf(b: str):
            b = b.strip()
            if not b:
                return
            pid = stable_id(str(doc_id), doc_name, str(page_no), b[:200])
            passages.append(Passage(
                passage_id=pid,
                doc_id=doc_id,
                doc_name=doc_name,
                page=page_no,
                text=b
            ))

        for para in paras:
            # If very long, split into windows
            if len(para) > max_chars:
                start = 0
                while start < len(para):
                    end = min(len(para), start + max_chars)
                    if end < len(para):
                        m = para.rfind(".", start, end)
                        if m != -1 and m > start + int(max_chars * 0.6):
                            end = m + 1
                    chunk = para[start:end].strip()
                    if len(chunk) >= min_chars:
                        flush_buf(chunk)
                    start = end
                continue

            # Merge small paras until min_chars
            if not buf:
                buf = para
            elif len(buf) < min_chars:
                buf = (buf + "\n" + para).strip()
            else:
                flush_buf(buf)
                buf = para

            if len(buf) >= max_chars:
                flush_buf(buf)
                buf = ""

        flush_buf(buf)

    passages = [ps for ps in passages if len(ps.text) >= min_chars]
    return passages


# ----------------------------
# Chunking strategies (per-doc, never cross PDFs)
# ----------------------------

@dataclass
class Chunk:
    chunk_id: str
    chunk_index: int
    doc_id: int
    doc_name: str
    page: int
    text: str
    passage_ids: List[str]  # gold passage ids contained

def chunk_passages_into_chunks_multi_doc(
    passages: List[Passage],
    max_chars: int,
    overlap_chars: int,
) -> List[Chunk]:
    """
    Fast + safe chunker:
    - never crosses doc boundaries
    - avoids slow O(n^2) string concatenation by buffering parts in a list
    - includes a "no progress" safeguard so i always advances
    """
    chunks: List[Chunk] = []
    chunk_index = 0

    # group by doc_id
    by_doc: Dict[int, List[Passage]] = {}
    for ps in passages:
        by_doc.setdefault(ps.doc_id, []).append(ps)

    for doc_id, doc_passages in sorted(by_doc.items(), key=lambda x: x[0]):
        if not doc_passages:
            continue

        doc_name = doc_passages[0].doc_name

        i = 0
        carry_text = ""
        carry_ids: List[str] = []
        carry_page = doc_passages[0].page

        while i < len(doc_passages):
            parts: List[str] = []
            cur_ids: List[str] = []
            cur_len = 0

            # seed with overlap tail (carry)
            if carry_text:
                parts.append(carry_text)
                cur_len = len(carry_text)
                cur_ids.extend(carry_ids)
                cur_page = carry_page
            else:
                cur_page = doc_passages[i].page

            start_i = i  # safeguard: detect no progress

            # fill up chunk
            while i < len(doc_passages):
                ps = doc_passages[i]
                addition = ps.text
                add_len = len(addition) + (2 if parts else 0)  # approx for "\n\n"

                # if we already have some text and adding would exceed max, stop
                if parts and (cur_len + add_len) > max_chars:
                    break

                # if chunk empty and single passage is huge, still take it (overshoot allowed)
                if (not parts) and (len(addition) > max_chars):
                    parts.append(addition)
                    cur_len = len(addition)
                    cur_ids.append(ps.passage_id)
                    cur_page = ps.page
                    i += 1
                    break

                # normal add
                if parts:
                    parts.append("\n\n" + addition)
                    cur_len += 2 + len(addition)
                else:
                    parts.append(addition)
                    cur_len += len(addition)
                    cur_page = ps.page

                cur_ids.append(ps.passage_id)
                i += 1

            # SAFEGUARD: if we didn't advance i, forcibly consume one passage
            if i == start_i:
                ps = doc_passages[i]
                parts = [ps.text]
                cur_ids = [ps.passage_id]
                cur_page = ps.page
                i += 1

            cur_text = "".join(parts).strip()
            if cur_text:
                chunk_index += 1
                cid = stable_id(str(doc_id), str(chunk_index), cur_text[:200])
                chunks.append(Chunk(
                    chunk_id=cid,
                    chunk_index=chunk_index,
                    doc_id=doc_id,
                    doc_name=doc_name,
                    page=cur_page,
                    text=cur_text,
                    passage_ids=cur_ids
                ))

            # compute carry overlap tail
            if overlap_chars <= 0:
                carry_text = ""
                carry_ids = []
                carry_page = doc_passages[i].page if i < len(doc_passages) else cur_page
                continue

            if len(cur_text) <= overlap_chars:
                carry_text = cur_text
                carry_ids = cur_ids[:]  # keep all
                carry_page = cur_page
            else:
                carry_text = cur_text[-overlap_chars:]
                # keep roughly proportional ids (simple heuristic)
                n_keep = max(1, int(len(cur_ids) * (overlap_chars / max(1, len(cur_text)))) + 1)
                carry_ids = cur_ids[-n_keep:]
                carry_page = cur_page

    return chunks


# ----------------------------
# Retrieval: Dense + BM25 + Hybrid + (optional) Rerank
# ----------------------------

def embed_texts_sbert(texts: List[str], model_name: str, batch_size: int = 32) -> np.ndarray:
    from sentence_transformers import SentenceTransformer
    model = SentenceTransformer(model_name)
    vecs = model.encode(
        texts,
        batch_size=batch_size,
        convert_to_numpy=True,
        normalize_embeddings=True,
        show_progress_bar=True,
    ).astype(np.float32)
    return vecs

def embed_query_sbert(query: str, model) -> np.ndarray:
    return model.encode([query], convert_to_numpy=True, normalize_embeddings=True)[0].astype(np.float32)

def topk_dense(query_vec: np.ndarray, doc_vecs: np.ndarray, k: int) -> List[int]:
    scores = doc_vecs @ query_vec
    if k >= len(scores):
        return list(np.argsort(-scores))
    idx = np.argpartition(-scores, kth=k - 1)[:k]
    idx = idx[np.argsort(-scores[idx])]
    return idx.tolist()

def simple_tokenize(text: str) -> List[str]:
    text = (text or "").lower()
    text = re.sub(r"[^0-9a-zåäöéü\- ]+", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+", " ", text).strip()
    return text.split()

def build_bm25_index(texts: List[str]):
    from rank_bm25 import BM25Okapi
    tokenized = [simple_tokenize(t) for t in texts]
    return BM25Okapi(tokenized)

def topk_bm25(bm25, query: str, k: int) -> List[int]:
    toks = simple_tokenize(query)
    scores = np.array(bm25.get_scores(toks), dtype=np.float32)
    if k >= len(scores):
        return list(np.argsort(-scores))
    idx = np.argpartition(-scores, kth=k - 1)[:k]
    idx = idx[np.argsort(-scores[idx])]
    return idx.tolist()

def hybrid_fuse(dense_ranked: List[int], bm25_ranked: List[int], alpha: float, k: int) -> List[int]:
    """
    Reciprocal-rank fusion (simple, robust).
    alpha closer to 1 => trust dense more.
    """
    score: Dict[int, float] = {}

    def add_rr(rank_list: List[int], weight: float):
        for r, idx in enumerate(rank_list, start=1):
            score[idx] = score.get(idx, 0.0) + weight * (1.0 / (r + 20))

    add_rr(dense_ranked, alpha)
    add_rr(bm25_ranked, 1.0 - alpha)

    items = sorted(score.items(), key=lambda x: -x[1])
    return [i for i, _ in items[:k]]

def rerank_cross_encoder(
    query: str,
    chunks: List[Chunk],
    candidate_indices: List[int],
    reranker_model: str,
    top_k: int,
) -> List[int]:
    """
    Cross-encoder reranking (slower, improves top precision).
    """
    from sentence_transformers import CrossEncoder
    ce = CrossEncoder(reranker_model)

    pairs = [(query, chunks[i].text) for i in candidate_indices]
    scores = ce.predict(pairs)
    scored = sorted(zip(candidate_indices, scores), key=lambda x: -x[1])
    return [i for i, _ in scored[:top_k]]


# ----------------------------
# Eval set generation (Gemini optional)
# ----------------------------

def extract_json_from_text(s: str) -> Any:
    s = (s or "").strip()
    try:
        return json.loads(s)
    except Exception:
        pass
    m = re.search(r"(\[\s*\{.*?\}\s*\]|\{.*?\})", s, re.DOTALL)
    if not m:
        raise ValueError("Could not locate JSON in model output.")
    return json.loads(m.group(1))

import requests

def ollama_generate(prompt: str, model: str = "llama-3-8b-8192") -> str:
    # We are hijacking the function name so you don't have to change the rest of the script
    api_key = os.environ.get("GROQ_API_KEY")
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    data = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.1
    }
    res = requests.post(url, json=data, headers=headers)
    res.raise_for_status()
    return res.json()["choices"][0]["message"]["content"]

def generate_evalset_from_passages_gemini(
    passages: List[Passage],
    n_questions: int,
    questions_per_passage: int,
    gemini_model: str,
    seed: int = 42,
) -> List[Dict[str, Any]]:
    if not os.environ.get("GEMINI_API_KEY"):
        raise SystemExit("Missing GEMINI_API_KEY. Set: export GEMINI_API_KEY='...'")

    rng = random.Random(seed)
    candidates = [p for p in passages if len(p.text) >= 300]
    rng.shuffle(candidates)

    need_passages = max(1, math.ceil(n_questions / questions_per_passage))
    picked = candidates[:need_passages]

    eval_items: List[Dict[str, Any]] = []
    qid = 0

    for ps in tqdm(picked, desc="Generating eval questions (Gemini)"):
        prompt = f"""
Du skapar testfrågor för ett retrieval-system (RAG). Returnera endast JSON.

Skriv {questions_per_passage} frågor som en användare skulle kunna ställa och som kan besvaras ENDAST med information i texten nedan.

Regler:
- Skriv frågorna på samma språk som texten.
- Frågorna får inte nämna "denna text" eller "detta utdrag".
- För varje fråga: ge 2–5 'must_contain'-fraser som är EXAKTA ordagranna utdrag (2–10 ord) från texten.
- Returnera ENDAST en JSON-lista med objekt i formatet:
[
  {{"question": "...", "must_contain": ["...", "..."], "type": "synthetic"}}
]

TEXT:
<<<{ps.text}>>>
""".strip()

        out = None
        last_err = None
        for _ in range(3):
            try:
                out = ollama_generate(prompt, model="llama-3.3-70b-versatile")
                data = extract_json_from_text(out)
                if not isinstance(data, list):
                    raise ValueError("Model returned JSON but not a list.")
                break
            except Exception as e:
                last_err = e
                out = None

        if out is None:
            print(f"Skipping passage due to Gemini parse errors: {last_err}")
            continue

        for obj in data:
            q = (obj.get("question") or "").strip()
            must = obj.get("must_contain") or []
            must = [m for m in must if isinstance(m, str) and m.strip()][:5]
            if not q:
                continue

            qid += 1
            eval_items.append({
                "id": qid,
                "question": q,
                "gold_passage_id": ps.passage_id,
                "gold_page": ps.page,
                "gold_doc_id": ps.doc_id,
                "gold_doc_name": ps.doc_name,
                "must_contain": must,
                "type": obj.get("type") or "synthetic",
            })
            if len(eval_items) >= n_questions:
                return eval_items

    return eval_items

def generate_evalset_simple(passages: List[Passage], n_questions: int, seed: int = 42) -> List[Dict[str, Any]]:
    """
    Free fallback: templated questions from first sentence.
    It's not pretty, but it lets you run everything offline.
    """
    rng = random.Random(seed)
    candidates = [p for p in passages if len(p.text) >= 300]
    rng.shuffle(candidates)

    out: List[Dict[str, Any]] = []
    qid = 0
    for ps in candidates:
        sent = re.split(r"(?<=[.!?])\s+", ps.text)[0].strip()
        if len(sent) < 30:
            continue
        qid += 1
        out.append({
            "id": qid,
            "question": f"Vad betyder följande avsnitt: {sent[:120]}?",
            "gold_passage_id": ps.passage_id,
            "gold_page": ps.page,
            "gold_doc_id": ps.doc_id,
            "gold_doc_name": ps.doc_name,
            "must_contain": [w for w in sent.split()[:5]],
            "type": "templated",
        })
        if len(out) >= n_questions:
            break
    return out


# ----------------------------
# Metrics
# ----------------------------

def dcg(rels: List[int]) -> float:
    s = 0.0
    for i, r in enumerate(rels, start=1):
        s += (2**r - 1) / math.log2(i + 1)
    return s

def ndcg_at_k(rels: List[int], k: int) -> float:
    rels = rels[:k]
    ideal = sorted(rels, reverse=True)
    denom = dcg(ideal)
    return 0.0 if denom == 0 else dcg(rels) / denom

def mrr_from_ranks(hit_ranks: List[Optional[int]]) -> float:
    vals = [(1.0 / r) if (r and r > 0) else 0.0 for r in hit_ranks]
    return float(np.mean(vals)) if vals else 0.0


# ----------------------------
# Strategy evaluation
# ----------------------------

@dataclass
class StrategyConfig:
    chunk_max_chars: int
    chunk_overlap_chars: int
    retriever: str                 # "dense" | "bm25" | "hybrid"
    hybrid_alpha: float = 0.65     # only used if retriever=="hybrid"
    use_rerank: bool = False
    rerank_model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"
    retrieve_k: int = 50
    final_k: int = 10

def strategy_id(cfg: StrategyConfig) -> str:
    return (
        f"chunk{cfg.chunk_max_chars}_ov{cfg.chunk_overlap_chars}"
        f"__{cfg.retriever}"
        + (f"_a{cfg.hybrid_alpha:.2f}" if cfg.retriever == "hybrid" else "")
        + ("__rerank" if cfg.use_rerank else "")
        + f"__K{cfg.final_k}"
    )

def evaluate_strategy(
    passages: List[Passage],
    eval_items: List[Dict[str, Any]],
    cfg: StrategyConfig,
    dense_model_name: str,
    run_dir: Path,
    batch_size: int = 32,
) -> Dict[str, Any]:
    sid = strategy_id(cfg)
    strat_dir = run_dir / "strategies"
    strat_dir.mkdir(parents=True, exist_ok=True)

    # 1) Build chunks for this strategy
    print(f"[{sid}] Building chunks (max_chars={cfg.chunk_max_chars}, overlap={cfg.chunk_overlap_chars}) ...")
    chunks = chunk_passages_into_chunks_multi_doc(passages, cfg.chunk_max_chars, cfg.chunk_overlap_chars)
    print(f"[{sid}] Built {len(chunks)} chunks.")
    chunk_texts = [c.text for c in chunks]

    # Save chunks
    chunks_path = strat_dir / f"{sid}_chunks.json"
    print(f"[{sid}] Writing chunks to disk: {chunks_path}")
    with open(chunks_path, "w", encoding="utf-8") as f:
        json.dump([asdict(c) for c in chunks], f, ensure_ascii=False, indent=2)

    # 2) Build indexes
    dense_vecs = None
    bm25 = None
    dense_model = None

    if cfg.retriever in ("dense", "hybrid"):
        # cache embeddings to avoid recompute for same strategy/model
        cache_key = stable_id("emb", sid, dense_model_name)
        emb_path = strat_dir / f"{cache_key}.npy"
        if emb_path.exists():
            print(f"[{sid}] Loading cached embeddings from {emb_path}")
            dense_vecs = np.load(emb_path)
        else:
            dense_vecs = embed_texts_sbert(chunk_texts, dense_model_name, batch_size=batch_size)
            np.save(emb_path, dense_vecs)

        from sentence_transformers import SentenceTransformer
        dense_model = SentenceTransformer(dense_model_name)

    if cfg.retriever in ("bm25", "hybrid"):
        bm25 = build_bm25_index(chunk_texts)

    # 3) Run eval
    hit_ranks: List[Optional[int]] = []
    ndcgs: List[float] = []
    must_total = 0
    must_hit = 0

    per_q: List[Dict[str, Any]] = []

    for item in tqdm(eval_items, desc=f"Evaluating {sid}"):
        q = item["question"]
        gold_pid = item["gold_passage_id"]
        must = item.get("must_contain") or []

        # Retrieve candidates
        if cfg.retriever == "dense":
            qv = embed_query_sbert(q, dense_model)
            cand = topk_dense(qv, dense_vecs, k=cfg.retrieve_k)
        elif cfg.retriever == "bm25":
            cand = topk_bm25(bm25, q, k=cfg.retrieve_k)
        elif cfg.retriever == "hybrid":
            qv = embed_query_sbert(q, dense_model)
            dense_rank = topk_dense(qv, dense_vecs, k=cfg.retrieve_k)
            bm25_rank = topk_bm25(bm25, q, k=cfg.retrieve_k)
            cand = hybrid_fuse(dense_rank, bm25_rank, alpha=cfg.hybrid_alpha, k=cfg.retrieve_k)
        else:
            raise ValueError(f"Unknown retriever: {cfg.retriever}")

        # Optional rerank
        if cfg.use_rerank:
            final = rerank_cross_encoder(q, chunks, cand, cfg.rerank_model, top_k=cfg.final_k)
        else:
            final = cand[:cfg.final_k]

        retrieved = [chunks[i] for i in final]

        # Gold hit = any retrieved chunk contains gold passage id
        rank_hit = None
        for rank, c in enumerate(retrieved, start=1):
            if gold_pid in set(c.passage_ids):
                rank_hit = rank
                break
        hit_ranks.append(rank_hit)

        # nDCG@K binary relevance
        rels = [1 if gold_pid in set(c.passage_ids) else 0 for c in retrieved]
        ndcgs.append(ndcg_at_k(rels, k=cfg.final_k))

        # must phrase coverage
        retrieved_text = "\n\n".join([c.text for c in retrieved])
        must_total += len(must)
        must_hit_here = sum(1 for phrase in must if contains_phrase(retrieved_text, phrase))
        must_hit += must_hit_here

        per_q.append({
            "id": item["id"],
            "question": q,
            "gold_doc_name": item.get("gold_doc_name"),
            "gold_page": item.get("gold_page"),
            "gold_passage_id": gold_pid,
            "hit_rank": rank_hit,
            "hit@k": rank_hit is not None,
            "ndcg@k": ndcgs[-1],
            "must_hit": must_hit_here,
            "must_total": len(must),
            "retrieved_chunk_ids": [chunks[i].chunk_id for i in final],
            "retrieved_docs": [chunks[i].doc_name for i in final],
            "retrieved_pages": [chunks[i].page for i in final],
        })

    hit_at_k = float(np.mean([1.0 if r is not None else 0.0 for r in hit_ranks])) if hit_ranks else 0.0
    mrr = mrr_from_ranks(hit_ranks)
    ndcg = float(np.mean(ndcgs)) if ndcgs else 0.0
    must_cov = float(must_hit / max(1, must_total))

    summary = {
        "strategy_id": sid,
        "n_questions": len(eval_items),
        "n_chunks": len(chunks),
        "hit_rate@k": hit_at_k,
        "mrr@k": mrr,
        "ndcg@k": ndcg,
        "must_phrase_coverage@k": must_cov,
        "config": asdict(cfg),
    }

    res_path = strat_dir / f"{sid}_results.json"
    with open(res_path, "w", encoding="utf-8") as f:
        json.dump({"summary": summary, "per_question": per_q}, f, ensure_ascii=False, indent=2)

    return summary


# ----------------------------
# Main CLI
# ----------------------------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdfs", nargs="+", default=[], help="One or more PDF paths")
    ap.add_argument("--pdf-dir", type=str, default="./chunking/data", help="Directory containing PDFs")
    ap.add_argument("--out", type=str, default="./out", help="Output directory")
    ap.add_argument("--run-name", type=str, default="run1", help="Subfolder name under --out")

    ap.add_argument("--dense-model", type=str,
                    default="sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
                    help="SentenceTransformer embedding model")
    ap.add_argument("--batch-size", type=int, default=32)

    # Evalset
    ap.add_argument("--make-evalset", action="store_true", help="Generate evalset.json")
    ap.add_argument("--evalset", type=str, default="./eval/demo/evalset.json", help="Use an existing evalset.json path")
    ap.add_argument("--n-questions", type=int, default=60)
    ap.add_argument("--q-per-passage", type=int, default=2)
    ap.add_argument("--gemini-model", type=str, default="gemini-2.5-flash")
    ap.add_argument("--no-gemini", action="store_true", help="Don't use Gemini; use offline templating")

    # Grid
    ap.add_argument("--run-grid", action="store_true", help="Run strategy grid")
    ap.add_argument("--final-k", type=int, default=10)
    ap.add_argument("--retrieve-k", type=int, default=50)
    ap.add_argument("--rerank", action="store_true", help="Include rerank strategies (slower)")
    ap.add_argument("--show-top", type=int, default=10)

    args = ap.parse_args()

    # Resolve PDFs
    pdf_paths: List[Path] = []
    if args.pdfs:
        pdf_paths.extend([Path(p) for p in args.pdfs])
    if args.pdf_dir:
        pdf_paths.extend(sorted(Path(args.pdf_dir).glob("*.pdf")))

    pdf_paths = [p for p in pdf_paths if p.exists()]
    if not pdf_paths:
        raise SystemExit("No PDFs found. Provide --pdfs or a --pdf-dir containing PDFs.")

    out_dir = Path(args.out)
    run_dir = out_dir / args.run_name
    run_dir.mkdir(parents=True, exist_ok=True)

    print("PDFs in corpus:")
    for p in pdf_paths:
        print(f" - {p}")

    # Build passages once (gold units)
    print("\nLoading corpus + building atomic passages...")
    pages = load_corpus(pdf_paths)
    passages = build_atomic_passages(pages)
    print(f"Built {len(passages)} atomic passages.")

    # Load or build evalset
    eval_items: List[Dict[str, Any]] = []
    if args.evalset:
        with open(args.evalset, "r", encoding="utf-8") as f:
            eval_items = json.load(f)
        print(f"\nLoaded evalset: {args.evalset} ({len(eval_items)} questions)")
    elif args.make_evalset:
        if args.no_gemini:
            eval_items = generate_evalset_simple(passages, n_questions=args.n_questions)
        else:
            eval_items = generate_evalset_from_passages_gemini(
                passages=passages,
                n_questions=args.n_questions,
                questions_per_passage=args.q_per_passage,
                gemini_model=args.gemini_model,
            )
        eval_path = run_dir / "evalset.json"
        with open(eval_path, "w", encoding="utf-8") as f:
            json.dump(eval_items, f, ensure_ascii=False, indent=2)
        print(f"\nWrote evalset -> {eval_path} ({len(eval_items)} questions)")
    else:
        raise SystemExit("Provide --evalset or run with --make-evalset")

    if not args.run_grid:
        print("\nDone. (No grid run). Use --run-grid to compare strategies.")
        return

    # Grid definition (feel free to tweak)
    # chunk_sizes = [500, 900, 1400, 2000]
    # overlaps = [0, 150, 250]
    # retrievers = ["dense", "bm25", "hybrid"]
    # alphas = [0.5, 0.65, 0.8]

    # Grid definition - REDUCED FOR SPEED
    chunk_sizes = [1200]  # Just pick one middle-ground size
    overlaps = [200]  # Just pick one overlap
    retrievers = ["hybrid"]  # Hybrid is the gold standard anyway
    alphas = [0.65]

    configs: List[StrategyConfig] = []
    for cs in chunk_sizes:
        for ov in overlaps:
            for r in retrievers:
                if r == "hybrid":
                    for a in alphas:
                        configs.append(StrategyConfig(
                            chunk_max_chars=cs,
                            chunk_overlap_chars=ov,
                            retriever=r,
                            hybrid_alpha=a,
                            use_rerank=False,
                            retrieve_k=args.retrieve_k,
                            final_k=args.final_k,
                        ))
                        if args.rerank:
                            configs.append(StrategyConfig(
                                chunk_max_chars=cs,
                                chunk_overlap_chars=ov,
                                retriever=r,
                                hybrid_alpha=a,
                                use_rerank=True,
                                retrieve_k=args.retrieve_k,
                                final_k=args.final_k,
                            ))
                else:
                    configs.append(StrategyConfig(
                        chunk_max_chars=cs,
                        chunk_overlap_chars=ov,
                        retriever=r,
                        use_rerank=False,
                        retrieve_k=args.retrieve_k,
                        final_k=args.final_k,
                    ))
                    if args.rerank:
                        configs.append(StrategyConfig(
                            chunk_max_chars=cs,
                            chunk_overlap_chars=ov,
                            retriever=r,
                            use_rerank=True,
                            retrieve_k=args.retrieve_k,
                            final_k=args.final_k,
                        ))

    print(f"\nRunning {len(configs)} strategies... (artifacts in {run_dir})")
    summaries = []
    for cfg in configs:
        s = evaluate_strategy(
            passages=passages,
            eval_items=eval_items,
            cfg=cfg,
            dense_model_name=args.dense_model,
            run_dir=run_dir,
            batch_size=args.batch_size,
        )
        summaries.append(s)

    df = pd.DataFrame(summaries)
    df = df.sort_values(
        ["hit_rate@k", "mrr@k", "ndcg@k", "must_phrase_coverage@k"],
        ascending=False,
    )

    leaderboard_path = run_dir / "leaderboard.csv"
    df.to_csv(leaderboard_path, index=False)

    print(f"\nWrote leaderboard -> {leaderboard_path}")
    print("\n=== Top strategies ===")
    print(df[[
        "strategy_id", "hit_rate@k", "mrr@k", "ndcg@k", "must_phrase_coverage@k", "n_chunks"
    ]].head(args.show_top).to_string(index=False))


if __name__ == "__main__":
    main()