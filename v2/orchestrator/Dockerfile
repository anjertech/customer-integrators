# orchestrator — reads the tenant list and creates one worker Job per tenant.
FROM python:3.12-slim-bookworm

ENV PYTHONUNBUFFERED=1
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY orchestrate.py worker-job.template.yaml ./

ENTRYPOINT ["python", "/app/orchestrate.py"]
