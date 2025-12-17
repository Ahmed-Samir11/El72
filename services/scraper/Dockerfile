FROM python:3.11-slim
WORKDIR /app
COPY services/scraper/requirements.txt ./
RUN pip install -r requirements.txt
# Install browsers for playwright
RUN python -m playwright install --with-deps
COPY . /app
ENV PYTHONUNBUFFERED=1
CMD ["python", "services/scraper/scraper.py"]
