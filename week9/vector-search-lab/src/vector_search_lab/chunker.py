"""Markdown-aware and sliding-window text chunker.

Why chunking matters in RAG:
1. Context Window Limits: Embedding models (e.g., text-embedding-3-small: 8192 tokens)
   and LLMs have finite input limits.
2. Embedding Specificity: Large text blocks compress too many disparate ideas into one
   vector, diluting semantic sharpness ("needle in a haystack"). Smaller chunks represent
   a focused, coherent thought.
3. Retrieval Precision: Returning 3 targeted 300-char chunks yields precise answers with
   minimal token cost compared to feeding entire multi-page manuals.
4. Overlap Rationale: Sliding window overlap (e.g. 10-20%) prevents key phrases, code snippets,
   or conditional clauses from being severed across chunk boundaries.
"""

import re
from typing import Any
from vector_search_lab.models import Document, Chunk


class MarkdownChunker:
    """Chunks Markdown documents while respecting heading hierarchy and paragraph boundaries."""

    def __init__(
        self,
        chunk_size: int = 350,
        chunk_overlap: int = 70,
        min_chunk_size: int = 40,
    ):
        """Initialize chunker.

        Args:
            chunk_size: Target maximum character length for each chunk (soft bound for
                paragraph preservation, hard bounded via sliding-window fallback).
            chunk_overlap: Target number of characters to overlap between adjacent chunks.
            min_chunk_size: Discard or merge chunks smaller than this threshold.
        """
        if chunk_overlap >= chunk_size:
            raise ValueError(
                f"chunk_overlap ({chunk_overlap}) must be strictly less than chunk_size ({chunk_size})"
            )
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.min_chunk_size = min_chunk_size

    def chunk_document(self, doc: Document) -> list[Chunk]:
        """Split a Document into multiple Chunks with heading breadcrumbs and metadata."""
        sections = self._split_markdown_sections(doc.content, doc.title)
        chunks: list[Chunk] = []
        chunk_idx = 0

        for heading, body in sections:
            body = body.strip()
            if not body:
                continue

            text_chunks = self._chunk_section_text(body)
            for text in text_chunks:
                if len(text.strip()) < self.min_chunk_size:
                    continue

                chunk_id = f"{doc.id}#chunk_{chunk_idx:03d}"
                chunks.append(
                    Chunk(
                        chunk_id=chunk_id,
                        doc_id=doc.id,
                        chunk_index=chunk_idx,
                        title=doc.title,
                        heading=heading,
                        content=text.strip(),
                        category=doc.category,
                        source_file=doc.source_file,
                        metadata=dict(doc.metadata),
                    )
                )
                chunk_idx += 1

        # Fallback: if document had no sections or text was too short, create one chunk
        if not chunks and doc.content.strip():
            chunks.append(
                Chunk(
                    chunk_id=f"{doc.id}#chunk_000",
                    doc_id=doc.id,
                    chunk_index=0,
                    title=doc.title,
                    heading=doc.title,
                    content=doc.content.strip(),
                    category=doc.category,
                    source_file=doc.source_file,
                    metadata=dict(doc.metadata),
                )
            )

        return chunks

    def _split_markdown_sections(self, content: str, default_title: str) -> list[tuple[str, str]]:
        """Split markdown content by `#`, `##`, `###` headings into (heading, body) pairs."""
        heading_pattern = re.compile(r"^(#{1,4})\s+(.+)$", re.MULTILINE)
        matches = list(heading_pattern.finditer(content))

        if not matches:
            return [(default_title, content)]

        sections: list[tuple[str, str]] = []

        # If there is introductory text before the first heading
        if matches[0].start() > 0:
            preamble = content[: matches[0].start()].strip()
            if preamble:
                sections.append((default_title, preamble))

        heading_stack: list[tuple[int, str]] = []  # [(level, heading_text), ...]

        for i, match in enumerate(matches):
            level = len(match.group(1))
            h_text = match.group(2).strip()
            start = match.end()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(content)
            body = content[start:end]

            # Pop headings at the same or deeper level to maintain hierarchy
            while heading_stack and heading_stack[-1][0] >= level:
                heading_stack.pop()
            heading_stack.append((level, h_text))

            breadcrumb = f"{default_title} > " + " > ".join(h for _, h in heading_stack)
            sections.append((breadcrumb, body))

        return sections

    def _chunk_section_text(self, text: str) -> list[str]:
        """Split a section's text into chunks respecting chunk_size and chunk_overlap."""
        if len(text) <= self.chunk_size:
            return [text]

        # First, try to split by paragraphs (\n\n)
        paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
        chunks: list[str] = []
        current_chunk: list[str] = []
        current_len = 0

        for para in paragraphs:
            para_len = len(para)
            if current_len + para_len + 2 <= self.chunk_size:
                current_chunk.append(para)
                current_len += para_len + 2
            else:
                if current_chunk:
                    chunk_str = "\n\n".join(current_chunk)
                    chunks.append(chunk_str)

                    # Build overlap from the end of current_chunk, bounded to respect target chunk_size
                    max_overlap = min(self.chunk_overlap, max(0, self.chunk_size - para_len - 2))
                    overlap_str = self._extract_tail(chunk_str, max_overlap) if max_overlap >= self.min_chunk_size else ""
                    current_chunk = [overlap_str, para] if overlap_str else [para]
                    current_len = len("\n\n".join(current_chunk))
                else:
                    # Single paragraph is larger than chunk_size -> sliding window split
                    sub_chunks = self._sliding_window_split(para)
                    chunks.extend(sub_chunks[:-1])
                    current_chunk = [sub_chunks[-1]]
                    current_len = len(sub_chunks[-1])

        if current_chunk:
            remaining = "\n\n".join(current_chunk).strip()
            if remaining:
                chunks.append(remaining)

        return chunks

    def _sliding_window_split(self, text: str) -> list[str]:
        """Split long unbroken text using character-based sliding window with overlap."""
        chunks: list[str] = []
        start = 0
        step = self.chunk_size - self.chunk_overlap

        while start < len(text):
            end = min(start + self.chunk_size, len(text))
            chunk_slice = text[start:end].strip()
            if chunk_slice:
                chunks.append(chunk_slice)
            if end >= len(text):
                break
            start += step

        return chunks

    def _extract_tail(self, text: str, max_chars: int) -> str:
        """Extract up to max_chars from the end of text, cleanly on sentence/space boundary if possible."""
        if len(text) <= max_chars:
            return text
        tail = text[-max_chars:]
        # Try to find a whitespace or punctuation to avoid cutting words
        for sep in ["\n", ". ", "。 ", " ", ", ", "，"]:
            idx = tail.find(sep)
            if idx != -1 and idx < len(tail) // 2:
                return tail[idx + len(sep) :].strip()
        return tail.strip()
