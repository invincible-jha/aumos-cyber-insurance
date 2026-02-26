"""Cyber Insurance service settings extending AumOS base configuration."""

from pydantic import Field
from pydantic_settings import SettingsConfigDict

from aumos_common.config import AumOSSettings


class Settings(AumOSSettings):
    """Configuration for the AumOS Cyber Insurance service.

    Extends base AumOS settings with cyber-insurance-specific configuration
    for carrier integrations, risk scoring, and premium optimization.

    All settings use the AUMOS_INSURANCE_ environment variable prefix.
    """

    service_name: str = "aumos-cyber-insurance"

    # ---------------------------------------------------------------------------
    # Risk scoring
    # ---------------------------------------------------------------------------
    risk_score_model_url: str = Field(
        default="http://localhost:8030",
        description="Base URL for the risk scoring model service (aumos-llm-serving)",
    )
    risk_model_timeout_seconds: float = Field(
        default=30.0,
        description="Timeout in seconds for risk model inference calls",
    )
    risk_score_cache_ttl_seconds: int = Field(
        default=3600,
        description="TTL in seconds for cached risk assessment results",
    )

    # ---------------------------------------------------------------------------
    # Premium optimization
    # ---------------------------------------------------------------------------
    synthetic_data_url: str = Field(
        default="http://localhost:8003",
        description="Base URL for aumos-tabular-engine synthetic data generation",
    )
    optimization_sample_size: int = Field(
        default=10_000,
        description="Number of synthetic records to generate per premium optimization run",
    )
    premium_discount_cap_pct: float = Field(
        default=35.0,
        description="Maximum premium discount percentage achievable via posture improvements",
    )

    # ---------------------------------------------------------------------------
    # Evidence packaging
    # ---------------------------------------------------------------------------
    evidence_package_expiry_days: int = Field(
        default=90,
        description="Days before a generated evidence package expires and must be refreshed",
    )
    evidence_storage_bucket: str = Field(
        default="aumos-cyber-insurance-evidence",
        description="Object storage bucket name for evidence package artifacts",
    )

    # ---------------------------------------------------------------------------
    # Carrier integration
    # ---------------------------------------------------------------------------
    carrier_api_timeout_seconds: float = Field(
        default=15.0,
        description="Timeout in seconds for outbound carrier requirement API calls",
    )
    carrier_data_refresh_hours: int = Field(
        default=24,
        description="Hours between refreshes of carrier requirement data from upstream sources",
    )

    # ---------------------------------------------------------------------------
    # HTTP client settings
    # ---------------------------------------------------------------------------
    http_timeout: float = Field(
        default=30.0,
        description="Timeout in seconds for HTTP calls to downstream services",
    )
    http_max_retries: int = Field(
        default=3,
        description="Maximum retry attempts for HTTP calls to upstream services",
    )

    model_config = SettingsConfigDict(env_prefix="AUMOS_INSURANCE_")
