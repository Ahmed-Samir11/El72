FROM python:3.11-slim
WORKDIR /app
COPY services/analyzer/requirements.txt ./
RUN pip install -r requirements.txt
COPY . /app
ENV PYTHONUNBUFFERED=1
EXPOSE 8000
CMD ["uvicorn", "services.analyzer.app:app", "--host", "0.0.0.0", "--port", "8000"]
