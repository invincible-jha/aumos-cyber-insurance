"""GAP-517: DatabaseCarrierAdapter — carrier requirements backed by PostgreSQL.

Reads carrier definitions and requirements from the ``cin_carrier_requirements``
table.  Replaces the StubCarrierAdapter for production deployments when
``AUMOS_INSURANCE_CARRIER_ADAPTER=database``.
"""
from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from aumos_common.observability import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Table reflection — lightweight, avoids importing the full ORM model here
# ---------------------------------------------------------------------------

_carrier_requirements_table = sa.table(
    "cin_carrier_requirements",
    sa.column("carrier_id", sa.String),
    sa.column("carrier_name", sa.String),
    sa.column("coverage_types", sa.JSON),
    sa.column("requirement_id", sa.String),
    sa.column("requirement_name", sa.String),
    sa.column("requirement_description", sa.Text),
    sa.column("category", sa.String),
    sa.column("severity", sa.String),
    sa.column("control_mappings", sa.JSON),
    sa.column("required_coverage_pct", sa.Float),
    sa.column("carrier_metadata", sa.JSON),
    sa.column("is_active", sa.Boolean),
)


class DatabaseCarrierAdapter:
    """Carrier adapter that loads requirements from the ``cin_carrier_requirements`` table.

    Designed as a drop-in replacement for ``StubCarrierAdapter`` in production.
    Requires an injected ``AsyncSession``; the session must already have the
    RLS context variable (``app.current_tenant``) set by ``aumos-common``'s
    ``get_db_session`` helper.

    Args:
        session: Async SQLAlchemy session with RLS context set.
    """

    def __init__(self, session: AsyncSession) -> None:
        """Initialise with an injected async database session.

        Args:
            session: Active async SQLAlchemy session.
        """
        self._session = session

    async def list_carriers(self) -> list[dict[str, Any]]:
        """List all active insurance carriers from the database.

        Returns:
            List of carrier dicts with carrier_id, name, coverage_types,
            requirements, and metadata keys.
        """
        result = await self._session.execute(
            sa.select(
                _carrier_requirements_table.c.carrier_id,
                _carrier_requirements_table.c.carrier_name,
                _carrier_requirements_table.c.coverage_types,
                _carrier_requirements_table.c.requirement_id,
                _carrier_requirements_table.c.requirement_name,
                _carrier_requirements_table.c.requirement_description,
                _carrier_requirements_table.c.category,
                _carrier_requirements_table.c.severity,
                _carrier_requirements_table.c.control_mappings,
                _carrier_requirements_table.c.required_coverage_pct,
                _carrier_requirements_table.c.carrier_metadata,
            ).where(
                _carrier_requirements_table.c.is_active == True  # noqa: E712
            ).order_by(
                _carrier_requirements_table.c.carrier_id,
                _carrier_requirements_table.c.requirement_id,
            )
        )
        rows = result.mappings().all()

        carriers: dict[str, dict[str, Any]] = {}
        for row in rows:
            cid = row["carrier_id"]
            if cid not in carriers:
                carriers[cid] = {
                    "carrier_id": cid,
                    "name": row["carrier_name"],
                    "coverage_types": row["coverage_types"] or [],
                    "requirements": [],
                    "metadata": row["carrier_metadata"] or {},
                }
            carriers[cid]["requirements"].append({
                "requirement_id": row["requirement_id"],
                "name": row["requirement_name"],
                "description": row["requirement_description"] or "",
                "category": row["category"],
                "severity": row["severity"],
                "control_mappings": row["control_mappings"] or [],
                "required_coverage_pct": row["required_coverage_pct"],
            })

        logger.debug("Carriers loaded from database", carrier_count=len(carriers))
        return list(carriers.values())

    async def get_carrier_requirements(self, carrier_id: str) -> list[dict[str, Any]]:
        """Retrieve all requirements for a specific carrier.

        Args:
            carrier_id: Carrier identifier to look up.

        Returns:
            List of requirement dicts for the carrier. Empty list if not found.
        """
        result = await self._session.execute(
            sa.select(
                _carrier_requirements_table.c.requirement_id,
                _carrier_requirements_table.c.requirement_name,
                _carrier_requirements_table.c.requirement_description,
                _carrier_requirements_table.c.category,
                _carrier_requirements_table.c.severity,
                _carrier_requirements_table.c.control_mappings,
                _carrier_requirements_table.c.required_coverage_pct,
            ).where(
                sa.and_(
                    _carrier_requirements_table.c.carrier_id == carrier_id,
                    _carrier_requirements_table.c.is_active == True,  # noqa: E712
                )
            ).order_by(_carrier_requirements_table.c.requirement_id)
        )
        rows = result.mappings().all()
        return [
            {
                "requirement_id": row["requirement_id"],
                "name": row["requirement_name"],
                "description": row["requirement_description"] or "",
                "category": row["category"],
                "severity": row["severity"],
                "control_mappings": row["control_mappings"] or [],
                "required_coverage_pct": row["required_coverage_pct"],
            }
            for row in rows
        ]

    async def check_posture_against_carrier(
        self,
        carrier_id: str,
        posture_data: dict[str, float],
    ) -> dict[str, bool]:
        """Check whether the provided posture satisfies each carrier requirement.

        Compares each control coverage percentage in ``posture_data`` against
        the ``required_coverage_pct`` for each active carrier requirement.
        A requirement is met when the control coverage meets or exceeds the
        required threshold.

        Args:
            carrier_id: Carrier to check posture against.
            posture_data: Per-control-domain coverage percentages (0.0–1.0).

        Returns:
            Dict mapping requirement_id to True (met) or False (not met).
        """
        requirements = await self.get_carrier_requirements(carrier_id)
        fulfillment: dict[str, bool] = {}

        for req in requirements:
            req_id: str = req["requirement_id"]
            required_pct: float = float(req.get("required_coverage_pct") or 0.0)
            control_mappings: list[str] = req.get("control_mappings") or []

            if not control_mappings:
                # No control mappings means the requirement cannot be auto-evaluated
                fulfillment[req_id] = False
                continue

            # A requirement is met if ALL mapped controls meet the threshold
            all_met = all(
                posture_data.get(ctrl, 0.0) >= required_pct
                for ctrl in control_mappings
            )
            fulfillment[req_id] = all_met

        logger.debug(
            "Carrier posture check complete",
            carrier_id=carrier_id,
            total_requirements=len(requirements),
            met_count=sum(1 for v in fulfillment.values() if v),
        )
        return fulfillment
