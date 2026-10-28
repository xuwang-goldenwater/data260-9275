# DATA 260 - HW8 Part 1: one image for both the worker and the FastAPI wrapper.
# Build context is code/kafka_app/, so only the Kafka service files are copied.
FROM python:3.11-slim

WORKDIR /app
# tzdata so log timestamps use Pacific time, matching scripts run on the Mac.
RUN apt-get update && apt-get install -y --no-install-recommends tzdata \
    && rm -rf /var/lib/apt/lists/*
ENV TZ=America/Los_Angeles
RUN pip install --no-cache-dir "confluent-kafka>=2.5" "fastapi>=0.110" "uvicorn>=0.27"

COPY recall_service.py worker.py api.py ./

# Logs go straight to `docker logs` instead of sitting in a buffer.
ENV PYTHONUNBUFFERED=1
# docker-compose.yml chooses which program runs (worker.py or api.py).
CMD ["python", "worker.py"]
