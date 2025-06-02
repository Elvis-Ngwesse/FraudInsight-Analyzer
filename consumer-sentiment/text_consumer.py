import pika
import json
import os
import logging
import traceback
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
from influxdb_client import InfluxDBClient, Point, WritePrecision

logging.basicConfig(level=logging.INFO)

# Config from env vars
RABBITMQ_HOST = os.getenv("RABBITMQ_HOST", "localhost")
RABBITMQ_PORT = int(os.getenv("RABBITMQ_PORT", 5672))
RABBITMQ_USER = os.getenv("RABBITMQ_USER", "guest")
RABBITMQ_PASS = os.getenv("RABBITMQ_PASS", "guest")
RABBITMQ_VHOST = os.getenv("RABBITMQ_VHOST", "/")
QUEUE_NAME = "text_complaints"

INFLUXDB_URL = os.getenv("INFLUXDB_URL", "http://localhost:8086")
INFLUXDB_ORG = os.getenv("INFLUXDB_ORG", "org")
INFLUXDB_BUCKET = os.getenv("INFLUXDB_BUCKET", "text_bucket")
INFLUXDB_TOKEN = os.getenv("INFLUXDB_TOKEN", "iQR2Im5uSfaAYysoyyk8qfSV2N473QPh5231vEigm6dsg7CG2SOURDMv2BWBrZhjc0oGNswwANqG-glEz_UnXA==")

analyzer = SentimentIntensityAnalyzer()

def ensure_bucket_exists(client, bucket_name, org):
    buckets_api = client.buckets_api()
    existing_buckets = buckets_api.find_buckets().buckets
    if any(bucket.name == bucket_name for bucket in existing_buckets):
        logging.info(f"Bucket '{bucket_name}' already exists.")
    else:
        logging.info(f"Bucket '{bucket_name}' not found. Creating it...")
        buckets_api.create_bucket(bucket_name=bucket_name, org=org)
        logging.info(f"Bucket '{bucket_name}' created.")

def connect_to_rabbitmq():
    credentials = pika.PlainCredentials(RABBITMQ_USER, RABBITMQ_PASS)
    parameters = pika.ConnectionParameters(
        host=RABBITMQ_HOST,
        port=RABBITMQ_PORT,
        virtual_host=RABBITMQ_VHOST,
        credentials=credentials
    )
    return pika.BlockingConnection(parameters)

def callback(ch, method, properties, body):
    try:
        message = json.loads(body)
        text = message.get("complaint_text", "")
        message_id = message.get("message_id", "unknown")

        sentiment = analyzer.polarity_scores(text)

        # Write to InfluxDB
        point = (
            Point("text_complaints")
            .tag("message_id", message_id)
            .field("neg", sentiment["neg"])
            .field("neu", sentiment["neu"])
            .field("pos", sentiment["pos"])
            .field("compound", sentiment["compound"])
        )
        if isinstance(text, str) and len(text) < 1024:
            point = point.field("text", text)
        else:
            logging.warning(f"Complaint text too long or invalid for message {message_id}, skipping 'text' field")

        write_api.write(bucket=INFLUXDB_BUCKET, record=point)

        logging.info(f"Processed text complaint {message_id} | Compound: {sentiment['compound']}")
        ch.basic_ack(delivery_tag=method.delivery_tag)

    except Exception:
        logging.error("Failed to process message:\n" + traceback.format_exc())
        ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)

def main():
    global write_api  # make available inside callback

    influx_client = InfluxDBClient(url=INFLUXDB_URL, token=INFLUXDB_TOKEN, org=INFLUXDB_ORG)
    ensure_bucket_exists(influx_client, INFLUXDB_BUCKET, INFLUXDB_ORG)
    write_api = influx_client.write_api(write_precision=WritePrecision.NS)

    conn = connect_to_rabbitmq()
    channel = conn.channel()
    channel.queue_declare(queue=QUEUE_NAME, durable=True)
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
