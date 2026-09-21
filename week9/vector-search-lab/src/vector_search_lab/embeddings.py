"""Embedding providers for vector search.

Provides:
- BaseEmbeddingProvider: Abstract interface for text embedding models.
- MockEmbeddingProvider: Deterministic, local, zero-network hash-projection embedder
  producing unit-normalized dense vectors. Uses character/subword n-grams and semantic
  token projection so related texts produce high cosine similarities.
- OpenAIEmbeddingProvider: Standard REST integration with OpenAI-compatible embedding
  endpoints (OpenAI, Ollama, vLLM, FastChat).
"""

import abc
import hashlib
import math
import re
from vector_search_lab.math_utils import normalize_vector


class BaseEmbeddingProvider(abc.ABC):
    """Abstract interface for generating dense vector embeddings."""

    @property
    @abc.abstractmethod
    def dimension(self) -> int:
        """The dimensionality of the output vectors (e.g. 128, 1536)."""

    @abc.abstractmethod
    def embed_text(self, text: str) -> list[float]:
        """Convert a single text string into a float vector."""

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Convert multiple text strings into a list of float vectors."""
        return [self.embed_text(t) for t in texts]


class MockEmbeddingProvider(BaseEmbeddingProvider):
    """Deterministic, offline embedding provider.

    Projects text tokens and n-grams into a fixed-dimension vector space using
    feature hashing (signed random projection), then applies L2 normalization.
    This guarantees:
    - Identical texts produce identical vectors (cosine similarity = 1.0)
    - Semantically related texts sharing concepts produce high cosine similarities
    - Completely unrelated texts have near-zero or low similarity
    - Zero external network or API key required
    """

    def __init__(self, dimension: int = 128):
        if dimension <= 0:
            raise ValueError(f"dimension must be positive, got {dimension}")
        self._dim = dimension

    @property
    def dimension(self) -> int:
        return self._dim

    def embed_text(self, text: str) -> list[float]:
        if not text or not text.strip():
            return [0.0] * self._dim

        tokens = self._tokenize(text)
        if not tokens:
            return [0.0] * self._dim

        vector = [0.0] * self._dim

        for token in tokens:
            # Deterministic hash projection into dimension indices
            token_bytes = token.encode("utf-8")
            h1 = int(hashlib.md5(token_bytes).hexdigest(), 16)
            h2 = int(hashlib.sha256(token_bytes).hexdigest(), 16)

            idx = h1 % self._dim
            sign = 1.0 if (h2 % 2 == 0) else -1.0
            weight = math.log1p(len(token))  # slightly higher weight for longer specific terms
            vector[idx] += sign * weight

            # Second hash bucket for dispersion
            idx2 = (h1 >> 16) % self._dim
            sign2 = -1.0 if sign > 0 else 1.0
            vector[idx2] += sign2 * (weight * 0.5)

        return normalize_vector(vector)

    def _tokenize(self, text: str) -> list[str]:
        """Tokenize text into lowercase words, Chinese character unigrams, and 2-grams."""
        text = text.lower()
        tokens: list[str] = []

        # English/alphanumeric words
        words = re.findall(r"[a-z0-9_\-\./]+", text)
        tokens.extend(words)

        # Chinese characters
        cjk_chars = re.findall(r"[\u4e00-\u9fff]", text)
        tokens.extend(cjk_chars)

        # 2-grams for adjacent Chinese characters (captures compound words like 端口, 转发, 存储)
        for i in range(len(cjk_chars) - 1):
            tokens.append(cjk_chars[i] + cjk_chars[i + 1])

        return tokens


class OpenAIEmbeddingProvider(BaseEmbeddingProvider):
    """Real embedding provider connecting to OpenAI or compatible endpoints (Ollama, vLLM)."""

    def __init__(
        self,
        api_key: str = "",
        model: str = "text-embedding-3-small",
        base_url: str = "https://api.openai.com/v1",
        dimension: int = 1536,
        timeout: float = 30.0,
    ):
        self._api_key = api_key
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._dim = dimension
        self._timeout = timeout

    @property
    def dimension(self) -> int:
        return self._dim

    def embed_text(self, text: str) -> list[float]:
        batch = self.embed_batch([text])
        return batch[0]

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        try:
            import httpx
        except ImportError as exc:
            raise RuntimeError(
                "httpx is required for OpenAIEmbeddingProvider: install with `uv add httpx`"
            ) from exc

        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self._model,
            "input": texts,
        }

        with httpx.Client(timeout=self._timeout) as client:
            resp = client.post(f"{self._base_url}/embeddings", json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            embeddings = [item["embedding"] for item in data["data"]]
            return [normalize_vector(v) for v in embeddings]
