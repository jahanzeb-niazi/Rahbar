# RAHBAR indexer: the Job's image and the only writer to Chroma.
# Build context: the repository root, because the Job also runs corpus/fetch.py:
#   docker build -f indexer/Dockerfile -t rahbar-indexer:dev .
FROM python:3.12.10-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# OCR needs system packages, not only pip packages: tesseract for OCR and poppler
# (pdftoppm) for rendering scanned pages to images. `upgrade` picks up security fixes for
# the base image's Debian packages, which Trivy fails the build on.
RUN apt-get update \
    && apt-get upgrade -y --no-install-recommends \
    && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-eng poppler-utils \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY indexer/requirements.txt .
RUN pip install -r requirements.txt

COPY indexer/pipeline ./pipeline
# The fetch script and the committed manifest: the Job downloads the corpus at start-up
# and refuses to index a file whose SHA-256 differs from corpus/MANIFEST.md.
COPY corpus/fetch.py corpus/sources.yaml corpus/MANIFEST.md ./corpus/
# The CI fixture corpus (our own fictional documents) for the e2e-eval job.
COPY eval/fixtures ./fixtures

RUN useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin rahbar
USER 10001

CMD ["python", "-m", "pipeline.run"]
