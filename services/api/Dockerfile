FROM python:3.11-slim

WORKDIR /app

COPY services/api/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Headless Chromium for the JS-rendered-page price fetch fallback
# (services/api/price_fetcher.py). The requests-only path cannot see
# prices on stores that render them client-side or gate bots.
# Installed to a shared path (not root's home) so the unprivileged
# runtime user below can read it.
ENV PLAYWRIGHT_BROWSERS_PATH=/opt/playwright-browsers
RUN python -m playwright install --with-deps chromium

COPY . .

# Run the API as an unprivileged user: limits the blast radius if a
# fetched page (or a browser bug) compromises the process. Chromium still
# needs --no-sandbox inside a container — the price fetcher passes it —
# but a non-root browser process can no longer touch host files or run
# privileged container operations.
RUN useradd --create-home --uid 10001 appuser \
    && chown -R appuser:appuser /app
USER appuser

CMD ["uvicorn", "services.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
