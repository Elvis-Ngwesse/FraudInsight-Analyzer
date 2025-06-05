import pika
import json
import os
import logging
import tempfile
import traceback
import signal
import re
from datetime import datetime
from urllib.parse import urlparse

from minio import Minio
from faster_whisper import WhisperModel
from influxdb_client import InfluxDBClient, Point, WritePrecision, BucketRetentionRules

# --- Logging ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')

def get_env_var(name):
    value = os.getenv(name)
    if value is None:
        raise EnvironmentError(f"Missing required environment variable: {name}")
    return value

# --- Env Variables ---
RABBITMQ_HOST = get_env_var("RABBITMQ_HOST")
RABBITMQ_PORT = int(get_env_var("RABBITMQ_PORT"))
RABBITMQ_USER = get_env_var("RABBITMQ_USER")
RABBITMQ_PASS = get_env_var("RABBITMQ_PASS")
RABBITMQ_VHOST = get_env_var("RABBITMQ_VHOST")
QUEUE_NAME = "voice_complaints"

MINIO_ENDPOINT = get_env_var("MINIO_ENDPOINT")
MINIO_ACCESS_KEY = get_env_var("MINIO_ACCESS_KEY")
MINIO_SECRET_KEY = get_env_var("MINIO_SECRET_KEY")
MINIO_BUCKET = get_env_var("MINIO_BUCKET")

INFLUXDB_URL = get_env_var("INFLUXDB_URL")
INFLUXDB_ORG = get_env_var("INFLUXDB_ORG")
INFLUXDB_BUCKET_VOICE_TOPIC = get_env_var("INFLUXDB_BUCKET")
INFLUXDB_TOKEN = get_env_var("INFLUXDB_TOKEN")

# --- Clients ---
minio_client = Minio(
    MINIO_ENDPOINT,
    access_key=MINIO_ACCESS_KEY,
    secret_key=MINIO_SECRET_KEY,
    secure=False,
)

if not minio_client.bucket_exists(MINIO_BUCKET):
    minio_client.make_bucket(MINIO_BUCKET)
    logging.info(f"Created MinIO bucket '{MINIO_BUCKET}'")
else:
    logging.info(f"MinIO bucket '{MINIO_BUCKET}' already exists")

# Use a bigger Whisper model for better transcription quality
whisper_model = WhisperModel("small", compute_type="int8")  # Change to "medium" or "large" if needed

influx_client = InfluxDBClient(url=INFLUXDB_URL, token=INFLUXDB_TOKEN, org=INFLUXDB_ORG)

# Ensure InfluxDB bucket exists
buckets_api = influx_client.buckets_api()
buckets = buckets_api.find_buckets().buckets
bucket_names = [b.name for b in buckets]

if INFLUXDB_BUCKET_VOICE_TOPIC not in bucket_names:
    retention = BucketRetentionRules(type="expire", every_seconds=0)
    buckets_api.create_bucket(
        bucket_name=INFLUXDB_BUCKET_VOICE_TOPIC,
        org=INFLUXDB_ORG,
        retention_rules=retention
    )
    logging.info(f"Created InfluxDB bucket '{INFLUXDB_BUCKET_VOICE_TOPIC}'")
else:
    logging.info(f"InfluxDB bucket '{INFLUXDB_BUCKET_VOICE_TOPIC}' already exists")

write_api = influx_client.write_api(write_precision=WritePrecision.NS)

# --- Transcript Cleaning ---
def clean_transcript(text: str) -> str:
    """Clean transcript text by removing sensitive data and noise."""

    # Remove phone numbers (various common formats, international and US)
    phone_pattern = re.compile(
        r'''(
            (\+?\d{1,3}[\s.-]?)?              # optional country code
            (\(?\d{3}\)?[\s.-]?)?             # optional area code
            \d{3}[\s.-]?\d{4}                 # main number
            (\s?(ext|x|extension)\s?\d{1,5})? # optional extension
        )''', re.VERBOSE)
    text = phone_pattern.sub('[PHONE]', text)

    # Remove email addresses (improved)
    email_pattern = re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b')
    text = email_pattern.sub('[EMAIL]', text)

    # Remove long digit sequences (e.g., IDs, account numbers)
    text = re.sub(r'\b\d{6,}\b', '[ID]', text)

    # Replace multiple commas with single comma
    text = re.sub(r',+', ',', text)
    # Separate misplaced commas surrounded by non-word characters
    text = re.sub(r'([^\w\s]),([^\w\s])', r'\1 \2', text)

    # Trim extra spaces
    text = re.sub(r'\s+', ' ', text).strip()

    return text

# --- Functions ---
def download_audio(object_name):
    # Parse full URL or object name to bucket and object key
    if object_name.startswith("http"):
        parsed_url = urlparse(object_name)
        path_parts = parsed_url.path.lstrip("/").split("/", 1)
        if len(path_parts) == 2:
            bucket = path_parts[0]
            obj = path_parts[1]
        else:
            bucket = MINIO_BUCKET
            obj = path_parts[0]
    else:
        bucket = MINIO_BUCKET
        obj = object_name

    with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as tmp_file:
        minio_client.fget_object(bucket, obj, tmp_file.name)
        logging.info(f"Downloaded object '{obj}' from bucket '{bucket}' to '{tmp_file.name}'")
        return tmp_file.name

stop_consuming = False
nack_count = 0
NACK_WARNING_THRESHOLD = 5

def signal_handler(sig, frame):
    global stop_consuming
    stop_consuming = True
    logging.info("Received termination signal. Stopping consumer...")

def on_message(channel, method, properties, body):
    global stop_consuming, nack_count
    delivery_tag = method.delivery_tag
    audio_path = None
    try:
        msg = json.loads(body)
        message_id = msg.get("id", "unknown")
        object_name = msg.get("object_name")
        scenario = msg.get("scenario", "unknown")
        customer_id = msg.get("customer_id", "unknown")
        channel_source = msg.get("channel", "unknown")

        if not object_name:
            raise ValueError("Missing 'object_name' in message")

        audio_path = download_audio(object_name)

        segments, info = whisper_model.transcribe(audio_path)
        # Log audio duration if available
        duration_seconds = None
        if info and isinstance(info, dict):
            duration_seconds = info.get('duration', None)
        if duration_seconds:
            minutes = int(duration_seconds // 60)
            seconds = duration_seconds % 60
            logging.info(f"Processing audio with duration {minutes:02d}:{seconds:05.2f}")
        # Log detected language if available
        language = None
        if info and isinstance(info, dict):
            language = info.get('language', None)
        if language:
            logging.info(f"Detected language '{language}'")

        raw_transcript = " ".join(segment.text for segment in segments).strip()
        cleaned = clean_transcript(raw_transcript)
        logging.info(f"Transcription complete. Raw: {raw_transcript[:200]}... Cleaned: {cleaned[:200]}...")

        point = (
            Point("voice_complaints_topic")
            .tag("message_id", message_id)
            .tag("scenario", scenario)
            .tag("customer_id", customer_id)
            .tag("channel", channel_source)
            .field("transcript", cleaned[:5000])
            .time(datetime.utcnow(), WritePrecision.NS)
        )
        write_api.write(bucket=INFLUXDB_BUCKET_VOICE_TOPIC, record=point)

        logging.info(f"Message {message_id} processed and written to InfluxDB")

        channel.basic_ack(delivery_tag=delivery_tag)
    except Exception:
        nack_count += 1
        logging.error(f"Error processing message:\n{traceback.format_exc()}")
        if nack_count >= NACK_WARNING_THRESHOLD:
            logging.warning(f"Number of NACKed messages reached {nack_count}. Investigate potential issues.")
        if channel.is_open:
            channel.basic_nack(delivery_tag=delivery_tag, requeue=False)
    finally:
        # Ensure cleanup of temp file
        if audio_path and os.path.exists(audio_path):
            os.remove(audio_path)

    if stop_consuming:
        channel.stop_consuming()

def connect_to_rabbitmq():
    params = pika.ConnectionParameters(
        host=RABBITMQ_HOST,
        port=RABBITMQ_PORT,
        virtual_host=RABBITMQ_VHOST,
        credentials=pika.PlainCredentials(RABBITMQ_USER, RABBITMQ_PASS),
        heartbeat=60,
        blocked_connection_timeout=600
    )
    return pika.BlockingConnection(params)

def main():
    conn = connect_to_rabbitmq()
    channel = conn.channel()
    channel.basic_qos(prefetch_count=1)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    channel.basic_consume(queue=QUEUE_NAME, on_message_callback=on_message, auto_ack=False)

    logging.info("Consumer started and waiting for messages...")
    try:
        channel.start_consuming()
    finally:
        if channel.is_open:
            channel.close()
        if conn.is_open:
            conn.close()
        logging.info("Consumer shutdown complete.")

if __name__ == "__main__":
    main()
