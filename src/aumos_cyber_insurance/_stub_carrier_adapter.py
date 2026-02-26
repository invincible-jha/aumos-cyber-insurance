"""Stub carrier adapter for development and testing.

In production this is replaced by a concrete adapter that calls
external carrier requirement APIs or a cached carrier requirements
data store.
"""

from typing import Any

from aumos_common.observability import get_logger

logger = get_logger(__name__)

# Hardcoded carrier catalogue for development — replace with real data source
_CARRIERS: list[dict[str, Any]] = [
    {
        "carrier_id": "coalition",
        "name": "Coalition Cyber Insurance",
        "coverage_types": ["first_party", "third_party", "e&o", "crime"],
        "requirements": [
            {
                "requirement_id": "coal-mfa-001",
                "name": "Multi-Factor Authentication",
                "description": "MFA required for all admin and remote access",
                "category": "access_control",
                "severity": "high",
                "control_mappings": ["mfa", "privileged_access"],
            },
            {
                "requirement_id": "coal-edr-001",
                "name": "Endpoint Detection and Response",
                "description": "EDR deployed on all managed endpoints",
                "category": "endpoint_security",
                "severity": "high",
                "control_mappings": ["endpoint_detection", "antivirus"],
            },
            {
                "requirement_id": "coal-bak-001",
                "name": "Offline Backups",
                "description": "Encrypted offline or immutable backups with tested recovery",
                "category": "resilience",
                "severity": "high",
                "control_mappings": ["backup_recovery", "disaster_recovery"],
            },
        ],
        "metadata": {"min_coverage_usd": 1_000_000, "max_coverage_usd": 15_000_000},
    },
    {
        "carrier_id": "hiscox",
        "name": "Hiscox Cyber Protect",
        "coverage_types": ["first_party", "third_party", "regulatory"],
        "requirements": [
            {
                "requirement_id": "hisc-mfa-001",
                "name": "Multi-Factor Authentication (Email & Admin)",
                "description": "MFA mandatory for email and all administrative access",
                "category": "access_control",
                "severity": "high",
                "control_mappings": ["mfa"],
            },
            {
                "requirement_id": "hisc-patch-001",
                "name": "Patch Management",
                "description": "Critical patches applied within 30 days of release",
                "category": "vulnerability_management",
                "severity": "medium",
                "control_mappings": ["patch_management", "vulnerability_scanning"],
            },
        ],
        "metadata": {"min_coverage_usd": 500_000, "max_coverage_usd": 10_000_000},
    },
    {
        "carrier_id": "chubb",
        "name": "Chubb Cyber Enterprise",
        "coverage_types": ["first_party", "third_party", "e&o", "crime", "bodily_injury"],
        "requirements": [
            {
                "requirement_id": "chub-mfa-001",
                "name": "MFA — All Critical Systems",
                "description": "MFA across all critical systems and cloud admin consoles",
                "category": "access_control",
                "severity": "high",
                "control_mappings": ["mfa", "cloud_security", "privileged_access"],
            },
            {
                "requirement_id": "chub-ir-001",
                "name": "Incident Response Plan",
                "description": "Documented and tested IR plan with defined escalation paths",
                "category": "incident_response",
                "severity": "high",
                "control_mappings": ["incident_response", "business_continuity"],
            },
            {
                "requirement_id": "chub-seg-001",
                "name": "Network Segmentation",
                "description": "OT/IT segmentation and micro-segmentation for critical assets",
                "category": "network_security",
                "severity": "medium",
                "control_mappings": ["network_segmentation", "firewall"],
            },
        ],
        "metadata": {"min_coverage_usd": 2_000_000, "max_coverage_usd": 50_000_000},
    },
]

# Map control_mappings to required coverage thresholds (0.0–1.0)
_CONTROL_THRESHOLDS: dict[str, float] = {
    "mfa": 0.80,
    "endpoint_detection": 0.70,
    "backup_recovery": 0.75,
    "disaster_recovery": 0.60,
    "patch_management": 0.80,
    "vulnerability_scanning": 0.70,
    "incident_response": 0.65,
    "business_continuity": 0.60,
    "network_segmentation": 0.55,
    "firewall": 0.75,
    "cloud_security": 0.70,
    "privileged_access": 0.80,
    "antivirus": 0.85,
}


class StubCarrierAdapter:
    """Stub implementation of ICarrierAdapter for development and tests.

    Returns hardcoded carrier data. Replace with a real implementation
    in production that pulls from carrier APIs or a managed data store.
    """

    async def list_carriers(self) -> list[dict[str, Any]]:
        """Return the list of supported insurance carriers.

        Returns:
            List of carrier metadata dicts.
        """
        return _CARRIERS

    async def get_carrier_requirements(self, carrier_id: str) -> dict[str, Any]:
        """Return requirements for a specific carrier.

        Args:
            carrier_id: Carrier identifier.

        Returns:
            Carrier requirements dict keyed by requirement_id.
        """
        for carrier in _CARRIERS:
            if carrier["carrier_id"] == carrier_id:
                return {
                    req["requirement_id"]: req
                    for req in carrier.get("requirements", [])
                }
        return {}

    async def check_posture_against_carrier(
        self,
        carrier_id: str,
        posture_data: dict[str, Any],
    ) -> dict[str, Any]:
        """Evaluate posture data against carrier requirements.

        Args:
            carrier_id: Target carrier identifier.
            posture_data: Current posture control coverage dict {domain: coverage_pct}.

        Returns:
            Requirement fulfillment map: {requirement_id: bool}.
        """
        requirements = await self.get_carrier_requirements(carrier_id)
        fulfillment: dict[str, Any] = {}

        for req_id, req in requirements.items():
            mappings: list[str] = req.get("control_mappings", [])
            if not mappings:
                fulfillment[req_id] = True
                continue

            # Requirement is met if ALL mapped controls meet their threshold
            is_met = all(
                posture_data.get(mapping, 0.0) >= _CONTROL_THRESHOLDS.get(mapping, 0.75)
                for mapping in mappings
            )
            fulfillment[req_id] = is_met

        return fulfillment
