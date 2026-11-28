# Group review checklist for the synthetic golden questions

The separate `human-question-answer-key.md` file contains eight question wordings
authored by Faizan Ahmed. Those are not the synthetic rows below, and the older
AI-drafted candidates in `human-question-drafts.jsonl` remain labelled as AI drafts.

The questions below are currently labelled synthetic in `golden.jsonl`. A group member
should independently compare each question with its cited corpus passage, verify the
expected answer and relevant section, then record their initials and date. Do not mark a
row reviewed before a person has checked it.

| ID | Expected answer | Source passage to inspect | Reviewer initials/date | Correct? / notes |
| --- | --- | --- | --- | --- |
| a1 | 80 percent | academic-rules-2026.md, 1. Attendance |  |  |
| a2 | Documented medical reasons | academic-rules-2026.md, 1. Attendance |  |  |
| a3 | FA | academic-rules-2026.md, 1. Attendance |  |  |
| a4 | Below 2.00 CGPA | academic-rules-2026.md, 2. Academic warning |  |  |
| a6 | Any course may be repeated | academic-rules-2026.md, 3. Repeating a course |  |  |
| a8 | PKR 10,000 per credit hour | fees-2026.md, 1. Tuition |  |  |
| a10 | PKR 3,000 | fees-2026.md, 2. Other charges |  |  |
| a13 | Full tuition refund within the first 10 days | fees-2026.md, 3. Refunds |  |  |

After review, preserve the synthetic origin label. Human review and human authorship are
different claims. The human-authored set is present, but its answer key has source gaps
noted in `human-question-answer-key.md`, and it has not yet been added to a rerun of the
evaluation suite. The eight entries in `human-question-drafts.jsonl` remain AI-drafted
candidates and do not count as human-authored questions.
