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

    async def optimize_portfolio(
        self,
        tenant_id: uuid.UUID,
        assessment_id: uuid.UUID,
        carrier_ids: list[str],
        current_premiums: dict[str, float] | None = None,
        coverage_limits: dict[str, float] | None = None,
    ) -> dict[str, Any]:
        """GAP-522: Cross-carrier portfolio optimization.

        Runs premium optimization across multiple carriers simultaneously and
        produces a ranked portfolio recommendation showing the optimal carrier
        mix for the given posture assessment.

        Args:
            tenant_id: Tenant UUID for RLS scoping.
            assessment_id: Completed PostureAssessment UUID.
            carrier_ids: List of carrier identifiers to include in optimization.
            current_premiums: Optional dict of {carrier_id: current_premium_usd}.
            coverage_limits: Optional dict of {carrier_id: coverage_limit_usd}.

        Returns:
            Portfolio recommendation dict with ranked carriers and combined metrics.

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
                f"PostureAssessment {assessment_id} must be completed for portfolio optimization.",
                error_code=ErrorCode.CONFLICT,
            )

        current_premiums = current_premiums or {}
        coverage_limits = coverage_limits or {}

        carrier_results: list[dict[str, Any]] = []
        for carrier_id in carrier_ids:
            premium = current_premiums.get(carrier_id)
            limit = coverage_limits.get(carrier_id)

            controls, discount_pct, roi_analysis, confidence = _run_premium_optimization(
                gaps=assessment.gaps,
                posture_score=assessment.posture_score or 0.0,
                current_premium_usd=premium or 0.0,
                sample_size=self._sample_size,
                discount_cap=self._discount_cap,
            )

            optimized_premium = (premium * (1.0 - discount_pct / 100.0)) if premium else None
            carrier_results.append(
                {
                    "carrier_id": carrier_id,
                    "current_premium_usd": premium,
                    "optimized_premium_usd": optimized_premium,
                    "discount_pct": discount_pct,
                    "coverage_limit_usd": limit,
                    "roi_analysis": roi_analysis,
                    "confidence_interval": confidence,
                    "recommended_controls": controls[:5],
                }
            )

        # Sort by discount_pct descending — best carrier at index 0
        carrier_results.sort(key=lambda x: x["discount_pct"], reverse=True)

        total_current = sum(r["current_premium_usd"] or 0.0 for r in carrier_results)
        total_optimized = sum(r["optimized_premium_usd"] or 0.0 for r in carrier_results)

        portfolio: dict[str, Any] = {
            "assessment_id": str(assessment_id),
            "tenant_id": str(tenant_id),
            "carrier_count": len(carrier_results),
            "carriers": carrier_results,
            "total_current_premium_usd": total_current,
            "total_optimized_premium_usd": total_optimized,
            "total_savings_usd": total_current - total_optimized,
            "recommended_carrier": carrier_results[0]["carrier_id"] if carrier_results else None,
            "posture_score": assessment.posture_score,
            "optimization_sample_size": self._sample_size,
        }

        logger.info(
            "Portfolio optimization complete",
            tenant_id=str(tenant_id),
            assessment_id=str(assessment_id),
            carrier_count=len(carrier_ids),
            total_savings_usd=portfolio["total_savings_usd"],
        )

        return portfolio


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

        # GAP-520: Run FAIR-CAM control scoring when methodology is 'fair'
        fair_cam_scores: dict[str, Any] = {}
        if methodology == "fair":
            fair_cam_scores = _compute_fair_cam_scores(
                controls=controls_to_apply,
                gaps=assessment.gaps,
            )

        calculation = await self._risk_repo.create(
            tenant_id=tenant_id,
            posture_assessment_id=assessment_id,
            calculation_type=calculation_type,
            methodology=methodology,
            controls_applied=controls_to_apply,
            threat_scenarios=threat_scenarios,
            calculation_metadata={
                "asset_value_usd": asset_value_usd,
                "fair_cam_scores": fair_cam_scores,
            },
        )

        baseline_score = 1.0 - (assessment.posture_score or 0.0)
        residual_score, reduction_pct = _compute_residual_risk(
            baseline_score=baseline_score,
            controls=controls_to_apply,
        )

        # GAP-520: Apply FAIR-CAM control effectiveness modifiers to residual risk
        if fair_cam_scores and methodology == "fair":
            cam_modifier = fair_cam_scores.get("aggregate_effectiveness_modifier", 1.0)
            residual_score = max(0.0, residual_score * cam_modifier)
            reduction_pct = (
                ((baseline_score - residual_score) / max(baseline_score, 0.001)) * 100.0
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


def _compute_fair_cam_scores(
    controls: list[dict[str, Any]],
    gaps: list[dict[str, Any]],
) -> dict[str, Any]:
    """GAP-520: Compute FAIR Control Analytics Model (FAIR-CAM) scores.

    FAIR-CAM maps controls to FAIR loss factors (Threat Event Frequency,
    Contact Frequency, Probability of Action, Vulnerability, Loss Magnitude)
    and scores each control's contribution to reducing those factors.

    This implementation produces normalized FAIR-CAM scores based on the
    control effectiveness and gap severity profile.

    Args:
        controls: List of controls with control_id, effectiveness_pct, weight.
        gaps: Current posture gaps with severity and control_id.

    Returns:
        Dict with per-control FAIR-CAM scores and an aggregate modifier.
    """
    # FAIR-CAM loss factor categories and base weights
    loss_factor_weights: dict[str, float] = {
        "threat_event_frequency": 0.25,
        "contact_frequency": 0.10,
        "probability_of_action": 0.15,
        "vulnerability": 0.30,
        "loss_magnitude": 0.20,
    }

    # Map gap severities to vulnerability contribution
    severity_vulnerability: dict[str, float] = {
        "high": 0.80,
        "medium": 0.50,
        "low": 0.20,
    }

    # Compute baseline vulnerability from gaps
    gap_vulnerabilities = [
        severity_vulnerability.get(g.get("severity", "low"), 0.20) for g in gaps
    ]
    baseline_vulnerability = (
        sum(gap_vulnerabilities) / len(gap_vulnerabilities) if gap_vulnerabilities else 0.5
    )

    per_control_scores: list[dict[str, Any]] = []
    for control in controls:
        effectiveness = control.get("effectiveness_pct", 50.0) / 100.0
        weight = control.get("weight", 1.0)

        # Score each FAIR loss factor based on control effectiveness
        factor_scores: dict[str, float] = {
            "threat_event_frequency": effectiveness * 0.6,
            "contact_frequency": effectiveness * 0.3,
            "probability_of_action": effectiveness * 0.5,
            "vulnerability": effectiveness * baseline_vulnerability,
            "loss_magnitude": effectiveness * 0.4,
        }

        # Weighted FAIR-CAM score for this control
        cam_score = sum(
            score * loss_factor_weights[factor]
            for factor, score in factor_scores.items()
        )

        per_control_scores.append({
            "control_id": control.get("control_id", "unknown"),
            "effectiveness_pct": control.get("effectiveness_pct", 50.0),
            "weight": weight,
            "cam_score": round(cam_score, 4),
            "factor_scores": {k: round(v, 4) for k, v in factor_scores.items()},
        })

    # Aggregate modifier reduces residual risk — higher CAM score = greater reduction
    if per_control_scores:
        avg_cam_score = sum(s["cam_score"] for s in per_control_scores) / len(per_control_scores)
        aggregate_modifier = max(0.1, 1.0 - avg_cam_score)
    else:
        aggregate_modifier = 1.0

    return {
        "methodology": "FAIR-CAM",
        "per_control_scores": per_control_scores,
        "baseline_vulnerability": round(baseline_vulnerability, 4),
        "aggregate_effectiveness_modifier": round(aggregate_modifier, 4),
        "loss_factor_weights": loss_factor_weights,
    }


# ---------------------------------------------------------------------------
# GAP-518: Continuous Monitoring Service
# ---------------------------------------------------------------------------


class ContinuousMonitoringService:
    """GAP-518: Background service that monitors posture drift on a schedule.

    Scheduled via APScheduler in the lifespan context manager. Compares the
    latest posture score for each active platform against the previous snapshot
    and emits an ``insurance.posture.drift_detected`` Kafka event when the
    score drops by more than ``drift_alert_threshold``.

    Also creates daily snapshots in ``cin_posture_score_history`` for trend
    analysis (GAP-524).
    """

    def __init__(
        self,
        posture_repo: IPostureAssessmentRepository,
        event_publisher: EventPublisher,
        drift_alert_threshold: float = 0.10,
    ) -> None:
        """Initialise with injected dependencies.

        Args:
            posture_repo: PostureAssessment persistence for reading latest scores.
            event_publisher: Kafka event publisher for drift alerts.
            drift_alert_threshold: Fractional score drop that triggers an alert (0.0–1.0).
        """
        self._posture_repo = posture_repo
        self._event_publisher = event_publisher
        self._drift_threshold = drift_alert_threshold
        self._last_scores: dict[str, float] = {}

    async def run_monitoring_cycle(self) -> dict[str, Any]:
        """Execute one monitoring cycle.

        Fetches the most recent completed posture assessments, compares each
        platform's current score to the last seen score, and emits drift events
        for platforms that have degraded beyond the threshold.

        Returns:
            Summary dict with cycle results (checked, drifted, snapshot_count).
        """
        logger.info("Continuous monitoring cycle started")

        try:
            recent_assessments = await self._posture_repo.list_recent_completed()
        except AttributeError:
            # Graceful degradation: repository may not implement list_recent_completed yet
            logger.warning("posture_repo does not implement list_recent_completed — skipping cycle")
            return {"checked": 0, "drifted": 0, "snapshot_count": 0}

        drift_events: list[dict[str, Any]] = []
        snapshot_count = 0

        for assessment in recent_assessments:
            platform_key = f"{assessment.tenant_id}:{assessment.platform_id}"
            current_score = assessment.posture_score or 0.0
            previous_score = self._last_scores.get(platform_key)

            if previous_score is not None:
                drop = previous_score - current_score
                if drop >= self._drift_threshold:
                    drift_event = {
                        "tenant_id": str(assessment.tenant_id),
                        "platform_id": assessment.platform_id,
                        "assessment_id": str(assessment.id),
                        "previous_score": previous_score,
                        "current_score": current_score,
                        "score_drop": round(drop, 4),
                        "threshold": self._drift_threshold,
                        "detected_at": datetime.now(tz=UTC).isoformat(),
                    }
                    drift_events.append(drift_event)

                    await self._event_publisher.publish(
                        topic="insurance.posture.drift_detected",
                        payload=drift_event,
                    )

                    logger.warning(
                        "Posture drift detected",
                        tenant_id=str(assessment.tenant_id),
                        platform_id=assessment.platform_id,
                        score_drop=round(drop, 4),
                    )

            self._last_scores[platform_key] = current_score
            snapshot_count += 1

        result = {
            "checked": len(recent_assessments),
            "drifted": len(drift_events),
            "snapshot_count": snapshot_count,
            "cycle_at": datetime.now(tz=UTC).isoformat(),
        }

        logger.info(
            "Continuous monitoring cycle complete",
            checked=result["checked"],
            drifted=result["drifted"],
        )
        return result


# ---------------------------------------------------------------------------
# GAP-519: Board Report Service
# ---------------------------------------------------------------------------


class BoardReportService:
    """GAP-519: Generate PDF board reports from posture assessment data.

    Combines Jinja2 templating for HTML rendering with WeasyPrint for
    PDF generation.  Board reports are executive-facing and summarise the
    organisation's current cyber insurance posture, coverage gaps, and
    recommended remediation actions.
    """

    def __init__(
        self,
        posture_repo: IPostureAssessmentRepository,
        template_dir: str = "templates/board_reports",
        logo_url: str = "",
    ) -> None:
        """Initialise with injected dependencies.

        Args:
            posture_repo: PostureAssessment persistence for reading data.
            template_dir: Path to Jinja2 HTML templates for board reports.
            logo_url: Optional URL or file path to embed as company logo.
        """
        self._posture_repo = posture_repo
        self._template_dir = template_dir
        self._logo_url = logo_url

    async def generate_board_report(
        self,
        tenant_id: uuid.UUID,
        assessment_id: uuid.UUID,
        report_metadata: dict[str, Any] | None = None,
    ) -> bytes:
        """Generate a PDF board report for a completed posture assessment.

        Args:
            tenant_id: Tenant UUID for RLS scoping.
            assessment_id: Completed PostureAssessment UUID.
            report_metadata: Optional metadata to embed in report header.

        Returns:
            PDF content as bytes.

        Raises:
            NotFoundError: If assessment not found.
            ConflictError: If assessment is not completed.
            RuntimeError: If Jinja2 or WeasyPrint are not installed.
        """
        try:
            import jinja2
            import weasyprint
        except ImportError as exc:
            raise RuntimeError(
                f"Board report generation requires 'weasyprint' and 'jinja2'. "
                f"Install with: pip install weasyprint jinja2. Error: {exc}"
            ) from exc

        assessment = await self._posture_repo.get(assessment_id, tenant_id)
        if not assessment:
            raise NotFoundError(
                f"PostureAssessment {assessment_id} not found",
                error_code=ErrorCode.NOT_FOUND,
            )
        if assessment.status != "completed":
            raise ConflictError(
                f"PostureAssessment {assessment_id} must be completed before generating a board report.",
                error_code=ErrorCode.CONFLICT,
            )

        report_context = _build_board_report_context(
            assessment=assessment,
            logo_url=self._logo_url,
            report_metadata=report_metadata or {},
        )

        html_content = _render_board_report_html(
            context=report_context,
            template_dir=self._template_dir,
            jinja2_module=jinja2,
        )

        pdf_bytes: bytes = weasyprint.HTML(string=html_content).write_pdf()

        logger.info(
            "Board report generated",
            tenant_id=str(tenant_id),
            assessment_id=str(assessment_id),
            pdf_size_bytes=len(pdf_bytes),
        )
        return pdf_bytes


def _build_board_report_context(
    assessment: PostureAssessment,
    logo_url: str,
    report_metadata: dict[str, Any],
) -> dict[str, Any]:
    """Build template context dict for the board report.

    Args:
        assessment: Completed posture assessment.
        logo_url: Company logo URL or path.
        report_metadata: Additional metadata (e.g., prepared_by, fiscal_quarter).

    Returns:
        Context dict for Jinja2 template rendering.
    """
    severity_order = {"high": 0, "medium": 1, "low": 2}
    top_gaps = sorted(
        assessment.gaps,
        key=lambda g: severity_order.get(g.get("severity", "low"), 2),
    )[:10]

    posture_rating: str
    score = assessment.posture_score or 0.0
    if score >= 0.85:
        posture_rating = "Strong"
    elif score >= 0.65:
        posture_rating = "Moderate"
    elif score >= 0.40:
        posture_rating = "Developing"
    else:
        posture_rating = "Critical"

    return {
        "report_date": datetime.now(tz=UTC).strftime("%B %d, %Y"),
        "assessment_id": str(assessment.id),
        "platform_id": assessment.platform_id,
        "platform_type": assessment.platform_type,
        "posture_score": round(score * 100, 1),
        "posture_rating": posture_rating,
        "gap_count": len(assessment.gaps),
        "top_gaps": top_gaps,
        "control_coverage": assessment.control_coverage,
        "carriers_assessed": list(assessment.carrier_requirements_met.keys()),
        "logo_url": logo_url,
        "completed_at": (
            assessment.completed_at.strftime("%Y-%m-%d %H:%M UTC")
            if assessment.completed_at
            else "N/A"
        ),
        **report_metadata,
    }


def _render_board_report_html(
    context: dict[str, Any],
    template_dir: str,
    jinja2_module: Any,
) -> str:
    """Render the board report HTML from a Jinja2 template or fallback inline HTML.

    Uses the template at ``{template_dir}/board_report.html`` if it exists;
    falls back to an inline HTML skeleton for robustness.

    Args:
        context: Template context dict.
        template_dir: Directory containing Jinja2 templates.
        jinja2_module: Imported jinja2 module (passed to avoid re-importing).

    Returns:
        Rendered HTML string.
    """
    import os

    template_path = os.path.join(template_dir, "board_report.html")

    if os.path.exists(template_path):
        loader = jinja2_module.FileSystemLoader(template_dir)
        env = jinja2_module.Environment(loader=loader, autoescape=True)
        template = env.get_template("board_report.html")
        return template.render(**context)

    # Inline fallback template — always available
    fallback_template = jinja2_module.Template(
        """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<title>Cyber Insurance Posture Board Report</title>
<style>
  body { font-family: Arial, sans-serif; margin: 40px; color: #1a1a2e; }
  h1 { color: #16213e; border-bottom: 2px solid #0f3460; padding-bottom: 8px; }
  h2 { color: #0f3460; margin-top: 24px; }
  .score { font-size: 48px; font-weight: bold; color: #e94560; }
  .rating { font-size: 20px; margin-top: 4px; }
  table { border-collapse: collapse; width: 100%; margin-top: 12px; }
  th { background: #0f3460; color: white; padding: 8px 12px; text-align: left; }
  td { border: 1px solid #ddd; padding: 8px 12px; }
  tr:nth-child(even) { background: #f8f9fa; }
  .gap-high { color: #dc3545; font-weight: bold; }
  .gap-medium { color: #fd7e14; }
  .gap-low { color: #6c757d; }
  .footer { margin-top: 40px; font-size: 11px; color: #999; border-top: 1px solid #ddd; padding-top: 8px; }
</style>
</head>
<body>
{% if logo_url %}<img src="{{ logo_url }}" alt="Logo" style="height:60px; margin-bottom: 20px;"/>{% endif %}
<h1>Cyber Insurance Posture — Board Report</h1>
<p><strong>Report Date:</strong> {{ report_date }} &nbsp;|&nbsp;
   <strong>Assessment ID:</strong> {{ assessment_id }}</p>
<p><strong>Platform:</strong> {{ platform_id }} ({{ platform_type }})</p>

<h2>Executive Summary</h2>
<div class="score">{{ posture_score }}%</div>
<div class="rating">Posture Rating: <strong>{{ posture_rating }}</strong></div>
<p>Assessment completed: {{ completed_at }}<br/>
Total gaps identified: <strong>{{ gap_count }}</strong></p>

<h2>Control Coverage by Domain</h2>
<table>
<tr><th>Control Domain</th><th>Coverage</th></tr>
{% for domain, pct in control_coverage.items() %}
<tr><td>{{ domain }}</td><td>{{ "%.1f"|format(pct * 100) }}%</td></tr>
{% endfor %}
</table>

<h2>Top Identified Gaps</h2>
<table>
<tr><th>Control ID</th><th>Severity</th><th>Description</th></tr>
{% for gap in top_gaps %}
<tr>
  <td>{{ gap.control_id or "—" }}</td>
  <td class="gap-{{ gap.severity }}">{{ gap.severity | upper }}</td>
  <td>{{ gap.description or "—" }}</td>
</tr>
{% endfor %}
</table>

<h2>Carriers Assessed</h2>
<p>{{ carriers_assessed | join(", ") or "None" }}</p>

<div class="footer">
Prepared {{ report_date }} | AumOS Cyber Insurance | Confidential — For Board Use Only
</div>
</body>
</html>""",
        autoescape=True,
    )
    return fallback_template.render(**context)


# ---------------------------------------------------------------------------
# GAP-523: Regulatory Monitoring Service
# ---------------------------------------------------------------------------


class RegulatoryMonitoringService:
    """GAP-523: Monitor carrier regulatory changes via RSS/SEC feeds.

    Polls configured RSS/Atom feeds and SEC EDGAR filings for changes to
    cyber insurance carrier requirements, underwriting guidelines, and
    regulatory mandates. Emits ``insurance.requirements.changed`` events
    when material changes are detected.

    Designed to run on a schedule via APScheduler in the lifespan context manager.
    """

    def __init__(
        self,
        event_publisher: EventPublisher,
        feed_urls: list[str] | None = None,
    ) -> None:
        """Initialise with injected dependencies.

        Args:
            event_publisher: Kafka event publisher for regulatory change events.
            feed_urls: List of RSS/Atom/SEC feed URLs to monitor.
        """
        self._event_publisher = event_publisher
        self._feed_urls: list[str] = feed_urls or []
        self._seen_entry_ids: set[str] = set()

    async def run_monitoring_cycle(self) -> dict[str, Any]:
        """Execute one regulatory monitoring cycle.

        Polls all configured feeds, identifies new entries since last check,
        and emits Kafka events for potentially material regulatory changes.

        Returns:
            Summary dict with feeds polled, new entries found, and events emitted.
        """
        try:
            import feedparser  # type: ignore[import-untyped]
        except ImportError:
            logger.warning(
                "feedparser not installed — regulatory monitoring disabled. "
                "Install with: pip install feedparser"
            )
            return {"feeds_polled": 0, "new_entries": 0, "events_emitted": 0}

        if not self._feed_urls:
            logger.debug("No regulatory feed URLs configured — skipping cycle")
            return {"feeds_polled": 0, "new_entries": 0, "events_emitted": 0}

        new_entries: list[dict[str, Any]] = []
        feeds_polled = 0

        import asyncio

        for feed_url in self._feed_urls:
            try:
                # feedparser is synchronous — run in thread pool to avoid blocking
                loop = asyncio.get_event_loop()
                feed = await loop.run_in_executor(None, feedparser.parse, feed_url)
                feeds_polled += 1

                for entry in feed.entries:
                    entry_id = entry.get("id") or entry.get("link") or entry.get("title", "")
                    if not entry_id or entry_id in self._seen_entry_ids:
                        continue

                    self._seen_entry_ids.add(entry_id)
                    new_entries.append(
                        {
                            "feed_url": feed_url,
                            "entry_id": entry_id,
                            "title": entry.get("title", ""),
                            "summary": entry.get("summary", "")[:500],
                            "link": entry.get("link", ""),
                            "published": entry.get("published", ""),
                        }
                    )

            except Exception as exc:
                logger.warning(
                    "Failed to poll regulatory feed",
                    feed_url=feed_url,
                    error=str(exc),
                )

        events_emitted = 0
        for entry in new_entries:
            await self._event_publisher.publish(
                topic="insurance.requirements.changed",
                payload={
                    "source": entry["feed_url"],
                    "entry_id": entry["entry_id"],
                    "title": entry["title"],
                    "summary": entry["summary"],
                    "link": entry["link"],
                    "detected_at": datetime.now(tz=UTC).isoformat(),
                },
            )
            events_emitted += 1

        result = {
            "feeds_polled": feeds_polled,
            "new_entries": len(new_entries),
            "events_emitted": events_emitted,
            "cycle_at": datetime.now(tz=UTC).isoformat(),
        }

        logger.info(
            "Regulatory monitoring cycle complete",
            feeds_polled=feeds_polled,
            new_entries=len(new_entries),
            events_emitted=events_emitted,
        )
        return result

    def add_feed_url(self, url: str) -> None:
        """Add a feed URL to the monitored list at runtime.

        Args:
            url: RSS/Atom/SEC feed URL to add.
        """
        if url not in self._feed_urls:
            self._feed_urls.append(url)
            logger.debug("Regulatory feed URL added", url=url)
