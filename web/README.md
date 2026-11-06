# AI Budget Control portal

Accessible React + TypeScript + Fluent UI v9 portal, hosted by a framework-free Node
server. Use Node **22.13+ LTS** or **24 LTS**.

```bash
npm ci
npm run lint
npm run typecheck
npm run test -- --run
npm run build
npm start
```

`npm start` serves `dist/` on `0.0.0.0:${PORT:-8080}`. Deploy `dist/`,
`server/`, and `package.json` together with `web/` as the working directory.
The production server needs only Node's built-in modules, not `node_modules`.
`npm run dev` uses Vite on loopback; the same runtime configuration is served
by its `/config.json` development middleware. Create `web/.env.local` for Vite,
or export settings in the shell for both servers. Never place secrets in Vite variables.

## Required production runtime settings

| Setting                                 | Meaning                                                                                                                                                          |
| --------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `AZURE_CLOUD`                           | Exactly `commercial` or `government`; no automatic cloud fallback                                                                                                |
| `AZURE_TENANT_ID`                       | Tenant-specific Entra GUID; `common`/`organizations` are rejected                                                                                                |
| `WEB_CLIENT_ID`                         | SPA application registration client GUID                                                                                                                         |
| `API_AUDIENCE`                          | Backend application ID URI, e.g. `api://<backend-app-id>`                                                                                                        |
| `API_SCOPE`                             | Full delegated scope under that audience, e.g. `api://<backend-app-id>/access_as_user`                                                                           |
| `API_BASE_URL`                          | HTTPS collection root without trailing slash: `https://<apim>/portal` or `https://<function>/api`                                                                |
| `PORT`                                  | Optional Node listening port; default `8080`                                                                                                                     |
| `WEB_DEMO_MODE`                         | Optional; defaults off. Only exact `true` enables an in-memory local demo                                                                                        |
| `APPLICATIONINSIGHTS_CONNECTION_STRING` | Optional workspace-based Application Insights connection string with explicit cloud-specific `IngestionEndpoint`; enables privacy-filtered browser custom events |

`/config.json` is generated at server startup from these **public** settings;
it contains no client secret, Function key or APIM subscription key. When configured,
its optional `appInsights` field contains **public instrumentation routing only**:
`{connectionString, ingestionOrigin}`. See the privacy contract below.
The browser build is cloud-independent. Only the two supported Microsoft
authorities are accepted. API URLs may use HTTP only for loopback development.
All browser requests use access tokens for `API_SCOPE`, never ID tokens.

Register the deployed portal **origin** (and `http://localhost:5173` or
`http://127.0.0.1:5173` for development) as SPA redirect URIs.
Grant consent for the delegated API scope and assign API app roles:
`RateLimit.Admin` or `RateLimit.Reader`. The UI reads role hints from the API
access token; the backend must independently validate audience, tenant and roles,
and scope consumer reads by tenant and principal. `RateLimit.Gateway` alone
cannot open portal data. Configure API/APIM CORS for exact portal origins,
`Authorization`, `Content-Type` and `X-Correlation-ID`, and GET/PUT/DELETE/OPTIONS.
Expose `X-Correlation-ID` if operators need to inspect backend correlation responses.
Do not enable App Service middleware that redirects anonymous static/config
requests to a different login flow; MSAL owns browser authentication.

For intentional local demonstration:

```bash
WEB_DEMO_MODE=true npm run dev
# or after npm run build:
WEB_DEMO_MODE=true npm start
```

The prominent demo banner remains visible on every screen. Fixtures are not live
Azure prices and changes disappear on reload. Auth/config/API failure **never**
silently switches to demo mode. Never enable the demo flag on a shared production
deployment.

## API contract

GET `/policies`, `/prices`, `/assignments`, `/usage`, `/audit`, and
`/reconciliation` return JSON **arrays**, not `{items: [...]}` wrappers.
PUT `/{collection}/{id}` accepts the full typed record; DELETE removes it
and supports either `200` with `{deleted:id}` JSON or `204` with no body.
Writes are admin-only and the API remains authoritative.

- Policy: `{id,name,service,model,tenant_id?,principal_id,limit,period,metric,enabled,priority}`.
  `service`: `foundry|document-intelligence|language`; `model` and `principal_id`
  can be `*`; tenant scope defaults to `*`. `limit` is a positive safe integer.
  Cost limits use **integer microUSD** (1 USD = 1,000,000 microUSD).
  Other metrics: `tokens|requests|pages|text_records`, restricted by service.
  Periods: UTC calendar `minute|hour|day|month`, not sliding windows.
- Price: `{id,service,model,version,input_per_million,output_per_million,cached_input_per_million,cache_write_5m_per_million?,cache_write_1h_per_million?,per_page,per_text_record,per_request}`.
  The original six rate fields remain required non-negative **decimal USD strings**.
  Both cache-write fields are optional/nullable decimal strings; blank editor fields
  save `null`, never an assumed zero. Legacy OpenAI records need no new rates.
  Anthropic requires explicitly configured uncached/read/write-5m/write-1h prices:
  unknown potentially billable rates fail closed, even if a request expects no writes.
  Token rates are USD per million tokens; others are USD per single unit, not microUSD.
  The editor uses the existing non-negative decimal validator (up to 12 decimal places)
  for nonblank write rates. Explicit `"0"` remains distinct from unknown `null`.
- Assignment: `{id,tenant_id,principal_id,policy_ids:string[]}`.
- Usage/audit/reconciliation:
  `{id,tenant_id,principal_id,kind,timestamp,data:{...}}`.
  Usage `data` contains `{request:{service,model,api_protocol?,usage:{input_tokens,output_tokens,cached_input_tokens,cache_write_input_tokens_5m,cache_write_input_tokens_1h,pages,text_records,requests},streaming},debits:[{policy_id,metric,amount,limit,reset_at,key}],remaining,estimated,status}`.
  Additive `data.api_protocol`, `data.cost_micro_usd`, `data.usage`,
  `data.cached_input_reported`, and `data.cache_write_input_reported` are supported.
  Settled `data.usage` takes precedence over admission estimates in `request.usage`.
  A single reported event cost is shown independently of per-policy impacts:
  matching multiple budgets does **not** make their cost debits additive.
  Audit `data` includes `{action,collection?,record_id?,actor_id?,...}`.
  Reconciliation `data` includes `{status,reservation_id,estimated,usage?}`.
  Each event is inspectable as JSON for additional server fields.

The browser never sends an arbitrary principal query. Readers see only the
collections the API authorizes. GET failures remain visible and retryable; failed
saves retain the editor and delete failures retain the confirmation.

## Accounting and operational limits

All three LLM protocols use service `foundry`: `openai-chat` (Chat Completions),
`openai-responses` (Responses), and `anthropic-messages` (Messages). Omitted protocol
means Chat only for legacy Foundry records; Document Intelligence and Language
do not acquire a chat label. Unknown protocols are shown as unrecognized, not
silently treated as Chat. The demo contains legacy chat plus representative
usage-only provider metadata for all three formats; it contains no prompts.

Normalized `input_tokens` is **total input**, including cache reads and both
write subsets. `cached_input_tokens` means cache reads; write subsets are
`cache_write_input_tokens_5m` and `cache_write_input_tokens_1h`. Their sum must
not exceed total input (validated by the backend). Do not add subsets to total
again. The browser displays server-normalized counters rather than attempting
to normalize provider payloads or reprice consumption.

Chat reports prompt/completion tokens and cached prompt details; Responses
reports input/output tokens and cached input details. Anthropic raw `input_tokens`
excludes reads/writes: the backend adds cache reads and the validated creation
TTL breakdown to obtain normalized total. Read pricing is the cache-read discount;
write pricing is the full rate **including** the surcharge, replacing uncached
pricing for that subset rather than adding a second charge to total input.

Conservative admission uses the highest applicable known input/cache rate plus
maximum output, not an assumed discounted cache hit. Anthropic requires an
operator-verified context input ceiling, not a universal byte-to-token bound.
Missing or ambiguous usage retains conservative confidence and does not imply
zero cached tokens. API `estimated`/`status` flags drive confidence badges; missing
write counters display “Not reported” for Anthropic, never an invented zero.
Streaming remains conservative until trusted reconciliation; expiry is not a refund.
The portal does not execute inference, buffer streams, certify provider/model
availability in Government, or configure gateway routes and backend capabilities.

The overview shows configured policy limits and last-decision remaining
snapshots, **not live balances or invoices**. Returned event counts are not
deduplicated reservation balances. Refresh is manual; there is no websocket,
automatic polling, pagination or price-feed integration. The API must bound
collection sizes and enforce validation, reference integrity and authorization.
Editing old price versions is possible for administrators; prefer new ID/version
records, and enforce immutability of referenced prices server-side if required.
Multiple catalog versions for one service/model require the gateway to send an
explicit `price_version` in reservations; ambiguous selection fails closed.
No live Azure deployment or cross-cloud tenant consent is verified by unit tests.

## Privacy-safe observability

The production Node server still has **no runtime npm dependencies**. Keep the
App Service native Application Insights Node agent as the server HTTP exporter
(`ApplicationInsightsAgent_EXTENSION_VERSION=~3` and
`APPLICATIONINSIGHTS_CONNECTION_STRING` for the workspace-based component).
The Microsoft `@microsoft/applicationinsights-web` SDK is bundled by Vite, not
loaded from a CDN and not required by the static server.

Server code writes one JSON `portal_request` outcome per request, including
HEAD, rejected requests and premature response closure. Fields are `timestamp`,
`event`, generated UUID-v4 `correlationId`, allowlisted `method` (`OTHER` for
unknown methods), safe `route` (`runtime_config|page|asset|other`), numeric
`status` (`0` when aborted), `durationMs`, `outcome`
(`success|failure|aborted`) and fixed `errorCategory`
(`none|method_not_allowed|invalid_path|not_found|serve_error|connection_closed`).
The server generates `X-Correlation-ID`; caller-supplied IDs are ignored.
`portal_started` includes port, cloud, demoMode and browserTelemetry.
`portal_server_error` includes only `startup_configuration|listen_error`.
These **console logs are not custom App Insights traces**: enable App Service
application/console logging and route `AppServiceConsoleLogs` to the intended
Log Analytics workspace using hosting diagnostic settings. Keep
`AppServiceHTTPLogs` separately if desired. The native HTTP agent has its own
request schema and collection/redaction settings, independent of this code.

The optional connection string must include a GUID `InstrumentationKey` and
explicit HTTPS root `IngestionEndpoint`. Commercial permits
`applicationinsights.azure.com` and its subdomains; Government permits
`applicationinsights.us` / `applicationinsights.azure.us` and their subdomains.
Credentials, non-default ports, query, fragment and non-root paths are rejected.
Missing, invalid or wrong-cloud optional telemetry **disables browser export**
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

Only manually sanitized **custom events** are exported to App Insights
`customEvents` / workspace `AppEvents`; API dependency counts are represented
by `portal_api` events, not automatic `AppDependencies` URL records:

| Event                  | Custom dimensions                                                                                                                                                      | Custom measurements                             |
| ---------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------- |
| `portal_page`          | allowlisted `page`, `outcome=success`                                                                                                                                  | none                                            |
| `portal_api`           | `collection`, `method=GET/PUT/DELETE`, generated UUID-v4 `correlationId`, `outcome=success/failure`, `errorCategory=none/authentication/http/network/invalid_response` | `status`, `durationMs`, `requestCount=0/1`      |
| `portal_configuration` | editable `collection`, `action=create/update/delete`, `outcome=success/failure/cancelled`, `errorCategory=none/validation/api`                                         | none                                            |
| `portal_refresh`       | `outcome=success/partial_failure`                                                                                                                                      | `collectionCount`, `failureCount`, `durationMs` |
| `portal_bootstrap`     | `action=configuration/authentication/sign_in/sign_out`, `outcome=success/failure`                                                                                      | none                                            |
| `portal_browser_error` | `errorCategory=script/unhandled_rejection/render_error`                                                                                                                | none                                            |

`requestCount` is zero when token acquisition fails before an HTTP attempt and
one once fetch is attempted. If optional UUID generation fails, the API still
works and omits the correlation header/property rather than inventing an ID.

Pages and collections come from fixed UI/API enums, never browser locations.
The API sends its generated `X-Correlation-ID` to the backend so operators can
join an API outcome to backend logs. It does not reuse server static-request IDs
or arbitrary backend/header IDs. Form values (including policy limit, price,
record ID, model, tenant and principal), identity/account/roles, searches,
headers, authorization, URLs/queries, bodies, response data, exception messages
and stacks are **never event properties**. Invalid or oversized measurements
are omitted. A final SDK initializer reconstructs allowed event data and strips
SDK user/session/operation/location context; all automatic page, dependency,
exception and diagnostic telemetry is dropped. Automatic fetch/XHR, route,
exception/rejection collection, request/response headers, cookies, SDK storage,
SDK diagnostics and remote CDN configuration are disabled. Global errors report
only fixed categories and never inspect the error or rejection reason.

Telemetry setup/export failures are best-effort and never fail saves, reads or
MSAL operations. Initial config failure cannot be sent from a fresh browser
because there is no validated destination yet; use the Node/hosting outcome.
StrictMode development can repeat lifecycle events. Page events count rendered
navigation, not audit-authoritative writes. Configuration events and API events
are separate results, not additive mutation counts. Demo mode remains explicitly
opt-in; if telemetry is configured for a demo, its navigation/configuration/refresh
events are exported, but the in-memory fixture API produces no HTTP API events.

## Authenticated GUI verification (operator harness only)

Use an isolated browser context and a separate ephemeral bundle of the **same
installed MSAL browser version**. Never add an auth bypass, test token endpoint,
fake JWT or token fixture to production code. The portal uses `sessionStorage`,
tenant-specific authority, `knownAuthorities` for its cloud, the configured
`WEB_CLIENT_ID`, origin redirect URI and delegated `API_SCOPE` from `/config.json`.
An existing approved operator delegated CLI token may be loaded using MSAL's
supported `getTokenCache().loadExternalTokens` API, then the real portal reloaded
in the **same tab/origin**:

1. Construct `PublicClientApplication` with the same configuration as
   `src/auth.ts`; call `await instance.initialize()`.
2. Use a genuine `AccountInfo` for the operator (`homeAccountId`, `environment`,
   `tenantId`, `localAccountId`, `username` from its actual account/client-info
   data). Do not manufacture an ID token; `id_token` is optional when an account
   is supplied. `client_info` may be supplied from the genuine token response.
3. Call `await instance.getTokenCache().loadExternalTokens(
{account, scopes: [config.apiScope], authority},
{access_token, token_type: 'Bearer', scope: config.apiScope,
expires_in: remainingLifetimeSeconds, client_info},
{expiresOn: actualExpiryEpochSeconds, extendedExpiresOn: actualExpiryEpochSeconds})`.
   MSAL requires nonzero `expires_in` even with `expiresOn`, and either response
   scope or request scopes. Only cache scopes the real token actually grants;
   verify tenant, API audience, delegated scope, expiry and Reader/Admin role
   against the real token/backend. Backend restrictions on the token's client
   (`azp`) still apply: caching does not turn a CLI-issued token into a SPA-issued one.
4. Optionally `instance.setActiveAccount(account)`, then reload the production
   portal without clearing sessionStorage. The portal takes `accounts[0]`,
   requests `API_SCOPE` using `acquireTokenSilent`, reads roles from the real
   access token, and sends that access token to the unchanged authenticated API.
   Account cache ownership and credential indexes are maintained by MSAL; do
   not handwrite storage keys. With no refresh token, expiration requires a new
   valid token or interactive auth. Discovery calls may still contact the
   tenant-specific authority. MFA is not performed by this harness.
5. Disclose that verification used an existing approved delegated session, not
   an interactive MFA sign-in. Disable screenshots/traces/network dumps that
   could capture tokens or operator PII; destroy the browser context afterward.

Prefer role/label selectors, not generated Fluent IDs or CSS class hashes.
Navigation: `getByRole('button', {name: 'Budget policies', exact: true})`.
Wait for `Refresh` to be enabled before editing; click `Create policy`.
In `getByRole('dialog', {name: 'Create policy'})` (or `Edit policy`), use
`getByLabel(/^ID/)`, `/^Name/`, `/^Service/`, `/^Model or deployment/`,
`/^Tenant scope/`, `/^Principal scope/`, `/^Accounting unit/`,
`/^Limit \(integer microUSD\)/` or `/^Limit \(whole units\)/`,
`/^UTC period/`, `/^Priority/`, and `getByRole('checkbox', {name: 'Policy enabled'})`.
Use `selectOption` values `foundry|document-intelligence|language`,
`cost|tokens|requests|pages|text_records` (service-dependent), and
`minute|hour|day|month`. Submit using `getByRole('button', {name: 'Save changes'})`.
Existing row buttons use exact names `Edit <record-id>` / `Delete <record-id>`;
deletion requires `Confirm delete` in `Delete this record?`.
Wait for the dialog to close and “Changes saved” / “Record deleted”; failures
keep the dialog open and expose an alert. `Search records` and `Filter by service`
are local filters only. Do not infer a live backend write from an optimistic UI.

Microsoft publishes the UI and identity libraries. Vite, React's community test
tools, ESLint and the TypeScript ESLint integration are development tooling;
there is no suitable Microsoft-maintained Fluent-compatible test runner or Vite
replacement required by this project.

Vitest uses the patched stable v4 line; it no longer depends on `tinypool`.
A narrow `@typescript-eslint/typescript-estree` override selects patched
`minimatch` v11 until upstream updates its v10 dependency range. Keep this
override until `npm audit` is clean without it.
