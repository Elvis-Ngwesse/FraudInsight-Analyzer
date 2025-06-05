import pika
import json
import os
import logging
import traceback
import time
from datetime import datetime

from sklearn.decomposition import LatentDirichletAllocation
from sklearn.feature_extraction.text import CountVectorizer
from influxdb_client import InfluxDBClient, Point, WritePrecision

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
INFLUXDB_BUCKET_TEXT_TOPIC = get_env_var("INFLUXDB_BUCKET")
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

def ensure_bucket_exists(client, bucket_name, org_name):
    try:
        bucket = client.buckets_api().find_bucket_by_name(bucket_name)
        if bucket is None:
            logging.info(f"Bucket '{bucket_name}' not found. Creating it...")
            client.buckets_api().create_bucket(bucket_name=bucket_name, org=org_name)
            logging.info(f"Bucket '{bucket_name}' created.")
        else:
            logging.info(f"Bucket '{bucket_name}' already exists.")
    except Exception as e:
        logging.error(f"Failed to verify/create bucket '{bucket_name}': {e}")

def main():
    global write_api, vectorizer, lda_model

    influx_client = InfluxDBClient(url=INFLUXDB_URL, token=INFLUXDB_TOKEN, org=INFLUXDB_ORG)
    ensure_bucket_exists(influx_client, INFLUXDB_BUCKET_TEXT_TOPIC, INFLUXDB_ORG)
    write_api = influx_client.write_api(write_precision=WritePrecision.NS)

    vectorizer = CountVectorizer(stop_words="english", max_features=1000)
    lda_model = None
    fit_buffer = []
    consumed_message_count = 0

    conn = connect_to_rabbitmq()
    channel = conn.channel()
    channel.basic_qos(prefetch_count=1)

    logging.info(f"Starting live message processing for queue '{QUEUE_NAME}'...")

    try:
        while True:
            queue_state = channel.queue_declare(queue=QUEUE_NAME, passive=True)
            message_count = queue_state.method.message_count

            if message_count < 1:
                logging.info("Queue empty. Sleeping 30 seconds...")
                time.sleep(30)
                continue

            method_frame, header_frame, body = channel.basic_get(QUEUE_NAME, auto_ack=False)
            if method_frame is None:
                logging.info("No message received despite message count, sleeping 30 seconds...")
                time.sleep(30)
                continue

            try:
                message = json.loads(body)
                complaint_text = message.get("complaint_text", "")
                message_id = message.get("message_id", "unknown")
                scenario = message.get("scenario", "unknown")
                customer_id = message.get("customer_id", "unknown")
                channel_name = message.get("channel", "unknown")

                if not complaint_text.strip():
                    logging.warning(f"Empty complaint text for message {message_id}")
                    channel.basic_ack(delivery_tag=method_frame.delivery_tag)
                    consumed_message_count += 1
                    logging.info(f"Total consumed messages: {consumed_message_count}")
                    continue

                fit_buffer.append(complaint_text)

                if lda_model is None and len(fit_buffer) >= 5:
                    X_train = vectorizer.fit_transform(fit_buffer)
                    lda_model = LatentDirichletAllocation(n_components=5, random_state=42)
                    lda_model.fit(X_train)
                    logging.info("LDA model fitted with first 5 messages.")
                    channel.basic_ack(delivery_tag=method_frame.delivery_tag)
                    consumed_message_count += 1
                    logging.info(f"Total consumed messages: {consumed_message_count}")
                    continue

                if lda_model:
                    X_new = vectorizer.transform([complaint_text])
                    topic_dist = lda_model.transform(X_new)[0]
                    topic_id = topic_dist.argmax()
                    topic_prob = topic_dist[topic_id]

                    topic_words = vectorizer.get_feature_names_out()
                    topic_terms = lda_model.components_[topic_id]
                    top_indices = topic_terms.argsort()[-5:][::-1]
                    topic_keywords = ", ".join(topic_words[i] for i in top_indices)

                    point = (
                        Point("text_complaints_topic_model")
                        .tag("message_id", message_id)
                        .tag("scenario", scenario)
                        .tag("customer_id", customer_id)
                        .tag("channel", channel_name)
                        .tag("topic_id", str(topic_id))
                        .field("topic_words", topic_keywords)
                        .field("topic_probability", float(topic_prob))
                        .time(datetime.utcnow(), WritePrecision.NS)
                    )

                    write_api.write(bucket=INFLUXDB_BUCKET_TEXT_TOPIC, record=point)
                    logging.info(f"Processed {message_id} -> topic {topic_id} with words [{topic_keywords}]")

                channel.basic_ack(delivery_tag=method_frame.delivery_tag)
                consumed_message_count += 1
                logging.info(f"Total consumed messages: {consumed_message_count}")

            except Exception:
                logging.error("Error processing message:\n" + traceback.format_exc())
                channel.basic_nack(delivery_tag=method_frame.delivery_tag, requeue=False)

    except KeyboardInterrupt:
        logging.info("Shutdown requested by user.")
    finally:
        influx_client.close()
        if conn.is_open:
            conn.close()

if __name__ == "__main__":
    main()
