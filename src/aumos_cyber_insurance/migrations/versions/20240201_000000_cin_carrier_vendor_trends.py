"""cin carrier requirements, third-party assessments, and posture score history.

GAP-517: cin_carrier_requirements table for DatabaseCarrierAdapter.
GAP-521: cin_third_party_assessments table for vendor risk endpoint.
GAP-524: cin_posture_score_history table for trend analysis endpoint.

Revision ID: cin_002
Revises: cin_001
Create Date: 2024-02-01 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "cin_002"
down_revision: str | None = "cin_001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create carrier requirements, third-party assessments, and score history tables."""

    # -----------------------------------------------------------------------
    # GAP-517: cin_carrier_requirements
    # Stores carrier control requirements for DatabaseCarrierAdapter.
    # NOT tenant-scoped — this is global carrier data managed by AumOS ops.
    # -----------------------------------------------------------------------
    op.create_table(
        "cin_carrier_requirements",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("carrier_id", sa.String(255), nullable=False),
        sa.Column("carrier_name", sa.String(255), nullable=False),
        sa.Column("coverage_types", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("requirement_id", sa.String(255), nullable=False),
        sa.Column("requirement_name", sa.String(512), nullable=False),
        sa.Column("requirement_description", sa.Text(), nullable=True),
        sa.Column("category", sa.String(255), nullable=False),
        sa.Column("severity", sa.String(50), nullable=False, server_default="medium"),
        sa.Column("control_mappings", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("required_coverage_pct", sa.Float(), nullable=False, server_default="0.8"),
        sa.Column("carrier_metadata", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("carrier_id", "requirement_id", name="uq_cin_carrier_req"),
    )
    op.create_index(
        "ix_cin_carrier_requirements_carrier_id",
        "cin_carrier_requirements",
        ["carrier_id"],
    )
    op.create_index(
        "ix_cin_carrier_requirements_is_active",
        "cin_carrier_requirements",
        ["is_active"],
    )
    op.create_index(
        "ix_cin_carrier_requirements_category",
        "cin_carrier_requirements",
        ["category"],
    )

    # -----------------------------------------------------------------------
    # GAP-521: cin_third_party_assessments
    # Tracks vendor/third-party risk assessments linked to posture assessments.
    # Tenant-scoped with RLS.
    # -----------------------------------------------------------------------
    op.create_table(
        "cin_third_party_assessments",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("posture_assessment_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("vendor_name", sa.String(512), nullable=False),
        sa.Column("vendor_category", sa.String(255), nullable=True),
        sa.Column("risk_score", sa.Float(), nullable=True),
        sa.Column("risk_tier", sa.String(50), nullable=True),
        sa.Column("findings", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("controls_reviewed", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("assessment_status", sa.String(50), nullable=False, server_default="pending"),
        sa.Column("assessor_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_review_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("assessment_metadata", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.ForeignKeyConstraint(
            ["posture_assessment_id"],
            ["cin_posture_assessments.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_cin_third_party_assessments_tenant_id",
        "cin_third_party_assessments",
        ["tenant_id"],
    )
    op.create_index(
        "ix_cin_third_party_assessments_posture_assessment_id",
        "cin_third_party_assessments",
        ["posture_assessment_id"],
    )
    op.create_index(
        "ix_cin_third_party_assessments_vendor_name",
        "cin_third_party_assessments",
        ["vendor_name"],
    )
    op.create_index(
        "ix_cin_third_party_assessments_risk_tier",
        "cin_third_party_assessments",
        ["risk_tier"],
    )

    op.execute("""
        ALTER TABLE cin_third_party_assessments ENABLE ROW LEVEL SECURITY;
        CREATE POLICY cin_third_party_rls ON cin_third_party_assessments
            USING (tenant_id = current_setting('app.current_tenant')::uuid);
    """)

    # -----------------------------------------------------------------------
    # GAP-524: cin_posture_score_history
    # Daily snapshots of posture scores for trend analysis.
    # Tenant-scoped with RLS.
    # -----------------------------------------------------------------------
    op.create_table(
        "cin_posture_score_history",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("snapshot_date", sa.Date(), nullable=False),
        sa.Column("platform_id", sa.String(255), nullable=False),
        sa.Column("posture_score", sa.Float(), nullable=False),
        sa.Column("gap_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("control_coverage_summary", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("carrier_id", sa.String(255), nullable=True),
        sa.Column("assessment_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("snapshot_metadata", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "platform_id",
            "snapshot_date",
            "carrier_id",
            name="uq_cin_score_history_daily",
        ),
    )
    op.create_index(
        "ix_cin_posture_score_history_tenant_id",
        "cin_posture_score_history",
        ["tenant_id"],
    )
    op.create_index(
        "ix_cin_posture_score_history_platform_id",
        "cin_posture_score_history",
        ["platform_id"],
    )
    op.create_index(
        "ix_cin_posture_score_history_snapshot_date",
        "cin_posture_score_history",
        ["snapshot_date"],
    )
    op.create_index(
        "ix_cin_posture_score_history_tenant_platform",
        "cin_posture_score_history",
        ["tenant_id", "platform_id"],
    )

    op.execute("""
        ALTER TABLE cin_posture_score_history ENABLE ROW LEVEL SECURITY;
        CREATE POLICY cin_score_history_rls ON cin_posture_score_history
            USING (tenant_id = current_setting('app.current_tenant')::uuid);
    """)


def downgrade() -> None:
    """Drop carrier requirements, third-party assessments, and score history tables."""
    op.execute("DROP TABLE IF EXISTS cin_posture_score_history CASCADE;")
    op.execute("DROP TABLE IF EXISTS cin_third_party_assessments CASCADE;")
    op.execute("DROP TABLE IF EXISTS cin_carrier_requirements CASCADE;")
