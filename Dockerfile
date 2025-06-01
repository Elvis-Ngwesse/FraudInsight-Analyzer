FROM python:3.11-slim

# Install dependencies for pyttsx3 to work (including espeak)
RUN apt-get update && apt-get install -y \
    espeak \
    ffmpeg \
    libespeak1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["python", "text_producer.py"]
