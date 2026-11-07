# Migrate the APIM backend to Microsoft Foundry

- [x] Inspect deployed resources, Terraform state and official account-upgrade guidance.
  Reuse the existing `publicdemo` Commercial environment, East US 2 and resource
  group. Preserve existing plan/Always On drift and all unrelated resources.
- [x] Choose a non-destructive account migration and document the approved scope
  in `.azure/deployment-plan.md`. Never apply an account replacement implicitly.
  Microsoft documents an in-place upgrade with AzureRM >= 4.56.0; the existing
  lock is latest stable 5.13.0. Preserve the existing account and model deployment.
- [x] Update Terraform, endpoint selection, preflight, application integration,
  examples and architecture/docs for the Foundry `AIServices` resource.
  Keep existing routes, identity boundaries, price pins and accounting behavior.
- [x] Run all Python, gateway, frontend and Terraform tests, lint/types/builds,
  and deployment validation; record skipped external integrations explicitly.
  175 Python passed / eight optional emulator skips; 33 gateway, 82 frontend
  and 25 Terraform tests passed; all lint/types/format/build/hooks passed.
  Actual scoped preview: four additions, 12 updates, zero deletions; account
  upgrade is in place, with no planned hosting/site-config or role changes.
- [x] Apply only reviewed infrastructure/application changes through azd.
  Provision succeeded: four additions, 12 updates, zero deletions. API, stream
  and portal deployed successfully. Both plans remain P1v2. Despite no planned
  site-config change, the provider reset main Function Always On to true;
  restored its original false value and verified stream remains true.
- [x] Verify actual Foundry account kind and live APIM Chat/Responses inference,
  streaming, trusted settlement and shared service routes; record unavailable
  providers or connectivity/authorization blockers without claiming success.
  Live account is AIServices/Succeeded with project management and its dedicated
  identity; original account ID and model/version/capacity are unchanged.
  Chat/Responses and both streams returned 200; unknown aliases 400 before
  reservation; caller-scoped cost policy 429, then removed. Language and Document
  submit/poll succeeded. Actual ledger costs match original pinned prices,
  including 5,376 provider-confirmed cached tokens. Baseline prices/policies
  remain unchanged. Live portal config/assets and resource-scoped inference roles
  verified; architecture diagram inspected and embedded assets validated.
  Evidence: ignored `foundry-*` JSON proofs and deployment logs under
  `.azure/publicdemo/`. Anthropic, Government deployment,
  private networking and interactive browser sign-in remain unverified.
