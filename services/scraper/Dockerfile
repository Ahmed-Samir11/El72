FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
# Install browsers for playwright
RUN python -m playwright install --with-deps
COPY . /app
ENV PYTHONUNBUFFERED=1
CMD ["python", "scraper.py"]
