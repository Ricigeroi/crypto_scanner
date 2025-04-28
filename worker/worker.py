import json, os, time
import pika
from dotenv import load_dotenv
from fetcher import fetch_symbol

load_dotenv()
AMQP_URL = os.getenv("AMQP_URL")
connection = pika.BlockingConnection(pika.URLParameters(AMQP_URL))
channel = connection.channel()
channel.queue_declare(queue="fetch_request", durable=True)
channel.basic_qos(prefetch_count=1)

def callback(ch, method, properties, body):
    try:
        payload = json.loads(body)
        sym    = payload["symbol"]
        period = payload["period"]
        rows = fetch_symbol(sym, period)
        print(f"[worker] {sym}/{period} → inserted {rows}")
        ch.basic_ack(delivery_tag=method.delivery_tag)
    except Exception as e:
        print("error:", e)
        time.sleep(1)
        ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)

print("[worker] waiting for tasks…")
channel.basic_consume(queue="fetch_request", on_message_callback=callback)
channel.start_consuming()
