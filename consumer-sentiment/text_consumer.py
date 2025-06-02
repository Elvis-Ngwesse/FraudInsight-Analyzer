import pika, json, os, redis, logging, time
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

logging.basicConfig(level=logging.INFO)

# --- Config ---
RABBITMQ_HOST = os.getenv("RABBITMQ_HOST", "localhost")
RABBITMQ_PORT = int(os.getenv("RABBITMQ_PORT", 5672))
RABBITMQ_USER = os.getenv("RABBITMQ_USER", "guest")
RABBITMQ_PASS = os.getenv("RABBITMQ_PASS", "guest")
RABBITMQ_VHOST = os.getenv("RABBITMQ_VHOST", "/")
QUEUE_NAME = 'text_complaints'

REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))

MAX_RETRIES = 10
RETRY_DELAY = 5  # seconds
HEARTBEAT_INTERVAL = 120  # seconds

# --- Setup ---
analyzer = SentimentIntensityAnalyzer()

def connect_to_rabbitmq():
    credentials = pika.PlainCredentials(RABBITMQ_USER, RABBITMQ_PASS)
    parameters = pika.ConnectionParameters(
        host=RABBITMQ_HOST,
        port=RABBITMQ_PORT,
        virtual_host=RABBITMQ_VHOST,
        credentials=credentials,
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

def callback(ch, method, properties, body):
    try:
        message = json.loads(body)
        text = message.get("complaint_text", "")
        message_id = message.get("message_id", "unknown")

        sentiment = analyzer.polarity_scores(text)
        redis_key = f"analysis:{message_id}"
        redis_client.hset(redis_key, mapping={
            "text": text,
            "sentiment_neg": sentiment['neg'],
            "sentiment_neu": sentiment['neu'],
            "sentiment_pos": sentiment['pos'],
            "sentiment_compound": sentiment['compound']
        })

        logging.info(f"Analyzed text complaint {message_id} | Compound: {sentiment['compound']}")
        ch.basic_ack(delivery_tag=method.delivery_tag)
    except Exception as e:
        logging.error(f"Failed to process message: {e}")
        ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)

def main():
    global redis_client
    rabbit_conn = connect_to_rabbitmq()
    redis_client = connect_to_redis()

    channel = rabbit_conn.channel()
    channel.queue_declare(queue=QUEUE_NAME, durable=True)
    channel.basic_qos(prefetch_count=1)
    channel.basic_consume(queue=QUEUE_NAME, on_message_callback=callback)
    logging.info(" [*] Waiting for text messages. To exit press CTRL+C")
    channel.start_consuming()

if __name__ == "__main__":
    main()
