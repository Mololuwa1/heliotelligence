FROM python:3.13-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy dependency definition first (for Docker layer caching)
COPY pyproject.toml .

# Copy source code
COPY src/ src/
COPY config/ config/

# Install the package properly (non-editable)
RUN pip install --no-cache-dir .

# Run as non-root
RUN useradd -m appuser && chown -R appuser /app
USER appuser

# Cloud Run sets PORT env var
ENV PORT=8080
EXPOSE 8080

CMD exec uvicorn heliotelligence.api.app:app \
    --host 0.0.0.0 \
    --port $PORT \
    --workers 2 \
    --log-level info
