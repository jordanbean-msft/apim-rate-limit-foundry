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

| Setting           | Meaning                                                                                           |
| ----------------- | ------------------------------------------------------------------------------------------------- |
| `AZURE_CLOUD`     | Exactly `commercial` or `government`; no automatic cloud fallback                                 |
| `AZURE_TENANT_ID` | Tenant-specific Entra GUID; `common`/`organizations` are rejected                                 |
| `WEB_CLIENT_ID`   | SPA application registration client GUID                                                          |
| `API_AUDIENCE`    | Backend application ID URI, e.g. `api://<backend-app-id>`                                         |
| `API_SCOPE`       | Full delegated scope under that audience, e.g. `api://<backend-app-id>/access_as_user`            |
| `API_BASE_URL`    | HTTPS collection root without trailing slash: `https://<apim>/portal` or `https://<function>/api` |
| `PORT`            | Optional Node listening port; default `8080`                                                      |
| `WEB_DEMO_MODE`   | Optional; defaults off. Only exact `true` enables an in-memory local demo                         |

`/config.json` is generated at server startup from these **public** settings;
it contains no client secret, Function key, APIM subscription key, or connection
string. The browser build is cloud-independent. Only the two supported Microsoft
authorities are accepted. API URLs may use HTTP only for loopback development.
All browser requests use access tokens for `API_SCOPE`, never ID tokens.

Register the deployed portal **origin** (and `http://localhost:5173` or
`http://127.0.0.1:5173` for development) as SPA redirect URIs.
Grant consent for the delegated API scope and assign API app roles:
`RateLimit.Admin` or `RateLimit.Reader`. The UI reads role hints from the API
access token; the backend must independently validate audience, tenant and roles,
and scope consumer reads by tenant and principal. `RateLimit.Gateway` alone
cannot open portal data. Configure API/APIM CORS for exact portal origins,
`Authorization` and `Content-Type`, and GET/PUT/DELETE/OPTIONS.
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
and should return `204`. Writes are admin-only and the API remains authoritative.

- Policy: `{id,name,service,model,tenant_id?,principal_id,limit,period,metric,enabled,priority}`.
  `service`: `foundry|document-intelligence|language`; `model` and `principal_id`
  can be `*`; tenant scope defaults to `*`. `limit` is a positive safe integer.
  Cost limits use **integer microUSD** (1 USD = 1,000,000 microUSD).
  Other metrics: `tokens|requests|pages|text_records`, restricted by service.
  Periods: UTC calendar `minute|hour|day|month`, not sliding windows.
- Price: `{id,service,model,version,input_per_million,output_per_million,cached_input_per_million,per_page,per_text_record,per_request}`.
  All six rate fields are non-negative **decimal USD strings**, not JavaScript
  floats or microUSD. Token fields are per million tokens, others per single unit.
- Assignment: `{id,tenant_id,principal_id,policy_ids:string[]}`.
- Usage/audit/reconciliation:
  `{id,tenant_id,principal_id,kind,timestamp,data:{...}}`.
  Usage `data` contains `{request:{service,model,usage:{input_tokens,output_tokens,cached_input_tokens,pages,text_records,requests},streaming},debits:[{policy_id,metric,amount,limit,reset_at,key}],remaining,estimated,status}`.
  Audit `data` includes `{action,collection?,record_id?,actor_id?,...}`.
  Reconciliation `data` includes `{status,reservation_id,estimated,usage?}`.
  Each event is inspectable as JSON for additional server fields.

The browser never sends an arbitrary principal query. Readers see only the
collections the API authorizes. GET failures remain visible and retryable; failed
saves retain the editor and delete failures retain the confirmation.

## Accounting and operational limits

Input, output and cached input have separate rates. Cached tokens replace
uncached input charges after trusted settlement; admission assumes no cache hit.
Streaming reserves estimated input plus maximum output. Unknown actual usage
retains the conservative debit; expiry is not a refund.

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

Microsoft publishes the UI and identity libraries. Vite, React's community test
tools, ESLint and the TypeScript ESLint integration are development tooling;
there is no suitable Microsoft-maintained Fluent-compatible test runner or Vite
replacement required by this project.
