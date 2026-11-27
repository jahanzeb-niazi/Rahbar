"""Print the exact context and prompt, or summarize a UTC trace window."""
import argparse
import json
import math
from datetime import datetime
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dir", default="traces")
    parser.add_argument("--from-time", type=datetime.fromisoformat)
    parser.add_argument("--until", type=datetime.fromisoformat)
    parser.add_argument("trace_id", nargs="?")
    args = parser.parse_args()
    rows = []
    for file in sorted(Path(args.dir).glob("*.jsonl")):
        with file.open(encoding="utf-8") as stream:
            for line in stream:
                if not line.endswith("\n"):
                    continue
                row = json.loads(line)
                if row["trace_id"] == args.trace_id:
                    print(json.dumps({key: row[key] for key in ("query", "context", "prompt")}, indent=2))
                    return 0
                if args.trace_id is None:
                    stamp = datetime.fromisoformat(row["timestamp"])
                    if (args.from_time is None or args.from_time <= stamp) and (
                            args.until is None or stamp < args.until):
                        rows.append(row)
    if args.trace_id:
        parser.exit(1, f"trace {args.trace_id} was not found\n")
    stages = {}
    for row in rows:
        for stage, seconds in row["latency_seconds"].items():
            stages.setdefault(stage, []).append(seconds)
    scores = [row["retrieved"][0]["score"] for row in rows if row["retrieved"] and row["cache"] != "hit"]
    lookups = [row for row in rows if row["cache"] in ("hit", "miss")]
    completed = [row for row in rows if row.get("status", 200) == 200]
    print(json.dumps({
        "queries": len(rows),
        "failed_queries": len(rows) - len(completed),
        "abstention_rate": sum(not row["response"]["answered_from_context"] for row in completed)
                           / max(1, len(completed)),
        "cache_hit_rate": sum(row["cache"] == "hit" for row in lookups) / max(1, len(lookups)),
        "stage_p95_seconds": {stage: sorted(values)[math.ceil(.95 * len(values)) - 1]
                              for stage, values in stages.items()},
        "top_similarity": sorted(scores),
        "injections_flagged": sum(len(row["guardrails"]) for row in rows),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
