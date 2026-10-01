FROM python:3.11-slim

WORKDIR /app

COPY services/api/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Headless Chromium for the JS-rendered-page price fetch fallback
# (services/api/price_fetcher.py). The requests-only path cannot see
# prices on stores that render them client-side or gate bots.
RUN python -m playwright install --with-deps chromium

COPY . .

CMD ["uvicorn", "services.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
