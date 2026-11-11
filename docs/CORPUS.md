# Corpus

Source: **FAST-NUCES public website** (nu.edu.pk), public pages only · Documents: **9**
(7 PDFs + 2 HTML pages) · Pages: **279 PDF pages** plus 2 web pages.

The documents are not committed (the repository may be public and we do not own them).
`corpus/MANIFEST.md` records each URL, size and SHA-256, `corpus/sources.yaml` lists
them with their `doc_version` and `superseded` flags, and `corpus/fetch.py` downloads them
one at a time with a pause between requests. The indexer Job runs
`fetch.py --frozen` and refuses to index a file whose checksum differs from the manifest.
All nine downloaded and matched on 8 November 2026, including the Aug 2023 rules that the
handout warned might not open. Both HTML pages returned identical bytes on a second fetch,
so their checksums are stable.

| Document | File | Version | Superseded | Pages | Text-layer pages |
| --- | --- | --- | --- | ---: | ---: |
| Undergraduate Academic Rules (Aug 2023) | `undergraduate-academic-rules-aug-2023.pdf` | 2023-08 | **yes** | 26 | 2 |
| Academic Rules Handbook (Jun 2026) | `academic-rules-handbook-jun-2026.pdf` | 2026-06 | no | 58 | 53 |
| Prospectus 2026: Academic Rules and Regulations | `prospectus-2026-academic-rules-and-regulations.pdf` | 2026 | no | 5 | 5 |
| Student Handbook (Jun 2026) | `student-handbook-jun-2026.pdf` | 2026-06 | no | 64 | 60 |
| Annual Report 2019-20 | `annual-report-2019-20.pdf` | 2019-20 | no | 33 | 33 |
| Annual Report 2023-24 | `annual-report-2023-24.pdf` | 2023-24 | no | 85 | 85 |
| Fee Structure page | `fee-structure-page.html` | 2026-27 | no | web | n/a |
| Grading page | `grading-page.html` | 2026 | no | web | n/a |
| Faculty Entrepreneurship and Technical Start-ups Policy | `faculty-entrepreneurship-and-technical-start-ups-policy.pdf` | 2022-05 | no | 8 | **0** |

"Text-layer pages" counts pages where pypdf extracts at least 20 characters. The handbooks'
missing pages are their image-only covers.

## The seven properties

| # | Required property | Document(s) that provide it | Evidence or notes |
| --- | --- | --- | --- |
| 1 | At least 6 documents, 40 pages | All nine | 9 documents, 279 PDF pages plus 2 web pages; every one public (manifest URLs) |
| 2 | Two versions of one policy | **Undergraduate Academic Rules Aug 2023** (superseded) and **Academic Rules Handbook Jun 2026** (current). The Prospectus 2026 rules are a third rendering of the same policy with different clause numbers | `superseded: true` and `doc_version: "2023-08"` in `corpus/sources.yaml` become chunk metadata, and the retriever filters `superseded: false` unless the question asks about an older version. Real differences we found by reading both: the withdrawal deadline (clause 4.25) moved from "the last day of classes" (2023) to "the last day of the makeup week" (2026), and summer semester new courses (2023 clause 6.4 allowed one or two new electives to graduate; 2026 clause 6.2 allows repeat courses only). Golden questions v01 and v02 |
| 3 | Scanned, image-only PDF | **Faculty Entrepreneurship and Technical Start-ups Policy**, and also most of the **2023 rules** | `pdffonts` is not available on our Windows machines, so we checked the same thing with pypdf: the policy has **0 font resources on all 8 pages** and no extractable text. The 2023 rules have text on only 2 of 26 pages; the rest are drawn as vector outlines with no text layer. Both are OCR'd by the indexer (tesseract at 300 dpi), see docs/PIPELINE.md |
| 4 | A table with real information | **Fee Structure page** (tuition per credit hour, miscellaneous fees, refund timeline), **Grading page** (letter grade to grade points per programme), **Annual Reports** (applications, faculty and graduates by campus) | HTML tables become Markdown rows (`\| BBA / BS \| Rs. 12,000 \|`). Golden questions q06, e02, e03, e04 depend on table cells |
| 5 | Long definitions | **Academic Rules Handbook** and **Student Handbook**: the Generative AI policy (sections 1 to 12, multi-paragraph numbered sub-sections) | The "Acceptable / Unacceptable Uses" and "Generative AI and Assessments" sections run across several pages; a fixed-size chunker cuts them mid-list. Golden question q07 |
| 6 | A deliberately absent topic | **Hostel rules**: we left out the prospectus's *Transport and Hostel Facilities* PDF | A student would plausibly ask how to apply for a hostel room, the hostel fee, or curfew times. The corpus only says hostels *exist* on some campuses (Student Handbook p. 45, Annual Reports p. 6 and p. 10), which makes this a good abstention test: there is nearby text, but none of it answers the question. Golden questions a01 and a02 must abstain |
| 7 | Exact-term content | Handbook clause numbers (1.21, 4.25, 5.4, 6.6), the CGPA threshold 2.00, fees (Rs. 12,000 per credit hour, Rs. 500 rechecking), grade points (B- = 2.67) | Golden questions e01 to e04. Embeddings blur these: "clause 1.21" and "clause 1.12" are near neighbours in vector space |

## Other real-world traps in this corpus
- The **Prospectus** numbers the same rules differently (attendance is clause 1 there and
  1.21 in the handbook), so a question that names a clause number is ambiguous across
  documents.
- The **Annual Reports** are versions over time (2019-20 vs 2023-24) but neither is
  superseded: each is the correct answer for its own year. They are marked
  `superseded: false`, and the year in the question decides which one is relevant.
- The **2026 handbook** PDF is a print layout that carries the facing page's text outside
  the visible page area; extraction crops to the page box (docs/PIPELINE.md).
