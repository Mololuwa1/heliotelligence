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

The validated dormant component-physics/control chain now extends through **S11C balanced radial LV AC collection operating solution**.

Final reviewed CI for PR #86 was:

- workflow run #217;
- run ID `37544412809`;
- base `3fb4c3181c283ecf62622865b88622ac7b24ae22`;
- head `73dafc1f79c09ccd9fb61dd9ee7610cc2e62233c`;
- synthetic merge `a8ea3ec4965e75f2ae67dae835a74dc619bf4d2e`;
- Python 3.13.15;
- `pvlib==0.15.2`;
- backend `3040 passed in 527.89s`;
- frontend success.

PR #86 then merged as `6f6dbb34027f9e648fe8623aab37b14341f193c7`.

Treat this as historical validation evidence and re-check current CI before release decisions.

Validated S8/S9/S10/S11 contracts remain dormant from production. Production activation requires a separately reviewed integration proving authoritative inputs, safe unresolved behavior, reference-plane alignment, telemetry compatibility, operational safety, and no double counting with legacy loss factors.

Deployment configuration is not controller or LV-network authority. Legacy `grid_limit_kwac`, `wiring_loss_ac_pct`, Cloud Run settings, environment variables, and service configuration must not be promoted into dispatch requests, LV topology/R/X, operating voltage, or solved state.

## Configuration rules

- `APP_ENV` is the canonical environment variable.
- `ENVIRONMENT` is accepted only as a backwards-compatible alias.
- staging and production must provide a non-default `SECRET_KEY`.
- CORS origins are provided through comma-separated `CORS_ORIGINS`.
- secrets are never committed to the repository.
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
