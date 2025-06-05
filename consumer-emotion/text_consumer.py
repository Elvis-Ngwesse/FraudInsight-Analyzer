import pika
import json
import os
import logging
import traceback
from transformers import pipeline
from influxdb_client import InfluxDBClient, Point, WritePrecision
from datetime import datetime

# Setup logging
logging.basicConfig(level=logging.INFO)

# Utility to load env vars with error if missing
def get_env_var(name):
    value = os.getenv(name)
    if value is None:
        raise EnvironmentError(f"Missing required environment variable: {name}")
    return value

# Environment config
RABBITMQ_HOST_LOCAL = get_env_var("RABBITMQ_HOST")
RABBITMQ_PORT = int(get_env_var("RABBITMQ_PORT"))
RABBITMQ_USER = get_env_var("RABBITMQ_USER")
RABBITMQ_PASS = get_env_var("RABBITMQ_PASS")
RABBITMQ_VHOST = get_env_var("RABBITMQ_VHOST")
QUEUE_NAME = "text_complaints"

INFLUXDB_URL_LOCAL = get_env_var("INFLUXDB_URL")
INFLUXDB_ORG = get_env_var("INFLUXDB_ORG")
INFLUXDB_BUCKET_TEXT_EMOTION = get_env_var("INFLUXDB_BUCKET")
INFLUXDB_TOKEN = get_env_var("INFLUXDB_TOKEN")

# Emotion classifier
emotion_classifier = pipeline("text-classification", model="j-hartmann/emotion-english-distilroberta-base", return_all_scores=True)

# Ensure InfluxDB bucket exists
def ensure_bucket_exists(client, bucket_name, org):
    buckets_api = client.buckets_api()
    existing_buckets = buckets_api.find_buckets().buckets
    if any(bucket.name == bucket_name for bucket in existing_buckets):
        logging.info(f"Bucket '{bucket_name}' already exists.")
    else:
        logging.info(f"Bucket '{bucket_name}' not found. Creating it...")
        buckets_api.create_bucket(bucket_name=bucket_name, org=org)
        logging.info(f"Bucket '{bucket_name}' created.")

# RabbitMQ connection setup
def connect_to_rabbitmq():
    credentials = pika.PlainCredentials(RABBITMQ_USER, RABBITMQ_PASS)
    parameters = pika.ConnectionParameters(
        host=RABBITMQ_HOST_LOCAL,
        port=RABBITMQ_PORT,
        virtual_host=RABBITMQ_VHOST,
        credentials=credentials
    )
    return pika.BlockingConnection(parameters)

# Main message processor
def callback(ch, method, properties, body):
    try:
        message = json.loads(body)

        text = message.get("complaint_text", "")
        message_id = message.get("message_id", "unknown")
        scenario = message.get("scenario", "unknown")
        customer_id = message.get("customer_id", "unknown")
        channel_name = message.get("channel", "unknown")

        if not text.strip():
            logging.warning(f"Empty complaint text for message {message_id}")
            ch.basic_ack(delivery_tag=method.delivery_tag)
            return

        # Emotion classification
        results = emotion_classifier(text)[0]
        top_emotion = max(results, key=lambda x: x["score"])
        emotion_label = top_emotion["label"]
        emotion_score = round(top_emotion["score"], 4)

        point = (
            Point("text_complaints")
            .tag("message_id", message_id)
            .tag("scenario", scenario)
            .tag("customer_id", customer_id)
            .tag("channel", channel_name)
            .field("emotion", emotion_label)
            .field("emotion_score", emotion_score)
            .time(datetime.utcnow(), WritePrecision.NS)
        )

        if isinstance(text, str) and len(text) < 5024:
            point = point.field("text", text)
        else:
            logging.warning(f"Complaint text too long or invalid for message {message_id}, skipping 'text' field")

        write_api.write(bucket=INFLUXDB_BUCKET_TEXT_EMOTION, record=point)

        logging.info(f"Processed text complaint {message_id} | Emotion: {emotion_label} ({emotion_score})")
        ch.basic_ack(delivery_tag=method.delivery_tag)

    except Exception:
        logging.error("Failed to process message:\n" + traceback.format_exc())
        ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)

# Entry point
def main():
    global write_api

    influx_client = InfluxDBClient(url=INFLUXDB_URL_LOCAL, token=INFLUXDB_TOKEN, org=INFLUXDB_ORG)
    ensure_bucket_exists(influx_client, INFLUXDB_BUCKET_TEXT_EMOTION, INFLUXDB_ORG)
    write_api = influx_client.write_api(write_precision=WritePrecision.NS)

    conn = connect_to_rabbitmq()
    channel = conn.channel()
    channel.basic_qos(prefetch_count=1)
    channel.basic_consume(queue=QUEUE_NAME, on_message_callback=callback)

    logging.info("Waiting for text complaints...")
    try:
        channel.start_consuming()
    except KeyboardInterrupt:
        logging.info("Interrupted by user, shutting down...")
    finally:
        influx_client.close()
        conn.close()

if __name__ == "__main__":
    main()
