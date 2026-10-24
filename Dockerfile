FROM python:3.14-slim

# No .pyc files, and logs appear immediately instead of being buffered
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Copy requirements first so this layer is cached until requirements change
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# App code changes often, so it comes after the dependency layer
COPY app/ ./app/

# Run as a non-root user; /data is where the SQLite file lives
RUN useradd --create-home appuser \
    && mkdir /data \
    && chown appuser:appuser /data
USER appuser

ENV DB_PATH=/data/orderbook.db

EXPOSE 8000

# Default command = API. docker-compose overrides this for the collector.
CMD ["uvicorn", "app.api:app", "--host", "0.0.0.0", "--port", "8000"]