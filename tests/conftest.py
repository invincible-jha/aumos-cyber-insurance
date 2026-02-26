"""Shared pytest fixtures for the AumOS Cyber Insurance test suite."""

import uuid
from collections.abc import AsyncGenerator
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from aumos_cyber_insurance._stub_carrier_adapter import StubCarrierAdapter
from aumos_cyber_insurance.core.models import PostureAssessment
from aumos_cyber_insurance.core.services import (
    EvidencePackagerService,
    ImpactAnalyzerService,
    PostureMapperService,
    PremiumOptimizerService,
    RiskCalculatorService,
)


@pytest.fixture
def tenant_id() -> uuid.UUID:
    """Return a fixed tenant UUID for tests."""
    return uuid.UUID("00000000-0000-0000-0000-000000000001")


@pytest.fixture
def user_id() -> uuid.UUID:
    """Return a fixed user UUID for tests."""
    return uuid.UUID("00000000-0000-0000-0000-000000000002")


@pytest.fixture
def mock_event_publisher() -> MagicMock:
    """Return a mocked EventPublisher that records publish calls."""
    publisher = MagicMock()
    publisher.publish = AsyncMock()
    return publisher


@pytest.fixture
def stub_carrier_adapter() -> StubCarrierAdapter:
    """Return the stub carrier adapter for testing."""
    return StubCarrierAdapter()


@pytest.fixture
def mock_posture_repo() -> MagicMock:
    """Return a mocked PostureAssessmentRepository."""
    repo = MagicMock()
    repo.create = AsyncMock()
    repo.get = AsyncMock()
    repo.list_by_tenant = AsyncMock()
    repo.update_status = AsyncMock()
    return repo


@pytest.fixture
def mock_impact_repo() -> MagicMock:
    """Return a mocked ImpactAnalysisRepository."""
    repo = MagicMock()
    repo.create = AsyncMock()
    repo.get = AsyncMock()
    repo.list_by_assessment = AsyncMock()
    repo.update_results = AsyncMock()
    return repo


@pytest.fixture
def mock_premium_repo() -> MagicMock:
    """Return a mocked PremiumRecommendationRepository."""
    repo = MagicMock()
    repo.create = AsyncMock()
    repo.get = AsyncMock()
    repo.list_by_assessment = AsyncMock()
    repo.update_results = AsyncMock()
    return repo


@pytest.fixture
def mock_evidence_repo() -> MagicMock:
    """Return a mocked EvidencePackageRepository."""
    repo = MagicMock()
    repo.create = AsyncMock()
    repo.get = AsyncMock()
    repo.list_by_assessment = AsyncMock()
    repo.update_status = AsyncMock()
    return repo


@pytest.fixture
def mock_risk_repo() -> MagicMock:
    """Return a mocked RiskCalculationRepository."""
    repo = MagicMock()
    repo.create = AsyncMock()
    repo.get = AsyncMock()
    repo.list_by_assessment = AsyncMock()
    repo.update_results = AsyncMock()
    return repo


@pytest.fixture
def sample_posture_assessment(tenant_id: uuid.UUID) -> PostureAssessment:
    """Return a sample completed PostureAssessment for test use."""
    assessment = PostureAssessment()
    assessment.id = uuid.uuid4()
    assessment.tenant_id = tenant_id
    assessment.platform_id = "prod-aws-us-east-1"
    assessment.platform_type = "cloud"
    assessment.carrier_id = None
    assessment.status = "completed"
    assessment.posture_score = 0.75
    assessment.control_coverage = {
        "mfa": 0.90,
        "endpoint_detection": 0.70,
        "backup_recovery": 0.80,
    }
    assessment.gaps = [
        {"control_id": "coal-edr-001", "severity": "medium", "description": "EDR below threshold", "carrier_ids": ["coalition"]},
    ]
    assessment.carrier_requirements_met = {
        "coalition": {"coal-mfa-001": True, "coal-edr-001": False, "coal-bak-001": True}
    }
    assessment.assessment_metadata = {}
    assessment.completed_at = None
    assessment.error_message = None
    assessment.requested_by = None
    return assessment


@pytest.fixture
def posture_mapper_service(
    mock_posture_repo: MagicMock,
    stub_carrier_adapter: StubCarrierAdapter,
    mock_event_publisher: MagicMock,
) -> PostureMapperService:
    """Return a PostureMapperService wired with mocks."""
    return PostureMapperService(
        posture_repo=mock_posture_repo,
        carrier_adapter=stub_carrier_adapter,
        event_publisher=mock_event_publisher,
    )
