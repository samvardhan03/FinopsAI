"""
Advanced embedding modules for FinOps AI RAG pipelines.

Provides TurboQuant-based 3-bit KV cache compression for drastically
reducing multi-cloud vector compute costs while preserving inner-product
accuracy.
"""

from finops_ai.ml.embeddings.turbo_quant import (
    TurboQuantEmbeddings,
    TurboQuantKVCache,
)

__all__ = ["TurboQuantKVCache", "TurboQuantEmbeddings"]
