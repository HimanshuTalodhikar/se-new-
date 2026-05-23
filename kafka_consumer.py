import json
import logging
import signal
import time

from config import settings
from logging_config import configure_logging

configure_logging()
logger = logging.getLogger("kafka_consumer")
running = True


def _stop(_signum, _frame) -> None:
    global running
    running = False


def main() -> None:
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)

    from kafka import KafkaConsumer

    topics = [settings.camera_events_topic, settings.ai_events_topic, settings.health_events_topic]
    while running:
        try:
            consumer = KafkaConsumer(
                *topics,
                bootstrap_servers=settings.kafka_bootstrap_servers.split(","),
                group_id="surveillance-monitoring",
                auto_offset_reset="latest",
                value_deserializer=lambda value: json.loads(value.decode("utf-8")),
            )
            logger.info("Kafka consumer connected", extra={"_topics": topics})
            for message in consumer:
                if not running:
                    break
                event = message.value
                logger.info(
                    "Kafka event consumed",
                    extra={"_topic": message.topic, "_camera_id": event.get("camera_id"), "_worker_id": event.get("worker_id")},
                )
        except Exception as exc:
            logger.warning("Kafka consumer waiting for broker", extra={"_error": str(exc)})
            time.sleep(5)


if __name__ == "__main__":
    main()
