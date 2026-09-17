# AskSage Proof Agent - Dash application image.
#
# Serves dashboard.py (the Dash app) behind gunicorn. The Bonsai LLM engine
# runs in a separate container (see docker-compose.yml); this app talks to it
# over LOCAL_API_BASE. Deterministic rules run fully offline.

FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# curl is used by the healthcheck.
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

# Application source and static assets.
COPY dashboard.py .
COPY wsgi.py .
COPY app.py .
COPY src/ ./src/
COPY configs/ ./configs/
COPY assets/ ./assets/
RUN mkdir -p /app/data

EXPOSE 8501

ENV PORT=8501
# Point the local outlet at the local engine container by default. Inside
# docker-compose this is overridden. The model id served by llama-server is
# the alias "bonsai-1.7b" below.
ENV LOCAL_API_BASE=http://maple-llm:8080/v1 \
    LOCAL_MODEL=bonsai-1.7b \
    REVIEW_ENGINE=pub_pipeline

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD curl -f http://localhost:8501/health || exit 1

# gunicorn serves the Dash app's underlying Flask server via wsgi.py.
# --timeout 900 matches LLM_REQUEST_TIMEOUT: a slow CPU stage call on a long
# document can legitimately exceed 300s, and gunicorn would otherwise kill
# the worker mid-request.
CMD ["sh", "-c", "gunicorn --bind 0.0.0.0:${PORT} --workers 1 --threads 4 --timeout 900 'wsgi:application'"]
