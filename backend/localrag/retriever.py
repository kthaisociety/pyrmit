"""
Hybrid retrieval over the local corpus.

Like the chat, results come in two pools searched separately: "law" (statutes) and
"local" (the kommun's pages and documents). The local pool is restricted to the kommuner
named in the question (gazetteer), since 290 kommuner have near-identical pages.

    dense   cosine similarity with a local embedding model (English or Swedish query)
    bm25    Swedish BM25 (stems, optionally compound 5-grams); needs the Swedish query,
            English keywords don't match Swedish text
    hybrid  reciprocal rank fusion of dense and bm25
    rerank  optional cross-encoder (bge-reranker-v2-m3) over the fused candidates
"""

from dataclasses import dataclass

import bm25s
import numpy as np

from embeddings import Embedder
from localrag.analyzer import analyze
from localrag.gazetteer import CorpusPlaces, detect_kommuner
from localrag.index import chunk_text, embed_chunks, load_model_config

RRF_K = 60


def _normalize_in_place(tensor, block: int = 20_000):
    """Normalise a large float16 GPU matrix block by block to keep peak memory low."""
    for start in range(0, tensor.shape[0], block):
        part = tensor[start:start + block].float()
        tensor[start:start + block] = (part / part.norm(dim=1, keepdim=True).clamp_min(1e-12)).half()
    return tensor


@dataclass
class Hit:
    chunk: dict
    score: float
    rank: int


class LocalRetriever:
    def __init__(self, chunks: list[dict], model: str | None = None, bm25_modes: tuple[str, ...] = ("compound",),
                 reranker: str | None = None, device: str | None = None):
        self.chunks = chunks
        self.is_law = np.array([c["kind"] == "law" for c in chunks])
        self.kommun = np.array([c.get("kommun_code") or "" for c in chunks])
        self.places = CorpusPlaces(chunks)
        self.model = model
        self.embedder = None
        self.matrix = None
        if model:
            store = embed_chunks(model, chunks)
            self.embedder = Embedder(load_model_config(model))
            self.matrix = self._normalized_matrix(store.get([c["chunk_id"] for c in chunks]), device)
            del store
        self.bm25: dict[str, bm25s.BM25] = {}
        for bm25_mode in bm25_modes:
            index = bm25s.BM25()
            index.index([analyze(chunk_text(c), bm25_mode) for c in chunks], show_progress=False)
            self.bm25[bm25_mode] = index
        self.reranker = None
        if reranker:
            from sentence_transformers import CrossEncoder
            self.reranker = CrossEncoder(reranker, max_length=512)
            if self.reranker.model.device.type == "cuda":
                self.reranker.model.half()

    @staticmethod
    def _normalized_matrix(matrix: np.ndarray, device: str | None):
        """L2-normalised vectors: float16 on the GPU when there is one (no float32 copy in RAM), else numpy."""
        try:
            import torch
            if (device or ("cuda" if torch.cuda.is_available() else "cpu")) == "cuda":
                tensor = torch.from_numpy(np.ascontiguousarray(matrix, dtype=np.float16)).cuda()
                norms = tensor.float().norm(dim=1, keepdim=True).clamp_min(1e-12)
                return (tensor.float() / norms).half() if tensor.shape[0] < 50_000 else _normalize_in_place(tensor)
        except ImportError:
            pass
        matrix = matrix.astype(np.float32)
        matrix /= np.clip(np.linalg.norm(matrix, axis=1, keepdims=True), 1e-12, None)
        return matrix

    # --- scoring --------------------------------------------------------------------

    def dense_scores(self, query: str) -> np.ndarray:
        vector = np.asarray(self.embedder.embed_query(query), dtype=np.float32)
        vector /= max(np.linalg.norm(vector), 1e-12)
        if isinstance(self.matrix, np.ndarray):
            return self.matrix @ vector
        import torch
        query_tensor = torch.from_numpy(vector).half().to(self.matrix.device)
        return (self.matrix @ query_tensor).float().cpu().numpy()

    def bm25_scores(self, query: str, bm25_mode: str | None = None) -> np.ndarray:
        bm25_mode = bm25_mode or next(iter(self.bm25))
        index = self.bm25[bm25_mode]
        tokens = [t for t in analyze(query, bm25_mode) if t in index.vocab_dict]
        if not tokens:
            return np.zeros(len(self.chunks), dtype=np.float32)
        return index.get_scores(tokens)

    @staticmethod
    def _top(scores: np.ndarray, mask: np.ndarray, n: int) -> list[int]:
        candidates = np.flatnonzero(mask)
        if len(candidates) == 0:
            return []
        local = scores[candidates]
        n = min(n, len(candidates))
        best = np.argpartition(-local, n - 1)[:n]
        return [int(candidates[i]) for i in best[np.argsort(-local[best])]]

    # --- search ---------------------------------------------------------------------

    def search(self, query: str, query_sv: str | None = None, k: int = 5, mode: str = "hybrid",
               kommuner: list[str] | None | str = "auto", dense_lang: str = "en", candidates: int = 50,
               rerank: bool = False, bm25_mode: str | None = None) -> dict[str, list[Hit]]:
        """Top-k per pool. `kommuner="auto"` detects them in the query; None disables the filter."""
        if kommuner == "auto":
            # Union: a small place can share its name with a Wikidata locality elsewhere ("Veda" is in
            # Härnösand for Wikidata but the corpus mentions it in Vallentuna)
            kommuner = list(dict.fromkeys(detect_kommuner(query, query_sv or "") +
                                          self.places.detect(query, query_sv or "")))
        local_mask = ~self.is_law
        if kommuner:
            local_mask &= np.isin(self.kommun, kommuner)
        masks = {"law": self.is_law, "local": local_mask}

        rankings: list[np.ndarray] = []
        if mode in ("dense", "hybrid"):
            texts = {"en": [query], "sv": [query_sv or query], "both": [query, query_sv or query]}[dense_lang]
            rankings.extend(self.dense_scores(text) for text in texts)
        if mode in ("bm25", "hybrid"):
            rankings.append(self.bm25_scores(query_sv or query, bm25_mode))

        results: dict[str, list[Hit]] = {}
        for pool, mask in masks.items():
            fused: dict[int, float] = {}
            for scores in rankings:
                for rank, index in enumerate(self._top(scores, mask, candidates)):
                    fused[index] = fused.get(index, 0.0) + 1.0 / (RRF_K + rank + 1)
            order = sorted(fused, key=fused.get, reverse=True)
            if rerank and self.reranker is not None and order:
                # Cross-encoders compare languages poorly: score the Swedish query against Swedish text
                pairs = [(query_sv or query, chunk_text(self.chunks[i])[:2000]) for i in order]
                rerank_scores = self.reranker.predict(pairs, batch_size=16, show_progress_bar=False)
                order = [order[i] for i in np.argsort(-rerank_scores)]
                fused = {index: float(score) for index, score in zip(order, sorted(rerank_scores, reverse=True))}
            results[pool] = [Hit(self.chunks[i], fused[i], rank) for rank, i in enumerate(order[:k], start=1)]
        results["kommuner"] = kommuner or []
        return results
