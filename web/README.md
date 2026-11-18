---
title: AI Budget Control portal
description: Configure and run the authenticated Fluent UI gateway administration portal.
---

## Overview

Accessible React + TypeScript + Fluent UI v9 portal, hosted by a framework-free Node
server. Use Node **24 LTS**.

The portal manages monthly USD budgets for OpenAI Chat Completions and Responses.
Its model inventory reflects deployment-managed aliases and pinned price versions.

```bash
npm ci
npm run lint
npm run typecheck
npm run test -- --run
npm run build
npm start
```

Run these commands from [`web/`](.). `npm start` serves `dist/` on
`0.0.0.0:${PORT:-8080}`. Deploy `dist/`, `server/`, `package.json`,
`package-lock.json` and locked production `node_modules/` together; see
[packaging](#privacy-safe-observability) below.
`npm run dev` uses Vite on loopback; the same runtime configuration is served
by its `/config.json` development middleware. Create `web/.env.local` for Vite,
or export settings in the shell for both servers. Never place secrets in Vite variables.

## Required production runtime settings

| Setting                                 | Meaning                                                                                                                                                                                                             |
| --------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `AZURE_CLOUD`                           | Exactly `commercial` or `government`; no automatic cloud fallback                                                                                                                                                   |
| `AZURE_TENANT_ID`                       | Tenant-specific Entra GUID; `common`/`organizations` are rejected                                                                                                                                                   |
| `WEB_CLIENT_ID`                         | SPA application registration client GUID                                                                                                                                                                            |
| `API_AUDIENCE`                          | Backend application ID URI, e.g. `api://<backend-app-id>`                                                                                                                                                           |
| `API_SCOPE`                             | Full delegated scope under that audience, e.g. `api://<backend-app-id>/access_as_user`                                                                                                                              |
| `API_BASE_URL`                          | HTTPS APIM `/portal` upstream in proxy mode; direct API collection root is used only for non-proxy local development                                                                                                |
| `PORT`                                  | Optional Node listening port; default `8080`                                                                                                                                                                        |
| `WEB_PLATFORM_AUTH_ENABLED`             | Terraform sets `true` for App Service; logout clears its session after MSAL sign-out. Defaults off for local development.                                                                                           |
| `WEB_API_PROXY_ENABLED`                 | Terraform sets `true` in production. Enables the same-origin `/api/*` proxy; `false` retains direct local development.                                                                                              |
| `PORTAL_APIM_SUBSCRIPTION_KEY`          | Server-only Key Vault reference for the APIM product key; required by the proxy and never sent to or exposed in the browser.                                                                                        |
| `APPLICATIONINSIGHTS_CONNECTION_STRING` | Optional workspace-based Application Insights connection string with explicit cloud-specific `IngestionEndpoint`; enables privacy-filtered browser events/dependencies and manual server requests/dependencies/logs |

`/config.json` is generated at server startup from these **public** settings;
it contains no client secret, Function key or APIM subscription key. When configured,
its optional `appInsights` field contains **public instrumentation routing only**:
`{connectionString, ingestionOrigin}`. See the privacy contract below.
In proxy mode it publishes `apiBaseUrl: "/api"` and `apiProxyEnabled: true`,
never the APIM key or upstream URL. The proxy accepts only allowlisted portal
routes and methods, requires the browser's `X-Portal-Access-Token`, forwards that
delegated token as upstream `Authorization`, and adds the server-side APIM key.
It never forwards cookies, App Service identity headers, client-supplied keys, or
arbitrary headers. Proxy upstream redirects, oversized bodies and missing or
unresolved Key Vault references fail closed. Browser API calls use the native
same-origin sign-in cookie and do not send an Authorization header to the web
audience.

An HTTP 401 does not necessarily mean the user's token expired: APIM also
returns it for missing or invalid subscription keys. After a deployment that
changes routing, reload the browser page to fetch current `/config.json`;
the in-app Refresh button only retries data using the already-loaded config.
Production calls must target same-origin `/api/*`, not APIM directly. Operators
should check APIM `LastErrorReason` and the server's Key Vault reference status
before changing Entra settings. Never put a product key in browser configuration.

The browser build is cloud-independent. Only the two supported Microsoft
authorities are accepted. API URLs may use HTTP only for loopback development.
All browser requests use access tokens for `API_SCOPE`, never ID tokens.

Register the deployed portal **origin** (and `http://localhost:5173` or
`http://127.0.0.1:5173` for development) as SPA redirect URIs.
Grant consent for the delegated API scope and Graph `User.Read`, and assign API app roles:
`RateLimit.Admin` or `RateLimit.Reader`. The UI reads role hints from the API
access token; the backend independently validates audience, tenant and roles,
and scopes Reader data to the authenticated user's explicit assignment,
department, and team. `RateLimit.Gateway` alone cannot open portal data.
The production same-origin proxy does not require browser-to-APIM CORS. Direct
local development uses the delegated API token and requires exact portal origins.
Expose `X-Correlation-ID` if operators need to inspect backend correlation responses.
Terraform also protects the deployed website, assets and `/config.json` with native
App Service Entra authentication. The same single-tenant registration has a
**Web** redirect URI at `https://<portal>/.auth/login/aad/callback` and a **SPA**
redirect URI at the portal origin. App Service uses the dedicated web managed
identity and a federated credential instead of a client secret; it does not store
provider tokens. Do not copy the identity's federation setting into browser config.
The Web platform enables ID-token issuance for App Service's native hybrid
`code id_token` response; implicit **access-token** issuance remains disabled.
MSAL still uses authorization code + PKCE for delegated **API access tokens**.
The App Service sign-in cookie does not grant API roles or replace these tokens.
Sign-out clears MSAL/Entra and then the native App Service session. Local Vite
development does not depend on App Service middleware.

The browser does not send local test-identity headers. Pointing `API_BASE_URL`
at the loopback Python API alone will not authenticate it. Follow
[local development](../docs/local-development.md) for the distinction between
header-based API testing and an authenticated browser/backend setup.

### Remembered sign-in and SSO

The website's encrypted, Secure/HttpOnly App Service session cookie remains
platform-managed. MSAL uses `localStorage` so the API account/cache is shared
across tabs rather than discarded when a tab closes. MSAL v4 manages its cache
encryption and `msal.cache.encryption` session cookie; the portal does not put
passwords, access tokens or user profiles in a custom cookie, and does not use
the deprecated `storeAuthStateInCookie` option.

A remembered account obtains API tokens silently. If native App Service login
has succeeded but no API account is cached, the portal starts one top-level
MSAL redirect to reuse Entra's existing session, without forcing a fresh login
or using a hidden iframe. A per-tab non-secret attempt flag prevents failed
redirect loops; explicit sign-in remains available. Local development never
auto-redirects. Logout still clears MSAL/Entra and the native website session.

Persistence across browser restarts depends on Entra **Keep me signed in** and
your tenant's session/Conditional Access policies. Session expiry, cleared
browser data, denied consent and MFA can require interaction; this feature
does not extend or bypass them. See Microsoft's
[cache behavior](https://learn.microsoft.com/entra/msal/javascript/browser/caching)
and [SSO guidance](https://learn.microsoft.com/entra/msal/javascript/browser/single-sign-on).

The portal requests a separate delegated Microsoft Graph `User.Read` token for
the signed-in user's `/me` profile and photo only. Commercial uses
`graph.microsoft.com`; Government uses `graph.microsoft.us`. The profile image is
held in a revocable in-memory blob URL; denied consent, missing photos and Graph
errors fall back to initials. Profile names and photo data are never sent to
telemetry or persisted by the portal.

The portal always uses authenticated API access. There is no browser-only demo
mode or bundled fixture dataset. Optional fictional records are deployed to
isolated backend stores with the separate [demo loader](../demo/README.md).

## Screens and server contracts

The [configuration reference](../docs/configuration-reference.md#routes)
owns API routes, payloads, units and selection semantics. The browser types in
[`src/contracts.ts`](src/contracts.ts) mirror the server; do not treat them as an
independent accounting implementation.

| Screen                               | Purpose                                                                                                                |
| ------------------------------------ | ---------------------------------------------------------------------------------------------------------------------- |
| Overview, Monthly budgets            | Show scoped operational month-to-date spend (including estimates) and remaining monthly USD budgets by hierarchy level |
| Usage records                        | Display normalized OpenAI token usage and explicit unknown-stream outcomes                                             |
| Chargeback                           | View and export authorized monthly JSON/CSV grouped by organization and request dimensions                             |
| Organization units, User assignments | Admin-only management of departments, teams, cost centers, and explicit Entra principal mapping                        |
| Monthly budgets, OpenAI price cards  | Admin-only CRUD for user/team/department monthly limits and versioned decimal USD price cards                          |
| Model inventory                      | Read-only OpenAI protocol/alias, provider deployment, pinned price and token bounds                                    |
| Azure dashboard (Admin only)         | Render deployed Azure dashboard tiles and shared KQL results                                                           |

Reader sessions load only authorized model/status/report routes; they do not
load management collections or send writes. See the
[route reference](../docs/configuration-reference.md#routes) for methods,
payloads and query parameters.

The Azure dashboard is visible only to RateLimit.Admin because it contains workspace-wide telemetry. It requests `/dashboard?period=1h|24h|7d`; production maps this through the same-origin proxy, while direct local development uses the configured API root. The browser never sends KQL or workspace identifiers. The tile titles, axes, chart definitions and tabular values come from the deployed Azure dashboard. Per-tile query failures, empty results and server truncation are shown independently; request-level failures remain retryable. Each chart exposes a detail table. Loading fictional backend records does not fabricate dashboard telemetry.

Reader requests contain no caller-selected identity or hierarchy filter; the
backend derives the signed-in user's access scope from explicit assignments.
Budget status is approximate operational month-to-date Redis spend from the API,
not a portal-side calculation or financially complete ledger balance. Usage and
chargeback read eventually persisted Table history and can lag or permanently
differ from live spend after background-write loss or a Redis reset. Unknown
stream usage in retained records remains visibly unknown and is not
displayed as a zero-cost completed request. The browser does not reprice provider
payloads: it sends USD values as decimal strings for price cards and displays
budget amounts through exact integer micro-USD conversion.

Monthly budgets are approximate soft caps, not invoice guarantees. The
[architecture](../ARCHITECTURE.md#key-design-decisions) owns these design
choices; [operations](../docs/operations.md) owns Redis retention and the shared,
lossy Table/export queue contract. The UI must not imply that a successful
accounting operation proves durable history or downstream event delivery.

GET failures remain visible and retryable. Failed saves retain the editor; failed
deletes retain confirmation. Search filters are local display operations. Model
aliases, provider deployment routing and pinned price versions remain
deployment-managed. Refresh is manual; there is no websocket, automatic polling,
pagination or live price feed.

The portal does not execute inference, configure gateway capabilities, or establish
Government model availability. Its model metadata and local unit tests do not prove
live cloud access or interactive sign-in. Source navigation and extension boundaries
are in the [code guide](../docs/code-guide.md).

### Recommended actions

Every screen leads with a **Recommended actions** panel, ordered by
urgency and limited to findings about the records actually loaded (no forecasts or generic advice), so the portal says what to do and not only what happened. The rules are pure functions in
[`src/insights/`](src/insights) computed from data the page already loaded; they add no API calls
and no accounting. Each recommendation names the fact and why it matters;
recommendations may include a next-step action (open the budget editor, create a
record, or jump to the relevant screen). Readers only see
guidance and navigation; create and edit actions are administrator-only and remain API-enforced.

| Screen                               | Examples                                                                                 |
| ------------------------------------ | ---------------------------------------------------------------------------------------- |
| Overview, Monthly budgets            | Limit reached, 80% or more used, missing budgets, child limit above parent               |
| Usage records                        | Unknown-usage requests and provider-reported usage exceeding model bounds                |
| Chargeback                           | Open month is provisional, unknown requests, estimated costs, rows without a cost center |
| Model inventory, OpenAI price cards  | Model without a price card, duplicate or unused cards, `$0` or inverted rates            |
| Organization units, User assignments | Teams without a department or users, assignments to disabled teams                       |
| Azure dashboard                      | Failed or empty tiles and truncated results                                              |

## Privacy-safe observability

The production Node server uses Microsoft's
`@azure/monitor-opentelemetry-exporter` with private OpenTelemetry trace/log
providers. The exact exporter and supporting OpenTelemetry versions are pinned
in [`package.json`](package.json) and [`package-lock.json`](package-lock.json).
Re-review remote configuration polling and auxiliary export behavior before
upgrading the exporter; those features are part of the privacy boundary.
Statsbeat, SDK statistics and resource-metric auxiliary export are explicitly
disabled using the SDK's supported environment switches before initialization.
The supporting OpenTelemetry packages are the exporter's required
standards-based SDK, not a second telemetry vendor. No auto instrumentation,
global provider registration, resource detection, console interception, live
metrics, exception capture or offline disk buffering is enabled.
The server role is `apim-rate-limit-foundry.ai-budget-portal`.
The browser role for manual dependencies is `ai-budget-portal-browser`.

Disable the App Service native Node agent
(`ApplicationInsightsAgent_EXTENSION_VERSION=disabled`) and any agent preload
in `NODE_OPTIONS`, retaining `APPLICATIONINSIGHTS_CONNECTION_STRING`.
Do not run native and explicit exporters together: that duplicates request
records and bypasses this manual privacy policy. The server needs production
npm dependencies. Packaging must stage `package.json`, `package-lock.json`,
`dist/`, `server/`, and production `node_modules/` (run `npm ci --omit=dev` in
the staging directory with Node 24). A static-only artifact cannot run this server.
The browser's Microsoft `@microsoft/applicationinsights-web` SDK remains bundled
by Vite, never loaded from a CDN.

Server code writes one JSON `portal_request` outcome per request, including
HEAD, rejected requests and premature response closure. Fields are `timestamp`,
`event`, validated browser UUID `correlationId` (or a new UUID-v4), allowlisted `method` (`OTHER` for
unknown methods), safe `route` (`runtime_config|page|asset|api_proxy|other`), numeric
`status` (`0` when aborted), `durationMs`, `outcome`
(`success|failure|aborted`) and fixed `errorCategory`
(`none|method_not_allowed|invalid_path|not_found|serve_error|connection_closed|proxy_disabled`
plus fixed `api_*` categories). The same correlation ID is returned to the browser,
logged and forwarded to APIM. With export configured, logs also include random
W3C `traceId` and `spanId`.
`portal_started` includes port, cloud and browserTelemetry.
`portal_server_error` includes only `startup_configuration|listen_error`.
The same allowlisted outcomes are exported as correlated `AppTraces`, alongside
one manual `AppRequests` span per Node request and one `AppDependencies` span per
attempted APIM fetch. Response processing, rejection, redirects, failures and
early disconnects retain safe outcomes; invalid/auth-rejected proxy requests do
not invent dependencies. Request names use method and fixed route categories,
never request URLs, record IDs or query strings. Dependency target is the fixed
`ai-gateway` label, not a hostname. Console logs remain available independently:
enable App Service console logging and route `AppServiceConsoleLogs` to the
intended workspace if desired. SIGTERM/SIGINT drain active HTTP work with a
five-second grace period, then flush/shut down SDK providers.

The optional connection string must include a GUID `InstrumentationKey` and
explicit HTTPS root `IngestionEndpoint`. Commercial permits
`applicationinsights.azure.com` and its subdomains; Government permits
`applicationinsights.us` / `applicationinsights.azure.us` and their subdomains.
Credentials, non-default ports, query, fragment and non-root paths are rejected.
Missing, invalid or wrong-cloud optional telemetry **disables browser and server export**
without breaking authentication or the portal. Government never falls back to
a commercial endpoint. Only the validated exact ingestion **origin** is added
to CSP `connect-src`, with no wildcard. The browser independently revalidates it.
Only instrumentation key and ingestion origin are published; additional
connection-string fields (including authorization, application ID and live
metrics endpoint) are not published.

The instrumentation key is **not a read credential**: it routes writes but
grants no access to stored telemetry. Public `/config.json` makes the key and
ingestion endpoint observable to anyone who can load the portal. Treat the
endpoint/resource/region as public deployment metadata; keep data access behind
Azure RBAC and monitor ingestion abuse. Ingestion necessarily contacts the
configured Azure endpoint; normal transport metadata, including source IP and
browser networking headers, is outside the custom-event payload privacy filter.
Choose component IP-masking, retention, RBAC and data-processing policies
accordingly. Nothing here promises anonymous network traffic.

Existing manually sanitized custom events remain in `customEvents` / workspace
`AppEvents`. Manual browser dependencies additionally go to `AppDependencies`;
automatic URL-based dependency collection remains disabled:

| Event                      | Custom dimensions                                                                                                                                                      | Custom measurements                             |
| -------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------- |
| `portal_page`              | allowlisted `page`, `outcome=success`                                                                                                                                  | none                                            |
| `portal_api`               | `collection`, `method=GET/PUT/DELETE`, generated UUID-v4 `correlationId`, `outcome=success/failure`, `errorCategory=none/authentication/http/network/invalid_response` | `status`, `durationMs`, `requestCount=0/1`      |
| `portal_configuration`     | editable `collection`, `action=create/update/delete`, `outcome=success/failure/cancelled`, `errorCategory=none/validation/api`                                         | none                                            |
| `portal_chargeback_export` | `format=json/csv`, `outcome=success/failure`                                                                                                                           | none                                            |
| `portal_refresh`           | `outcome=success/partial_failure`                                                                                                                                      | `collectionCount`, `failureCount`, `durationMs` |
| `portal_bootstrap`         | `action=configuration/authentication/sign_in/sign_out`, `outcome=success/failure`                                                                                      | none                                            |
| `portal_browser_error`     | `errorCategory=script/unhandled_rejection/render_error`                                                                                                                | none                                            |
| `portal_identity`          | `action=token_api/token_graph`, `outcome=success/failure`                                                                                                              | none                                            |

`requestCount` is zero when token acquisition fails before an HTTP attempt and
one once fetch is attempted. If optional UUID generation fails, the API still
works and omits the correlation header/property rather than inventing an ID.

Pages and collections come from fixed UI/API enums, never browser locations.
The API generates a random W3C dependency context and sends `traceparent` and
its explicit `X-Correlation-ID` only to its configured API root. The Node proxy
validates W3C version-00 IDs, rejects zero/ambiguous/malformed context, starts a
server child and forwards a new dependency child to APIM. Incoming `baggage`,
`tracestate`, arbitrary headers and raw URLs are never copied. APIM/Function
must preserve W3C context to complete the downstream graph.

Manual browser dependency fields are restricted to fixed collection/Graph
operation names, method, fixed service target, random trace/span IDs, numeric
HTTP status/duration and success. Graph profile/photo fetches have high-level
dependency outcomes but receive **no tracing headers**; their query strings,
names and photo bytes are never telemetry. Token acquisition emits only a fixed
action/outcome event; it does not pretend a cache hit is an Entra network call.
API/Graph fetches reject redirects so access tokens cannot be redirected to a
different endpoint. Form values (including budget limit, price, record ID, model, tenant, principal ID,
team ID and cost center), identity/account/roles, Graph profile names/photos, searches,
headers, authorization, URLs/queries, bodies, response data, exception messages
and stacks are **never event properties**. Invalid or oversized measurements
are omitted. A final SDK initializer reconstructs allowed event data and strips
SDK user/session/location context; only validated manual dependency trace
context survives. All automatic page, dependency,
exception and diagnostic telemetry is dropped. Automatic fetch/XHR, route,
exception/rejection collection, request/response headers, cookies, SDK storage,
SDK diagnostics and remote CDN configuration are disabled. Global errors report
only fixed categories and never inspect the error or rejection reason.

Telemetry setup/export failures are best-effort and never fail saves, reads or
MSAL operations. Initial config failure cannot be sent from a fresh browser
because there is no validated destination yet; use the Node/hosting outcome.
StrictMode development can repeat lifecycle events. Page events count rendered
navigation, not audit-authoritative writes. Configuration events and API events
are separate results, not additive mutation counts. Loading fictional backend
records does not bypass authentication or change the portal's telemetry handling.

## Validation

Run the lint, type-check, Vitest and build commands in [setup](#overview).
Live verification uses normal Entra sign-in with appropriately assigned
Admin/Reader roles; unit tests do not establish interactive sign-in or deployed
API access. Follow the
[operational acceptance checklist](../docs/operations.md#acceptance-checklist)
for end-to-end checks.

Microsoft publishes the UI and identity libraries. Vite, React's community test
tools, ESLint and the TypeScript ESLint integration are development tooling;
there is no suitable Microsoft-maintained Fluent-compatible test runner or Vite
replacement required by this project.

Return to the [README](../README.md) for the documentation map and
[code guide](../docs/code-guide.md#portal-code-map) for source navigation.
A narrow `@typescript-eslint/typescript-estree` override selects patched
`minimatch` v11 until upstream updates its v10 dependency range. Keep this
override until `npm audit` is clean without it.
