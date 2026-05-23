import json
import logging
import time
from typing import Any

from config import settings

logger = logging.getLogger("kafka_producer")


class EventProducer:
    """Lazy Kafka producer with a no-crash fallback when Kafka is still starting."""

    def __init__(self) -> None:
        self._producer = None
        self._last_error = ""

    def _connect(self) -> None:
        if self._producer or not settings.kafka_enabled:
            return
        try:
            from kafka import KafkaProducer

            self._producer = KafkaProducer(
                bootstrap_servers=settings.kafka_bootstrap_servers.split(","),
                value_serializer=lambda value: json.dumps(value).encode("utf-8"),
                linger_ms=50,
                retries=3,
            )
            self._last_error = ""
        except Exception as exc:
            self._last_error = str(exc)
            logger.warning("Kafka producer unavailable", extra={"_error": self._last_error})

    def publish(self, topic: str, event: dict[str, Any]) -> bool:
        self._connect()
        if not self._producer:
            return False
        try:
            event.setdefault("published_at", time.time())
            self._producer.send(topic, event)
            self._producer.flush(timeout=1)
            return True
        except Exception as exc:
            self._last_error = str(exc)
            self._producer = None
            logger.warning("Kafka publish failed", extra={"_topic": topic, "_error": self._last_error})
            return False

    def status(self) -> dict[str, Any]:
        return {"enabled": settings.kafka_enabled, "connected": self._producer is not None, "last_error": self._last_error}
