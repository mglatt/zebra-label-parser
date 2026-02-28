FROM python:3.12-slim

# Install CUPS client libraries and build deps for pycups
RUN apt-get update && apt-get install -y --no-install-recommends \
    libcups2-dev \
    cups-client \
    cups \
    gcc \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies
COPY pyproject.toml ./
RUN pip install --no-cache-dir ".[cups]"

# Copy application code
COPY app/ ./app/
COPY docker/entrypoint.sh ./entrypoint.sh
COPY docker/cupsd.conf /etc/cups/cupsd.conf

RUN chmod +x /entrypoint.sh

EXPOSE 8099
EXPOSE 631

ENTRYPOINT ["/entrypoint.sh"]
