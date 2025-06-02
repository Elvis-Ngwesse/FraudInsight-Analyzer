import pika
import json
import os
import redis
import logging
import tempfile
from minio import Minio
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
import whisper
import wave

logging.basicConfig(level=logging.INFO)

# --- Env vars ---
RABBITMQ_HOST = os.getenv("RABBITMQ_HOST", "rabbitmq")
REDIS_HOST = os.getenv("REDIS_HOST", "redis")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))
QUEUE_NAME = 'voice_complaints'

MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT", "minio:9000")
MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY", "minioadmin")
MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY", "minioadmin")
MINIO_BUCKET = os.getenv("MINIO_BUCKET", "audiofiles")

# --- Clients ---
redis_client = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=0)
minio_client = Minio(MINIO_ENDPOINT, access_key=MINIO_ACCESS_KEY, secret_key=MINIO_SECRET_KEY, secure=False)
whisper_model = whisper.load_model("base")
analyzer = SentimentIntensityAnalyzer()


def download_audio_from_minio(object_name):
    """
    Downloads the audio file from MinIO and returns the local temporary file path.
    """
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as tmp_file:
            minio_client.fget_object(MINIO_BUCKET, object_name, tmp_file.name)
            logging.info(f"Downloaded audio file from MinIO: {object_name} -> {tmp_file.name}")

            # Check if file is empty
            file_size = os.path.getsize(tmp_file.name)
            if file_size == 0:
                raise Exception("Downloaded file is empty (0 bytes)")

            # Validate WAV format by opening with wave module
            try:
                with wave.open(tmp_file.name, 'rb') as wav_file:
                    logging.info(f"WAV file parameters: channels={wav_file.getnchannels()}, "
                                 f"framerate={wav_file.getframerate()}, "
                                 f"frames={wav_file.getnframes()}")
            except wave.Error as e:
                raise Exception(f"Invalid WAV file: {e}")

            return tmp_file.name
    except Exception as e:
        raise Exception(f"Failed to download or validate audio from MinIO: {e}")


def callback(ch, method, properties, body):
    try:
        message = json.loads(body)
        message_id = message.get("message_id", "unknown")
        object_name = message.get("object_name")

        if not object_name:
            raise ValueError(f"Message {message_id} missing 'object_name' field.")

        audio_path = download_audio_from_minio(object_name)

        # Transcribe audio
        result = whisper_model.transcribe(audio_path)
        transcript = result.get("text", "").strip()
        logging.info(f"Transcript for {message_id}: '{transcript}'")

        if not transcript:
            logging.warning(f"Empty transcript for message {message_id}")

        sentiment = analyzer.polarity_scores(transcript)
        logging.info(f"Sentiment for {message_id}: {sentiment}")

        # Save analysis in Redis
        redis_key = f"analysis:{message_id}"
        redis_client.hset(redis_key, mapping={
            "transcript": transcript,
            "sentiment_neg": sentiment['neg'],
            "sentiment_neu": sentiment['neu'],
            "sentiment_pos": sentiment['pos'],
            "sentiment_compound": sentiment['compound']
        })

        # Clean up temporary audio file
        os.remove(audio_path)

        ch.basic_ack(delivery_tag=method.delivery_tag)

    except Exception as e:
        logging.error(f"Failed to process message: {e}")
        # Nack and discard message (no requeue)
        ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)


def main():
    conn = pika.BlockingConnection(pika.ConnectionParameters(host=RABBITMQ_HOST))
    channel = conn.channel()
    channel.queue_declare(queue=QUEUE_NAME, durable=True)
    channel.basic_qos(prefetch_count=1)
    channel.basic_consume(queue=QUEUE_NAME, on_message_callback=callback)
    logging.info(" [*] Waiting for voice messages. To exit press CTRL+C")
    channel.start_consuming()


if __name__ == "__main__":
    main()
