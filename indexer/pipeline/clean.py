"""Stage 2: Clean. Remove artefacts without destroying structure.

Rules, in order (recorded in docs/PIPELINE.md):
1. Unicode NFKC (ligatures such as "ﬁ" become "fi") and the U+FFFD replacement character
   becomes an apostrophe (the handbooks' curly apostrophe extracts as U+FFFD).
2. pdfminer "(cid:NN)" glyph artefacts are removed.
3. Running headers and footers are removed: a line (digits masked) that appears on at least
   half the pages of a document with 3+ pages, either in the first or last three lines of
   the page or, for lines of four or more words, anywhere on it (two-column pages put the
   footer between the columns).
4. Bare page numbers ("12", "Page 12 of 58") on their own line are removed.
5. Words hyphenated across a line break are re-joined ("regis-\\ntration").
6. Runs of spaces collapse to one; three or more blank lines collapse to one blank line.

Deliberately NOT stripped: clause numbers at the start of a line ("1.21 ..."), headings,
Markdown table rows ("| a | b |") and blank lines, because chunking uses them as section,
clause and paragraph boundaries and citations need the clause numbers.
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter

from .models import Document, Page

EDGE_LINES = 3
REPEAT_SHARE = 0.5

_CID = re.compile(r"\(cid:\d+\)")
_PAGE_NO = re.compile(r"^\s*(page\s+)?\d{1,3}(\s+of\s+\d{1,3})?\s*$", re.I)
_HYPHEN = re.compile(r"(\w)-\n(\w)")


def _mask(line: str) -> str:
    """Digits masked, and a run of numbers counts as one: the footer "... Regulations 2026"
    and "... Regulations 2026 37" (page number on the same line) are the same line."""
    masked = re.sub(r"\d+", "#", " ".join(line.split())).lower()
    return re.sub(r"#(\s*#)+", "#", masked)


def _normalise(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).replace("�", "'")
    return _CID.sub("", text)


def repeating_lines(pages: list[Page]) -> set[str]:
    """Masked lines that sit at the top or bottom of at least half the pages."""
    non_empty = [p for p in pages if p.text.strip()]
    if len(non_empty) < 3:
        return set()
    counts: Counter[str] = Counter()
    for p in non_empty:
        lines = [ln for ln in p.text.splitlines() if ln.strip()]
        edges = lines[:EDGE_LINES] + lines[-EDGE_LINES:]
        # Long lines count wherever they sit: on two-column pages the running footer ends
        # up between the columns, not at the bottom of the extracted text.
        anywhere = [ln for ln in lines if len(ln.split()) >= 4]
        counts.update({_mask(ln) for ln in edges + anywhere})
    threshold = max(2, int(len(non_empty) * REPEAT_SHARE))
    return {line for line, n in counts.items() if n >= threshold and len(line) > 3}


def clean_text(text: str, drop: set[str]) -> str:
    kept = []
    for line in text.splitlines():
        if _mask(line) in drop or _PAGE_NO.match(line):
            continue
        kept.append(re.sub(r"[ \t]+", " ", line).rstrip())
    out = "\n".join(kept)
    out = _HYPHEN.sub(r"\1\2", out)
    return re.sub(r"\n{3,}", "\n\n", out).strip()


def clean(doc: Document) -> Document:
    """Strip headers and footers that repeat on every page; keep headings and
    section boundaries, because chunking and citations depend on them."""
    pages = [Page(source=p.source, page=p.page, text=_normalise(p.text), ocr=p.ocr)
             for p in doc.pages]
    drop = repeating_lines(pages)
    cleaned = [Page(source=p.source, page=p.page, text=clean_text(p.text, drop), ocr=p.ocr)
               for p in pages]
    return Document(source=doc.source, doc_version=doc.doc_version,
                    superseded=doc.superseded, pages=cleaned)
