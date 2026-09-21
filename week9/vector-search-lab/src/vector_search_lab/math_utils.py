"""Vector mathematics and similarity metrics.

Provides pure-Python implementations of:
- Cosine similarity: cos(theta) = (u . v) / (||u|| * ||v||)
- Cosine distance: 1.0 - cosine_similarity (used by pgvector's <=> operator)
- Euclidean distance: sqrt(sum((u_i - v_i)^2)) (used by pgvector's <-> operator)
- Dot product / Inner product: sum(u_i * v_i) (used by pgvector's <#> operator)
- L2 vector normalization: v / ||v||
"""

import math


def dot_product(u: list[float], v: list[float]) -> float:
    """Calculate the inner product of two vectors."""
    if len(u) != len(v):
        raise ValueError(f"Vector dimension mismatch: len(u)={len(u)} != len(v)={len(v)}")
    return sum(x * y for x, y in zip(u, v))


def vector_norm(v: list[float]) -> float:
    """Calculate the Euclidean norm (L2 length) of a vector."""
    return math.sqrt(sum(x * x for x in v))


def normalize_vector(v: list[float]) -> list[float]:
    """Normalize a vector to unit length (L2 norm = 1.0).

    Unit-normalized vectors have the property that:
    - dot_product(u_norm, v_norm) == cosine_similarity(u, v)
    - Euclidean distance^2 == 2 - 2 * cosine_similarity
    """
    norm = vector_norm(v)
    if norm == 0.0 or math.isclose(norm, 0.0, abs_tol=1e-12):
        return [0.0] * len(v)
    return [x / norm for x in v]


def cosine_similarity(u: list[float], v: list[float]) -> float:
    """Compute cosine similarity between two vectors.

    cos(theta) = (u . v) / (||u|| * ||v||)

    Range: [-1.0, 1.0]
    - 1.0: perfectly aligned (same direction)
    - 0.0: orthogonal (completely independent/uncorrelated)
    - -1.0: directly opposite
    """
    if len(u) != len(v):
        raise ValueError(f"Vector dimension mismatch: len(u)={len(u)} != len(v)={len(v)}")

    norm_u = vector_norm(u)
    norm_v = vector_norm(v)

    if math.isclose(norm_u, 0.0, abs_tol=1e-12) or math.isclose(norm_v, 0.0, abs_tol=1e-12):
        return 0.0

    sim = dot_product(u, v) / (norm_u * norm_v)
    # Clamp to [-1.0, 1.0] to guard against floating-point inaccuracies
    return max(-1.0, min(1.0, sim))


def cosine_distance(u: list[float], v: list[float]) -> float:
    """Compute cosine distance between two vectors.

    distance = 1.0 - cosine_similarity(u, v)

    Used by PostgreSQL pgvector with the `<=>` operator.
    Range: [0.0, 2.0]
    - 0.0: identical direction
    - 1.0: orthogonal
    - 2.0: opposite direction
    """
    return 1.0 - cosine_similarity(u, v)


def euclidean_distance(u: list[float], v: list[float]) -> float:
    """Compute Euclidean (L2) distance between two vectors.

    d(u, v) = sqrt(sum((u_i - v_i)^2))

    Used by PostgreSQL pgvector with the `<->` operator.
    """
    if len(u) != len(v):
        raise ValueError(f"Vector dimension mismatch: len(u)={len(u)} != len(v)={len(v)}")
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(u, v)))
