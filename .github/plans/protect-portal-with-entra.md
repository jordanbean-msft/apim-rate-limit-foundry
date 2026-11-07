# Protect the portal with Microsoft Entra ID

- [x] Inspect existing browser/API authentication and native secretless sign-in.
  Reuse the Terraform-created single-tenant SPA registration; do not duplicate
  app registrations or change API permissions. Add a web callback and trust only
  the dedicated web managed identity. Government uses sovereign issuer/audience.
- [x] Update `infra/modules/identity`, `infra/modules/hosting` and root wiring.
  Native Easy Auth must protect the website/config/assets, use federation instead
  of a secret and preserve the existing user-token API authorization boundary.
- [x] Update web runtime/MSAL logout and focused frontend/Terraform regressions.
  Clear both sessions in Azure; preserve local-development and demo behavior.
- [x] Update deployment, portal and identity documentation; run affected suites,
  lint/types/build, recursive Terraform format/validate and pre-commit hooks.
  All 27 Terraform plans and 85 frontend tests passed; lint/types/build, formatting,
  Terraform zero-warning validation and hooks/TFLint passed. Web package succeeded.
- [x] Validate/review the existing Commercial demo's scoped azd preview, provision
  and deploy the portal. Preserve existing P1v2 plans/main Function Always On drift.
  Applied one new federated credential and two in-place updates; web package
  deployed. Native login uses `code id_token`; a separately reviewed/applied
  registration-only update enabled ID tokens, leaving implicit access tokens off.
  Restored web Always On=false; main remains false, stream true, both plans P1v2.
- [x] Verify actual registration/callback/federation, anonymous website redirect,
  protected config/assets, and Function rejection of unauthenticated/forged callers.
  Verify authorized portal API access and existing APIM managed-identity inference.
  Record interactive sign-in, Government or private-network verification limits.
  Actual Graph registration/federation matches Terraform with zero client secrets.
  Browser website/config/assets redirect to the correct tenant/client/callback;
  non-browser requests return 401. Both Functions reject anonymous calls, forged
  platform headers and invalid tokens. Delegated portal API and real APIM
  reserve/inference/actual settlement succeed. Evidence:
  `.azure/publicdemo/portal-auth-live-results.json` and protected deployment logs.
  Full interactive browser/MFA sign-in, Government and private networking remain
  unverified; no authentication bypass or synthetic browser session was added.
