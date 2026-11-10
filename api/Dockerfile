# RAHBAR API: reads the index, never writes it. Build context: api/
FROM python:3.12.10-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Dependencies first, so a code change does not reinstall them.
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY app ./app

# Non-root (section 4.7). The Deployment also sets runAsNonRoot and a read-only root fs.
RUN useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin rahbar
USER 10001

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
