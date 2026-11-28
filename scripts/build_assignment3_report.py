#!/usr/bin/env python3
"""Build the Assignment 03 report and its evidence appendix from captured runs."""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch, mm
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    Image,
    KeepTogether,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)


ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
EVIDENCE = DOCS / "evidence" / "assignment3"
PDF_PATH = DOCS / "Assignment-03-report.pdf"
SUMMARY_PATH = ROOT / "eval" / "results" / "assignment3-summary.json"

INK = colors.HexColor("#172235")
BLUE = colors.HexColor("#234D78")
PALE = colors.HexColor("#EAF1F7")
GRID = colors.HexColor("#CAD4DF")
MUTED = colors.HexColor("#586678")
AMBER = colors.HexColor("#FFF4D6")
GREEN = colors.HexColor("#E7F4EB")
RED = colors.HexColor("#FBE9E7")


def styles():
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "TitleCustom", parent=base["Title"], fontName="Helvetica-Bold",
            fontSize=24, leading=29, textColor=INK, alignment=TA_CENTER,
            spaceAfter=8,
        ),
        "subtitle": ParagraphStyle(
            "SubtitleCustom", parent=base["Normal"], fontName="Helvetica",
            fontSize=11, leading=15, textColor=MUTED, alignment=TA_CENTER,
            spaceAfter=7,
        ),
        "h1": ParagraphStyle(
            "H1Custom", parent=base["Heading1"], fontName="Helvetica-Bold",
            fontSize=16, leading=19, textColor=BLUE, spaceBefore=2, spaceAfter=7,
        ),
        "h2": ParagraphStyle(
            "H2Custom", parent=base["Heading2"], fontName="Helvetica-Bold",
            fontSize=10.5, leading=13, textColor=INK, spaceBefore=5, spaceAfter=3,
        ),
        "body": ParagraphStyle(
            "BodyCustom", parent=base["BodyText"], fontName="Helvetica",
            fontSize=8.35, leading=11.2, textColor=INK, spaceAfter=4,
        ),
        "small": ParagraphStyle(
            "SmallCustom", parent=base["BodyText"], fontName="Helvetica",
            fontSize=7.25, leading=9.2, textColor=INK, spaceAfter=2,
        ),
        "tiny": ParagraphStyle(
            "TinyCustom", parent=base["BodyText"], fontName="Helvetica",
            fontSize=6.45, leading=8, textColor=INK, spaceAfter=1,
        ),
        "cell": ParagraphStyle(
            "CellCustom", parent=base["BodyText"], fontName="Helvetica",
            fontSize=6.9, leading=8.45, textColor=INK, spaceAfter=0,
        ),
        "cellbold": ParagraphStyle(
            "CellBoldCustom", parent=base["BodyText"], fontName="Helvetica-Bold",
            fontSize=6.9, leading=8.45, textColor=INK, spaceAfter=0,
        ),
        "note": ParagraphStyle(
            "NoteCustom", parent=base["BodyText"], fontName="Helvetica",
            fontSize=7.5, leading=9.5, textColor=INK, leftIndent=7,
            rightIndent=7, spaceBefore=2, spaceAfter=3,
        ),
        "caption": ParagraphStyle(
            "CaptionCustom", parent=base["BodyText"], fontName="Helvetica",
            fontSize=8, leading=10, textColor=MUTED, alignment=TA_CENTER,
        ),
        "covermeta": ParagraphStyle(
            "CoverMeta", parent=base["BodyText"], fontName="Helvetica",
            fontSize=11, leading=16, textColor=INK, alignment=TA_CENTER,
        ),
    }


S = styles()


def p(text: str, style: str = "body") -> Paragraph:
    return Paragraph(text, S[style])


def table(rows, widths, header=True, font="cell", row_bgs=None, repeat=1):
    converted = []
    for ri, row in enumerate(rows):
        converted.append([
            item if isinstance(item, (Paragraph, Image)) else p(str(item), "cellbold" if header and ri == 0 else font)
            for item in row
        ])
    t = Table(converted, colWidths=widths, repeatRows=repeat if header else 0, hAlign="LEFT")
    commands = [
        ("GRID", (0, 0), (-1, -1), 0.35, GRID),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]
    if header:
        commands.extend([
            ("BACKGROUND", (0, 0), (-1, 0), PALE),
            ("TEXTCOLOR", (0, 0), (-1, 0), BLUE),
        ])
    if row_bgs:
        for row_index, background in row_bgs.items():
            commands.append(("BACKGROUND", (0, row_index), (-1, row_index), background))
    t.setStyle(TableStyle(commands))
    return t


def note(text: str, color=PALE):
    t = Table([[p(text, "note")]], colWidths=[174 * mm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), color),
        ("BOX", (0, 0), (-1, -1), 0.45, GRID),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
    ]))
    return t


def header_footer(canvas, doc):
    canvas.saveState()
    w, h = A4
    canvas.setStrokeColor(GRID)
    canvas.setLineWidth(0.5)
    canvas.line(18 * mm, h - 14 * mm, w - 18 * mm, h - 14 * mm)
    canvas.setFont("Helvetica-Bold", 7)
    canvas.setFillColor(BLUE)
    canvas.drawString(18 * mm, h - 11.2 * mm, "RAHBAR  |  ASSIGNMENT 03  |  RAGOPS")
    canvas.setFont("Helvetica", 7)
    canvas.setFillColor(MUTED)
    canvas.drawString(18 * mm, 9 * mm, "Faizan Ahmed (24I-3145)  |  Jahanzeb Arfan (24P-3079)")
    canvas.drawRightString(w - 18 * mm, 9 * mm, f"{doc.page}")
    canvas.restoreState()


class ReportDoc(BaseDocTemplate):
    def __init__(self, path):
        super().__init__(
            str(path), pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm,
            topMargin=19 * mm, bottomMargin=16 * mm,
            title="RAHBAR - Assignment 03 RAGOps Report",
            author="Faizan Ahmed; Jahanzeb Arfan",
        )
        frame = Frame(
            self.leftMargin, self.bottomMargin, self.width, self.height,
            leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0,
            id="normal",
        )
        self.addPageTemplates(PageTemplate(id="main", frames=[frame], onPage=header_footer))


def screenshot_page(code: str, caption: str, filename: str):
    path = EVIDENCE / filename
    img = Image(str(path))
    max_w = 174 * mm
    max_h = 116 * mm
    scale = min(max_w / img.imageWidth, max_h / img.imageHeight)
    img.drawWidth = img.imageWidth * scale
    img.drawHeight = img.imageHeight * scale
    return [
        p(f"Appendix {code}", "h1"),
        p(caption, "caption"),
        Spacer(1, 5 * mm),
        img,
        Spacer(1, 3 * mm),
        p(f"Evidence file: docs/evidence/assignment3/{filename}", "tiny"),
        PageBreak(),
    ]


def build_summary():
    data = {
        "metadata": {
            "project": "RAHBAR Assignment 03 RAGOps",
            "date": "2026-11-28",
            "cluster": "Minikube v1.37.0 on Docker Desktop, Kubernetes v1.36.1 client",
            "llm": "llama3.2:3b via Ollama 0.40.18",
            "embedding_model": "nomic-embed-text",
            "provenance": "Values transcribed from the captured Kubernetes Job logs and outputs; raw timestamped Job result JSON remained on the cluster PVC.",
        },
        "baseline": {
            "paraphrase_cosine": 0.7746, "unrelated_cosine": 0.5357, "cosine_gap": 0.2389,
            "embedding_seconds_per_text": [0.0458, 0.0690], "embedding_max_difference": 0.0,
            "recall_at_3": [0.95, 0.95], "recall_at_5": [1.0, 1.0],
            "mrr": [0.9625, 0.9625], "noisy_mrr": [0.96, 0.96],
            "ndcg_at_5": [0.9715, 0.9715], "noisy_ndcg_at_5": [0.9693, 0.9693],
            "faithfulness_proxy": [0.65, 0.65], "abstention_correctness": [1.0, 1.0],
            "citation_validity": [1.0, 1.0], "latency_p50_seconds": [15.5027, 13.2613],
            "latency_p95_seconds": [38.1216, 34.6010],
        },
        "candidate_top_k_6": {
            "recall_at_3": [0.95, 0.95], "recall_at_5": [1.0, 1.0],
            "mrr": [0.9625, 0.9625], "ndcg_at_5": [0.9715, 0.9715],
            "faithfulness_proxy": [0.65, 0.65], "abstention_correctness": [1.0, 1.0],
            "citation_validity": [1.0, 1.0], "latency_p50_seconds": [11.5763, 12.7173],
            "latency_p95_seconds": [30.8577, 31.2957], "gate": "pass",
        },
        "negative_control_top_k_1": {
            "recall_at_3": [0.9, 0.9], "recall_at_5": [0.9, 0.9],
            "faithfulness_proxy": [0.7, 0.7], "abstention_correctness": [1.0, 1.0],
            "citation_validity": [1.0, 1.0], "latency_p95_seconds": [15.5386, 15.7648],
            "gate": "fail: recall_at_5 drop 0.10 exceeded 0.02",
        },
        "drift_same_golden": {
            "recall_at_3": [0.4, 0.4], "recall_at_5": [0.4, 0.4], "mrr": [0.4, 0.4],
            "ndcg_at_5": [0.4, 0.4], "faithfulness_proxy": [0.35, 0.35],
            "abstention_correctness": [1.0, 1.0], "citation_validity": [1.0, 1.0],
        },
        "drift_updated_golden": {
            "recall_at_3": [0.9524, 0.9524], "recall_at_5": [1.0, 1.0],
            "mrr": [0.9643, 0.9643], "ndcg_at_5": [0.9729, 0.9729],
            "faithfulness_proxy": [0.6667, 0.6667], "abstention_correctness": [1.0, 1.0],
            "citation_validity": [1.0, 1.0],
        },
        "coverage": {"before_percent": 47.5, "after_percent": 62.5, "threshold_percent": 85.0,
                     "live_queries": 40, "new_questions_added": 6},
        "verification_batch_b": {
            "documents_seen": 15, "indexed": 8, "archived": 2, "quarantined": 5,
            "chunks_embedded": 10, "verification_embeddings": 8,
            "quarantine_reasons": {
                "exact_duplicates": 2, "near_duplicate": 1, "truncated_incomplete": 1,
                "missing_title": 1,
            },
        },
        "incremental_update": {
            "unchanged_batch_a_chunks_embedded": 0,
            "deleted_fees_chunks_remaining": 0,
            "restore_2026_chunks_embedded": 3,
        },
        "evidence_gaps": [
            "No screenshot of the unchanged Batch A repeat; result was previously shared in chat.",
            "No screenshot of kubectl get all,pvc,configmap,cronjob,job; provided status screenshot shows deployments and pods.",
            "No post-rollback trace screenshot; trace JSONL is retained, and rollback status is shown separately.",
            "No measured per-pod resource peak during Job execution; report lists configured requests/limits and one Docker host snapshot.",
            "All current golden questions are labelled synthetic; the required eight hand-authored questions and human review are not evidenced.",
            "Coverage improved but remained below the configured 85 percent target.",
        ],
    }
    SUMMARY_PATH.parent.mkdir(parents=True, exist_ok=True)
    SUMMARY_PATH.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return data


def build():
    build_summary()
    story = []
    W = 174 * mm

    # Main report page 1: cover and executive summary.
    story += [Spacer(1, 15 * mm), p("RAHBAR", "title"),
              p("Assignment 03 - RAGOps on Kubernetes", "subtitle"),
              p("Software Construction and Development | CS4032 | Fall 2026", "subtitle"),
              Spacer(1, 7 * mm),
              p("Group members", "h2"),
              table([
                  ["Member", "Roll number", "Assignment 03 contribution"],
                  ["Faizan Ahmed", "24I-3145", "Kubernetes runs, evaluation experiments, evidence capture, Windows PowerShell runbook fixes, report preparation."],
                  ["Jahanzeb Arfan", "24P-3079", "RAHBAR Assignment 02 system supplied as the starting point; specific Assignment 03 task split was not provided for this report."],
              ], [33 * mm, 28 * mm, 113 * mm]),
              Spacer(1, 4 * mm),
              p("Executive summary", "h2"),
              p("This work adds a Kubernetes RAGOps loop to the existing RAHBAR system: ingestion verification, incremental index updates, offline evaluation, a gated top-k candidate, per-query trace records, and live query coverage checks. The local Minikube demo ran with Ollama using llama3.2:3b for generation and nomic-embed-text for embeddings. The top-k=6 candidate passed the configured quality gate on the baseline snapshot; the top-k=1 negative control failed recall@5. After Batch B changed the active policy, the old golden labels caused retrieval scores to fall; an updated golden set restored the measured retrieval scores. Coverage improved from 47.5% to 62.5%, but did not reach the 85% target."),
              note("Interpret results with the stated evidence limits: run values below are transcribed from Kubernetes Job logs and screenshots. The raw timestamped Job JSON files were not copied from the PVC. No numbers are invented to fill missing measurements.", AMBER),
              p("Implementation snapshot", "h2"),
              p("Repository: https://github.com/jahanzeb-niazi/Rahbar (Assignment 03 branch). The serving namespace is rahbar. At capture, the live API Deployment was 3/3 ready; api-candidate was 1/1 ready; Chroma, Redis and UI were Running. See Appendix F1."),
              p("Report date: 28 November 2026. Main report: 8 pages; evidence appendix follows.", "small"),
              PageBreak()]

    # Page 2: lifecycle mapping and A1.
    story += [p("1. RAGOps lifecycle and verification", "h1"),
              p("The implementation follows the paper's paired software and data lifecycles. The indexer is the only vector-store writer; API Deployments read published collections. The mapping below records implementation and remaining evidence gaps.")]
    lifecycle = [
        ["Figure 3 stage", "Implementation and file", "Run evidence / gap"],
        ["Ingest", "Kubernetes Job; eval/ingest_job.py; indexer/pipeline/run.py", "Batch A and Batch B jobs completed."],
        ["Verify", "indexer/pipeline/verified.py: quality, completeness, recency, uniqueness", "Batch B report logged per-document checks and disposition."],
        ["Update data lake", "PVC ragops; raw input, quarantine, archive, reports", "Two exact duplicates, one near duplicate, one truncated file and one missing-title file quarantined."],
        ["Update retrieval sources", "indexer/pipeline/store.py: generation pointer and per-document counts", "Superseded versions archived; 2026 rules restored after 2027 became active."],
        ["Offline testing", "eval/assignment3.py: module, retrieval and answer metrics; two runs", "Baseline and candidate results captured as terminal screenshots."],
        ["Live testing", "api-candidate Deployment/Service; scripts/ragops.ps1 release", "top-k=6 gate passed; top-k=1 failed; bad live rollout was undone."],
        ["Check coverage", "eval/assignment3.py coverage; live.jsonl", "40 queries; coverage rose 47.5% to 62.5%, below 85%."],
    ]
    story += [table(lifecycle, [31 * mm, 70 * mm, 73 * mm]),
              Spacer(1, 3 * mm), p("Batch B verification", "h2"),
              p("The captured report lists 15 document records: 8 indexed, 2 archived and 5 quarantined. It embedded 10 chunks and 8 verification embeddings. Exact duplicates were rejected by hash; the near duplicate scored 0.9999 and was quarantined. The truncated document failed completeness; the missing-title document failed metadata completeness. The newer 2027 academic rules were indexed and the 2023/2026 editions archived. The injected orientation file was accepted as data, with its instruction-like line removed at query time."),
              p("Incremental update evidence", "h2"),
              p("The unchanged Batch A rerun previously shared in chat reported chunks_embedded=0 and verification_embeddings=0. The deletion run reported zero remaining fee chunks; restore indexed three chunks and made academic-rules 2026 active again. A screenshot of the unchanged rerun and a one-file replacement run were not supplied, so those two demonstrations are not fully evidenced in the appendix."),
              PageBreak()]

    # Page 3: A2 metrics.
    story += [p("2. Data update results", "h1"),
              p("The PVC-backed lake keeps original inputs, per-run verification reports, archived versions and quarantined files. A blue/green collection pointer publishes accepted content. The tests below show that deletion and restore operations affected the intended document IDs."),
              table([
                  ["Operation", "Observed output", "Interpretation"],
                  ["Batch A initial", "7 chunks embedded: academic-rules 4, fees 3", "Baseline collection seeded."],
                  ["Batch A repeat", "0 chunks embedded; 0 verification embeddings", "Idempotent rerun on unchanged input; log was supplied in chat, but no appendix screenshot."],
                  ["Delete fees", "chunks_embedded=0; fees count=0", "No fee chunks remained in the serving collection after deletion."],
                  ["Restore 2026 rules", "3 chunks embedded; 2026 indexed, 2027 archived", "Archived version restored with an explicit version override."],
                  ["Batch B", "13 accepted chunks in candidate collection; 10 newly embedded", "Existing vectors reused; new content appended after checks."],
              ], [32 * mm, 50 * mm, 92 * mm]),
              Spacer(1, 3 * mm), p("Quality choices and data limits", "h2"),
              p("Quality rejects empty or unreadable text; completeness requires title/source/version/page metadata and a matching end marker where configured; recency archives superseded versions; uniqueness checks hashes and embedding similarity. The near-duplicate cutoff is 0.96, so the observed 0.9999 pair was quarantined. The check cannot prove that a syntactically complete document is semantically complete when the source has no trusted checksum or terminator; source-side hashes and expected lengths would reduce that risk."),
              p("A one-document replacement was not separately captured. The deletion and restore screenshots show per-document counts but do not replace that required test. Likewise, the repeated Batch A output proves no-op behavior in the supplied log, but the screenshot appendix does not contain that terminal run."),
              p("Evidence: Appendix A1 shows Batch B's verification report; A2 shows deletion and archive restoration. The unchanged-run result was provided as text during the session.", "small"),
              PageBreak()]

    # Page 4: B.
    story += [p("3. Offline evaluation (Part B)", "h1"),
              p("The suite records module, retrieval and answer-level measurements twice with seed 42. eval/golden.jsonl contains 25 questions and labels all 25 synthetic; eval/live.jsonl contains 40 queries. The assignment asks for at least eight hand-authored questions and human review of eight synthetic questions. Those contributions are not evidenced in the current files, so the question-origin requirement remains open."),
              table([
                  ["Level / metric", "Run 1", "Run 2", "Reading"],
                  ["Embedding paraphrase cosine", "0.7746", "0.7746", "Mean positive-pair similarity."],
                  ["Embedding unrelated cosine", "0.5357", "0.5357", "Mean unrelated-pair similarity."],
                  ["Cosine gap", "0.2389", "0.2389", "Positive pairs are separated from unrelated pairs."],
                  ["Embedding seconds / text", "0.0458", "0.0690", "Variation +0.0232 s; CPU/model load can vary."],
                  ["Max embedding difference", "0.0000", "0.0000", "Exact deterministic repeat in this run."],
                  ["Recall@3 / noisy", "0.9500", "0.9500", "No change after query typo noise."],
                  ["Recall@5 / noisy", "1.0000", "1.0000", "No change after query typo noise."],
                  ["MRR / noisy MRR", "0.9625 / 0.9600", "0.9625 / 0.9600", "Noise delta -0.0025."],
                  ["nDCG@5 / noisy", "0.9715 / 0.9693", "0.9715 / 0.9693", "Noise delta -0.0022."],
                  ["Faithfulness proxy", "0.6500", "0.6500", "Above the configured 0.60 floor."],
                  ["Abstention / citation validity", "1.0000 / 1.0000", "1.0000 / 1.0000", "All measured expected abstentions and citations passed."],
                  ["Latency p50 / p95 (s)", "15.5027 / 38.1216", "13.2613 / 34.6010", "Both p95 values below 60 s."],
              ], [44 * mm, 31 * mm, 31 * mm, 68 * mm]),
              Spacer(1, 3 * mm),
              note("Noise was injected by typo perturbation. The noise changed MRR and nDCG only slightly, and did not change recall@3 or recall@5. The suite reports identical paired metric values across its two repetitions except for the measured embedding-time difference."),
              p("The faithfulness proxy is not a human judge. It depends on an expected phrase and citation match; paraphrases can be penalized and unsupported claims may escape the proxy. The result should be read as a test signal, not a human-validated faithfulness rate.", "small"),
              PageBreak()]

    # Page 5: C.
    story += [p("4. Change experiment and release gate (Part C)", "h1"),
              p("The pipeline change was retrieval top-k: baseline=5, candidate=6. The candidate used an isolated Chroma collection and the same Batch A corpus snapshot and embedding model. A deliberately poor top-k=1 setting served as the negative control."),
              table([
                  ["Candidate", "Recall@5", "Faithfulness", "Citation / abstention", "p95 (s)", "Gate"],
                  ["Baseline, top-k=5", "1.0000", "0.6500", "1.0000 / 1.0000", "38.1216 / 34.6010", "Reference"],
                  ["top-k=1 negative control", "0.9000", "0.7000", "1.0000 / 1.0000", "15.5386 / 15.7648", "FAIL: recall drop 0.10 > 0.02"],
                  ["top-k=6 candidate", "1.0000", "0.6500", "1.0000 / 1.0000", "30.8577 / 31.2957", "PASS"],
              ], [38 * mm, 21 * mm, 24 * mm, 39 * mm, 30 * mm, 22 * mm]),
              Spacer(1, 3 * mm), p("Gate thresholds and decision", "h2"),
              p("The committed gate config requires recall@5 drop no greater than 0.02, faithfulness_proxy at least 0.60, latency_p95 no more than 60 seconds, abstention correctness no lower than baseline, and citation validity at least 1.0. top-k=1 failed on recall@5; top-k=6 passed all of these checks on the baseline snapshot. The top-k=6 candidate was promoted; the later live misconfiguration to a nonexistent collection was reversed with kubectl rollout undo, after which the live API returned to 3/3 Ready."),
              p("A separate strict-gate run lowered the configured p95 maximum to 1 second and failed without rebuilding the image. That run also used a changed corpus with the older reference, so recall@5=0.4 and faithfulness_proxy=0.35 were confounded by data drift. It demonstrates that a ConfigMap-controlled threshold can change the gate outcome, but it is not an isolated threshold-only comparison. The gate was restored to max=60 seconds."),
              note("Release decision: promote top-k=6 for the baseline snapshot; reject top-k=1. The strict-gate result is retained as a sensitivity check, not as a clean candidate comparison.", GREEN),
              p("Appendix C2 contains the failing and passing candidate Job outputs. Appendix F also includes the threshold failure and the live rollout timeout/undo.", "small"),
              PageBreak()]

    # Page 6: D.
    story += [p("5. Traceability and observability (Part D)", "h1"),
              p("Each API query emits JSONL to stdout and a pod-specific trace file. The record includes trace/time, user query, embedding model/version, collection generation, retrieved chunk IDs and scores, filters, reranked order, context and exact prompt, model parameters, response/citations, guardrail actions, cache state and stage latencies. A trace ID command reconstructs the context and prompt."),
              table([
                  ["Signal", "Implementation / evidence"],
                  ["Top-1 similarity", "rahbar_top_similarity histogram; observed record carries top retrieval scores."],
                  ["Abstention and cache", "rahbar_abstentions_total, rahbar_cache_lookups_total and rahbar_cache_hit_ratio."],
                  ["Latency", "HTTP, retrieval, generation and per-stage histograms; evaluation prints request p50/p95."],
                  ["Injection attempts", "rahbar_injection_attempts_total; trace stores the action and affected chunk."],
                  ["Trace replay", "traces/inspect_trace.py prints the exact evidence context and prompt by trace ID."],
              ], [42 * mm, 132 * mm]),
              Spacer(1, 3 * mm), p("Observed trace and injection test", "h2"),
              p("Trace ad37b78a93be4b8b8d5fd12d668fdc90 answered the orientation question from orientation.md / Orientation check-in, page 1, with score 0.8575. It used nomic-embed-text, the candidate collection generation, llama3.2:3b, and recorded an injection guardrail action: one instruction-like line was removed from orientation-md-0000. The trace JSONL is retained under traces/. The terminal screenshot shows the reconstructed prompt/context; a full-trace terminal screenshot was not supplied."),
              p("Five-line trace-only root cause (trace b43ca9aa328549079dd43e28bfee1021):", "h2"),
              table([
                  ["1", "The query asked how many lectures were needed before finals; the answer was a fallback abstention."],
                  ["2", "Retrieval returned academic-rules-2027-md-0001, section 1. Attendance, score 0.7505."],
                  ["3", "The relevance floor was 0.65, so the correct attendance chunk passed filtering."],
                  ["4", "The exact prompt context included the 85 percent attendance rule and the FA consequence."],
                  ["5", "The model/validator returned no cited answer; the failure is generation/validation, not retrieval."],
              ], [9 * mm, 165 * mm], header=False),
              p("The metrics endpoint was reachable through port-forward. The supplied screenshot shows Prometheus output and request counters; per-stage metric time series were implemented, but a numeric stage-p95 summary was not captured in the appendix.", "small"),
              PageBreak()]

    # Page 7: E.
    story += [p("6. Query coverage and data drift (Part E)", "h1"),
              p("The live workload contains 40 questions: 28 in the academic/fees domain and 12 from uncovered topics. The 0.82 cosine threshold was selected as a provisional semantic-match bar; 85% is the target coverage rate used for the check."),
              table([
                  ["Check", "Result", "Interpretation"],
                  ["Coverage before expansion", "47.5% (19/40 above threshold)", "Below 85%; gaps span academic/fees, residence, transport and health."],
                  ["Coverage after +6 questions", "62.5% (25/40 above threshold)", "Improved by 15 percentage points; still fails the 85% target."],
                  ["Drift, old golden labels", "Recall@3/5=0.4000; MRR=0.4000; nDCG@5=0.4000; faithfulness=0.3500", "The newer 2027 policy changed expected answers while the old golden set retained 2026 labels."],
                  ["Drift, updated golden", "Recall@3=0.9524; recall@5=1.0000; MRR=0.9643; nDCG@5=0.9729; faithfulness=0.6667", "Updated labels align with the active policy; abstention and citation validity remained 1.0."],
              ], [39 * mm, 61 * mm, 74 * mm]),
              Spacer(1, 3 * mm), p("Uncovered topics", "h2"),
              p("The original uncovered list included academic standing and fees questions not represented by the seeded rules, plus questions about hostel applications and check-in, campus shuttle schedules and bicycle rules, and clinic services. The expanded set added six questions across residence, transport and health; coverage rose but remained below target. The data demonstrates a remaining need for domain sources and/or additional reviewed questions."),
              note("E4 is partially achieved: coverage increased from 47.5% to 62.5%, but the report does not call the gap closed because the configured threshold is 85%.", AMBER),
              p("The Batch B / updated-golden run restores retrieval scores after policy-version labels are updated. This illustrates why the data lifecycle and the evaluation dataset must advance together.", "small"),
              PageBreak()]

    # Page 8: F, qualities, short answers, contributions.
    story += [p("7. Kubernetes reliability, discussion and conclusion", "h1"),
              p("Kubernetes objects and resource settings", "h2"),
              table([
                  ["Component", "Object / responsibility", "Requests and limits"],
                  ["API", "Deployment x3; Service; maxUnavailable=0; HPA 3-8", "100m CPU / 96Mi; 500m / 256Mi"],
                  ["Chroma", "StatefulSet + PVC; persistent vector index", "50m / 128Mi; 500m / 512Mi"],
                  ["Indexing Job", "Only vector writer; CronJob uses Forbid concurrency", "500m / 512Mi; 1 CPU / 1Gi"],
                  ["Eval Job", "Runs suite and gate; writes results to PVC", "100m / 64Mi; 500m / 256Mi"],
                  ["Redis / UI", "Cache PVC / UI Deployment", "20m / 32Mi; 200m / 128Mi / 10m /16Mi; 100m /64Mi"],
              ], [26 * mm, 73 * mm, 75 * mm]),
              p("At capture, live API was 3/3 Ready and candidate 1/1, with Chroma, Redis and UI Running. One Docker Desktop snapshot during heavy work showed the Minikube container using 2.063 GiB of its 4 GiB limit and 112% CPU. This is a point-in-time host-container sample, not a per-pod peak; the report does not claim measured peak memory for each Job.", "small"),
              p("Table 2 qualities", "h2"),
              table([
                  ["Quality", "Measurement / threshold", "Evidence"],
                  ["Adaptability", "0 chunks on unchanged repeat; 0 deleted-document chunks", "Batch A repeat output; delete/restore Jobs."],
                  ["Monitorability", "recall drop <=0.02; faithfulness >=0.60; p95 <=60s; abstention no regression; citations=1", "Candidate pass, top-k=1 fail, ConfigMap strict failure."],
                  ["Observability", "Top score histogram, abstentions, cache, stage latency, injection count", "/metrics route and JSONL traces."],
                  ["Traceability", "Complete JSONL trace with prompt/context and trace ID inspector", "Trace file, injection record, reconstruction screenshot."],
                  ["Reliability", "maxUnavailable=0; 3 live replicas; requests/limits", "Healthy deployment snapshot and rollout undo."],
              ], [27 * mm, 81 * mm, 66 * mm]),
              p("Short answers", "h2"),
              p("(a) Uniqueness caught the most seeded problems: two exact duplicates and one near duplicate. The truncation and missing-title inputs failed completeness. We did not test a valid-looking but semantically partial file; source hashes or expected lengths would help. (b) Embedding gap and determinism looked stable, while using old labels after Batch B produced recall@5=0.4 and faithfulness=0.35; updating the labels restored scores. (c) Superseded versions were archived. Deleting them would prevent restoration and weaken historical citation provenance. (d) Faithfulness proxy is least trusted because phrase matching and citation presence are not human semantic review."),
              p("(e) The hardest paper idea was coupling a changing data lake with a stable test set. We used separate candidate collections and updated labels to expose drift. (f) Kubernetes responsibilities: Job writes vectors, CronJob schedules ingestion, PVC stores data/results/traces, ConfigMap carries thresholds, Deployments serve API/UI, Service routes traffic, StatefulSet preserves Chroma identity and storage, and rollout status/undo controls release."),
              p("Contribution and AI statement", "h2"),
              p("Faizan Ahmed executed the local Kubernetes experiments, captured the submitted evidence and maintained the Assignment 03 branch fixes. Jahanzeb Arfan's Assignment 02 RAHBAR system is the starting point; specific Assignment 03 task allocation was not independently provided. The five local Assignment 03 commits currently visible in the branch are attributed to Faizan Ahmed. AI assistance was used for code and report drafting; the group must review the implementation, metrics and explanations and be prepared to explain them at the demo.", "small"),
              p("Conclusion: top-k=6 passed its baseline gate and the failed live configuration was rolled back. Batch verification, tracing and drift experiments ran on Kubernetes. Remaining evidence gaps are a screenshot of the unchanged run, the full namespace inventory, a post-rollback trace screenshot, per-pod resource peak measurements, and human-authored/reviewed golden questions. Coverage is still below 85%.", "small"),
              p("References: Assignment 03 handout, CS4032 Fall 2026. Xiwei Xu et al., RAGOps: Operating and Managing Retrieval-Augmented Generation Pipelines, arXiv:2506.03401 (2025), https://arxiv.org/abs/2506.03401.", "tiny"),
              PageBreak()]

    # Evidence appendix: each user-supplied terminal image is kept unaltered.
    appendix = [
        ("A1", "Batch B verification report with per-document checks, dispositions and chunk counts.", "A1-batch-b-verification.png"),
        ("B2", "Baseline evaluation summary: embedding, retrieval and answer-level metrics, including both runs.", "B2-baseline-evaluation.png"),
        ("C2-Fail", "Negative control: top-k=1 fails the recall@5 release gate.", "C2-topk1-gate-fail.png"),
        ("C2-Pass", "Candidate: top-k=6 passes the release gate against baseline.", "C2-topk6-gate-pass.png"),
        ("F-Gate", "Strict ConfigMap threshold run fails; see report discussion for corpus/reference confounding.", "F-config-threshold-gate-fail.png"),
        ("E2", "Live query coverage before adding questions: 47.5% against the 85% target.", "E2-coverage-before.png"),
        ("E4", "Live query coverage after six added questions: 62.5% against the 85% target.", "E4-coverage-after.png"),
        ("E3-Same", "Drift evaluation with the old golden labels.", "E3-drift-same-golden.png"),
        ("E3-Updated", "Drift evaluation with updated golden labels.", "E3-drift-updated-golden.png"),
        ("A2-Delete", "Deleting the fee document leaves zero fee chunks in the serving collection.", "A2-delete-document.png"),
        ("A2-Restore", "Restoring academic-rules 2026 archives 2027 and indexes the restored version.", "A2-restore-archived-version.png"),
        ("F1", "Kubernetes deployment and pod status at capture: live API 3/3 Ready, candidate 1/1 Ready.", "F1-kubernetes-deployment-status.png"),
        ("F3-Bad", "Bad live rollout using a nonexistent collection fails readiness and times out.", "F3-bad-rollout-timeout.png"),
        ("F3-Undo", "kubectl rollout undo and successful live API rollout status.", "F3-rollout-undo.png"),
        ("D1-Copy", "Trace JSONL copied from the live pod to the local trace folder.", "D1-copy-trace.png"),
        ("D2", "Trace inspector reconstructs the exact evidence context and prompt for a trace ID.", "D2-reconstructed-context-prompt.png"),
        ("D3", "Prometheus metrics endpoint reached through kubectl port-forward.", "D3-metrics-endpoint.png"),
    ]
    for code, caption, filename in appendix:
        story.extend(screenshot_page(code, caption, filename))

    doc = ReportDoc(PDF_PATH)
    doc.build(story)
    print(f"Wrote {PDF_PATH}")
    print(f"Wrote {SUMMARY_PATH}")


if __name__ == "__main__":
    build()
