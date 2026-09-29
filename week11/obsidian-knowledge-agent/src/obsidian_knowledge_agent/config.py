"""Environment configuration. Never log connection strings or keys."""

import os

from vector_search_lab.embeddings import BaseEmbeddingProvider, MockEmbeddingProvider, OpenAIEmbeddingProvider


def provider_from_env() -> tuple[BaseEmbeddingProvider, str]:
    name = os.getenv("W11_PROVIDER", "mock")
    dimension = int(os.getenv("W11_DIMENSION", "128" if name == "mock" else "1536"))
    if not 1 <= dimension <= 16000:
        raise ValueError("W11_DIMENSION must be between 1 and 16000")
    if name == "mock":
        return MockEmbeddingProvider(dimension), f"mock:{dimension}:week9-v1"
    if name == "openai":
        model = os.getenv("W11_MODEL", "text-embedding-3-small")
        endpoint = os.getenv("W11_BASE_URL", "https://api.openai.com/v1")
        # The endpoint contributes to identity without storing a potentially private URL.
        import hashlib
        identity = hashlib.sha256(endpoint.encode()).hexdigest()
        return OpenAIEmbeddingProvider(api_key=os.getenv("W11_API_KEY", ""), model=model,
                                       base_url=endpoint, dimension=dimension), f"openai:{model}:{dimension}:{identity}"
    raise ValueError("W11_PROVIDER must be mock or openai")
