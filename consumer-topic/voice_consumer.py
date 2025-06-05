import pika
import json
import os
import logging
import tempfile
import wave
import time
import traceback
import signal
from datetime import datetime
from urllib.parse import urlparse

from minio import Minio
import whisper
from bertopic import BERTopic
from influxdb_client import InfluxDBClient, Point, WritePrecision

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')

# --- Utility ---
def get_env_var(name):
    value = os.getenv(name)
    if value is None:
        raise EnvironmentError(f"Missing required environment variable: {name}")
    return value

# --- Environment Variables ---
RABBITMQ_HOST_LOCAL = get_env_var("RABBITMQ_HOST")
RABBITMQ_PORT = int(get_env_var("RABBITMQ_PORT"))
RABBITMQ_USER = get_env_var("RABBITMQ_USER")
RABBITMQ_PASS = get_env_var("RABBITMQ_PASS")
RABBITMQ_VHOST = get_env_var("RABBITMQ_VHOST")
QUEUE_NAME = "voice_complaints"

MINIO_ENDPOINT = get_env_var("MINIO_ENDPOINT")
MINIO_ACCESS_KEY = get_env_var("MINIO_ACCESS_KEY")
MINIO_SECRET_KEY = get_env_var("MINIO_SECRET_KEY")
MINIO_BUCKET = get_env_var("MINIO_BUCKET")

INFLUXDB_URL_LOCAL = get_env_var("INFLUXDB_URL")
INFLUXDB_ORG = get_env_var("INFLUXDB_ORG")
INFLUXDB_BUCKET_VOICE_TOPIC = get_env_var("INFLUXDB_BUCKET")
INFLUXDB_TOKEN = get_env_var("INFLUXDB_TOKEN")

MAX_RETRIES = 5
RETRY_DELAY = 5  # seconds
HEARTBEAT_INTERVAL = 60  # seconds

# --- Clients ---
minio_client = Minio(
    MINIO_ENDPOINT,
    access_key=MINIO_ACCESS_KEY,
    secret_key=MINIO_SECRET_KEY,
    secure=False,
)

whisper_model = whisper.load_model("base")

# Load your pretrained BERTopic model or create a new one here.
topic_model_path = "bertopic_model"
if os.path.exists(topic_model_path):
    import joblib
    topic_model = joblib.load(topic_model_path)
    logging.info("Loaded BERTopic model from disk.")
else:
    topic_model = BERTopic(language="english", calculate_probabilities=True)
    logging.warning("No BERTopic model found. Using untrained model; fit before use.")

influx_client = InfluxDBClient(
    url=INFLUXDB_URL_LOCAL,
    token=INFLUXDB_TOKEN,
    org=INFLUXDB_ORG
)
write_api = influx_client.write_api(write_precision=WritePrecision.NS)

# --- Ensure InfluxDB Bucket Exists ---
def ensure_bucket_exists(client, bucket_name, org):
    buckets_api = client.buckets_api()
    existing_buckets = buckets_api.find_buckets().buckets
    if any(bucket.name == bucket_name for bucket in existing_buckets):
        logging.info(f"Bucket '{bucket_name}' already exists.")
    else:
        logging.info(f"Bucket '{bucket_name}' not found. Creating it...")
        buckets_api.create_bucket(bucket_name=bucket_name, org=org)
        logging.info(f"Bucket '{bucket_name}' created.")

# --- Download and Validate Audio from MinIO ---
def download_audio(object_name):
    # If object_name is a full URL, extract the object key
    if object_name.startswith("http://") or object_name.startswith("https://"):
        parsed = urlparse(object_name)
        object_name = parsed.path.lstrip("/")
        logging.info(f"Extracted object name from URL: {object_name}")

    try:
        # Check if object exists
        stat = minio_client.stat_object(MINIO_BUCKET, object_name)
        logging.info(f"Object '{object_name}' found in bucket '{MINIO_BUCKET}', size: {stat.size} bytes")

        with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as tmp_file:
            minio_client.fget_object(MINIO_BUCKET, object_name, tmp_file.name)
            logging.info(f"Downloaded audio '{object_name}' to '{tmp_file.name}'")

            if os.path.getsize(tmp_file.name) == 0:
                raise Exception("Downloaded file is empty")

            with wave.open(tmp_file.name, "rb") as wav_file:
                logging.info(f"WAV file params: channels={wav_file.getnchannels()}, "
                             f"framerate={wav_file.getframerate()}, frames={wav_file.getnframes()}")

            return tmp_file.name

    except Exception as e:
        raise Exception(f"Download or validation failed: {e}")

# --- Predict topic with BERTopic ---
def predict_topic(text):
    if not text:
        return -1, "No transcript", 0.0

    topics, probs = topic_model.transform([text])
    topic_id = topics[0]
    prob = probs[0][topic_id] if probs and len(probs[0]) > topic_id and topic_id != -1 else 0.0
    topic_name = topic_model.get_topic(topic_id)
    if topic_name is None or topic_id == -1:
        return -1, "Unknown", prob

    words = [w for w, _ in topic_name]
    topic_summary = ", ".join(words[:5])
    return topic_id, topic_summary, prob

# --- Connect to RabbitMQ with retry ---
def connect_to_rabbitmq():
    parameters = pika.ConnectionParameters(
        host=RABBITMQ_HOST_LOCAL,
        port=RABBITMQ_PORT,
        virtual_host=RABBITMQ_VHOST,
        credentials=pika.PlainCredentials(RABBITMQ_USER, RABBITMQ_PASS),
        heartbeat=HEARTBEAT_INTERVAL,
        blocked_connection_timeout=600,
        connection_attempts=MAX_RETRIES,
        retry_delay=RETRY_DELAY,
        socket_timeout=600,
    )
    delay = RETRY_DELAY
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            logging.info(f"Connecting to RabbitMQ (attempt {attempt})...")
            conn = pika.BlockingConnection(parameters)
            logging.info("Connected to RabbitMQ.")
            return conn
        except pika.exceptions.AMQPConnectionError as e:
            logging.warning(f"RabbitMQ not ready: {e}. Retrying in {delay}s...")
            time.sleep(delay)
            delay = min(delay * 2, 60)
    raise ConnectionError("Failed to connect to RabbitMQ after max retries")

# --- Graceful shutdown ---
stop_consuming = False

def signal_handler(sig, frame):
    global stop_consuming
    logging.info("Signal received, stopping consumer...")
    stop_consuming = True

# --- RabbitMQ message callback ---
def on_message(channel, method, properties, body):
    global stop_consuming
    delivery_tag = method.delivery_tag

    try:
        message = json.loads(body)
        message_id = message.get("id") or message.get("message_id") or "unknown"
        object_name = message.get("object_name")
        scenario = message.get("scenario", "unknown")
        customer_id = message.get("customer_id", "unknown")
        channel_source = message.get("channel", "unknown")

        logging.info(f"Received message {message_id} for scenario '{scenario}'")

        if not object_name:
            raise ValueError(f"Message {message_id} missing 'object_name'")

        # Download audio from MinIO
        audio_path = download_audio(object_name)

        # Transcribe with Whisper
        result = whisper_model.transcribe(audio_path)
        transcript = result.get("text", "").strip()

        # Clean up temp audio file
        try:
            os.remove(audio_path)
        except Exception:
            logging.warning(f"Failed to delete temp audio file {audio_path}")

        if not transcript:
            raise ValueError(f"Empty transcript for message {message_id}")

        # Predict topic cluster
        topic_id, topic_summary, topic_prob = predict_topic(transcript)
        logging.info(f"Predicted topic {topic_id}: {topic_summary} (prob={topic_prob:.3f})")

        # Build InfluxDB point
        point = (
            Point("voice_complaints_topic")
            .tag("message_id", message_id)
            .tag("scenario", scenario)
            .tag("customer_id", customer_id)
            .tag("channel", channel_source)
            .field("transcript", transcript[:5000])
            .field("topic_id", topic_id)
            .field("topic_summary", topic_summary)
            .field("topic_probability", float(topic_prob))
            .time(datetime.utcnow(), WritePrecision.NS)
        )

        # Write to InfluxDB
        write_api.write(bucket=INFLUXDB_BUCKET_VOICE_TOPIC, record=point)
        logging.info(f"Wrote topic modeling data for message {message_id}")

        # Acknowledge message
        channel.basic_ack(delivery_tag=delivery_tag)
        logging.info(f"Acknowledged message {message_id}")

    except Exception:
        logging.error("Error processing message:\n%s", traceback.format_exc())
        if channel.is_open:
            try:
                channel.basic_nack(delivery_tag=delivery_tag, requeue=False)
                logging.info(f"Rejected message {delivery_tag}")
            except Exception as nack_err:
                logging.warning(f"Failed to nack message: {nack_err}")

    if stop_consuming:
        channel.stop_consuming()

def main():
    ensure_bucket_exists(influx_client, INFLUXDB_BUCKET_VOICE_TOPIC, INFLUXDB_ORG)

    connection = connect_to_rabbitmq()
    channel = connection.channel()

    # Declare queue durable in case it doesn't exist
    channel.queue_declare(queue=QUEUE_NAME, durable=True)

    # QoS: one message at a time
    channel.basic_qos(prefetch_count=1)

    # Setup graceful shutdown signals
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    channel.basic_consume(queue=QUEUE_NAME, on_message_callback=on_message, auto_ack=False)

    logging.info(f"Waiting for messages on queue '{QUEUE_NAME}'. To exit press CTRL+C")
    try:
        channel.start_consuming()
    except Exception as e:
        logging.error(f"Consumer stopped with error: {e}")
    finally:
        if channel.is_open:
            channel.close()
        if connection.is_open:
            connection.close()
        logging.info("Connection closed, exiting")

if __name__ == "__main__":
    main()
