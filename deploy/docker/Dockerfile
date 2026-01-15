# Kalshi Prediction Bot - Docker Image
# Build: docker build -t kalshi-bot .
# Run: docker run -d --name kalshi-bot --env-file .env kalshi-bot

FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    openssl \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN useradd -r -s /bin/false kalshi

# Copy requirements first (for caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create data directory
RUN mkdir -p /app/data && chown -R kalshi:kalshi /app

# Generate RSA keys if not provided
RUN if [ ! -f kalshi_private_key.pem ]; then \
    openssl genrsa -out kalshi_private_key.pem 4096 && \
    openssl rsa -in kalshi_private_key.pem -pubout -out kalshi_public_key.pem; \
    fi

# Set permissions
RUN chmod 600 kalshi_private_key.pem

# Switch to non-root user
USER kalshi

# Environment variables
ENV PYTHONUNBUFFERED=1
ENV DATABASE_PATH=/app/data/trades.db
ENV LOG_LEVEL=INFO

# Health check
HEALTHCHECK --interval=60s --timeout=10s --start-period=30s --retries=3 \
    CMD curl -f http://localhost:8080/health || exit 1

# Run the bot
CMD ["python", "main.py"]
