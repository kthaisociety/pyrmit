"""
Embedding provider shared by ingestion, query-time retrieval and the benchmark.

Configured through env vars; the defaults reproduce the original setup
(direct OpenAI, text-embedding-3-large, 3072 dims):

  EMBEDDING_PROVIDER         openai (default) | openrouter | local | st
                               openai     -> api.openai.com, OPENAI_API_KEY
                               openrouter -> openrouter.ai, OPENROUTER_API_KEY (model ids like "qwen/qwen3-embedding-8b")
                               local      -> any OpenAI-compatible server at EMBEDDING_BASE_URL
                                             (Ollama, HF text-embeddings-inference, vLLM, LM Studio)
                               st         -> sentence-transformers loaded in-process from Hugging Face
  EMBEDDING_MODEL            text-embedding-3-large
  EMBEDDING_DIM              3072, must match the vector column (see chunking/reembed.py)
  EMBEDDING_BASE_URL         override the provider's base URL
  EMBEDDING_API_KEY          override the provider's API key
  EMBEDDING_QUERY_PREFIX     text prepended to queries   (e.g. "query: " for E5 models)
  EMBEDDING_DOCUMENT_PREFIX  text prepended to documents (e.g. "passage: " for E5 models)
  EMBEDDING_BATCH_SIZE       100
  EMBEDDING_RUNTIME          auto (default) | torch | onnx -- how "st" models run:
                               auto  -> torch (fp16) on a CUDA GPU; otherwise the model's ONNX int8
                                        export (`onnx_file`, e.g. localrag/models.toml) on the CPU,
                                        else torch on the CPU
                               onnx  -> ONNX export on the CPU (onnxruntime), even with a GPU
                               torch -> sentence-transformers (GPU when available)
                             arctic-embed-l-v2 int8 on CPU: 34 ms/query, 0.9 GB RAM, same recall
                             as the GPU model on the eval (torch fp32 on CPU: 141 ms, 3.4 GB)
"""

import logging
import os
import threading
from dataclasses import dataclass, field
from typing import Any

from openai import OpenAI

logger = logging.getLogger(__name__)

OPENAI_BASE_URL = "https://api.openai.com/v1"
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

_PROVIDERS = {"openai", "openrouter", "local", "st"}
_DEFAULT_API_KEY_ENV = {"openai": "OPENAI_API_KEY", "openrouter": "OPENROUTER_API_KEY", "local": None, "st": None}


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


@dataclass(frozen=True)
class EmbeddingConfig:
    provider: str = "openai"
    model: str = "text-embedding-3-large"
    dim: int | None = 3072
    base_url: str | None = None
    api_key: str | None = field(default=None, repr=False)
    query_prefix: str = ""
    document_prefix: str = ""
    batch_size: int = 100
    # Extra kwargs for SentenceTransformer(...), e.g. {"model_kwargs": {"torch_dtype": "float16"}}
    st_kwargs: dict[str, Any] = field(default_factory=dict, hash=False, compare=False)
    # ONNX export inside the model's Hugging Face repo (e.g. "onnx/model_int8.onnx"), used on CPU
    onnx_file: str | None = None
    pooling: str = "cls"  # of the ONNX export: "cls" or "mean" (sentence-transformers reads its own config)

    def __post_init__(self):
        if self.provider not in _PROVIDERS:
            raise ValueError(f"Unknown EMBEDDING_PROVIDER {self.provider!r}, expected one of {sorted(_PROVIDERS)}")
        if self.provider == "local" and not self.base_url:
            raise ValueError("EMBEDDING_BASE_URL is required for EMBEDDING_PROVIDER=local")

    @classmethod
    def from_env(cls) -> "EmbeddingConfig":
        dim = _env("EMBEDDING_DIM", "3072")
        return cls(
            provider=_env("EMBEDDING_PROVIDER", "openai").lower(),
            model=_env("EMBEDDING_MODEL", "text-embedding-3-large"),
            dim=int(dim) if dim else None,
            base_url=_env("EMBEDDING_BASE_URL") or None,
            api_key=_env("EMBEDDING_API_KEY") or None,
            # Prefixes are not stripped: trailing spaces are significant ("query: ")
            query_prefix=os.getenv("EMBEDDING_QUERY_PREFIX", ""),
            document_prefix=os.getenv("EMBEDDING_DOCUMENT_PREFIX", ""),
            batch_size=int(_env("EMBEDDING_BATCH_SIZE", "100")),
        )

    @property
    def label(self) -> str:
        return f"{self.provider}:{self.model}"


class Embedder:
    def __init__(self, config: EmbeddingConfig):
        self.config = config
        self._client: OpenAI | None = None
        self._st_model = None
        self._lock = threading.Lock()

    def embed_query(self, text: str) -> list[float]:
        return self._embed([self.config.query_prefix + text])[0]

    def embed_documents(self, texts: list[str], progress=None) -> list[list[float]]:
        """Embed in batches. `progress(done, total)` is called after each batch."""
        prefixed = [self.config.document_prefix + text for text in texts]
        vectors: list[list[float]] = []
        for start in range(0, len(prefixed), self.config.batch_size):
            vectors.extend(self._embed(prefixed[start:start + self.config.batch_size]))
            if progress is not None:
                progress(len(vectors), len(prefixed))
        return vectors

    def _embed(self, texts: list[str]) -> list[list[float]]:
        if self.config.provider == "st":
            vectors = self._embed_sentence_transformers(texts)
        else:
            vectors = self._embed_openai_compatible(texts)
        if self.config.dim is not None and vectors and len(vectors[0]) != self.config.dim:
            raise ValueError(
                f"{self.config.label} returned {len(vectors[0])}-dim vectors but EMBEDDING_DIM={self.config.dim}"
            )
        return vectors

    def _embed_openai_compatible(self, texts: list[str]) -> list[list[float]]:
        model = self.config.model
        if self.config.provider == "openai":
            model = model.removeprefix("openai/")
        response = self._get_client().embeddings.create(model=model, input=texts)
        data = sorted(response.data, key=lambda item: item.index)
        if len(data) != len(texts):
            raise RuntimeError(f"{self.config.label} returned {len(data)} embeddings for {len(texts)} inputs")
        return [item.embedding for item in data]

    def _get_client(self) -> OpenAI:
        with self._lock:
            if self._client is None:
                provider = self.config.provider
                base_url = self.config.base_url or {
                    "openai": OPENAI_BASE_URL,
                    "openrouter": OPENROUTER_BASE_URL,
                }.get(provider)
                key_env = _DEFAULT_API_KEY_ENV[provider]
                api_key = self.config.api_key or (_env(key_env) if key_env else "")
                if provider == "openrouter":
                    api_key = api_key or _env("OPENROUTER_KEY")
                api_key = api_key or "not-needed"
                if key_env and api_key == "not-needed":
                    raise RuntimeError(f"{key_env} is required for EMBEDDING_PROVIDER={provider}")
                self._client = OpenAI(api_key=api_key, base_url=base_url, max_retries=5)
            return self._client

    def _embed_sentence_transformers(self, texts: list[str]) -> list[list[float]]:
        with self._lock:
            if self._st_model is None:
                runtime = _resolve_runtime(self.config)
                logger.info("Embedding model %s: %s", self.config.model,
                            f"ONNX {self.config.onnx_file} on the CPU" if runtime == "onnx" else "torch")
                if runtime == "onnx":
                    self._st_model = _OnnxEncoder(self.config.model, self.config.onnx_file, self.config.pooling)
            if isinstance(self._st_model, _OnnxEncoder):
                return self._st_model.encode(texts, batch_size=min(self.config.batch_size, 32))
            if self._st_model is None:
                try:
                    from sentence_transformers import SentenceTransformer
                except ImportError as exc:
                    raise RuntimeError(
                        "EMBEDDING_PROVIDER=st needs sentence-transformers: uv pip install -e \".[local]\""
                    ) from exc
                self._st_model = SentenceTransformer(self.config.model, **self.config.st_kwargs)
                # Chunks are ~1500 chars; an 8k-32k window only costs memory
                if (self._st_model.max_seq_length or 0) > 1024:
                    self._st_model.max_seq_length = 1024
                if self._st_model.device.type == "cuda":
                    self._st_model.half()
            vectors = self._st_model.encode(
                texts,
                batch_size=min(self.config.batch_size, 32),
                normalize_embeddings=True,
                convert_to_numpy=True,
            )
        return vectors.tolist()


def _cuda_available() -> bool:
    try:
        import torch
    except ImportError:
        return False
    return torch.cuda.is_available()


def _resolve_runtime(config: EmbeddingConfig) -> str:
    """EMBEDDING_RUNTIME for an "st" model: torch on a GPU, else the ONNX export when there is one."""
    runtime = _env("EMBEDDING_RUNTIME", "auto").lower()
    if runtime not in {"auto", "torch", "onnx"}:
        raise ValueError(f"Unknown EMBEDDING_RUNTIME {runtime!r}, expected auto, torch or onnx")
    if runtime == "onnx" and not config.onnx_file:
        raise ValueError(f"EMBEDDING_RUNTIME=onnx but {config.model} has no onnx_file configured")
    if runtime != "auto":
        return runtime
    if _cuda_available():
        return "torch"
    return "onnx" if config.onnx_file else "torch"


class _OnnxEncoder:
    """CPU inference of an ONNX export from the model's Hugging Face repo (onnxruntime + tokenizers, no torch)."""

    MAX_LENGTH = 1024  # same window as the torch path

    def __init__(self, repo: str, onnx_file: str, pooling: str):
        try:
            import onnxruntime
            from huggingface_hub import snapshot_download
            from tokenizers import Tokenizer
        except ImportError as exc:
            raise RuntimeError("The ONNX runtime needs onnxruntime: uv pip install -e \".[local]\"") from exc
        # fp32 exports keep their weights in a "<file>_data" side file; int8 ones are a single file
        folder = snapshot_download(repo, allow_patterns=[onnx_file, f"{onnx_file}_data", "tokenizer.json"])
        options = onnxruntime.SessionOptions()
        options.graph_optimization_level = onnxruntime.GraphOptimizationLevel.ORT_ENABLE_ALL
        self.session = onnxruntime.InferenceSession(f"{folder}/{onnx_file}", options,
                                                    providers=["CPUExecutionProvider"])
        self.inputs = {item.name for item in self.session.get_inputs()}
        self.tokenizer = Tokenizer.from_file(f"{folder}/tokenizer.json")
        self.tokenizer.enable_truncation(self.MAX_LENGTH)
        pad_id = self.tokenizer.token_to_id("<pad>")
        self.tokenizer.enable_padding(pad_id=pad_id if pad_id is not None else 0)
        self.pooling = pooling

    def encode(self, texts: list[str], batch_size: int) -> list[list[float]]:
        import numpy as np

        vectors = []
        for start in range(0, len(texts), batch_size):
            encodings = self.tokenizer.encode_batch(texts[start:start + batch_size])
            ids = np.array([e.ids for e in encodings], dtype=np.int64)
            mask = np.array([e.attention_mask for e in encodings], dtype=np.int64)
            feed = {"input_ids": ids, "attention_mask": mask, "token_type_ids": np.zeros_like(ids)}
            hidden = self.session.run(None, {name: value for name, value in feed.items() if name in self.inputs})[0]
            if self.pooling == "mean":
                pooled = (hidden * mask[..., None]).sum(1) / mask.sum(1, keepdims=True)
            else:
                pooled = hidden[:, 0]
            vectors.append(pooled / np.clip(np.linalg.norm(pooled, axis=1, keepdims=True), 1e-12, None))
        return np.vstack(vectors).astype(np.float32).tolist()


_default_embedder: Embedder | None = None
_default_lock = threading.Lock()


def get_embedder() -> Embedder:
    """Process-wide embedder configured from the environment."""
    global _default_embedder
    with _default_lock:
        if _default_embedder is None:
            _default_embedder = Embedder(EmbeddingConfig.from_env())
        return _default_embedder


def embedding_dim() -> int:
    return EmbeddingConfig.from_env().dim or 3072
