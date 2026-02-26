# Security Policy

## Supported Versions

| Version | Supported |
|---------|-----------|
| 0.1.x   | Yes       |

## Reporting a Vulnerability

Report security vulnerabilities to security@aumos.ai. Do NOT create public GitHub issues for security bugs.

We will respond within 48 hours and aim to release a patch within 7 business days.

## Security Controls in this Service

- **Row-Level Security**: All tenant tables have PostgreSQL RLS policies on `tenant_id`.
- **Authentication**: JWT validation is performed by `aumos-auth-gateway` — this service trusts the `X-Tenant-ID` header set by the upstream gateway.
- **Input Validation**: All API inputs are validated by Pydantic models before reaching service logic.
- **No SQL Concatenation**: All database queries use SQLAlchemy ORM parameterized statements.
- **Secrets Management**: No secrets in source code — all configuration via environment variables with `AUMOS_INSURANCE_` prefix.
- **Evidence Isolation**: Evidence packages are carrier-scoped and never shared across carriers.
- **Audit Trail**: All posture assessments, risk calculations, and evidence packages are immutable records once completed.
