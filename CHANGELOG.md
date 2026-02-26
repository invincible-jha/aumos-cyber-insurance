# Changelog

All notable changes to `aumos-cyber-insurance` will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] - 2024-01-01

### Added
- `PostureMapperService` — carrier requirement mapping and posture scoring
- `ImpactAnalyzerService` — per-platform financial impact analysis (ALE, breach probability, coverage gap)
- `PremiumOptimizerService` — premium optimization recommendations via Monte Carlo simulation
- `EvidencePackagerService` — carrier-specific evidence package generation
- `RiskCalculatorService` — FAIR-methodology risk reduction quantification
- REST API: 8 endpoints covering posture, impact, premium, evidence, risk, and carrier management
- PostgreSQL persistence with `cin_` table prefix and RLS tenant isolation
- Kafka event publishing for all domain state changes
- Initial Alembic migration for all 5 database tables
- Stub carrier adapter with Coalition, Hiscox, and Chubb requirement data
- Docker + docker-compose development environment
