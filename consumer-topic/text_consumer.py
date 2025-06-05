import pika
import json
import os
import logging
import traceback
from datetime import datetime
from influxdb_client import InfluxDBClient, Point, WritePrecision

from bertopic import BERTopic

# Setup logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

def get_env_var(name):
    value = os.getenv(name)
    if value is None:
        raise EnvironmentError(f"Missing required environment variable: {name}")
    return value

# Configs
RABBITMQ_HOST = get_env_var("RABBITMQ_HOST")
RABBITMQ_PORT = int(get_env_var("RABBITMQ_PORT"))
RABBITMQ_USER = get_env_var("RABBITMQ_USER")
RABBITMQ_PASS = get_env_var("RABBITMQ_PASS")
RABBITMQ_VHOST = get_env_var("RABBITMQ_VHOST")
QUEUE_NAME = "text_complaints"

INFLUXDB_URL = get_env_var("INFLUXDB_URL")
INFLUXDB_ORG = get_env_var("INFLUXDB_ORG")
INFLUXDB_BUCKET_Text_TOPIC = get_env_var("INFLUXDB_BUCKET")
INFLUXDB_TOKEN = get_env_var("INFLUXDB_TOKEN")

def connect_to_rabbitmq():
    credentials = pika.PlainCredentials(RABBITMQ_USER, RABBITMQ_PASS)
    params = pika.ConnectionParameters(
        host=RABBITMQ_HOST,
        port=RABBITMQ_PORT,
        virtual_host=RABBITMQ_VHOST,
        credentials=credentials,
        heartbeat=600,
        blocked_connection_timeout=300
    )
    return pika.BlockingConnection(params)

def main():
    global write_api, topic_model

    # Initialize InfluxDB client and write API
    influx_client = InfluxDBClient(url=INFLUXDB_URL, token=INFLUXDB_TOKEN, org=INFLUXDB_ORG)
    write_api = influx_client.write_api(write_precision=WritePrecision.NS)

    # Load or create BERTopic model
    # You can load a pretrained model from file or create a new one.
    topic_model = BERTopic(language="english")

    # Connect to RabbitMQ
    conn = connect_to_rabbitmq()
    channel = conn.channel()

    # Consume only, no queue declare
    channel.basic_qos(prefetch_count=1)

    def callback(ch, method, properties, body):
        try:
            message = json.loads(body)
            complaint_text = message.get("complaint_text", "")
            message_id = message.get("message_id", "unknown")
            scenario = message.get("scenario", "unknown")
            customer_id = message.get("customer_id", "unknown")
            channel_name = message.get("channel", "unknown")

            if not complaint_text.strip():
                logging.warning(f"Empty complaint text for message {message_id}")
                ch.basic_ack(delivery_tag=method.delivery_tag)
                return

            # Perform topic modeling for this single text
            # BERTopic expects a list, so pass [complaint_text]
            topics, probs = topic_model.transform([complaint_text])

            topic_id = topics[0]
            topic_prob = probs[0] if probs else None
            topic_name = topic_model.get_topic(topic_id)
            # topic_name is list of (word, score) tuples; get top words
            if topic_name is not None and len(topic_name) > 0:
                topic_words = ", ".join([word for word, score in topic_name[:5]])
            else:
                topic_words = "No topic found"

            # Prepare data point for InfluxDB
            point = (
                Point("text_complaints_topic_model")
                .tag("message_id", message_id)
                .tag("scenario", scenario)
                .tag("customer_id", customer_id)
                .tag("channel", channel_name)
                .tag("topic_id", str(topic_id))
                .field("topic_words", topic_words)
                .field("topic_probability", float(topic_prob) if topic_prob else 0.0)
                .time(datetime.utcnow(), WritePrecision.NS)
            )

            write_api.write(bucket=INFLUXDB_BUCKET, record=point)

            logging.info(f"Processed message {message_id} with topic ID {topic_id} and words [{topic_words}]")

            ch.basic_ack(delivery_tag=method.delivery_tag)

        except Exception:
            logging.error("Error processing message:\n" + traceback.format_exc())
            ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)

    channel.basic_consume(queue=QUEUE_NAME, on_message_callback=callback)

    logging.info(f"Waiting for messages on queue '{QUEUE_NAME}'... Press Ctrl+C to exit.")

    try:
        channel.start_consuming()
    except KeyboardInterrupt:
        logging.info("Interrupted by user, shutting down...")
    finally:
        influx_client.close()
        if conn and conn.is_open:
            conn.close()

if __name__ == "__main__":
    main()
