# PR #13 — Browser acceptance tests and synthetic demonstration data

## Goals and scope

This is a **functional Playwright acceptance harness**, not a production-data
migration or a new authorization endpoint. It tests the real frontend against a
real FastAPI server and a **dedicated PostgreSQL database**.

- Browser: Playwright / Chromium (desktop and 390 px mobile viewport)
- Servers: Vite proxy → FastAPI → PostgreSQL 16
- Synthetic fixture: users, enterprise, nested units, four fictional specialists,
  versioned competence, independently approved evidence, separately verified
  mandatory permits, recurring shifts and a scheduled technical WorkOrder
- Mutations: performed with normal authenticated REST API and correct CSRF
  headers; expected negative results assert real HTTP status codes
- Artifacts: HTML and JUnit reports, failure-only screenshots, trace and video
- GitHub Actions: dedicated E2E job following backend unit tests and frontend
  build; uploads artifacts even on failure

### Covered scenarios

1. Guest sees navigation but no private organization/personnel data; successful
   UI login refreshes the session and right rail.
2. Hash-routed modules and old `#home` deep link work after reload.
3. Responsive menu can be opened on a narrow viewport; no page-wide overflow.
4. Right rail shows actual nested units and personnel. Unit filter, search
   and employee-to-card navigation work.
5. Viewer is restricted to the granted department and cannot see other Person
   records or mutate WorkOrders. Manager cannot access a foreign department.
6. A work candidate without approved competence / mandatory permit is
   rejected by the backend. A verified candidate can be assigned.
7. A qualified second crew member is added and gets a separate reservation.
8. Work start validates participants; a later **synthetic credential revocation**
   causes an explicit revalidation to transition the task to `on_hold`.
   Completion is not available. Canceling preserves work history.

All role/competence/permit/availability constraints remain implemented
**exclusively by the backend**, not by the Playwright fixture or React.

## Isolation and safety

`frontend/e2e/global-setup.ts` refuses to run unless:

- `E2E_ALLOW_SEED=1` is explicitly set;
- `E2E_BASE_URL` points to HTTP `localhost` or `127.0.0.1`;
- administrator and test actor credentials are provided in environment
  variables, not checked into the repository.

**These are guardrails, not a substitute for database isolation.** The easiest
safe method is `docker-compose.e2e.yml`, which uses its **own PostgreSQL
volume**, containers and host ports. It cannot access the normal `db` service
volume and uses ports `5174` and `8001`, so it may run beside the regular
local TWM stack. E2E setup generates a unique code namespace per run and
never modifies or deletes unrelated records.

Do not point this runner at your populated production/development database or
a database with real personnel information, even if its frontend is on localhost.
Do not use real credentials, certificates or employees as E2E inputs.

## Local Windows run — isolated Docker stack

PowerShell in the repository root (Node.js 22 and Docker Desktop required):

```powershell
$env:E2E_DB_PASSWORD = ([guid]::NewGuid().ToString("N") + [guid]::NewGuid().ToString("N"))
$env:E2E_ADMIN_PASSWORD = ([guid]::NewGuid().ToString("N") + [guid]::NewGuid().ToString("N"))
$env:E2E_ACTOR_PASSWORD = ([guid]::NewGuid().ToString("N") + [guid]::NewGuid().ToString("N"))
$env:E2E_ADMIN_USERNAME = "e2e_admin"

docker compose -f docker-compose.e2e.yml up --build -d
docker compose -f docker-compose.e2e.yml ps
docker compose -f docker-compose.e2e.yml exec -e TWM_ADMIN_USERNAME=e2e_admin -e TWM_ADMIN_PASSWORD="$env:E2E_ADMIN_PASSWORD" backend python -m app.identity.bootstrap_admin

cd frontend
npm install
npx playwright install chromium
$env:E2E_BASE_URL = "http://127.0.0.1:5174"
$env:E2E_ALLOW_SEED = "1"
npm run test:e2e
```

**On later runs**, reuse the original `E2E_ADMIN_PASSWORD` or reset the
disposable test database. The bootstrap command refuses to overwrite an
existing admin password. A new shell will not automatically remember those
environment variables. This is intentional.

The Playwright HTML result is under `frontend/playwright-report/index.html`;
JUnit under `frontend/test-results/junit.xml`. Failure traces, screenshots
and videos are under `frontend/test-results/artifacts`. Never check these
artifacts in.

To destroy **only the E2E environment and its isolated volume**, from the
repository root:

```powershell
docker compose -f docker-compose.e2e.yml down -v
```

Warning: `down -v` deletes the synthetic E2E data. Do not run it against your
regular `docker-compose.yml` environment.

## CI execution

The `e2e` GitHub Actions job:

1. Starts a fresh PostgreSQL 16 service for the job.
2. Applies Alembic revisions through head.
3. Generates short-lived admin and reviewer passwords, masks them in the CI
   log, and bootstraps an admin. No real secrets are committed.
4. Starts Uvicorn and Vite, installs Chromium, and runs `npm run test:e2e`.
5. Uploads reports and traces for 14 days, including on failures.

Review artifacts from the GitHub Actions **Browser E2E** job. They contain
synthetic people and IDs only; they should still be treated as internal
engineering diagnostics.

## Definition of Done

- Existing backend unit suite and frontend TypeScript/build pass.
- Playwright desktop, mobile, organization/role, and technical work acceptance
  scenarios pass with a real PostgreSQL service on a clean CI runner.
- Browser failures produce readable trace/screenshots and do not silently
  retry or downgrade safety decisions to UI-only checks.
- CI includes the new E2E gate for future Pull Requests.
- Manual visual acceptance on the user's Windows workstation remains distinct:
  CI cannot assert legibility of real dashboards and long enterprise catalogs.

### Limitations

The fixture focuses on one synthetic activity/skill/permit policy and one
technical work order; it does not cover all enterprise localization rules,
full workload capacity, concurrent PostgreSQL races, every responsive
breakpoint, real external certificate issuers, equipment isolation/LOTO or
hazardous-work legal permits. E2E success does not certify industrial safety.
