FROM python:3.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update && apt-get install -y --no-install-recommends \
      build-essential gcc g++ libglib2.0-0 libgl1 ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /srv/frs

COPY pyproject.toml ./pyproject.toml
COPY app ./app
COPY migrations ./migrations

RUN python -m pip install --upgrade pip setuptools wheel \
    && python -m pip install "Cython<3" \
    && python -m pip install .

RUN useradd --system --uid 10001 --create-home frs \
    && mkdir -p /data /models/insightface/models \
    && chown -R frs:frs /srv/frs /data /models

ENV FRS_DATABASE_URL=postgresql+psycopg://frs:configure-a-real-password@db:5432/frs
USER frs
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=120s --retries=3 \
  CMD curl --fail http://127.0.0.1:8000/health/live || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--proxy-headers"]
