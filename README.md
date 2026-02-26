# aumos-cyber-insurance

**AumOS Enterprise — Cyber Insurance Posture Mapping**

Maps organizational cyber posture against insurance carrier requirements, quantifies financial risk exposure, optimizes premiums via synthetic data simulation, and generates carrier-ready evidence packages.

## Capabilities

| Service | Description |
|---------|-------------|
| `PostureMapperService` | Assess posture against carrier requirements; score control coverage; identify gaps |
| `ImpactAnalyzerService` | Per-platform ALE, breach probability, coverage gap, and carrier premium delta |
| `PremiumOptimizerService` | Monte Carlo optimization — prioritized controls for maximum premium reduction |
| `EvidencePackagerService` | Assemble carrier-specific evidence packages with expiry tracking |
| `RiskCalculatorService` | FAIR-methodology risk reduction quantification with before/after ALE |

## API Endpoints

```
POST   /api/v1/insurance/posture/assess         Assess insurance posture
GET    /api/v1/insurance/posture/status          Current posture status
POST   /api/v1/insurance/impact/analyze          Per-platform impact analysis
GET    /api/v1/insurance/impact/reports          Impact reports list
POST   /api/v1/insurance/premium/optimize        Premium optimization recommendations
GET    /api/v1/insurance/evidence/package        Generate evidence package
POST   /api/v1/insurance/risk/calculate          Calculate risk reduction (FAIR)
GET    /api/v1/insurance/carriers                Carrier requirements catalogue
```

## Quick Start

```bash
git clone <repo-url> && cd aumos-cyber-insurance
cp .env.example .env
make docker-up
make install
make dev
```

Open http://localhost:8000/docs for the interactive API documentation.

## Supported Carriers

- Coalition Cyber Insurance (MFA, EDR, Backups)
- Hiscox Cyber Protect (MFA, Patch Management)
- Chubb Cyber Enterprise (MFA, IR Plan, Network Segmentation)

The carrier catalogue is pluggable — replace `StubCarrierAdapter` with a real implementation for production.

## Database Tables

| Table | Description |
|-------|-------------|
| `cin_posture_assessments` | Insurance posture assessment records |
| `cin_impact_analyses` | Per-platform insurance impact analyses |
| `cin_premium_recommendations` | Premium optimization recommendations |
| `cin_evidence_packages` | Generated evidence packages for carriers |
| `cin_risk_calculations` | Quantified risk reduction calculations |

## Configuration

All settings use the `AUMOS_INSURANCE_` environment variable prefix. See `.env.example` for the full list.

Key settings:
- `AUMOS_INSURANCE_PREMIUM_DISCOUNT_CAP_PCT` — maximum achievable premium discount (default: 35%)
- `AUMOS_INSURANCE_EVIDENCE_PACKAGE_EXPIRY_DAYS` — days before evidence package expires (default: 90)
- `AUMOS_INSURANCE_OPTIMIZATION_SAMPLE_SIZE` — Monte Carlo sample size (default: 10,000)

## Development

```bash
make lint          # ruff lint + format check
make typecheck     # mypy strict mode
make test          # pytest
make test-cov      # pytest with coverage report
make migrate       # apply Alembic migrations
```

## License

Apache 2.0 — see [LICENSE](LICENSE).
