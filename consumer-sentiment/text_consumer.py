import pika
import json
import os
import logging
import traceback
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
from influxdb_client import InfluxDBClient, Point, WritePrecision

logging.basicConfig(level=logging.INFO)

def get_env_var(name):
    value = os.getenv(name)
    if value is None:
        raise EnvironmentError(f"Missing required environment variable: {name}")
    return value

RABBITMQ_HOST_LOCAL = get_env_var("RABBITMQ_HOST")
RABBITMQ_PORT = int(get_env_var("RABBITMQ_PORT"))
RABBITMQ_USER = get_env_var("RABBITMQ_USER")
RABBITMQ_PASS = get_env_var("RABBITMQ_PASS")
RABBITMQ_VHOST = get_env_var("RABBITMQ_VHOST")
QUEUE_NAME = "text_complaints"

INFLUXDB_URL_LOCAL = get_env_var("INFLUXDB_URL")
INFLUXDB_ORG = get_env_var("INFLUXDB_ORG")
INFLUXDB_BUCKET_TEXT = get_env_var("INFLUXDB_BUCKET")
INFLUXDB_TOKEN = get_env_var("INFLUXDB_TOKEN")

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
        host=RABBITMQ_HOST_LOCAL,
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

        point = (
            Point("text_complaints")
            .tag("message_id", message_id)
            .field("neg", sentiment["neg"])
            .field("neu", sentiment["neu"])
            .field("pos", sentiment["pos"])
            .field("compound", sentiment["compound"])
        )
        if isinstance(text, str) and len(text) < 5024:
            point = point.field("text", text)
        else:
            logging.warning(f"Complaint text too long or invalid for message {message_id}, skipping 'text' field")

        write_api.write(bucket=INFLUXDB_BUCKET_TEXT, record=point)

        logging.info(f"Processed text complaint {message_id} | Compound: {sentiment['compound']}")
        ch.basic_ack(delivery_tag=method.delivery_tag)

    except Exception:
        logging.error("Failed to process message:\n" + traceback.format_exc())
        ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)

def main():
    global write_api

    influx_client = InfluxDBClient(url=INFLUXDB_URL_LOCAL, token=INFLUXDB_TOKEN, org=INFLUXDB_ORG)
    ensure_bucket_exists(influx_client, INFLUXDB_BUCKET_TEXT, INFLUXDB_ORG)
    write_api = influx_client.write_api(write_precision=WritePrecision.NS)

    conn = connect_to_rabbitmq()
    channel = conn.channel()

    # Removed queue_declare to avoid argument conflicts
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
