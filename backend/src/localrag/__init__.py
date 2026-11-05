"""
Local retrieval over the offline corpus (corpus/): dense embeddings computed on the local
GPU, Swedish BM25, hybrid fusion, optional cross-encoder reranking and kommun filtering.

    python -m localrag.index --model st-bge-m3     # embed chunks.jsonl + build BM25
    python -m localrag.search "height limit in Veda"
    python -m localrag.eval                         # compare retrieval setups
"""
