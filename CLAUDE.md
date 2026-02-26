# CLAUDE.md — AumOS Cyber Insurance

## Project Overview

AumOS Enterprise is a composable enterprise AI platform with 9 products + 2 services
across 62+ repositories. This repo (`aumos-cyber-insurance`) is part of **Tier C Innovations**:
Cyber insurance posture mapping — carrier requirement mapping, per-platform impact analysis,
premium optimization via synthetic data simulation, evidence packages for carriers, and risk
quantification using the FAIR methodology.

**Release Tier:** C: Innovations
**Port:** 8000
**Package:** `aumos_cyber_insurance`
**Table Prefix:** `cin_`
**Env Prefix:** `AUMOS_INSURANCE_`
**License:** Apache 2.0

## Repo Purpose

Maps organizational cyber posture against insurance carrier requirements to:
1. Identify which controls are missing for each carrier
2. Quantify financial impact of coverage gaps per platform
3. Optimize premiums using Monte Carlo simulation over synthetic breach data
4. Generate submission-ready evidence packages for each carrier
5. Calculate quantified risk reduction (FAIR methodology) from control investments

## Architecture Position

```
aumos-tabular-engine  → synthetic breach scenario data for Monte Carlo
aumos-llm-serving     → risk model inference for scoring
aumos-common          → auth, database, events, errors, config, health
aumos-proto           → Protobuf event definitions

aumos-cyber-insurance → standalone service, no downstream repo dependencies
                      → Kafka: insurance.posture.assessed
                               insurance.impact.analyzed
                               insurance.premium.optimized
                               insurance.evidence.packaged
                               insurance.risk.calculated
```

**Upstream dependencies (this repo IMPORTS from):**
- `aumos-common` — auth, database, events, errors, config, health, pagination
- `aumos-proto` — Protobuf message definitions for Kafka events

## Tech Stack (DO NOT DEVIATE)

| Component | Version | Purpose |
|-----------|---------|---------|
| Python | 3.11+ | Runtime |
| FastAPI | 0.110+ | REST API framework |
| SQLAlchemy | 2.0+ (async) | Database ORM |
| asyncpg | 0.29+ | PostgreSQL async driver |
| Pydantic | 2.6+ | Data validation, settings, API schemas |
| Alembic | 1.13+ | Database migrations |
| confluent-kafka | 2.3+ | Kafka event publishing via aumos-common |
| structlog | 24.1+ | Structured JSON logging |
| OpenTelemetry | 1.23+ | Distributed tracing |
| pytest | 8.0+ | Testing framework |
| ruff | 0.3+ | Linting and formatting |
| mypy | 1.8+ | Type checking |

## Coding Standards

### ABSOLUTE RULES (violations will break integration with other repos)

1. **Import aumos-common, never reimplement.**
   ```python
   from aumos_common.auth import get_current_tenant, get_current_user
   from aumos_common.database import get_db_session, Base, AumOSModel, BaseRepository
   from aumos_common.events import EventPublisher, Topics
   from aumos_common.errors import NotFoundError, ConflictError, ErrorCode
   from aumos_common.config import AumOSSettings
   from aumos_common.health import create_health_router
   from aumos_common.app import create_app
   ```

2. **Type hints on EVERY function.** No exceptions.

3. **Pydantic models for ALL API inputs/outputs.** Never return raw dicts.

4. **RLS tenant isolation via aumos-common.** Never write raw SQL that bypasses RLS.

5. **Structured logging via structlog.** Never use print() or logging.getLogger().

6. **Publish domain events to Kafka after all state changes.**

7. **Async by default.** All I/O operations must be async.

8. **Google-style docstrings** on all public classes and functions.

### Domain Rules

- **PostureAssessment must be completed** before downstream services (ImpactAnalyzer,
  PremiumOptimizer, EvidencePackager, RiskCalculator) can operate on it.

- **Premium discount cap**: Discount is hard-capped at `Settings.premium_discount_cap_pct`
  (default 35%). This cap reflects realistic carrier discount limits.

- **Evidence package isolation**: Each EvidencePackage is scoped to exactly one carrier.
  Never share or merge packages across carriers.

- **Evidence expiry**: Packages expire after `Settings.evidence_package_expiry_days` (default 90).
  Expired packages must be regenerated before submission.

- **FAIR methodology default**: Risk calculations default to the FAIR methodology.
  Custom methodologies are allowed but must be documented in `calculation_metadata`.

- **Carrier adapter is pluggable**: The `StubCarrierAdapter` is for dev/test only.
  In production, replace it with a real implementation that calls carrier APIs or
  a managed carrier requirements data store.

### File Structure Convention

```
src/aumos_cyber_insurance/
├── __init__.py
├── main.py                       # FastAPI app entry point using create_app()
├── settings.py                   # Extends AumOSSettings with AUMOS_INSURANCE_ prefix
├── _stub_carrier_adapter.py      # Dev/test stub — replace in production
├── api/                          # FastAPI routes (thin layer — delegates to services)
│   ├── __init__.py
│   ├── router.py                 # All 8 endpoints
│   └── schemas.py                # Pydantic request/response models
├── core/                         # Business logic (no framework dependencies)
│   ├── __init__.py
│   ├── models.py                 # SQLAlchemy ORM models (cin_ prefix)
│   ├── interfaces.py             # Protocol classes for dependency injection
│   └── services.py               # 5 domain services
├── adapters/                     # External integrations
│   ├── __init__.py
│   ├── repositories.py           # SQLAlchemy repositories (extend BaseRepository)
│   └── kafka.py                  # Insurance event publishing
└── migrations/                   # Alembic migrations
    ├── env.py
    ├── alembic.ini
    └── versions/
        └── 20240101_000000_cin_initial_schema.py
tests/
├── __init__.py
├── conftest.py
├── test_services.py
└── (test_api.py — add when integration testing)
```

## API Conventions

- All endpoints under `/api/v1/insurance/` prefix
- Auth: Bearer JWT token (validated by aumos-auth-gateway)
- Tenant: `X-Tenant-ID` header (set by auth middleware)
- Request ID: `X-Request-ID` header (auto-generated if missing)
- Errors: Standard `ErrorResponse` from aumos-common
- Content-Type: `application/json` (always)

## Database Conventions

- Table prefix: `cin_` (e.g., `cin_posture_assessments`, `cin_evidence_packages`)
- ALL tenant-scoped tables: extend `AumOSModel` (gets id, tenant_id, created_at, updated_at)
- RLS policy on every tenant table (created in migration)
- Migration naming: `{timestamp}_cin_{description}.py`
- Foreign keys to other repos' tables: use UUID type, no FK constraints (cross-service)

## Kafka Topics

- `insurance.posture.assessed` — PostureAssessment completed
- `insurance.impact.analyzed` — ImpactAnalysis completed
- `insurance.premium.optimized` — PremiumRecommendation generated
- `insurance.evidence.packaged` — EvidencePackage ready
- `insurance.risk.calculated` — RiskCalculation completed

## Environment Variables

All standard env vars: `aumos_common.config.AumOSSettings`.
Repo-specific vars use `AUMOS_INSURANCE_` prefix.

Key variables:
- `AUMOS_INSURANCE_PREMIUM_DISCOUNT_CAP_PCT` — cap on achievable discount (default: 35.0)
- `AUMOS_INSURANCE_EVIDENCE_PACKAGE_EXPIRY_DAYS` — package validity period (default: 90)
- `AUMOS_INSURANCE_OPTIMIZATION_SAMPLE_SIZE` — Monte Carlo sample count (default: 10000)
- `AUMOS_INSURANCE_SYNTHETIC_DATA_URL` — aumos-tabular-engine base URL
- `AUMOS_INSURANCE_RISK_SCORE_MODEL_URL` — aumos-llm-serving base URL

## What Claude Code Should NOT Do

1. **Do NOT reimplement anything in aumos-common.**
2. **Do NOT use print().** Use `get_logger(__name__)`.
3. **Do NOT return raw dicts from API endpoints.** Use Pydantic models.
4. **Do NOT write raw SQL.** Use SQLAlchemy ORM with BaseRepository.
5. **Do NOT hardcode configuration.** Use Pydantic Settings with env vars.
6. **Do NOT skip type hints.** Every function signature must be typed.
7. **Do NOT put business logic in API routes.** Routes call services.
8. **Do NOT run downstream analysis on a non-completed PostureAssessment.**
   Always check `assessment.status == "completed"` before proceeding.
9. **Do NOT share EvidencePackages across carriers.**
10. **Do NOT exceed the premium discount cap.** Always apply `min(discount, cap)`.
