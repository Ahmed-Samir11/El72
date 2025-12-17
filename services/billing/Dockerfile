FROM python:3.11-slim

WORKDIR /app

COPY services/billing/requirements.txt .
RUN pip install -r requirements.txt

COPY . .

CMD ["uvicorn", "services.billing.main:app", "--host", "0.0.0.0", "--port", "8000"]