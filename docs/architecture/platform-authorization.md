# Platform and site authorization

The server is the security boundary. Firebase ID tokens authenticate identities;
exact server-side authorities authorize resources. Browser secrets, navigation,
email/domain, site count, deployment environment and Bracon identity grant nothing.

```text
Firebase ID token verification
    → {uid, email, platform_admin}
    → exact platform_admin custom claim: global administration
    OR
    → user_site_access(uid, site_id): viewer/admin site authorization
```

## Identity and authorities

`api/auth.py::get_current_user` exposes only uid, email (possibly null) and a
boolean platform-admin flag. Admission is exactly
`decoded.get("platform_admin") is True`; strings, numbers and other truthy values
are false. Missing/empty/invalid tokens and verification failure return HTTP 401.
Arbitrary decoded claims are not passed to application code.

`require_platform_admin` requires that verified flag, otherwise HTTP 403. It has
no additional header or browser-secret requirement. The retired `X-Admin-Key`,
`ADMIN_API_KEY` and `VITE_ADMIN_KEY` mechanisms have no active authorization use.
They are removed from frontend source, examples, CI and deployment bindings.
Removing bindings does not delete any external secret-manager resources.

`require_site_access` allows an exact `viewer` or `admin` membership.
`require_site_admin` allows only an exact `admin` membership. Both intentionally
allow verified platform administrators without a membership row. Site admins are
not platform admins. Normal users have no implicit site access. Parameterized SQL
selects the exact UID/site pair; unknown, padded, empty or malformed roles fail
closed with HTTP 403 and are neither repaired nor deleted. Roles are read per
request without an authorization cache. `get_user_sites` excludes invalid roles;
platform administrators explicitly receive all canonical sites.

## Route matrix

| Resource | Policy |
| --- | --- |
| `GET /health` | Public |
| `GET /api/v1/admin/me` | Authenticated identity, not admin-only |
| `GET /api/v1/expected-energy/{site_id}` | Site read |
| `GET /api/v1/benchmarking/{site_id}` | Site read |
| All four `GET /api/v1/analysis/{site_id}/...` routes | Site read |
| `POST /api/v1/reports/{site_id}` | Site read despite POST |
| `GET /api/v1/alerts/{site_id}` | Site read |
| `GET /api/v1/sites/{site_id}/layout` and `/geometry` | Site read, including demo mode |
| `POST /api/v1/backfill/{site_id}` | Site admin |
| `POST /api/v1/alerts/{alert_id}/acknowledge` | Admin for the alert's canonical site |
| `GET /api/v1/admin/sites` | Platform admin |
| `POST /api/v1/admin/sites` | Platform admin |
| `POST /api/v1/admin/sites/{site_id}/upload` | Platform admin |
| `POST /api/v1/admin/sites/{site_id}/access` | Platform admin |
| `GET /api/v1/ingest/status` | Platform admin; operational data is global |

FastAPI's generated schema/documentation and CORS preflight remain public API
metadata/protocol handling. They expose no protected site data. Every application
resource has an explicit policy asserted by the route-policy regression.

Alert acknowledgement authenticates first, locates the alert, obtains its stored
`site_id`, authorizes site-admin access in the same session, and only then mutates
`acknowledged`, commits and refreshes. A client-supplied site ID cannot authorize
another site's alert. Failed authorization performs no mutation or commit.

Access grants require platform administration, a nonblank target UID, an exact
`viewer`/`admin` request role and an existing canonical `sites` database row. The
normal startup site sync establishes these rows. Configuration-only sites must be
persisted before a grant succeeds. Existing role updates use the same parameterized
UID/site conflict identity. This endpoint never assigns a Firebase platform claim.
No migration or implicit rewrite of historical authorization data is introduced.

## Trusted platform-admin bootstrap

Provision `platform_admin=true` only out of band with Firebase Admin SDK and
trusted server credentials authorized for the intended Firebase project. No
HTTP claim-assignment endpoint is added, including for existing platform admins.
Never ship these credentials or real target UIDs in browser code or repository
files. Explicit operator selection of the target identity is required; do not
select administrators by email, domain or site membership.

Example in a trusted administrative environment, with placeholders only:

```python
import firebase_admin
from firebase_admin import auth, credentials

firebase_admin.initialize_app(credentials.ApplicationDefault())
target_uid = "<TARGET_FIREBASE_UID>"
record = auth.get_user(target_uid)
claims = dict(record.custom_claims or {})
claims["platform_admin"] = True
auth.set_custom_user_claims(record.uid, claims)
```

The SDK replaces the custom-claim map, so preserve unrelated claims and coordinate
concurrent administrative changes. Claims reach requests only in a newly issued
or refreshed ID token; reauthenticate or force the signed-in user's
`getIdToken(true)` refresh. Previously issued tokens retain their original claims
until refresh/expiry. Membership changes are checked from the database on the
next request. See Firebase's [custom-claim provisioning and propagation contract](https://firebase.google.com/docs/auth/admin/custom-claims)
and [ID-token verification](https://firebase.google.com/docs/auth/admin/verify-id-tokens).

Before rollout, bootstrap the intended trusted operator, refresh its token,
confirm `/api/v1/admin/me`, and grant explicit site memberships through the
protected API. Verify the same negative cross-site and mutation cases in the
intended deployment. This PR does not execute bootstrap, deploy services, grant
real users access or activate shadow output.

## Browser behavior and readiness

`frontend/src/api/client.js` already attaches the Firebase bearer token. Admin
calls now use that same client without an extra secret. Existing admin navigation
may remain visible to ordinary users; backend 403 responses are authoritative.
Frontend navigation/auth-state design is separate work, not a security boundary.

Authorization implementation readiness is complete when the focused tests pass:
identity claim exactness, all 19 application-route policies, cross-site denial,
viewer mutation denial, global-operation denial for site admins, explicit platform
bypass, indirect alert ownership, role/grant validation and browser-secret removal.
Generic physics and the revenue-meter uncertainty stack remain unchanged. The next
backend readiness work is site evidence / P1-P2 finalisation; P1/P2/P3 are not
complete, Bracon physical evidence is not admitted and no shadow source is active.
