# ADR 0002: Structure-aware chunking at 200 tokens with 25 overlap

## Status
Accepted · 8 November 2026

## Context
Our corpus is mostly numbered rules ("5.4 Minimum CGPA required to avoid academic warning
is 2.00"), fee and grade tables, and a long Generative AI policy with multi-paragraph
sub-sections. A fixed-size chunker would cut a clause from its heading, split a table
row from its column header, and break definitions in half (failure mode B). Every chunk
also has to carry a `section` for citations and for recall@k.

## Decision
`indexer/pipeline/chunk.py` splits top-down, as section 3.1 asks:

1. **Sections.** A heading starts a new section, and a chunk never crosses one. Headings are
   Markdown headings (HTML pages and fixtures), numbered chapter titles
   ("4. Registration", "7. Procedure for evaluating the application"), Roman-numeral parts
   ("III - DISCIPLINARY CONDUCT") and short title-case lines ("Attendance Requirements").
   Sub-headings are recorded under their chapter, for example
   `5. Academic Assessment > Academic Warning/Probation`.
2. **Paragraphs.** A blank line, a numbered clause ("1.21 Students are…"), a lettered item
   ("a) …") or a table row starts a new unit.
3. **Sentences.** Only a paragraph larger than the target size is split into sentences.

Units are packed up to the target size. The next chunk in the same section starts with
the previous chunk's last whole sentences, up to the overlap. Each chunk's text begins
with its section heading. Sizes are **approximate tokens = words x 1.3**, which needs no
tokenizer dependency.

**Shipped: `CHUNK_SIZE=200`, `CHUNK_OVERLAP=25`** (ConfigMap).

## Measurements
Each setting was a full re-index of the real corpus (the same Job, the same OCR), then the
19-question golden set (`eval/golden.yaml`, written before tuning) through the Ingress.
Generation was set to the stub for these runs, because recall depends only on retrieval.
The raw results are in `docs/evidence/chunking/`.

| Size (tokens) | Overlap (tokens) | Chunks stored | Storage amplification | recall@1 | recall@3 | recall@5 | MRR |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| **200** | **25** | 877 | 1.071 | **0.765** | 0.941 | 0.941 | **0.843** |
| 400 | 50 | 679 | 1.055 | 0.706 | 0.941 | 0.941 | 0.824 |
| 800 | 100 | 615 | 1.033 | 0.647 | 0.941 | 0.941 | 0.794 |

Storage amplification is stored tokens divided by original tokens (93,318 original
tokens after cleaning; the indexer logs it as `chunking summary`).

## Why 200 / 25
- **recall@5 does not separate the settings.** All three find 16 of 17 answerable
  questions in the top 5. The only miss in every setting is e01 ("What does clause 1.21
  require?"): an exact-term question, discussed in ENGINEERING-NOTES question 5.
- **Ranking does.** Smaller chunks put the right section first more often: recall@1 goes
  from 0.647 to 0.765, MRR from 0.794 to 0.843. A larger chunk holds more unrelated
  clauses of the same section. Its vector is an average over all of them, so it scores
  lower against a question about one clause: q10 and v02 are rank 1 at 200 tokens but
  rank 2 at 800. One question goes the other way. e04 (the rechecking fee, a row in the
  miscellaneous-fees table) is rank 3 at 200 and rank 2 at 800, because a small chunk
  holds part of the table without its heading context. Per-question ranks are in
  `docs/evidence/chunking/`.
- **The cost is small.** Because chunks never cross a section and most sections are short,
  overlap rarely applies: amplification is 1.07 at 200/25, below the lecture's 150/120 =
  1.25.
- **It suits the laptop.** Five 200-token chunks make a prompt of about 1,500 tokens instead
  of about 4,500 with 800, so CPU generation is faster, and it fits the 4,096-token context
  that this 16 GB laptop can afford (see the Ollama provider's `NUM_CTX`).

## Options considered
- **Fixed-size windows**: rejected without measuring the full corpus; failure mode B in
  docs/FAILURE-ANALYSIS.md shows what it does.
- **Larger chunks for more context per passage**: 800/100 is measured above. It has fewer
  chunks but worse ranking, and a prompt three times longer.

## Consequences
- More chunks (877) means a bigger index and slightly slower indexing. The re-index time
  is dominated by OCR, so the difference is small.
- A short section is one chunk regardless of the setting, so the setting matters most for
  the long Generative AI policy sections and the annual reports.
- Watch recall by type in `eval/results.json` after any change to `chunk.py`: the CI gate
  fails if recall@5 drops more than 5 points below the baseline.
