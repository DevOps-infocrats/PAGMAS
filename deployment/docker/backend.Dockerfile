FROM python:3.11-slim

WORKDIR /app

# 1. Install required system compilation dependencies for gevent & numpy
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

# 2. Upgrade pip and build tools to handle modern version hashes correctly
RUN pip install --no-cache-dir --upgrade pip setuptools wheel

COPY requirements.txt .

# 3. Install Python requirements with a clean cache
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4"]
