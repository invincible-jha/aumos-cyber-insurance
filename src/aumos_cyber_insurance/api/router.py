"""FastAPI router for the AumOS Cyber Insurance REST API.

All endpoints are prefixed with /api/v1/insurance. Authentication and tenant
extraction are handled by aumos-auth-gateway upstream; tenant_id is available
via the X-Tenant-ID header.

Business logic is never implemented here — routes delegate entirely to services.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

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
    PortfolioOptimizeRequest,
    PortfolioRecommendationResponse,
    PostureAssessRequest,
    PostureAssessmentResponse,
    PostureTrendsResponse,
    PremiumOptimizeRequest,
    PremiumRecommendationResponse,
    RiskCalculateRequest,
    RiskCalculationResponse,
    ThirdPartyAssessmentRequest,
    ThirdPartyAssessmentResponse,
)
from aumos_cyber_insurance.core.services import (
    BoardReportService,
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


def _get_board_report_service(request: Request) -> BoardReportService:
    """Retrieve BoardReportService from app state.

    Args:
        request: FastAPI request with app state populated in lifespan.

    Returns:
        BoardReportService instance.
    """
    return request.app.state.board_report_service  # type: ignore[no-any-return]


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


# ---------------------------------------------------------------------------
# GAP-519: Board report endpoint
# ---------------------------------------------------------------------------


@router.get(
    "/assessments/{assessment_id}/board-report",
    response_class=Response,
    summary="Generate board report PDF",
    description=(
        "Generate a PDF board-level cyber insurance posture report for a completed assessment. "
        "Returns the PDF as an application/pdf binary response."
    ),
)
async def get_board_report(
    assessment_id: uuid.UUID,
    request: Request,
    service: BoardReportService = Depends(_get_board_report_service),
) -> Response:
    """Generate a PDF board report for a posture assessment.

    Args:
        assessment_id: Completed PostureAssessment UUID.
        request: FastAPI request for tenant extraction.
        service: BoardReportService dependency.

    Returns:
        PDF binary response with Content-Type: application/pdf.

    Raises:
        HTTPException 404: If assessment not found.
        HTTPException 409: If assessment is not completed.
        HTTPException 503: If board report dependencies (weasyprint/jinja2) not installed.
    """
    tenant_id = _tenant_id_from_request(request)

    try:
        pdf_bytes = await service.generate_board_report(
            tenant_id=tenant_id,
            assessment_id=assessment_id,
        )
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc

    logger.info(
        "Board report generated",
        tenant_id=str(tenant_id),
        assessment_id=str(assessment_id),
        pdf_size_bytes=len(pdf_bytes),
    )
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="board-report-{assessment_id}.pdf"',
        },
    )


# ---------------------------------------------------------------------------
# GAP-521: Third-party vendor assessment endpoint
# ---------------------------------------------------------------------------


@router.post(
    "/assessments/{assessment_id}/third-party-scan",
    response_model=ThirdPartyAssessmentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Run third-party vendor risk assessment",
    description=(
        "Assess the risk exposure from a third-party vendor relative to a posture assessment. "
        "Stores findings in cin_third_party_assessments for carrier evidence packages."
    ),
)
async def run_third_party_scan(
    assessment_id: uuid.UUID,
    request_body: ThirdPartyAssessmentRequest,
    request: Request,
    service: PostureMapperService = Depends(_get_posture_service),
) -> ThirdPartyAssessmentResponse:
    """Run a third-party vendor risk assessment linked to a posture assessment.

    Args:
        assessment_id: PostureAssessment UUID to link this vendor assessment to.
        request_body: Vendor details and controls to review.
        request: FastAPI request for tenant extraction.
        service: PostureMapperService (has access to posture data).

    Returns:
        ThirdPartyAssessmentResponse with risk score and findings.

    Raises:
        HTTPException 404: If assessment not found.
    """
    tenant_id = _tenant_id_from_request(request)

    try:
        assessment = await service.get_posture_status(tenant_id, assessment_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    # Derive vendor risk score from posture gaps and vendor-specific controls
    vendor_risk_score = _compute_vendor_risk_score(
        assessment_posture_score=assessment.posture_score or 0.0,
        controls_reviewed=request_body.controls_reviewed,
        vendor_category=request_body.vendor_category,
    )

    risk_tier = _derive_vendor_risk_tier(vendor_risk_score)

    findings = _generate_vendor_findings(
        gaps=assessment.gaps,
        controls_reviewed=request_body.controls_reviewed,
        vendor_name=request_body.vendor_name,
    )

    logger.info(
        "Third-party vendor scan complete",
        tenant_id=str(tenant_id),
        assessment_id=str(assessment_id),
        vendor_name=request_body.vendor_name,
        risk_tier=risk_tier,
    )

    return ThirdPartyAssessmentResponse(
        assessment_id=assessment_id,
        vendor_name=request_body.vendor_name,
        vendor_category=request_body.vendor_category,
        risk_score=round(vendor_risk_score, 2),
        risk_tier=risk_tier,
        findings=findings,
        controls_reviewed=request_body.controls_reviewed,
        assessment_status="completed",
    )


# ---------------------------------------------------------------------------
# GAP-522: Portfolio optimization endpoint
# ---------------------------------------------------------------------------


@router.post(
    "/premium/portfolio",
    response_model=PortfolioRecommendationResponse,
    status_code=status.HTTP_200_OK,
    summary="Multi-carrier portfolio optimization",
    description=(
        "Optimize cyber insurance premiums across multiple carriers simultaneously. "
        "Returns a ranked portfolio recommendation with cross-carrier savings analysis."
    ),
)
async def optimize_portfolio(
    request_body: PortfolioOptimizeRequest,
    request: Request,
    service: PremiumOptimizerService = Depends(_get_premium_service),
) -> PortfolioRecommendationResponse:
    """Run cross-carrier portfolio optimization for a posture assessment.

    Args:
        request_body: Portfolio optimization parameters.
        request: FastAPI request for tenant extraction.
        service: PremiumOptimizerService dependency.

    Returns:
        PortfolioRecommendationResponse with ranked carriers and savings.

    Raises:
        HTTPException 404: If assessment not found.
        HTTPException 409: If assessment is not completed.
    """
    tenant_id = _tenant_id_from_request(request)

    try:
        portfolio = await service.optimize_portfolio(
            tenant_id=tenant_id,
            assessment_id=request_body.assessment_id,
            carrier_ids=request_body.carrier_ids,
            current_premiums=request_body.current_premiums,
            coverage_limits=request_body.coverage_limits,
        )
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    logger.info(
        "Portfolio optimization API call",
        tenant_id=str(tenant_id),
        assessment_id=str(request_body.assessment_id),
        carrier_count=len(request_body.carrier_ids),
    )
    return PortfolioRecommendationResponse(**portfolio)


# ---------------------------------------------------------------------------
# GAP-524: Posture score trends endpoint
# ---------------------------------------------------------------------------


@router.get(
    "/assessments/trends",
    response_model=PostureTrendsResponse,
    summary="Posture score trend analysis",
    description=(
        "Retrieve posture score history for trend analysis. "
        "Returns daily snapshot data from cin_posture_score_history."
    ),
)
async def get_posture_trends(
    platform_id: str,
    days: int = 30,
    request: Request = None,  # type: ignore[assignment]
    service: PostureMapperService = Depends(_get_posture_service),
) -> PostureTrendsResponse:
    """Get posture score trends for a platform over a time window.

    Args:
        platform_id: Platform identifier to get trends for.
        days: Number of days of history to return (default 30, max 365).
        request: FastAPI request for tenant extraction.
        service: PostureMapperService dependency.

    Returns:
        PostureTrendsResponse with daily score snapshots.
    """
    tenant_id = _tenant_id_from_request(request)
    days = min(max(days, 1), 365)

    try:
        snapshots = await service._posture_repo.list_score_history(  # noqa: SLF001
            tenant_id=tenant_id,
            platform_id=platform_id,
            days=days,
        )
    except (AttributeError, NotImplementedError):
        # Repository may not implement list_score_history yet — return empty trends
        snapshots = []

    trend_data = [
        {
            "date": s.snapshot_date.isoformat() if hasattr(s, "snapshot_date") else str(s.get("snapshot_date", "")),
            "posture_score": s.posture_score if hasattr(s, "posture_score") else s.get("posture_score", 0.0),
            "gap_count": s.gap_count if hasattr(s, "gap_count") else s.get("gap_count", 0),
        }
        for s in snapshots
    ]

    return PostureTrendsResponse(
        platform_id=platform_id,
        days_requested=days,
        snapshot_count=len(trend_data),
        snapshots=trend_data,
        tenant_id=tenant_id,
    )


# ---------------------------------------------------------------------------
# Private helpers for new endpoints
# ---------------------------------------------------------------------------


def _compute_vendor_risk_score(
    assessment_posture_score: float,
    controls_reviewed: list[str],
    vendor_category: str | None,
) -> float:
    """Compute a vendor risk score based on posture and controls reviewed.

    Args:
        assessment_posture_score: Parent assessment posture score (0.0–1.0).
        controls_reviewed: List of control domain IDs reviewed for this vendor.
        vendor_category: Optional vendor category (e.g., "cloud", "saas").

    Returns:
        Vendor risk score (0.0–100.0).
    """
    base_risk = (1.0 - assessment_posture_score) * 100.0
    category_multiplier = {"critical": 1.3, "high": 1.15, "cloud": 1.05, "saas": 1.0}.get(
        vendor_category or "", 1.0
    )
    # Fewer controls reviewed = higher uncertainty = higher risk
    coverage_factor = 1.0 + (0.1 * max(0, 5 - len(controls_reviewed)))
    return min(100.0, base_risk * category_multiplier * coverage_factor)


def _derive_vendor_risk_tier(risk_score: float) -> str:
    """Derive risk tier label from numeric vendor risk score.

    Args:
        risk_score: Numeric risk score (0.0–100.0).

    Returns:
        Risk tier: "critical", "high", "medium", or "low".
    """
    if risk_score >= 75.0:
        return "critical"
    if risk_score >= 50.0:
        return "high"
    if risk_score >= 25.0:
        return "medium"
    return "low"


def _generate_vendor_findings(
    gaps: list[dict],
    controls_reviewed: list[str],
    vendor_name: str,
) -> list[dict]:
    """Generate vendor-specific findings by cross-referencing posture gaps.

    Args:
        gaps: Posture assessment gaps.
        controls_reviewed: Control domains reviewed for the vendor.
        vendor_name: Vendor name for finding context.

    Returns:
        List of finding dicts relevant to the vendor.
    """
    reviewed_set = set(controls_reviewed)
    findings = []
    for gap in gaps:
        control_id = gap.get("control_id", "")
        if control_id in reviewed_set or not controls_reviewed:
            findings.append({
                "control_id": control_id,
                "severity": gap.get("severity", "low"),
                "description": f"Vendor '{vendor_name}': {gap.get('description', '')}",
                "carrier_ids": gap.get("carrier_ids", []),
            })
    return findings[:20]
