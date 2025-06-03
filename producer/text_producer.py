import pika
import json
import time
import redis
import logging
import os
from utils import generate_customer, generate_dialogue

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)


def get_env_var(name):
    value = os.getenv(name)
    if value is None:
        raise EnvironmentError(f"Missing required environment variable: {name}")
    return value


RABBITMQ_HOST_LOCAL = get_env_var("RABBITMQ_HOST")
REDIS_HOST_LOCAL = get_env_var("REDIS_HOST")
REDIS_PORT = int(get_env_var("REDIS_PORT"))

QUEUE_NAME = 'text_complaints'
TOTAL_MESSAGES = 2000
DELAY_BETWEEN_MESSAGES = 60  # seconds
MAX_RETRIES = 10
RETRY_DELAY = 5  # seconds
HEARTBEAT_INTERVAL = 120  # seconds
MIN_LINES_PER_COMPLAINT = 20  # Minimum lines in each complaint text


def connect_to_rabbitmq():
    parameters = pika.ConnectionParameters(
        host=RABBITMQ_HOST_LOCAL,
        heartbeat=HEARTBEAT_INTERVAL,
        blocked_connection_timeout=300,
        connection_attempts=MAX_RETRIES,
        retry_delay=RETRY_DELAY
    )
    for attempt in range(MAX_RETRIES):
        try:
            logging.info(f"[RabbitMQ] Connecting to {RABBITMQ_HOST_LOCAL} (attempt {attempt + 1})")
            connection = pika.BlockingConnection(parameters)
            logging.info("[RabbitMQ] Connection established")
            return connection
        except pika.exceptions.AMQPConnectionError as e:
            logging.warning(f"[RabbitMQ] Connection failed: {e}")
            time.sleep(RETRY_DELAY)
    raise Exception("[RabbitMQ] Failed to connect after retries")


def connect_to_redis():
    for attempt in range(MAX_RETRIES):
        try:
            logging.info(f"[Redis] Connecting to {REDIS_HOST_LOCAL}:{REDIS_PORT} (attempt {attempt + 1})")
            redis_client = redis.Redis(host=REDIS_HOST_LOCAL, port=REDIS_PORT, db=0)
            redis_client.ping()
            logging.info("[Redis] Connection established")
            return redis_client
        except redis.exceptions.ConnectionError as e:
            logging.warning(f"[Redis] Connection failed: {e}")
            time.sleep(RETRY_DELAY)
    raise Exception("[Redis] Failed to connect after retries")


def main():
    redis_client = connect_to_redis()
    rabbit_conn = connect_to_rabbitmq()
    channel = rabbit_conn.channel()
    channel.queue_declare(queue=QUEUE_NAME, durable=True)

    for i in range(TOTAL_MESSAGES):
        customer = generate_customer()
        logging.info(f"[{i + 1}/{TOTAL_MESSAGES}] Generating complaint for customer: {customer['name']} (ID: {customer['id']})")

        complaint_lines = []
        while len(complaint_lines) < MIN_LINES_PER_COMPLAINT:
            dialogue = generate_dialogue()
            lines = [line.strip() for line in dialogue.split('\n') if line.strip()]
            complaint_lines.extend(lines)

        complaint_text = "\n".join(complaint_lines[:MIN_LINES_PER_COMPLAINT])
        timestamp = time.time()
        message_id = f"text-{customer['id']}-{int(timestamp)}"

        logging.info(f"[{i + 1}/{TOTAL_MESSAGES}] Complaint ready (Lines: {len(complaint_lines)}). Preparing to publish message_id: {message_id}")

        message = {
            "message_id": message_id,
            "customer": customer,
            "complaint_text": complaint_text,
            "timestamp": timestamp
        }

        try:
            channel.basic_publish(
                exchange='',
                routing_key=QUEUE_NAME,
                body=json.dumps(message),
                properties=pika.BasicProperties(delivery_mode=2)
            )
        except (pika.exceptions.AMQPConnectionError, pika.exceptions.ChannelWrongStateError) as e:
            logging.error(f"[RabbitMQ] Publish failed: {e}. Attempting reconnect.")
            try:
                rabbit_conn.close()
            except Exception:
                pass
            rabbit_conn = connect_to_rabbitmq()
            channel = rabbit_conn.channel()
            channel.queue_declare(queue=QUEUE_NAME, durable=True)
            channel.basic_publish(
                exchange='',
                routing_key=QUEUE_NAME,
                body=json.dumps(message),
                properties=pika.BasicProperties(delivery_mode=2)
            )

        redis_key = f"text:{message_id}"
        redis_client.hset(redis_key, mapping={
            "customer_id": customer["id"],
            "customer_name": customer["name"],
            "queue": QUEUE_NAME,
            "timestamp": timestamp
        })

        logging.info(f"[{i + 1}/{TOTAL_MESSAGES}] ✅ Message published and stored in Redis: {message_id}")

        time.sleep(DELAY_BETWEEN_MESSAGES)

    rabbit_conn.close()
    logging.info("🚀 Finished sending all text complaints.")


if __name__ == "__main__":
    main()
