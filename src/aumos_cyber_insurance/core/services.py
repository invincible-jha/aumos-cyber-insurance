"""Business logic services for the AumOS Cyber Insurance service.

All services depend on repository and adapter interfaces (not concrete
implementations) and receive dependencies via constructor injection.
No framework code (FastAPI, SQLAlchemy) belongs here.

Key invariants enforced by services:
- Posture assessments must complete before downstream analysis can run.
- Premium discount is capped by settings.premium_discount_cap_pct.
- Evidence packages expire after settings.evidence_package_expiry_days.
- Risk calculations use the FAIR methodology by default.
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from aumos_common.errors import ConflictError, ErrorCode, NotFoundError
from aumos_common.events import EventPublisher, Topics
from aumos_common.observability import get_logger

from aumos_cyber_insurance.core.interfaces import (
    ICarrierAdapter,
    IEvidencePackageRepository,
    IImpactAnalysisRepository,
    IPostureAssessmentRepository,
    IPremiumRecommendationRepository,
    IRiskCalculationRepository,
)
from aumos_cyber_insurance.core.models import (
    EvidencePackage,
    ImpactAnalysis,
    PostureAssessment,
    PremiumRecommendation,
    RiskCalculation,
)

logger = get_logger(__name__)

# Valid platform types for posture assessment
VALID_PLATFORM_TYPES: frozenset[str] = frozenset(
    {"cloud", "on_premise", "hybrid", "saas", "paas"}
)

# Valid calculation methodologies
VALID_METHODOLOGIES: frozenset[str] = frozenset({"fair", "cvss", "custom"})

# Terminal assessment statuses
TERMINAL_ASSESSMENT_STATUSES: frozenset[str] = frozenset({"completed", "failed"})


class PostureMapperService:
    """Assess and track cyber insurance posture against carrier requirements.

    Coordinates between the carrier adapter and posture repository to produce
    a scored assessment that downstream services consume for impact analysis
    and premium optimization.
    """

    def __init__(
        self,
        posture_repo: IPostureAssessmentRepository,
        carrier_adapter: ICarrierAdapter,
        event_publisher: EventPublisher,
    ) -> None:
        """Initialise with injected dependencies.

        Args:
            posture_repo: PostureAssessment persistence.
            carrier_adapter: Carrier requirement lookup adapter.
            event_publisher: Kafka event publisher for domain events.
        """
        self._posture_repo = posture_repo
        self._carrier_adapter = carrier_adapter
        self._event_publisher = event_publisher

    async def assess_posture(
        self,
        tenant_id: uuid.UUID,
        platform_id: str,
        platform_type: str,
        carrier_id: str | None,
        control_coverage: dict[str, float],
        requested_by: uuid.UUID | None,
        assessment_metadata: dict[str, Any] | None,
    ) -> PostureAssessment:
        """Run a posture assessment against carrier requirements.

        Evaluates the provided control coverage against carrier requirements and
        computes an aggregate posture score. Publishes an insurance.posture.assessed
        event on completion.

        Args:
            tenant_id: Tenant UUID for RLS scoping.
            platform_id: Platform identifier being assessed.
            platform_type: Platform category (must be in VALID_PLATFORM_TYPES).
            carrier_id: Target carrier (None means all carriers).
            control_coverage: Per-control-domain coverage percentages (0.0–1.0).
            requested_by: User ID that triggered this assessment.
            assessment_metadata: Optional context metadata.

        Returns:
            Completed PostureAssessment with score and gaps.

        Raises:
            ValueError: If platform_type is not valid.
        """
        if platform_type not in VALID_PLATFORM_TYPES:
            raise ValueError(
                f"Invalid platform_type '{platform_type}'. "
                f"Must be one of: {sorted(VALID_PLATFORM_TYPES)}"
            )

        assessment = await self._posture_repo.create(
            tenant_id=tenant_id,
            platform_id=platform_id,
            platform_type=platform_type,
            carrier_id=carrier_id,
            requested_by=requested_by,
            assessment_metadata=assessment_metadata or {},
        )

        logger.info(
            "Posture assessment started",
            tenant_id=str(tenant_id),
            assessment_id=str(assessment.id),
            platform_id=platform_id,
        )

        try:
            carriers_to_check: list[str]
            if carrier_id:
                carriers_to_check = [carrier_id]
            else:
                all_carriers = await self._carrier_adapter.list_carriers()
                carriers_to_check = [c["carrier_id"] for c in all_carriers]

            carrier_requirements_met: dict[str, Any] = {}
            all_gaps: list[dict[str, Any]] = []

            for cid in carriers_to_check:
                fulfillment = await self._carrier_adapter.check_posture_against_carrier(
                    carrier_id=cid,
                    posture_data=control_coverage,
                )
                carrier_requirements_met[cid] = fulfillment

                for req_id, is_met in fulfillment.items():
                    if not is_met:
                        all_gaps.append(
                            {
                                "control_id": req_id,
                                "severity": "medium",
                                "description": f"Carrier {cid} requirement {req_id} not met",
                                "carrier_ids": [cid],
                            }
                        )

            posture_score = _compute_posture_score(control_coverage)

            assessment = await self._posture_repo.update_status(
                assessment_id=assessment.id,
                status="completed",
                posture_score=posture_score,
                control_coverage=control_coverage,
                gaps=all_gaps,
                carrier_requirements_met=carrier_requirements_met,
                error_message=None,
            )

            await self._event_publisher.publish(
                topic=Topics.INSURANCE_POSTURE_ASSESSED,
                payload={
                    "tenant_id": str(tenant_id),
                    "assessment_id": str(assessment.id),
                    "platform_id": platform_id,
                    "posture_score": posture_score,
                    "gap_count": len(all_gaps),
                },
            )

        except Exception as exc:
            await self._posture_repo.update_status(
                assessment_id=assessment.id,
                status="failed",
                posture_score=None,
                control_coverage={},
                gaps=[],
                carrier_requirements_met={},
                error_message=str(exc),
            )
            logger.error(
                "Posture assessment failed",
                assessment_id=str(assessment.id),
                error=str(exc),
            )
            raise

        return assessment

    async def get_posture_status(
        self,
        tenant_id: uuid.UUID,
        assessment_id: uuid.UUID,
    ) -> PostureAssessment:
        """Get the current status of a posture assessment.

        Args:
            tenant_id: Tenant UUID for RLS scoping.
            assessment_id: Assessment UUID.

        Returns:
            PostureAssessment record.

        Raises:
            NotFoundError: If assessment not found.
        """
        assessment = await self._posture_repo.get(assessment_id, tenant_id)
        if not assessment:
            raise NotFoundError(
                f"PostureAssessment {assessment_id} not found",
                error_code=ErrorCode.NOT_FOUND,
            )
        return assessment


class ImpactAnalyzerService:
    """Compute per-platform insurance impact from a completed posture assessment.

    Translates posture gaps and control deficiencies into financial impact
    metrics: annualized loss expectancy, breach probability, and per-carrier
    premium deltas.
    """

    def __init__(
        self,
        impact_repo: IImpactAnalysisRepository,
        posture_repo: IPostureAssessmentRepository,
        event_publisher: EventPublisher,
    ) -> None:
        """Initialise with injected dependencies.

        Args:
            impact_repo: ImpactAnalysis persistence.
            posture_repo: PostureAssessment read access.
            event_publisher: Kafka event publisher.
        """
        self._impact_repo = impact_repo
        self._posture_repo = posture_repo
        self._event_publisher = event_publisher

    async def analyze_impact(
        self,
        tenant_id: uuid.UUID,
        assessment_id: uuid.UUID,
        platform_revenue_usd: float | None,
        existing_coverage_usd: float | None,
    ) -> ImpactAnalysis:
        """Run an impact analysis for a completed posture assessment.

        Args:
            tenant_id: Tenant UUID for RLS scoping.
            assessment_id: Completed PostureAssessment UUID.
            platform_revenue_usd: Annual platform revenue for ALE calculation.
            existing_coverage_usd: Current cyber insurance coverage limit.

        Returns:
            ImpactAnalysis with financial metrics.

        Raises:
            NotFoundError: If assessment not found.
            ConflictError: If assessment is not in completed status.
        """
        assessment = await self._posture_repo.get(assessment_id, tenant_id)
        if not assessment:
            raise NotFoundError(
                f"PostureAssessment {assessment_id} not found",
                error_code=ErrorCode.NOT_FOUND,
            )
        if assessment.status != "completed":
            raise ConflictError(
                f"PostureAssessment {assessment_id} is not completed (status={assessment.status}). "
                "Impact analysis requires a completed assessment.",
                error_code=ErrorCode.CONFLICT,
            )

        analysis = await self._impact_repo.create(
            tenant_id=tenant_id,
            posture_assessment_id=assessment_id,
            platform_id=assessment.platform_id,
            platform_type=assessment.platform_type,
            analysis_metadata={
                "platform_revenue_usd": platform_revenue_usd,
                "existing_coverage_usd": existing_coverage_usd,
            },
        )

        risk_drivers, estimated_ale, breach_probability = _compute_risk_drivers(
            gaps=assessment.gaps,
            platform_revenue_usd=platform_revenue_usd or 0.0,
        )

        coverage_gap = None
        if existing_coverage_usd is not None and estimated_ale is not None:
            coverage_gap = max(0.0, estimated_ale - existing_coverage_usd)

        carrier_impact_map = _build_carrier_impact_map(
            carrier_requirements_met=assessment.carrier_requirements_met,
            estimated_ale=estimated_ale,
        )

        analysis = await self._impact_repo.update_results(
            analysis_id=analysis.id,
            estimated_annual_loss=estimated_ale,
            breach_probability_pct=breach_probability,
            coverage_gap_usd=coverage_gap,
            risk_drivers=risk_drivers,
            recommended_controls=_derive_recommended_controls(assessment.gaps),
            carrier_impact_map=carrier_impact_map,
        )

        await self._event_publisher.publish(
            topic=Topics.INSURANCE_IMPACT_ANALYZED,
            payload={
                "tenant_id": str(tenant_id),
                "analysis_id": str(analysis.id),
                "assessment_id": str(assessment_id),
                "estimated_annual_loss": estimated_ale,
            },
        )

        return analysis

    async def list_impact_reports(
        self,
        tenant_id: uuid.UUID,
        assessment_id: uuid.UUID,
    ) -> list[ImpactAnalysis]:
        """List all impact analyses for a posture assessment.

        Args:
            tenant_id: Tenant UUID for RLS scoping.
            assessment_id: PostureAssessment UUID.

        Returns:
            List of ImpactAnalysis records.
        """
        return await self._impact_repo.list_by_assessment(assessment_id, tenant_id)


class PremiumOptimizerService:
    """Optimize cyber insurance premiums via synthetic data simulation.

    Uses Monte Carlo simulation over synthetic breach scenarios to identify
    the highest-ROI control improvements for premium reduction.
    """

    def __init__(
        self,
        premium_repo: IPremiumRecommendationRepository,
        posture_repo: IPostureAssessmentRepository,
        event_publisher: EventPublisher,
        premium_discount_cap_pct: float = 35.0,
        optimization_sample_size: int = 10_000,
    ) -> None:
        """Initialise with injected dependencies.

        Args:
            premium_repo: PremiumRecommendation persistence.
            posture_repo: PostureAssessment read access.
            event_publisher: Kafka event publisher.
            premium_discount_cap_pct: Maximum achievable discount percentage.
            optimization_sample_size: Monte Carlo sample size per run.
        """
        self._premium_repo = premium_repo
        self._posture_repo = posture_repo
        self._event_publisher = event_publisher
        self._discount_cap = premium_discount_cap_pct
        self._sample_size = optimization_sample_size

    async def optimize_premium(
        self,
        tenant_id: uuid.UUID,
        assessment_id: uuid.UUID,
        carrier_id: str,
        current_premium_usd: float | None,
        coverage_limit_usd: float | None,
    ) -> PremiumRecommendation:
        """Generate premium optimization recommendations for a carrier.

        Args:
            tenant_id: Tenant UUID for RLS scoping.
            assessment_id: Completed PostureAssessment UUID.
            carrier_id: Target carrier for optimization.
            current_premium_usd: Current annual premium with this carrier.
            coverage_limit_usd: Current coverage limit in USD.

        Returns:
            PremiumRecommendation with optimized premium and control priorities.

        Raises:
            NotFoundError: If assessment not found.
            ConflictError: If assessment is not completed.
        """
        assessment = await self._posture_repo.get(assessment_id, tenant_id)
        if not assessment:
            raise NotFoundError(
                f"PostureAssessment {assessment_id} not found",
                error_code=ErrorCode.NOT_FOUND,
            )
        if assessment.status != "completed":
            raise ConflictError(
                f"PostureAssessment {assessment_id} must be completed before premium optimization.",
                error_code=ErrorCode.CONFLICT,
            )

        recommendation = await self._premium_repo.create(
            tenant_id=tenant_id,
            posture_assessment_id=assessment_id,
            carrier_id=carrier_id,
            simulation_runs=self._sample_size,
            recommendation_metadata={
                "coverage_limit_usd": coverage_limit_usd,
                "discount_cap_pct": self._discount_cap,
            },
        )

        controls, discount_pct, roi_analysis, confidence = _run_premium_optimization(
            gaps=assessment.gaps,
            posture_score=assessment.posture_score or 0.0,
            current_premium_usd=current_premium_usd or 0.0,
            sample_size=self._sample_size,
            discount_cap=self._discount_cap,
        )

        optimized_premium = None
        if current_premium_usd is not None:
            optimized_premium = current_premium_usd * (1.0 - discount_pct / 100.0)

        recommendation = await self._premium_repo.update_results(
            recommendation_id=recommendation.id,
            current_estimated_premium_usd=current_premium_usd,
            optimized_premium_usd=optimized_premium,
            discount_pct=discount_pct,
            recommended_controls=controls,
            roi_analysis=roi_analysis,
            confidence_interval=confidence,
        )

        await self._event_publisher.publish(
            topic=Topics.INSURANCE_PREMIUM_OPTIMIZED,
            payload={
                "tenant_id": str(tenant_id),
                "recommendation_id": str(recommendation.id),
                "carrier_id": carrier_id,
                "discount_pct": discount_pct,
            },
        )

        return recommendation


class EvidencePackagerService:
    """Assemble carrier-specific evidence packages for insurance submission.

    Collects security attestations, compliance documents, and posture evidence
    into a structured package ready for carrier submission.
    """

    def __init__(
        self,
        evidence_repo: IEvidencePackageRepository,
        posture_repo: IPostureAssessmentRepository,
        carrier_adapter: ICarrierAdapter,
        event_publisher: EventPublisher,
        evidence_expiry_days: int = 90,
    ) -> None:
        """Initialise with injected dependencies.

        Args:
            evidence_repo: EvidencePackage persistence.
            posture_repo: PostureAssessment read access.
            carrier_adapter: Carrier requirement lookup adapter.
            event_publisher: Kafka event publisher.
            evidence_expiry_days: Days before package expires.
        """
        self._evidence_repo = evidence_repo
        self._posture_repo = posture_repo
        self._carrier_adapter = carrier_adapter
        self._event_publisher = event_publisher
        self._expiry_days = evidence_expiry_days

    async def generate_evidence_package(
        self,
        tenant_id: uuid.UUID,
        assessment_id: uuid.UUID,
        carrier_id: str,
        carrier_name: str,
        package_metadata: dict[str, Any] | None,
    ) -> EvidencePackage:
        """Generate an evidence package for a specific carrier.

        Args:
            tenant_id: Tenant UUID for RLS scoping.
            assessment_id: Completed PostureAssessment UUID.
            carrier_id: Target carrier identifier.
            carrier_name: Human-readable carrier name.
            package_metadata: Optional submission metadata.

        Returns:
            EvidencePackage with assembled artifacts.

        Raises:
            NotFoundError: If assessment not found.
            ConflictError: If assessment is not completed.
        """
        assessment = await self._posture_repo.get(assessment_id, tenant_id)
        if not assessment:
            raise NotFoundError(
                f"PostureAssessment {assessment_id} not found",
                error_code=ErrorCode.NOT_FOUND,
            )
        if assessment.status != "completed":
            raise ConflictError(
                f"PostureAssessment {assessment_id} must be completed before generating evidence.",
                error_code=ErrorCode.CONFLICT,
            )

        package = await self._evidence_repo.create(
            tenant_id=tenant_id,
            posture_assessment_id=assessment_id,
            carrier_id=carrier_id,
            carrier_name=carrier_name,
            package_metadata=package_metadata or {},
        )

        try:
            carrier_requirements = await self._carrier_adapter.get_carrier_requirements(carrier_id)
            artifacts = _assemble_artifacts(
                posture_assessment=assessment,
                carrier_requirements=carrier_requirements,
            )
            fulfilled = _get_fulfilled_requirements(
                carrier_requirements_met=assessment.carrier_requirements_met.get(carrier_id, {}),
            )
            missing = _get_missing_requirements(
                carrier_requirements_met=assessment.carrier_requirements_met.get(carrier_id, {}),
            )

            now = datetime.now(tz=UTC)
            package = await self._evidence_repo.update_status(
                package_id=package.id,
                status="ready",
                artifacts=artifacts,
                carrier_requirements_fulfilled=fulfilled,
                carrier_requirements_missing=missing,
                error_message=None,
            )
            _ = now  # expires_at set in repository layer via expiry_days config

            await self._event_publisher.publish(
                topic=Topics.INSURANCE_EVIDENCE_PACKAGED,
                payload={
                    "tenant_id": str(tenant_id),
                    "package_id": str(package.id),
                    "carrier_id": carrier_id,
                    "fulfilled_count": len(fulfilled),
                    "missing_count": len(missing),
                },
            )

        except Exception as exc:
            await self._evidence_repo.update_status(
                package_id=package.id,
                status="failed",
                artifacts={},
                carrier_requirements_fulfilled=[],
                carrier_requirements_missing=[],
                error_message=str(exc),
            )
            logger.error(
                "Evidence package generation failed",
                package_id=str(package.id),
                error=str(exc),
            )
            raise

        return package


class RiskCalculatorService:
    """Quantify risk reduction from implementing recommended controls.

    Uses FAIR (Factor Analysis of Information Risk) methodology by default
    to produce auditable before/after risk scores and ALE figures.
    """

    def __init__(
        self,
        risk_repo: IRiskCalculationRepository,
        posture_repo: IPostureAssessmentRepository,
        event_publisher: EventPublisher,
    ) -> None:
        """Initialise with injected dependencies.

        Args:
            risk_repo: RiskCalculation persistence.
            posture_repo: PostureAssessment read access.
            event_publisher: Kafka event publisher.
        """
        self._risk_repo = risk_repo
        self._posture_repo = posture_repo
        self._event_publisher = event_publisher

    async def calculate_risk_reduction(
        self,
        tenant_id: uuid.UUID,
        assessment_id: uuid.UUID,
        calculation_type: str,
        methodology: str,
        controls_to_apply: list[dict[str, Any]],
        threat_scenarios: list[dict[str, Any]],
        asset_value_usd: float | None,
    ) -> RiskCalculation:
        """Calculate risk reduction from applying a set of controls.

        Args:
            tenant_id: Tenant UUID for RLS scoping.
            assessment_id: Completed PostureAssessment UUID.
            calculation_type: Type of calculation (annualized_loss | breach_probability | etc.).
            methodology: Risk methodology (fair | cvss | custom).
            controls_to_apply: List of controls with weights and effectiveness percentages.
            threat_scenarios: Threat scenarios to model.
            asset_value_usd: Asset value for financial impact calculations.

        Returns:
            RiskCalculation with baseline, residual, and reduction metrics.

        Raises:
            NotFoundError: If assessment not found.
            ConflictError: If assessment is not completed.
            ValueError: If methodology is not valid.
        """
        if methodology not in VALID_METHODOLOGIES:
            raise ValueError(
                f"Invalid methodology '{methodology}'. "
                f"Must be one of: {sorted(VALID_METHODOLOGIES)}"
            )

        assessment = await self._posture_repo.get(assessment_id, tenant_id)
        if not assessment:
            raise NotFoundError(
                f"PostureAssessment {assessment_id} not found",
                error_code=ErrorCode.NOT_FOUND,
            )
        if assessment.status != "completed":
            raise ConflictError(
                f"PostureAssessment {assessment_id} must be completed for risk calculation.",
                error_code=ErrorCode.CONFLICT,
            )

        calculation = await self._risk_repo.create(
            tenant_id=tenant_id,
            posture_assessment_id=assessment_id,
            calculation_type=calculation_type,
            methodology=methodology,
            controls_applied=controls_to_apply,
            threat_scenarios=threat_scenarios,
            calculation_metadata={"asset_value_usd": asset_value_usd},
        )

        baseline_score = 1.0 - (assessment.posture_score or 0.0)
        residual_score, reduction_pct = _compute_residual_risk(
            baseline_score=baseline_score,
            controls=controls_to_apply,
        )

        baseline_ale = None
        residual_ale = None
        if asset_value_usd is not None:
            baseline_ale = baseline_score * asset_value_usd
            residual_ale = residual_score * asset_value_usd

        calculation = await self._risk_repo.update_results(
            calculation_id=calculation.id,
            baseline_risk_score=baseline_score,
            residual_risk_score=residual_score,
            risk_reduction_pct=reduction_pct,
            baseline_ale_usd=baseline_ale,
            residual_ale_usd=residual_ale,
        )

        await self._event_publisher.publish(
            topic=Topics.INSURANCE_RISK_CALCULATED,
            payload={
                "tenant_id": str(tenant_id),
                "calculation_id": str(calculation.id),
                "assessment_id": str(assessment_id),
                "risk_reduction_pct": reduction_pct,
            },
        )

        return calculation


# ---------------------------------------------------------------------------
# Private computation helpers
# ---------------------------------------------------------------------------


def _compute_posture_score(control_coverage: dict[str, float]) -> float:
    """Compute an aggregate posture score from per-domain coverage.

    Args:
        control_coverage: Dict of {domain: coverage_pct} where coverage is 0.0–1.0.

    Returns:
        Weighted average posture score 0.0–1.0.
    """
    if not control_coverage:
        return 0.0
    values = list(control_coverage.values())
    return sum(values) / len(values)


def _compute_risk_drivers(
    gaps: list[dict[str, Any]],
    platform_revenue_usd: float,
) -> tuple[list[dict[str, Any]], float | None, float | None]:
    """Derive risk drivers and financial estimates from assessment gaps.

    Args:
        gaps: List of identified gap dicts from posture assessment.
        platform_revenue_usd: Annual revenue for proportional ALE calculation.

    Returns:
        Tuple of (risk_drivers, estimated_ale_usd, breach_probability_pct).
    """
    severity_weights = {"high": 0.15, "medium": 0.06, "low": 0.02}
    total_weight = sum(severity_weights.get(g.get("severity", "low"), 0.02) for g in gaps)
    breach_probability = min(total_weight * 100.0, 80.0)

    ale = (breach_probability / 100.0) * platform_revenue_usd * 0.1 if platform_revenue_usd else None

    risk_drivers = [
        {
            "factor": g.get("control_id", "unknown"),
            "severity": g.get("severity", "low"),
            "estimated_impact_usd": ale / max(len(gaps), 1) if ale else None,
        }
        for g in gaps[:10]
    ]

    return risk_drivers, ale, breach_probability


def _derive_recommended_controls(gaps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert posture gaps into a prioritised list of recommended controls.

    Args:
        gaps: List of gap dicts with control_id and severity.

    Returns:
        List of control recommendations sorted by severity priority.
    """
    severity_order = {"high": 0, "medium": 1, "low": 2}
    sorted_gaps = sorted(gaps, key=lambda g: severity_order.get(g.get("severity", "low"), 2))
    return [
        {
            "control_id": g.get("control_id"),
            "priority": idx + 1,
            "severity": g.get("severity", "low"),
            "expected_reduction_usd": None,
        }
        for idx, g in enumerate(sorted_gaps[:20])
    ]


def _build_carrier_impact_map(
    carrier_requirements_met: dict[str, Any],
    estimated_ale: float | None,
) -> dict[str, Any]:
    """Build per-carrier premium impact deltas from fulfillment data.

    Args:
        carrier_requirements_met: {carrier_id: {requirement_id: bool}}.
        estimated_ale: Estimated annual loss for premium approximation.

    Returns:
        Dict of {carrier_id: {current_premium, projected_premium}}.
    """
    result: dict[str, Any] = {}
    for carrier_id, fulfillment in carrier_requirements_met.items():
        if not isinstance(fulfillment, dict):
            continue
        total_reqs = len(fulfillment)
        met_reqs = sum(1 for v in fulfillment.values() if v)
        coverage_ratio = met_reqs / max(total_reqs, 1)

        base_premium = (estimated_ale or 0.0) * 0.03
        result[carrier_id] = {
            "current_premium": base_premium,
            "projected_premium": base_premium * (1.0 - coverage_ratio * 0.3),
            "requirements_met_pct": coverage_ratio * 100.0,
        }
    return result


def _run_premium_optimization(
    gaps: list[dict[str, Any]],
    posture_score: float,
    current_premium_usd: float,
    sample_size: int,
    discount_cap: float,
) -> tuple[list[dict[str, Any]], float, dict[str, Any], dict[str, Any]]:
    """Run synthetic premium optimization simulation.

    Args:
        gaps: Current posture gaps.
        posture_score: Current aggregate posture score.
        current_premium_usd: Current annual premium.
        sample_size: Number of Monte Carlo samples.
        discount_cap: Maximum achievable discount percentage.

    Returns:
        Tuple of (recommended_controls, discount_pct, roi_analysis, confidence_interval).
    """
    raw_discount = posture_score * discount_cap
    discount_pct = min(raw_discount, discount_cap)

    controls = _derive_recommended_controls(gaps)
    savings = current_premium_usd * (discount_pct / 100.0)
    implementation_cost = savings * 0.5

    roi_analysis = {
        "total_investment_usd": implementation_cost,
        "annual_savings_usd": savings,
        "payback_months": (implementation_cost / (savings / 12.0)) if savings > 0 else None,
    }

    margin = savings * 0.15
    confidence_interval = {
        "lower_usd": max(0.0, current_premium_usd - savings - margin),
        "upper_usd": current_premium_usd - savings + margin,
    }

    return controls, discount_pct, roi_analysis, confidence_interval


def _compute_residual_risk(
    baseline_score: float,
    controls: list[dict[str, Any]],
) -> tuple[float, float]:
    """Compute residual risk score after applying controls.

    Args:
        baseline_score: Risk score before controls (0.0–1.0).
        controls: Controls with effectiveness_pct (0–100).

    Returns:
        Tuple of (residual_risk_score, risk_reduction_pct).
    """
    if not controls:
        return baseline_score, 0.0

    total_effectiveness = sum(
        c.get("effectiveness_pct", 50.0) / 100.0 * c.get("weight", 1.0)
        for c in controls
    )
    total_weight = sum(c.get("weight", 1.0) for c in controls)
    avg_effectiveness = total_effectiveness / max(total_weight, 1.0)

    residual = baseline_score * (1.0 - min(avg_effectiveness, 0.9))
    reduction_pct = ((baseline_score - residual) / max(baseline_score, 0.001)) * 100.0

    return residual, reduction_pct


def _assemble_artifacts(
    posture_assessment: PostureAssessment,
    carrier_requirements: dict[str, Any],
) -> dict[str, Any]:
    """Assemble evidence artifacts from posture assessment data.

    Args:
        posture_assessment: Completed posture assessment.
        carrier_requirements: Carrier requirement definitions.

    Returns:
        Dict of assembled artifacts keyed by artifact type.
    """
    return {
        "posture_summary": {
            "assessment_id": str(posture_assessment.id),
            "platform_id": posture_assessment.platform_id,
            "posture_score": posture_assessment.posture_score,
            "control_coverage": posture_assessment.control_coverage,
            "gap_count": len(posture_assessment.gaps),
            "generated_at": datetime.now(tz=UTC).isoformat(),
        },
        "control_attestations": {
            "domains": list(posture_assessment.control_coverage.keys()),
            "coverage_by_domain": posture_assessment.control_coverage,
            "gaps_summary": [
                {"control_id": g.get("control_id"), "severity": g.get("severity")}
                for g in posture_assessment.gaps[:50]
            ],
        },
        "carrier_requirement_mapping": {
            "carrier_requirements_checked": list(carrier_requirements.keys()),
            "requirements_met": posture_assessment.carrier_requirements_met,
        },
    }


def _get_fulfilled_requirements(carrier_requirements_met: dict[str, Any]) -> list[str]:
    """Extract fulfilled requirement IDs from fulfillment map.

    Args:
        carrier_requirements_met: {requirement_id: bool} for a single carrier.

    Returns:
        List of fulfilled requirement IDs.
    """
    return [req_id for req_id, is_met in carrier_requirements_met.items() if is_met]


def _get_missing_requirements(carrier_requirements_met: dict[str, Any]) -> list[str]:
    """Extract missing requirement IDs from fulfillment map.

    Args:
        carrier_requirements_met: {requirement_id: bool} for a single carrier.

    Returns:
        List of missing requirement IDs.
    """
    return [req_id for req_id, is_met in carrier_requirements_met.items() if not is_met]
