"""Pydantic request and response schemas for the AumOS Cyber Insurance API.

All API inputs and outputs are typed Pydantic models.
Never return raw dicts from route handlers.
"""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Posture assessment schemas
# ---------------------------------------------------------------------------


class PostureAssessRequest(BaseModel):
    """Request body for POST /api/v1/insurance/posture/assess."""

    platform_id: str = Field(
        description="Identifier of the platform or environment to assess",
        examples=["prod-aws-us-east-1"],
    )
    platform_type: str = Field(
        description="Platform category: cloud | on_premise | hybrid | saas | paas",
        examples=["cloud"],
    )
    carrier_id: str | None = Field(
        default=None,
        description="Target carrier for assessment (None = all carriers)",
        examples=["hiscox"],
    )
    control_coverage: dict[str, float] = Field(
        description="Per-control-domain coverage percentages (0.0–1.0)",
        examples=[{"mfa": 0.95, "endpoint_detection": 0.70, "backup_recovery": 0.85}],
    )
    assessment_metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Optional context metadata for this assessment",
    )


class PostureAssessmentResponse(BaseModel):
    """Response model for posture assessment endpoints."""

    id: uuid.UUID
    tenant_id: uuid.UUID
    platform_id: str
    platform_type: str
    carrier_id: str | None
    status: str
    posture_score: float | None
    control_coverage: dict[str, Any]
    gaps: list[dict[str, Any]]
    carrier_requirements_met: dict[str, Any]
    assessment_metadata: dict[str, Any]
    completed_at: datetime | None
    error_message: str | None
    requested_by: uuid.UUID | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class PostureAssessmentListResponse(BaseModel):
    """Paginated list of posture assessments."""

    items: list[PostureAssessmentResponse]
    total: int
    page: int
    page_size: int


# ---------------------------------------------------------------------------
# Impact analysis schemas
# ---------------------------------------------------------------------------


class ImpactAnalyzeRequest(BaseModel):
    """Request body for POST /api/v1/insurance/impact/analyze."""

    assessment_id: uuid.UUID = Field(
        description="Completed PostureAssessment UUID to analyze",
    )
    platform_revenue_usd: float | None = Field(
        default=None,
        description="Annual platform revenue for ALE calculation",
        examples=[5_000_000.0],
    )
    existing_coverage_usd: float | None = Field(
        default=None,
        description="Current cyber insurance coverage limit in USD",
        examples=[2_000_000.0],
    )


class ImpactAnalysisResponse(BaseModel):
    """Response model for impact analysis endpoints."""

    id: uuid.UUID
    tenant_id: uuid.UUID
    posture_assessment_id: uuid.UUID
    platform_id: str
    platform_type: str
    estimated_annual_loss: float | None
    breach_probability_pct: float | None
    coverage_gap_usd: float | None
    risk_drivers: list[dict[str, Any]]
    recommended_controls: list[dict[str, Any]]
    carrier_impact_map: dict[str, Any]
    analysis_metadata: dict[str, Any]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ImpactAnalysisListResponse(BaseModel):
    """List of impact analyses."""

    items: list[ImpactAnalysisResponse]
    total: int


# ---------------------------------------------------------------------------
# Premium optimization schemas
# ---------------------------------------------------------------------------


class PremiumOptimizeRequest(BaseModel):
    """Request body for POST /api/v1/insurance/premium/optimize."""

    assessment_id: uuid.UUID = Field(
        description="Completed PostureAssessment UUID to optimize premiums for",
    )
    carrier_id: str = Field(
        description="Target carrier for premium optimization",
        examples=["coalition"],
    )
    current_premium_usd: float | None = Field(
        default=None,
        description="Current annual premium with this carrier in USD",
        examples=[50_000.0],
    )
    coverage_limit_usd: float | None = Field(
        default=None,
        description="Current coverage limit with this carrier in USD",
        examples=[5_000_000.0],
    )


class PremiumRecommendationResponse(BaseModel):
    """Response model for premium recommendation endpoints."""

    id: uuid.UUID
    tenant_id: uuid.UUID
    posture_assessment_id: uuid.UUID
    carrier_id: str
    current_estimated_premium_usd: float | None
    optimized_premium_usd: float | None
    discount_pct: float | None
    simulation_runs: int
    recommended_controls: list[dict[str, Any]]
    roi_analysis: dict[str, Any]
    confidence_interval: dict[str, Any]
    recommendation_metadata: dict[str, Any]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Evidence package schemas
# ---------------------------------------------------------------------------


class EvidencePackageResponse(BaseModel):
    """Response model for evidence package endpoints."""

    id: uuid.UUID
    tenant_id: uuid.UUID
    posture_assessment_id: uuid.UUID
    carrier_id: str
    carrier_name: str
    status: str
    artifacts: dict[str, Any]
    carrier_requirements_fulfilled: list[str]
    carrier_requirements_missing: list[str]
    generated_at: datetime | None
    expires_at: datetime | None
    submitted_at: datetime | None
    error_message: str | None
    package_metadata: dict[str, Any]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class EvidencePackageRequest(BaseModel):
    """Request body for GET /api/v1/insurance/evidence/package (query params handled separately)."""

    assessment_id: uuid.UUID = Field(
        description="PostureAssessment UUID to generate evidence package for",
    )
    carrier_id: str = Field(
        description="Target carrier identifier",
        examples=["chubb"],
    )
    carrier_name: str = Field(
        description="Human-readable carrier name",
        examples=["Chubb Cyber"],
    )
    package_metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Optional metadata (submission reference, contact info, etc.)",
    )


# ---------------------------------------------------------------------------
# Risk calculation schemas
# ---------------------------------------------------------------------------


class RiskCalculateRequest(BaseModel):
    """Request body for POST /api/v1/insurance/risk/calculate."""

    assessment_id: uuid.UUID = Field(
        description="Completed PostureAssessment UUID",
    )
    calculation_type: str = Field(
        description="Type: annualized_loss | breach_probability | control_effectiveness | portfolio",
        examples=["annualized_loss"],
    )
    methodology: str = Field(
        default="fair",
        description="Risk quantification methodology: fair | cvss | custom",
        examples=["fair"],
    )
    controls_to_apply: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Controls to include: [{control_id, weight, effectiveness_pct}]",
    )
    threat_scenarios: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Threat scenarios to model: [{scenario_id, name, probability, impact_usd}]",
    )
    asset_value_usd: float | None = Field(
        default=None,
        description="Asset value in USD for financial impact calculations",
        examples=[10_000_000.0],
    )


class RiskCalculationResponse(BaseModel):
    """Response model for risk calculation endpoints."""

    id: uuid.UUID
    tenant_id: uuid.UUID
    posture_assessment_id: uuid.UUID
    calculation_type: str
    baseline_risk_score: float | None
    residual_risk_score: float | None
    risk_reduction_pct: float | None
    baseline_ale_usd: float | None
    residual_ale_usd: float | None
    controls_applied: list[dict[str, Any]]
    methodology: str
    threat_scenarios: list[dict[str, Any]]
    calculation_metadata: dict[str, Any]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Carrier schemas
# ---------------------------------------------------------------------------


class CarrierRequirementItem(BaseModel):
    """A single carrier requirement."""

    requirement_id: str
    name: str
    description: str
    category: str
    severity: str
    control_mappings: list[str]


class CarrierResponse(BaseModel):
    """Response model for a single insurance carrier."""

    carrier_id: str
    name: str
    coverage_types: list[str]
    requirements: list[CarrierRequirementItem]
    metadata: dict[str, Any] = Field(default_factory=dict)


class CarrierListResponse(BaseModel):
    """List of supported insurance carriers."""

    items: list[CarrierResponse]
    total: int


# ---------------------------------------------------------------------------
# GAP-521: Third-party vendor assessment schemas
# ---------------------------------------------------------------------------


class ThirdPartyAssessmentRequest(BaseModel):
    """Request body for POST /api/v1/insurance/assessments/{id}/third-party-scan."""

    vendor_name: str = Field(
        description="Name of the third-party vendor to assess",
        examples=["Acme Cloud Services"],
    )
    vendor_category: str | None = Field(
        default=None,
        description="Vendor risk category: cloud | saas | critical | high | medium | low",
        examples=["cloud"],
    )
    controls_reviewed: list[str] = Field(
        default_factory=list,
        description="Control domain IDs to include in the vendor review",
        examples=[["mfa", "endpoint_detection", "backup_recovery"]],
    )
    assessment_metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Optional additional metadata for this vendor assessment",
    )


class ThirdPartyAssessmentResponse(BaseModel):
    """Response model for third-party vendor risk assessments."""

    assessment_id: uuid.UUID
    vendor_name: str
    vendor_category: str | None
    risk_score: float
    risk_tier: str
    findings: list[dict[str, Any]]
    controls_reviewed: list[str]
    assessment_status: str

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# GAP-522: Portfolio optimization schemas
# ---------------------------------------------------------------------------


class PortfolioOptimizeRequest(BaseModel):
    """Request body for POST /api/v1/insurance/premium/portfolio."""

    assessment_id: uuid.UUID = Field(
        description="Completed PostureAssessment UUID to optimize portfolio for",
    )
    carrier_ids: list[str] = Field(
        description="List of carrier IDs to include in portfolio optimization",
        examples=[["hiscox", "coalition", "chubb", "travelers"]],
    )
    current_premiums: dict[str, float] | None = Field(
        default=None,
        description="Current annual premiums per carrier {carrier_id: usd_amount}",
        examples=[{"hiscox": 45000.0, "coalition": 38000.0}],
    )
    coverage_limits: dict[str, float] | None = Field(
        default=None,
        description="Current coverage limits per carrier {carrier_id: usd_amount}",
        examples=[{"hiscox": 5000000.0, "coalition": 3000000.0}],
    )


class PortfolioRecommendationResponse(BaseModel):
    """Response model for multi-carrier portfolio optimization."""

    assessment_id: str
    tenant_id: str
    carrier_count: int
    carriers: list[dict[str, Any]]
    total_current_premium_usd: float
    total_optimized_premium_usd: float
    total_savings_usd: float
    recommended_carrier: str | None
    posture_score: float | None
    optimization_sample_size: int

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# GAP-524: Posture trends schemas
# ---------------------------------------------------------------------------


class PostureTrendsResponse(BaseModel):
    """Response model for posture score trend analysis."""

    platform_id: str
    tenant_id: uuid.UUID
    days_requested: int
    snapshot_count: int
    snapshots: list[dict[str, Any]]

    model_config = {"from_attributes": True}
