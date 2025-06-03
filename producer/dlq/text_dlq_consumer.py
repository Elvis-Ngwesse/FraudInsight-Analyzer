import pika
import time
import json
import redis
import logging
import os

# Setup logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

# Environment variables (make sure these are set in your environment)
RABBITMQ_HOST = os.getenv("RABBITMQ_HOST", "localhost")
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))

MAIN_QUEUE = "text_complaints_dlq"
DLQ_QUEUE = f"{MAIN_QUEUE}.dlq"
DEAD_LETTER_EXCHANGE = "text_dlx"
DEAD_LETTER_ROUTING_KEY = "text_dead_letter"  # This routing key must match your RabbitMQ setup

# Delay before retrying a message from DLQ (seconds)
REQUEUE_DELAY = 5


def connect_rabbitmq():
    for attempt in range(5):
        try:
            connection = pika.BlockingConnection(pika.ConnectionParameters(host=RABBITMQ_HOST))
            channel = connection.channel()

            # Declare dead-letter exchange (direct type)
            channel.exchange_declare(
                exchange=DEAD_LETTER_EXCHANGE,
                exchange_type='direct',
                durable=True
            )

            # Declare DLQ queue and bind it to the dead-letter exchange with routing key
            channel.queue_declare(queue=DLQ_QUEUE, durable=True)
            channel.queue_bind(queue=DLQ_QUEUE, exchange=DEAD_LETTER_EXCHANGE, routing_key=DEAD_LETTER_ROUTING_KEY)

            # Declare main queue with dead-letter exchange and routing key arguments
            channel.queue_declare(
                queue=MAIN_QUEUE,
                durable=True,
                arguments={
                    'x-dead-letter-exchange': DEAD_LETTER_EXCHANGE,
                    'x-dead-letter-routing-key': DEAD_LETTER_ROUTING_KEY
                }
            )

            logging.info("RabbitMQ queues and exchange declared successfully")
            return connection, channel
        except Exception as e:
            logging.warning(f"Retrying RabbitMQ connection (attempt {attempt + 1}/5): {e}")
            time.sleep(2)
    raise RuntimeError("Failed to connect to RabbitMQ after multiple attempts")


def connect_redis():
    for attempt in range(5):
        try:
            r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=0)
            r.ping()
            logging.info("Connected to Redis successfully")
            return r
        except Exception as e:
            logging.warning(f"Retrying Redis connection (attempt {attempt + 1}/5): {e}")
            time.sleep(2)
    raise RuntimeError("Failed to connect to Redis after multiple attempts")


def callback(ch, method, properties, body):
    try:
        message = json.loads(body)
        retry_count = message.get("retry_count", 0)
        message_id = message.get("message_id", "unknown")

        if retry_count == 0:
            logging.info(f"[DLQ] First failure for {message_id}. Requeuing after {REQUEUE_DELAY}s...")
            message["retry_count"] = 1
            time.sleep(REQUEUE_DELAY)
            ch.basic_publish(
                exchange="",
                routing_key=MAIN_QUEUE,
                body=json.dumps(message),
                properties=pika.BasicProperties(delivery_mode=2),  # make message persistent
            )
        else:
            logging.warning(f"[DLQ] Second failure for {message_id}. Sending to Redis.")
            redis_key = f"text_dlq:{message_id}"
            redis_client.set(redis_key, json.dumps(message))
            logging.info(f"[Redis] Saved message to Redis key: {redis_key}")

        ch.basic_ack(delivery_tag=method.delivery_tag)

    except Exception as e:
        logging.error(f"[DLQ] Error processing message: {e}")
        ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)


if __name__ == "__main__":
    redis_client = connect_redis()
    conn, channel = connect_rabbitmq()

    logging.info(f"[DLQ] Waiting for messages in queue: {DLQ_QUEUE}")
    channel.basic_qos(prefetch_count=1)
    channel.basic_consume(queue=DLQ_QUEUE, on_message_callback=callback)

    try:
        channel.start_consuming()
    except KeyboardInterrupt:
        logging.info("Stopping consumer...")
        channel.stop_consuming()
    finally:
        conn.close()
        logging.info("Connection closed.")
