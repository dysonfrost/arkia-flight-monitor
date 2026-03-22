FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY arkia_monitor.py .

ENV NOTIFIED_FILE=/app/data/notified_flights.json
ENV AVE_CTR_FILE=/app/data/ave_counter.json
ENV AIRLABS_CTR=/app/data/airlabs_counter.json
ENV LOG_FILE=/app/data/arkia_monitor.log

RUN mkdir -p /app/data

CMD ["python", "-u", "arkia_monitor.py"]
