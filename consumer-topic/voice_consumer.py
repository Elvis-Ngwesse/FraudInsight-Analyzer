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
from influxdb_client import InfluxDBClient, Point, WritePrecision, BucketRetentionRules
from sentence_transformers import SentenceTransformer
import joblib

# --- Logging ---
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
RETRY_DELAY = 5
HEARTBEAT_INTERVAL = 60

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

whisper_model = whisper.load_model("base")

topic_model_path = "bertopic_model"
if os.path.exists(topic_model_path):
    topic_model = joblib.load(topic_model_path)
    logging.info("Loaded BERTopic model from disk.")
else:
    logging.warning("No BERTopic model found. Creating an untrained one.")
    embedding_model = SentenceTransformer("all-mpnet-base-v2")
    topic_model = BERTopic(embedding_model=embedding_model, language="english", calculate_probabilities=True)
    logging.warning("Model is untrained. Fit and save it using joblib to 'bertopic_model' before use.")

influx_client = InfluxDBClient(
    url=INFLUXDB_URL_LOCAL,
    token=INFLUXDB_TOKEN,
    org=INFLUXDB_ORG
)
write_api = influx_client.write_api(write_precision=WritePrecision.NS)

buckets_api = influx_client.buckets_api()
buckets = buckets_api.find_buckets().buckets
if not any(b.name == INFLUXDB_BUCKET_VOICE_TOPIC for b in buckets):
    retention = BucketRetentionRules(type="expire", every_seconds=0)
    buckets_api.create_bucket(bucket_name=INFLUXDB_BUCKET_VOICE_TOPIC, org=INFLUXDB_ORG, retention_rules=retention)
    logging.info(f"Created InfluxDB bucket '{INFLUXDB_BUCKET_VOICE_TOPIC}'")
else:
    logging.info(f"InfluxDB bucket '{INFLUXDB_BUCKET_VOICE_TOPIC}' already exists")

def download_audio(object_name):
    if object_name.startswith("http://") or object_name.startswith("https://"):
        object_name = urlparse(object_name).path.lstrip("/")
        logging.info(f"Parsed object name: {object_name}")
    try:
        stat = minio_client.stat_object(MINIO_BUCKET, object_name)
        logging.info(f"Object '{object_name}' found, size: {stat.size} bytes")
        with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as tmp_file:
            minio_client.fget_object(MINIO_BUCKET, object_name, tmp_file.name)
            logging.info(f"Downloaded audio to '{tmp_file.name}'")
            if os.path.getsize(tmp_file.name) == 0:
                raise Exception("Downloaded file is empty")
            with wave.open(tmp_file.name, "rb") as wav_file:
                logging.info(f"WAV params: channels={wav_file.getnchannels()}, framerate={wav_file.getframerate()}")
            return tmp_file.name
    except Exception as e:
        raise Exception(f"Download failed: {e}")

def predict_topic(text):
    if not text:
        return -1, "No transcript", 0.0
    try:
        topics, probs = topic_model.transform([text])
        topic_id = topics[0]
        prob = probs[0][topic_id] if probs and len(probs[0]) > topic_id and topic_id != -1 else 0.0
        topic_name = topic_model.get_topic(topic_id)
        if topic_name is None or topic_id == -1:
            return -1, "Unknown", prob
        words = [w for w, _ in topic_name]
        return topic_id, ", ".join(words[:5]), prob
    except Exception as e:
        logging.warning(f"BERTopic error: {e}")
        return -1, "Error", 0.0

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
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            logging.info(f"Connecting to RabbitMQ (attempt {attempt})...")
            conn = pika.BlockingConnection(parameters)
            logging.info("Connected.")
            return conn
        except pika.exceptions.AMQPConnectionError as e:
            logging.warning(f"RabbitMQ error: {e}, retrying in {RETRY_DELAY}s")
            time.sleep(RETRY_DELAY)
    raise ConnectionError("RabbitMQ unavailable after retries")

stop_consuming = False
def signal_handler(sig, frame):
    global stop_consuming
    logging.info("Interrupt received, stopping consumer...")
    stop_consuming = True

def on_message(channel, method, properties, body):
    global stop_consuming
    delivery_tag = method.delivery_tag
    try:
        message = json.loads(body)
        message_id = message.get("id", "unknown")
        object_name = message.get("object_name")
        scenario = message.get("scenario", "unknown")
        customer_id = message.get("customer_id", "unknown")
        channel_source = message.get("channel", "unknown")

        logging.info(f"Processing message {message_id} from scenario '{scenario}'")

        if not object_name:
            raise ValueError("No object_name in message")

        audio_path = download_audio(object_name)
        result = whisper_model.transcribe(audio_path)
        transcript = result.get("text", "").strip()
        os.remove(audio_path)

        if not transcript:
            raise ValueError(f"No transcript for message {message_id}")

        topic_id, topic_summary, topic_prob = predict_topic(transcript)
        logging.info(f"Topic {topic_id}: {topic_summary} ({topic_prob:.3f})")

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

        write_api.write(bucket=INFLUXDB_BUCKET_VOICE_TOPIC, record=point)
        logging.info(f"Stored result for message {message_id}")
        channel.basic_ack(delivery_tag=delivery_tag)
    except Exception:
        logging.error("Error processing message:\n%s", traceback.format_exc())
        if channel.is_open:
            try:
                channel.basic_nack(delivery_tag=delivery_tag, requeue=False)
            except Exception as nack_err:
                logging.warning(f"Failed to nack: {nack_err}")
    if stop_consuming:
        channel.stop_consuming()

def main():
    connection = connect_to_rabbitmq()
    channel = connection.channel()
    channel.basic_qos(prefetch_count=1)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    channel.basic_consume(queue=QUEUE_NAME, on_message_callback=on_message, auto_ack=False)
    logging.info(f"Listening on queue '{QUEUE_NAME}'...")

    try:
        channel.start_consuming()
    except Exception as e:
        logging.error(f"Consumer stopped: {e}")
    finally:
        if channel.is_open:
            channel.close()
        if connection.is_open:
            connection.close()
        logging.info("Shutdown complete.")

if __name__ == "__main__":
    main()
