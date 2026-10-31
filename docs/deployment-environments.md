# Deployment environments

Heliotelligence uses three runtime environments. The same application code should move through each environment; only configuration, credentials, infrastructure, and data differ.

## Environment flow

```text
Developer laptop
    |
    | feature branch + pull request
    v
CI validation
    |
    v
Staging
    |
    | validate API, physics regressions, migrations, and frontend
    v
Production
```

## Development

Development runs locally and uses `APP_ENV=development`.

Typical services:

- frontend: Vite on `http://localhost:5173`
- API: FastAPI on `http://localhost:8000`
- database: local PostgreSQL/TimescaleDB
- local `.env` for developer-only credentials

Development must never use production database credentials.

## Staging

Staging is a provisioned cloud deployment isolated from production. It uses:

- a dedicated Cloud Run service;
- a dedicated staging PostgreSQL database;
- staging Secret Manager secrets;
- a staging Firebase project/site;
- `APP_ENV=staging`;
- CORS configured for the staging frontend origin.

The staging environment is where schema migrations, physics changes, regression reports, API changes, and frontend integration are validated before production promotion.

The `deploy/cloudbuild.staging.yaml` template is connected to the staging deployment trigger. Triggered builds run tests, publish an immutable commit-tagged image, and deploy only the staging Cloud Run service with its dedicated runtime identity.

## Production

Production uses `APP_ENV=production` and production-only secrets. The production Cloud Build deployment uses the immutable `$SHORT_SHA` image built during that build rather than deploying a mutable `latest` tag.

Current `cloudbuild.yaml` deploys the production Cloud Run API with:

- `--min-instances=0`;
- `--max-instances=10`;
- 2 GiB memory;
- 2 CPUs;
- production secrets supplied through Secret Manager;
- `APP_ENV=production`.

The `--min-instances=0` setting was introduced by the operations-only PR #71 before the S9-4A physics merge and did not change physics code or tests.

## CI gates

CI currently validates:

1. backend unit tests;
2. frontend dependency installation and production build.

S8 through S14 generic component/control/network/meter physics is validated but not automatically production-active.

Current canonical code checkpoint: `a750524c347a2be0f841bedcd24a627bfbe37941` (PR #128 merge on `main`). Live GitHub CI must be rechecked for release/merge decisions. Git history and GitHub Actions are the authoritative historical record.

Production still uses the legacy expected-energy path. Activation requires explicit site evidence, reference-plane alignment, operational safety and no double counting. Staging should be the first environment for future source-separated physical shadow execution, expected-energy validation and migration comparisons. Shadow execution is planned, not already deployed; P0 source isolation must precede it, and the upstream thermal/irradiance/time-semantics, S14B density, uncertainty and access-control gates in the [production-integration roadmap](development/production-integration-roadmap.md) must be closed before the shadow model is treated as an end-to-end validation source.

Deployment settings, `grid_limit_kwac`, `wiring_loss_ac_pct` and equipment labels are not dispatch, topology, R/X, temperature, grid-voltage or meter-measurement authority. Valid transformer fallback may resolve downstream physics/accounting, but must retain explicit fidelity and provenance.

## Shadow access-control gate

Staging isolation does not make application authorization sufficient by itself.

The authorization implementation now requires verified Firebase identity on every protected route, exact `platform_admin=true` for global operations and exact database viewer/admin membership for site scope. Platform admin bypass is intentional; site admins are not platform admins. The browser administrator key/header has been retired without fallback, including CI examples and Cloud Build secret bindings. No external secret resources are deleted by this source change.

Before exposing data in a deployment, provision the intended platform-admin claim with trusted credentials, refresh the ID token, establish explicit site memberships and verify negative cross-site/mutation behavior. See the [full policy, route matrix and bootstrap procedure](architecture/platform-authorization.md). The same model applies to staging/production and every site; deployment environment grants no access. No deployment or shadow activation is performed by this increment.

## Configuration rules

- `APP_ENV` is the canonical environment variable.
- `ENVIRONMENT` is accepted only as a backwards-compatible alias.
- staging and production must provide a non-default `SECRET_KEY`.
- CORS origins are provided through comma-separated `CORS_ORIGINS`.
- secrets are never committed to the repository.
- browser-visible `VITE_*` values must never be treated as confidential authorization secrets.
- frontend staging and production must point to their matching API environment.
- physics equipment/topology authority must come from explicit configuration or validated data sources; deployment configuration must not invent missing electrical relationships.
- deployment parameters such as Cloud Run scaling, grid/export limits, or service configuration must not be promoted into inverter physics authority.

## Staging operations

The staging project, database, container registry, Cloud Run service, Firebase Hosting target, and deployment trigger are provisioned. Repository changes flow to staging through the dedicated staging build configuration and identity; production deployment remains a separate workflow.

Staging runtime configuration follows these rules:

- Cloud Run connects only to the staging database.
- Firebase Admin uses the runtime service account through Application Default Credentials.
- optional integrations remain disabled until real staging credentials are intentionally configured.
- frontend builds use only the staging API and staging Firebase application.
- migrations run separately with the dedicated staging migration identity.

The `/health` response includes the runtime environment so deployment wiring can be verified directly.

## Scheduler architecture note

The API currently starts APScheduler inside the FastAPI lifespan unless the scheduler gate disables it. Cloud Run may run multiple workers and multiple service instances, so in-process scheduling can execute a scheduled workload more than once if enabled.

The request-serving staging API has been validated with `RUN_SCHEDULER=false`. The target long-term architecture remains:

```text
Cloud Run API        -> request/response only
Cloud Scheduler      -> Cloud Run Job / worker -> collectors + physics jobs
```

The dedicated scheduler/worker migration is operational work and should remain separate from component-physics development unless a specific runtime dependency requires them to move together.
