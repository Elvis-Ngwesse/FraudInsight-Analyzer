import pika
import json
import time
import redis
import logging
import os
from utils import generate_customer, generate_dialogue

logging.basicConfig(level=logging.INFO)

RABBITMQ_HOST = os.getenv("RABBITMQ_HOST", "localhost")
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))
QUEUE_NAME = 'text_complaints'
TOTAL_MESSAGES = 2000
DELAY_BETWEEN_MESSAGES = 120  # seconds

MAX_RETRIES = 10
RETRY_DELAY = 5  # seconds
HEARTBEAT_INTERVAL = 120  # seconds


def connect_to_rabbitmq():
    parameters = pika.ConnectionParameters(
        host=RABBITMQ_HOST,
        heartbeat=HEARTBEAT_INTERVAL,
        blocked_connection_timeout=300,
        connection_attempts=MAX_RETRIES,
        retry_delay=RETRY_DELAY
    )
    for attempt in range(MAX_RETRIES):
        try:
            logging.info(f"Connecting to RabbitMQ at {RABBITMQ_HOST} (attempt {attempt + 1})")
            connection = pika.BlockingConnection(parameters)
            logging.info("Connected to RabbitMQ.")
            return connection
        except pika.exceptions.AMQPConnectionError as e:
            logging.warning(f"RabbitMQ not ready: {e}")
            time.sleep(RETRY_DELAY)
    raise Exception("Failed to connect to RabbitMQ after retries.")


def connect_to_redis():
    for attempt in range(MAX_RETRIES):
        try:
            logging.info(f"Connecting to Redis at {REDIS_HOST}:{REDIS_PORT} (attempt {attempt + 1})")
            redis_client = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=0)
            redis_client.ping()
            logging.info("Connected to Redis.")
            return redis_client
        except redis.exceptions.ConnectionError as e:
            logging.warning(f"Redis not ready: {e}")
            time.sleep(RETRY_DELAY)
    raise Exception("Failed to connect to Redis after retries.")


def main():
    redis_client = connect_to_redis()
    rabbit_conn = connect_to_rabbitmq()
    channel = rabbit_conn.channel()
    channel.queue_declare(queue=QUEUE_NAME, durable=True)

    for i in range(TOTAL_MESSAGES):
        customer = generate_customer()
        complaint_text = generate_dialogue()
        timestamp = time.time()
        message_id = f"text-{customer['id']}-{int(timestamp)}"

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
            logging.error(f"Failed to publish message: {e}. Reconnecting and retrying.")
            # Reconnect and retry once
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

        logging.info(f"[{i+1}/{TOTAL_MESSAGES}] Sent text complaint: {message_id}")

        time.sleep(DELAY_BETWEEN_MESSAGES)

    rabbit_conn.close()
    logging.info("Finished sending all complaints.")


if __name__ == "__main__":
    main()