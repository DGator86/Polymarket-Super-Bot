# Polymarket Hybrid Bot Dockerfile
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY src/ ./src/
COPY markets.json .

# Create directory for database
RUN mkdir -p /app/data

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV DB_PATH=/app/data/bot_state.db

# Run as non-root user for security
RUN useradd -m -u 1000 botuser && \
    chown -R botuser:botuser /app
USER botuser

# Run the bot
CMD ["python", "-m", "src.app"]
