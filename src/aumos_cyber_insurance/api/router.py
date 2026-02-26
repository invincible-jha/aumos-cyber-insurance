"""FastAPI router for the AumOS Cyber Insurance REST API.

All endpoints are prefixed with /api/v1/insurance. Authentication and tenant
extraction are handled by aumos-auth-gateway upstream; tenant_id is available
via the X-Tenant-ID header.

Business logic is never implemented here — routes delegate entirely to services.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status

from aumos_common.errors import ConflictError, NotFoundError
from aumos_common.observability import get_logger

from aumos_cyber_insurance.api.schemas import (
    CarrierListResponse,
    CarrierRequirementItem,
    CarrierResponse,
    EvidencePackageRequest,
    EvidencePackageResponse,
    ImpactAnalyzeRequest,
    ImpactAnalysisListResponse,
    ImpactAnalysisResponse,
    PostureAssessRequest,
    PostureAssessmentResponse,
    PremiumOptimizeRequest,
    PremiumRecommendationResponse,
    RiskCalculateRequest,
    RiskCalculationResponse,
)
from aumos_cyber_insurance.core.services import (
    EvidencePackagerService,
    ImpactAnalyzerService,
    PostureMapperService,
    PremiumOptimizerService,
    RiskCalculatorService,
)

logger = get_logger(__name__)

router = APIRouter(tags=["cyber-insurance"])


# ---------------------------------------------------------------------------
# Dependency helpers — replaced by real DI populated in lifespan
# ---------------------------------------------------------------------------


def _get_posture_service(request: Request) -> PostureMapperService:
    """Retrieve PostureMapperService from app state.

    Args:
        request: FastAPI request with app state populated in lifespan.

    Returns:
        PostureMapperService instance.
    """
    return request.app.state.posture_service  # type: ignore[no-any-return]


def _get_impact_service(request: Request) -> ImpactAnalyzerService:
    """Retrieve ImpactAnalyzerService from app state.

    Args:
        request: FastAPI request with app state populated in lifespan.

    Returns:
        ImpactAnalyzerService instance.
    """
    return request.app.state.impact_service  # type: ignore[no-any-return]


def _get_premium_service(request: Request) -> PremiumOptimizerService:
    """Retrieve PremiumOptimizerService from app state.

    Args:
        request: FastAPI request with app state populated in lifespan.

    Returns:
        PremiumOptimizerService instance.
    """
    return request.app.state.premium_service  # type: ignore[no-any-return]


def _get_evidence_service(request: Request) -> EvidencePackagerService:
    """Retrieve EvidencePackagerService from app state.

    Args:
        request: FastAPI request with app state populated in lifespan.

    Returns:
        EvidencePackagerService instance.
    """
    return request.app.state.evidence_service  # type: ignore[no-any-return]


def _get_risk_service(request: Request) -> RiskCalculatorService:
    """Retrieve RiskCalculatorService from app state.

    Args:
        request: FastAPI request with app state populated in lifespan.

    Returns:
        RiskCalculatorService instance.
    """
    return request.app.state.risk_service  # type: ignore[no-any-return]


def _tenant_id_from_request(request: Request) -> uuid.UUID:
    """Extract tenant UUID from request headers (set by auth middleware).

    Falls back to a random UUID in development mode.

    Args:
        request: Incoming FastAPI request.

    Returns:
        Tenant UUID.
    """
    tenant_header = request.headers.get("X-Tenant-ID")
    if tenant_header:
        return uuid.UUID(tenant_header)
    return uuid.uuid4()


# ---------------------------------------------------------------------------
# Posture endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/posture/assess",
    response_model=PostureAssessmentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Assess insurance posture",
    description=(
        "Run a full cyber insurance posture assessment against carrier requirements. "
        "Evaluates control coverage, identifies gaps, and scores the current posture."
    ),
)
async def assess_posture(
    request_body: PostureAssessRequest,
    request: Request,
    service: PostureMapperService = Depends(_get_posture_service),
) -> PostureAssessmentResponse:
    """Assess insurance posture against carrier requirements.

    Args:
        request_body: Posture assessment parameters.
        request: FastAPI request for tenant extraction.
        service: PostureMapperService dependency.

    Returns:
        PostureAssessmentResponse with score, gaps, and carrier fulfillment map.

    Raises:
        HTTPException 400: If platform_type is invalid.
    """
    tenant_id = _tenant_id_from_request(request)

    try:
        assessment = await service.assess_posture(
            tenant_id=tenant_id,
            platform_id=request_body.platform_id,
            platform_type=request_body.platform_type,
            carrier_id=request_body.carrier_id,
            control_coverage=request_body.control_coverage,
            requested_by=None,
            assessment_metadata=request_body.assessment_metadata,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    logger.info(
        "Posture assessment API call",
        tenant_id=str(tenant_id),
        assessment_id=str(assessment.id),
    )
    return PostureAssessmentResponse.model_validate(assessment)


@router.get(
    "/posture/status",
    response_model=PostureAssessmentResponse,
    summary="Current posture status",
    description="Retrieve the current posture assessment status by assessment ID.",
)
async def get_posture_status(
    assessment_id: uuid.UUID,
    request: Request,
    service: PostureMapperService = Depends(_get_posture_service),
) -> PostureAssessmentResponse:
    """Get the current posture assessment status.

    Args:
        assessment_id: PostureAssessment UUID to retrieve.
        request: FastAPI request for tenant extraction.
        service: PostureMapperService dependency.

    Returns:
        PostureAssessmentResponse with current status.

    Raises:
        HTTPException 404: If assessment not found.
    """
    tenant_id = _tenant_id_from_request(request)

    try:
        assessment = await service.get_posture_status(tenant_id, assessment_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    return PostureAssessmentResponse.model_validate(assessment)


# ---------------------------------------------------------------------------
# Impact analysis endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/impact/analyze",
    response_model=ImpactAnalysisResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Per-platform impact analysis",
    description=(
        "Run a per-platform financial impact analysis from a completed posture assessment. "
        "Computes ALE, breach probability, coverage gap, and per-carrier premium deltas."
    ),
)
async def analyze_impact(
    request_body: ImpactAnalyzeRequest,
    request: Request,
    service: ImpactAnalyzerService = Depends(_get_impact_service),
) -> ImpactAnalysisResponse:
    """Run per-platform insurance impact analysis.

    Args:
        request_body: Impact analysis parameters.
        request: FastAPI request for tenant extraction.
        service: ImpactAnalyzerService dependency.

    Returns:
        ImpactAnalysisResponse with financial metrics.

    Raises:
        HTTPException 404: If assessment not found.
        HTTPException 409: If assessment is not completed.
    """
    tenant_id = _tenant_id_from_request(request)

    try:
        analysis = await service.analyze_impact(
            tenant_id=tenant_id,
            assessment_id=request_body.assessment_id,
            platform_revenue_usd=request_body.platform_revenue_usd,
            existing_coverage_usd=request_body.existing_coverage_usd,
        )
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    return ImpactAnalysisResponse.model_validate(analysis)


@router.get(
    "/impact/reports",
    response_model=ImpactAnalysisListResponse,
    summary="Impact reports",
    description="List all per-platform impact analyses for a given posture assessment.",
)
async def list_impact_reports(
    assessment_id: uuid.UUID,
    request: Request,
    service: ImpactAnalyzerService = Depends(_get_impact_service),
) -> ImpactAnalysisListResponse:
    """List per-platform impact reports for a posture assessment.

    Args:
        assessment_id: PostureAssessment UUID to list analyses for.
        request: FastAPI request for tenant extraction.
        service: ImpactAnalyzerService dependency.

    Returns:
        ImpactAnalysisListResponse with all analyses.
    """
    tenant_id = _tenant_id_from_request(request)
    analyses = await service.list_impact_reports(tenant_id, assessment_id)

    return ImpactAnalysisListResponse(
        items=[ImpactAnalysisResponse.model_validate(a) for a in analyses],
        total=len(analyses),
    )


# ---------------------------------------------------------------------------
# Premium optimization endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/premium/optimize",
    response_model=PremiumRecommendationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Premium optimization recommendations",
    description=(
        "Generate premium optimization recommendations using synthetic data Monte Carlo simulation. "
        "Returns prioritized controls that maximize premium discount for a specific carrier."
    ),
)
async def optimize_premium(
    request_body: PremiumOptimizeRequest,
    request: Request,
    service: PremiumOptimizerService = Depends(_get_premium_service),
) -> PremiumRecommendationResponse:
    """Generate premium optimization recommendations for a carrier.

    Args:
        request_body: Premium optimization parameters.
        request: FastAPI request for tenant extraction.
        service: PremiumOptimizerService dependency.

    Returns:
        PremiumRecommendationResponse with discount and control priorities.

    Raises:
        HTTPException 404: If assessment not found.
        HTTPException 409: If assessment is not completed.
    """
    tenant_id = _tenant_id_from_request(request)

    try:
        recommendation = await service.optimize_premium(
            tenant_id=tenant_id,
            assessment_id=request_body.assessment_id,
            carrier_id=request_body.carrier_id,
            current_premium_usd=request_body.current_premium_usd,
            coverage_limit_usd=request_body.coverage_limit_usd,
        )
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    return PremiumRecommendationResponse.model_validate(recommendation)


# ---------------------------------------------------------------------------
# Evidence package endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/evidence/package",
    response_model=EvidencePackageResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Generate evidence package",
    description=(
        "Generate a carrier-specific evidence package for insurance submission. "
        "Assembles posture attestations, control mappings, and compliance documents."
    ),
)
async def generate_evidence_package(
    assessment_id: uuid.UUID,
    carrier_id: str,
    carrier_name: str,
    request: Request,
    service: EvidencePackagerService = Depends(_get_evidence_service),
) -> EvidencePackageResponse:
    """Generate a carrier-specific evidence package.

    Args:
        assessment_id: PostureAssessment UUID to package evidence for.
        carrier_id: Target carrier identifier.
        carrier_name: Human-readable carrier name.
        request: FastAPI request for tenant extraction.
        service: EvidencePackagerService dependency.

    Returns:
        EvidencePackageResponse with assembled artifacts.

    Raises:
        HTTPException 404: If assessment not found.
        HTTPException 409: If assessment is not completed.
    """
    tenant_id = _tenant_id_from_request(request)

    try:
        package = await service.generate_evidence_package(
            tenant_id=tenant_id,
            assessment_id=assessment_id,
            carrier_id=carrier_id,
            carrier_name=carrier_name,
            package_metadata={},
        )
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    return EvidencePackageResponse.model_validate(package)


# ---------------------------------------------------------------------------
# Risk calculation endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/risk/calculate",
    response_model=RiskCalculationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Calculate risk reduction",
    description=(
        "Quantify risk reduction from implementing recommended controls using the FAIR methodology. "
        "Returns baseline and residual risk scores, ALE figures, and reduction percentage."
    ),
)
async def calculate_risk_reduction(
    request_body: RiskCalculateRequest,
    request: Request,
    service: RiskCalculatorService = Depends(_get_risk_service),
) -> RiskCalculationResponse:
    """Calculate risk reduction from applying recommended controls.

    Args:
        request_body: Risk calculation parameters.
        request: FastAPI request for tenant extraction.
        service: RiskCalculatorService dependency.

    Returns:
        RiskCalculationResponse with quantified risk metrics.

    Raises:
        HTTPException 400: If methodology is invalid.
        HTTPException 404: If assessment not found.
        HTTPException 409: If assessment is not completed.
    """
    tenant_id = _tenant_id_from_request(request)

    try:
        calculation = await service.calculate_risk_reduction(
            tenant_id=tenant_id,
            assessment_id=request_body.assessment_id,
            calculation_type=request_body.calculation_type,
            methodology=request_body.methodology,
            controls_to_apply=request_body.controls_to_apply,
            threat_scenarios=request_body.threat_scenarios,
            asset_value_usd=request_body.asset_value_usd,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    return RiskCalculationResponse.model_validate(calculation)


# ---------------------------------------------------------------------------
# Carrier endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/carriers",
    response_model=CarrierListResponse,
    summary="Insurance carrier requirements",
    description="List all supported cyber insurance carriers and their control requirements.",
)
async def list_carriers(
    request: Request,
    service: PostureMapperService = Depends(_get_posture_service),
) -> CarrierListResponse:
    """List all supported insurance carriers and their requirements.

    Args:
        request: FastAPI request (unused, included for consistency).
        service: PostureMapperService dependency (holds carrier adapter access).

    Returns:
        CarrierListResponse with carrier metadata and requirements.
    """
    carriers_raw = await service._carrier_adapter.list_carriers()  # noqa: SLF001

    carriers = [
        CarrierResponse(
            carrier_id=c["carrier_id"],
            name=c.get("name", c["carrier_id"]),
            coverage_types=c.get("coverage_types", []),
            requirements=[
                CarrierRequirementItem(
                    requirement_id=r.get("requirement_id", ""),
                    name=r.get("name", ""),
                    description=r.get("description", ""),
                    category=r.get("category", ""),
                    severity=r.get("severity", "medium"),
                    control_mappings=r.get("control_mappings", []),
                )
                for r in c.get("requirements", [])
            ],
            metadata=c.get("metadata", {}),
        )
        for c in carriers_raw
    ]

    return CarrierListResponse(items=carriers, total=len(carriers))
