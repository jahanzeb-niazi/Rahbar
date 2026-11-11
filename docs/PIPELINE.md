# Indexing and retrieval pipeline

Five stages in `indexer/pipeline/` (`extract.py`, `clean.py`, `chunk.py`, `embed.py`,
`store.py`), run by `indexer/pipeline/run.py` as a Kubernetes Job. Every number below comes
from the indexer's own JSON log lines (`chunked`, `chunking summary`, `embedded`) or from
`eval/results.json`.

## Extraction

`extract.py` reads PDFs page by page with pdfplumber, HTML with a small parser that keeps
headings and turns tables into Markdown rows, and Markdown as is.

**OCR.** A page with fewer than 20 characters of text (`MIN_TEXT_CHARS`) has no usable text
layer. It is rendered at 300 dpi (pdf2image and poppler) and read by tesseract with
`--psm 6`, and the page is marked `ocr=True`. The indexer image installs `tesseract-ocr`,
`tesseract-ocr-eng` and `poppler-utils` (`indexer/Dockerfile`). From the log of
`manual-reindex-1`:

| Document | Pages | OCR'd | Still empty after OCR |
| --- | ---: | ---: | ---: |
| Faculty Entrepreneurship and Technical Start-ups Policy (scanned) | 8 | **8** | 0 |
| Undergraduate Academic Rules, Aug 2023 (glyphs drawn as vector outlines) | 26 | **24** | 1 |
| Academic Rules Handbook, Jun 2026 (image-only cover and dividers) | 58 | 5 | 3 |
| Student Handbook, Jun 2026 (image-only cover and dividers) | 64 | 4 | 3 |
| Other five documents | 124 | 0 | 0 |

41 pages are OCR'd in all. Without OCR the start-up policy gives 0 chunks and the 2023
rules give 2 (failure analysis, stage A).

Two other extraction rules matter:

- **Crop to the visible page.** The handbooks are print layouts that carry the facing page's
  text at negative x, so each page is cropped to its own box before extraction.
- **Multi-column pages are read column by column.** `column_gutters()` finds vertical white
  strips that almost no text line crosses. Full-width lines (titles, running headers) are
  read first, then each column left to right.

**Tables: one that was recovered.** The fee page's "Miscellaneous Fees" table. Read as
plain text, the label and the amount end up on separate lines, far apart. The HTML parser
renders each `<tr>` as one Markdown row, so the value stays next to its label in the chunk:

```
| Paper Rechecking Fee (Per Course/Lab) | Rs. 500 |
| Issuance of Certificate/Letter Fee | Rs. 300 |
```

PDF tables found by pdfplumber are rendered the same way (`table_to_markdown`).

**Tables: one that was mangled, and what we could not recover.** Prospectus 2026, page 1,
is a three-column page whose third column holds the grade-point tables. Before our guard,
pdfplumber's `find_tables()` reported the *whole page* as one 2-column table, bounding box
`[0, 0, 612, 792]`, and turned three columns of prose into one cell:

```
| FAST-NUCES Academic Rules and Regulations |  |
| --- | --- |
| Letter grades for MS & MBA pr ograms: 1. Attendance Requirement 4. Semester Course Load Gr ade Po ints ... A+ 4.00 B- 2.67 100% attendance in lectures, labs, ...
```

`_region_text()` now rejects a "table" that covers more than 60% of the region or has a
cell longer than 250 characters, and reads it as text. That stops the giant cell, but the
page is still **not recovered**:

- The gutter detector finds no columns on the five prospectus pages. Stray marks in the
  left margin, and clause numbers ("4.", "5.") hanging into the gutters, break its test.
- Each text line therefore runs across all three columns:
  `A+ 4.00 B- 2.67` sits on the same line as attendance-rule prose.

We tried to fix the detector: drop an edge strip that holds almost no text, ignore list
markers, and cut at the emptiest point of the gutter. The prospectus pages came out right,
but the same change split two single-column handbook pages and an annual-report table
(journal articles per department) into false columns, separating numbers from their rows.
We reverted it, because 5 pages were not worth damaging others.

The cost is measurable. The grade-point question (e03) is still answered, from the Grading
web page, which carries the same table cleanly. The prospectus copy of the table is noise
in the index.

Other things lost:

- The handbook covers and dividers (6 pages), which are images with no words even after OCR.
- The prospectus spells some words with spaces inside ("pr ograms", "Gr ade Po ints"),
  because pdfminer splits words at kerning gaps. We left that alone.

## Cleaning

`clean.py`, applied per document, in this order:

1. Unicode NFKC, so ligatures such as "ﬁ" become "fi". U+FFFD becomes an apostrophe,
   because the handbooks' curly apostrophe extracts as U+FFFD.
2. pdfminer `(cid:NN)` glyph artefacts are removed.
3. **Running headers and footers** are removed. These are lines that appear on at least half
   the non-empty pages of a document with 3 or more pages, compared with digits masked and
   a run of numbers counted as one. A line counts in the first or last three lines of a
   page; a line of four or more words counts anywhere on it, because on two-column pages
   the footer lands between the columns. This removes, for example, "NATIONAL UNIVERSITY OF
   COMPUTER AND EMERGING SCIENCES" and the handbook's "Academic Rules and Regulations 2026
   37" footer.
4. Bare page numbers ("12", "Page 12 of 58") on their own line are removed.
5. Words hyphenated across a line break are re-joined ("regis-\ntration").
6. Runs of spaces collapse to one, and three or more blank lines collapse to one blank line.

**Deliberately not stripped:**

- **Clause numbers at the start of a line** ("1.21 Students are…"). They look like
  numbering noise, but chunking uses them as paragraph boundaries, the exact-term question
  e01 asks for one, and citations need them.
- Headings, Markdown table rows and blank lines, for the same reason: they are the
  section, row and paragraph boundaries the chunker splits on.

## Chunking

Structure-aware, in `chunk.py`. Sections (headings) come first, then paragraphs (a blank
line, a clause number, a lettered item, a table row), then sentences, only for a paragraph
larger than the target. Overlap carries the previous chunk's last whole sentences, and
never crosses a section. Every chunk's text starts with its section heading. Sizes are
approximate tokens, words × 1.3. The design and its options are in
`docs/adr/0002-chunking.md`.

**Shipped: 200 tokens, overlap 25** (`CHUNK_SIZE`, `CHUNK_OVERLAP` in
`k8s/base/configmap.yaml`). **877 chunks.** **Storage amplification 1.071**: 99,943 stored
tokens divided by 93,318 original tokens after cleaning.

Each configuration was a full re-index of the real corpus, then the 19-question golden
set with the stub provider (recall depends only on retrieval). Raw results are in
`docs/evidence/chunking/`.

| Size (tokens) | Overlap (tokens) | recall@5 | recall@1 | MRR | Chunks stored | Storage amplification |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| **200** | **25** | **0.941** | **0.765** | **0.843** | 877 | 1.071 |
| 400 | 50 | 0.941 | 0.706 | 0.824 | 679 | 1.055 |
| 800 | 100 | 0.941 | 0.647 | 0.794 | 615 | 1.033 |

Why 200/25:

- recall@5 ties at 16 of 17 answerable questions. The miss in every setting is e01, the
  exact clause number.
- The ranking metrics decide it. With smaller chunks the right passage is first more often.
  That matters because the model reads the first passages most.
- The prompt stays short: five passages of about 200 tokens fit the 4,096-token context we
  can afford on CPU.

For contrast, stage B of the failure analysis (fixed 100-token windows, no overlap) is
reported in `docs/FAILURE-ANALYSIS.md`.

**Store and metadata schema.** `store.py` writes each chunk with this metadata:

| Field | Type | Example |
| --- | --- | --- |
| `source` | str | `academic-rules-handbook-jun-2026.pdf` |
| `section` | str | `5. Academic Assessment > Academic Warning/Probation` |
| `page` | int | 23 |
| `doc_version` | str | `2026-06` |
| `superseded` | bool | `false` (`true` for the Aug 2023 rules) |

The chunk id is `{file stem}-{n:04d}`, which is stable for the same document and position.
The API filters on `superseded`. Writes are **blue/green**:

1. The Job writes a new collection, `rahbar-g<UTC timestamp>`.
2. It checks the count.
3. It points the `rahbar-active` pointer collection at the new one.
4. It keeps the previous generation for in-flight queries and deletes older ones.

A failed Job therefore never leaves the API with a half-written index (ADR 0001).

## Embedding

- **Model:** `nomic-embed-text` via Ollama.
- **Dimension:** 768.
- **Prefixes:** `search_document: ` on chunks (`indexer/pipeline/embed.py`) and
  `search_query: ` on questions (`api/app/retrieval/chroma.py`), as the model expects.
- **Batching:** 32 texts per batch, 3 attempts each.

**Where the pin lives.** The collection metadata, written by
`indexer/pipeline/store.py:53-55`, holds `"embed_model"` and `"dimension"` next to
`"hnsw:space": "cosine"`. The API reads the model it should use from `EMBED_MODEL` in the
ConfigMap.

**How the API checks it.** `api/app/services/pin.py:13` (`pin_mismatch`) compares the two
models. It is called:

- by `/readyz` (`api/app/retrieval/chroma.py:147`), which returns 503, so a mismatched pod
  never receives traffic;
- before every retrieval (`api/app/retrieval/chroma.py:105`), which raises
  `PinMismatchError`, turned into a clear 503 by `api/app/routes/ask.py:24`.

The retriever also checks that the question vector's length equals the stored
`dimension`. The demonstration is in `docs/evidence/embedding-pin-guard.txt`: the pod with
`EMBED_MODEL=all-minilm` stays 0/1 READY with

```
embedding model mismatch: the index was built with 'nomic-embed-text' (dimension 768) but this API has EMBED_MODEL='all-minilm'
```

while the three old pods keep serving.

## Semantic cache

Redis (ADR 0003). There is one hash per index generation, `rahbar:cache:<generation>`, and
a hit is cosine similarity ≥ `CACHE_THRESHOLD` between query embeddings. We tested ten
question pairs:

- five paraphrases, which should hit;
- five near-misses that need a different answer, which must not.

Tried with `nomic-embed-text`; raw output in `docs/evidence/cache-threshold-experiment.txt`.

| Threshold | Correct hits (of 5) | False hits (of 5) |
| ---: | ---: | ---: |
| 0.90 | 4 | 2 |
| 0.93 | 3 | **1** |
| **0.95** | **3** | **0** |
| 0.97 | 2 | 0 |

**The false hit that ruled out 0.93:**

- "Can I take a new elective in summer under the **2023** rules?" scores **0.9323** against
  the cached "…under the **2026** rules?".
- At 0.93 the cache would serve the current rule (repeat courses only) to someone asking
  about the repealed one (one or two new electives allowed).
- At 0.90, "What grade point is a **B+**?" (0.9132) would also get the cached answer for
  **B-**.

**Shipped: 0.95**, the lowest threshold with zero false hits. The cost is two missed
paraphrases (0.9244 and 0.8693), which are simply generated again.

Rules in `api/app/services/answer.py`:

- Follow-up questions (`api/app/services/followup.py`) skip the cache entirely.
- Abstentions, fallback answers and answers with no valid citation are never stored.
- When a lookup or store sees a newer generation than the cached ones, it deletes the stale
  hashes. Evidence in `docs/evidence/reindex-cache-invalidation.txt`: after
  `manual-reindex-1` the same question is a miss again, and the api logs
  `cache invalidated after re-index`.

## Relevance floor

`RELEVANCE_FLOOR=0.65`. Passages scoring below it are dropped from the prompt. If none is
left, the API abstains without calling the model. From `eval/results.json`:

- every relevant passage of every answerable question scored at least 0.6929 (e04's fee
  row at rank 3);
- the hostel questions topped out at 0.7303 (a01) and 0.6471 (a02).

The floor is a safety net, not the abstention mechanism. No floor separates a01 from the
answerable questions, because nearby hostel text exists. a01 is abstained by the model,
following the prompt's rule. 0.65 keeps a 0.04 margin below the weakest relevant passage.
It catches a02 by only 0.003, which we report as luck, not design.

## Evaluation method

`eval/run_eval.py` sends each `eval/golden.yaml` question through the Ingress and reads
`retrieved` (chunk id, source, section, score) and `citations` from the response.

- **Matching.** A retrieved passage matches a golden one when the **source file is the
  same** and the **golden section is contained in the retrieved section**, after
  lower-casing and collapsing spaces (`_matches`). Sections are matched, not chunk ids,
  because chunk ids change whenever chunking changes, and the golden set was written once,
  before tuning.
- **recall@k** for a question is the share of its golden passages found in the top k. It is
  averaged over answerable questions; abstain questions have no golden passages.
- **MRR** uses the rank of the first relevant passage.
- **Citation validity** pools all citations: a citation is valid when it names a passage
  that was actually retrieved for that question.
- **Abstention correctness** is the share of must-abstain questions answered with
  `answered_from_context: false`.

The CI gate (`gate()`) fails when:

- recall@5 is more than 5 points below `eval/baseline.json`;
- any must-abstain question is answered;
- citation validity is below 0.95.

**Final run** (real llama3.2:3b, 200/25, `eval/results.json`, copied to
`eval/baseline.json`):

| Metric | Value |
| --- | ---: |
| recall@5 | 0.941 |
| recall@3 | 0.941 |
| recall@1 | 0.765 |
| MRR | 0.843 |
| Citation validity | 1.0 (16 citations) |
| Abstention correctness | 1.0 |
| Gate | **passed** |

recall@5 by question type: ordinary 1.0, version 1.0, injection 1.0, exact **0.75**. The
exact-term question is the weak one (ENGINEERING-NOTES question 5).
