"""Parse one explicitly selected Markdown file; reuse Week 9 chunk models."""

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
from pathlib import Path
import re

import yaml
from vector_search_lab.chunker import MarkdownChunker
from vector_search_lab.models import Chunk, Document


def document_id(source_path: str) -> str:
    return hashlib.sha256(source_path.encode("utf-8")).hexdigest()


@dataclass
class Note:
    document: Document
    tags: list[str]
    modified_at: datetime
    content_hash: str
    chunks: list[Chunk]


def read_note(path: Path, source_path: str | None = None) -> Note:
    if not path.is_file() or path.suffix.lower() != ".md":
        raise ValueError("Select one existing .md file, not a directory")
    source = source_path if source_path is not None else path.resolve().as_posix()
    if not source.strip():
        raise ValueError("source_path must not be empty")
    raw = path.read_bytes()
    body = raw.decode("utf-8-sig")
    metadata = {}
    match = re.match(r"\A---\r?\n(.*?)\r?\n---(?:\r?\n|$)", body, re.DOTALL)
    if match:
        metadata = yaml.safe_load(match.group(1)) or {}
        if not isinstance(metadata, dict):
            raise ValueError("Frontmatter must be a YAML mapping")
        body = body[match.end():]
    elif body.startswith("---\n") or body.startswith("---\r\n"):
        raise ValueError("Frontmatter requires a closing --- line")
    heading = re.search(r"^#\s+(.+)$", body, re.MULTILINE)
    title = metadata.get("title") or (heading.group(1).strip() if heading else path.stem)
    if not isinstance(title, str):
        raise ValueError("title must be a string")
    tags = metadata.get("tags", [])
    if isinstance(tags, str):
        tags = re.split(r"[,\s]+", tags)
    if not isinstance(tags, list) or any(not isinstance(tag, str) for tag in tags):
        raise ValueError("tags must be strings or a list of strings")
    tags = sorted({tag.strip().lstrip("#") for tag in tags if tag.strip().lstrip("#")})
    doc = Document(id=document_id(source), title=title, content=body,
                   source_file=source, metadata={"tags": tags, "frontmatter": metadata})
    return Note(doc, tags, datetime.fromtimestamp(path.stat().st_mtime, timezone.utc),
                hashlib.sha256(raw).hexdigest(),
                MarkdownChunker(min_chunk_size=1).chunk_document(doc))
