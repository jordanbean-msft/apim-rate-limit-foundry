# Show the Azure dashboard inside the portal

- [x] Backend/main agent: add an Admin-only `/api/dashboard?period=1h|24h|7d`
  endpoint. Read the deployed Azure dashboard's tile metadata and exact KQL;
  query only its configured workspace using managed identity. Return its 13
  charts and nine grids with bounded results and explicit per-tile errors.
  Readers must not gain access to workspace-wide data. Mock external calls.
- [x] Infrastructure/main agent: grant the Function identity read-only access to
  the dashboard and workspace, pass fixed resource IDs/cloud endpoints through
  centralized settings, and expose the authenticated APIM GET operation.
  Preserve hosting, models, keys and unrelated drift. Validate Terraform.
- [x] Frontend/isolated agent (`web/**`): add an administrator Dashboard page
  using Microsoft Fluent charts, time-range/refresh controls and accessible
  detail tables; render the native tile titles/axes without duplicating KQL.
  Maintain square edges/one font, explicit empty/error/truncated states and
  labelled fixture mode. Extend the same-origin proxy allowlist and tests.
- [x] Main agent: integrate the isolated frontend patch, update operator docs
  and VS Code automation only where commands change, and run combined Python,
  APIM, frontend, lint/type/build and Terraform checks.
  Validated 191 Python/37 APIM/107 frontend/33 Terraform tests and all hooks.
  Existing VS Code commands/tasks cover the feature; no new entry point.
  Local Chromium snapshot rendered all 22 tiles at desktop/mobile; Fluent emits
  one non-fatal internal React key warning. No native browser auth was simulated.
- [x] Main agent: provision only reviewed dashboard RBAC/settings/API changes,
  deploy the API and portal, verify all 22 live tiles and native authorization,
  and record remaining interactive browser/sovereign limitations.
  Deployed API/stream/web and final contract correction. Live Function identity
  returned all 22 tiles (21 populated, zero errors) for every supported period.
  Verified scoped Reader/Log Analytics Reader roles, native token/key rejection,
  forbidden query inputs, six existing model aliases and protected portal 302.
  No ledger/policy/price reset or unrelated drift applied. Interactive Entra
  browser authentication and Government/private networking remain unverified.

Contract: `GET /dashboard?period=24h` returns `DashboardTile[]`. Each tile has
`id`, `title`, `chart` (`Line`, `Pie`, `Column`, `StackedColumn`, or `""` for
tables), `x_axis`, `y_axis`, `split_by` (column names or null), `columns`
(`{name,type}[]`), `rows` (JSON scalar arrays), `error` (safe message or null)
and `truncated` (boolean). There is no client-supplied KQL, workspace or URL.
The deployment's dashboard remains the single source of chart/query definitions.
