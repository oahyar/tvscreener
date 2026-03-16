# Use a slim Python image for a smaller footprint
FROM python:3.11-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=off

# Set the working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    git \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements if they exist separately, otherwise use pyproject.toml
COPY pyproject.toml README.md ./
COPY tvscreener/ ./tvscreener/

# Install the package with MCP support and tabulate for scripts
RUN pip install --upgrade pip && \
    pip install ".[mcp]" tabulate "python-telegram-bot>=20.0"

# Create a non-root user for security
RUN useradd -m appuser && chown -R appuser /app
USER appuser

# Expose no ports by default as MCP often communicates via stdio, 
# but could be used for other things later.

# Default command to run the MCP server
CMD ["tvscreener-mcp"]
