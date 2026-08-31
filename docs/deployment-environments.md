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

- a dedicated Cloud Run service
- a dedicated staging PostgreSQL database
- staging Secret Manager secrets
- a staging Firebase project/site
- `APP_ENV=staging`
- CORS configured for the staging frontend origin

The staging environment is where schema migrations, physics changes, regression reports, API changes, and frontend integration are validated before production promotion.

The `deploy/cloudbuild.staging.yaml` template is connected to the staging deployment trigger. Triggered builds run tests, publish an immutable commit-tagged image, and deploy only the staging Cloud Run service with its dedicated runtime identity.

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

The API currently starts APScheduler inside the FastAPI lifespan. Cloud Run is configured with multiple workers and can scale to multiple instances, so scheduled jobs can run more than once. Do not change this behavior until an external scheduler/worker path is provisioned. The target architecture is:

```text
Cloud Run API        -> request/response only
Cloud Scheduler      -> Cloud Run Job / worker -> collectors + physics jobs
```

This should be implemented as a separate migration after staging exists, so job execution can be validated without interrupting production ingestion.
