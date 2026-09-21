"""Tests for text chunker and markdown splitting."""

import pytest
from vector_search_lab.chunker import MarkdownChunker
from vector_search_lab.models import Document


def test_chunk_size_and_overlap_validation():
    with pytest.raises(ValueError, match="chunk_overlap .* must be strictly less than chunk_size"):
        MarkdownChunker(chunk_size=100, chunk_overlap=100)

    with pytest.raises(ValueError, match="chunk_overlap .* must be strictly less than chunk_size"):
        MarkdownChunker(chunk_size=100, chunk_overlap=120)


def test_markdown_section_splitting():
    content = """# Title Doc

Introduction paragraph here.

## Section One

This is the content of section one. It provides basic details.

## Section Two

This is the content of section two. It explains advanced concepts.
"""
    doc = Document(id="test.md", title="Test Document", content=content, category="test")
    chunker = MarkdownChunker(chunk_size=200, chunk_overlap=40)
    chunks = chunker.chunk_document(doc)

    assert len(chunks) >= 2
    # Check heading breadcrumbs
    headings = [c.heading for c in chunks]
    assert any("Section One" in h for h in headings)
    assert any("Section Two" in h for h in headings)
    # Check preserved metadata
    for c in chunks:
        assert c.doc_id == "test.md"
        assert c.category == "test"
        assert c.chunk_id.startswith("test.md#chunk_")


def test_chunking_with_overlap():
    # Long text with repeated paragraphs
    content = """## Data Section

""" + "\n\n".join([f"Paragraph {i}: The quick brown fox jumps over the lazy dog." for i in range(15)])

    doc = Document(id="overlap.md", title="Overlap Test", content=content)
    chunker = MarkdownChunker(chunk_size=200, chunk_overlap=60, min_chunk_size=20)
    chunks = chunker.chunk_document(doc)

    assert len(chunks) > 1
    for i in range(len(chunks) - 1):
        c1 = chunks[i].content
        c2 = chunks[i + 1].content
        # Ensure there is content in each chunk
        assert len(c1) > 0
        assert len(c2) > 0


def test_short_document_produces_single_chunk():
    doc = Document(id="short.md", title="Short", content="Just a brief sentence.")
    chunker = MarkdownChunker(chunk_size=500, chunk_overlap=50)
    chunks = chunker.chunk_document(doc)

    assert len(chunks) == 1
    assert chunks[0].content == "Just a brief sentence."
    assert chunks[0].chunk_index == 0


def test_empty_document_produces_no_chunks():
    doc = Document(id="empty.md", title="Empty", content="   \n\n  ")
    chunker = MarkdownChunker()
    chunks = chunker.chunk_document(doc)
    assert len(chunks) == 0
