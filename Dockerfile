FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    HEADLESS=true \
    DEBIAN_FRONTEND=noninteractive \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

RUN playwright install --with-deps firefox \
    && rm -rf /var/lib/apt/lists/*

COPY config.py storage.py scraper.py ui.py index.py ./

RUN useradd --create-home --uid 10001 app \
    && mkdir -p /app/data \
    && chown -R app:app /app/data

USER app

ENV SUBSCRIPTIONS_FILE=/app/data/subscriptions.json

CMD ["python", "index.py"]