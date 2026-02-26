"""Kafka event publisher adapter for the AumOS Cyber Insurance service.

Wraps aumos-common EventPublisher to publish domain events on the
insurance.* topic namespace.
"""

from aumos_common.events import EventPublisher, KafkaSettings
from aumos_common.observability import get_logger

logger = get_logger(__name__)


class InsuranceEventPublisher:
    """Thin wrapper around EventPublisher for cyber insurance domain events.

    Provides a named publisher for the cyber insurance service, making
    dependency injection explicit in the lifespan context.
    """

    def __init__(self, kafka_settings: KafkaSettings) -> None:
        """Initialise the Kafka event publisher.

        Args:
            kafka_settings: Kafka broker connection settings from AumOSSettings.
        """
        self._publisher = EventPublisher(kafka_settings)

    async def start(self) -> None:
        """Start the Kafka producer connection.

        Must be called in the FastAPI lifespan startup handler.
        """
        await self._publisher.start()
        logger.info("Cyber Insurance Kafka event publisher started")

    async def stop(self) -> None:
        """Stop the Kafka producer and flush pending messages.

        Must be called in the FastAPI lifespan shutdown handler.
        """
        await self._publisher.stop()
        logger.info("Cyber Insurance Kafka event publisher stopped")

    @property
    def publisher(self) -> EventPublisher:
        """Return the underlying EventPublisher for service injection.

        Returns:
            EventPublisher instance used by all insurance services.
        """
        return self._publisher
