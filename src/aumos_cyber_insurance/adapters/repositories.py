"""SQLAlchemy repository implementations for the Cyber Insurance service.

All repositories extend BaseRepository from aumos-common and implement the
Protocol interfaces defined in core/interfaces.py.
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from aumos_common.database import BaseRepository
from aumos_common.observability import get_logger

from aumos_cyber_insurance.core.models import (
    EvidencePackage,
    ImpactAnalysis,
    PostureAssessment,
    PremiumRecommendation,
    RiskCalculation,
)

logger = get_logger(__name__)


class PostureAssessmentRepository(BaseRepository[PostureAssessment]):
    """Persistence for PostureAssessment entities.

    Extends BaseRepository which provides RLS-enforced CRUD and pagination.
    """

    def __init__(self, session: AsyncSession) -> None:
        """Initialise with an async SQLAlchemy session.

        Args:
            session: AsyncSession with RLS context already set.
        """
        super().__init__(session, PostureAssessment)

    async def create(
        self,
        tenant_id: uuid.UUID,
        platform_id: str,
        platform_type: str,
        carrier_id: str | None,
        requested_by: uuid.UUID | None,
        assessment_metadata: dict[str, Any],
    ) -> PostureAssessment:
        """Create and persist a new PostureAssessment.

        Args:
            tenant_id: Tenant UUID for RLS scoping.
            platform_id: Platform identifier.
            platform_type: Platform category.
            carrier_id: Optional target carrier ID.
            requested_by: User ID that triggered the assessment.
            assessment_metadata: Optional metadata dict.

        Returns:
            Newly created PostureAssessment in pending status.
        """
        assessment = PostureAssessment(
            tenant_id=tenant_id,
            platform_id=platform_id,
            platform_type=platform_type,
            carrier_id=carrier_id,
            status="pending",
            control_coverage={},
            gaps=[],
            carrier_requirements_met={},
            assessment_metadata=assessment_metadata,
            requested_by=requested_by,
        )
        self._session.add(assessment)
        await self._session.flush()
        await self._session.refresh(assessment)
        logger.debug("PostureAssessment created", assessment_id=str(assessment.id))
        return assessment

    async def get(self, assessment_id: uuid.UUID, tenant_id: uuid.UUID) -> PostureAssessment | None:
        """Retrieve a PostureAssessment by ID within a tenant.

        Args:
            assessment_id: Assessment UUID.
            tenant_id: Tenant UUID for RLS scoping.

        Returns:
            PostureAssessment or None if not found.
        """
        result = await self._session.execute(
            select(PostureAssessment).where(
                PostureAssessment.id == assessment_id,
                PostureAssessment.tenant_id == tenant_id,
            )
        )
        return result.scalar_one_or_none()

    async def list_by_tenant(
        self,
        tenant_id: uuid.UUID,
        page: int,
        page_size: int,
        status: str | None,
        platform_id: str | None,
    ) -> tuple[list[PostureAssessment], int]:
        """List assessments for a tenant with optional filters.

        Args:
            tenant_id: Tenant UUID.
            page: 1-based page number.
            page_size: Results per page.
            status: Optional status filter.
            platform_id: Optional platform filter.

        Returns:
            Tuple of (assessments, total_count).
        """
        query = select(PostureAssessment).where(PostureAssessment.tenant_id == tenant_id)
        if status:
            query = query.where(PostureAssessment.status == status)
        if platform_id:
            query = query.where(PostureAssessment.platform_id == platform_id)

        return await self.paginate(query, page, page_size)

    async def update_status(
        self,
        assessment_id: uuid.UUID,
        status: str,
        posture_score: float | None,
        control_coverage: dict[str, Any],
        gaps: list[dict[str, Any]],
        carrier_requirements_met: dict[str, Any],
        error_message: str | None,
    ) -> PostureAssessment:
        """Update assessment status and computed results.

        Args:
            assessment_id: Assessment UUID.
            status: New status value.
            posture_score: Computed aggregate score.
            control_coverage: Per-domain coverage map.
            gaps: Identified gap list.
            carrier_requirements_met: Per-carrier fulfillment map.
            error_message: Error detail if failed.

        Returns:
            Updated PostureAssessment.
        """
        completed_at = datetime.now(tz=UTC) if status in {"completed", "failed"} else None

        await self._session.execute(
            update(PostureAssessment)
            .where(PostureAssessment.id == assessment_id)
            .values(
                status=status,
                posture_score=posture_score,
                control_coverage=control_coverage,
                gaps=gaps,
                carrier_requirements_met=carrier_requirements_met,
                error_message=error_message,
                completed_at=completed_at,
            )
        )
        await self._session.flush()

        result = await self._session.execute(
            select(PostureAssessment).where(PostureAssessment.id == assessment_id)
        )
        return result.scalar_one()


class ImpactAnalysisRepository(BaseRepository[ImpactAnalysis]):
    """Persistence for ImpactAnalysis entities."""

    def __init__(self, session: AsyncSession) -> None:
        """Initialise with an async SQLAlchemy session.

        Args:
            session: AsyncSession with RLS context already set.
        """
        super().__init__(session, ImpactAnalysis)

    async def create(
        self,
        tenant_id: uuid.UUID,
        posture_assessment_id: uuid.UUID,
        platform_id: str,
        platform_type: str,
        analysis_metadata: dict[str, Any],
    ) -> ImpactAnalysis:
        """Create and persist a new ImpactAnalysis.

        Args:
            tenant_id: Tenant UUID.
            posture_assessment_id: Parent assessment UUID.
            platform_id: Platform being analysed.
            platform_type: Platform category.
            analysis_metadata: Context metadata.

        Returns:
            Newly created ImpactAnalysis.
        """
        analysis = ImpactAnalysis(
            tenant_id=tenant_id,
            posture_assessment_id=posture_assessment_id,
            platform_id=platform_id,
            platform_type=platform_type,
            risk_drivers=[],
            recommended_controls=[],
            carrier_impact_map={},
            analysis_metadata=analysis_metadata,
        )
        self._session.add(analysis)
        await self._session.flush()
        await self._session.refresh(analysis)
        return analysis

    async def get(self, analysis_id: uuid.UUID, tenant_id: uuid.UUID) -> ImpactAnalysis | None:
        """Retrieve an ImpactAnalysis by ID within a tenant.

        Args:
            analysis_id: Analysis UUID.
            tenant_id: Tenant UUID.

        Returns:
            ImpactAnalysis or None if not found.
        """
        result = await self._session.execute(
            select(ImpactAnalysis).where(
                ImpactAnalysis.id == analysis_id,
                ImpactAnalysis.tenant_id == tenant_id,
            )
        )
        return result.scalar_one_or_none()

    async def list_by_assessment(
        self,
        posture_assessment_id: uuid.UUID,
        tenant_id: uuid.UUID,
    ) -> list[ImpactAnalysis]:
        """List all analyses for a posture assessment.

        Args:
            posture_assessment_id: Parent assessment UUID.
            tenant_id: Tenant UUID.

        Returns:
            List of ImpactAnalysis records.
        """
        result = await self._session.execute(
            select(ImpactAnalysis).where(
                ImpactAnalysis.posture_assessment_id == posture_assessment_id,
                ImpactAnalysis.tenant_id == tenant_id,
            )
        )
        return list(result.scalars().all())

    async def update_results(
        self,
        analysis_id: uuid.UUID,
        estimated_annual_loss: float | None,
        breach_probability_pct: float | None,
        coverage_gap_usd: float | None,
        risk_drivers: list[dict[str, Any]],
        recommended_controls: list[dict[str, Any]],
        carrier_impact_map: dict[str, Any],
    ) -> ImpactAnalysis:
        """Update analysis with computed financial results.

        Args:
            analysis_id: Analysis UUID.
            estimated_annual_loss: Computed ALE in USD.
            breach_probability_pct: Breach probability 0–100.
            coverage_gap_usd: Coverage gap in USD.
            risk_drivers: Top risk drivers list.
            recommended_controls: Prioritised controls list.
            carrier_impact_map: Per-carrier premium delta map.

        Returns:
            Updated ImpactAnalysis.
        """
        await self._session.execute(
            update(ImpactAnalysis)
            .where(ImpactAnalysis.id == analysis_id)
            .values(
                estimated_annual_loss=estimated_annual_loss,
                breach_probability_pct=breach_probability_pct,
                coverage_gap_usd=coverage_gap_usd,
                risk_drivers=risk_drivers,
                recommended_controls=recommended_controls,
                carrier_impact_map=carrier_impact_map,
            )
        )
        await self._session.flush()

        result = await self._session.execute(
            select(ImpactAnalysis).where(ImpactAnalysis.id == analysis_id)
        )
        return result.scalar_one()


class PremiumRecommendationRepository(BaseRepository[PremiumRecommendation]):
    """Persistence for PremiumRecommendation entities."""

    def __init__(self, session: AsyncSession) -> None:
        """Initialise with an async SQLAlchemy session.

        Args:
            session: AsyncSession with RLS context already set.
        """
        super().__init__(session, PremiumRecommendation)

    async def create(
        self,
        tenant_id: uuid.UUID,
        posture_assessment_id: uuid.UUID,
        carrier_id: str,
        simulation_runs: int,
        recommendation_metadata: dict[str, Any],
    ) -> PremiumRecommendation:
        """Create and persist a new PremiumRecommendation.

        Args:
            tenant_id: Tenant UUID.
            posture_assessment_id: Parent assessment UUID.
            carrier_id: Target carrier.
            simulation_runs: Number of Monte Carlo samples.
            recommendation_metadata: Context metadata.

        Returns:
            Newly created PremiumRecommendation.
        """
        recommendation = PremiumRecommendation(
            tenant_id=tenant_id,
            posture_assessment_id=posture_assessment_id,
            carrier_id=carrier_id,
            simulation_runs=simulation_runs,
            recommended_controls=[],
            roi_analysis={},
            confidence_interval={},
            recommendation_metadata=recommendation_metadata,
        )
        self._session.add(recommendation)
        await self._session.flush()
        await self._session.refresh(recommendation)
        return recommendation

    async def get(self, recommendation_id: uuid.UUID, tenant_id: uuid.UUID) -> PremiumRecommendation | None:
        """Retrieve a PremiumRecommendation by ID within a tenant.

        Args:
            recommendation_id: Recommendation UUID.
            tenant_id: Tenant UUID.

        Returns:
            PremiumRecommendation or None.
        """
        result = await self._session.execute(
            select(PremiumRecommendation).where(
                PremiumRecommendation.id == recommendation_id,
                PremiumRecommendation.tenant_id == tenant_id,
            )
        )
        return result.scalar_one_or_none()

    async def list_by_assessment(
        self,
        posture_assessment_id: uuid.UUID,
        tenant_id: uuid.UUID,
    ) -> list[PremiumRecommendation]:
        """List all recommendations for a posture assessment.

        Args:
            posture_assessment_id: Parent assessment UUID.
            tenant_id: Tenant UUID.

        Returns:
            List of PremiumRecommendation records.
        """
        result = await self._session.execute(
            select(PremiumRecommendation).where(
                PremiumRecommendation.posture_assessment_id == posture_assessment_id,
                PremiumRecommendation.tenant_id == tenant_id,
            )
        )
        return list(result.scalars().all())

    async def update_results(
        self,
        recommendation_id: uuid.UUID,
        current_estimated_premium_usd: float | None,
        optimized_premium_usd: float | None,
        discount_pct: float | None,
        recommended_controls: list[dict[str, Any]],
        roi_analysis: dict[str, Any],
        confidence_interval: dict[str, Any],
    ) -> PremiumRecommendation:
        """Update recommendation with optimization results.

        Args:
            recommendation_id: Recommendation UUID.
            current_estimated_premium_usd: Current premium.
            optimized_premium_usd: Projected premium after controls.
            discount_pct: Projected discount percentage.
            recommended_controls: Priority-ordered control list.
            roi_analysis: ROI breakdown dict.
            confidence_interval: 95% CI dict.

        Returns:
            Updated PremiumRecommendation.
        """
        await self._session.execute(
            update(PremiumRecommendation)
            .where(PremiumRecommendation.id == recommendation_id)
            .values(
                current_estimated_premium_usd=current_estimated_premium_usd,
                optimized_premium_usd=optimized_premium_usd,
                discount_pct=discount_pct,
                recommended_controls=recommended_controls,
                roi_analysis=roi_analysis,
                confidence_interval=confidence_interval,
            )
        )
        await self._session.flush()

        result = await self._session.execute(
            select(PremiumRecommendation).where(PremiumRecommendation.id == recommendation_id)
        )
        return result.scalar_one()


class EvidencePackageRepository(BaseRepository[EvidencePackage]):
    """Persistence for EvidencePackage entities."""

    def __init__(self, session: AsyncSession, evidence_expiry_days: int = 90) -> None:
        """Initialise with an async SQLAlchemy session.

        Args:
            session: AsyncSession with RLS context already set.
            evidence_expiry_days: Days before package expires.
        """
        super().__init__(session, EvidencePackage)
        self._expiry_days = evidence_expiry_days

    async def create(
        self,
        tenant_id: uuid.UUID,
        posture_assessment_id: uuid.UUID,
        carrier_id: str,
        carrier_name: str,
        package_metadata: dict[str, Any],
    ) -> EvidencePackage:
        """Create and persist a new EvidencePackage in pending status.

        Args:
            tenant_id: Tenant UUID.
            posture_assessment_id: Parent assessment UUID.
            carrier_id: Target carrier.
            carrier_name: Human-readable carrier name.
            package_metadata: Optional metadata.

        Returns:
            Newly created EvidencePackage.
        """
        package = EvidencePackage(
            tenant_id=tenant_id,
            posture_assessment_id=posture_assessment_id,
            carrier_id=carrier_id,
            carrier_name=carrier_name,
            status="pending",
            artifacts={},
            carrier_requirements_fulfilled=[],
            carrier_requirements_missing=[],
            package_metadata=package_metadata,
        )
        self._session.add(package)
        await self._session.flush()
        await self._session.refresh(package)
        return package

    async def get(self, package_id: uuid.UUID, tenant_id: uuid.UUID) -> EvidencePackage | None:
        """Retrieve an EvidencePackage by ID within a tenant.

        Args:
            package_id: Package UUID.
            tenant_id: Tenant UUID.

        Returns:
            EvidencePackage or None.
        """
        result = await self._session.execute(
            select(EvidencePackage).where(
                EvidencePackage.id == package_id,
                EvidencePackage.tenant_id == tenant_id,
            )
        )
        return result.scalar_one_or_none()

    async def list_by_assessment(
        self,
        posture_assessment_id: uuid.UUID,
        tenant_id: uuid.UUID,
    ) -> list[EvidencePackage]:
        """List all evidence packages for a posture assessment.

        Args:
            posture_assessment_id: Parent assessment UUID.
            tenant_id: Tenant UUID.

        Returns:
            List of EvidencePackage records.
        """
        result = await self._session.execute(
            select(EvidencePackage).where(
                EvidencePackage.posture_assessment_id == posture_assessment_id,
                EvidencePackage.tenant_id == tenant_id,
            )
        )
        return list(result.scalars().all())

    async def update_status(
        self,
        package_id: uuid.UUID,
        status: str,
        artifacts: dict[str, Any],
        carrier_requirements_fulfilled: list[str],
        carrier_requirements_missing: list[str],
        error_message: str | None,
    ) -> EvidencePackage:
        """Update package status and assembled artifacts.

        Args:
            package_id: Package UUID.
            status: New status value.
            artifacts: Assembled artifact dict.
            carrier_requirements_fulfilled: Fulfilled requirement IDs.
            carrier_requirements_missing: Missing requirement IDs.
            error_message: Error detail if failed.

        Returns:
            Updated EvidencePackage.
        """
        now = datetime.now(tz=UTC)
        generated_at = now if status == "ready" else None
        expires_at = now + timedelta(days=self._expiry_days) if status == "ready" else None

        await self._session.execute(
            update(EvidencePackage)
            .where(EvidencePackage.id == package_id)
            .values(
                status=status,
                artifacts=artifacts,
                carrier_requirements_fulfilled=carrier_requirements_fulfilled,
                carrier_requirements_missing=carrier_requirements_missing,
                error_message=error_message,
                generated_at=generated_at,
                expires_at=expires_at,
            )
        )
        await self._session.flush()

        result = await self._session.execute(
            select(EvidencePackage).where(EvidencePackage.id == package_id)
        )
        return result.scalar_one()


class RiskCalculationRepository(BaseRepository[RiskCalculation]):
    """Persistence for RiskCalculation entities."""

    def __init__(self, session: AsyncSession) -> None:
        """Initialise with an async SQLAlchemy session.

        Args:
            session: AsyncSession with RLS context already set.
        """
        super().__init__(session, RiskCalculation)

    async def create(
        self,
        tenant_id: uuid.UUID,
        posture_assessment_id: uuid.UUID,
        calculation_type: str,
        methodology: str,
        controls_applied: list[dict[str, Any]],
        threat_scenarios: list[dict[str, Any]],
        calculation_metadata: dict[str, Any],
    ) -> RiskCalculation:
        """Create and persist a new RiskCalculation.

        Args:
            tenant_id: Tenant UUID.
            posture_assessment_id: Parent assessment UUID.
            calculation_type: Type of calculation.
            methodology: Risk methodology.
            controls_applied: Controls included in calculation.
            threat_scenarios: Threat scenarios modelled.
            calculation_metadata: Context metadata.

        Returns:
            Newly created RiskCalculation.
        """
        calculation = RiskCalculation(
            tenant_id=tenant_id,
            posture_assessment_id=posture_assessment_id,
            calculation_type=calculation_type,
            methodology=methodology,
            controls_applied=controls_applied,
            threat_scenarios=threat_scenarios,
            calculation_metadata=calculation_metadata,
        )
        self._session.add(calculation)
        await self._session.flush()
        await self._session.refresh(calculation)
        return calculation

    async def get(self, calculation_id: uuid.UUID, tenant_id: uuid.UUID) -> RiskCalculation | None:
        """Retrieve a RiskCalculation by ID within a tenant.

        Args:
            calculation_id: Calculation UUID.
            tenant_id: Tenant UUID.

        Returns:
            RiskCalculation or None.
        """
        result = await self._session.execute(
            select(RiskCalculation).where(
                RiskCalculation.id == calculation_id,
                RiskCalculation.tenant_id == tenant_id,
            )
        )
        return result.scalar_one_or_none()

    async def list_by_assessment(
        self,
        posture_assessment_id: uuid.UUID,
        tenant_id: uuid.UUID,
    ) -> list[RiskCalculation]:
        """List all risk calculations for a posture assessment.

        Args:
            posture_assessment_id: Parent assessment UUID.
            tenant_id: Tenant UUID.

        Returns:
            List of RiskCalculation records.
        """
        result = await self._session.execute(
            select(RiskCalculation).where(
                RiskCalculation.posture_assessment_id == posture_assessment_id,
                RiskCalculation.tenant_id == tenant_id,
            )
        )
        return list(result.scalars().all())

    async def update_results(
        self,
        calculation_id: uuid.UUID,
        baseline_risk_score: float | None,
        residual_risk_score: float | None,
        risk_reduction_pct: float | None,
        baseline_ale_usd: float | None,
        residual_ale_usd: float | None,
    ) -> RiskCalculation:
        """Update calculation with quantified risk results.

        Args:
            calculation_id: Calculation UUID.
            baseline_risk_score: Pre-control risk score.
            residual_risk_score: Post-control risk score.
            risk_reduction_pct: Percentage reduction.
            baseline_ale_usd: Pre-control ALE.
            residual_ale_usd: Post-control ALE.

        Returns:
            Updated RiskCalculation.
        """
        await self._session.execute(
            update(RiskCalculation)
            .where(RiskCalculation.id == calculation_id)
            .values(
                baseline_risk_score=baseline_risk_score,
                residual_risk_score=residual_risk_score,
                risk_reduction_pct=risk_reduction_pct,
                baseline_ale_usd=baseline_ale_usd,
                residual_ale_usd=residual_ale_usd,
            )
        )
        await self._session.flush()

        result = await self._session.execute(
            select(RiskCalculation).where(RiskCalculation.id == calculation_id)
        )
        return result.scalar_one()
