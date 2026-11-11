# Failure analysis

We broke four of the six stages, one at a time, measured each, and restored it before the
next. None of the breaks touched the live index or the deployed API:

- **A and B** ran as one-off Jobs created from the `reindex` CronJob, with
  `CHROMA_COLLECTION=rahbarbrk`. They wrote a separate collection and pointer, so
  `rahbar-active` never moved.
- **A, B and C** were scored with the 19-question golden set through a local api with the
  stub provider (recall depends only on retrieval).
- **E** used the real `llama3.2:3b`, because its damage is in the answer.

Raw results are in `docs/evidence/failure/`. The baseline, `eval/baseline.json`, has
recall@5 0.941, recall@1 0.765, exact-term recall@5 0.75, citation validity 1.0 and
abstention 1.0.

| Stage | Break | recall@5 | recall@1 | Worst type | Gate |
| --- | --- | ---: | ---: | --- | --- |
| baseline | none | 0.941 | 0.765 | exact 0.75 | passed |
| A · Extraction | OCR off | 0.882 | 0.765 | exact 0.75, ordinary 0.90 | **failed** |
| B · Chunking | fixed 100-token windows, no overlap | 0.765 | 0.706 | ordinary 0.70 | **failed** |
| C · Retrieval | `TOP_K=1` | 0.735 | 0.765 | exact 0.50, ordinary 0.75 | **failed** |
| E · Source | superseded filter removed | n/a (answers) | | | |

With the stub provider, the stub "answers" whenever any passage clears the relevance floor,
so the must-abstain hostel question a01 is reported as answered in A, B and C (and a02 in
B). That is an
artefact of the stub, not of the break: with the real model a01 abstains (baseline).

## Stage A · Extraction: index the scanned PDFs without OCR

- **What we broke:** a Job ran the indexer with `pipeline.extract._ocr_page` replaced by
  `lambda path, n: None`, the same path as an image without tesseract installed. Command in
  `docs/evidence/failure/stage-a-indexer.txt`.
- **Symptom:** nothing visibly failed.
  - The Job completed (exit 0, 420 s, faster than usual because no OCR ran).
  - It stored 771 chunks instead of 877.
  - The API stayed Ready.
  - Questions about the start-up policy still got confident-looking answers, from the wrong
    documents. q09 ("Who gives final approval to a faculty member's technical start-up
    application?") retrieved annual-report
    chunks at 0.71 and 0.70, and the only document that answers it was no longer in the
    index.
  - recall@5 fell to 0.882 (q09 lost). The 2023 rules shrank from 64 chunks to 2, which
    also starves every version question of its "older version" evidence.
- **Diagnosis, as if we had not caused it:**
  1. The indexer's own log says it. There are 41 lines of
     `"page has no text layer and OCR is unavailable; page lost"`, and the `chunked` line
     for the policy reads `"pages": 8, "ocr_pages": 0, "empty_pages": 8, "chunks": 0`.
  2. A document with **0 chunks**, or `empty_pages` close to `pages`, is the number to
     alert on. Compare `chunks` per source with the previous run: the start-up policy went
     from 30 to 0.
  3. In the eval, recall@5 for ordinary questions dropped from 1.0 to 0.9, and the miss's
     top score (0.71) was lower than any correct top-1 in the baseline (at least 0.7156
     for answerable questions with a rank-1 hit).
- **Remedy:**
  - tesseract and poppler in the image (`indexer/Dockerfile`);
  - `_ocr_page()` for any page under `MIN_TEXT_CHARS`;
  - the `ocr_pages` and `empty_pages` counts in the `chunked` log line, so a lost page is
    visible.
  
  Restored by doing nothing to the live index: the break only ever wrote `rahbarbrk`.

## Stage B · Chunking: fixed 100-token windows with no overlap

- **What we broke:** a Job replaced `pipeline.chunk.chunk` with a fixed-size splitter:
  77-word windows (≈100 tokens at words × 1.3), no overlap, cut wherever the count runs
  out, ignoring headings, clauses, paragraphs and sentences. Each window is labelled with
  the section its first word sits in. `CHUNK_SIZE=100`, `CHUNK_OVERLAP=0`. The log is in
  `docs/evidence/failure/stage-b-indexer.txt`.
- **Symptom:**
  - The Job succeeded with 936 chunks and an amplification of 1.008. The cheaper storage
    looks like an improvement.
  - recall@5 fell from 0.941 to **0.765**, and ordinary questions from 1.0 to **0.70**.
    q04, q05 and q08 are lost, and e03 drops to rank 3.
  - The scores did **not** drop, which is what makes this failure nasty. q04 ("For how many
    semesters can a student freeze their admission?") has a top hit of **0.872**, about
    the same as the baseline (0.879), and its text contains the answer. But the window starts with the
    end of the previous section:

    ```
    section: 4. Registration > Restoration of Suspended Registration   (page 21)
    "that resulted in suspension and has paid all dues. Freezing of Semester 4.18 A student
     may request freezing of his/her admission for up to 2 semesters ..."
    ```

    So the answer would be cited as "Restoration of Suspended Registration": a correct
    answer with a wrong citation.
  - The next window begins mid-heading, "Dropping a Course 4.19 …", because "Adding or" was
    left in the window before. Definitions and table rows are cut the same way.
- **Diagnosis, as if we had not caused it:**
  1. In the eval, a high top-1 score with a recall miss is the fingerprint. The right text
     is found but attributed to the wrong section. Per question, `scores[0]` stayed above
     0.76 for all three lost ordinary questions.
  2. In the index, `chunking summary` reports `chunk_overlap: 0` and an amplification of
     about 1.0. Sampling a few chunks shows text that starts mid-sentence, or with the tail
     of another section. With our chunker, every chunk text starts with its own heading.
  3. In production: citation complaints ("that section doesn't say this") while the answers
     look right, and a rising share of answers whose cited section does not contain the
     answer's key terms.
- **Remedy:** structure-aware chunking (`indexer/pipeline/chunk.py`):
  - split on sections, then paragraphs and clauses, then sentences;
  - never cross a heading;
  - put the section heading at the start of each chunk;
  - carry whole-sentence overlap within a section;
  - ship 200/25, chosen by measurement (`docs/adr/0002-chunking.md`).

  The live index was never touched; the break only wrote `rahbarbrk`.

## Stage C · Retrieval: `TOP_K=1`

- **What we broke:** the api ran with `TOP_K=1` instead of 5. That is one ConfigMap value,
  the kind of change someone makes "to speed up generation".
- **Symptom:**
  - Every answer cites a single passage.
  - recall@5 fell from 0.941 to **0.735**; with one passage, recall@5 is recall@1.
  - **Exact-term questions halved, to 0.50.** e04 (the Rs. 500 rechecking fee) was at
    rank 3 and is now gone.
  - q02 and q09 were at rank 2 and are gone.
  - q07 needs two documents and can now only ever get one.
  - The worst part is that the answers stay confident. q02 ("What happens if a student's
    CGPA stays below 2.00 for three consecutive semesters?") retrieved one Grading-page chunk at **0.7768**,
    which is a high score for the wrong section. The model is handed only that.
- **Diagnosis, as if we had not caused it:**
  1. The api logs one structured line per turn
     (`docs/evidence/failure/stage-c-answered-log-q02.txt`):

     ```
     "msg": "answered", "top_k": 1, "chunk_ids": ["grading-page-html-0007"], "scores": [0.7768]
     ```

     `top_k: 1` and a one-element `chunk_ids` on every line give it away, as does the
     `api started` line, which prints `"top_k": 1` at startup.
  2. The eval shows recall@5 equal to recall@1 (0.735 against 0.765). That only happens
     when fewer than two passages come back.
  3. In production, citations per answer flatten to exactly 1, and the abstention rate
     rises on multi-part questions.
- **Remedy:** `TOP_K: "5"` in `k8s/base/configmap.yaml`. The gate catches this one: recall@5
  is more than 5 points below the baseline, so a pull request with `TOP_K=1` cannot merge.
  Restored by stopping the local api; the cluster was never changed.

## Stage E · Source: remove the superseded filter, ask a version-sensitive question

- **What we broke:** the api ran with `wants_older_version()` patched to always return
  True, so the `where={"superseded": False}` filter in `ChromaRetriever.retrieve()`
  (`api/app/retrieval/chroma.py:114`) was never applied. We asked the two version
  questions with the real model. Output in
  `docs/evidence/failure/stage-e-superseded-filter-removed.txt`.
- **Symptom:** the repealed Aug 2023 rules came back into the evidence.
  - **v02** ("Can I take a new elective course in the summer semester if I need it to
    graduate?"): the
    **top** passage was the 2023 rules, clause 6.4 (0.7684), which *allowed* one or two
    new electives. It ranked above the 2026 handbook's repeat-only rule (0.7534).
  - **v01** (withdrawal deadline): 2 of the 5 passages were from the 2023 rules. Rank 2,
    at 0.8364, was the old "last day of classes" clause.
  - The 3B model gave the current answer both times ("the last day of the makeup week";
    "No"), because the prompt tells it to prefer the newer version. But for v01 it **cited
    the 2023 document as support for the 2026 rule**. That citation passes our citation
    check, because the passage really was retrieved.
  - A student who clicks it reads the opposite rule. With a weaker model, or a question
    where the two texts look alike, the repealed rule becomes the answer. The prompt is
    a last line of defence, not a filter.
- **Diagnosis, as if we had not caused it:**
  1. Every retrieved passage carries `superseded` in its metadata, and every turn logs
     `chunk_ids`. A chunk id from `undergraduate-academic-rules-aug-2023-pdf-*` in a turn
     whose question has no version words is the signal; with the filter it can never
     happen.
  2. In the eval, v01 and v02 still pass recall (the current section is retrieved), so
     recall alone does not catch this. The number to watch is citations to a
     `superseded: true` source on questions not asking for one. It is 0 in the baseline
     and 1 here (v01).
- **Remedy:** the metadata filter, not the prompt.
  - `superseded` and `doc_version` are stored on every chunk (`indexer/pipeline/store.py`).
  - The retriever filters `superseded: False` unless the question asks for an older
    version, using the `_OLDER` pattern in `api/app/retrieval/chroma.py`.
  - We tightened `_OLDER` so that words like "earlier" alone do not pull in repealed rules.

  Restored by stopping the patched local api.

## Stages not broken

- **D · Prompt** (remove "use the supplied context").
- **F · Generation** (temperature 1.2).

We chose the four stages whose breaks can be measured with retrieval numbers, because each
real-model run of the golden set takes 20 to 25 minutes on this laptop's CPU. As the RAG
lecture says, only F is the model's fault. Our A, B, C and E all fail before the model
sees anything, and the model could not have fixed any of them.
