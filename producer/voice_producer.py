import os
import uuid
import json
import time
import logging
import pika
import boto3
import redis
import tempfile
from datetime import datetime
from TTS.api import TTS
from utils import generate_dialogue  # your own module

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    force=True
)

# Environment Variables
RABBITMQ_HOST = os.getenv("RABBITMQ_HOST")
VOICE_QUEUE = "voice_complaints"

MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT")
MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY")
MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY")
MINIO_BUCKET = os.getenv("MINIO_BUCKET")

REDIS_HOST_LOCAL = os.getenv("REDIS_HOST")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))

MAX_RETRIES = 10
RETRY_DELAY = 2
MESSAGE_LENGHT = 30

# MinIO (S3-compatible) client setup
s3 = boto3.client(
    "s3",
    endpoint_url=f"http://{MINIO_ENDPOINT}",
    aws_access_key_id=MINIO_ACCESS_KEY,
    aws_secret_access_key=MINIO_SECRET_KEY,
)

# Ensure MinIO bucket exists
try:
    s3.head_bucket(Bucket=MINIO_BUCKET)
    logging.info(f"[MinIO] Bucket '{MINIO_BUCKET}' exists")
except s3.exceptions.ClientError as e:
    error_code = int(e.response['Error']['Code'])
    if error_code == 404:
        logging.info(f"[MinIO] Bucket '{MINIO_BUCKET}' not found, creating it")
        s3.create_bucket(Bucket=MINIO_BUCKET)
    else:
        logging.error(f"[MinIO] Bucket access error: {e}")

# Load multi-speaker TTS model
logging.info("[TTS] Loading TTS model: 'tts_models/en/vctk/vits'")
tts = TTS("tts_models/en/vctk/vits")


def clean_text(text):
    return text.replace("’", "'").replace("“", '"').replace("”", '"')


def split_into_chunks(dialogue, max_chars=250):
    import re
    sentence_pattern = re.compile(r'(?<=[.!?]) +')
    current_chunk = ""
    for line in dialogue:
        line = clean_text(line.strip())
        if not line or line == ".":
            continue
        for sentence in sentence_pattern.split(line):
            sentence = sentence.strip()
            if not sentence:
                continue
            if len(current_chunk) + len(sentence) + 1 <= max_chars:
                current_chunk += " " + sentence
            else:
                yield current_chunk.strip()
                current_chunk = sentence
    if current_chunk.strip():
        yield current_chunk.strip()


def connect_to_rabbitmq():
    for attempt in range(10):
        try:
            logging.info(f"[RabbitMQ] Connecting to {RABBITMQ_HOST} (attempt {attempt + 1})")
            connection = pika.BlockingConnection(pika.ConnectionParameters(host=RABBITMQ_HOST))
            channel = connection.channel()
            logging.info("[RabbitMQ] Connection established")
            # Declare voice_complaints queue with no DLQ or exchanges
            channel.queue_declare(queue=VOICE_QUEUE, durable=True)
            return channel
        except pika.exceptions.AMQPConnectionError:
            logging.warning("[RabbitMQ] Connection failed, retrying in 2s")
            time.sleep(2)
    raise RuntimeError("[RabbitMQ] Failed to connect after 10 attempts")


def connect_to_redis():
    for attempt in range(MAX_RETRIES):
        try:
            logging.info(f"[Redis] Connecting to {REDIS_HOST_LOCAL}:{REDIS_PORT} (attempt {attempt + 1})")
            redis_client = redis.Redis(host=REDIS_HOST_LOCAL, port=REDIS_PORT, db=0)
            redis_client.ping()
            logging.info("[Redis] Connection established")
            return redis_client
        except redis.exceptions.ConnectionError as e:
            logging.warning(f"[Redis] Connection failed: {e}")
            time.sleep(RETRY_DELAY)
    raise Exception("[Redis] Failed to connect after retries")


def generate_and_upload_audio(dialogue_lines, audio_id):
    logging.info(f"[Audio] Generating TTS chunks for audio_id: {audio_id}")
    chunks = list(split_into_chunks(dialogue_lines))
    logging.info(f"[Audio] {len(chunks)} chunks prepared for synthesis")

    with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as temp_file:
        temp_path = temp_file.name

    speaker_id = "p225"
    logging.info(f"[TTS] Synthesizing audio using speaker: '{speaker_id}'")
    tts.tts_to_file(
        text="\n".join(chunks),
        file_path=temp_path,
        speaker=speaker_id
    )

    minio_key = f"{audio_id}.wav"
    with open(temp_path, "rb") as f:
        s3.upload_fileobj(f, MINIO_BUCKET, minio_key)
    os.remove(temp_path)

    audio_url = f"http://{MINIO_ENDPOINT}/{MINIO_BUCKET}/{minio_key}"
    logging.info(f"[MinIO] Uploaded audio to: {audio_url}")
    return audio_url


def main():
    channel = connect_to_rabbitmq()
    redis_client = connect_to_redis()

    scenario_names = ["fraud", "card_issue", "login_problem"]

    for i in range(2000):
        scenario = scenario_names[i % len(scenario_names)]
        audio_id = f"voice-{uuid.uuid4()}-{int(time.time())}"
        logging.info(f"[{i + 1}/2000] Creating voice complaint for scenario: '{scenario}', ID: {audio_id}")

        dialogue_text = generate_dialogue(MESSAGE_LENGHT)
        logging.info(f"[Dialogue] Generated {MESSAGE_LENGHT}-line dialogue for scenario: {scenario}")

        audio_url = generate_and_upload_audio(dialogue_text.splitlines(), audio_id)

        object_name = f"{audio_id}.wav"

        payload = {
            "id": audio_id,
            "timestamp": datetime.utcnow().isoformat(),
            "audio_url": audio_url,
            "object_name": object_name,
            "scenario": scenario,
        }

        channel.basic_publish(
            exchange="",
            routing_key=VOICE_QUEUE,
            body=json.dumps(payload),
            properties=pika.BasicProperties(delivery_mode=2),
        )
        logging.info(f"[RabbitMQ] ✅ Pushed complaint to queue '{VOICE_QUEUE}' with ID: {audio_id}")

        redis_key = f"voice:{audio_id}"
        redis_client.set(redis_key, json.dumps(payload))
        logging.info(f"[Redis] 📝 Stored metadata with key: {redis_key}")

        time.sleep(0.5)

    logging.info("🎉 All complaints sent successfully.")


if __name__ == "__main__":
    main()
