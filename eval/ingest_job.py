"""Serialize manual and scheduled ingestion that shares the data lake."""
import fcntl
import os
import subprocess
import sys
from pathlib import Path


def main():
    lake = Path(os.environ["RAGOPS_LAKE"])
    corpus = Path(os.environ["CORPUS_DIR"])
    with (lake / ".ingestion.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        batch = os.environ.get("RAGOPS_BATCH")
        if batch or not (corpus / "_index.json").exists():
            subprocess.run([sys.executable, "/app/eval/prepare_batches.py", str(corpus),
                            "--batch", batch or "a"], check=True)
        subprocess.run([sys.executable, "-m", "pipeline.run"], check=True)


if __name__ == "__main__":
    main()
