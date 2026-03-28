"""
Tests for TurboQuant Embeddings — 3-bit PolarQuant + QJL compression.

Validates that the asymmetric compression scheme preserves inner-product
accuracy: document vectors are compressed, query vectors remain FP32,
and the asymmetric dot product closely approximates the true dot product.
"""

from __future__ import annotations

from typing import List
from unittest.mock import MagicMock

import numpy as np
import pytest

from finops_ai.ml.embeddings.turbo_quant import TurboQuantEmbeddings, TurboQuantKVCache


# ── Fixtures ────────────────────────────────────────────────────────────


@pytest.fixture
def dim() -> int:
    """Standard embedding dimensionality for tests (must be even)."""
    return 128


@pytest.fixture
def cache(dim: int) -> TurboQuantKVCache:
    """Pre-initialised TurboQuantKVCache with fixed seed."""
    return TurboQuantKVCache(dim=dim, seed=42)


@pytest.fixture
def random_vectors(dim: int) -> np.ndarray:
    """Batch of random unit-normalised vectors."""
    rng = np.random.default_rng(123)
    vecs = rng.standard_normal((50, dim)).astype(np.float64)
    norms = np.linalg.norm(vecs, axis=1, keepdims=True)
    return (vecs / norms).astype(np.float32)


class FakeBaseEmbeddings:
    """Mock base embeddings that return deterministic vectors."""

    def __init__(self, dim: int, seed: int = 99) -> None:
        self._dim = dim
        self._rng = np.random.default_rng(seed)

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        vecs = self._rng.standard_normal((len(texts), self._dim)).astype(np.float64)
        norms = np.linalg.norm(vecs, axis=1, keepdims=True)
        return (vecs / norms).astype(np.float32).tolist()

    def embed_query(self, text: str) -> List[float]:
        vec = self._rng.standard_normal(self._dim).astype(np.float64)
        vec = vec / np.linalg.norm(vec)
        return vec.astype(np.float32).tolist()


# ── TurboQuantKVCache Tests ─────────────────────────────────────────────


class TestTurboQuantKVCache:
    """Unit tests for the core compression engine."""

    def test_output_shape_batch(self, cache: TurboQuantKVCache, random_vectors: np.ndarray) -> None:
        """Compressed output must have the same shape as input."""
        compressed = cache.compress(random_vectors)
        assert compressed.shape == random_vectors.shape

    def test_output_shape_single(self, cache: TurboQuantKVCache, dim: int) -> None:
        """Single vector (1-D input) should produce 1-D output."""
        vec = np.random.default_rng(0).standard_normal(dim).astype(np.float32)
        compressed = cache.compress(vec)
        assert compressed.shape == (dim,)

    def test_output_dtype(self, cache: TurboQuantKVCache, random_vectors: np.ndarray) -> None:
        """Output should be float32."""
        compressed = cache.compress(random_vectors)
        assert compressed.dtype == np.float32

    def test_cosine_similarity_preservation(
        self, cache: TurboQuantKVCache, dim: int
    ) -> None:
        """
        Asymmetric dot product between compressed docs and FP32 queries
        should closely approximate the true dot product.

        Threshold: cosine similarity > 0.95 for each pair.
        """
        rng = np.random.default_rng(777)
        n_docs = 30
        n_queries = 10

        # Generate normalised document and query vectors
        docs = rng.standard_normal((n_docs, dim)).astype(np.float64)
        docs /= np.linalg.norm(docs, axis=1, keepdims=True)

        queries = rng.standard_normal((n_queries, dim)).astype(np.float64)
        queries /= np.linalg.norm(queries, axis=1, keepdims=True)

        # Compress documents
        compressed_docs = cache.compress(docs.astype(np.float32)).astype(np.float64)

        # Compute dot products
        true_dots = docs @ queries.T          # (n_docs, n_queries)
        approx_dots = compressed_docs @ queries.T  # (n_docs, n_queries)

        # Flatten for easier comparison
        true_flat = true_dots.flatten()
        approx_flat = approx_dots.flatten()

        # Compute cosine similarity between the two dot-product vectors
        cos_sim = np.dot(true_flat, approx_flat) / (
            np.linalg.norm(true_flat) * np.linalg.norm(approx_flat) + 1e-10
        )

        assert cos_sim > 0.95, (
            f"Cosine similarity between true and approximate dot products "
            f"is {cos_sim:.4f}, expected > 0.95"
        )

    def test_per_vector_cosine_similarity(
        self, cache: TurboQuantKVCache, dim: int
    ) -> None:
        """
        Each individual compressed vector should have high cosine
        similarity with its original.
        """
        rng = np.random.default_rng(456)
        n = 20
        vecs = rng.standard_normal((n, dim)).astype(np.float64)
        vecs /= np.linalg.norm(vecs, axis=1, keepdims=True)

        compressed = cache.compress(vecs.astype(np.float32)).astype(np.float64)

        for i in range(n):
            cos = np.dot(vecs[i], compressed[i]) / (
                np.linalg.norm(vecs[i]) * np.linalg.norm(compressed[i]) + 1e-10
            )
            assert cos > 0.90, (
                f"Vector {i}: cosine similarity {cos:.4f} is below 0.90"
            )

    def test_seed_reproducibility(self, dim: int) -> None:
        """Same seed should yield identical compression results."""
        cache_a = TurboQuantKVCache(dim=dim, seed=42)
        cache_b = TurboQuantKVCache(dim=dim, seed=42)

        vec = np.random.default_rng(0).standard_normal((5, dim)).astype(np.float32)

        result_a = cache_a.compress(vec)
        result_b = cache_b.compress(vec)

        np.testing.assert_array_equal(result_a, result_b)

    def test_different_seeds_differ(self, dim: int) -> None:
        """Different seeds should produce different results."""
        cache_a = TurboQuantKVCache(dim=dim, seed=42)
        cache_b = TurboQuantKVCache(dim=dim, seed=99)

        vec = np.random.default_rng(0).standard_normal((5, dim)).astype(np.float32)

        result_a = cache_a.compress(vec)
        result_b = cache_b.compress(vec)

        assert not np.allclose(result_a, result_b)

    def test_invalid_dim_odd(self) -> None:
        """Odd dimensionality should raise ValueError."""
        with pytest.raises(ValueError, match="positive even integer"):
            TurboQuantKVCache(dim=127)

    def test_invalid_dim_zero(self) -> None:
        """Zero dimensionality should raise ValueError."""
        with pytest.raises(ValueError, match="positive even integer"):
            TurboQuantKVCache(dim=0)

    def test_dimension_mismatch(self, cache: TurboQuantKVCache) -> None:
        """Input with wrong dimension should raise ValueError."""
        wrong = np.zeros((3, cache.dim + 2), dtype=np.float32)
        with pytest.raises(ValueError, match="Expected last dim"):
            cache.compress(wrong)


# ── TurboQuantEmbeddings Tests ──────────────────────────────────────────


class TestTurboQuantEmbeddings:
    """Integration tests for the LangChain-compatible wrapper."""

    def test_embed_documents_shape(self, dim: int) -> None:
        """Compressed document embeddings should have correct shape."""
        base = FakeBaseEmbeddings(dim=dim)
        tq = TurboQuantEmbeddings(base, dim=dim, seed=42)

        texts = ["doc one", "doc two", "doc three"]
        result = tq.embed_documents(texts)

        assert len(result) == 3
        assert all(len(v) == dim for v in result)

    def test_embed_query_passthrough(self, dim: int) -> None:
        """Query embedding should be identical to base embeddings output."""
        base = FakeBaseEmbeddings(dim=dim, seed=50)
        tq = TurboQuantEmbeddings(base, dim=dim, seed=42)

        # Reset seed for reproducible comparison
        base_copy = FakeBaseEmbeddings(dim=dim, seed=50)

        query_result = tq.embed_query("test query")
        base_result = base_copy.embed_query("test query")

        np.testing.assert_array_almost_equal(query_result, base_result, decimal=6)

    def test_asymmetric_dot_product_accuracy(self, dim: int) -> None:
        """
        The core guarantee: asymmetric dot product of compressed docs
        with uncompressed queries preserves the true inner product.
        """
        base = FakeBaseEmbeddings(dim=dim, seed=200)
        tq = TurboQuantEmbeddings(base, dim=dim, seed=42)

        # Get base embeddings for ground truth
        base_ground = FakeBaseEmbeddings(dim=dim, seed=200)
        texts = [f"document {i}" for i in range(20)]

        true_docs = np.array(base_ground.embed_documents(texts))

        # Get compressed embeddings
        compressed_docs = np.array(tq.embed_documents(texts))

        # Get a query
        base_q = FakeBaseEmbeddings(dim=dim, seed=200)
        # Advance the RNG state past the document embeddings
        _ = base_q.embed_documents(texts)
        query = np.array(base_q.embed_query("test query"))

        # True dot products
        true_dots = true_docs @ query
        # Asymmetric dot products (compressed docs, FP32 query)
        approx_dots = compressed_docs @ query

        # Cosine similarity of the dot product vectors
        cos_sim = np.dot(true_dots, approx_dots) / (
            np.linalg.norm(true_dots) * np.linalg.norm(approx_dots) + 1e-10
        )

        assert cos_sim > 0.95, (
            f"Asymmetric dot product cosine similarity: {cos_sim:.4f}, expected > 0.95"
        )

    def test_embed_documents_calls_base(self, dim: int) -> None:
        """Verify that embed_documents delegates to base.embed_documents."""
        mock_base = MagicMock()
        mock_base.embed_documents.return_value = np.random.default_rng(0).standard_normal(
            (2, dim)
        ).tolist()

        tq = TurboQuantEmbeddings(mock_base, dim=dim, seed=42)
        tq.embed_documents(["a", "b"])

        mock_base.embed_documents.assert_called_once_with(["a", "b"])

    def test_embed_query_calls_base(self, dim: int) -> None:
        """Verify that embed_query delegates to base.embed_query."""
        mock_base = MagicMock()
        mock_base.embed_query.return_value = [0.1] * dim

        tq = TurboQuantEmbeddings(mock_base, dim=dim, seed=42)
        result = tq.embed_query("hello")

        mock_base.embed_query.assert_called_once_with("hello")
        assert result == [0.1] * dim
