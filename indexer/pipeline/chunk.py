"""Stage 3: Chunk. Structure-aware, with overlap.

Sizes are in approximate tokens: words x 1.3 (see estimate_tokens). The splitter works
top-down, exactly as section 3.1 asks:

1. Sections: a heading starts a new section and a chunk never crosses a section boundary.
   Headings are Markdown headings ("## 2. Academic warning"), numbered chapter titles
   ("4. Registration") or short title-case lines ("Attendance Requirements").
2. Paragraphs: blank lines, numbered clauses ("1.21 Students are ...") and table rows.
3. Sentences: only when a single paragraph is larger than the target size.

Units are packed greedily up to `size` tokens. The next chunk in the same section starts
with the last whole sentences of the previous one, up to `overlap` tokens. Every chunk's
text begins with its section heading, so the vector and the reader both know where it sits.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

from .models import Chunk, Document

TOKENS_PER_WORD = 1.3
MAX_SECTION_CHARS = 120

_MD_HEADING = re.compile(r"^#{1,6}\s+(.+?)\s*#*$")
_CHAPTER = re.compile(r"^(\d{1,2})\.\s+([A-Z][^.]{2,80})$")
_ROMAN = re.compile(r"^[IVX]{1,5}\s*[-'.–]\s*[A-Z][A-Za-z &,]{3,80}$")
_CLAUSE = re.compile(r"^\(?\d{1,2}(\.\d{1,2}){1,3}\)?\s+\S")
_SENTENCE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9(\"'])")
_SMALL = {"of", "and", "the", "in", "for", "to", "with", "a", "an", "on", "under", "at",
          "by", "or", "from", "as", "into", "per", "vs", "&"}


def estimate_tokens(text: str) -> int:
    return math.ceil(len(text.split()) * TOKENS_PER_WORD)


def heading_of(line: str) -> str | None:
    """Return the heading text if this line is a heading, else None."""
    s = line.strip()
    if not s or s.startswith("|"):
        return None
    m = _MD_HEADING.match(s)
    if m:
        return m.group(1).strip()
    # table-of-contents lines end in a page number or dot leaders: not headings
    if re.search(r"(\.{3,}|\s\d{1,3})$", s):
        return None
    chapter = _CHAPTER.match(s)
    if chapter:
        title = chapter.group(2)
        words = title.split()
        short = len(words) <= 7 and "," not in title and words[-1].lower() not in _SMALL
        return s if _title_case(title) or short else None
    if _ROMAN.match(s) and len(s.split()) <= 10:
        return s
    if _CLAUSE.match(s) or s[0].isdigit():
        return None
    if s[-1] in ".,;)" or not s[0].isupper():
        return None
    return s.rstrip(":") if _title_case(s) else None


def _title_case(s: str) -> bool:
    """1 to 8 words, the first capitalised, and at least 3/4 of the significant words."""
    words = s.rstrip(":").split()
    if not 1 <= len(words) <= 8 or not words[0][0].isupper():
        return False
    significant = [w for w in words if w.lower() not in _SMALL]
    if not significant:
        return False
    capitalised = sum(1 for w in significant if w[0].isupper())
    return capitalised / len(significant) >= 0.75


@dataclass
class _Unit:
    text: str
    page: int
    tokens: int


@dataclass
class _Section:
    title: str
    units: list[_Unit]


def _paragraphs(lines: list[tuple[str, int]]) -> list[_Unit]:
    """Join lines into paragraphs. A blank line, a clause number or a table row starts one."""
    units: list[_Unit] = []
    buf: list[str] = []
    page = 0

    def flush() -> None:
        nonlocal buf
        if buf:
            text = " ".join(buf).strip()
            if text:
                units.append(_Unit(text, page, estimate_tokens(text)))
        buf = []

    for line, pg in lines:
        s = line.strip()
        if not s:
            flush()
            continue
        if s.startswith("|"):
            flush()
            units.append(_Unit(s, pg, estimate_tokens(s)))
            continue
        if _CLAUSE.match(s) or re.match(r"^[a-z]\)\s", s):
            flush()
        if not buf:
            page = pg
        buf.append(s)
    flush()
    return units


def _sections(doc: Document) -> list[_Section]:
    sections: list[_Section] = []
    chapter = ""
    title = doc.source
    lines: list[tuple[str, int]] = []

    def close() -> None:
        units = _paragraphs(lines)
        if units:
            sections.append(_Section(title, units))
        lines.clear()

    for page in doc.pages:
        for line in page.text.splitlines():
            h = heading_of(line)
            if h is None:
                lines.append((line, page.page))
                continue
            close()
            if _CHAPTER.match(h) or _ROMAN.match(h) or _MD_HEADING.match(line.strip()):
                chapter = h
                title = h
            else:
                title = f"{chapter} > {h}" if chapter and chapter != h else h
            title = title[:MAX_SECTION_CHARS]
        lines.append(("", page.page))   # a page break ends a paragraph
    close()
    return sections


def _split_large(unit: _Unit, size: int) -> list[_Unit]:
    """Split one oversized paragraph into sentences; split a giant sentence by words."""
    if unit.tokens <= size:
        return [unit]
    pieces: list[_Unit] = []
    for sentence in _SENTENCE.split(unit.text):
        t = estimate_tokens(sentence)
        if t <= size:
            pieces.append(_Unit(sentence, unit.page, t))
            continue
        words = sentence.split()
        step = max(1, int(size / TOKENS_PER_WORD))
        for i in range(0, len(words), step):
            part = " ".join(words[i:i + step])
            pieces.append(_Unit(part, unit.page, estimate_tokens(part)))
    return pieces


def _overlap_tail(units: list[_Unit], overlap: int) -> list[_Unit]:
    """The last whole sentences of a chunk, up to `overlap` tokens."""
    if overlap <= 0:
        return []
    sentences: list[_Unit] = []
    for u in units:
        if u.text.startswith("|"):
            sentences.append(u)
        else:
            sentences.extend(_Unit(s, u.page, estimate_tokens(s)) for s in _SENTENCE.split(u.text))
    tail: list[_Unit] = []
    total = 0
    for s in reversed(sentences):
        if total + s.tokens > overlap:
            break
        tail.insert(0, s)
        total += s.tokens
    return tail


def chunk(doc: Document, size: int, overlap: int) -> list[Chunk]:
    """Split on sections, then paragraphs, then sentences, keeping each chunk under
    `size` tokens, with `overlap` tokens shared between neighbours. Every chunk keeps
    the section heading it sits under, its page, doc_version and superseded."""
    if size <= 0 or overlap < 0 or overlap >= size:
        raise ValueError(f"need 0 <= overlap < size, got size={size} overlap={overlap}")
    stem = re.sub(r"[^a-z0-9]+", "-", doc.source.lower()).strip("-")
    chunks: list[Chunk] = []

    def emit(section: str, units: list[_Unit]) -> None:
        body = "\n".join(u.text for u in units).strip()
        if not body:
            return
        chunks.append(Chunk(
            id=f"{stem}-{len(chunks):04d}",
            text=f"{section}\n{body}",
            source=doc.source, section=section, page=units[0].page,
            doc_version=doc.doc_version, superseded=doc.superseded,
        ))

    for sec in _sections(doc):
        current: list[_Unit] = []
        fresh = 0   # tokens in `current` that are not overlap carried from the last chunk
        for unit in (p for u in sec.units for p in _split_large(u, size)):
            used = sum(u.tokens for u in current)
            if current and fresh and used + unit.tokens > size:
                emit(sec.title, current)
                current = _overlap_tail(current, overlap)
                fresh = 0
                while current and sum(u.tokens for u in current) + unit.tokens > size:
                    current.pop(0)
            current.append(unit)
            fresh += unit.tokens
        if fresh:
            emit(sec.title, current)
    return chunks
