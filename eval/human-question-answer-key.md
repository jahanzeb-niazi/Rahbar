# Human-authored question and answer set

The eight question wordings below were supplied by Faizan Ahmed. They are kept verbatim and are classified by the requested type. Answer text is a concise expected answer for the evaluator; the cited source passages should be checked against the indexed corpus before treating this file as a final answer key.

## 1. Answerable — fee structure

**Question:** What is the fee for issuing a duplicate degree?

**Expected answer:** The currently published FAST-NUCES Fee Structure page does not list a duplicate-degree issuance fee. It lists a degree-correction fee of PKR 2,000, which is a different charge and should not be presented as the duplicate-degree fee.

**Source:** `fee-structure-page.html`, “Miscellaneous Fees” (page 1). The duplicate-degree amount remains unresolved in the supplied source. The question is marked answerable in Faizan’s source notes, but the current page does not support a numeric answer.

## 2. Answerable — grading

**Question:** How many grade points is a C+ worth in BS programs?

**Expected answer:** A C+ is worth 2.33 grade points in BBA and BS programs.

**Source:** `grading-page.html`, “Letter Code Interpretation” → “Letter grades for BBA & BS programs” (page 1).

## 3. Answerable — generative AI

**Question:** Which uses of generative AI are students allowed?

**Expected answer:** Uses can include preparatory research, exploring or summarizing ideas, taking notes, organizing work, planning presentations, formatting references, proofreading, and self-assessment. Students must follow the instructor’s assessment-specific rules, use trusted sources to verify facts, and must not submit AI-generated assessment work as their own or upload sensitive or university material to unsupported tools.

**Source:** `student-handbook-jun-2026.pdf`, “Policy on Generative AI Based Tools” and its acceptable-use guidance. The instructor’s assessment instructions determine whether and how AI may be used for a particular assessment.

## 4. Answerable — faculty start-up policy

**Question:** Who reviews a faculty member's start-up application before final approval?

**Expected answer:** The exact reviewing body and approval sequence must be transcribed from the start-up policy before this answer is finalized. The policy PDF was not available as extracted text in the local workspace, so this answer key intentionally does not guess a committee name.

**Source:** `faculty-entrepreneurship-and-technical-start-ups-policy.pdf`, application/review procedure (page and section to confirm from the source PDF).

## 5. Hard — two annual reports

**Question:** How did the number of graduates change between 2019-20 and 2023-24?

**Expected answer:** The reports’ university-wide Graduation Summary totals increased from 2,410 in 2019-20 to 4,016 in 2023-24, a rise of 1,606 graduates. These totals combine the undergraduate, master’s, and PhD summary tables.

**Sources:** `annual-report-2019-20.pdf`, “Graduation Summary” (printed page 19 and following tables); `annual-report-2023-24.pdf`, “Graduation Summary” (printed page 19). Both source passages are required.

## 6. Hard — paraphrase, academic warning

**Question:** My grades have been poor for several terms in a row. Can the university end my admission?

**Expected answer:** Yes. Under the 2026 rules, a student’s admission is closed when the warning count reaches three. The warning count increases after a semester below the program’s minimum CGPA and resets when the required CGPA is reached.

**Source:** `academic-rules-2026.md`, “5. Academic Warning/Probation” (page and exact section label to verify in the extracted corpus).

## 7. Hard — paraphrase, attendance and illness

**Question:** I was ill and missed many classes. Can I still sit the final exam?

**Expected answer:** The 2026 rules require at least 80% attendance to sit a course’s final examination. A genuine medical reason may support an exception to the absence allowance, subject to the handbook’s approval/documentation conditions; if the minimum is not met and no exception is approved, the student is not eligible and may receive FA.

**Source:** `academic-rules-2026.md`, “1. Attendance” (attendance clause and exception conditions; page and clause number to verify in the extracted corpus).

## 8. Unanswerable — transport

**Question:** What are the university bus routes and the monthly transport charge?

**Expected answer:** The provided corpus does not contain a source that specifies university bus routes or a monthly transport charge. The assistant should abstain and say the documents do not provide this information.

**Source:** No transport document is included in the indexed corpus; `must_abstain: true`.

## Evaluation status

These questions are human-authored because Faizan supplied their exact wording. The earlier entries in `human-question-drafts.jsonl` remain AI-drafted and are not relabelled. Before adding numeric answer expectations to the main golden set, verify Q1 and Q4 against the actual source documents, and verify the PDF page/section metadata for Q3, Q6, and Q7 against the indexed extraction. Evaluation metrics captured before this set was added do not measure these eight questions.
