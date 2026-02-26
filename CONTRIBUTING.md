# Contributing to aumos-cyber-insurance

## Development Setup

```bash
git clone <repo-url>
cd aumos-cyber-insurance
python -m venv .venv && source .venv/bin/activate
make install
```

## Running Locally

```bash
cp .env.example .env  # fill in values
make docker-up        # start postgres + kafka
make dev              # start the service with hot reload
```

## Code Standards

- Python 3.11+, type hints on all function signatures
- `ruff` for linting and formatting (`make lint`)
- `mypy` in strict mode (`make typecheck`)
- Google-style docstrings on all public functions and classes
- No `print()` — use `get_logger(__name__)` from aumos-common

## Pull Request Process

1. Branch from `main`: `git checkout -b feature/your-feature`
2. Run `make lint typecheck test` — all must pass
3. Write or update tests alongside implementation
4. Conventional commit messages: `feat:`, `fix:`, `refactor:`, `docs:`, `test:`
5. Squash-merge into `main`

## Domain Rules

- PostureAssessment must be in `completed` status before impact analysis, premium optimization, evidence packaging, or risk calculation can run
- Premium discount is hard-capped at `AUMOS_INSURANCE_PREMIUM_DISCOUNT_CAP_PCT` (default 35%)
- Evidence packages expire after `AUMOS_INSURANCE_EVIDENCE_PACKAGE_EXPIRY_DAYS` days
- Never share evidence packages across carriers — each package is carrier-scoped
- Table prefix: `cin_` — all new tables must use this prefix
- Environment variable prefix: `AUMOS_INSURANCE_`
