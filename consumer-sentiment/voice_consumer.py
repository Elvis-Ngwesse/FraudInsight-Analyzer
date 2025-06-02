import pika
import json
import os
import redis
import logging
import tempfile
from minio import Minio
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
import whisper

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
minio_client = Minio(
    MINIO_ENDPOINT,
    access_key=MINIO_ACCESS_KEY,
    secret_key=MINIO_SECRET_KEY,
    secure=False  # Change to True if using HTTPS
)
whisper_model = whisper.load_model("base")
analyzer = SentimentIntensityAnalyzer()


def download_audio(object_name):
    """
    Download the audio object from MinIO to a temp file and return the path.
    """
    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".wav")
    temp_file.close()  # Close the file so MinIO can write to it
    try:
        minio_client.fget_object(MINIO_BUCKET, object_name, temp_file.name)
        return temp_file.name
    except Exception as e:
        os.unlink(temp_file.name)  # Clean up if download failed
        raise e


def callback(ch, method, properties, body):
    message = json.loads(body)
    message_id = message.get("message_id", "unknown")
    object_name = message.get("object_name")  # Expect object key, e.g., "voice-123.wav"

    if not object_name:
        logging.error(f"Message {message_id} missing 'object_name' field.")
        ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)
        return

    try:
        audio_path = download_audio(object_name)
        result = whisper_model.transcribe(audio_path)
        transcript = result["text"]
        sentiment = analyzer.polarity_scores(transcript)

        redis_key = f"analysis:{message_id}"
        redis_client.hset(redis_key, mapping={
            "transcript": transcript,
            "sentiment_neg": sentiment['neg'],
            "sentiment_neu": sentiment['neu'],
            "sentiment_pos": sentiment['pos'],
            "sentiment_compound": sentiment['compound']
        })

        logging.info(f"Processed voice message {message_id} | Compound: {sentiment['compound']}")

        # Cleanup temp audio file after processing
        os.unlink(audio_path)

        ch.basic_ack(delivery_tag=method.delivery_tag)
    except Exception as e:
        logging.error(f"Failed to process {message_id}: {e}")
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
