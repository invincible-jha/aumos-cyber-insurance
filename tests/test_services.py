"""Unit tests for AumOS Cyber Insurance service layer."""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from aumos_cyber_insurance.core.services import (
    PostureMapperService,
    PremiumOptimizerService,
    RiskCalculatorService,
    _compute_posture_score,
    _compute_residual_risk,
    _run_premium_optimization,
)


class TestComputePostureScore:
    """Tests for the posture score computation helper."""

    def test_empty_coverage_returns_zero(self) -> None:
        """Empty coverage dict should return 0.0."""
        assert _compute_posture_score({}) == 0.0

    def test_full_coverage_returns_one(self) -> None:
        """All controls at 1.0 should return 1.0."""
        score = _compute_posture_score({"mfa": 1.0, "backup": 1.0, "edr": 1.0})
        assert score == 1.0

    def test_partial_coverage_returns_average(self) -> None:
        """Partial coverage should return the average."""
        score = _compute_posture_score({"mfa": 0.8, "backup": 0.6})
        assert score == pytest.approx(0.7)

    def test_single_control_returns_its_value(self) -> None:
        """Single control dict should return that value."""
        assert _compute_posture_score({"mfa": 0.95}) == pytest.approx(0.95)


class TestComputeResidualRisk:
    """Tests for the residual risk computation helper."""

    def test_no_controls_returns_baseline(self) -> None:
        """No controls applied should leave risk unchanged."""
        residual, reduction = _compute_residual_risk(0.5, [])
        assert residual == 0.5
        assert reduction == 0.0

    def test_controls_reduce_risk(self) -> None:
        """Controls with positive effectiveness should reduce risk."""
        controls = [{"effectiveness_pct": 80.0, "weight": 1.0}]
        residual, reduction = _compute_residual_risk(0.6, controls)
        assert residual < 0.6
        assert reduction > 0.0

    def test_reduction_capped_at_ninety_percent(self) -> None:
        """Risk reduction should not exceed 90% of baseline."""
        controls = [{"effectiveness_pct": 100.0, "weight": 1.0}]
        residual, reduction = _compute_residual_risk(1.0, controls)
        assert residual >= 0.1

    def test_zero_baseline_risk_returns_zero_reduction(self) -> None:
        """Zero baseline risk should result in zero residual and small reduction."""
        controls = [{"effectiveness_pct": 80.0, "weight": 1.0}]
        residual, reduction = _compute_residual_risk(0.0, controls)
        assert residual == 0.0


class TestRunPremiumOptimization:
    """Tests for the premium optimization helper."""

    def test_no_gaps_yields_discount_based_on_score(self) -> None:
        """High posture score with no gaps should yield positive discount."""
        controls, discount, roi, confidence = _run_premium_optimization(
            gaps=[],
            posture_score=0.8,
            current_premium_usd=50_000.0,
            sample_size=1000,
            discount_cap=35.0,
        )
        assert discount > 0.0
        assert discount <= 35.0

    def test_discount_never_exceeds_cap(self) -> None:
        """Discount should be capped at the configured cap percentage."""
        _, discount, _, _ = _run_premium_optimization(
            gaps=[],
            posture_score=1.0,
            current_premium_usd=100_000.0,
            sample_size=1000,
            discount_cap=25.0,
        )
        assert discount <= 25.0

    def test_roi_analysis_has_expected_keys(self) -> None:
        """ROI analysis dict should contain the required keys."""
        _, _, roi, _ = _run_premium_optimization(
            gaps=[],
            posture_score=0.7,
            current_premium_usd=60_000.0,
            sample_size=1000,
            discount_cap=35.0,
        )
        assert "total_investment_usd" in roi
        assert "annual_savings_usd" in roi
        assert "payback_months" in roi

    def test_confidence_interval_has_bounds(self) -> None:
        """Confidence interval dict should have lower and upper bounds."""
        _, _, _, confidence = _run_premium_optimization(
            gaps=[],
            posture_score=0.7,
            current_premium_usd=60_000.0,
            sample_size=1000,
            discount_cap=35.0,
        )
        assert "lower_usd" in confidence
        assert "upper_usd" in confidence
        assert confidence["lower_usd"] <= confidence["upper_usd"]


class TestPostureMapperService:
    """Tests for PostureMapperService."""

    @pytest.mark.asyncio
    async def test_assess_posture_invalid_platform_type_raises(
        self,
        posture_mapper_service: PostureMapperService,
        tenant_id: uuid.UUID,
    ) -> None:
        """Invalid platform_type should raise ValueError before any DB call."""
        with pytest.raises(ValueError, match="Invalid platform_type"):
            await posture_mapper_service.assess_posture(
                tenant_id=tenant_id,
                platform_id="test-platform",
                platform_type="invalid_type",
                carrier_id=None,
                control_coverage={},
                requested_by=None,
                assessment_metadata={},
            )

    @pytest.mark.asyncio
    async def test_assess_posture_creates_and_completes(
        self,
        posture_mapper_service: PostureMapperService,
        mock_posture_repo: MagicMock,
        tenant_id: uuid.UUID,
    ) -> None:
        """Successful assessment should create record, compute score, and publish event."""
        assessment_id = uuid.uuid4()
        mock_assessment = MagicMock()
        mock_assessment.id = assessment_id
        mock_assessment.gaps = []
        mock_assessment.carrier_requirements_met = {}

        mock_posture_repo.create.return_value = mock_assessment
        mock_posture_repo.update_status.return_value = mock_assessment

        result = await posture_mapper_service.assess_posture(
            tenant_id=tenant_id,
            platform_id="prod-aws",
            platform_type="cloud",
            carrier_id="coalition",
            control_coverage={"mfa": 0.90, "endpoint_detection": 0.75, "backup_recovery": 0.80},
            requested_by=None,
            assessment_metadata={},
        )

        mock_posture_repo.create.assert_called_once()
        mock_posture_repo.update_status.assert_called_once()
        assert result is mock_assessment

    @pytest.mark.asyncio
    async def test_get_posture_status_not_found_raises(
        self,
        posture_mapper_service: PostureMapperService,
        mock_posture_repo: MagicMock,
        tenant_id: uuid.UUID,
    ) -> None:
        """get_posture_status should raise NotFoundError when assessment missing."""
        from aumos_common.errors import NotFoundError

        mock_posture_repo.get.return_value = None
        with pytest.raises(NotFoundError):
            await posture_mapper_service.get_posture_status(tenant_id, uuid.uuid4())


class TestRiskCalculatorService:
    """Tests for RiskCalculatorService."""

    @pytest.mark.asyncio
    async def test_invalid_methodology_raises(
        self,
        mock_risk_repo: MagicMock,
        mock_posture_repo: MagicMock,
        mock_event_publisher: MagicMock,
        tenant_id: uuid.UUID,
    ) -> None:
        """Invalid methodology should raise ValueError."""
        service = RiskCalculatorService(
            risk_repo=mock_risk_repo,
            posture_repo=mock_posture_repo,
            event_publisher=mock_event_publisher,
        )
        with pytest.raises(ValueError, match="Invalid methodology"):
            await service.calculate_risk_reduction(
                tenant_id=tenant_id,
                assessment_id=uuid.uuid4(),
                calculation_type="annualized_loss",
                methodology="invalid_method",
                controls_to_apply=[],
                threat_scenarios=[],
                asset_value_usd=None,
            )
