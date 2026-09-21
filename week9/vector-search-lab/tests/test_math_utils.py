"""Tests for vector math utilities and similarity metrics."""

import math
import pytest
from vector_search_lab.math_utils import (
    cosine_similarity,
    cosine_distance,
    euclidean_distance,
    dot_product,
    normalize_vector,
    vector_norm,
)


def test_identical_vectors_have_cosine_similarity_one():
    v1 = [1.0, 2.0, 3.0]
    v2 = [1.0, 2.0, 3.0]
    sim = cosine_similarity(v1, v2)
    assert math.isclose(sim, 1.0, abs_tol=1e-6)
    assert math.isclose(cosine_distance(v1, v2), 0.0, abs_tol=1e-6)


def test_proportional_vectors_have_cosine_similarity_one():
    v1 = [1.0, 2.0, 3.0]
    v2 = [2.0, 4.0, 6.0]  # scaled by 2, same direction
    sim = cosine_similarity(v1, v2)
    assert math.isclose(sim, 1.0, abs_tol=1e-6)


def test_orthogonal_vectors_have_cosine_similarity_zero():
    v1 = [1.0, 0.0, 0.0]
    v2 = [0.0, 1.0, 0.0]
    sim = cosine_similarity(v1, v2)
    assert math.isclose(sim, 0.0, abs_tol=1e-6)
    assert math.isclose(cosine_distance(v1, v2), 1.0, abs_tol=1e-6)


def test_opposite_vectors_have_cosine_similarity_minus_one():
    v1 = [1.0, 2.0, 3.0]
    v2 = [-1.0, -2.0, -3.0]
    sim = cosine_similarity(v1, v2)
    assert math.isclose(sim, -1.0, abs_tol=1e-6)
    assert math.isclose(cosine_distance(v1, v2), 2.0, abs_tol=1e-6)


def test_zero_vector_similarity_is_zero():
    v1 = [0.0, 0.0, 0.0]
    v2 = [1.0, 2.0, 3.0]
    assert cosine_similarity(v1, v2) == 0.0
    assert cosine_similarity(v1, v1) == 0.0


def test_dimension_mismatch_raises_value_error():
    with pytest.raises(ValueError, match="Vector dimension mismatch"):
        cosine_similarity([1.0, 2.0], [1.0, 2.0, 3.0])

    with pytest.raises(ValueError, match="Vector dimension mismatch"):
        euclidean_distance([1.0], [1.0, 2.0])

    with pytest.raises(ValueError, match="Vector dimension mismatch"):
        dot_product([1.0], [1.0, 2.0])


def test_vector_normalization():
    v = [3.0, 4.0]
    norm_v = normalize_vector(v)
    assert math.isclose(norm_v[0], 0.6, abs_tol=1e-6)
    assert math.isclose(norm_v[1], 0.8, abs_tol=1e-6)
    assert math.isclose(vector_norm(norm_v), 1.0, abs_tol=1e-6)


def test_zero_vector_normalization():
    v = [0.0, 0.0, 0.0]
    assert normalize_vector(v) == [0.0, 0.0, 0.0]


def test_euclidean_distance():
    v1 = [0.0, 0.0]
    v2 = [3.0, 4.0]
    assert math.isclose(euclidean_distance(v1, v2), 5.0, abs_tol=1e-6)


def test_normalized_vector_dot_product_equals_cosine_similarity():
    u = [1.5, -2.3, 4.1]
    v = [-0.5, 3.2, 1.8]
    u_norm = normalize_vector(u)
    v_norm = normalize_vector(v)
    dp = dot_product(u_norm, v_norm)
    sim = cosine_similarity(u, v)
    assert math.isclose(dp, sim, abs_tol=1e-6)
