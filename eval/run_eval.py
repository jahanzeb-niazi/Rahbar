#!/usr/bin/env python3
"""Score a running RAHBAR against a golden set, and gate CI on the result (section 5).

    python eval/run_eval.py --api http://<ingress>                 # your corpus
    python eval/run_eval.py --api ... --golden eval/fixtures/golden.fixture.yaml
    python eval/run_eval.py --api ... --update-baseline            # after a deliberate improvement

Exit code 0 when every gate passes, 1 when any fails. CI relies on that exit code.

Given: talking to the API, reading the golden set, writing results.json, the exit
code. Ours: recall_at_k, citation_validity, summarise and gate. They are the evaluation.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import httpx
import yaml

HERE = Path(__file__).resolve().parent

# The gate from section 5.4. Change these only with a reason written in docs/PIPELINE.md.
MAX_RECALL5_DROP = 0.05        # recall@5 may fall at most 5 points below the baseline
MIN_CITATION_VALIDITY = 0.95   # at least 95% of citations must match retrieved passages
REQUIRED_ABSTENTION = 1.0      # every must-abstain question must be declined


def load_golden(path: Path) -> list[dict]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    questions = data.get("questions") or []
    if not questions:
        sys.exit(f"no questions in {path}")
    return questions


def ask(client: httpx.Client, api: str, question: str) -> dict:
    """POST one question and return the AskResponse as a dict (see api/app/schemas.py)."""
    response = client.post(f"{api.rstrip('/')}/api/ask", json={"question": question})
    response.raise_for_status()
    return response.json()


def _norm(text: str) -> str:
    return " ".join(str(text).lower().split())


def _matches(relevant: dict, passage: dict) -> bool:
    """A golden (source, section) pair is found by a retrieved passage with the same source
    whose section contains the golden section text (headings carry their parents, e.g.
    "5. Academic Assessment > Academic Warning/Probation" contains "Academic Warning")."""
    return (_norm(relevant["source"]) == _norm(passage.get("source", ""))
            and _norm(relevant["section"]) in _norm(passage.get("section", "")))


def recall_at_k(relevant: list[dict], retrieved: list[dict], k: int) -> float | None:
    """Fraction of the relevant (source, section) pairs found in the top k retrieved.
    Return None when the question has no relevant passages (must-abstain questions)."""
    if not relevant:
        return None
    top = retrieved[:k]
    found = sum(1 for rel in relevant if any(_matches(rel, p) for p in top))
    return found / len(relevant)


def first_relevant_rank(relevant: list[dict], retrieved: list[dict]) -> int | None:
    """1-based rank of the first retrieved passage that matches any relevant pair."""
    for rank, passage in enumerate(retrieved, start=1):
        if any(_matches(rel, passage) for rel in relevant):
            return rank
    return None


def citation_validity(response: dict) -> float | None:
    """Fraction of the response's citations that match a passage in response['retrieved'].
    Return None when there are no citations."""
    citations = response.get("citations") or []
    if not citations:
        return None
    retrieved = {(_norm(p["source"]), _norm(p["section"])) for p in response.get("retrieved", [])}
    valid = sum(1 for c in citations if (_norm(c["source"]), _norm(c["section"])) in retrieved)
    return valid / len(citations)


def _mean(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 4) if values else None


def summarise(rows: list[dict]) -> dict:
    """Overall recall@3, recall@5, citation validity and abstention correctness, plus
    recall@5 broken down by question type. This dict becomes results.json."""
    per_question = []
    by_type: dict[str, dict[str, list[float]]] = {}
    total_citations = valid_citations = 0
    abstain_rows = abstained_ok = 0
    answerable = answered = 0
    for row in rows:
        response = row["response"]
        retrieved = response.get("retrieved", [])
        r3 = recall_at_k(row["relevant"], retrieved, 3)
        r5 = recall_at_k(row["relevant"], retrieved, 5)
        rank = first_relevant_rank(row["relevant"], retrieved) if row["relevant"] else None
        cv = citation_validity(response)
        n_cit = len(response.get("citations") or [])
        total_citations += n_cit
        valid_citations += round((cv or 0.0) * n_cit)
        declined = not response.get("answered_from_context", False)
        if row["must_abstain"]:
            abstain_rows += 1
            abstained_ok += int(declined)
        else:
            answerable += 1
            answered += int(not declined)
        bucket = by_type.setdefault(row["type"], {"recall@3": [], "recall@5": []})
        if r3 is not None and r5 is not None:
            bucket["recall@3"].append(r3)
            bucket["recall@5"].append(r5)
        expect = row.get("expect")
        per_question.append({
            "id": row["id"], "type": row["type"], "recall@3": r3, "recall@5": r5,
            "first_relevant_rank": rank,
            "citation_validity": cv, "citations": n_cit,
            "answered_from_context": not declined, "must_abstain": row["must_abstain"],
            "expect_found": (_norm(expect) in _norm(response.get("answer", "")))
            if expect else None,
            "cached": bool(response.get("cached", False)), "seconds": row["seconds"],
            "retrieved": [p["chunk_id"] for p in retrieved],
            "scores": [p.get("score") for p in retrieved],
        })
    r3_all = [q["recall@3"] for q in per_question if q["recall@3"] is not None]
    r5_all = [q["recall@5"] for q in per_question if q["recall@5"] is not None]
    scored = [q for q in per_question if q["recall@5"] is not None]
    rr = [1.0 / q["first_relevant_rank"] if q["first_relevant_rank"] else 0.0 for q in scored]
    r1 = [1.0 if q["first_relevant_rank"] == 1 else 0.0 for q in scored]
    return {
        "recall@3": _mean(r3_all),
        "recall@5": _mean(r5_all),
        "recall@1": _mean(r1),
        "mrr": _mean(rr),
        "recall_by_type": {t: {"recall@3": _mean(v["recall@3"]), "recall@5": _mean(v["recall@5"]),
                               "questions": sum(1 for q in per_question if q["type"] == t)}
                           for t, v in sorted(by_type.items())},
        "citation_validity": round(valid_citations / total_citations, 4)
        if total_citations else None,
        "citations_total": total_citations,
        "abstention_correctness": round(abstained_ok / abstain_rows, 4) if abstain_rows else None,
        "answered_rate": round(answered / answerable, 4) if answerable else None,
        "expect_found_rate": _mean([float(q["expect_found"]) for q in per_question
                                    if q["expect_found"] is not None]),
        "per_question": per_question,
    }


def gate(results: dict, baseline: dict | None) -> list[str]:
    """Return one message per failed gate (section 5.4); an empty list means pass."""
    failures = []
    recall5 = results.get("recall@5")
    if baseline and baseline.get("recall@5") is not None:
        floor = baseline["recall@5"] - MAX_RECALL5_DROP
        if recall5 is None or recall5 < floor - 1e-9:
            failures.append(f"recall@5 {recall5} is more than {MAX_RECALL5_DROP:.0%} below "
                            f"the baseline {baseline['recall@5']}")
    abstention = results.get("abstention_correctness")
    if abstention is not None and abstention < REQUIRED_ABSTENTION:
        wrong = [q["id"] for q in results.get("per_question", [])
                 if q["must_abstain"] and q["answered_from_context"]]
        failures.append(f"must-abstain questions answered from context: {', '.join(wrong)}")
    validity = results.get("citation_validity")
    if validity is None or validity < MIN_CITATION_VALIDITY:
        failures.append(f"citation validity {validity} is below {MIN_CITATION_VALIDITY:.0%}")
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate RAHBAR against a golden set.")
    parser.add_argument("--api", required=True, help="base URL, e.g. http://192.168.49.2")
    parser.add_argument("--host", help="Host header, when your Ingress rule names a host")
    parser.add_argument("--golden", type=Path, default=HERE / "golden.yaml")
    parser.add_argument("--baseline", type=Path, default=HERE / "baseline.json")
    parser.add_argument("--out", type=Path, default=HERE / "results.json")
    parser.add_argument("--update-baseline", action="store_true",
                        help="write these results as the new baseline")
    args = parser.parse_args()

    questions = load_golden(args.golden)
    rows = []
    headers = {"Host": args.host} if args.host else {}
    with httpx.Client(timeout=600.0, headers=headers) as client:
        for q in questions:
            started = time.perf_counter()
            response = ask(client, args.api, q["question"])
            rows.append({
                "id": q["id"], "type": q.get("type", "ordinary"),
                "must_abstain": bool(q.get("must_abstain", False)),
                "relevant": q.get("relevant") or [],
                "expect": q.get("expect"),
                "response": response,
                "seconds": round(time.perf_counter() - started, 2),
            })
            print(f"  {q['id']:<5} {rows[-1]['seconds']:>6.2f}s  {q['question'][:60]}")

    try:
        results = summarise(rows)
        baseline = json.loads(args.baseline.read_text()) if args.baseline.exists() else None
        failures = gate(results, baseline)
    except NotImplementedError as exc:
        print(f"\nnot implemented yet: {exc}")
        return 2

    results["golden"] = str(args.golden)
    results["questions"] = len(rows)
    args.out.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"\nresults written to {args.out}")
    if args.update_baseline:
        args.baseline.write_text(json.dumps(results, indent=2), encoding="utf-8")
        print(f"baseline updated: {args.baseline}")

    if failures:
        print("\nGATE FAILED")
        for message in failures:
            print(f"  - {message}")
        return 1
    print("\ngate passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
