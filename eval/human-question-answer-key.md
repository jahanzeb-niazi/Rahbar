# Human-authored question and answer set

Faizan Ahmed supplied the eight question wordings verbatim. Answers and source locations below were checked against the documents fetched by `corpus/fetch.py`. The current Kubernetes A/B fixture jobs use synthetic documents and do not index most of these official sources; these rows have not yet been evaluated live against the official corpus.

## 1. Answerable in intent — fee structure

**Question:** What is the fee for issuing a duplicate degree?

**Expected answer:** The supplied FAST-NUCES fee page does not state a duplicate-degree issuance fee, so the assistant should abstain. The page lists a degree-correction fee of PKR 2,000, which is a different charge.

**Source:** `fee-structure-page.html`, “Miscellaneous Fees” (page 1). Scored as unanswerable because the requested amount is absent.

## 2. Answerable — grading

**Question:** How many grade points is a C+ worth in BS programs?

**Expected answer:** A C+ is worth 2.33 grade points in BBA and BS programs.

**Source:** `grading-page.html`, “Letter grades for BBA & BS programs” (page 1).

## 3. Answerable — generative AI

**Question:** Which uses of generative AI are students allowed?

**Expected answer:** Permitted uses include preparatory research, exploring or summarizing ideas, taking notes, organizing work, planning presentations, formatting references, proofreading, and self-assessment. Students must follow course instructions, verify facts against trusted sources, and must not submit AI-generated assessment work as their own or upload sensitive/university material to unsupported tools.

**Source:** `student-handbook-jun-2026.pdf`, “XII. Policy on Generative AI Based Tools / 4. Acceptable Uses of Generative AI Tools” (PDF pages 51–52).

## 4. Answerable — faculty start-up policy

**Question:** Who reviews a faculty member's start-up application before final approval?

**Expected answer:** The Campus Director comments on and recommends the application and forwards it to ORIC. ORIC evaluates and recommends it; the Rector gives final approval.

**Source:** `faculty-entrepreneurship-and-technical-start-ups-policy.pdf`, section 7, “Procedure for evaluating the application” (PDF page 2).

## 5. Hard — two annual reports

**Question:** How did the number of graduates change between 2019-20 and 2023-24?

**Expected answer:** The university-wide Graduation Summary total rose from 2,410 (2019–20) to 4,016 (2023–24), an increase of 1,606 graduates. The totals combine undergraduate, master’s, and PhD counts.

**Sources:** `annual-report-2019-20.pdf`, “Graduation Summary” (PDF page 20); `annual-report-2023-24.pdf`, “Graduation Summary” (PDF page 19). Both are needed.

## 6. Hard — paraphrase, academic warning

**Question:** My grades have been poor for several terms in a row. Can the university end my admission?

**Expected answer:** Yes. If CGPA remains below 2.00 for three consecutive semesters, the warning count reaches three and admission is automatically closed. It may reset if the student restores the required CGPA after an earlier warning.

**Source:** `academic-rules-handbook-jun-2026.pdf`, section 5, “Academic Assessment / Academic Warning/Probation” (PDF page 24; printed page 18).

## 7. Hard — paraphrase, attendance and illness

**Question:** I was ill and missed many classes. Can I still sit the final exam?

**Expected answer:** The rules require 100% attendance, but the Head of Department may condone up to 20% absence for genuine reasons such as illness. If attendance requirements are not met, the student is ineligible for the final and receives F/A.

**Source:** `academic-rules-handbook-jun-2026.pdf`, section 1, “Attendance Requirements,” clauses 1.21–1.22 (PDF page 10; printed page 4).

## 8. Unanswerable — transport

**Question:** What are the university bus routes and the monthly transport charge?

**Expected answer:** The supplied corpus has no source for bus routes or monthly transport charges. The assistant should abstain.

**Source:** No transport document is included; `must_abstain: true`.

## Evaluation status

All eight rows have `origin: human` in `eval/golden.jsonl`; the earlier rows in `human-question-drafts.jsonl` remain AI-drafted. Q1 is scored as must-abstain because the current source lacks the requested fee. The answer expectations and locations are verified, but the eight rows have not been rerun. Index the official sources in the live Kubernetes collection before claiming the app answered them correctly; the current A/B fixture batches do not contain most of these files.
