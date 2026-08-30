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

Staging is a cloud deployment isolated from production. It should have:

- a dedicated Cloud Run service, e.g. `heliotelligence-api-staging`
- a dedicated staging PostgreSQL/TimescaleDB database
- staging Secret Manager secrets
- a staging Firebase project/site
- `APP_ENV=staging`
- CORS configured for the staging frontend origin

The staging environment is where schema migrations, physics changes, regression reports, API changes, and frontend integration are validated before production promotion.

A staging Cloud Build template is provided at `deploy/cloudbuild.staging.yaml`. It is intentionally not wired to a trigger until the staging GCP project and secrets exist.

## Production

Production uses `APP_ENV=production` and production-only secrets. The production Cloud Build deployment uses the immutable `$SHORT_SHA` image built during that build rather than deploying a mutable `latest` tag.

## CI gates

Pull requests to `main` run:

1. backend unit tests
2. frontend dependency installation and production build

Additional physics regression tests will be added as the Stage 4/5 architecture is upgraded.

## Configuration rules

- `APP_ENV` is the canonical environment variable.
- `ENVIRONMENT` is accepted only as a backwards-compatible alias.
- staging and production must provide a non-default `SECRET_KEY`.
- CORS origins are provided through comma-separated `CORS_ORIGINS`.
- secrets are never committed to the repository.
- frontend staging and production must point to their matching API environment.

## Codex / local-cloud handoff

Codex or a local terminal with authenticated GCP/Firebase access becomes useful when repository-only work reaches infrastructure provisioning. At that point, use it to:

1. create or select the staging GCP project
2. create the staging Artifact Registry repository if needed
3. provision the staging PostgreSQL/TimescaleDB instance/database
4. create staging Secret Manager values using the same logical secret names as production
5. create/configure the staging Firebase project and hosting target
6. configure the staging Cloud Build trigger using `deploy/cloudbuild.staging.yaml`
7. configure staging frontend deployment secrets and API URL
8. run the first staging deployment and smoke-test `/health`

The `/health` response includes the runtime environment so deployment wiring can be verified directly.

## Scheduler architecture note

The API currently starts APScheduler inside the FastAPI lifespan. Cloud Run is configured with multiple workers and can scale to multiple instances, so scheduled jobs can run more than once. Do not change this behavior until an external scheduler/worker path is provisioned. The target architecture is:

```text
Cloud Run API        -> request/response only
Cloud Scheduler      -> Cloud Run Job / worker -> collectors + physics jobs
```

This should be implemented as a separate migration after staging exists, so job execution can be validated without interrupting production ingestion.
