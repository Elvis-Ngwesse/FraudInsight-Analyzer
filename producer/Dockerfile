FROM python:3.11-slim

# Install system dependencies for audio processing and TTS phonemizer
RUN apt-get update && apt-get install -y \
    ffmpeg \
    libsndfile1 \
    git \
    gcc \
    g++ \
    build-essential \
    espeak-ng \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Set working directory
WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Run your voice producer
CMD ["python", "voice_producer.py"]
