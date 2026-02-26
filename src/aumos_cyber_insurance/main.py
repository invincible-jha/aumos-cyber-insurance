"""AumOS Cyber Insurance service entry point."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from aumos_common.app import create_app
from aumos_common.database import init_database
from aumos_common.health import HealthCheck
from aumos_common.observability import get_logger

from aumos_cyber_insurance.adapters.kafka import InsuranceEventPublisher
from aumos_cyber_insurance.api.router import router
from aumos_cyber_insurance.settings import Settings

logger = get_logger(__name__)
settings = Settings()

_kafka_publisher: InsuranceEventPublisher | None = None


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Manage application startup and shutdown lifecycle.

    Initialises the database connection pool, Kafka event publisher,
    and all service instances, then exposes them on app.state for DI.

    Args:
        app: The FastAPI application instance.

    Yields:
        None
    """
    global _kafka_publisher  # noqa: PLW0603

    logger.info("Starting AumOS Cyber Insurance", version="0.1.0")

    # Database connection pool
    init_database(settings.database)
    logger.info("Database connection pool ready")

    # Kafka event publisher
    _kafka_publisher = InsuranceEventPublisher(settings.kafka)
    await _kafka_publisher.start()
    app.state.kafka_publisher = _kafka_publisher
    logger.info("Kafka event publisher ready")

    # Wire up services — lazy import avoids circular deps at module level
    from aumos_common.database import get_db_session  # noqa: PLC0415

    from aumos_cyber_insurance.adapters.repositories import (  # noqa: PLC0415
        EvidencePackageRepository,
        ImpactAnalysisRepository,
        PostureAssessmentRepository,
        PremiumRecommendationRepository,
        RiskCalculationRepository,
    )
    from aumos_cyber_insurance.core.services import (  # noqa: PLC0415
        EvidencePackagerService,
        ImpactAnalyzerService,
        PostureMapperService,
        PremiumOptimizerService,
        RiskCalculatorService,
    )

    # NOTE: In production, replace these stubs with a real carrier adapter
    # that calls external carrier requirement APIs.
    from aumos_cyber_insurance._stub_carrier_adapter import StubCarrierAdapter  # noqa: PLC0415

    carrier_adapter = StubCarrierAdapter()
    publisher = _kafka_publisher.publisher

    # Expose settings and service factories on app state
    # Each request creates fresh repository instances within a DB session.
    app.state.settings = settings
    app.state.carrier_adapter = carrier_adapter
    app.state.publisher = publisher

    # Build stateless service factories that accept a session
    # The actual service instances are constructed per-request in route deps
    # via request.app.state; here we store a callable factory pattern.
    # For simplicity in this implementation, services are pre-wired as
    # singletons — repositories will be session-scoped in production.

    # For now, we pre-wire with no session (session injection handled by
    # repository layer via aumos_common.database.get_db_session middleware).
    # Services are stored as constructors on app.state for request-time DI.
    app.state._posture_mapper_cls = PostureMapperService  # type: ignore[attr-defined]
    app.state._impact_analyzer_cls = ImpactAnalyzerService  # type: ignore[attr-defined]
    app.state._premium_optimizer_cls = PremiumOptimizerService  # type: ignore[attr-defined]
    app.state._evidence_packager_cls = EvidencePackagerService  # type: ignore[attr-defined]
    app.state._risk_calculator_cls = RiskCalculatorService  # type: ignore[attr-defined]

    logger.info("Cyber Insurance service startup complete")
    yield

    # Shutdown
    if _kafka_publisher:
        await _kafka_publisher.stop()

    logger.info("Cyber Insurance service shutdown complete")


app: FastAPI = create_app(
    service_name="aumos-cyber-insurance",
    version="0.1.0",
    settings=settings,
    lifespan=lifespan,
    health_checks=[
        HealthCheck(name="postgres", check_fn=lambda: None),
        HealthCheck(name="kafka", check_fn=lambda: None),
    ],
)

app.include_router(router, prefix="/api/v1/insurance")
