import pika
import json
import time
import redis
import logging
import pyttsx3
import os
from utils import generate_customer, generate_dialogue

logging.basicConfig(level=logging.INFO)

RABBITMQ_HOST = os.getenv("RABBITMQ_HOST", "rabbitmq")
QUEUE_NAME = 'voice_complaints'
REDIS_HOST = os.getenv("REDIS_HOST", "redis")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))
AUDIO_OUTPUT_DIR = "./audio_files"

MAX_RETRIES = 10
RETRY_DELAY = 5  # seconds

if not os.path.exists(AUDIO_OUTPUT_DIR):
    os.makedirs(AUDIO_OUTPUT_DIR)

def text_to_speech_file(text, filename):
    engine = pyttsx3.init()
    engine.setProperty('rate', 150)
    engine.setProperty('volume', 1.0)
    engine.save_to_file(text, filename)
    engine.runAndWait()

def connect_to_rabbitmq():
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            logging.info(f"Connecting to RabbitMQ at {RABBITMQ_HOST} (attempt {attempt})")
            connection = pika.BlockingConnection(pika.ConnectionParameters(RABBITMQ_HOST))
            logging.info("Connected to RabbitMQ.")
            return connection
        except pika.exceptions.AMQPConnectionError as e:
            logging.warning(f"RabbitMQ not ready: {e}. Retrying in {RETRY_DELAY} seconds...")
            time.sleep(RETRY_DELAY)
    raise ConnectionError("Could not connect to RabbitMQ after retries.")

def main():
    r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=0)

    connection = connect_to_rabbitmq()
    channel = connection.channel()
    channel.queue_declare(queue=QUEUE_NAME, durable=True)

    for i in range(2000):
        customer = generate_customer()
        complaint_text = generate_dialogue()
        timestamp = time.time()
        message_id = f"voice-{customer['id']}-{int(timestamp)}"
        audio_filename = os.path.join(AUDIO_OUTPUT_DIR, f"{message_id}.wav")

        logging.info(f"[{i+1}/2000] Generating TTS for: {message_id}")
        text_to_speech_file(complaint_text, audio_filename)

        # Prepare metadata-only message (no audio content)
        message = {
            "message_id": message_id,
            "customer": customer,
            "timestamp": timestamp,
            "audio_filename": audio_filename
        }

        channel.basic_publish(
            exchange='',
            routing_key=QUEUE_NAME,
            body=json.dumps(message),
            properties=pika.BasicProperties(delivery_mode=2)
        )

        r.hset(message_id, mapping={
            "customer_id": customer['id'],
            "customer_name": customer['name'],
            "queue": QUEUE_NAME,
            "timestamp": timestamp,
            "audio_filename": audio_filename
        })

        logging.info(f"[{i+1}/2000] Sent voice complaint: {message_id}")
        time.sleep(120)  # 2 minutes between complaints

    connection.close()

if __name__ == "__main__":
    main()
