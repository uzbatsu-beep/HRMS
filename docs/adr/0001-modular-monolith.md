
# ADR-0001: Modular monolith as the initial application architecture

- Status: Accepted for the foundation stage
- Date: 2026-11-12

## Context

TWM contains closely related domains: organization, personnel, competence, credentials, availability, work management, matching, configuration and analytics. There is no current scale or independent deployment requirement that justifies distributed services. The first goal is a reproducible, testable vertical slice with low operational overhead.

## Decision

Start with a modular monolith:
- one FastAPI application and one PostgreSQL database;
- separate domain packages and explicit module interfaces as domain features are implemented;
- domain-owned business rules and schemas;
- no direct cross-domain table manipulation from unrelated modules;
- REST/OpenAPI as the frontend and future integration contract;
- migrations managed by Alembic.

The React frontend is served independently during development and communicates with the backend through the Vite API proxy.

## Consequences

### Positive
- simple local development and deployment;
- transactional integrity across assignment and availability operations;
- simpler observability, testing and debugging;
- domain boundaries can be extracted later if evidence justifies it.

### Trade-offs
- modules share a deployment lifecycle;
- module boundaries must be preserved through code review and tests;
- independent scaling and deployment are not available initially.

## Revisit when

A domain has a demonstrated independent scaling, reliability, security, ownership or deployment requirement that cannot be handled adequately within the modular monolith.
