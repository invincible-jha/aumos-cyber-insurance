"""SQLAlchemy ORM models for the AumOS Cyber Insurance service.

All tables use the `cin_` prefix. Tenant-scoped tables extend AumOSModel
which supplies id (UUID), tenant_id, created_at, and updated_at columns.

Domain model:
  PostureAssessment      — insurance posture assessment for a tenant/platform
  ImpactAnalysis         — per-platform insurance impact analysis result
  PremiumRecommendation  — premium optimization recommendation from synthetic data
  EvidencePackage        — generated evidence package for a specific carrier
  RiskCalculation        — quantified risk reduction calculation
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from aumos_common.database import AumOSModel


class PostureAssessment(AumOSModel):
    """Insurance posture assessment record for a tenant or platform.

    Captures the current security and compliance posture against carrier
    requirements at a point in time. Each assessment yields a posture score
    that feeds directly into premium optimization recommendations.

    Status transitions:
        pending → in_progress → completed
        pending → in_progress → failed

    Table: cin_posture_assessments
    """

    __tablename__ = "cin_posture_assessments"

    platform_id: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        index=True,
        comment="Identifier of the platform or environment being assessed",
    )
    platform_type: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        comment="Platform category: cloud | on_premise | hybrid | saas | paas",
    )
    carrier_id: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        index=True,
        comment="Target insurance carrier ID for requirement mapping (null = all carriers)",
    )
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="pending",
        index=True,
        comment="pending | in_progress | completed | failed",
    )
    posture_score: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
        comment="Aggregate posture score 0.0–1.0 (higher = better cyber hygiene)",
    )
    control_coverage: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        comment="Per-control-domain coverage percentages: {domain: pct_covered}",
    )
    gaps: Mapped[list] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        comment="List of identified gaps: [{control_id, severity, description, carrier_ids}]",
    )
    carrier_requirements_met: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        comment="Per-carrier requirement fulfillment: {carrier_id: {requirement_id: bool}}",
    )
    assessment_metadata: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        comment="Arbitrary metadata about the assessment context",
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="Timestamp when assessment reached a terminal state",
    )
    error_message: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="Error detail if status=failed",
    )
    requested_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
        comment="User ID of the person or service that triggered this assessment",
    )

    impact_analyses: Mapped[list["ImpactAnalysis"]] = relationship(
        "ImpactAnalysis",
        back_populates="posture_assessment",
        cascade="all, delete-orphan",
    )
    premium_recommendations: Mapped[list["PremiumRecommendation"]] = relationship(
        "PremiumRecommendation",
        back_populates="posture_assessment",
        cascade="all, delete-orphan",
    )
    evidence_packages: Mapped[list["EvidencePackage"]] = relationship(
        "EvidencePackage",
        back_populates="posture_assessment",
        cascade="all, delete-orphan",
    )
    risk_calculations: Mapped[list["RiskCalculation"]] = relationship(
        "RiskCalculation",
        back_populates="posture_assessment",
        cascade="all, delete-orphan",
    )


class ImpactAnalysis(AumOSModel):
    """Per-platform insurance impact analysis result.

    Breaks down the financial and coverage impact of cyber incidents across
    platforms, informing which platforms drive the most premium exposure.

    Table: cin_impact_analyses
    """

    __tablename__ = "cin_impact_analyses"

    posture_assessment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("cin_posture_assessments.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="Parent posture assessment UUID",
    )
    platform_id: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        index=True,
        comment="Platform being analysed",
    )
    platform_type: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        comment="cloud | on_premise | hybrid | saas | paas",
    )
    estimated_annual_loss: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
        comment="Estimated annual loss exposure in USD based on posture gaps",
    )
    breach_probability_pct: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
        comment="Estimated probability of a material breach in the next 12 months (0–100)",
    )
    coverage_gap_usd: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
        comment="Estimated dollar gap between current coverage and required coverage",
    )
    risk_drivers: Mapped[list] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        comment="Top risk factors: [{factor, severity, estimated_impact_usd}]",
    )
    recommended_controls: Mapped[list] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        comment="Controls recommended to reduce impact: [{control_id, expected_reduction_usd}]",
    )
    carrier_impact_map: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        comment="Per-carrier premium impact delta: {carrier_id: {current_premium, projected_premium}}",
    )
    analysis_metadata: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        comment="Arbitrary analysis context (model version, data sources, etc.)",
    )

    posture_assessment: Mapped["PostureAssessment"] = relationship(
        "PostureAssessment",
        back_populates="impact_analyses",
    )


class PremiumRecommendation(AumOSModel):
    """Premium optimization recommendation derived from synthetic data simulation.

    Runs Monte Carlo simulations over synthetic breach scenarios to identify
    which control improvements yield the highest premium reduction per dollar invested.

    Table: cin_premium_recommendations
    """

    __tablename__ = "cin_premium_recommendations"

    posture_assessment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("cin_posture_assessments.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="Parent posture assessment UUID",
    )
    carrier_id: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        index=True,
        comment="Target carrier for this premium recommendation",
    )
    current_estimated_premium_usd: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
        comment="Estimated current annual premium based on posture assessment",
    )
    optimized_premium_usd: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
        comment="Projected premium after implementing recommended controls",
    )
    discount_pct: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
        comment="Projected premium discount percentage (capped at settings.premium_discount_cap_pct)",
    )
    simulation_runs: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        comment="Number of synthetic Monte Carlo simulation runs used for this recommendation",
    )
    recommended_controls: Mapped[list] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        comment="Priority-ordered control improvements: [{control_id, priority, estimated_discount_pct, implementation_cost_usd}]",
    )
    roi_analysis: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        comment="Return-on-investment analysis: {total_investment_usd, annual_savings_usd, payback_months}",
    )
    confidence_interval: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        comment="95% confidence interval for the premium estimate: {lower_usd, upper_usd}",
    )
    recommendation_metadata: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        comment="Metadata about the optimization run (model version, synthetic data config, etc.)",
    )

    posture_assessment: Mapped["PostureAssessment"] = relationship(
        "PostureAssessment",
        back_populates="premium_recommendations",
    )


class EvidencePackage(AumOSModel):
    """Generated evidence package for submission to a specific carrier.

    Assembles all security attestations, compliance certificates, and
    posture evidence required by a carrier into a structured package
    ready for submission.

    Table: cin_evidence_packages
    """

    __tablename__ = "cin_evidence_packages"

    posture_assessment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("cin_posture_assessments.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="Parent posture assessment UUID",
    )
    carrier_id: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        index=True,
        comment="Target carrier for this evidence package",
    )
    carrier_name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="Human-readable carrier name",
    )
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="pending",
        index=True,
        comment="pending | generating | ready | submitted | expired",
    )
    artifacts: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        comment="Assembled evidence artifacts: {artifact_type: {content, source, generated_at}}",
    )
    carrier_requirements_fulfilled: Mapped[list] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        comment="List of carrier requirement IDs that this package satisfies",
    )
    carrier_requirements_missing: Mapped[list] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        comment="List of carrier requirement IDs that could not be satisfied",
    )
    generated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="Timestamp when package generation completed",
    )
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="Timestamp when the package expires and must be regenerated",
    )
    submitted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="Timestamp when the package was submitted to the carrier",
    )
    error_message: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="Error detail if status=failed during generation",
    )
    package_metadata: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        comment="Arbitrary metadata about the package (submission reference, contacts, etc.)",
    )

    posture_assessment: Mapped["PostureAssessment"] = relationship(
        "PostureAssessment",
        back_populates="evidence_packages",
    )


class RiskCalculation(AumOSModel):
    """Quantified risk reduction calculation.

    Measures the before/after risk reduction from implementing a set of
    controls, providing auditable evidence of security investment ROI
    for carrier negotiations.

    Table: cin_risk_calculations
    """

    __tablename__ = "cin_risk_calculations"

    posture_assessment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("cin_posture_assessments.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="Parent posture assessment UUID",
    )
    calculation_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        comment="Type of risk calculation: annualized_loss | breach_probability | control_effectiveness | portfolio",
    )
    baseline_risk_score: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
        comment="Risk score before controls: 0.0 (no risk) to 1.0 (maximum risk)",
    )
    residual_risk_score: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
        comment="Risk score after applying recommended controls",
    )
    risk_reduction_pct: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
        comment="Percentage reduction in risk from baseline to residual",
    )
    baseline_ale_usd: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
        comment="Annualized Loss Expectancy before controls in USD",
    )
    residual_ale_usd: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
        comment="Annualized Loss Expectancy after controls in USD",
    )
    controls_applied: Mapped[list] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        comment="Controls included in this calculation: [{control_id, weight, effectiveness_pct}]",
    )
    methodology: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="fair",
        comment="Risk quantification methodology: fair | cvss | custom",
    )
    threat_scenarios: Mapped[list] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        comment="Threat scenarios modelled: [{scenario_id, name, probability, impact_usd}]",
    )
    calculation_metadata: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        comment="Arbitrary metadata about the calculation run",
    )

    posture_assessment: Mapped["PostureAssessment"] = relationship(
        "PostureAssessment",
        back_populates="risk_calculations",
    )
