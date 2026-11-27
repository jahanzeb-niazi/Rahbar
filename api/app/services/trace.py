"""Persist a query trace as a single JSON line in stdout and a pod-specific file."""
from __future__ import annotations

import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from prometheus_client import Counter, Histogram

TOP_SIMILARITY = Histogram("rahbar_top_similarity", "Top retrieval similarity",
                           buckets=(-1, 0, .25, .5, .65, .75, .9, 1))
INJECTIONS = Counter("rahbar_injection_attempts_total", "Instruction-like passages flagged")
STAGE_TIME = Histogram("rahbar_stage_seconds", "Time per query stage", ["stage"])
INSTRUCTION = re.compile(r"ignore (?:all |the )?(?:previous|prior|earlier) instructions", re.I)


def emit(trace: dict[str, Any]) -> None:
    trace["timestamp"] = datetime.now(UTC).isoformat()
    for stage, elapsed in trace["latency_seconds"].items():
        STAGE_TIME.labels(stage=stage).observe(elapsed)
    scores = trace["retrieved"]
    if scores and trace["cache"] != "hit":
        TOP_SIMILARITY.observe(scores[0]["score"])
    line = json.dumps(trace, ensure_ascii=True, separators=(",", ":"))
    print(line, flush=True)
    if directory := os.environ.get("RAGOPS_TRACES"):
        path = Path(directory)
        path.mkdir(parents=True, exist_ok=True)
        with (path / f'{os.environ.get("HOSTNAME", "local")}.jsonl').open("ab", buffering=0) as file:
            file.write((line + "\n").encode())
