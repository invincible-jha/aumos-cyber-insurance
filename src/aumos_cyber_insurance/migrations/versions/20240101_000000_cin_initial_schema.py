"""cin initial schema.

Revision ID: cin_001
Revises:
Create Date: 2024-01-01 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "cin_001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create all cyber insurance tables with RLS policies."""
    # cin_posture_assessments
    op.create_table(
        "cin_posture_assessments",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("platform_id", sa.String(255), nullable=False),
        sa.Column("platform_type", sa.String(100), nullable=False),
        sa.Column("carrier_id", sa.String(255), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("posture_score", sa.Float(), nullable=True),
        sa.Column("control_coverage", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("gaps", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("carrier_requirements_met", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("assessment_metadata", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("requested_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_cin_posture_assessments_tenant_id", "cin_posture_assessments", ["tenant_id"])
    op.create_index("ix_cin_posture_assessments_platform_id", "cin_posture_assessments", ["platform_id"])
    op.create_index("ix_cin_posture_assessments_carrier_id", "cin_posture_assessments", ["carrier_id"])
    op.create_index("ix_cin_posture_assessments_status", "cin_posture_assessments", ["status"])

    op.execute("""
        ALTER TABLE cin_posture_assessments ENABLE ROW LEVEL SECURITY;
        CREATE POLICY cin_posture_rls ON cin_posture_assessments
            USING (tenant_id = current_setting('app.current_tenant')::uuid);
    """)

    # cin_impact_analyses
    op.create_table(
        "cin_impact_analyses",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("posture_assessment_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("platform_id", sa.String(255), nullable=False),
        sa.Column("platform_type", sa.String(100), nullable=False),
        sa.Column("estimated_annual_loss", sa.Float(), nullable=True),
        sa.Column("breach_probability_pct", sa.Float(), nullable=True),
        sa.Column("coverage_gap_usd", sa.Float(), nullable=True),
        sa.Column("risk_drivers", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("recommended_controls", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("carrier_impact_map", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("analysis_metadata", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.ForeignKeyConstraint(
            ["posture_assessment_id"],
            ["cin_posture_assessments.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_cin_impact_analyses_tenant_id", "cin_impact_analyses", ["tenant_id"])
    op.create_index("ix_cin_impact_analyses_posture_assessment_id", "cin_impact_analyses", ["posture_assessment_id"])
    op.create_index("ix_cin_impact_analyses_platform_id", "cin_impact_analyses", ["platform_id"])

    op.execute("""
        ALTER TABLE cin_impact_analyses ENABLE ROW LEVEL SECURITY;
        CREATE POLICY cin_impact_rls ON cin_impact_analyses
            USING (tenant_id = current_setting('app.current_tenant')::uuid);
    """)

    # cin_premium_recommendations
    op.create_table(
        "cin_premium_recommendations",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("posture_assessment_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("carrier_id", sa.String(255), nullable=False),
        sa.Column("current_estimated_premium_usd", sa.Float(), nullable=True),
        sa.Column("optimized_premium_usd", sa.Float(), nullable=True),
        sa.Column("discount_pct", sa.Float(), nullable=True),
        sa.Column("simulation_runs", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("recommended_controls", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("roi_analysis", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("confidence_interval", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("recommendation_metadata", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.ForeignKeyConstraint(
            ["posture_assessment_id"],
            ["cin_posture_assessments.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_cin_premium_recommendations_tenant_id", "cin_premium_recommendations", ["tenant_id"])
    op.create_index("ix_cin_premium_recommendations_assessment_id", "cin_premium_recommendations", ["posture_assessment_id"])
    op.create_index("ix_cin_premium_recommendations_carrier_id", "cin_premium_recommendations", ["carrier_id"])

    op.execute("""
        ALTER TABLE cin_premium_recommendations ENABLE ROW LEVEL SECURITY;
        CREATE POLICY cin_premium_rls ON cin_premium_recommendations
            USING (tenant_id = current_setting('app.current_tenant')::uuid);
    """)

    # cin_evidence_packages
    op.create_table(
        "cin_evidence_packages",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("posture_assessment_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("carrier_id", sa.String(255), nullable=False),
        sa.Column("carrier_name", sa.String(255), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("artifacts", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("carrier_requirements_fulfilled", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("carrier_requirements_missing", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("package_metadata", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.ForeignKeyConstraint(
            ["posture_assessment_id"],
            ["cin_posture_assessments.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_cin_evidence_packages_tenant_id", "cin_evidence_packages", ["tenant_id"])
    op.create_index("ix_cin_evidence_packages_assessment_id", "cin_evidence_packages", ["posture_assessment_id"])
    op.create_index("ix_cin_evidence_packages_carrier_id", "cin_evidence_packages", ["carrier_id"])
    op.create_index("ix_cin_evidence_packages_status", "cin_evidence_packages", ["status"])

    op.execute("""
        ALTER TABLE cin_evidence_packages ENABLE ROW LEVEL SECURITY;
        CREATE POLICY cin_evidence_rls ON cin_evidence_packages
            USING (tenant_id = current_setting('app.current_tenant')::uuid);
    """)

    # cin_risk_calculations
    op.create_table(
        "cin_risk_calculations",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("posture_assessment_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("calculation_type", sa.String(50), nullable=False),
        sa.Column("baseline_risk_score", sa.Float(), nullable=True),
        sa.Column("residual_risk_score", sa.Float(), nullable=True),
        sa.Column("risk_reduction_pct", sa.Float(), nullable=True),
        sa.Column("baseline_ale_usd", sa.Float(), nullable=True),
        sa.Column("residual_ale_usd", sa.Float(), nullable=True),
        sa.Column("controls_applied", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("methodology", sa.String(50), nullable=False, server_default="fair"),
        sa.Column("threat_scenarios", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("calculation_metadata", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.ForeignKeyConstraint(
            ["posture_assessment_id"],
            ["cin_posture_assessments.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_cin_risk_calculations_tenant_id", "cin_risk_calculations", ["tenant_id"])
    op.create_index("ix_cin_risk_calculations_assessment_id", "cin_risk_calculations", ["posture_assessment_id"])

    op.execute("""
        ALTER TABLE cin_risk_calculations ENABLE ROW LEVEL SECURITY;
        CREATE POLICY cin_risk_rls ON cin_risk_calculations
            USING (tenant_id = current_setting('app.current_tenant')::uuid);
    """)


def downgrade() -> None:
    """Drop all cyber insurance tables."""
    op.execute("DROP TABLE IF EXISTS cin_risk_calculations CASCADE;")
    op.execute("DROP TABLE IF EXISTS cin_evidence_packages CASCADE;")
    op.execute("DROP TABLE IF EXISTS cin_premium_recommendations CASCADE;")
    op.execute("DROP TABLE IF EXISTS cin_impact_analyses CASCADE;")
    op.execute("DROP TABLE IF EXISTS cin_posture_assessments CASCADE;")
