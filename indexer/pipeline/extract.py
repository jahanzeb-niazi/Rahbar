"""Stage 1: Extract. PDF (or HTML, or Markdown) to text, page by page.

PDF pages with no text layer are OCR'd (tesseract via pdf2image + pytesseract) and marked
ocr=True. Two-column pages are read column by column, because reading straight across a
gutter interleaves two unrelated clauses on every line. Tables found by pdfplumber are
rendered as Markdown rows ("| a | b |") so their columns stay aligned in the chunk text.
HTML pages keep their headings as Markdown headings and their tables as Markdown rows.
"""

from __future__ import annotations

import json
import re
import time
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from .models import Document, Page

MIN_TEXT_CHARS = 20      # a page with less text than this is treated as having no text layer
GUTTER_MIN_GAP = 12.0    # points of white space at the midline that make a column gutter


def _log(msg: str, **fields: object) -> None:
    print(json.dumps({"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                      "logger": "rahbar.indexer.extract", "msg": msg, **fields}), flush=True)


def extract(path: str, doc_version: str, superseded: bool) -> Document:
    """Return the document's text page by page.

    Detect pages with no text layer and OCR them; mark those pages ocr=True.
    The OCR libraries need system packages in the Dockerfile (tesseract-ocr,
    poppler-utils), not only pip packages.
    """
    p = Path(path)
    suffix = p.suffix.lower()
    doc = Document(source=p.name, doc_version=doc_version, superseded=superseded)
    if suffix == ".pdf":
        doc.pages = _extract_pdf(p)
    elif suffix in (".html", ".htm"):
        doc.pages = [Page(source=p.name, page=1, text=html_to_text(p.read_text("utf-8", "replace")))]
    elif suffix == ".md":
        doc.pages = [Page(source=p.name, page=1, text=_strip_front_matter(p.read_text("utf-8")))]
    else:
        doc.pages = [Page(source=p.name, page=1, text=p.read_text("utf-8", "replace"))]
    return doc


# ---------------------------------------------------------------- Markdown

def _strip_front_matter(text: str) -> str:
    lines = text.splitlines()
    if lines and lines[0].strip() == "---":
        for i, line in enumerate(lines[1:], start=1):
            if line.strip() == "---":
                return "\n".join(lines[i + 1:]).strip() + "\n"
    return text


# ---------------------------------------------------------------- PDF

def _extract_pdf(path: Path) -> list[Page]:
    import pdfplumber

    pages: list[Page] = []
    ocr_pages: list[int] = []
    with pdfplumber.open(str(path)) as pdf:
        for number, raw_page in enumerate(pdf.pages, start=1):
            # Print-layout PDFs carry the facing page's text at negative x, outside the
            # visible page; reading it would duplicate (and interleave) a neighbour page.
            page = raw_page.within_bbox((0, 0, raw_page.width, raw_page.height))
            text = _pdf_page_text(page)
            # Free the page's parsed objects now. pdfplumber caches them per page, and the
            # 2023 rules draw every glyph as vector outlines: without this, that one PDF
            # held ~950 MB and the indexer was OOMKilled (docs/ENGINEERING-NOTES.md, Q4).
            raw_page.close()
            if len(text.strip()) >= MIN_TEXT_CHARS:
                pages.append(Page(source=path.name, page=number, text=text))
                continue
            ocr_text = _ocr_page(path, number)
            if ocr_text is None:
                _log("page has no text layer and OCR is unavailable; page lost",
                     source=path.name, page=number)
                pages.append(Page(source=path.name, page=number, text="", ocr=False))
            else:
                ocr_pages.append(number)
                pages.append(Page(source=path.name, page=number, text=ocr_text, ocr=True))
    if ocr_pages:
        _log("ocr applied", source=path.name, pages=len(ocr_pages))
    return pages


def _lines(page: Any) -> list[list[dict[str, Any]]]:
    rows: dict[int, list[dict[str, Any]]] = {}
    for w in page.extract_words():
        rows.setdefault(round(w["top"] / 3), []).append(w)
    return list(rows.values())


def column_gutters(page: Any) -> list[float]:
    """x positions of the vertical white-space strips that separate text columns.

    For every x, count the text lines that have a word covering it. A gutter is a run of
    at least GUTTER_MIN_GAP points that almost no line covers (full-width headers and
    titles may cross it) with text on both sides. One column gives no gutters."""
    lines = _lines(page)
    if len(page.chars) < 200 or len(lines) < 8:
        return []
    width = int(page.width) + 1
    coverage = [0] * width
    for words in lines:
        for w in words:
            for x in range(max(0, int(w["x0"])), min(width, int(w["x1"]) + 1)):
                coverage[x] += 1
    covered = [x for x in range(width) if coverage[x]]
    if not covered:
        return []
    lo, hi = covered[0], covered[-1]
    tolerance = max(2, int(0.08 * len(lines)))
    gutters: list[float] = []
    run_start = None
    for x in range(lo, hi + 1):
        if coverage[x] <= tolerance:
            run_start = x if run_start is None else run_start
            continue
        if run_start is not None and x - run_start >= GUTTER_MIN_GAP:
            gutters.append((run_start + x) / 2)
        run_start = None
    # a real column holds a meaningful share of the text on each side of every gutter
    edges = [lo, *gutters, hi]
    for a, b in zip(edges, edges[1:]):
        if sum(coverage[int(a):int(b)]) < 0.1 * sum(coverage):
            return []
    return gutters


def _region_text(region: Any) -> str:
    """Text outside tables, then each table as Markdown rows. A detected "table" that
    covers most of the region or holds paragraph-length cells is a layout box, not a
    table, so it is read as text."""
    area = max(1.0, (region.bbox[2] - region.bbox[0]) * (region.bbox[3] - region.bbox[1]))
    tables = []
    for t in region.find_tables():
        x0, top, x1, bottom = t.bbox
        cells = [c for row in t.extract() for c in row if c]
        if (x1 - x0) * (bottom - top) > 0.6 * area or any(len(c) > 250 for c in cells):
            continue
        tables.append(t)
    boxes = [t.bbox for t in tables]

    def outside(obj: dict[str, Any]) -> bool:
        if obj.get("object_type") != "char":
            return True
        cx, cy = (obj["x0"] + obj["x1"]) / 2, (obj["top"] + obj["bottom"]) / 2
        return not any(x0 <= cx <= x1 and top <= cy <= bottom for x0, top, x1, bottom in boxes)

    text = region.filter(outside).extract_text() or ""
    rendered = [table_to_markdown(t.extract()) for t in tables]
    rendered = [r for r in rendered if r]
    if rendered:
        text = text.rstrip() + "\n\n" + "\n\n".join(rendered) + "\n"
    return text


def _pdf_page_text(page: Any) -> str:
    """Multi-column pages: full-width lines (running headers, titles) that cross a gutter
    are read whole first (or last, below the middle), then each column left to right."""
    gutters = column_gutters(page)
    if not gutters:
        return _region_text(page)
    wide_tops = {round(w["top"]) for words in _lines(page)
                 if any(w["x0"] < g < w["x1"] for w in words for g in gutters)
                 for w in words}

    def in_wide_line(obj: dict[str, Any]) -> bool:
        return obj.get("object_type") == "char" and round(obj["top"]) in wide_tops

    def column(x0: float, x1: float) -> str:
        region = page.crop((x0, 0, x1, page.height))
        return _region_text(region.filter(lambda o: not in_wide_line(o)))

    middle = page.height / 2
    head = page.filter(lambda o: in_wide_line(o) and o["top"] < middle).extract_text() or ""
    foot = page.filter(lambda o: in_wide_line(o) and o["top"] >= middle).extract_text() or ""
    edges = [0.0, *gutters, float(page.width)]
    parts = [head, *(column(a, b) for a, b in zip(edges, edges[1:])), foot]
    return "\n\n".join(p.strip() for p in parts if p.strip()) + "\n"


def table_to_markdown(rows: list[list[str | None]]) -> str:
    """Render a table as Markdown rows, one row per line, so each value stays next to
    its column header. Empty rows are dropped; cell line breaks become spaces."""
    clean = [[" ".join((cell or "").split()) for cell in row] for row in rows if row]
    clean = [row for row in clean if any(row)]
    if len(clean) < 2:
        return ""
    width = max(len(r) for r in clean)
    clean = [r + [""] * (width - len(r)) for r in clean]
    lines = ["| " + " | ".join(clean[0]) + " |", "| " + " | ".join(["---"] * width) + " |"]
    lines += ["| " + " | ".join(r) + " |" for r in clean[1:]]
    return "\n".join(lines)


def _ocr_page(path: Path, number: int) -> str | None:
    """OCR one page at 300 dpi. Returns None when tesseract or poppler is not installed."""
    try:
        import pytesseract
        from pdf2image import convert_from_path
    except ImportError:
        return None
    try:
        images = convert_from_path(str(path), dpi=300, first_page=number, last_page=number)
        if not images:
            return ""
        # --psm 6 (one uniform block): the default layout analysis split clause numbers
        # into their own column, so "7. Procedure for evaluating..." never formed a heading.
        return str(pytesseract.image_to_string(images[0], lang="eng", config="--psm 6"))
    except Exception as exc:  # tesseract/poppler binaries missing, or a corrupt page
        _log("ocr failed", source=path.name, page=number, error=type(exc).__name__)
        return None


# ---------------------------------------------------------------- HTML

class _HtmlText(HTMLParser):
    """HTML to Markdown-ish text: headings, paragraphs, list items and tables."""

    SKIP = {"script", "style", "noscript", "nav", "header", "footer", "svg", "form", "button",
            "select", "iframe"}
    BLOCK = {"p", "div", "section", "article", "br", "li", "ul", "ol", "dd", "dt", "main"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self.skip_depth = 0
        self.table: list[list[str]] | None = None
        self.row: list[str] | None = None
        self.cell: list[str] | None = None
        self.heading: int | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self.SKIP:
            self.skip_depth += 1
            return
        if self.skip_depth:
            return
        if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            self.heading = int(tag[1])
            self.out.append("\n\n" + "#" * self.heading + " ")
        elif tag == "table":
            self.table = []
        elif tag == "tr" and self.table is not None:
            self.row = []
        elif tag in ("td", "th") and self.row is not None:
            self.cell = []
        elif tag in self.BLOCK and self.cell is None:
            self.out.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self.SKIP:
            self.skip_depth = max(0, self.skip_depth - 1)
            return
        if self.skip_depth:
            return
        if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            self.heading = None
            self.out.append("\n\n")
        elif tag in ("td", "th") and self.row is not None and self.cell is not None:
            self.row.append(" ".join("".join(self.cell).split()))
            self.cell = None
        elif tag == "tr" and self.table is not None and self.row is not None:
            self.table.append(self.row)
            self.row = None
        elif tag == "table" and self.table is not None:
            rendered = table_to_markdown([list(r) for r in self.table])
            if rendered:
                self.out.append("\n\n" + rendered + "\n\n")
            self.table = None
        elif tag in ("p", "li", "div"):
            self.out.append("\n")

    def handle_data(self, data: str) -> None:
        if self.skip_depth:
            return
        if self.cell is not None:
            self.cell.append(data)
        elif self.table is None:
            self.out.append(data if self.heading is None else " ".join(data.split()))


def html_to_text(html: str) -> str:
    parser = _HtmlText()
    parser.feed(html)
    text = "".join(parser.out)
    lines = [" ".join(line.split()) for line in text.splitlines()]
    text = "\n".join(lines)
    return re.sub(r"\n{3,}", "\n\n", text).strip() + "\n"
