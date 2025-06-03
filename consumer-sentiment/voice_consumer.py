import pika
import json
import os
import logging
import tempfile
import wave
import time
import traceback
from minio import Minio
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
import whisper
from influxdb_client import InfluxDBClient, Point, WritePrecision
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')

def get_env_var(name):
    value = os.getenv(name)
    if value is None:
        raise EnvironmentError(f"Missing required environment variable: {name}")
    return value

# --- Environment variables ---
# Config from env, no defaults allowed:
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

minio_client = Minio(
    MINIO_ENDPOINT,
    access_key=MINIO_ACCESS_KEY,
    secret_key=MINIO_SECRET_KEY,
    secure=False,
)

analyzer = SentimentIntensityAnalyzer()
whisper_model = whisper.load_model("base")

influx_client = InfluxDBClient(url=INFLUXDB_URL_LOCAL, token=INFLUXDB_TOKEN, org=INFLUXDB_ORG)
write_api = influx_client.write_api(write_precision=WritePrecision.NS)


def ensure_bucket_exists(client, bucket_name, org):
    buckets_api = client.buckets_api()
    existing_buckets = buckets_api.find_buckets().buckets
    if any(bucket.name == bucket_name for bucket in existing_buckets):
        logging.info(f"Bucket '{bucket_name}' already exists.")
    else:
        logging.info(f"Bucket '{bucket_name}' not found. Creating it...")
        buckets_api.create_bucket(bucket_name=bucket_name, org=org)
        logging.info(f"Bucket '{bucket_name}' created.")


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


def callback(ch, method, properties, body):
    audio_path = None
    try:
        logging.info(f"Received message from queue '{QUEUE_NAME}': {body}")
        message = json.loads(body)
        logging.info(f"Message JSON parsed: {message}")

        message_id = message.get("message_id", "unknown")
        object_name = message.get("object_name")

        if not object_name:
            raise ValueError(f"Message {message_id} missing 'object_name' field")

        audio_path = download_audio(object_name)

        result = whisper_model.transcribe(audio_path)
        logging.info(f"Whisper transcription result: {result}")

        transcript = result.get("text", "").strip()
        logging.info(f"Transcript for {message_id}: '{transcript}'")

        if not transcript:
            logging.warning(f"Empty transcript for message {message_id}")

        sentiment = analyzer.polarity_scores(transcript)
        logging.info(f"Sentiment for {message_id}: {sentiment}")

        point = (
            Point("voice_complaints")
            .tag("message_id", message_id)
            .field("transcript", transcript)
            .field("neg", sentiment["neg"])
            .field("neu", sentiment["neu"])
            .field("pos", sentiment["pos"])
            .field("compound", sentiment["compound"])
        )

        try:
            write_api.write(bucket=INFLUXDB_BUCKET_VOICE, record=point)
            logging.info(f"Written point to InfluxDB: {point}")
        except Exception as e:
            logging.error(f"InfluxDB write failed: {e}")

        ch.basic_ack(delivery_tag=method.delivery_tag)

    except Exception:
        logging.error(f"Failed to process message:\n{traceback.format_exc()}")
        ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)
    finally:
        if audio_path and os.path.exists(audio_path):
            try:
                os.remove(audio_path)
                logging.info(f"Deleted temporary audio file: {audio_path}")
            except Exception as e:
                logging.warning(f"Could not remove temp audio file {audio_path}: {e}")


def connect_to_rabbitmq():
    delay = RETRY_DELAY
    parameters = pika.ConnectionParameters(
        host=RABBITMQ_HOST,
        port=RABBITMQ_PORT,
        virtual_host=RABBITMQ_VHOST,
        credentials=pika.PlainCredentials(RABBITMQ_USER, RABBITMQ_PASS),
        heartbeat=HEARTBEAT_INTERVAL,
        blocked_connection_timeout=300,
        connection_attempts=MAX_RETRIES,
        retry_delay=RETRY_DELAY,
    )
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            logging.info(f"Connecting to RabbitMQ at {RABBITMQ_HOST_LOCAL}:{RABBITMQ_PORT} (attempt {attempt})")
            connection = pika.BlockingConnection(parameters)
            logging.info("Connected to RabbitMQ.")
            return connection
        except pika.exceptions.AMQPConnectionError as e:
            logging.warning(f"RabbitMQ not ready: {e}. Retrying in {delay}s...")
            time.sleep(delay)
            delay = min(delay * 2, 60)
    raise ConnectionError(f"Could not connect to RabbitMQ at {RABBITMQ_HOST_LOCAL} after {MAX_RETRIES} attempts")


def main():
    ensure_bucket_exists(influx_client, INFLUXDB_BUCKET_VOICE, INFLUXDB_ORG)

    connection = connect_to_rabbitmq()
    channel = connection.channel()
    channel.queue_declare(queue=QUEUE_NAME, durable=True)
    channel.basic_qos(prefetch_count=1)
    channel.basic_consume(queue=QUEUE_NAME, on_message_callback=callback)
    logging.info("Waiting for voice complaints...")
    try:
        channel.start_consuming()
    except KeyboardInterrupt:
        logging.info("Interrupted by user, shutting down...")
    finally:
        connection.close()
        influx_client.close()


if __name__ == "__main__":
    main()
