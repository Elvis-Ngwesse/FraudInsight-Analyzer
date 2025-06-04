import pika
import json
import os
import logging
import tempfile
import wave
import time
import traceback
from datetime import datetime

from minio import Minio
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
import whisper
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
INFLUXDB_BUCKET_VOICE = get_env_var("INFLUXDB_BUCKET")
INFLUXDB_TOKEN = get_env_var("INFLUXDB_TOKEN")

MAX_RETRIES = 5
RETRY_DELAY = 5  # seconds
HEARTBEAT_INTERVAL = 60  # seconds

# --- Clients ---
minio_client = Minio(MINIO_ENDPOINT, access_key=MINIO_ACCESS_KEY, secret_key=MINIO_SECRET_KEY, secure=False)
analyzer = SentimentIntensityAnalyzer()
whisper_model = whisper.load_model("base")
influx_client = InfluxDBClient(url=INFLUXDB_URL_LOCAL, token=INFLUXDB_TOKEN, org=INFLUXDB_ORG)
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

# --- Download and Validate Audio ---
def download_audio(object_name):
    try:
        stat = minio_client.stat_object(MINIO_BUCKET, object_name)
        logging.info(f"Object '{object_name}' found in MinIO bucket '{MINIO_BUCKET}', size: {stat.size} bytes")

        with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as tmp_file:
            minio_client.fget_object(MINIO_BUCKET, object_name, tmp_file.name)
            logging.info(f"Downloaded audio: {object_name} -> {tmp_file.name}")

            if os.path.getsize(tmp_file.name) == 0:
                raise Exception("Downloaded file is empty")

            with wave.open(tmp_file.name, "rb") as wav_file:
                logging.info(f"WAV params: channels={wav_file.getnchannels()}, "
                             f"framerate={wav_file.getframerate()}, frames={wav_file.getnframes()}")

            return tmp_file.name
    except Exception as e:
        raise Exception(f"Download or validation failed: {e}")

# --- RabbitMQ Message Callback ---
def callback(ch, method, properties, body):
    audio_path = None
    message_id = "unknown"
    try:
        logging.info(f"Received message: {body}")
        message = json.loads(body)
        message_id = message.get("id") or message.get("message_id") or "unknown"
        object_name = message.get("object_name")

        if not object_name:
            raise ValueError(f"Message {message_id} missing 'object_name'")

        scenario = message.get("scenario", "unknown")
        customer_id = message.get("customer_id", "unknown")
        channel_source = message.get("channel", "unknown")

        # Transcribe audio
        audio_path = download_audio(object_name)
        result = whisper_model.transcribe(audio_path)
        transcript = result.get("text", "").strip()

        if not transcript:
            raise ValueError(f"Empty transcript for message {message_id}")

        sentiment = analyzer.polarity_scores(transcript)

        # InfluxDB point creation
        point = (
            Point("voice_complaints")
            .tag("message_id", message_id)
            .tag("scenario", scenario)
            .tag("customer_id", customer_id)
            .tag("channel", channel_source)
            .field("transcript", transcript[:5000])
            .field("neg", sentiment["neg"])
            .field("neu", sentiment["neu"])
            .field("pos", sentiment["pos"])
            .field("compound", sentiment["compound"])
            .time(datetime.utcnow(), WritePrecision.NS)
        )

        write_api.write(bucket=INFLUXDB_BUCKET_VOICE, record=point)
        logging.info(f"Wrote point for message {message_id}")

        if ch.is_open:
            ch.basic_ack(delivery_tag=method.delivery_tag)
            logging.info(f"Acknowledged message {message_id}")

    except Exception:
        logging.error(f"Error processing message {message_id}:\n{traceback.format_exc()}")
        if ch.is_open:
            ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)
            logging.info(f"Rejected message {message_id}")

    finally:
        if audio_path and os.path.exists(audio_path):
            try:
                os.remove(audio_path)
                logging.info(f"Deleted temp audio file: {audio_path}")
            except Exception as e:
                logging.warning(f"Could not delete temp file {audio_path}: {e}")

# --- RabbitMQ Connection ---
def connect_to_rabbitmq():
    parameters = pika.ConnectionParameters(
        host=RABBITMQ_HOST_LOCAL,
        port=RABBITMQ_PORT,
        virtual_host=RABBITMQ_VHOST,
        credentials=pika.PlainCredentials(RABBITMQ_USER, RABBITMQ_PASS),
        heartbeat=HEARTBEAT_INTERVAL,
        blocked_connection_timeout=300,
        connection_attempts=MAX_RETRIES,
        retry_delay=RETRY_DELAY,
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

# --- Main Loop ---
def main():
    ensure_bucket_exists(influx_client, INFLUXDB_BUCKET_VOICE, INFLUXDB_ORG)

    while True:
        connection = None
        try:
            connection = connect_to_rabbitmq()
            channel = connection.channel()
            channel.queue_declare(queue=QUEUE_NAME, durable=True)
            channel.basic_qos(prefetch_count=1)
            channel.basic_consume(queue=QUEUE_NAME, on_message_callback=callback)

            logging.info("Waiting for voice complaints...")
            channel.start_consuming()

        except (pika.exceptions.StreamLostError, pika.exceptions.AMQPConnectionError) as e:
            logging.warning(f"Connection issue: {e}. Reconnecting in {RETRY_DELAY} seconds...")
            time.sleep(RETRY_DELAY)

        except KeyboardInterrupt:
            logging.info("Interrupted. Shutting down...")
            break

        except Exception:
            logging.error(f"Unexpected error:\n{traceback.format_exc()}")
            time.sleep(RETRY_DELAY)

        finally:
            if connection and not connection.is_closed:
                try:
                    connection.close()
                except Exception:
                    pass

    influx_client.close()

if __name__ == "__main__":
    main()
