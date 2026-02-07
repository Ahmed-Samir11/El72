FROM python:3.11-slim

WORKDIR /app

# Install system deps for Playwright + Crawl4AI
RUN apt-get update && apt-get install -y --no-install-recommends \
    wget curl gnupg ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Crawl4AI browser
RUN crawl4ai-setup || true

COPY . /app/backend
# Also copy legacy scrapers for fallback
COPY ../services/scraper /app/services/scraper

EXPOSE 8080

CMD ["python", "-m", "uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8080"]
