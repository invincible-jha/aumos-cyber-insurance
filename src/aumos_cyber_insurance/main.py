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
    all service instances, and optional APScheduler background jobs
    (continuous monitoring, regulatory monitoring), then exposes them
    on app.state for DI.

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
        BoardReportService,
        ContinuousMonitoringService,
        EvidencePackagerService,
        ImpactAnalyzerService,
        PostureMapperService,
        PremiumOptimizerService,
        RegulatoryMonitoringService,
        RiskCalculatorService,
    )

    publisher = _kafka_publisher.publisher

    # ---------------------------------------------------------------------------
    # GAP-517: Carrier adapter selection — stub (dev) or database (production)
    # ---------------------------------------------------------------------------
    if settings.carrier_adapter == "database":
        from aumos_cyber_insurance.adapters.carrier_database import DatabaseCarrierAdapter  # noqa: PLC0415

        # DatabaseCarrierAdapter requires a session; we store the class and
        # create instances per-request. For background tasks, a dedicated
        # session must be passed at call time.
        carrier_adapter_cls = DatabaseCarrierAdapter
        logger.info("Using DatabaseCarrierAdapter (production mode)")
    else:
        from aumos_cyber_insurance._stub_carrier_adapter import StubCarrierAdapter  # noqa: PLC0415

        carrier_adapter_cls = StubCarrierAdapter  # type: ignore[assignment]
        logger.info("Using StubCarrierAdapter (development mode)")

    carrier_adapter = carrier_adapter_cls() if settings.carrier_adapter != "database" else None

    app.state.settings = settings
    app.state.carrier_adapter = carrier_adapter
    app.state.carrier_adapter_cls = carrier_adapter_cls
    app.state.publisher = publisher

    # Store service class references for request-time DI
    app.state._posture_mapper_cls = PostureMapperService  # type: ignore[attr-defined]
    app.state._impact_analyzer_cls = ImpactAnalyzerService  # type: ignore[attr-defined]
    app.state._premium_optimizer_cls = PremiumOptimizerService  # type: ignore[attr-defined]
    app.state._evidence_packager_cls = EvidencePackagerService  # type: ignore[attr-defined]
    app.state._risk_calculator_cls = RiskCalculatorService  # type: ignore[attr-defined]

    # ---------------------------------------------------------------------------
    # GAP-518: APScheduler continuous monitoring
    # GAP-524: Daily posture score snapshot via ContinuousMonitoringService
    # ---------------------------------------------------------------------------
    scheduler = None
    if settings.continuous_monitoring_enabled or settings.regulatory_monitoring_enabled:
        try:
            from apscheduler.schedulers.asyncio import AsyncIOScheduler  # type: ignore[import-untyped]  # noqa: PLC0415

            scheduler = AsyncIOScheduler()

            if settings.continuous_monitoring_enabled:
                # Build a stub posture repo for background use (session-less placeholder)
                continuous_monitoring_service = ContinuousMonitoringService(
                    posture_repo=None,  # type: ignore[arg-type]  # will be replaced per-run
                    event_publisher=publisher,
                    drift_alert_threshold=settings.drift_alert_threshold,
                )
                app.state.continuous_monitoring_service = continuous_monitoring_service

                scheduler.add_job(
                    continuous_monitoring_service.run_monitoring_cycle,
                    trigger="cron",
                    hour=settings.monitoring_schedule_hour,
                    minute=0,
                    id="continuous_posture_monitoring",
                    replace_existing=True,
                )
                logger.info(
                    "Continuous posture monitoring scheduled",
                    hour=settings.monitoring_schedule_hour,
                    drift_threshold=settings.drift_alert_threshold,
                )

            # GAP-523: Regulatory monitoring scheduler
            if settings.regulatory_monitoring_enabled:
                regulatory_service = RegulatoryMonitoringService(
                    event_publisher=publisher,
                    feed_urls=settings.regulatory_feed_urls,
                )
                app.state.regulatory_monitoring_service = regulatory_service

                scheduler.add_job(
                    regulatory_service.run_monitoring_cycle,
                    trigger="interval",
                    hours=settings.regulatory_check_interval_hours,
                    id="regulatory_monitoring",
                    replace_existing=True,
                )
                logger.info(
                    "Regulatory monitoring scheduled",
                    interval_hours=settings.regulatory_check_interval_hours,
                    feed_count=len(settings.regulatory_feed_urls),
                )

            scheduler.start()
            app.state.scheduler = scheduler
            logger.info("APScheduler started")

        except ImportError:
            logger.warning(
                "apscheduler not installed — background monitoring disabled. "
                "Install with: pip install apscheduler>=3.10.4"
            )

    # GAP-519: Board report service
    board_report_service = BoardReportService(
        posture_repo=None,  # type: ignore[arg-type]  # injected per-request
        template_dir=settings.board_report_template_dir,
        logo_url=settings.board_report_logo_url,
    )
    app.state.board_report_service = board_report_service

    logger.info("Cyber Insurance service startup complete")
    yield

    # Shutdown
    if scheduler is not None:
        scheduler.shutdown(wait=False)
        logger.info("APScheduler shutdown")

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
