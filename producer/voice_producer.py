import pika
import json
import time
import redis
import logging
import os
import tempfile
import traceback
import pyttsx3
from minio import Minio
from minio.error import S3Error
from pydub import AudioSegment
import wave
from utils import generate_customer, generate_dialogue

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
def get_env(key, default=None, required=False):
    value = os.getenv(key, default)
    if required and value is None:
        raise EnvironmentError(f"Missing required environment variable: {key}")
    return value

RABBITMQ_HOST = get_env("RABBITMQ_HOST", required=True)
REDIS_HOST = get_env("REDIS_HOST", required=True)
REDIS_PORT = int(get_env("REDIS_PORT", required=True))
MINIO_ENDPOINT = get_env("MINIO_ENDPOINT", required=True)
MINIO_ACCESS_KEY = get_env("MINIO_ACCESS_KEY", required=True)
MINIO_SECRET_KEY = get_env("MINIO_SECRET_KEY", required=True)
MINIO_BUCKET = get_env("MINIO_BUCKET", required=True)
QUEUE_NAME = 'voice_complaints'
MAX_RETRIES = 5         # max retries for TTS or connections
RETRY_DELAY = 5         # initial retry delay in seconds
HEARTBEAT_INTERVAL = 120
DELAY_BETWEEN_MESSAGES = 60  # seconds

# --- MinIO client setup ---
minio_client = Minio(
    MINIO_ENDPOINT,
    access_key=MINIO_ACCESS_KEY,
    secret_key=MINIO_SECRET_KEY,
    secure=False
)

if not minio_client.bucket_exists(MINIO_BUCKET):
    minio_client.make_bucket(MINIO_BUCKET)
    logging.info(f"Created MinIO bucket: {MINIO_BUCKET}")

# --- Initialize pyttsx3 engine once ---
tts_engine = pyttsx3.init()
tts_engine.setProperty('rate', 150)   # speaking speed
tts_engine.setProperty('volume', 1.0) # volume (0.0 to 1.0)

def get_wav_duration(path):
    with wave.open(path, 'rb') as wf:
        frames = wf.getnframes()
        rate = wf.getframerate()
        duration = frames / float(rate)
    return duration

# --- TTS with retry, normalization, and wait ---
def text_to_speech_file_to_temp(text):
    delay = RETRY_DELAY
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix='.wav') as tmp_file:
                temp_path = tmp_file.name

            tts_engine.save_to_file(text, temp_path)
            tts_engine.runAndWait()

            # Wait up to 5 seconds to ensure file is fully written
            timeout = 5
            for _ in range(timeout):
                if os.path.exists(temp_path) and os.path.getsize(temp_path) > 0:
                    break
                time.sleep(1)
            else:
                raise RuntimeError("TTS output file is empty after wait")

            # Normalize WAV to 16kHz mono 16-bit PCM (Whisper expects this)
            audio = AudioSegment.from_file(temp_path)
            audio = audio.set_frame_rate(16000).set_channels(1).set_sample_width(2)
            audio.export(temp_path, format="wav")

            duration = get_wav_duration(temp_path)
            filesize = os.path.getsize(temp_path)
            logging.info(f"TTS generated and normalized WAV saved to {temp_path} "
                         f"(duration: {duration:.2f}s, size: {filesize} bytes)")
            return temp_path

        except Exception as e:
            logging.error(f"TTS generation failed on attempt {attempt}/{MAX_RETRIES}: {e}")
            if attempt == MAX_RETRIES:
                return None
            else:
                logging.info(f"Retrying TTS in {delay} seconds...")
                time.sleep(delay)
                delay = min(delay * 2, 60)  # exponential backoff, max 60s
    return None

def upload_file_to_minio(local_path, bucket, object_name):
    try:
        minio_client.fput_object(bucket, object_name, local_path)
        logging.info(f"Uploaded {local_path} to MinIO bucket '{bucket}' as '{object_name}'")
        return True
    except S3Error as e:
        logging.error(f"Failed to upload file to MinIO: {e}")
        return False

def connect_to_rabbitmq():
    delay = RETRY_DELAY
    parameters = pika.ConnectionParameters(
        host=RABBITMQ_HOST,
        heartbeat=HEARTBEAT_INTERVAL,
        blocked_connection_timeout=300,
        connection_attempts=MAX_RETRIES,
        retry_delay=RETRY_DELAY,
    )
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            logging.info(f"Connecting to RabbitMQ at {RABBITMQ_HOST} (attempt {attempt})")
            connection = pika.BlockingConnection(parameters)
            logging.info("Connected to RabbitMQ.")
            return connection
        except pika.exceptions.AMQPConnectionError as e:
            logging.warning(f"RabbitMQ not ready: {e}. Retrying in {delay}s...")
            time.sleep(delay)
            delay = min(delay * 2, 60)
    raise ConnectionError("Could not connect to RabbitMQ after retries.")

def publish_message(channel, message):
    try:
        channel.basic_publish(
            exchange='',
            routing_key=QUEUE_NAME,
            body=json.dumps(message),
            properties=pika.BasicProperties(delivery_mode=2)
        )
        return True
    except (pika.exceptions.AMQPConnectionError, pika.exceptions.ChannelWrongStateError) as e:
        logging.error(f"Failed to publish message due to connection error: {e}")
        return False

def main():
    redis_client = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=0)

    try:
        connection = connect_to_rabbitmq()
        channel = connection.channel()
        channel.queue_declare(queue=QUEUE_NAME, durable=True)
    except Exception as e:
        logging.error(f"Initial RabbitMQ connection failed: {e}")
        return

    for i in range(2000):
        try:
            customer = generate_customer()

            # Keep generating dialogue until we get at least 20 lines
            dialogue_lines = []
            while len(dialogue_lines) < 20:
                dialogue = generate_dialogue()
                # If generate_dialogue returns list of lines, use directly
                # If returns multiline string, split by newlines
                if isinstance(dialogue, list):
                    dialogue_lines = dialogue
                else:
                    dialogue_lines = dialogue.strip().split('\n')

            # Use exactly first 20 lines
            selected_lines = dialogue_lines[:20]

            # Join lines with natural pauses
            complaint_text = ". ".join(line.strip() for line in selected_lines if line.strip()) + "."

            # Safety check for minimum length (~50 words)
            if not complaint_text or len(complaint_text.strip().split()) < 50:
                logging.warning(f"Skipping iteration {i+1} due to too short complaint text.")
                continue

            timestamp = time.time()
            message_id = f"voice-{customer['id']}-{int(timestamp)}"
            minio_object_name = f"{message_id}.wav"   # note .wav extension

            logging.info(f"[{i + 1}/2000] Generating TTS for: {message_id}")

            temp_audio_path = None
            upload_success = False
            try:
                temp_audio_path = text_to_speech_file_to_temp(complaint_text)
                if not temp_audio_path:
                    logging.error(f"Skipping message {message_id} due to TTS failure")
                    continue

                upload_success = upload_file_to_minio(temp_audio_path, MINIO_BUCKET, minio_object_name)

            finally:
                if temp_audio_path and os.path.exists(temp_audio_path):
                    os.remove(temp_audio_path)

            if not upload_success:
                logging.error(f"Skipping message {message_id} due to upload failure")
                continue

            message = {
                "message_id": message_id,
                "customer": customer,
                "timestamp": timestamp,
                "object_name": minio_object_name
            }

            if not publish_message(channel, message):
                logging.warning("Publish failed, trying to reconnect and retry once")
                try:
                    connection.close()
                except Exception:
                    pass
                try:
                    connection = connect_to_rabbitmq()
                    channel = connection.channel()
                    channel.queue_declare(queue=QUEUE_NAME, durable=True)
                    if not publish_message(channel, message):
                        logging.error("Publish retry failed, skipping message")
                        continue
                except Exception as e:
                    logging.error(f"Reconnect failed: {e}, skipping message")
                    continue

            redis_key = f"audio:{message_id}"
            redis_client.hset(redis_key, mapping={
                "customer_id": customer['id'],
                "customer_name": customer['name'],
                "queue": QUEUE_NAME,
                "timestamp": timestamp,
                "object_name": minio_object_name
            })

            logging.info(f"[{i + 1}/2000] Sent voice complaint: {message_id}")

        except Exception as e:
            logging.error(f"Unexpected error at iteration {i + 1}: {e}")
            logging.error(traceback.format_exc())

        # Sleep between each complaint
        time.sleep(DELAY_BETWEEN_MESSAGES)

    try:
        connection.close()
    except Exception:
        pass

    logging.info("Finished sending all voice complaints.")

    # Keep container alive if needed
    while True:
        time.sleep(3600)

if __name__ == "__main__":
    main()
