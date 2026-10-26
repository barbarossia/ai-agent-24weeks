from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .models import Citation
from .security import looks_instruction_like


WORD = re.compile(r"[a-z0-9][a-z0-9.-]{1,}", re.I)


@dataclass(frozen=True)
class RetrievedKnowledge:
    citations: tuple[Citation, ...]
    redacted_paragraphs: int


def _sections(path: Path, vault_root: Path) -> list[tuple[str, int, str]]:
    lines = path.read_text(encoding="utf-8").splitlines()
    rel = path.resolve().relative_to(vault_root.resolve()).as_posix()
    heading = path.stem.replace("-", " ").title()
    start = 1
    chunks: list[tuple[str, int, list[str]]] = []
    body: list[str] = []
    for number, line in enumerate(lines, 1):
        if line.startswith("#"):
            if body:
                chunks.append((heading, start, body))
                body = []
            heading = line.lstrip("# ").strip()
            start = number
        else:
            body.append(line)
    if body:
        chunks.append((heading, start, body))

    result: list[tuple[str, int, str]] = []
    for section_heading, line_number, section_lines in chunks:
        paragraph_lines: list[str] = []
        safe_paragraphs: list[str] = []
        for line in section_lines + [""]:
            if line.strip():
                paragraph_lines.append(line.strip())
                continue
            if paragraph_lines:
                paragraph = " ".join(paragraph_lines)
                paragraph_lines = []
                if not looks_instruction_like(paragraph):
                    safe_paragraphs.append(paragraph)
        content = " ".join(safe_paragraphs).strip()
        if content:
            result.append((section_heading, line_number, content))
    return [(rel, start, f"{heading}\n{text}") for heading, start, text in result]


class ObsidianRetriever:
    """Prioritize canonical runbooks and include one matching archived report as context."""

    def __init__(self, vault_root: Path):
        self.vault_root = vault_root.resolve()
        self.knowledge_root = (self.vault_root / "knowledge").resolve()
        if not self.knowledge_root.is_relative_to(self.vault_root):
            raise ValueError("knowledge directory must stay inside the configured vault")

    def retrieve(self, query: str, *, topic_terms: str = "", top_k: int = 3) -> RetrievedKnowledge:
        if not 1 <= top_k <= 5:
            raise ValueError("top_k must be between 1 and 5")
        query_tokens = {word.casefold() for word in WORD.findall(f"{query} {topic_terms}")}
        runbook_candidates: list[tuple[int, str, int, str, str]] = []
        archive_candidates: list[tuple[int, str, int, str, str]] = []
        redacted = 0
        for path in sorted(self.knowledge_root.rglob("*.md")):
            resolved = path.resolve()
            if not resolved.is_relative_to(self.knowledge_root) or not resolved.is_file():
                continue
            relative_path = resolved.relative_to(self.knowledge_root)
            document_candidates = archive_candidates if len(relative_path.parts) > 1 else runbook_candidates
            raw = path.read_text(encoding="utf-8")
            redacted += sum(1 for paragraph in re.split(r"\n\s*\n", raw) if looks_instruction_like(paragraph))
            for source, line, text in _sections(path, self.vault_root):
                score = len(query_tokens & {word.casefold() for word in WORD.findall(text)})
                if score:
                    heading, _, excerpt = text.partition("\n")
                    document_candidates.append((score, source, line, heading, excerpt))
        ordering = lambda item: (-item[0], item[1], item[2])
        runbook_candidates.sort(key=ordering)
        archive_candidates.sort(key=ordering)
        if runbook_candidates and archive_candidates and top_k > 1:
            # Keep canonical runbooks first and reserve one secondary slot for prior incidents.
            selected = runbook_candidates[: top_k - 1] + archive_candidates[:1]
        elif runbook_candidates:
            selected = runbook_candidates[:top_k]
        else:
            selected = archive_candidates[:1]
        citations = tuple(
            Citation(
                source=source,
                heading=heading,
                line=line,
                excerpt=excerpt[:400],
                source_id=f"{source}#{heading.lower().replace(' ', '-')}",
            )
            for _, source, line, heading, excerpt in selected
        )
        return RetrievedKnowledge(citations=citations, redacted_paragraphs=redacted)
