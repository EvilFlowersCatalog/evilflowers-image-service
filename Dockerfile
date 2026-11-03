FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ ./src/

ARG IMAGE_TAG=dev
ENV PYTHONPATH=/app/src \
    PYTHONUNBUFFERED=1 \
    IMAGE_TAG=${IMAGE_TAG}

CMD ["celery", "--workdir", "src", "-A", "worker", "worker", "--loglevel=info", "-E", "--concurrency=1", "--queues=evilflowers_image"]
