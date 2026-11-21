# ADR-0026 — Isolated pilot security baseline and non-destructive DR

> **Сверка 2026-11-21:** [PR #33](https://github.com/uzbatsu-beep/HRMS/pull/33) объединён в `main`; исходная пометка `Proposed` оставлена как исторический статус документа. [Текущий статус](../REQUIREMENTS_MATRIX.md) · [G6 NO-GO](../PILOT_READINESS_G6.md) · [Индекс](../DOCUMENTATION_INDEX.md). Код и синтетические CI не заменяют PKI, эксплуатационный DR, PIA или допуск к реальному персоналу.


**Status:** Proposed in G6 PR. **Data:** synthetic until external signoff.

## Decision
Keep existing `docker-compose.yml` development-only. Provide a separately
configured production-mode Compose profile with a static-built frontend served
over TLS, an internal API/database network, separate migration job, non-root
backend, credentials from file-backed Docker secrets, and strict production
configuration validation. Only the resolved internal `web` peer may supply overwritten `X-Real-IP`; `X-Forwarded-For` is never accepted as client identity. The proxy TLS boundary must be separately verified; an upstream load balancer would require a new trust-chain review. Backend will not start with example DB password,
development HMAC key, plaintext/wildcard origin or missing secrets.

Use PostgreSQL custom-format logical archives, SHA-256 manifest and
no-overwrite isolated test restore. CI creates a disposable synthetic schema,
verifies canary data and Alembic revision after restore, and rejects corrupted
archives and already existing targets. Never run destructive rollback or
restore against the live DB from automation.

## Explicit boundaries
- GitHub branch rulesets require admin permissions not granted to this
  integration; they cannot be enabled by a repository file.
- Logical dumps are not cluster-role backups, WAL archiving, PITR or
  independently encrypted offsite backups.
- Synthetic health endpoint latency test is NOT production workload capacity
  validation.
- Runtime API access log suppression and Nginx access log suppression do not
  constitute a complete PII audit.
- Docker images use upstream version tags. Before pilot, pin immutable
  digests, scan images and dependencies and produce a signed SBOM.
- No dynamic workflow can modify safety-critical WorkOrder transitions,
  permit/credential hard gates or hardware interlocks.

## Risks and alternative
A fully managed PostgreSQL / TLS ingress / secret manager with audited
staging restore may be preferable to single-host Compose for real users.
The choice requires owner, operations and information-security approval.

See `docs/PILOT_READINESS_G6.md`, `docs/BACKUP_RESTORE_RUNBOOK.md`,
`docs/PRIVACY_IMPACT_CHECKLIST.md`, and `docs/MAIN_PROTECTION.md`.
