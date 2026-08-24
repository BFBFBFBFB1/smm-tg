FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DEFAULT_TIMEOUT=120

WORKDIR /app

# Offline install: wheels/ must be present (downloaded on a PC with PyPI access)
COPY requirements.txt .
COPY wheels/ ./wheels/
RUN pip install --no-index --find-links=/app/wheels setuptools wheel \
    && pip install --no-index --find-links=/app/wheels -r requirements.txt \
    && rm -rf /app/wheels

COPY . .

RUN mkdir -p logs

CMD ["python", "-m", "app.main"]
