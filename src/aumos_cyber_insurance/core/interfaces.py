"""Protocol interfaces for dependency injection in the Cyber Insurance service.

All service dependencies are defined as Protocol classes here.
Concrete implementations live in adapters/. Services depend only on these
interfaces — never on concrete adapter types.
"""

import uuid
from typing import Any, Protocol, runtime_checkable

from aumos_cyber_insurance.core.models import (
    EvidencePackage,
    ImpactAnalysis,
    PostureAssessment,
    PremiumRecommendation,
    RiskCalculation,
)


@runtime_checkable
class IPostureAssessmentRepository(Protocol):
    """Persistence interface for PostureAssessment entities."""

    async def create(
        self,
        tenant_id: uuid.UUID,
        platform_id: str,
        platform_type: str,
        carrier_id: str | None,
        requested_by: uuid.UUID | None,
        assessment_metadata: dict[str, Any],
    ) -> PostureAssessment:
        """Create and persist a new PostureAssessment."""
        ...

    async def get(self, assessment_id: uuid.UUID, tenant_id: uuid.UUID) -> PostureAssessment | None:
        """Retrieve a PostureAssessment by ID within a tenant."""
        ...

    async def list_by_tenant(
        self,
        tenant_id: uuid.UUID,
        page: int,
        page_size: int,
        status: str | None,
        platform_id: str | None,
    ) -> tuple[list[PostureAssessment], int]:
        """List assessments for a tenant with pagination and optional filters."""
        ...

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
        """Update assessment status and results."""
        ...


@runtime_checkable
class IImpactAnalysisRepository(Protocol):
    """Persistence interface for ImpactAnalysis entities."""

    async def create(
        self,
        tenant_id: uuid.UUID,
        posture_assessment_id: uuid.UUID,
        platform_id: str,
        platform_type: str,
        analysis_metadata: dict[str, Any],
    ) -> ImpactAnalysis:
        """Create and persist a new ImpactAnalysis."""
        ...

    async def get(self, analysis_id: uuid.UUID, tenant_id: uuid.UUID) -> ImpactAnalysis | None:
        """Retrieve an ImpactAnalysis by ID within a tenant."""
        ...

    async def list_by_assessment(
        self,
        posture_assessment_id: uuid.UUID,
        tenant_id: uuid.UUID,
    ) -> list[ImpactAnalysis]:
        """List all impact analyses for a given posture assessment."""
        ...

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
        """Update analysis results after computation."""
        ...


@runtime_checkable
class IPremiumRecommendationRepository(Protocol):
    """Persistence interface for PremiumRecommendation entities."""

    async def create(
        self,
        tenant_id: uuid.UUID,
        posture_assessment_id: uuid.UUID,
        carrier_id: str,
        simulation_runs: int,
        recommendation_metadata: dict[str, Any],
    ) -> PremiumRecommendation:
        """Create and persist a new PremiumRecommendation."""
        ...

    async def get(self, recommendation_id: uuid.UUID, tenant_id: uuid.UUID) -> PremiumRecommendation | None:
        """Retrieve a PremiumRecommendation by ID within a tenant."""
        ...

    async def list_by_assessment(
        self,
        posture_assessment_id: uuid.UUID,
        tenant_id: uuid.UUID,
    ) -> list[PremiumRecommendation]:
        """List all recommendations for a posture assessment."""
        ...

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
        """Update recommendation with optimization results."""
        ...


@runtime_checkable
class IEvidencePackageRepository(Protocol):
    """Persistence interface for EvidencePackage entities."""

    async def create(
        self,
        tenant_id: uuid.UUID,
        posture_assessment_id: uuid.UUID,
        carrier_id: str,
        carrier_name: str,
        package_metadata: dict[str, Any],
    ) -> EvidencePackage:
        """Create and persist a new EvidencePackage."""
        ...

    async def get(self, package_id: uuid.UUID, tenant_id: uuid.UUID) -> EvidencePackage | None:
        """Retrieve an EvidencePackage by ID within a tenant."""
        ...

    async def list_by_assessment(
        self,
        posture_assessment_id: uuid.UUID,
        tenant_id: uuid.UUID,
    ) -> list[EvidencePackage]:
        """List all evidence packages for a posture assessment."""
        ...

    async def update_status(
        self,
        package_id: uuid.UUID,
        status: str,
        artifacts: dict[str, Any],
        carrier_requirements_fulfilled: list[str],
        carrier_requirements_missing: list[str],
        error_message: str | None,
    ) -> EvidencePackage:
        """Update package status and assembled artifacts."""
        ...


@runtime_checkable
class IRiskCalculationRepository(Protocol):
    """Persistence interface for RiskCalculation entities."""

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
        """Create and persist a new RiskCalculation."""
        ...

    async def get(self, calculation_id: uuid.UUID, tenant_id: uuid.UUID) -> RiskCalculation | None:
        """Retrieve a RiskCalculation by ID within a tenant."""
        ...

    async def list_by_assessment(
        self,
        posture_assessment_id: uuid.UUID,
        tenant_id: uuid.UUID,
    ) -> list[RiskCalculation]:
        """List all risk calculations for a posture assessment."""
        ...

    async def update_results(
        self,
        calculation_id: uuid.UUID,
        baseline_risk_score: float | None,
        residual_risk_score: float | None,
        risk_reduction_pct: float | None,
        baseline_ale_usd: float | None,
        residual_ale_usd: float | None,
    ) -> RiskCalculation:
        """Update calculation with quantified results."""
        ...


@runtime_checkable
class ICarrierAdapter(Protocol):
    """Interface for fetching insurance carrier requirements from external sources."""

    async def list_carriers(self) -> list[dict[str, Any]]:
        """Return the list of supported insurance carriers and their metadata."""
        ...

    async def get_carrier_requirements(self, carrier_id: str) -> dict[str, Any]:
        """Return the full requirement set for a specific carrier.

        Args:
            carrier_id: Carrier identifier (e.g., 'hiscox', 'chubb', 'coalition').

        Returns:
            Carrier requirements dict with control mappings.
        """
        ...

    async def check_posture_against_carrier(
        self,
        carrier_id: str,
        posture_data: dict[str, Any],
    ) -> dict[str, Any]:
        """Evaluate posture data against carrier requirements.

        Args:
            carrier_id: Target carrier identifier.
            posture_data: Current posture control coverage dict.

        Returns:
            Requirement fulfillment map: {requirement_id: bool}.
        """
        ...
