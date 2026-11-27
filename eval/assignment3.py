"""Run the three-level evaluation, coverage check, or release gate."""
from __future__ import annotations

import argparse
import json
import math
import random
import re
import statistics
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent


def read_rows(path):
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line]


def post(url, data):
    request = Request(url, data=json.dumps(data).encode(), headers={"Content-Type": "application/json", "X-RAGOps-Eval": "1"})
    with urlopen(request, timeout=310) as response:
        return json.load(response)


def embed(texts, args, task="query"):
    prefix = f"search_{task}: " if args.model.split(":")[0] == "nomic-embed-text" else ""
    vectors = []
    for start in range(0, len(texts), 32):
        vectors.extend(post(args.ollama + "/api/embed", {
            "model": args.model, "input": [prefix + text for text in texts[start:start + 32]],
        })["embeddings"])
    return vectors


def cosine(a, b):
    return sum(x * y for x, y in zip(a, b, strict=True)) / (math.hypot(*a) * math.hypot(*b) or 1)


def average(values):
    return statistics.mean(values) if values else 0.0


def percentile(values, fraction):
    return sorted(values)[math.ceil(len(values) * fraction) - 1] if values else 0.0


def retrieval(refs, expected):
    relevant = {(r["source"], r["page"], r["section"]) for r in expected}
    hits = []
    seen = set()
    for ref in refs[:5]:
        key = (ref["source"], ref["page"], ref["section"])
        hits.append(int(key in relevant and key not in seen))
        seen.add(key)
    dcg = sum(hit / math.log2(rank + 2) for rank, hit in enumerate(hits))
    ideal = sum(1 / math.log2(rank + 2) for rank in range(min(5, len(relevant))))
    return {
        "recall_at_3": sum(hits[:3]) / len(relevant),
        "recall_at_5": sum(hits) / len(relevant),
        "mrr": next((1 / rank for rank, hit in enumerate(hits, 1) if hit), 0.0),
        "ndcg_at_5": dcg / ideal,
    }


def typo(text, rng):
    positions = [m.start() + 1 for m in re.finditer(r"\b[A-Za-z]{5,}\b", text)]
    if not positions:
        return text
    index = rng.choice(positions)
    return text[:index] + text[index + 1] + text[index] + text[index + 2:]


def suite(args):
    rng = random.Random(42)
    golden = read_rows(args.golden)
    pairs = read_rows(ROOT / "embedding-pairs.jsonl")
    texts = [text for row in pairs for text in (row["text"], row["paraphrase"], row["unrelated"])]
    started = time.perf_counter()
    vectors = embed(texts, args, "document")
    per_chunk = (time.perf_counter() - started) / len(texts)
    paraphrase = average([cosine(*vectors[i:i + 2]) for i in range(0, len(vectors), 3)])
    unrelated = average([cosine(vectors[i], vectors[i + 2]) for i in range(0, len(vectors), 3)])
    first, second = (embed([texts[0]], args, "document")[0] for _ in range(2))
    metrics = {
        "paraphrase_cosine": paraphrase, "unrelated_cosine": unrelated,
        "cosine_gap": paraphrase - unrelated, "embedding_seconds_per_text": per_chunk,
        "embedding_max_difference": max(abs(a - b) for a, b in zip(first, second, strict=True)),
    }
    clean_scores, noisy_scores, abstention, valid, support, times, rows = [], [], [], [], [], [], []
    for row in golden:
        url = args.api + "/api/ask"
        started = time.perf_counter()
        answer = post(url, {"question": row["question"]})
        times.append(time.perf_counter() - started)
        expected = row.get("relevant", [])
        if expected:
            noise = post(url, {"question": typo(row["question"], rng)})
            clean_scores.append(retrieval(answer["retrieved"], expected))
            noisy_scores.append(retrieval(noise["retrieved"], expected))
        elif row.get("must_abstain"):
            abstention.append(not answer["answered_from_context"])
        citations = answer["citations"]
        grounded = {(ref["source"], ref["page"], ref["section"]) for ref in answer["retrieved"]}
        cited = {(ref["source"], ref["page"], ref["section"]) for ref in citations}
        valid.extend((key in grounded) for key in cited)
        if answer["answered_from_context"] and not citations:
            valid.append(False)
        # Reference-based proxy. Human reviewers can use the recorded trace ids.
        if expected or answer["answered_from_context"]:
            keys = {(r["source"], r["page"], r["section"]) for r in expected}
            support.append(bool(answer["answered_from_context"] and cited & keys and
                                row.get("expect", "").casefold() in answer["answer"].casefold()
                                and expected))
        rows.append({"id": row["id"], "trace_id": answer["request_id"], "answer": answer})
    for key in clean_scores[0]:
        metrics[key] = average([r[key] for r in clean_scores])
        metrics["noisy_" + key] = average([r[key] for r in noisy_scores])
        metrics["noise_delta_" + key] = metrics["noisy_" + key] - metrics[key]
    metrics.update(faithfulness_proxy=average(support), abstention_correctness=average(abstention),
                   citation_validity=average(valid), latency_p50=percentile(times, .50),
                   latency_p95=percentile(times, .95))
    return {"metrics": metrics, "questions": rows}


def output(data, directory, name):
    target = Path(directory)
    target.mkdir(parents=True, exist_ok=True)
    path = target / f"{datetime.now(UTC):%Y%m%dT%H%M%S.%fZ}-{name}.json"
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    print(path)


def gate(current, reference, thresholds):
    failures = []
    for key, requirement in thresholds.items():
        value = current[key]
        if "min" in requirement and value < requirement["min"]:
            failures.append(f"{key} {value:.4f} < {requirement['min']}")
        if "max" in requirement and value > requirement["max"]:
            failures.append(f"{key} {value:.4f} > {requirement['max']}")
        if "max_drop" in requirement and value < reference[key] - requirement["max_drop"]:
            failures.append(f"{key} {value:.4f} dropped from {reference[key]:.4f}")
    return failures


def coverage(args):
    golden = read_rows(args.golden)
    live = read_rows(ROOT / "live.jsonl")
    gold_vectors = embed([row["question"] for row in golden], args)
    live_vectors = embed([row["question"] for row in live], args)
    matches = []
    groups = {}
    for row, vector in zip(live, live_vectors, strict=True):
        score, index = max((cosine(vector, candidate), index)
                           for index, candidate in enumerate(gold_vectors))
        covered = score >= args.similarity
        matches.append({**row, "golden_id": golden[index]["id"], "similarity": score,
                        "covered": covered})
        if not covered:
            groups.setdefault(row["topic"], []).append(row["question"])
    share = average([row["covered"] for row in matches])
    output({"coverage": share, "similarity_threshold": args.similarity,
            "required_share": args.minimum_coverage, "matches": matches, "uncovered": groups},
           args.out, "coverage")
    print(f"Coverage {share:.1%} against {args.minimum_coverage:.1%}")
    print(json.dumps(groups, indent=2))
    return int(share < args.minimum_coverage)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["suite", "coverage"])
    parser.add_argument("--api", default="http://localhost:8000")
    parser.add_argument("--ollama", default="http://localhost:11434")
    parser.add_argument("--model", default="nomic-embed-text")
    parser.add_argument("--golden", default=ROOT / "golden.jsonl")
    parser.add_argument("--out", default=ROOT / "results")
    parser.add_argument("--name", default="suite")
    parser.add_argument("--baseline")
    parser.add_argument("--thresholds", default=ROOT / "gate.json")
    parser.add_argument("--similarity", type=float, default=.82)
    parser.add_argument("--minimum-coverage", type=float, default=.85)
    args = parser.parse_args()
    if args.command == "coverage":
        return coverage(args)
    first, second = suite(args), suite(args)
    delta = {key: second["metrics"][key] - value for key, value in first["metrics"].items()}
    thresholds = json.loads(Path(args.thresholds).read_text(encoding="utf-8"))
    failures = []
    if args.baseline:
        reference = json.loads(Path(args.baseline).read_text(encoding="utf-8"))["runs"][0]["metrics"]
        for number, run in enumerate((first, second), 1):
            failures.extend(f"run {number}: {reason}" for reason in gate(run["metrics"], reference, thresholds))
    output({"runs": [first, second], "delta": delta, "gate_checked": bool(args.baseline),
            "gate_failures": failures, "configuration": {"model": args.model, "seed": 42,
            "name": args.name, "golden": Path(args.golden).name, "api": args.api}},
           args.out, args.name)
    for key, value in first["metrics"].items():
        print(f"{key:32} {value:9.4f} {second['metrics'][key]:9.4f} {delta[key]:+9.4f}")
    if args.baseline:
        print("GATE FAIL" if failures else "GATE PASS")
        for failure in failures:
            print(failure)
    return int(bool(failures))


if __name__ == "__main__":
    raise SystemExit(main())
