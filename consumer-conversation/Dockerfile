FROM python:3.10-slim

WORKDIR /app

COPY requirements.txt .

# Install ffmpeg and dependencies, then install python dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg curl && \
    pip install --no-cache-dir -r requirements.txt && \
    rm -rf /var/lib/apt/lists/*

# Download spaCy English model
RUN python -m spacy download en_core_web_sm

COPY . .

CMD ["python", "text_consumer.py"]
