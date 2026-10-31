FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY services/chatbot/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright browsers (required by Crawl4AI for web scraping)
RUN playwright install --with-deps chromium

# Application code: the chatbot service plus the shared library it imports
# (services/common -> /app/common, which carries the JWT and robots.txt contracts
# the chatbot must not re-implement).
COPY services/common/ /app/common/
COPY services/chatbot/main.py services/chatbot/search_service.py services/chatbot/models.py services/chatbot/arabic_nlp.py services/chatbot/i18n.py services/chatbot/cache.py services/chatbot/extractors.py services/chatbot/store_health.py ./

# Expose port (service listens on 8003)
EXPOSE 8003

# Run the application
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8003"]
